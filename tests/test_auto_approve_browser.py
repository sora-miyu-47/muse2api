"""审批卡看守的浏览器集成测试：独立临时 Chromium + 本地合成 DOM，不访问 Muse、不读取账号。

合成卡片按 muse.ai 前端 i18n 文案搭建（Allow / Allow once / Deny / Always allow / Show approval details），
验证真实的 DOM 扫描 JS、按钮定位与鼠标点击：

    python tests/test_auto_approve_browser.py            # 需要 chromium / google-chrome（或 MUSE2API_CHROMIUM）
"""
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import engine as engine_mod  # noqa: E402
from approval import ApprovalAudit, ApprovalGuard, ApprovalSettings  # noqa: E402

DOM = r"""
<style>button{margin:4px;padding:6px 10px} .card{border:1px solid #ccc;margin:10px;padding:8px;width:600px}</style>
<div id="chat">
  <div class="agent-bubble">I'll check which user runs the shell first.</div>
  <div class="card" data-testid="hatch-inline-approval-card" id="c1">
    <div><span>Muse needs approval</span></div>
    <div>Run command</div>
    <pre><code>whoami</code></pre>
    <div class="actions">
      <button data-id="c1-deny">Deny</button>
      <button data-id="c1-always">Always allow</button>
      <button data-id="c1-allow">Allow</button>
      <button aria-label="More allow options" data-id="c1-more">▾</button>
    </div>
  </div>
  <div class="card" data-testid="hatch-inline-approval-card" id="c2">
    <div>小明需要审核</div><div>命令</div><pre>uv sync</pre>
    <div><button data-id="c2-task">此任务内允许</button><button data-id="c2-once">允许一次</button><button data-id="c2-deny">拒绝</button></div>
  </div>
  <div class="card" data-testid="hatch-inline-approval-card" id="c3">
    <div>Muse needs approval</div><pre>rm -rf ~/project</pre>
    <div><button data-id="c3-allow">Allow</button><button data-id="c3-deny">Deny</button></div>
  </div>
  <div class="card" data-testid="hatch-inline-approval-card" id="c4">
    <div>Muse needs approval</div><div>Deploy the site to production</div>
    <div><button data-id="c4-allow">Allow</button><button data-id="c4-deny">Deny</button></div>
  </div>
  <div class="card" data-testid="hatch-inline-approval-card" id="c5">
    <div>Muse needs approval</div>
    <div id="c5-details" style="display:none"><pre>git clone https://github.com/astral-sh/uv</pre></div>
    <div><button data-id="c5-show" onclick="document.getElementById('c5-details').style.display='block';this.textContent='Hide approval details'">Show approval details</button>
      <button data-id="c5-allow">Allow</button><button data-id="c5-deny">Deny</button></div>
  </div>
  <div class="card" id="u1">
    <div>Muse needs approval</div><pre>pwd</pre>
    <div><button data-id="u1-allow">Allow</button><button data-id="u1-deny">Deny</button></div>
  </div>
</div>
<textarea placeholder="Message"></textarea>
"""
# 审查中复现过的 DOM 攻击：aria-label 冒充单次放行、详情展开失败、标记卡外面藏危险命令
ATTACKS = r"""
<div id="chat">
  <div data-testid="hatch-inline-approval-card" id="a1"><div>Muse needs approval</div><pre>whoami</pre>
    <div><button data-id="a1-trick" aria-label="Allow pending approval">Always allow for this project</button>
      <button data-id="a1-deny">Deny</button></div></div>
  <div data-testid="hatch-inline-approval-card" id="a2"><div>Muse needs approval</div><div>whoami</div>
    <div style="display:none"><pre>rm -rf ~</pre></div>
    <div><button data-id="a2-show" disabled>Show approval details</button>
      <button data-id="a2-allow">Allow</button><button data-id="a2-deny">Deny</button></div></div>
  <div><pre>rm -rf ~/project</pre>
    <div><div>whoami</div><button data-id="a3-allow">Allow</button><button data-id="a3-deny">Deny</button></div></div>
</div>
<textarea></textarea>
"""
# 按 muse-auto-approve 记录的线上 DOM 标记搭的卡片：标记卡、批次卡、连接器动作卡、检阅横幅
MARKED = r"""
<div id="chat">
  <div data-hatch-background-approval-surface="true" data-testid="hatch-inline-approval-card">
    2 tasks need review <button data-id="bg-review">Review</button></div>
  <div data-testid="hatch-inline-approval-card" data-hatch-approval-surface="inline" id="m1">
    <div><span>Allow Ren to access </span><a href="#">github.com</a><span>?</span></div>
    <div>This task comes from Daily build.</div>
    <div><button data-id="m1-deny">Deny</button><button data-id="m1-allow" data-hatch-approval-primary-action="true">Allow</button>
      <button aria-haspopup="menu" aria-label="More allow options" data-id="m1-more">▾</button></div>
  </div>
  <div data-testid="hatch-inline-approval-card" id="m2">
    <div>Send email?</div><div>To: bob@example.com</div>
    <div><button data-id="m2-deny">Don't send</button><button data-id="m2-send" data-hatch-approval-primary-action="true">Send</button></div>
  </div>
  <div data-testid="hatch-inline-approval-card" id="m3">
    <div>Ren needs approval to continue.</div>
    <div role="button" aria-expanded="true" id="m3a"><span title="x">Terminal</span><pre>whoami</pre>
      <button data-id="m3a-deny">Deny</button><button data-id="m3a-allow" data-hatch-approval-primary-action="true">Allow</button></div>
    <div role="button" aria-expanded="true" id="m3b"><span title="x">Terminal</span><pre>ls -la</pre>
      <button data-id="m3b-deny">Deny</button><button data-id="m3b-allow" data-hatch-approval-primary-action="true">Allow</button></div>
    <div><button data-id="m3-allall">Allow all once</button><button data-id="m3-denyall">Deny all</button></div>
  </div>
</div>
<textarea></textarea>
"""
# 线上实测卡片的 DOM 复刻（2026-11-25，alice 账号 git clone 触发的外联卡）
REAL = r"""
<div class="mb-2"><div role="group" data-testid="hatch-inline-approval-card" data-hatch-approval-surface="chat">
  <div><div><span></span><div><div><div><span><span>Allow Muse to share information with github.com?</span></span></div></div>
    <p>"Always allow" covers github.com and all its subdomains, not just this page.</p></div></div></div>
  <div>
    <div role="button" aria-expanded="false" data-id="%(p)s-toggle"
         onclick="var o=this.getAttribute('aria-expanded')==='true';this.setAttribute('aria-expanded',o?'false':'true');
                  this.nextElementSibling.style.display=o?'none':'block';this.querySelector('.lbl').textContent=o?'See details':'Hide details';">
      <div><p>Your assistant wants to download the uv-pre-commit repository and check the installed uv tool version. This task comes from the side chat “Check uv version and Git clone”.</p></div>
      <span class="lbl">See details</span><span></span></div>
    <div style="display:none"><div><dl>
      <div><dt>Host</dt><dd>github.com</dd></div><div><dt>Grants</dt><dd>github.com and all subdomains</dd></div>
      <div><dt>Method</dt><dd>%(method)s</dd></div><div><dt>Path</dt><dd>%(path)s</dd></div>
      <div><dt>Policy</dt><dd>tool.exec</dd></div></dl></div></div>
  </div>
  <div><div><div><button data-hatch-approval-primary-action="true" data-id="%(p)s-once"><span>Allow once</span></button></div>
    <div><button data-id="%(p)s-always"><span>Always allow this site</span></button></div>
    <div><button data-id="%(p)s-deny"><span>Deny</span></button></div></div></div>
</div></div>
<textarea></textarea>
"""
DIALOG = r"""<div role="dialog"><div>Muse needs approval</div><pre>rm -rf /</pre>
  <button data-id="d-allow">Allow</button><button data-id="d-deny">Deny</button></div>
<div id="chat"></div><textarea></textarea>"""
TRACK = r"""window.__clicks=[];if(!window.__tracked){window.__tracked=1;document.addEventListener('click',function(e){
  var b=e.target.closest('button,[role="button"]'); if(b&&b.getAttribute('data-id')) window.__clicks.push(b.getAttribute('data-id'));},true);}"""


def main():
    chromium = os.environ.get("MUSE2API_CHROMIUM") or next(
        (shutil.which(n) for n in ("chromium", "google-chrome", "chromium-browser") if shutil.which(n)), None)
    if not chromium:
        raise SystemExit("Chromium required; set MUSE2API_CHROMIUM to its executable.")
    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="muse-approve-browser-", dir=Path.home(), ignore_cleanup_errors=True) as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cfg = SimpleNamespace(chromium=chromium, cdp_port=port, home_dir=str(Path.home()), extra_path="",
                              profile_dir=tmp + "/profile", data_dir=tmp, download_dir=tmp + "/downloads",
                              auto_approve=True, auto_approve_dry_run="", auto_approve_accounts="")
        Path(cfg.download_dir).mkdir()
        settings = ApprovalSettings(tmp + "/auto-approve.json", cfg, lambda a: "小明")
        audit = ApprovalAudit(tmp + "/audit.jsonl")
        guard = ApprovalGuard(settings, audit, lambda a: "小明")
        eng = engine_mod.MuseEngine(cfg)
        eng.approval_guard = guard
        try:
            eng.start()
            page = eng._open_page()
            eng.page = page
            eng.current_acc_id = "acc-bob"

            def load(html):
                page.js("document.body.innerHTML=%s;%s" % (json.dumps(html), TRACK))

            def clicks():
                return page.js("JSON.stringify(window.__clicks)")

            # 1. 演练模式（管理页默认）：只记日志，任何按钮都不点（包括「显示详情」）
            load(DOM)
            cards = guard.scan(eng)
            check(len(cards) == 6, f"扫描到 6 张卡片（实际 {len(cards)}）")
            check(sum(1 for c in cards if c["marked"]) == 5, "5 张带 Muse 标记，1 张不带")
            c1 = next(c for c in cards if "whoami" in c["text"])
            check("I'll check" not in c1["text"] and "Message" not in c1["text"], "卡片文字不含聊天气泡 / 输入框内容")
            check({b["kind"] for b in c1["buttons"]} == {"deny", "broad", "allow"}, f"按钮分类正确 {c1['buttons']}")
            check(guard.tick(eng, force=True) is True, "演练模式 tick 报告有卡片在等")
            guard.tick(eng, force=True)
            check(json.loads(clicks()) == ["c5-show"], f"演练模式只展开详情，不点放行 / 拒绝（{clicks()}）")
            rows = audit.query()
            by_text = {r["text"].splitlines()[-1]: r for r in rows if r["text"]}
            check(by_text.get("whoami", {}).get("action") == "would-click", "演练：whoami 记为 would-click")
            check(any(r["action"] == "would-click" and "git clone" in r["text"] for r in rows),
                  "演练：展开详情后读到 git clone，记为 would-click")
            check(any(r["category"] == "unmarked" and r["text"] == "" for r in rows), "无标记的块不记文字")

            # 2. 真批
            settings.update(dry_run=False)
            load(DOM)
            guard._expanded.clear()
            guard._logged.clear()
            for _ in range(6):   # 一轮只点一次（展开详情也算一次）
                guard.tick(eng, force=True)
            got = json.loads(clicks())
            check(sorted(got) == ["c1-allow", "c2-once", "c5-allow", "c5-show"], f"白名单卡片各点一次单次放行 {got}")
            check(not ({"c1-always", "c1-more", "c2-task"} & set(got)), "从不点扩大授权按钮")
            check(not ({"c3-allow", "c3-deny", "c4-allow", "c4-deny", "u1-allow"} & set(got)),
                  "黑名单 / 待定 / 无标记卡片一个按钮都不点")
            live = [r for r in audit.query() if r["mode"] == "live"]
            check(any(r["action"] == "clicked" and r["button"] == "允许一次" for r in live), "审计记下点击的按钮")
            check(any(r["tier"] == "block" and "rm -rf" in r["text"] for r in live), "黑名单卡片记为 block")
            check(any(r["tier"] == "unknown" and "Deploy" in r["text"] for r in live), "待定卡片记为 unknown")

            # 2a. 审查复现过的攻击
            load(ATTACKS)
            guard._expanded.clear()
            guard._logged.clear()
            kinds = {b["label"]: b["kind"] for c in guard.scan(eng) for b in c["buttons"]}
            check(kinds.get("Always allow for this project") not in ("allow", "allow_once", "allow_aria"),
                  f"可见文字优先于 aria-label，不当单次放行 {kinds}")
            for _ in range(4):
                guard.tick(eng, force=True)
            got = json.loads(clicks())
            check(not ({"a1-trick", "a2-allow", "a3-allow"} & set(got)), f"攻击用例一个放行都不点 {got}")

            # 2b. Muse 线上标记：标记卡、批次卡一轮一项、连接器动作卡不点、检阅横幅不当卡片
            load(MARKED)
            guard._logged.clear()
            cards = guard.scan(eng)
            texts = [c["text"] for c in cards]
            check(len(cards) == 4 and all(c["marked"] for c in cards), f"标记卡识别为 4 张（批次卡拆项）: {texts}")
            check(not any("need review" in t for t in texts), "检阅横幅不当卡片")
            guard.tick(eng, force=True)
            first = json.loads(clicks())
            check(len(first) == 1, f"一轮只点一张卡 {first}")
            for _ in range(3):
                guard.tick(eng, force=True)
            got = json.loads(clicks())
            check(sorted(got) == ["m1-allow", "m3a-allow", "m3b-allow"], f"网站卡与批次卡各项逐个放行 {got}")
            check(not ({"m2-send", "m2-deny", "m1-more", "m3-allall", "bg-review"} & set(got)),
                  "连接器动作 / 扩权 / 全部允许 / 检阅横幅都不点")
            m2 = [r for r in audit.query() if "Send email" in r["text"]]
            check(bool(m2) and m2[0]["tier"] != "allow", f"发邮件卡不放行 {m2[:1]}")

            # 2c. 线上实测卡片复刻：演练只展开详情；真批点 Allow once；push 不点
            settings.update(dry_run=True)
            load(REAL % {"p": "real", "method": "POST", "path": "/astral-sh/uv-pre-commit/git-upload-pack"})
            guard._logged.clear(); guard._expanded.clear()
            for _ in range(3):
                guard.tick(eng, force=True)
            check(json.loads(clicks()) == ["real-toggle"], f"实测卡（演练）：只展开详情 {clicks()}")
            r = audit.query()[0]
            check((r["tier"], r["action"], r["button"]) == ("allow", "would-click", "Allow once")
                  and "Path: /astral-sh/uv-pre-commit/git-upload-pack" in r["text"], f"实测卡（演练）记录 {r}")
            settings.update(dry_run=False)
            load(REAL % {"p": "real", "method": "POST", "path": "/astral-sh/uv-pre-commit/git-upload-pack"})
            guard._logged.clear(); guard._expanded.clear()
            for _ in range(3):
                guard.tick(eng, force=True)
            check(json.loads(clicks()) == ["real-toggle", "real-once"], f"实测卡（真批）：展开后点 Allow once {clicks()}")
            load(REAL % {"p": "real", "method": "POST", "path": "/astral-sh/uv-pre-commit/git-receive-pack"})
            guard._logged.clear(); guard._expanded.clear()
            for _ in range(3):
                guard.tick(eng, force=True)
            check(json.loads(clicks()) == ["real-toggle"], f"实测卡 push：不点 {clicks()}")
            check(audit.query()[0]["tier"] == "block", "实测卡 push 记为 block")

            # 2d. 标题相同、详情不同的两张卡：先 push（拦截）后 clone（放行）——只能点 clone 那张
            load(REAL % {"p": "push", "method": "POST", "path": "/a/b/git-receive-pack"}
                 + REAL % {"p": "pull", "method": "POST", "path": "/a/b/git-upload-pack"})
            guard._logged.clear(); guard._expanded.clear(); guard._clicks.clear()
            for _ in range(5):
                guard.tick(eng, force=True)
            got = json.loads(clicks())
            check("pull-once" in got and "push-once" not in got, f"同标题不同详情：只点放行那张 {got}")
            # 两张完全相同的卡：认不出是哪张，一张都不点
            def expanded(**kw):
                return (REAL % kw).replace('aria-expanded="false"', 'aria-expanded="true"').replace(
                    '<div style="display:none">', '<div>').replace('See details', 'Hide details')
            load(expanded(p="t1", method="GET", path="/a/b/info/refs") + expanded(p="t2", method="GET", path="/a/b/info/refs"))
            guard._logged.clear(); guard._expanded.clear(); guard._clicks.clear()
            for _ in range(6):
                guard.tick(eng, force=True)
            got = json.loads(clicks())
            check(not ({"t1-once", "t2-once"} & set(got)), f"两张已展开且一模一样的卡（无法区分）不点放行 {got}")

            # 3. 按账号关闭：完全不扫描、不点击
            settings.update(accounts={"acc-bob": False})
            load(DOM)
            check(guard.tick(eng, force=True) is False and json.loads(clicks()) == [], "按账号关闭后不处理")
            settings.update(accounts={"acc-bob": True})

            # 4. reset_thread 关弹窗：审批弹窗不再被「点第一个按钮」
            load(DIALOG)
            page.js("history.replaceState(null,'','/thread/new')")
            eng.approval_guard = None
            orig_send = page.send
            page.send = lambda m, p=None, timeout=None: None if m == "Page.navigate" else orig_send(m, p, timeout)
            orig_wait = eng._wait_ws_ready
            eng._wait_ws_ready = lambda *a, **k: True
            try:
                eng.reset_thread(for_chat=True)
                check(json.loads(clicks()) == [], f"reset_thread 不点审批弹窗按钮（{clicks()}）")
                load('<div role="dialog"><button data-id="x-close">Close</button></div><textarea></textarea>')
                eng.reset_thread(for_chat=True)
                check(json.loads(clicks()) == ["x-close"], f"普通弹窗仍照旧关闭（{clicks()}）")
            finally:
                page.send, eng._wait_ws_ready = orig_send, orig_wait
        finally:
            eng.stop()
    if failures:
        raise SystemExit(f"{len(failures)} 项失败")
    print("AUTO_APPROVE_BROWSER all passed")


if __name__ == "__main__":
    main()
