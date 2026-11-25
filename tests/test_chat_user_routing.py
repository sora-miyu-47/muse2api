"""Per-`user` chat routing, persona injection and muse thread continuity.

No live accounts, network or browser: a fake engine stands in for muse.ai and
records which account, thread and prompt each request used.

    python tests/test_chat_user_routing.py
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
HOME = tempfile.TemporaryDirectory(prefix="m2a-chat-users-")
os.environ.update(MUSE2API_HOME=HOME.name, MUSE2API_PROFILE_ROOT=HOME.name,
                  MUSE2API_KEY="fixture-only")

import app  # noqa: E402
import chat_sessions  # noqa: E402
from chat_sessions import ChatUserRegistry, ChatUserConflict, ChatUserUnavailable  # noqa: E402
from engine import MuseEngine, MuseGenerationError, MuseThreadUnavailable  # noqa: E402
from test_media_delete import Client  # noqa: E402

AUTH = {"authorization": "Bearer fixture-only"}
PERSONA_A = "你是 Alice 的私人助理，名叫小A。"
PERSONA_B = "You are Bob's pirate assistant."


class FakeMuse:
    """Stands in for engine.chat_stream: one thread list per account."""

    def __init__(self):
        self.calls = []
        self.threads = {}            # path -> account id
        self.lost = set()            # thread paths that no longer open
        self.lock = threading.Lock()
        self.counter = 0

    def chat_stream(self, cookies, prompt, expires=None, timeout=None, account_id=None,
                    stop_event=None, thread_path=None, new_thread=False, on_thread=None):
        call = {"account": account_id, "prompt": prompt, "thread": thread_path,
                "new_thread": new_thread, "has_on_thread": on_thread is not None}
        with self.lock:
            self.calls.append(call)
        if thread_path:
            if thread_path in self.lost:
                raise MuseThreadUnavailable("gone")
            assert self.threads[thread_path] == account_id, "thread opened on a foreign account"
            path = thread_path
        else:
            with self.lock:
                self.counter += 1
                path = f"/thread/t{self.counter:04d}"
                self.threads[path] = account_id
        if on_thread:
            on_thread(path)
        yield "re"
        yield "ply"


def run(coro):
    return asyncio.run(coro)


def put(client, path, data):
    return client.request("PUT", path, body=json.dumps(data).encode(),
                          headers={"content-type": "application/json"})


def chat(client, body):
    return client.post("/v1/chat/completions", json_data=body)


def fresh_state(accounts=("acc-a", "acc-b", "acc-c")):
    """Reset the shared app state to a known set of accounts and no users."""
    app.store.accounts[:] = [
        {"id": aid, "label": aid.upper(), "enabled": True, "ok": True,
         "cookies": {"hatch_sess": aid}, "cookies_exp": {}, "use_count": i}
        for i, aid in enumerate(accounts)]
    if os.path.exists(app.CFG.chat_users_file):
        os.unlink(app.CFG.chat_users_file)
    app.CHAT_USERS = ChatUserRegistry(app.CFG.chat_users_file)
    app.ACCOUNT_POOL.busy_accounts.clear()


def patched(fake):
    return [
        patch("store._write", lambda *a, **k: None),
        patch.object(app.engine, "chat_stream", side_effect=fake.chat_stream),
        patch.object(app.engine, "start", return_value=None),
        patch.object(app.engine, "close_current_page", return_value=None),
        patch.object(app.engine, "reset_thread", return_value=None),
        patch.object(app, "_renew_and_persist", side_effect=lambda aid, **_: app.store.get_account(aid)),
        patch.object(app, "_sync_cookies", return_value=None),
    ]


class Patched:
    def __init__(self, fake):
        self.items = patched(fake)

    def __enter__(self):
        for p in self.items:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self.items):
            p.stop()


# ---------------------------------------------------------------- registry
def test_registry_binding_and_persistence():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "chat-users.json")
        reg = ChatUserRegistry(path)
        accounts = [{"id": "a1", "use_count": 5}, {"id": "a2", "use_count": 1},
                    {"id": "a3", "use_count": 0, "ok": False}]
        alice = reg.bind("alice", accounts)
        assert alice["account_id"] == "a2" and alice["auto_bound"], alice   # healthy, least used
        assert reg.bind("alice", accounts)["account_id"] == "a2"            # sticky
        assert reg.bind("bob", accounts)["account_id"] == "a1"              # exclusive: not a2
        assert reg.bind("carol", accounts)["account_id"] == "a3"            # unhealthy only as last resort
        try:
            reg.bind("dave", accounts)
            raise AssertionError("no free account must fail")
        except ChatUserUnavailable:
            pass
        assert reg.bind("dave", accounts, exclusive=False)["account_id"] in {"a1", "a2"}
        try:
            reg.upsert("erin", account_id="a1")
            raise AssertionError("exclusive conflict expected")
        except ChatUserConflict:
            pass
        try:
            reg.bind("zed", accounts, auto_bind=False)
            raise AssertionError("auto-bind disabled must fail")
        except chat_sessions.ChatUserNotFound:
            pass

        # thread lifecycle
        assert not reg.save_thread("alice", "a2", "/thread/new", new=True)
        assert reg.save_thread("alice", "a2", "/thread/abc123", new=True, persona_sha="p1")
        t = reg.thread_for("alice", "a2")
        assert t["path"] == "/thread/abc123" and t["persona_injected"] and t["persona_sha256"] == "p1"
        assert reg.thread_for("alice", "a1") is None                        # foreign account
        reg.complete_turn("alice", "a2", "/thread/abc123")
        assert reg.thread_for("alice", "a2")["turns"] == 1
        reg.upsert("alice", persona="new persona")
        assert reg.thread_for("alice", "a2"), "persona edit keeps the running thread"
        reg.upsert("alice", account_id="a9")
        assert reg.get("alice")["thread"] is None, "account change must forget the thread"

        # persisted and reloaded; hand edits are picked up
        again = ChatUserRegistry(path)
        assert again.get("alice")["account_id"] == "a9"
        data = json.loads(Path(path).read_text())
        data["users"]["frank"] = {"account_id": "a7", "persona": "hand written"}
        Path(path).write_text(json.dumps(data))
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
        assert again.get("frank")["persona"] == "hand written"

        # a broken hand edit keeps the last good state and is backed up, not overwritten
        Path(path).write_text("{broken")
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 20_000_000))
        assert again.get("frank")["account_id"] == "a7"
        again.reset_thread("frank")
        assert any(n.startswith("chat-users.json.invalid-") for n in os.listdir(d))
        assert json.loads(Path(path).read_text())["users"]["frank"]["account_id"] == "a7"

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "chat-users.json")
        reg = ChatUserRegistry(path)
        reg.upsert("alice", account_id="a1", persona="P")
        reg.save_thread("alice", "a1", "/thread/abc123", new=True)
        # a rejected patch changes nothing, in memory or on disk
        try:
            reg.upsert("alice", account_id="a2", persona="x" * (chat_sessions.MAX_PERSONA_LEN + 1))
            raise AssertionError("oversized persona must fail")
        except chat_sessions.ChatUserError:
            pass
        assert reg.get("alice")["account_id"] == "a1" and reg.thread_for("alice", "a1")
        # a reset while a request is in flight wins over that request's thread report
        rev = reg.revision("alice")
        reg.reset_thread("alice")
        assert not reg.save_thread("alice", "a1", "/thread/abc123", new=True, revision=rev)
        assert reg.thread_for("alice", "a1") is None
        assert reg.save_thread("alice", "a1", "/thread/def456", new=True, revision=reg.revision("alice"))
        # bad field types are cleaned instead of crashing the load
        Path(path).write_text(json.dumps({"users": {"bob": {"account_id": "a3", "created_at": "bad",
                                                           "thread": {"path": 5}}}}))
        bob = ChatUserRegistry(path).get("bob")
        assert bob["account_id"] == "a3" and bob["created_at"] is None and bob["thread"] is None
        # unreadable file at start: fail closed, never re-bind users or overwrite the file
        Path(path).write_text("{broken")
        cold = ChatUserRegistry(path)
        for action in (lambda: cold.bind("bob", [{"id": "a9"}]),
                       lambda: cold.upsert("bob", persona="x"),
                       lambda: cold.reset_thread("bob")):
            try:
                action()
                raise AssertionError("unreadable registry must fail closed")
            except ChatUserUnavailable:
                pass
        assert Path(path).read_text() == "{broken"
        client = Client(app.app, AUTH)
        with patch.object(app, "CHAT_USERS", cold):
            assert run(client.post("/admin/chat-users/bob/reset")).status_code == 503
            assert run(client.delete("/admin/chat-users/bob")).status_code == 503
        # non-finite numbers are cleaned too
        Path(path).write_text('{"users": {"bob": {"account_id": "a3", "created_at": 1e309, "revision": 1e309}}}')
        assert ChatUserRegistry(path).get("bob")["created_at"] is None

    for bad in ("x" * 300, "a\nb"):
        try:
            chat_sessions.normalize_user(bad)
            raise AssertionError(bad)
        except chat_sessions.ChatUserError:
            pass
    assert chat_sessions.normalize_user("  ") is None
    assert chat_sessions.normalize_user(" u1 ") == "u1"
    print("PASS: registry binds, keeps, isolates and persists users")


# ---------------------------------------------------------------- prompts
def test_prompt_builders():
    M = app.ChatMessage
    msgs = [M(role="system", content="client rules"), M(role="user", content="hi"),
            M(role="assistant", content="hello"), M(role="user", content="second")]
    opening = app.build_chat_prompt(msgs[:2], persona="PERSONA")
    assert opening.index("PERSONA") < opening.index("client rules") < opening.index("hi"), opening
    assert app.build_chat_prompt(msgs[1:2]) == "hi", "stateless single turn unchanged"
    assert app.build_chat_prompt(msgs) == app.build_chat_prompt(msgs, persona=None)
    assert app.build_followup_prompt(msgs) == "second"
    assert app.build_followup_prompt([M(role="user", content="only")]) == "only"
    tool = [M(role="user", content="q"), M(role="assistant", tool_calls=[{"id": "1"}]),
            M(role="tool", content="42"), M(role="user", content="and?")]
    follow = app.build_followup_prompt(tool)
    assert "42" in follow and "and?" in follow and "q" not in follow.split("42")[0], follow
    assert app.build_followup_prompt(msgs[:3]) == "", "ending with assistant has no new content"
    print("PASS: persona first, follow-ups carry only new turns")


# ---------------------------------------------------------------- endpoint
def test_directed_routing_persona_and_continuity():
    fresh_state()
    fake = FakeMuse()
    client = Client(app.app, AUTH)
    with Patched(fake):
        r = run(put(client, "/admin/chat-users/alice", {"account_id": "acc-c", "persona": PERSONA_A}))
        assert r.status_code == 200, r.body
        r = run(put(client, "/admin/chat-users/bob", {"persona": PERSONA_B}))
        assert r.status_code == 200 and r.json()["account_id"] is None

        hist = [{"role": "system", "content": "client system"},
                {"role": "user", "content": "hello 1"}]
        r = run(chat(client, {"model": "muse-spark", "user": "alice", "messages": hist}))
        assert r.status_code == 200, r.body
        assert r.json()["choices"][0]["message"]["content"] == "reply"
        first = fake.calls[-1]
        assert first["account"] == "acc-c" and first["thread"] is None and first["new_thread"]
        assert PERSONA_A in first["prompt"] and "client system" in first["prompt"]
        assert first["prompt"].index(PERSONA_A) < first["prompt"].index("hello 1")
        thread = app.CHAT_USERS.get("alice")["thread"]
        assert thread["path"] == "/thread/t0001" and thread["persona_injected"] and thread["turns"] == 1

        # follow-up with full history: same account, same thread, only the new turn, no persona
        hist += [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "hello 2"}]
        r = run(chat(client, {"user": "alice", "messages": hist}))
        assert r.status_code == 200, r.body
        second = fake.calls[-1]
        assert second == {"account": "acc-c", "prompt": "hello 2", "thread": "/thread/t0001",
                          "new_thread": False, "has_on_thread": True}, second
        assert app.CHAT_USERS.get("alice")["thread"]["turns"] == 2

        # streaming follow-up behaves the same
        hist += [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "hello 3"}]
        r = run(chat(client, {"user": "alice", "messages": hist, "stream": True}))
        assert r.status_code == 200 and b"data: [DONE]" in r.body, r.body
        assert fake.calls[-1]["prompt"] == "hello 3" and fake.calls[-1]["thread"] == "/thread/t0001"
        assert PERSONA_A not in "".join(c["prompt"] for c in fake.calls[1:])

        # bob: auto-bound to a different account, own persona, own thread
        r = run(chat(client, {"user": "bob", "messages": [{"role": "user", "content": "ahoy"}]}))
        assert r.status_code == 200, r.body
        bob = fake.calls[-1]
        assert bob["account"] not in ("acc-c", None) and bob["thread"] is None
        assert PERSONA_B in bob["prompt"] and PERSONA_A not in bob["prompt"]
        assert app.CHAT_USERS.get("bob")["thread"]["path"] != "/thread/t0001"
        bob_account = bob["account"]
        for _ in range(3):
            run(chat(client, {"user": "bob", "messages": [{"role": "user", "content": "again"}]}))
            assert fake.calls[-1]["account"] == bob_account, "user must stay on its account"

        # new_thread=true starts over and injects the persona once more
        r = run(chat(client, {"user": "alice", "new_thread": True,
                              "messages": [{"role": "user", "content": "fresh start"}]}))
        assert r.status_code == 200
        assert fake.calls[-1]["thread"] is None and PERSONA_A in fake.calls[-1]["prompt"]
        assert app.CHAT_USERS.get("alice")["thread"]["path"] != "/thread/t0001"

        # requests without `user` keep the old stateless, rotating path
        before = len(fake.calls)
        r = run(chat(client, {"messages": [{"role": "user", "content": "anon"}]}))
        assert r.status_code == 200
        anon = fake.calls[before]
        assert anon["thread"] is None and not anon["new_thread"] and not anon["has_on_thread"]
        assert anon["prompt"] == "anon"

        # routing switched off: `user` is ignored and the stateless path is used
        with patch.object(app.CFG, "chat_user_routing", False):
            r = run(chat(client, {"user": "alice", "messages": [{"role": "user", "content": "off"}]}))
        assert r.status_code == 200 and not fake.calls[-1]["has_on_thread"]
        assert fake.calls[-1]["prompt"] == "off" and fake.calls[-1]["thread"] is None

        # last message from assistant: nothing new to send
        r = run(chat(client, {"user": "alice", "messages": hist[:3]}))
        assert r.status_code == 400, r.body
    assert not app.ACCOUNT_POOL.busy_accounts
    print("PASS: directed routing, one-time persona, thread continuity, stateless path intact")


def test_busy_target_queues_then_errors_without_switching():
    fresh_state()
    fake = FakeMuse()
    client = Client(app.app, AUTH)
    with Patched(fake), patch.object(app.CFG, "chat_user_queue_timeout", 1):
        run(put(client, "/admin/chat-users/alice", {"account_id": "acc-a"}))
        app.ACCOUNT_POOL.busy_accounts.add("acc-a")
        t0 = time.monotonic()
        r = run(chat(client, {"user": "alice", "messages": [{"role": "user", "content": "x"}]}))
        assert r.status_code == 429, (r.status_code, r.body)
        assert r.json()["error"]["type"] == "rate_limit_error"
        assert time.monotonic() - t0 >= 0.9
        assert fake.calls == [], "must not run on another account"

        r = run(chat(client, {"user": "alice", "stream": True,
                              "messages": [{"role": "user", "content": "x"}]}))
        assert b'"code": 429' in r.body and fake.calls == [], r.body

        # queued request runs on the same account once it is released
        threading.Timer(0.4, app.ACCOUNT_POOL.release, args=("acc-a",)).start()
        r = run(chat(client, {"user": "alice", "messages": [{"role": "user", "content": "queued"}]}))
        assert r.status_code == 200, r.body
        assert [c["account"] for c in fake.calls] == ["acc-a"]

        # no rebind or delete while the account is leased (a send may be in progress)
        app.ACCOUNT_POOL.busy_accounts.add("acc-a")
        assert run(put(client, "/admin/chat-users/alice", {"account_id": "acc-b"})).status_code == 409
        assert run(put(client, "/admin/chat-users/carl", {"account_id": "acc-a"})).status_code == 409
        assert run(client.delete("/admin/chat-users/alice")).status_code == 409
        assert run(put(client, "/admin/chat-users/alice", {"persona": "ok"})).status_code == 200
        assert app.CHAT_USERS.get("alice")["account_id"] == "acc-a"
        app.ACCOUNT_POOL.release("acc-a")

        # rebound in the window before the lease: the request is cancelled after leasing
        conv = app._UserChat("alice", "acc-a", [app.ChatMessage(role="user", content="late")])
        run(put(client, "/admin/chat-users/alice", {"account_id": "acc-b"}))
        try:
            conv.prepare()
            raise AssertionError("stale binding must be rejected")
        except app.ChatTargetError as exc:
            assert exc.status == 409
        run(put(client, "/admin/chat-users/alice", {"account_id": "acc-a"}))
        result = {}

        # disabled while queued: 503 once the account frees up, never used
        app.ACCOUNT_POOL.busy_accounts.add("acc-a")
        waiter = threading.Thread(target=lambda: result.update(r=run(chat(
            client, {"user": "alice", "messages": [{"role": "user", "content": "late"}]}))))
        waiter.start()
        time.sleep(0.2)
        app.store.get_account("acc-a")["enabled"] = False
        app.ACCOUNT_POOL.release("acc-a")
        waiter.join(5)
        assert result["r"].status_code == 503, result["r"].body
        assert len(fake.calls) == 1 and "acc-a" not in app.ACCOUNT_POOL.busy_accounts
        app.store.get_account("acc-a")["enabled"] = True

        # disabled or deleted target: clear 503, still no other account
        app.store.get_account("acc-a")["enabled"] = False
        r = run(chat(client, {"user": "alice", "messages": [{"role": "user", "content": "y"}]}))
        assert r.status_code == 503 and "disabled" in r.json()["error"]["message"], r.body
        app.store.accounts[:] = [a for a in app.store.accounts if a["id"] != "acc-a"]
        r = run(chat(client, {"user": "alice", "messages": [{"role": "user", "content": "y"}]}))
        assert r.status_code == 503 and "deleted" in r.json()["error"]["message"], r.body
        assert len(fake.calls) == 1
    assert not app.ACCOUNT_POOL.busy_accounts
    print("PASS: busy target queues, then 429; disabled/deleted target 503; never switches")


def test_waiting_for_account_holds_no_generation_slot():
    fresh_state(("acc-a", "acc-b"))
    lock = app.ConcurrencyLock(limit=1)
    stop = threading.Event()
    app.ACCOUNT_POOL.busy_accounts.add("acc-a")
    with patch.object(app, "GEN_LOCK", lock):
        waiter = threading.Thread(target=lambda: app._lease_target("acc-a", 2, stop))
        waiter.start()
        time.sleep(0.2)
        assert lock.acquire(timeout=0.1), "a queued user request must not hold a slot"
        lock.release()
        app.ACCOUNT_POOL.release("acc-a")
        waiter.join(3)
        assert "acc-a" in app.ACCOUNT_POOL.busy_accounts and lock.locked()
        app.ACCOUNT_POOL.release("acc-a")
        lock.release()
    print("PASS: waiting for a busy account does not block other accounts")


def test_lost_thread_recovers_on_same_account():
    fresh_state()
    fake = FakeMuse()
    client = Client(app.app, AUTH)
    with Patched(fake):
        run(put(client, "/admin/chat-users/alice", {"account_id": "acc-b", "persona": PERSONA_A}))
        hist = [{"role": "user", "content": "one"}]
        run(chat(client, {"user": "alice", "messages": hist}))
        fake.lost.add("/thread/t0001")
        hist += [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "two"}]
        r = run(chat(client, {"user": "alice", "messages": hist}))
        assert r.status_code == 200, r.body
        failed, retry = fake.calls[-2:]
        assert failed["thread"] == "/thread/t0001" and failed["prompt"] == "two"
        assert retry["account"] == "acc-b" and retry["thread"] is None
        assert PERSONA_A in retry["prompt"] and "one" in retry["prompt"] and "two" in retry["prompt"]
        assert app.CHAT_USERS.get("alice")["thread"]["path"] == "/thread/t0002"
    print("PASS: a lost thread is rebuilt (persona + transcript) on the same account")


def test_admin_endpoints():
    fresh_state()
    client = Client(app.app, AUTH)
    with patch("store._write", lambda *a, **k: None):
        assert run(put(client, "/admin/chat-users/team%2Fa", {"account_id": "nope"})).status_code == 404
        r = run(put(client, "/admin/chat-users/u1", {"account_id": "acc-a", "persona": "P"}))
        assert r.status_code == 200 and r.json()["account_label"] == "ACC-A"
        r = run(put(client, "/admin/chat-users/u2", {"account_id": "acc-a"}))
        assert r.status_code == 409, r.body
        r = run(put(client, "/admin/chat-users/u1", {"persona": None}))
        assert r.json()["persona"] is None and r.json()["account_id"] == "acc-a", "partial update"
        app.CHAT_USERS.save_thread("u1", "acc-a", "/thread/zzz", new=True)
        assert run(client.post("/admin/chat-users/u1/reset")).status_code == 200
        assert app.CHAT_USERS.get("u1")["thread"] is None
        listing = run(client.get("/admin/chat-users")).json()
        assert [u["user"] for u in listing["data"]] == ["u1"] and listing["exclusive"] is True
        assert run(client.get("/admin/chat-users/u1")).json()["user"] == "u1"
        assert run(client.delete("/admin/chat-users/u1")).status_code == 200
        assert run(client.get("/admin/chat-users/u1")).status_code == 404
        assert run(client.get("/admin/chat-users", headers={"authorization": "Bearer x"})).status_code == 401
    print("PASS: admin endpoints bind, update, reset and delete users")


# ---------------------------------------------------------------- engine
class FakePage:
    def __init__(self, path):
        self.path = path
        self.navigated = []

    def js(self, expr, **_):
        if "location.pathname" in expr:
            return self.path
        return None

    def send(self, method, params=None):
        if method == "Page.navigate":
            self.navigated.append(params["url"])


def make_engine(path, polls, users=0):
    eng = MuseEngine(SimpleNamespace(profile_dir=HOME.name, chat_timeout=5))
    eng._user_count = lambda: users
    page = FakePage(path)
    eng.page = page
    seq = iter(polls)
    last = [polls[-1]]

    def poll():
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]
    eng._poll_chat = poll
    eng._wait_ws_ready = lambda *_a, **_k: True
    return eng, page


def test_engine_thread_open_and_report():
    with patch("time.sleep", lambda *_: None):
        # redirected to /thread/new: the thread is gone
        eng, _ = make_engine("/thread/new", [(0, "", False)])
        try:
            eng.open_thread("/thread/abc123")
            raise AssertionError("redirect must raise")
        except MuseThreadUnavailable:
            pass
        # no history renders: unavailable
        eng, _ = make_engine("/thread/abc123", [(0, "", False)])
        try:
            eng.open_thread("/thread/abc123", load_timeout=0.05)
            raise AssertionError("empty thread must raise")
        except MuseThreadUnavailable:
            pass
        # earlier reply still streaming: wait for idle and stable history first
        polls = [(0, "", False), (2, "old", True), (2, "old more", True)] + [(2, "old more", False)] * 4
        eng, _ = make_engine("/thread/abc123", polls)
        eng.open_thread("/thread/abc123")
        assert eng._poll_chat() == (2, "old more", False)
        # only the accepted user message, no reply text yet: still a valid thread
        eng, _ = make_engine("/thread/abc123", [(0, "", False)], users=1)
        eng.open_thread("/thread/abc123", load_timeout=0.05)
        # reply generating with no agent text yet: wait for it, do not call the thread lost
        eng, _ = make_engine("/thread/abc123", [(0, "", True)] * 3 + [(1, "done", False)] * 4)
        eng.open_thread("/thread/abc123", load_timeout=0.0)
        # still streaming past the idle limit: clear error, not a silent send
        eng, _ = make_engine("/thread/abc123", [(2, "old", True)])
        try:
            eng.open_thread("/thread/abc123", load_timeout=0.01, idle_timeout=0.01)
            raise AssertionError("busy thread must raise")
        except MuseThreadUnavailable:
            raise AssertionError("busy thread is not a lost thread")
        except MuseGenerationError:
            pass

    # chat_stream: thread mode opens the thread and reports its path before the first token
    eng = MuseEngine(SimpleNamespace(profile_dir=HOME.name, chat_timeout=5))
    seen = []
    eng.ensure_page = lambda *a, **k: seen.append(("ensure", k.get("path", "/thread/new")))
    eng.open_thread = lambda p, stop_event=None: seen.append(("open", p))
    eng.reset_thread = lambda for_chat=False: seen.append(("reset", for_chat))
    eng._send = lambda prompt: seen.append(("send", prompt))
    eng.current_thread_path = lambda: "/thread/abc123"
    polls = iter([(1, "old", False), (2, "new", True), (2, "new reply", True)]
                 + [(2, "new reply", False)] * 5)
    eng._poll_chat = lambda: next(polls)
    reported = []
    out = []
    for chunk in eng.chat_stream({}, "hi", thread_path="/thread/abc123", on_thread=reported.append):
        out.append((chunk, list(reported)))
    assert seen[:3] == [("ensure", "/thread/abc123"), ("open", "/thread/abc123"), ("send", "hi")], seen
    assert out[0] == ("new", ["/thread/abc123"]), out
    assert "".join(c for c, _ in out) == "new reply" and reported == ["/thread/abc123"]

    # cancelled while reopening: nothing is sent
    seen.clear()
    stop = threading.Event()
    stop.set()
    assert list(eng.chat_stream({}, "hi", thread_path="/thread/abc123", stop_event=stop)) == []
    assert ("send", "hi") not in seen, seen

    # muse.ai accepted the first message but no reply text came: the thread is still recorded
    seen.clear()
    reported.clear()
    eng._poll_chat = lambda: (0, "", False)
    try:
        list(eng.chat_stream({}, "hi", timeout=1, new_thread=True, on_thread=reported.append))
        raise AssertionError("no reply must time out")
    except MuseGenerationError:
        pass
    assert reported == ["/thread/abc123"], reported

    # stateless and new-thread modes keep using reset_thread
    for kwargs, expected in (({}, True), ({"new_thread": True}, False)):
        seen.clear()
        polls = iter([(0, "", False), (1, "x", False)] + [(1, "x", False)] * 5)
        eng._poll_chat = lambda: next(polls)
        list(eng.chat_stream({}, "hi", **kwargs))
        assert seen[:2] == [("ensure", "/thread/new"), ("reset", expected)], seen
    print("PASS: engine opens stored threads safely and reports new thread paths")


def test_release_lists_include_new_module():
    assert "chat_sessions.py" in (ROOT / "Dockerfile").read_text()
    assert {"chat_sessions.py", "CHAT_USERS.md"} <= set(app.TRACKED_REPO_PATHS)
    print("PASS: Docker image and upgrade lists include the new module")


if __name__ == "__main__":
    test_registry_binding_and_persistence()
    test_prompt_builders()
    test_directed_routing_persona_and_continuity()
    test_busy_target_queues_then_errors_without_switching()
    test_waiting_for_account_holds_no_generation_slot()
    test_lost_thread_recovers_on_same_account()
    test_admin_endpoints()
    test_engine_thread_open_and_report()
    test_release_lists_include_new_module()
    print("ALL CHAT USER ROUTING TESTS PASSED")
