"""盘点 muse.ai 页面上的审批卡（只读，不点击任何按钮）。

在网关所在机器上运行（Docker 部署时在容器里运行）：

    docker exec muse2api python tools/probe_approval_cards.py            # 扫描网关 Chromium 里所有 muse.ai 页面
    docker exec muse2api python tools/probe_approval_cards.py --tree     # 额外打印按钮到卡片之间的祖先结构

输出只包含：卡片文字（已脱敏）、卡片里的按钮文案与类型、卡片容器的 tag/role/data-testid/aria-label，
以及按钮祖先链的 tag/role/data-testid/class 前缀。不读取 cookie，不导出整页 DOM。
把输出贴回来即可核对 approval.py 里的定位方法与 approval_rules.py 的白名单 / 黑名单。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from approval import SCAN_CFG, SCAN_JS  # noqa: E402
from approval_rules import classify, redact  # noqa: E402
from cdp import CDP, http_json  # noqa: E402

TREE_JS = r"""(function(cfg){
  function norm(s){return String(s||'').replace(/[\u2018\u2019\u02bc]/g,"'").replace(/\s+/g,' ').trim().toLowerCase();}
  var L=[].concat(cfg.allow_once,cfg.allow,cfg.allow_aria,cfg.deny,cfg.broad);
  var out=[];
  [].slice.call(document.querySelectorAll('button,[role="button"]')).forEach(function(b){
    var t=norm(b.innerText||b.textContent), a=norm(b.getAttribute('aria-label'));
    if(L.indexOf(t)===-1&&L.indexOf(a)===-1) return;
    var chain=[], el=b;
    for(var i=0;el&&el!==document.body&&i<12;i++,el=el.parentElement){
      chain.push({tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'',
        testid:String(el.getAttribute('data-testid')||'').slice(0,80),
        cls:String(el.className&&el.className.baseVal!==undefined?el.className.baseVal:el.className||'').slice(0,80),
        textLen:String(el.innerText||'').length});
    }
    out.push({text:t.slice(0,60), aria:a.slice(0,80), chain:chain});
  });
  return JSON.stringify(out);
})(%s)"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("MUSE2API_CDP_PORT", "19210")))
    ap.add_argument("--tree", action="store_true", help="打印审批按钮的祖先结构")
    args = ap.parse_args()
    try:
        targets = http_json(f"http://127.0.0.1:{args.port}/json/list")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"连不上 Chromium CDP 端口 {args.port}: {exc}（网关没在跑或端口不同？）")
    pages = [t for t in targets if t.get("type") == "page" and "muse.ai" in (t.get("url") or "")]
    if not pages:
        print("没有打开的 muse.ai 页面（网关空闲时页面可能已关闭；在任务卡住时再运行）")
        return
    cfg = json.dumps(SCAN_CFG, ensure_ascii=False)
    for t in pages:
        path = (t.get("url") or "").split("muse.ai", 1)[-1].split("?", 1)[0]
        page = CDP(t["webSocketDebuggerUrl"], timeout=20)
        try:
            cards = json.loads(page.js(SCAN_JS % (cfg, "null")) or "{}").get("cards") or []
            print(f"=== 页面 {path}：{len(cards)} 张审批卡")
            for i, c in enumerate(cards, 1):
                v = classify(c.get("text") or "", c.get("codes") or [])
                print(f"--- 卡片 {i}  判定={v.tier}/{v.category}  {redact(v.reason, 200)}")
                print("容器:", json.dumps(c.get("shape"), ensure_ascii=False), " 过大:", c.get("too_large"))
                print("按钮:", ", ".join(f"{b['label']}[{b['kind']}]" for b in c.get("buttons") or []))
                print("文字:\n  " + redact(c.get("text") or "").replace("\n", "\n  "))
                if c.get("codes"):
                    print("代码块:", json.dumps([redact(x, 400) for x in c["codes"]], ensure_ascii=False))
            if args.tree:
                for b in json.loads(page.js(TREE_JS % cfg) or "[]"):
                    print(f"按钮 {b['text']!r} aria={b['aria']!r}")
                    for n in b["chain"]:
                        print("   ", json.dumps(n, ensure_ascii=False))
        finally:
            page.close()


if __name__ == "__main__":
    main()
