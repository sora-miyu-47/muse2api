"""Per-`user` chat routing: account binding, persona and muse thread state.

A chat request that carries the OpenAI `user` field is bound to exactly one
account and one muse.ai thread:

* the account comes from the user's entry (set by an admin) or is bound
  automatically on first use and then kept;
* the persona (a custom system prompt) is sent once, in the first message of a
  new thread; follow-up requests continue the stored thread and send only the
  new turns, so the thread history keeps the persona alive.

State lives in a small JSON file (``data/chat-users.json``) that admins may also
edit by hand; the file is re-read when its modification time changes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time

log = logging.getLogger("muse2api")

MAX_USER_LEN = 256
MAX_PERSONA_LEN = 100_000
# muse.ai thread URLs look like /thread/<id>; /thread/new is the empty composer.
THREAD_PATH_RE = re.compile(r"^/thread/(?!new$)[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")

_UNSET = object()


class ChatUserError(Exception):
    """Configuration or routing problem for a `user`; carries an HTTP status."""
    status = 400


class ChatUserNotFound(ChatUserError):
    status = 404


class ChatUserConflict(ChatUserError):
    status = 409


class ChatUserUnavailable(ChatUserError):
    status = 503


def normalize_user(value) -> str | None:
    """Return the cleaned `user` value, or None when the request has none."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChatUserError("user 必须是字符串 (user must be a string)")
    user = value.strip()
    if not user:
        return None
    if len(user) > MAX_USER_LEN:
        raise ChatUserError(f"user 过长，最多 {MAX_USER_LEN} 个字符 (user is too long)")
    if any(ord(ch) < 32 for ch in user):
        raise ChatUserError("user 不能包含控制字符 (user must not contain control characters)")
    return user


def persona_digest(persona: str | None) -> str | None:
    if not persona:
        return None
    return hashlib.sha256(persona.encode("utf-8")).hexdigest()[:16]


def valid_thread_path(path) -> str | None:
    if not isinstance(path, str):
        return None
    path = path.rstrip("/")
    return path if THREAD_PATH_RE.match(path) else None


def _int(value) -> int | None:
    try:
        return int(value) or None
    except (TypeError, ValueError, OverflowError):
        return None


def _clean_thread(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    path = valid_thread_path(raw.get("path"))
    account_id = raw.get("account_id")
    if not path or not isinstance(account_id, str) or not account_id:
        return None
    return {
        "account_id": account_id,
        "path": path,
        "persona_injected": bool(raw.get("persona_injected")),
        "persona_sha256": raw.get("persona_sha256") if isinstance(raw.get("persona_sha256"), str) else None,
        "created_at": _int(raw.get("created_at")),
        "last_used": _int(raw.get("last_used")),
        "turns": max(0, _int(raw.get("turns")) or 0),
    }


def _clean_entry(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    account_id = raw.get("account_id")
    persona = raw.get("persona")
    return {
        "account_id": account_id if isinstance(account_id, str) and account_id else None,
        "persona": persona if isinstance(persona, str) and persona.strip() else None,
        "auto_bound": bool(raw.get("auto_bound")),
        "created_at": _int(raw.get("created_at")),
        "updated_at": _int(raw.get("updated_at")),
        # Bumped whenever the thread is reset; stale in-flight requests cannot restore it.
        "revision": max(0, _int(raw.get("revision")) or 0),
        "thread": _clean_thread(raw.get("thread")),
    }


class ChatUserRegistry:
    """Thread-safe store of `user` -> {account_id, persona, thread}."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._users: dict[str, dict] = {}
        self._mtime: int | None = None
        self._file_invalid = False
        self._loaded = False         # a valid state (or a genuinely absent file) was read
        with self._lock:
            self._reload()

    # ---------- persistence ----------
    def _reload(self):
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except FileNotFoundError:
            self._users, self._mtime, self._file_invalid, self._loaded = {}, None, False, True
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            users = data.get("users") if isinstance(data, dict) else None
            if not isinstance(users, dict):
                raise ValueError("missing 'users' object")
            cleaned = {str(k): _clean_entry(v) for k, v in users.items() if str(k).strip()}
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            # Keep the last good state; never route on a half-edited file.
            if not self._file_invalid:
                log.error("chat-users 配置文件无效，%s: %s",
                          "继续使用上次的有效配置" if self._loaded else "user 定向已暂停，请修正该文件", exc)
            self._file_invalid = True
            self._mtime = mtime
            return
        self._users = cleaned
        self._mtime = mtime
        self._file_invalid = False
        self._loaded = True

    def _require_loaded(self):
        """Never route or write on an unreadable registry with no known-good state."""
        self._reload()
        if not self._loaded:
            raise ChatUserUnavailable(
                f"{os.path.basename(self.path)} 无法解析，user 定向已暂停；请修正该文件 "
                "(chat user registry is unreadable; fix the file)")

    def _write(self):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        if self._file_invalid and os.path.exists(self.path):
            # Keep a hand-edited file we could not parse instead of overwriting it.
            backup = f"{self.path}.invalid-{int(time.time())}"
            os.replace(self.path, backup)
            log.warning("无效的 chat-users 配置已备份到 %s", backup)
        fd, tmp = tempfile.mkstemp(prefix=".chat-users-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "users": self._users}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self._mtime = os.stat(self.path).st_mtime_ns
        self._file_invalid = False

    # ---------- reads ----------
    def get(self, user: str) -> dict | None:
        with self._lock:
            self._reload()
            entry = self._users.get(user)
            return copy.deepcopy(entry) if entry else None

    def list(self) -> dict[str, dict]:
        with self._lock:
            self._reload()
            return copy.deepcopy(self._users)

    def owner_of(self, account_id: str, exclude_user: str | None = None) -> str | None:
        with self._lock:
            self._reload()
            for user, entry in self._users.items():
                if user != exclude_user and entry.get("account_id") == account_id:
                    return user
            return None

    def revision(self, user: str) -> int:
        with self._lock:
            self._reload()
            return (self._users.get(user) or {}).get("revision", 0)

    def thread_for(self, user: str, account_id: str) -> dict | None:
        """The stored thread, only if it belongs to the user's current account."""
        with self._lock:
            self._reload()
            thread = (self._users.get(user) or {}).get("thread")
            if thread and thread.get("account_id") == account_id:
                return copy.deepcopy(thread)
            return None

    # ---------- admin writes ----------
    def upsert(self, user: str, *, account_id=_UNSET, persona=_UNSET,
               exclusive: bool = True) -> dict:
        with self._lock:
            self._require_loaded()
            if persona is not _UNSET and persona is not None and len(persona) > MAX_PERSONA_LEN:
                raise ChatUserError(f"persona 过长，最多 {MAX_PERSONA_LEN} 个字符 (persona is too long)")
            if account_id is not _UNSET:
                account_id = account_id or None
                owner = self.owner_of(account_id, exclude_user=user) if account_id and exclusive else None
                if owner is not None:
                    raise ChatUserConflict(
                        f"账号 {account_id} 已绑定给 user {owner!r}；不同 user 不能共用账号 "
                        "(account is already bound to another user)")
            now = int(time.time())
            entry = copy.deepcopy(self._users.get(user) or _clean_entry({"created_at": now}))
            if account_id is not _UNSET:
                if account_id != entry.get("account_id"):
                    # A muse thread belongs to one account; a new account starts a new thread.
                    self._drop_thread(entry)
                entry["account_id"] = account_id
                entry["auto_bound"] = False
            if persona is not _UNSET:
                entry["persona"] = persona if persona and persona.strip() else None
            entry["updated_at"] = now
            self._users[user] = entry
            self._write()
            return copy.deepcopy(entry)

    @staticmethod
    def _drop_thread(entry: dict) -> None:
        entry["thread"] = None
        entry["revision"] = entry.get("revision", 0) + 1

    def delete(self, user: str) -> bool:
        with self._lock:
            self._require_loaded()
            if user not in self._users:
                return False
            del self._users[user]
            self._write()
            return True

    def reset_thread(self, user: str) -> bool:
        with self._lock:
            self._require_loaded()
            entry = self._users.get(user)
            if not entry:
                return False
            self._drop_thread(entry)
            entry["updated_at"] = int(time.time())
            self._write()
            return True

    # ---------- routing ----------
    def bind(self, user: str, candidates: list[dict], *, auto_bind: bool = True,
             exclusive: bool = True) -> dict:
        """Return the user's entry; bind an account on first use when allowed.

        `candidates` are the usable accounts (enabled, with cookies). A bound
        account is never replaced here, even when it is busy or unhealthy.
        """
        with self._lock:
            self._require_loaded()
            entry = self._users.get(user)
            if entry and entry.get("account_id"):
                return copy.deepcopy(entry)
            if not auto_bind:
                raise ChatUserNotFound(
                    f"user {user!r} 未配置绑定账号，且已关闭自动绑定 (MUSE2API_CHAT_USER_AUTO_BIND=0)")
            bound: dict[str, int] = {}
            for other in self._users.values():
                aid = other.get("account_id")
                if aid:
                    bound[aid] = bound.get(aid, 0) + 1
            pool = [a for a in candidates if not (exclusive and a["id"] in bound)]
            if not pool:
                raise ChatUserUnavailable(
                    "没有可绑定给该 user 的空闲账号（每个账号只能绑定一个 user），"
                    "请导入更多账号或在管理接口中手动绑定 (no free account to bind this user)")
            pool.sort(key=lambda a: (a.get("ok") is False, bound.get(a["id"], 0),
                                     a.get("use_count") or 0, a.get("last_used") or 0.0))
            now = int(time.time())
            entry = entry or _clean_entry({"created_at": now})
            self._drop_thread(entry)
            entry.update(account_id=pool[0]["id"], auto_bound=True, updated_at=now)
            self._users[user] = entry
            self._write()
            log.info("chat user %r 自动绑定到账号 %s", user, entry["account_id"])
            return copy.deepcopy(entry)

    def save_thread(self, user: str, account_id: str, path: str, *, new: bool,
                    persona_sha: str | None = None, revision: int | None = None) -> bool:
        """Record the muse thread a request used. Idempotent for the same path.

        `revision` is the value read when the request was prepared; a reset or
        rebind since then makes the request stale and it is not recorded.
        """
        path = valid_thread_path(path)
        if not path:
            return False
        with self._lock:
            self._reload()
            entry = self._users.get(user)
            if not entry or entry.get("account_id") != account_id:
                return False  # rebound while the request ran; do not resurrect the old thread
            if revision is not None and entry.get("revision", 0) != revision:
                return False  # reset while the request ran
            now = int(time.time())
            thread = entry.get("thread")
            if thread and thread["path"] == path and thread["account_id"] == account_id:
                thread["last_used"] = now
            elif new:
                entry["thread"] = {"account_id": account_id, "path": path,
                                   "persona_injected": bool(persona_sha),
                                   "persona_sha256": persona_sha, "created_at": now,
                                   "last_used": now, "turns": 0}
            elif thread and thread["account_id"] == account_id:
                log.warning("chat user %r 的 muse 线程地址从 %s 变为 %s", user, thread["path"], path)
                thread.update(path=path, last_used=now)
            else:
                return False
            self._write()
            return True

    def complete_turn(self, user: str, account_id: str, path: str | None) -> None:
        with self._lock:
            self._reload()
            thread = (self._users.get(user) or {}).get("thread")
            if thread and thread["account_id"] == account_id and thread["path"] == path:
                thread["turns"] += 1
                thread["last_used"] = int(time.time())
                self._write()

    def clear_thread(self, user: str, path: str | None = None) -> None:
        with self._lock:
            self._reload()
            entry = self._users.get(user)
            if entry and (path is None or (entry.get("thread") or {}).get("path") == path):
                self._drop_thread(entry)
                self._write()
