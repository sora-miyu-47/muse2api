"""审批卡看守：在等待生成期间发现 Muse 的 Allow / Deny 审批卡，按规则处理并写审计日志。

卡片盘点（2026-11-25）
--------------------
来源一：muse.ai 公开前端包里的 i18n 文案（en / zh_CN / zh_TW / zh_HK / ja）。
来源二：已在 muse.ai 线上验证过的开源扩展 muse-auto-approve（MIT，content.js / bridge.js）记录的 DOM 标记。

  * 卡片容器：``[data-testid="hatch-inline-approval-card"]``；带
    ``data-hatch-background-approval-surface="true"`` 的是「N 项工作需要检阅」横幅，不是卡片，跳过。
    ``data-hatch-approval-surface="panel"`` 表示卡片在右侧审批面板里。
  * 批次卡（「{assistant} needs approval to continue」）：每一项是 ``[role="button"][aria-expanded]``，
    标题在 ``span[title]`` 里，各项有自己的按钮；Muse 处理一项时会重画整张卡，所以一轮只点一项。
  * 主操作按钮：``[data-hatch-approval-primary-action="true"]``。连接器动作卡（发邮件等）的主按钮写的是
    动作本身（"Send"），拒绝按钮是「不要＋动作」（"Don't send" / 「不要傳送」/「不发送」）。
    这类卡只会被识别和记录，不会被点：只有文案是单次放行的按钮才会被点。
  * 单次放行按钮（唯一允许自动点的按钮）："Allow" / "Allow once" / aria-label "Allow pending approval"，
    中文「允许」「允许一次」「允許」「允許一次」，日文「許可」「1回だけ許可」等。
  * 扩大授权的按钮（永远不点）："Always allow"、"Allow for this task"、"Allow all once"、"Always allow all"、
    "Allow {domain} always"，以及收起 Always allow 的 "More allow options"（``[aria-haspopup="menu"]``）。
  * 折叠详情按钮："Show approval details" / 「显示批准详情」（只展开，便于读到完整命令）。
  * 线上实测（2026-11-25，alice 账号 git clone）：容器 div[role=group][data-testid=hatch-inline-approval-card]
    [data-hatch-approval-surface=chat]；标题 "Allow Muse to share information with github.com?"；
    说明 '"Always allow" covers github.com and all its subdomains, not just this page.'；
    详情开关 div[role=button][aria-expanded]（助手写的用途说明 + "See details"）；
    详情 dl：Host / Grants / Method(POST) / Path(/owner/repo/git-upload-pack) / Policy(tool.exec)；
    按钮 "Allow once"[primary] / "Always allow this site" / "Deny"。
  * 卡片文字：网站卡标题是「Allow {assistant} to access <域名>?」一类，来源聊天写在
    「This task comes from …」/「此任務來自…」里；其它说明见 approval_rules.HEADER_TEMPLATES。

  没有标记的页面走兜底：从单次放行按钮往上找最近的、同时含拒绝按钮的块。

  在真实页面上核对：tools/probe_approval_cards.py（只输出卡片结构与卡片文字，不读 cookie / 整页 DOM），
  或开演练模式看审计日志里每条记录的 card.shape / card.marked / buttons。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid

from approval_rules import (BLACKLIST, BUILD_RULES, FLOOR, WHITELIST_RULES, Verdict, classify, classify_allow_all,
                            normalize, normalize_trusted_host, redact)

log = logging.getLogger("muse2api")


def _lc(values):
    return sorted({re.sub(r"\s+", " ", normalize(v)).strip().lower() for v in values})


ALLOW_ONCE_LABELS = _lc(["Allow once", "允许一次", "允許一次", "1回だけ許可"])
ALLOW_LABELS = _lc(["Allow", "允许", "允許", "許可", "許可する"])
ALLOW_ARIA_LABELS = _lc(["Allow pending approval", "允许待审核内容", "允許待批准項目", "承認待ちを許可"])
DENY_LABELS = _lc(["Deny", "Don't allow", "Don’t allow", "Decline", "Deny pending approval", "拒绝", "不允许",
                   "拒绝待批准项", "拒絕", "不允許", "拒絕待批准項目", "拒絕待審查的項目", "却下", "却下する",
                   "承認しない", "許可しない", "承認待ちを却下"])
BROAD_LABELS = _lc([
    "Always allow", "Always allow all", "Allow all once", "Deny all", "Allow for this task",
    "Allow all web access for this task", "Allow web access for this task", "Allow for this scheduled task",
    "Allow for this space", "Allow for this artefact", "Allow for this artifact", "Allow for your Feed",
    "Always allow this site", "Allow always for this connector", "Allow options", "More allow options",
    "始终允许", "始终全部允许", "全部允许一次", "全部拒绝", "此任务内允许", "允许这项任务的所有网络访问", "允许这项任务的网络访问",
    "此定时任务内允许", "此空间内允许", "此构件内允许", "总是允许此站点", "始终允许此连接器", "允许选项", "更多允许选项",
    "一律允許", "一律允許全部", "一律全部允許", "全部允許一次", "允許全部一次", "全部拒絕", "允許此任務", "允許此工作",
    "允許此任務的所有網絡存取權限", "允許此任務的網絡存取權限", "允許此任務的所有網路存取權限", "允許此任務的網路存取權限",
    "允許此排定任務", "允許這項排定的任務", "允許這個空間", "允許此空間", "允許此成品", "一律允許此網站", "這個網站一律允許",
    "一律允許此連接器", "許可選項", "允許選項", "更多許可選項", "更多允許選項",
    "常に許可", "すべてを常に許可", "一度だけすべて許可", "すべて却下", "このタスクに許可", "このスペースに対して許可",
    "このスケジュール済みタスクに許可", "このサイトで常に許可", "このコネクターを常に許可", "許可オプション", "その他の許可オプション",
])
# 带占位符的扩权按钮 / 详情按钮，转成正则（JS 端 new RegExp(src, 'i')）
_BROAD_TEMPLATES = ["Allow {x} always", "Allow always for {x}", "Allow all {x} actions", "Allow all {x} methods always",
                    "Allow {x} always for {x}", "始终允许{x}", "允许所有{x}操作", "始终允许所有{x}方法", "一律允許{x}",
                    "允許所有{x}動作", "允許所有{x}方式", "針對{x}一律允許{x}", "{x}を常に許可", "{x}に対して常に許可",
                    "{x}のすべてのアクションを許可", "{x}のすべてのメソッドを常に許可"]
_SHOW_TEMPLATES = ["Show approval details", "Show approval details for {x}", "显示批准详情", "显示{x}的批准详情",
                   "顯示批准詳細資料", "顯示核可詳細資料", "顯示{x}的批准詳細資料", "承認の詳細を表示", "{x}の承認の詳細を表示"]
_HIDE_TEMPLATES = ["Hide approval details", "Hide approval details for {x}", "隐藏批准详情", "隐藏{x}的批准详情",
                   "隱藏批准詳細資料", "隱藏核可詳細資料", "隱藏{x}的批准詳細資料", "承認の詳細を非表示にする",
                   "{x}の承認の詳細を非表示にする"]


def _js_re(tpl: str) -> str:
    parts = normalize(tpl).lower().split("{x}")
    esc = [re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", p) for p in parts]
    return "^" + ".{1,120}".join(esc) + "$"


SCAN_CFG = {
    "allow_once": ALLOW_ONCE_LABELS, "allow": ALLOW_LABELS, "allow_aria": ALLOW_ARIA_LABELS, "deny": DENY_LABELS,
    "broad": BROAD_LABELS, "broad_re": [_js_re(t) for t in _BROAD_TEMPLATES],
    "show_re": [_js_re(t) for t in _SHOW_TEMPLATES], "hide_re": [_js_re(t) for t in _HIDE_TEMPLATES],
    "max_chars": 3000, "max_lines": 40,
    "details_labels": _lc(["See details", "Hide details", "Show details", "查看详情", "隐藏详情", "显示详情",
                           "查看詳細資料", "隱藏詳細資料", "顯示詳細資料", "詳細を表示", "詳細を非表示"]),
    # 以下 DOM 标记来自已在 muse.ai 线上验证过的开源扩展 muse-auto-approve（MIT）
    "card_sel": '[data-testid="hatch-inline-approval-card"]:not([data-hatch-background-approval-surface="true"])',
    "bg_sel": '[data-hatch-background-approval-surface="true"]',
    "primary_sel": '[data-hatch-approval-primary-action="true"]',
    # 连接器动作卡的拒绝按钮写成「不要＋动作」，例如 "Don't send" / 「不要傳送」/「不发送」
    "deny_re": "^(拒絕|拒绝|不允許|不允许|不要|不发|封鎖|阻擋|deny|reject|block|decline|don't |do not )",
}

# 一次 JS 调用完成「扫描全部卡片」或「重新定位某张卡上的某个按钮并返回点击坐标」。
# 只返回卡片自身的文字与结构，不返回整页 DOM / cookie / 其它气泡内容。
SCAN_JS = r"""(function(cfg, want){
  function norm(s){return String(s||'').replace(/[\u200b-\u200f\u2028\u2029\u2060\ufeff]/g,'')
      .replace(/[\u2018\u2019\u02bc]/g,"'").replace(/\s+/g,' ').trim().toLowerCase();}
  function vis(e){ if(!e||!e.getClientRects||!e.getClientRects().length) return false;
      var s=getComputedStyle(e); return s.visibility!=='hidden'&&s.display!=='none'; }
  function rx(list){return list.map(function(s){return new RegExp(s,'i');});}
  var BR=rx(cfg.broad_re), SH=rx(cfg.show_re), HI=rx(cfg.hide_re), DR=new RegExp(cfg.deny_re,'i');
  function anyRe(l,v){for(var i=0;i<l.length;i++){if(l[i].test(v))return true;}return false;}
  function kindOfLabel(v){
    if(!v) return '';
    if(cfg.broad.indexOf(v)!==-1||anyRe(BR,v)) return 'broad';
    if(cfg.allow_once.indexOf(v)!==-1) return 'allow_once';
    if(cfg.allow.indexOf(v)!==-1) return 'allow';
    if(cfg.allow_aria.indexOf(v)!==-1) return 'allow_aria';
    if(cfg.deny.indexOf(v)!==-1) return 'deny';
    if(anyRe(SH,v)) return 'show';
    if(anyRe(HI,v)) return 'hide';
    return 'other';
  }
  // 看得见的文字说了算；只有纯图标按钮（没有可见文字）才看 aria-label。
  // 任一处是扩权文案就当扩权；文字与 aria 冲突时不当放行。
  function kindOf(b){
    var tv=norm(b.innerText||b.textContent), av=norm(b.getAttribute('aria-label'));
    var t=kindOfLabel(tv), a=kindOfLabel(av);
    if(t==='broad'||a==='broad') return 'broad';
    var k=tv?t:a, v=tv||av;
    if(tv&&isAllowKind(t)&&a&&a!=='other'&&!isAllowKind(a)) return 'other';
    if(k&&k!=='other') return k;
    if(v&&DR.test(v)) return 'deny';
    if(b.matches(cfg.primary_sel)) return 'primary';
    return 'other';
  }
  function isAllowKind(k){return k==='allow'||k==='allow_once'||k==='allow_aria';}
  function label(b){return (String(b.innerText||b.textContent||'').trim()||String(b.getAttribute('aria-label')||'').trim()).slice(0,80);}
  // 批次卡的每一项是 [role=button][aria-expanded]，里面还有真按钮：它是容器，不当按钮
  function isContainer(e){return !!e.querySelector('button,[role="button"]');}
  var all=[].slice.call(document.querySelectorAll('button,[role="button"]')).filter(function(b){
    return vis(b)&&!isContainer(b)&&!b.closest(cfg.bg_sel);});
  var kinds=new Map(); all.forEach(function(b){
    var k=kindOf(b);
    // 卡片里的「See details / Hide details」开关：div[role=button][aria-expanded]，只展开说明，不是审批按钮
    if(k==='other'&&b.hasAttribute('aria-expanded')&&!b.matches(cfg.primary_sel)) k='toggle';
    kinds.set(b,k);});
  function isAllow(k){return k==='allow'||k==='allow_once'||k==='allow_aria';}
  function btnsIn(el){return all.filter(function(b){return el.contains(b);});}
  // 卡片自身文字：按块级元素分行，跳过按钮 / 隐藏元素 / 输入框；pre 保留换行
  function ownLines(root){
    var out=[];
    function walk(n){
      if(n.nodeType===3){
        var p=n.parentElement, v=n.nodeValue||'';
        out.push(p&&/^pre/.test(getComputedStyle(p).whiteSpace)?v:v.replace(/\s+/g,' '));
        return;
      }
      if(n.nodeType!==1) return;
      var tag=n.tagName.toUpperCase();
      if(((tag==='BUTTON'||n.getAttribute('role')==='button')&&!isContainer(n))||tag==='SCRIPT'||tag==='STYLE'||tag==='SVG'
         ||tag==='TEXTAREA'||tag==='INPUT'||tag==='NOSCRIPT'||tag==='DL') return;
      var cs=getComputedStyle(n);
      if(cs.display==='none'||cs.visibility==='hidden') return;
      if(tag==='BR'){out.push('\n');return;}
      var block=!/^inline/.test(cs.display)&&cs.display!=='contents';
      if(block) out.push('\n');
      for(var c=n.firstChild;c;c=c.nextSibling) walk(c);
      if(block) out.push('\n');
    }
    for(var c=root.firstChild;c;c=c.nextSibling) walk(c);
    return out.join('').split('\n').map(function(x){return x.replace(/[ \t\u00a0]+/g,' ').trim();}).filter(Boolean);
  }
  var cards=[];
  function add(c){if(cards.indexOf(c)===-1) cards.push(c);}
  // a) Muse 自己的标记：data-testid="hatch-inline-approval-card"（不含「N 项需要检阅」横幅）；
  //    批次卡拆成每一项 [role=button][aria-expanded]（含主操作按钮的那些）
  [].slice.call(document.querySelectorAll(cfg.card_sel)).filter(vis).forEach(function(card){
    var items=[].slice.call(card.querySelectorAll('[role="button"][aria-expanded]')).filter(function(it){
      return isContainer(it)&&btnsIn(it).some(function(x){var k=kinds.get(x);return isAllow(k)||k==='primary';});
    });
    if(items.length) items.forEach(add); else add(card);
  });
  // b) 兜底：标记之外，从单次放行按钮往上找同时含拒绝按钮的块
  all.forEach(function(b){
    if(!isAllow(kinds.get(b))||b.closest(cfg.card_sel)) return;
    var el=b.parentElement, d=0, found=null;
    while(el&&el!==document.body&&d<14){
      if(btnsIn(el).some(function(x){return kinds.get(x)==='deny';})){found=el;break;}
      el=el.parentElement; d++;
    }
    if(!found) return;
    var c=found, g=0;
    while(ownLines(c).length===0&&c.parentElement&&c.parentElement!==document.body&&g<6){
      var p=c.parentElement;
      if(btnsIn(p).filter(function(x){return isAllow(kinds.get(x));}).length>1) break;
      if(p.querySelector('textarea')) break;
      c=p; g++;
    }
    add(c);
  });
  cards=cards.filter(function(c){return !cards.some(function(o){return o!==c&&c.contains(o);});});
  var out=cards.map(function(c){
    var bs=btnsIn(c).map(function(b){return {label:label(b),kind:kinds.get(b)};});
    var full=String(c.innerText||''), lines=ownLines(c);
    var big=full.length>cfg.max_chars||lines.length>cfg.max_lines;
    var codes=[].slice.call(c.querySelectorAll('pre,code,kbd,samp')).filter(function(x){
      return vis(x)&&(x.tagName==='PRE'||!x.closest('pre'))&&!x.closest('button,[role="button"]');
    }).map(function(x){return String(x.innerText||'').trim().slice(0,2000);}).filter(Boolean).slice(0,10);
    var mark=c.closest(cfg.card_sel);
    var collapsed=c.getAttribute('aria-expanded')==='false'||!!c.querySelector('[aria-expanded="false"]');
    // 详情里的结构化字段（Host / Grants / Method / Path / Policy）
    var fields=[].slice.call(c.querySelectorAll('dt')).filter(vis).map(function(dt){
      var dd=dt.nextElementSibling; return [String(dt.innerText||'').trim().slice(0,60),
        dd&&dd.tagName==='DD'?String(dd.innerText||'').trim().slice(0,600):''];}).slice(0,20);
    // 详情开关里的说明（助手自己写的，只参与黑名单扫描与审计，不当作操作）
    var summary=btnsIn(c).filter(function(b){return kinds.get(b)==='toggle';}).map(function(b){
      return String(b.innerText||'').split('\n').map(function(x){return x.trim();}).filter(function(x){
        return x&&cfg.details_labels.indexOf(norm(x))===-1;}).join('\n');}).join('\n').slice(0,1500);
    return {text:big?'':lines.join('\n'), codes:big?[]:codes, buttons:bs.slice(0,12), too_large:big,
      fields:big?[]:fields, summary:big?'':summary,
      marked:!!mark, collapsed:collapsed, surface:mark?String(mark.getAttribute('data-hatch-approval-surface')||'').slice(0,40):'',
      has_show:bs.some(function(x){return x.kind==='show';})||btnsIn(c).some(function(b){
        return kinds.get(b)==='toggle'&&b.getAttribute('aria-expanded')==='false';}),
      shape:{tag:c.tagName.toLowerCase(), role:c.getAttribute('role')||'',
             testid:String(c.getAttribute('data-testid')||'').slice(0,80)}};
  });
  if(!want) return JSON.stringify({cards:out});
  // 点击前按完整快照（文字 + 代码块 + 说明 + 详情字段）重新认卡；同样快照的卡不止一张就不点
  function sig(o){return JSON.stringify([o.text,o.codes,o.summary,o.fields]);}
  var hits=[];
  for(var i=0;i<cards.length;i++){ if(!out[i].too_large&&sig(out[i])===want.sig) hits.push(i); }
  // 展开详情只是看一眼：快照相同时展开第一张即可；放行按钮必须唯一对应一张卡
  var expand=want.kind==='toggle'||want.kind==='show';
  if(!hits.length||(hits.length>1&&!expand)) return null;
  for(var j=0;j<1;j++){
    var i=hits[j];
    var bs=btnsIn(cards[i]).filter(function(x){return kinds.get(x)===want.kind&&label(x)===want.label;});
    if(bs.length!==1) return null;
    var b=bs[0];
    b.scrollIntoView({block:'center',inline:'nearest'});
    var r=b.getBoundingClientRect(), x=Math.round(r.x+r.width/2), y=Math.round(r.y+r.height/2);
    var hit=document.elementFromPoint(x,y);
    if(!hit||!(hit===b||b.contains(hit))) return null;
    return JSON.stringify({x:x,y:y});
  }
  return null;
})(%s, %s)"""

# reset_thread / open_thread 关弹窗前用：弹窗里只要有审批相关按钮就不点（以前会点第一个按钮）
APPROVAL_LIKE_JS = r"""(function(d){
  if(d.querySelector('[data-testid="hatch-inline-approval-card"],[data-hatch-approval-primary-action]')) return true;
  var L=%s;
  function norm(s){return String(s||'').replace(/[\u2018\u2019\u02bc]/g,"'").replace(/\s+/g,' ').trim().toLowerCase();}
  return [].slice.call(d.querySelectorAll('button,[role="button"]')).some(function(b){
    return L.indexOf(norm(b.innerText||b.textContent))!==-1||L.indexOf(norm(b.getAttribute('aria-label')))!==-1;
  });
})""" % json.dumps(sorted(set(ALLOW_ONCE_LABELS + ALLOW_LABELS + ALLOW_ARIA_LABELS + DENY_LABELS + BROAD_LABELS)),
                   ensure_ascii=False)

TIERS = ("allow", "block", "unknown")
_CLICK_PREFERENCE = ("allow_once", "allow", "allow_aria")


def _flag(value) -> bool | None:
    v = str(value if value is not None else "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------
def clean_hosts(values) -> tuple[list[str], list[str]]:
    """规范化信任主机列表，返回 (合格的去重列表, 不合格的原值)。"""
    good, bad = [], []
    for raw in values or []:
        if not str(raw or "").strip():
            continue
        h = normalize_trusted_host(raw)
        if h:
            if h not in good:
                good.append(h)
        else:
            bad.append(str(raw).strip()[:80])
    return good[:50], bad


class ApprovalSettings:
    """开关 = .env（硬闸门）× 管理页（data/auto-approve.json）。

    * 总开关：MUSE2API_AUTO_APPROVE=1 才可能开启；管理页可以随时关掉。
    * 演练模式：MUSE2API_AUTO_APPROVE_DRY_RUN=1 强制演练；=0 或不设时由管理页决定（管理页默认演练）。
    * 按账号：MUSE2API_AUTO_APPROVE_ACCOUNTS 留空 = 全部账号，填 id/备注名（逗号分隔）= 只允许这些；
      管理页可以再逐个关掉（默认开）。
    * 信任主机：MUSE2API_AUTO_APPROVE_HOSTS 与管理页填的主机合在一起；只用于网络访问卡，只放行 GET / HEAD。
    * 全放行模式：管理页打开后，除付款和发送凭据外全部放行；MUSE2API_AUTO_APPROVE_ALL=0 强制关闭。
    任何一侧说「关 / 演练」都按更安全的那一侧执行。
    """

    def __init__(self, path: str, cfg, label_resolver=None):
        self.path = path
        self.cfg = cfg
        self.label_resolver = label_resolver
        self.lock = threading.RLock()
        self.value = {"enabled": True, "dry_run": True, "build": True, "accounts": {}, "trusted_hosts": [],
                      "allow_all": False}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.value.update({k: data[k] for k in ("enabled", "dry_run", "build", "accounts", "allow_all")
                               if k in data})
            self.value["trusted_hosts"] = clean_hosts(data.get("trusted_hosts") or [])[0]
        except (OSError, ValueError, TypeError):
            pass

    # env
    def env_enabled(self) -> bool:
        return bool(getattr(self.cfg, "auto_approve", False))

    def env_dry_run(self) -> bool:
        return _flag(getattr(self.cfg, "auto_approve_dry_run", "")) is True

    def env_build(self) -> bool:
        """MUSE2API_AUTO_APPROVE_BUILD=0 强制关闭构建安装类白名单；默认允许（管理页可再关）。"""
        return _flag(getattr(self.cfg, "auto_approve_build", "")) is not False

    def env_allow_all(self) -> bool:
        """MUSE2API_AUTO_APPROVE_ALL=0 强制关闭全放行模式；留空由管理页决定（默认关）。"""
        return _flag(getattr(self.cfg, "auto_approve_all", "")) is not False

    def env_hosts(self) -> list[str]:
        raw = getattr(self.cfg, "auto_approve_hosts", "") or ""
        return clean_hosts(raw.replace("\n", ",").split(","))[0]

    def trusted_hosts(self) -> list[str]:
        with self.lock:
            return sorted(set(self.env_hosts()) | set(self.value.get("trusted_hosts") or []))

    def env_accounts(self) -> list[str]:
        raw = getattr(self.cfg, "auto_approve_accounts", "") or ""
        return [x.strip() for x in raw.split(",") if x.strip()]

    def _env_account_ok(self, account_id: str | None) -> bool:
        allowed = [x.lower() for x in self.env_accounts()]
        if not allowed or "*" in allowed or "all" in allowed:
            return True
        label = ""
        if self.label_resolver and account_id:
            try:
                label = self.label_resolver(account_id) or ""
            except Exception:  # noqa: BLE001
                label = ""
        return (account_id or "").lower() in allowed or (label.lower() in allowed if label else False)

    def admin(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.value))

    def update(self, enabled=None, dry_run=None, accounts: dict | None = None, build=None,
               trusted_hosts: list | None = None, allow_all=None) -> dict:
        with self.lock:
            if allow_all is not None:
                self.value["allow_all"] = bool(allow_all)
            if trusted_hosts is not None:
                hosts, bad = clean_hosts(trusted_hosts)
                if bad:
                    raise ValueError("主机格式不对（只填主机名或 IP，可带端口，不要协议、路径或通配符）: "
                                     + ", ".join(bad)[:200])
                self.value["trusted_hosts"] = hosts
            if build is not None:
                self.value["build"] = bool(build)
            if enabled is not None:
                self.value["enabled"] = bool(enabled)
            if dry_run is not None:
                self.value["dry_run"] = bool(dry_run)
            if accounts:
                for aid, on in accounts.items():
                    self.value["accounts"][str(aid)] = bool(on)
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".auto-approve-", dir=os.path.dirname(self.path) or ".")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.value, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return self.admin()

    def effective(self, account_id: str | None) -> dict:
        """该账号当前是否看守、是否真点。"""
        with self.lock:
            v = self.value
            if not self.env_enabled():
                return {"enabled": False, "mode": "off", "reason": ".env 未开启 MUSE2API_AUTO_APPROVE"}
            if not v.get("enabled", True):
                return {"enabled": False, "mode": "off", "reason": "管理页总开关已关闭"}
            if not account_id:
                return {"enabled": False, "mode": "off", "reason": "未绑定账号"}
            if not self._env_account_ok(account_id):
                return {"enabled": False, "mode": "off", "reason": "不在 MUSE2API_AUTO_APPROVE_ACCOUNTS 名单内"}
            if not v.get("accounts", {}).get(account_id, True):
                return {"enabled": False, "mode": "off", "reason": "管理页已关闭该账号"}
            dry = self.env_dry_run() or bool(v.get("dry_run", True))
            return {"enabled": True, "mode": "dry-run" if dry else "live",
                    "allow_build": self.env_build() and bool(v.get("build", True)),
                    "trusted_hosts": self.trusted_hosts(),
                    "allow_all": self.env_allow_all() and bool(v.get("allow_all", False)),
                    "reason": ".env 强制演练" if self.env_dry_run() else ("管理页演练模式" if dry else "")}

    def view(self, accounts: list[dict] | None = None) -> dict:
        return {
            "env": {"enabled": self.env_enabled(), "dry_run_forced": self.env_dry_run(), "build": self.env_build(),
                    "accounts": self.env_accounts(), "hosts": self.env_hosts(), "allow_all": self.env_allow_all()},
            "admin": self.admin(),
            "accounts": [dict(id=a.get("id"), label=a.get("label") or "", admin_enabled=self.admin()["accounts"].get(
                a.get("id"), True), **self.effective(a.get("id"))) for a in (accounts or [])],
            "rules": {"whitelist": [{"id": i, "desc": d, "build": i in BUILD_RULES} for i, d in WHITELIST_RULES],
                      "blacklist": [{"id": i, "desc": d} for i, d, _ in BLACKLIST],
                      "floor": [{"id": i, "desc": d} for i, d, _ in FLOOR]},
        }


# ---------------------------------------------------------------------------
# 审计日志（JSONL，只记卡片描述文本与判定结果；文本先脱敏）
# ---------------------------------------------------------------------------
class ApprovalAudit:
    FIELDS = ("time", "account_id", "account_label", "tier", "category", "mode", "action", "button", "attempt",
              "reason", "text")

    def __init__(self, path: str, max_bytes: int = 5 * 1024 * 1024):
        self.path = path
        self.max_bytes = max_bytes
        self.lock = threading.Lock()

    def append(self, entry: dict) -> dict:
        e = {"id": uuid.uuid4().hex[:12], "ts": round(time.time(), 3)}
        e["time"] = time.strftime("%Y-%m-%d %H:%M:%S%z", time.localtime(e["ts"]))
        e.update(entry)
        line = json.dumps(e, ensure_ascii=False)
        with self.lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            try:
                if os.path.getsize(self.path) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")
            except OSError:
                pass
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return e

    def _read_all(self) -> list[dict]:
        out = []
        with self.lock:
            for p in (self.path + ".1", self.path):
                try:
                    with open(p, encoding="utf-8") as f:
                        for ln in f:
                            try:
                                out.append(json.loads(ln))
                            except ValueError:
                                continue
                except OSError:
                    continue
        return out

    def query(self, account: str | None = None, tier: str | None = None, limit: int | None = 200) -> list[dict]:
        rows = self._read_all()
        if account:
            rows = [r for r in rows if r.get("account_id") == account]
        if tier:
            rows = [r for r in rows if r.get("tier") == tier]
        rows.reverse()
        return rows[:limit] if limit else rows

    def export(self, account=None, tier=None, fmt: str = "csv") -> tuple[bytes, str, str]:
        rows = self.query(account, tier, limit=None)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if fmt == "jsonl":
            body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
            return body, "application/x-ndjson", f"auto-approve-audit-{stamp}.jsonl"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(self.FIELDS)
        for r in rows:
            w.writerow([r.get(k, "") for k in self.FIELDS])
        return ("\ufeff" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"auto-approve-audit-{stamp}.csv"


# ---------------------------------------------------------------------------
# 看守
# ---------------------------------------------------------------------------
class ApprovalGuard:
    interval = 1.2          # 扫描间隔（秒）
    click_cooldown = 5.0    # 同一张卡点完后多久内不重复点
    max_clicks = 3          # 同一张卡最多点几次
    dedupe_ttl = 600.0      # 同一张卡的待定/拦截/演练记录多久内只记一次

    def __init__(self, settings: ApprovalSettings, audit: ApprovalAudit, label_resolver=None):
        self.settings = settings
        self.audit = audit
        self.label_resolver = label_resolver
        self.lock = threading.Lock()
        self._logged: dict[str, float] = {}
        self._clicks: dict[str, list] = {}     # key -> [count, last_ts]
        self._expanded: dict[str, tuple[int, float]] = {}   # key -> (展开次数, 最近一次)

    @staticmethod
    def _key(aid, card) -> str:
        h = hashlib.sha256()
        h.update((aid or "").encode())
        h.update(b"\0" + (card.get("text") or "").encode())
        for c in card.get("codes") or []:
            h.update(b"\0" + c.encode())
        h.update(b"\0" + (card.get("summary") or "").encode())
        for k, v in card.get("fields") or []:
            h.update(b"\0" + str(k).encode() + b"=" + str(v).encode())
        return h.hexdigest()[:24]

    def _label(self, aid):
        if self.label_resolver and aid:
            try:
                return self.label_resolver(aid) or ""
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def _prune(self, now):
        if len(self._logged) > 2000:
            for k, t in list(self._logged.items()):
                if now - t > self.dedupe_ttl:
                    self._logged.pop(k, None)
        if len(self._expanded) > 2000:
            for k, v in list(self._expanded.items()):
                if now - v[1] > self.dedupe_ttl:
                    self._expanded.pop(k, None)
        if len(self._clicks) > 2000:
            for k, v in list(self._clicks.items()):
                if now - v[1] > self.dedupe_ttl:
                    self._clicks.pop(k, None)

    def _record(self, aid, card, verdict, mode, action, button="", attempt=0, key=None, once=True):
        now = time.monotonic()
        if once and key:
            key = f"{key}:{verdict.tier}:{mode}"   # 改了设置（信任主机 / 演练）后判定变了，要重新记一条
            with self.lock:
                last = self._logged.get(key)
                if last is not None and now - last < self.dedupe_ttl:
                    return None
                self._logged[key] = now
                self._prune(now)
        text = card.get("text") or ""
        if card.get("summary"):
            text += "\n" + card["summary"]
        if card.get("fields"):
            text += "\n" + "\n".join(f"{k}: {v}" for k, v in card["fields"])
        codes = [c for c in (card.get("codes") or []) if c and c not in text]
        entry = {
            "account_id": aid or "", "account_label": self._label(aid),
            "tier": verdict.tier, "category": verdict.category, "reason": redact(verdict.reason, 300),
            "mode": mode, "action": action, "button": button, "attempt": attempt,
            # 没有 Muse 审批卡标记的块边界不可靠，可能圈进聊天内容，不记文字
            "text": redact(text + ("\n" + "\n".join(codes) if codes else ""))
            if card.get("marked") and not card.get("too_large") else "",
            "card": {"buttons": [redact(b.get("label", ""), 40) + ":" + b.get("kind", "") for b in card.get("buttons") or []],
                     "shape": {k: redact(str(v), 80) for k, v in (card.get("shape") or {}).items() if k in ("tag", "role", "testid")},
                     "too_large": bool(card.get("too_large")), "marked": bool(card.get("marked")),
                     "surface": redact(card.get("surface") or "", 40)},
        }
        try:
            e = self.audit.append(entry)
        except OSError as exc:
            log.warning("审批卡审计日志写入失败: %s", exc)
            return None
        log.info("审批卡[%s] 账号=%s 判定=%s(%s) 动作=%s %s", mode, aid, verdict.tier, verdict.category, action, button)
        return e

    @staticmethod
    def _sig(card) -> str:
        """与 SCAN_JS 里 sig() 相同的卡片快照串（JSON.stringify 与 json.dumps 紧凑格式一致）。"""
        return json.dumps([card.get("text") or "", card.get("codes") or [], card.get("summary") or "",
                           card.get("fields") or []], ensure_ascii=False, separators=(",", ":"))

    def _locate(self, engine, card, kind, label):
        raw = engine.page.js(SCAN_JS % (json.dumps(SCAN_CFG, ensure_ascii=False),
                                        json.dumps({"sig": self._sig(card), "kind": kind, "label": label},
                                                   ensure_ascii=False)))
        return json.loads(raw) if isinstance(raw, str) and raw else None

    def scan(self, engine) -> list[dict]:
        raw = engine.page.js(SCAN_JS % (json.dumps(SCAN_CFG, ensure_ascii=False), "null"))
        if not isinstance(raw, str) or not raw:
            return []
        try:
            return list(json.loads(raw).get("cards") or [])
        except ValueError:
            return []

    def tick(self, engine, force: bool = False) -> bool:
        """扫描一次（自带节流）。返回当前页面上是否有审批卡（用于让等待逻辑别提前放弃）。"""
        local = engine._ensure_local()
        now = time.monotonic()
        if not force and now < getattr(local, "approval_next", 0.0):
            return bool(getattr(local, "approval_pending", False))
        local.approval_next = now + self.interval
        aid = engine.current_acc_id
        state = self.settings.effective(aid)
        if not state["enabled"] or engine.page is None:
            local.approval_pending = False
            return False
        try:
            cards = self.scan(engine)
        except Exception as exc:  # noqa: BLE001
            log.debug("审批卡扫描失败: %s", exc)
            return bool(getattr(local, "approval_pending", False))
        clicked = False
        for card in cards:
            try:
                # 批次卡点完一项后 Muse 会重画整张卡，一轮只点一次，下一轮再点下一项
                clicked = self._handle(engine, aid, state, card, can_click=not clicked) or clicked
            except Exception as exc:  # noqa: BLE001
                log.warning("审批卡处理失败: %s", exc)
        local.approval_pending = bool(cards)
        return bool(cards)

    def _handle(self, engine, aid, state, card, can_click: bool = True) -> bool:
        """处理一张卡；真的点了按钮（含展开详情）返回 True。演练模式下任何按钮都不点。"""
        mode = state["mode"]
        live = mode == "live"
        key = self._key(aid, card)
        now = time.monotonic()
        if not card.get("marked"):
            self._record(aid, card, Verdict("unknown", "unmarked", "没有 Muse 审批卡标记（hatch-inline-approval-card），"
                                            "卡片边界不可靠，不自动处理"), mode, "none", key=key)
            return False
        if card.get("too_large"):
            self._record(aid, card, Verdict("unknown", "too_large", "卡片区域过大，未读取文字，不自动处理"),
                         mode, "none", key=key)
            return False
        if card.get("has_show") or card.get("collapsed"):
            # 详情折叠时读不到完整操作（Host / Method / Path），一律待定。展开详情只是「看一眼」，
            # 不是审批动作，演练模式也会展开一次（只点「See details」开关，绝不碰放行 / 拒绝按钮）；
            # 展开后开关还是折叠 = 展开失败，保持待定。
            show = next((b for b in card.get("buttons") or [] if b.get("kind") in ("show", "toggle")), None)
            with self.lock:
                tries = self._expanded.get(key, (0, 0.0))[0]
            # 同一快照最多展开 3 次（几张折叠卡长得一样时要逐张展开）；仍折叠 = 展开失败，保持待定
            if can_click and show and tries < 3:
                with self.lock:
                    self._expanded[key] = (tries + 1, now)
                pt = self._locate(engine, card, show["kind"], show["label"])
                if pt:
                    engine._click_point(pt["x"], pt["y"])
                    return True
            self._record(aid, card, Verdict("unknown", "collapsed", "审批详情折叠着（或展开失败），读不到完整操作，不自动处理"),
                         mode, "none", key=key)
            return False
        if state.get("allow_all"):
            verdict = classify_allow_all(card.get("text") or "", card.get("codes") or [], fields=card.get("fields") or [],
                                         summary=card.get("summary") or "", trusted_hosts=state.get("trusted_hosts") or ())
        else:
            verdict = classify(card.get("text") or "", card.get("codes") or [], allow_build=state.get("allow_build", True),
                               fields=card.get("fields") or [], summary=card.get("summary") or "",
                               trusted_hosts=state.get("trusted_hosts") or ())
        button = None
        if verdict.tier == "allow":
            buttons = card.get("buttons") or []
            for kind in _CLICK_PREFERENCE:
                button = next((b for b in buttons if b.get("kind") == kind), None)
                if button:
                    break
            if not button:
                verdict = Verdict("unknown", "no_single_allow",
                                  "卡片上没有单次放行按钮（只有扩大授权或连接器动作按钮），不自动点")
        if verdict.tier != "allow":
            self._record(aid, card, verdict, mode, "none", key=key)
            return False
        if not live:
            self._record(aid, card, verdict, mode, "would-click", button["label"], key=key)
            return False
        if not can_click:
            return False
        with self.lock:
            rec = self._clicks.get(key)
            if rec and now - rec[1] < self.click_cooldown:
                return False
            give_up = bool(rec and rec[0] >= self.max_clicks)
            if not give_up:
                rec = self._clicks[key] = [(rec[0] if rec else 0) + 1, now]
        if give_up:
            self._record(aid, card, verdict, mode, "click-failed", button["label"], self.max_clicks, key=key + ":fail")
            return False
        pt = self._locate(engine, card, button["kind"], button["label"])
        if not pt:
            self._record(aid, card, verdict, mode, "not-clickable", button["label"], rec[0], once=False)
            return False
        engine._click_point(pt["x"], pt["y"])
        self._record(aid, card, verdict, mode, "clicked", button["label"], rec[0], once=False)
        return True
