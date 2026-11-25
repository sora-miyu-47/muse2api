"""审批卡判定规则：白名单放行 / 黑名单拦截 / 其他待定（不批）。

本模块只做纯文本判定，不碰浏览器，便于单元测试。

判定顺序（宁窄勿宽）：
  1. 文本为空、过长          -> unknown（不批）
  2. 命中任一黑名单          -> block（永不自动批，停住等人工）
  3. 卡片全文逐行核对：每一行必须是已知的 Muse 界面套话，或是完全匹配白名单的命令 /
     白名单域名；有任何一行认不出来 -> unknown（不批，记日志）
  4. 全部行都通过            -> allow

白名单按「操作全文」匹配：命令要整行完全匹配某条规则，参数逐个校验
（例如 curl 只能 GET 白名单域名、不能带数据/请求头/凭据/管道）。
"""
from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------
MAX_CARD_TEXT = 4000        # 超过这个长度的「卡片」大概率是误圈了整块页面，不判定
MAX_COMMAND_LEN = 400       # 单条命令最长；更长的一律待定

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2028\u2029\u2060\ufeff]")


def normalize(text: str) -> str:
    """NFKC + 去零宽字符 + 统一引号，防止全角/零宽字符绕过规则。"""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t)
    t = t.replace("\u2018", "'").replace("\u2019", "'").replace("\u02bc", "'")
    return t.replace("\u201c", '"').replace("\u201d", '"')


@dataclass
class Verdict:
    tier: str                      # allow | block | unknown
    category: str = ""             # 黑名单类别 / 白名单规则 id
    reason: str = ""
    commands: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"tier": self.tier, "category": self.category, "reason": self.reason}


# ---------------------------------------------------------------------------
# 黑名单：全文（含代码块）任意位置命中即拦截。宁可误拦，不可漏拦。
# ---------------------------------------------------------------------------
_B = r"(?<![\w.-])"   # 词首：前面不是字母数字、点、连字符
_E = r"(?![\w-])"     # 词尾

BLACKLIST: list[tuple[str, str, str]] = [
    # (类别 id, 说明, 正则)
    ("delete", "删文件 / 删数据",
     _B + r"(rm|rmdir|unlink|shred|srm|wipe|truncate|mkfs(\.\w+)?|del|rd|erase|purge|uninstall)" + _E
     + r"|\bdd\s+if=|-delete\b|\bremove-item\b|\bdelete\b|\bremove\b|\bdrop\s+(table|database|schema)\b"
     + r"|\btruncate\s+table\b|\bgit\s+(clean|reset\s+--hard|checkout\s+--|restore|stash\s+(drop|clear)|branch\s+-[dD])\b"
     + r"|\bgit\s+rm\b|/dev/(sd|nvme|null\s*$)|删除|删掉|清空|清除|移除|抹除|卸载|刪除|削除"),
    ("message", "对外发消息 / 发邮件 / 发布 / 分享",
     r"\bsend(s|ing)?\b|\bsent\b|\bmail(s|x)?\b|\be-?mail\b|\bgmail\b|\boutlook\b|\bsmtp\b|\bsendmail\b|\bmutt\b"
     r"|\bsms\b|\bslack\b|\bdiscord\b|\btelegram\b|\bwhatsapp\b|\bmessenger\b|\bwechat\b|\btwitter\b|\btweet"
     r"|\binstagram\b|\bfacebook\b|\bthreads\b|\bpublish|\bpost(s|ing)?\s+(to|on|a|an|the)\b|\bshare(s|d)?\b|\bsharing\b"
     r"|\bgit\s+push\b|git-receive-pack|\bupload|\bwebhook|\bnotify\b|\binvite\b|\bmessage(s)?\b|\breply\b|\bforward\b|\bcomment\b"
     r"|发送|发消息|发邮件|发帖|发布|分享|转发|群发|邮件|短信|私信|回复|傳送|發送|分享資訊|送信|共有|投稿"),
    ("credential", "读取或发送凭据 / cookie / 密钥",
     r"cookie|\btokens?\b|token=|passw|\bpwd=|secret|credential|api[_ -]?key|apikey|private[_ -]?key|access[_ -]?key"
     r"|\.ssh\b|id_rsa|id_ed25519|id_ecdsa|authorized_keys|known_hosts|\.netrc|\.git-credentials|\.aws\b|\.kube\b"
     r"|\.docker/config|\.npmrc|\.pypirc|\.gnupg|\bgpg\b|keychain|keyring|1password|bitwarden|lastpass|vault"
     r"|" + _B + r"(printenv|env|set|export|history)" + _E + r"|/proc/\S*environ|\.env\b|\.bash_history|/etc/shadow"
     r"|authori[sz]ation|\bbearer\b|\boauth|\bauth\b|\blog\s?in\b|\bsign\s?in\b|\bsession|\bjwt\b|\botp\b|\b2fa\b|\bmfa\b"
     r"|hatch_|凭据|憑證|密码|密碼|密钥|密鑰|令牌|口令|登录|登入|验证码|パスワード|認証"),
    ("payment", "付款 / 下单 / 绑卡",
     r"\bpay(s|ment|ments|ing|pal)?\b|\bpurchas|\bbuy(ing|s)?\b|\bcheck\s?out\b|\border(s|ing)?\b|\bbilling\b|\binvoice"
     r"|\bcredit\s*card|\bdebit\s*card|\bcard\s*number|\bcvv\b|\bspend|\btransaction|\bsubscri(be|ption)|\bwallet\b"
     r"|\bstripe\b|\balipay\b|\brefund|\bbook(ing|s)?\s+(a|an|the|round|one|multi|flight|car|hotel)|\bduffel\b|\bmerchant\b"
     r"|付款|支付|付费|購買|购买|下单|下單|绑卡|綁卡|银行卡|信用卡|充值|订阅|訂閱|结账|結帳|转账|轉帳|決済|購入|注文"),
    ("account", "改账号设置 / 改绑账号 / 授权连接",
     r"\bsettings?\b|\baccounts?\b|\bprofile\b|\brevoke|\bpair(ing|ed)?\b|\bconnect(ed)?\s+(your|with|to)\b"
     r"|\blink(ed)?\s+(account|your)\b|\bphone\s*number|\brecovery\b|\bdelete\s+account|\bdeactivate"
     r"|\b(change|reset|update)\s+(your\s+)?(password|email|phone|username)\b"
     r"|改绑|绑定|解绑|綁定|账号|帳號|账户|帳戶|设置|設定|手机号|配对|配對|アカウント"),
    ("remote_script", "执行来路不明的远程脚本",
     r"\b(curl|wget|fetch|iwr|invoke-webrequest)\b[^\n]*\|\s*(sudo\s+)?(ba|z|k|da|fi|c|tc)?sh\b"
     r"|\b(curl|wget|fetch)\b[^\n]*\|\s*(sudo\s+)?(python\d?|perl|ruby|node|php|bun|deno)\b"
     r"|\b(ba|z)?sh\s+(-\w+\s+)*<\(|\bsource\s+<\(|(^|\s)\.\s+<\(|\$\(\s*(curl|wget)\b|`\s*(curl|wget)\b"
     r"|\beval\b|\biex\b|invoke-expression|downloadstring|\bbase64\s+(-d|--decode)\b|\bnpx\b|\bbunx\b|\bpipx\s+run\b|\buvx\b"
     r"|\bpip3?\s+install\s+[^\n]*(git\+|https?://)"),
    ("privilege", "提权 / 远程登录 / 持久化",
     _B + r"(sudo|su|doas|ssh|scp|sftp|nc|ncat|netcat|socat|telnet|crontab|systemctl|service|chown|chattr|iptables"
     r"|useradd|usermod|passwd|visudo|mount|kill|pkill|killall|reboot|shutdown)" + _E
     + r"|/dev/tcp/|\bchmod\s+(-\w+\s+)*([0-7]*7[0-7]{0,2}|[ugoa]*\+[rwx]*s)\b|\brsync\b[^\n]*\S+:"),
]
_BLACKLIST_RE = [(cid, desc, re.compile(rx, re.I | re.M)) for cid, desc, rx in BLACKLIST]


# 这些词作为命令才危险（history / env / set / kill …），出现在助手写的英文说明里是普通单词，
# 扫说明时跳过它们；其它黑名单类别（删除、发消息、凭据名词、付款、账号、远程脚本）照常生效。
# profile / account / settings 在说明里多是名词（「角色简介 character profile」）；改账号的说法
# （link your account、change password、delete account、connect to …）仍由其它分支命中。
_PROSE_SKIP = {"env", "set", "export", "history", "del", "rd", "kill", "service", "mount", "su", "shutdown",
               "reboot", "erase", "purge", "truncate", "wipe", "profile", "account", "accounts", "setting", "settings"}
# 「登录页 / login page」只是在描述一个页面，不是用凭据登录
_PROSE_LOGIN = re.compile(r"^(log\s?in|sign\s?in)$", re.I)
_PROSE_PAGE_AFTER = re.compile(r"^[\s-]*(page|screen|form|entry|entrance|portal)\b", re.I)


def blacklist_hit(text: str, prose: bool = False) -> tuple[str, str, str] | None:
    t = normalize(text)
    for cid, desc, rx in _BLACKLIST_RE:
        for m in rx.finditer(t):
            frag = m.group(0).strip()
            if prose and frag.lower() in _PROSE_SKIP:
                continue
            if prose and _PROSE_LOGIN.match(frag) and _PROSE_PAGE_AFTER.match(t[m.end():]):
                continue
            return cid, desc, frag[:60]
    return None


# ---------------------------------------------------------------------------
# Muse 界面套话：从 muse.ai 前端 i18n 包（en / zh_CN / zh_TW / zh_HK / ja）整理。
# 只收录不带操作内容的模板：{assistant} {agentName} {approvalCount} {position} {total}
# 是名字/数字，可以放过；{subject} {requestName} {action} {summary} 这几个位置的内容
# 必须本身是短标签或白名单命令；带 {connector} {merchant} {domain} 等的模板不收录
# （那是连接器/购物/分享类卡片，整行会被当成认不出的内容 -> 不批）。
# ---------------------------------------------------------------------------
HEADER_TEMPLATES = [
    # en
    "The agent needs approval", "{assistant} needs approval", "Agent needs {approvalCount} approvals",
    "{assistant} needs {approvalCount} approvals", "Review the request so that the agent can continue.",
    "Review the request so {assistant} can continue.", "Review the requests so that the agent can continue.",
    "Review the requests so {assistant} can continue.", "Agent needs approval to continue.",
    "{assistant} needs approval to continue.", "Needs approval", "{agentName}, needs approval",
    "Approval {position} of {total}", "Approval {position} of {total}: {requestName}", "Approval request",
    "Approval request for {requestName}", "Approval requests", "Waiting for approval",
    "Review the approval request in chat to continue",
    "Approval required. You can keep typing, but sending is paused until you allow or deny the request above.",
    "The agent needs your permission for {subject}: {action} – {summary}",
    "{assistant} needs your permission for {subject}: {action} – {summary}",
    "The agent needs your permission for {subject}: {action}", "{assistant} needs your permission for {subject}: {action}",
    "The agent needs your permission for {subject}: {summary}", "{assistant} needs your permission for {subject}: {summary}",
    "The agent wants to access", "{assistant} wants to access", "Allow {assistant} to access",
    # zh_CN
    "智能体需要获得批准", "{assistant}需要审核", "智能体需要获得{approvalCount}项批准", "{assistant}需要获得{approvalCount}项批准",
    "审核请求以便智能体继续。", "审核请求以便智能体继续操作。", "审核请求，以便{assistant}继续操作。", "智能体需要获批才能继续。",
    "{assistant}需要获批才能继续。", "需要批准", "{agentName}，需要审核", "第{position}项批准（共{total}项）",
    "第{position}项批准（共{total}项）：{requestName}", "批准请求", "{requestName}的批准请求", "审核请求", "正在等待批准",
    "审核聊天中的批准请求以继续", "需要批准。你可以继续输入，但发送功能会暂停，直到你允许或拒绝上方的请求。",
    "智能体需要你的授权才能{subject}：{action} — {summary}", "{assistant}需要你的授权才能{subject}：{action} — {summary}",
    "智能体需要你的授权才能{subject}：{action}", "{assistant}需要你授予{subject}权限：{action}",
    "智能体需要你授予{subject}权限：{summary}", "{assistant}需要你的授权才能{subject}：{summary}",
    "智能体想访问", "{assistant}想访问", "允许{assistant}访问",
    # zh_TW / zh_HK
    "代理需要獲得批准", "{assistant}需要獲得批准", "{assistant}需要批准", "代理正在等待批准", "需要核可", "需要獲得批准",
    "代理需要{approvalCount}項批准", "{assistant}需要{approvalCount}項批准", "代理必須獲得{approvalCount}項批准",
    "該代理需要獲得批准才能繼續。", "{assistant}必須獲得批准才能繼續。", "代理須要獲得批准才能繼續。",
    "{assistant}需要獲得批准才能繼續。", "請審查要求，以便代理可以繼續。", "請審查要求，以便{assistant}可以繼續。",
    "檢閱要求，讓代理可以繼續。", "檢閱要求以便{assistant}可以繼續。", "審查要求以便{assistant}可以繼續。",
    "{agentName}，需要獲得批准", "{agentName}，需要核可", "第{position}個批准，共{total}個",
    "第{position}個批准，共{total}個：{requestName}", "核可{total}之{position}", "核可{total}之{position}：{requestName}",
    "批准要求", "核可要求", "審查要求", "{requestName}的批准要求", "等待核准", "查看聊天室中的批准要求以繼續",
    "查看聊天室中的核可要求以繼續",
    "代理需要你授予{subject}的權限：{action} -- {summary}", "{assistant}需要你授予{subject}的權限：{action} -- {summary}",
    "代理需要你授予{subject}的權限：{action}—{summary}", "代理需要你授予{subject}的權限：{action}",
    "{assistant}需要你授予{subject}的權限：{action}", "代理需要你授予{subject}的權限：{summary}",
    "{assistant}需要你授予{subject}的權限：{summary}", "代理想存取", "{assistant}想要存取", "允許{assistant}存取",
    # ja
    "エージェントは承認が必要です", "エージェントは承認が必要です。", "{assistant}は承認が必要です",
    "エージェントは{approvalCount}件の承認が必要です", "{assistant}には{approvalCount}件の承認が必要です",
    "エージェントが続行できるようリクエストを確認してください。", "{assistant}が続行できるようリクエストを確認してください。",
    "{assistant}を続けるには承認が必要です。", "承認が必要です", "{agentName}、承認が必要です", "承認{total}件中{position}件",
    "承認{total}件中{position}件: {requestName}", "承認リクエスト", "{requestName}の承認リクエスト", "承認待ち",
    "次へ進むには、チャット内の承認リクエストを確認してください",
    "エージェントには{subject}のアクセス許可が必要です: {action} -- {summary}",
    "{assistant}には{subject}のアクセス許可が必要です: {action} -- {summary}",
    "エージェントには{subject}のアクセス許可が必要です: {action}", "{assistant}には{subject}のアクセス許可が必要です: {action}",
    "エージェントには{subject}のアクセス許可が必要です: {summary}", "{assistant}には{subject}のアクセス許可が必要です: {summary}",
    "エージェントがアクセスをリクエストしています", "{assistant}がアクセスをリクエストしています", "{assistant}にアクセスを許可",
    # 网络外联卡（2026-11-25 在线上 alice 账号实测，git clone 触发）：
    #   标题 "Allow Muse to share information with github.com?"，说明 "\"Always allow\" covers github.com and all its
    #   subdomains, not just this page."，详情 dl 里是 Host / Grants / Method / Path / Policy。
    "Allow {assistant} to share information with {host}?",
    '"Always allow" covers {host} and all its subdomains, not just this page.',
    # 网站卡标题：域名直接跟在「访问」后面（{host} 必须是白名单域名）
    "Allow {assistant} to access {host}?", "Allow {assistant} to access {host}", "Allow the agent to access {host}?",
    "{assistant} wants to access {host}", "The agent wants to access {host}", "Allow {assistant} to open {host}?",
    "{assistant} wants to open {host}", "允许{assistant}访问{host}？", "允许{assistant}访问{host}", "{assistant}想访问{host}",
    "智能体想访问{host}", "允許{assistant}存取{host}？", "允許{assistant}存取{host}", "{assistant}想要存取{host}",
    "代理想存取{host}", "{assistant}に{host}へのアクセスを許可しますか？", "{assistant}が{host}へのアクセスをリクエストしています",
]
# 来源聊天 / 排程说明（整行都是这句才算界面套话），取自 Muse 线上文案
_SOURCE_LINE = re.compile(
    r"^(此任務來自[^。]{0,80}。|此任务来自[^。]{0,80}。|這是針對排定的[^。]{0,80}任務。|这是预定任务[^。]{0,80}。"
    r"|this task (?:is |comes |came )?from [^.]{0,80}\.|this is for the scheduled task [^.]{0,80}\.)$", re.I)
# 「想访问」类模板：之后出现的裸域名行才被当成网络访问目标
_ACCESS_MARKERS = ("wants to access", "to access", "想访问", "访问", "想存取", "想要存取", "存取", "アクセスを")

# 名字槽位只允许 1~3 个纯字母词（含中日文），并单独捕获：要过黑名单，且不能是命令名。
_NAME = r"[^\W\d_]{1,24}(?:\s[^\W\d_]{1,24}){0,2}?"
_NAME_SLOTS = {"assistant": _NAME, "agentName": _NAME, "approvalCount": r"\d{1,3}",
               "position": r"\d{1,3}", "total": r"\d{1,3}"}
_CONTENT_SLOTS = ("subject", "requestName", "action", "summary", "host")


def _literal(p: str) -> str:
    body = r"\s+".join(re.escape(x) for x in re.split(r"\s+", p) if x)
    return (r"\s*" if p[:1].isspace() else "") + body + (r"\s*" if p[-1:].isspace() else "")


def _template_regex(tpl: str) -> re.Pattern:
    parts = re.split(r"\{(\w+)\}", normalize(tpl))
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(_literal(p))
        elif p in ("assistant", "agentName"):
            out.append(f"(?P<name{i}>{_NAME})")
        elif p in _NAME_SLOTS:
            out.append(_NAME_SLOTS[p])
        else:
            out.append(f"(?P<{p}>.+?)")
    return re.compile(r"^\s*" + "".join(out) + r"\s*$", re.I)


_HEADER_RES = [_template_regex(t) for t in HEADER_TEMPLATES]

# 短标签：卡片里单独成行的类别名/字段名（小写比较）。
SHORT_LABELS = {
    "terminal", "shell", "bash", "command", "commands", "run command", "run a command", "run commands",
    "execute command", "run", "computer", "network", "network access", "web access", "internet access",
    "details", "approval details", "request", "code", "script", "cli",
    "终端", "命令", "运行命令", "执行命令", "运行", "电脑", "计算机", "网络", "网络访问", "详情",
    "終端機", "指令", "執行指令", "執行", "電腦", "網絡", "網路", "網絡存取", "網路存取", "詳細資料",
    "ターミナル", "コマンド", "コマンドを実行", "実行", "コンピューター", "ネットワーク", "詳細",
}
_TIME_LINE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?\s*([ap]\.?m\.?)?$|^(just now|刚刚|剛剛|たった今)$", re.I)

# ---------------------------------------------------------------------------
# 白名单：只读 / 低风险命令 + 常规构建安装命令 + 只读访问白名单域名
# ---------------------------------------------------------------------------
SAFE_HOSTS = {
    "github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com",
    "objects.githubusercontent.com", "gitlab.com", "pypi.org", "files.pythonhosted.org",
    "registry.npmjs.org", "nodejs.org", "www.python.org", "docs.python.org", "crates.io",
    "static.crates.io", "index.crates.io", "proxy.golang.org", "sum.golang.org", "go.dev",
}

# 构建安装类规则会执行项目或依赖自带的脚本（npm 生命周期脚本、setup.py、Makefile、build.rs、测试代码），
# 网关无法检查这些内容，所以单独成组，可在管理页 / .env 关掉。
BUILD_RULES = {"uv", "pip", "npm", "build"}

WHITELIST_RULES: list[tuple[str, str]] = [
    ("readonly", "查看类命令：whoami / id / pwd / ls / cat / head / tail / wc / stat / du / df / ps / uname / date / which / echo / grep / rg / find，每个命令只认列出的选项；不允许重定向、管道、命令替换、未加引号的通配符"),
    ("version", "版本查询：python/node/npm/uv/git/pip/cargo 等 --version，go version"),
    ("git_read", "git 只读与同步：status / log / diff / show / branch(列出) / remote -v / rev-parse / ls-files / fetch / pull / submodule update，只认列出的选项"),
    ("git_clone", "git clone：只允许 https 的 github.com / gitlab.com，URL 不能带账号密码"),
    ("http_get", "curl / wget：只允许对白名单域名做 GET 下载，只认列出的选项（禁止 -d/-F/-T/-X/-H/-u/-b/-K、管道与重定向）"),
    ("net_access", "网络访问卡片：目标域名全部在白名单内（只读的代码托管 / 包仓库域名）"),
    ("trusted_host", "网络访问卡片：目标是你在管理页 / .env（MUSE2API_AUTO_APPROVE_HOSTS）里填的信任主机，"
                     "必须读到详情字段，且只放行 GET / HEAD、策略 tool.exec"),
    ("uv", "【构建安装】uv sync / lock / venv / add <包名> / pip install <包名>：禁止 URL、git+、-r/-e/-c 文件、自定义索引、自定义解释器路径"),
    ("pip", "【构建安装】pip / python -m pip install <包名>：禁止 URL、git+、-r/-e/-c 文件、自定义索引"),
    ("npm", "【构建安装】npm ci / npm install [包名] / npm test / npm run build|test|lint、pnpm/yarn install：只认列出的选项"),
    ("build", "【构建安装】python -m venv / pytest / make build|test|check|lint|all / cargo build|check|test / go build|test|vet"),
]

_FORBIDDEN_CHARS = re.compile(r"[;&|<>$`\\(){}\n\r!]")
_PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*(\[[A-Za-z0-9_,.\-]+\])?"
                     r"((==|>=|<=|~=|!=|>|<)[A-Za-z0-9_.*+\-]+)?(,(==|>=|<=|~=|!=|>|<)[A-Za-z0-9_.*+\-]+)*$")
_NPM_PKG_RE = re.compile(r"^(@[a-z0-9][a-z0-9._\-]*/)?[a-z0-9][a-z0-9._\-]*(@[A-Za-z0-9._\-^~><=]+)?$")
_PATH_RE = re.compile(r"^[A-Za-z0-9_./~\-+=:,@%]+$")       # 不含通配符 * ? [ ]
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./\-]*$")
_NUM_RE = re.compile(r"^\d{1,6}$")
_PYVER_RE = re.compile(r"^(python)?3(\.\d{1,2}){0,2}$")


def url_ok(u: str) -> bool:
    try:
        p = urlsplit(u)
        port = p.port
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname:
        return False
    if p.username or p.password or (port not in (None, 443)):
        return False
    if p.query and re.search(r"(token|key|secret|sig|auth|pass)", p.query, re.I):
        return False
    return p.hostname.lower() in SAFE_HOSTS


def _unquoted_glob(cmd: str) -> bool:
    """命令里有没有不在引号里的 * ? [ ]（shell 会展开，字面黑名单就拦不住了）。"""
    quote = ""
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "*?[]":
            return True
    return False


def _path_ok(a: str) -> bool:
    return bool(_PATH_RE.match(a)) and "://" not in a and not a.startswith("-")


def _parse(args: list[str], flags: set[str] = frozenset(), valued: dict | None = None,
           positional=_path_ok, short: re.Pattern | None = None) -> bool:
    """逐个校验参数：只认 flags 里的开关、valued 里的带值选项（值用对应函数校验）、合格的位置参数。"""
    valued = valued or {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in flags or (short is not None and short.match(a)):
            i += 1
            continue
        if "=" in a and a.startswith("--") and a.split("=", 1)[0] in valued:
            k, v = a.split("=", 1)
            if not valued[k](v):
                return False
            i += 1
            continue
        if a in valued:
            if i + 1 >= len(args) or not valued[a](args[i + 1]):
                return False
            i += 2
            continue
        if a.startswith("-") or not positional(a):
            return False
        i += 1
    return True


def _any_text(a: str) -> bool:   # grep 搜索词 / echo 文本 / find -name 模式（已排除元字符与未加引号的通配符）
    return 0 < len(a) <= 200 and "://" not in a


_NO_POSITIONAL = lambda a: False  # noqa: E731

# 每个查看类命令允许的选项
_READONLY = {
    "whoami": dict(positional=_NO_POSITIONAL),
    "id": dict(flags={"-u", "-g", "-G", "-n", "-un", "-gn"}, positional=_NO_POSITIONAL),
    "pwd": dict(flags={"-P", "-L"}, positional=_NO_POSITIONAL),
    "uptime": dict(flags={"-p", "-s"}, positional=_NO_POSITIONAL),
    "nproc": dict(positional=_NO_POSITIONAL),
    "arch": dict(positional=_NO_POSITIONAL),
    "groups": dict(positional=_NO_POSITIONAL),
    "tty": dict(positional=_NO_POSITIONAL),
    "free": dict(flags={"-h", "-m", "-g", "-k", "-b"}, positional=_NO_POSITIONAL),
    "df": dict(short=re.compile(r"^-[hTikl]+$"), positional=_path_ok),
    "uname": dict(short=re.compile(r"^-[asnrvmpio]+$"), positional=_NO_POSITIONAL),
    "lsb_release": dict(short=re.compile(r"^-[adrc]+$"), positional=_NO_POSITIONAL),
    "hostname": dict(flags={"-f", "-i", "-I", "-s", "-d", "--fqdn", "--short"}, positional=_NO_POSITIONAL),
    "date": dict(flags={"-u", "-R", "-I", "--utc", "--iso-8601"},
                 positional=lambda a: a.startswith("+") and len(a) <= 40),
    "ps": dict(flags={"aux", "-ef", "-e", "-f", "-A", "ax", "-aux"}, positional=_NO_POSITIONAL),
    "ls": dict(short=re.compile(r"^-[alhtrSR1dFAiG]+$"), flags={"--all", "--color=never"}),
    "cat": dict(flags={"-n", "-A", "-b"}),
    "head": dict(short=re.compile(r"^-\d{1,6}$"), valued={"-n": _NUM_RE.match, "-c": _NUM_RE.match}),
    "tail": dict(short=re.compile(r"^-\d{1,6}$"), valued={"-n": _NUM_RE.match, "-c": _NUM_RE.match}),
    "wc": dict(short=re.compile(r"^-[lwcm]+$")),
    "file": dict(flags={"-b", "-i"}),
    "stat": dict(),
    "tree": dict(flags={"-a", "-d"}, valued={"-L": _NUM_RE.match}),
    "du": dict(short=re.compile(r"^-[shac]+$"), valued={"-d": _NUM_RE.match, "--max-depth": _NUM_RE.match}),
    "realpath": dict(), "basename": dict(), "dirname": dict(),
    "readlink": dict(flags={"-f", "-e"}),
    "md5sum": dict(), "sha1sum": dict(), "sha256sum": dict(),
    "which": dict(flags={"-a"}, positional=lambda a: bool(re.match(r"^[A-Za-z0-9_.+\-]+$", a))),
    "diff": dict(short=re.compile(r"^-[uqr]+$")),
    "cmp": dict(flags={"-s"}),
    "nl": dict(),
    "echo": dict(flags={"-n"}, positional=_any_text),
    "grep": dict(short=re.compile(r"^-[rRnilcvwEFHhosI]+$"), positional=_any_text),
    "rg": dict(short=re.compile(r"^-[nilcvwFS]+$"), flags={"--hidden", "--no-heading"}, positional=_any_text),
}
_FIND_PRED = {"-name": _any_text, "-iname": _any_text, "-path": _any_text, "-type": lambda v: v in ("f", "d", "l"),
              "-maxdepth": _NUM_RE.match, "-mindepth": _NUM_RE.match, "-size": lambda v: bool(re.match(r"^[+-]?\d+[ckMG]?$", v)),
              "-mtime": lambda v: bool(re.match(r"^[+-]?\d+$", v))}


def _rule_readonly(t: list[str]) -> bool:
    cmd, args = t[0], t[1:]
    if cmd == "find":
        i = 0
        while i < len(args) and not args[i].startswith("-"):
            if not _path_ok(args[i]):
                return False
            i += 1
        return _parse(args[i:], flags={"-print"}, valued=_FIND_PRED, positional=_NO_POSITIONAL)
    spec = _READONLY.get(cmd)
    return spec is not None and _parse(args, **spec)


_VERSION_FORMS = {
    ("python", "--version"), ("python", "-V"), ("python3", "--version"), ("python3", "-V"),
    ("node", "--version"), ("node", "-v"), ("npm", "--version"), ("npm", "-v"), ("pnpm", "--version"),
    ("yarn", "--version"), ("uv", "--version"), ("git", "--version"), ("pip", "--version"), ("pip3", "--version"),
    ("go", "version"), ("cargo", "--version"), ("rustc", "--version"), ("java", "--version"), ("java", "-version"),
    ("gcc", "--version"), ("g++", "--version"), ("clang", "--version"), ("make", "--version"), ("cmake", "--version"),
    ("deno", "--version"), ("bun", "--version"), ("ruby", "--version"), ("docker", "--version"),
    ("pytest", "--version"), ("ruff", "--version"), ("tsc", "--version"), ("rustup", "--version"),
}


def _rule_version(t: list[str]) -> bool:
    return (len(t) == 2 and (t[0], t[1]) in _VERSION_FORMS) or t in (
        ["python", "-m", "pip", "--version"], ["python3", "-m", "pip", "--version"])


def _strip_git_globals(t: list[str]) -> list[str] | None:
    i = 1
    while i < len(t) and t[i].startswith("-"):
        if t[i] == "-C" and i + 1 < len(t) and _path_ok(t[i + 1]):
            i += 2
        elif t[i] == "--no-pager":
            i += 1
        else:
            return None   # 拒绝 -c key=value 等（可改写 core.pager / diff.external 等外部程序）
    return t[i:]


def _rev(a: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_][A-Za-z0-9_./\-~^]*$", a))


_GIT_READ = {
    "status": dict(flags={"-s", "-sb", "--short", "--branch", "--porcelain", "-uno"}, positional=_NO_POSITIONAL),
    "log": dict(flags={"--oneline", "--graph", "--decorate", "--stat", "--all", "--name-only", "--name-status", "-p"},
                short=re.compile(r"^-\d{1,4}$"), valued={"-n": _NUM_RE.match, "--max-count": _NUM_RE.match},
                positional=lambda a: _rev(a) or _path_ok(a)),
    "diff": dict(flags={"--stat", "--cached", "--staged", "--name-only", "--name-status", "--no-ext-diff"},
                 positional=lambda a: _rev(a) or _path_ok(a)),
    "show": dict(flags={"--stat", "--name-only", "--name-status", "--no-ext-diff"},
                 positional=lambda a: _rev(a) or _path_ok(a)),
    "branch": dict(flags={"-a", "-r", "-v", "-vv", "--all", "--remotes", "--list", "-l", "--show-current"},
                   positional=_NO_POSITIONAL),
    "rev-parse": dict(flags={"HEAD", "--abbrev-ref", "--short", "--show-toplevel", "--git-dir"},
                      positional=_rev),
    "ls-files": dict(flags={"-m", "-o", "--others", "--modified", "--exclude-standard"}),
    "describe": dict(flags={"--tags", "--always"}, positional=_rev),
    "shortlog": dict(flags={"-s", "-n", "-sn", "-e"}, positional=_rev),
}


def _rule_git_read(t: list[str]) -> bool:
    if t[0] != "git":
        return False
    rest = _strip_git_globals(t)
    if not rest:
        return False
    sub, args = rest[0], rest[1:]
    if sub in _GIT_READ:
        return _parse(args, **_GIT_READ[sub])
    if sub == "remote":
        return args in ([], ["-v"], ["--verbose"])
    if sub in ("fetch", "pull"):
        return _parse(args, flags={"--all", "--tags", "--prune", "-p", "--ff-only", "-q", "--quiet", "--no-rebase"},
                      valued={"--depth": _NUM_RE.match}, positional=lambda a: bool(_BRANCH_RE.match(a)))
    if sub == "submodule":
        return args in (["status"], ["update", "--init"], ["update", "--init", "--recursive"],
                        ["update", "--recursive", "--init"])
    return False


def _rule_git_clone(t: list[str]) -> bool:
    if t[0] != "git":
        return False
    rest = _strip_git_globals(t)
    if not rest or rest[0] != "clone":
        return False
    urls, dests = [], []

    def pos(a):
        (urls if ("://" in a or "@" in a) else dests).append(a)
        return True
    ok = _parse(rest[1:], flags={"--single-branch", "--recursive", "--recurse-submodules", "--shallow-submodules",
                                 "-q", "--quiet", "--no-tags", "--filter=blob:none", "--filter=tree:0"},
                valued={"--depth": _NUM_RE.match, "--branch": _BRANCH_RE.match, "-b": _BRANCH_RE.match},
                positional=pos)
    if not ok or len(urls) != 1 or len(dests) > 1:
        return False
    return (url_ok(urls[0]) and urlsplit(urls[0]).hostname in ("github.com", "gitlab.com")
            and all(_path_ok(d) and not d.startswith(("/", "~")) and ".." not in d for d in dests))


def _pkg(a: str) -> bool:
    return bool(_PKG_RE.match(a))


def _rule_uv(t: list[str]) -> bool:
    if t[0] != "uv" or len(t) < 2:
        return False
    sub, args = t[1], t[2:]
    common = {"-q", "--quiet", "--frozen", "--locked"}
    pyver = {"--python": _PYVER_RE.match, "-p": _PYVER_RE.match}
    if sub in ("sync", "lock", "tree"):
        return _parse(args, flags=common | {"--all-extras", "--no-dev", "--dev"}, valued=pyver, positional=_NO_POSITIONAL)
    if sub == "venv":
        return _parse(args, flags={"--seed", "-q", "--quiet"}, valued=pyver,
                      positional=lambda a: _path_ok(a) and not a.startswith(("/", "~")) and ".." not in a)
    if sub == "add":
        return bool(args) and _parse(args, flags=common | {"--dev"}, positional=_pkg)
    if sub == "pip" and args:
        if args[0] in ("list", "freeze", "check"):
            return _parse(args[1:], positional=_NO_POSITIONAL)
        if args[0] == "show":
            return _parse(args[1:], positional=_pkg)
        if args[0] == "install":
            return len(args) > 1 and _parse(args[1:], flags={"-U", "--upgrade", "-q", "--quiet"}, positional=_pkg)
    if sub == "python" and args:
        return args[0] in ("list", "find", "install") and all(_PYVER_RE.match(a) for a in args[1:])
    return False


def _rule_pip(t: list[str]) -> bool:
    if t[0] in ("pip", "pip3"):
        rest = t[1:]
    elif len(t) >= 3 and t[0] in ("python", "python3") and t[1:3] == ["-m", "pip"]:
        rest = t[3:]
    else:
        return False
    if not rest:
        return False
    if rest[0] in ("list", "freeze", "check"):
        return _parse(rest[1:], positional=_NO_POSITIONAL)
    if rest[0] == "show":
        return _parse(rest[1:], positional=_pkg)
    if rest[0] == "install":
        return len(rest) > 1 and _parse(rest[1:], flags={"-U", "--upgrade", "-q", "--quiet", "--user", "--no-cache-dir"},
                                        positional=_pkg)
    return False


def _rule_npm(t: list[str]) -> bool:
    if t[0] in ("pnpm", "yarn"):
        return t[1:] in ([], ["install"], ["install", "--frozen-lockfile"], ["build"], ["test"], ["lint"],
                         ["run", "build"], ["run", "test"], ["run", "lint"])
    if t[0] != "npm" or len(t) < 2:
        return False
    sub, args = t[1], t[2:]
    if sub in ("install", "i", "ci"):
        return _parse(args, flags={"--save-dev", "-D", "--no-audit", "--no-fund", "--omit=dev", "--legacy-peer-deps",
                                   "--silent", "--prefer-offline"},
                      positional=lambda a: sub != "ci" and bool(_NPM_PKG_RE.match(a)))
    if sub in ("ls", "list"):
        return _parse(args, flags={"--all"}, valued={"--depth": _NUM_RE.match}, positional=_NO_POSITIONAL)
    if sub in ("test", "t"):
        return args == []
    if sub == "run":
        return args in (["build"], ["test"], ["lint"])
    return False


def _rule_build(t: list[str]) -> bool:
    pytest_args = dict(flags={"-q", "-v", "-vv", "-x", "-s", "--tb=short", "--tb=line", "--tb=no"},
                       valued={"--maxfail": _NUM_RE.match},
                       positional=lambda a: _path_ok(a) and not a.startswith(("/", "~")) and ".." not in a)
    if t[0] in ("python", "python3") and len(t) >= 3 and t[1] == "-m":
        if t[2] == "venv":
            return len(t) == 4 and _path_ok(t[3]) and not t[3].startswith(("/", "~")) and ".." not in t[3]
        if t[2] == "pytest":
            return _parse(t[3:], **pytest_args)
        return False
    if t[0] == "pytest":
        return _parse(t[1:], **pytest_args)
    if t[0] == "make":
        return all(a in ("build", "test", "check", "lint", "all") for a in t[1:])
    if t[0] == "cargo":
        return t[1:] in (["build"], ["check"], ["test"], ["build", "--release"], ["fmt", "--check"])
    if t[0] == "go":
        return t[1:] in (["build", "./..."], ["test", "./..."], ["vet", "./..."], ["build"], ["test"], ["mod", "download"])
    return False


_OUT_PATH_RE = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-/]*$")


def _out_path_ok(v: str) -> bool:
    """下载落盘路径：相对路径、不进隐藏目录、不往上跳。"""
    return bool(_OUT_PATH_RE.match(v)) and ".." not in v and "/." not in v


def _rule_http_get(t: list[str]) -> bool:
    if t[0] not in ("curl", "wget"):
        return False
    urls = []

    def pos(a):
        urls.append(a)
        return True
    if t[0] == "curl":
        ok = _parse(t[1:], short=re.compile(r"^-[sSLfIO#]+$"),
                    flags={"--head", "--fail", "--silent", "--show-error", "--location", "--compressed", "--remote-name"},
                    valued={"-o": _out_path_ok, "--output": _out_path_ok, "-m": _NUM_RE.match,
                            "--max-time": _NUM_RE.match, "--retry": _NUM_RE.match, "--connect-timeout": _NUM_RE.match},
                    positional=pos)
    else:
        ok = _parse(t[1:], flags={"-q", "--quiet", "-nv", "--no-verbose", "-c", "--continue"},
                    valued={"-O": _out_path_ok, "--output-document": _out_path_ok, "-P": _out_path_ok,
                            "--directory-prefix": _out_path_ok, "-T": _NUM_RE.match, "--timeout": _NUM_RE.match,
                            "-t": _NUM_RE.match, "--tries": _NUM_RE.match},
                    positional=pos)
    return ok and len(urls) == 1 and url_ok(urls[0])


_RULE_FUNCS = [("readonly", _rule_readonly), ("version", _rule_version), ("git_read", _rule_git_read),
               ("git_clone", _rule_git_clone), ("http_get", _rule_http_get), ("uv", _rule_uv), ("pip", _rule_pip),
               ("npm", _rule_npm), ("build", _rule_build)]
# 名字槽位里出现这些词就不当界面套话（防止把命令藏进「{assistant} needs approval」里）
_COMMAND_WORDS = set(_READONLY) | {"find", "git", "uv", "pip", "pip3", "npm", "npx", "pnpm", "yarn", "python",
                                   "python3", "node", "make", "cargo", "go", "curl", "wget", "bash", "sh", "zsh",
                                   "rm", "sudo", "ssh", "scp", "mv", "cp", "chmod", "chown", "dd", "kill", "env"}


def command_rule(cmd: str) -> str | None:
    """返回命中的白名单规则 id；不在白名单返回 None。"""
    c = normalize(cmd).strip()
    if not c or len(c) > MAX_COMMAND_LEN or _FORBIDDEN_CHARS.search(c) or _unquoted_glob(c):
        return None
    try:
        tokens = shlex.split(c, posix=True)
    except ValueError:
        return None
    if not tokens or "=" in tokens[0]:          # FOO=bar cmd：环境变量前缀一律不放
        return None
    for rid, fn in _RULE_FUNCS:
        try:
            if fn(tokens):
                return rid
        except (IndexError, TypeError):
            continue
    return None


_HOST_LINE = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(:\d+)?(/\S*)?$", re.I)


def _host_ok(line: str) -> bool:
    url = line if "://" in line else "https://" + line
    return url_ok(url)


# 信任主机：主机名 / IPv4 / [IPv6]，可带端口；不允许通配符、协议、路径
_TRUSTED_HOST_RE = re.compile(
    r"^(?:(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"|(?:\d{1,3}\.){3}\d{1,3}|\[[0-9a-f:]{2,45}\])(?::\d{1,5})?$")


def normalize_trusted_host(value: str) -> str | None:
    """校验并规范化一个信任主机；不合格返回 None。"""
    h = normalize(str(value or "")).strip().lower().rstrip(".")
    if not h or len(h) > 253 or not _TRUSTED_HOST_RE.match(h):
        return None
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?", h) and \
            any(int(x) > 255 for x in h.split(":", 1)[0].split(".")):
        return None
    if ":" in h and not h.startswith("[") and not h.rsplit(":", 1)[1].isdigit():
        return None
    port = h.rsplit(":", 1)[1] if re.search(r":\d+$", h) else None
    if port is not None and not 0 < int(port) < 65536:
        return None
    return h


def _segment_ok(seg: str, commands: list[str], rules: set[str], slot: str = "",
                trusted: frozenset = frozenset()) -> bool:
    """模板里 {subject}/{action}/{summary}/{requestName} 位置的内容：短标签、白名单命令或白名单域名；
    {host} 位置只能是白名单域名或信任主机（信任主机必须另有详情字段确认方法）。"""
    s = seg.strip().strip("`'\"")
    if slot == "host":
        if s.lower() in trusted:
            rules.add("trusted_host")
            return True
        if _HOST_LINE.match(s) and _host_ok(s):
            rules.add("net_access")
            return True
        return False
    if not s or s.lower() in SHORT_LABELS:
        return True
    rid = command_rule(s)
    if rid:
        commands.append(s)
        rules.add(rid)
        return True
    if _HOST_LINE.match(s) and _host_ok(s):
        rules.add("net_access")
        return True
    return False


# 外联卡详情字段：只认这几个键；Policy 只认终端工具外联
_FIELD_KEYS = {"host", "grants", "method", "path", "policy"}
ALLOWED_POLICIES = {"tool.exec"}
_GIT_FETCH_PATH = re.compile(r"^/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+?(\.git)?/(git-upload-pack|info/refs)$")
_URL_PATH = re.compile(r"^/[A-Za-z0-9._~/%+@:\-]*(\?[A-Za-z0-9._~/%+=&\-]*)?$")


def _fields_verdict(fields: list, title_hosts: set[str], trusted: frozenset = frozenset()) -> str | None:
    """校验外联详情字段，通过返回 None，否则返回待定原因。信任主机只放行 GET / HEAD。"""
    d = {}
    for k, v in fields:
        d[normalize(k).strip().lower()] = normalize(v).strip()
    extra = set(d) - _FIELD_KEYS
    if extra:
        return "详情里有不认识的字段: " + ",".join(sorted(extra))[:80]
    host = d.get("host", "").lower()
    if not host or (host not in SAFE_HOSTS and host not in trusted):
        return f"外联目标不在白名单域名或信任主机内: {host[:80]}"
    if title_hosts and title_hosts != {host}:
        return "标题与详情里的域名不一致"
    if d.get("policy", "") not in ALLOWED_POLICIES:
        return f"外联策略不在白名单内: {d.get('policy', '')[:60]}"
    method, path = d.get("method", "").upper(), d.get("path", "/") or "/"
    if not _URL_PATH.match(path) or re.search(r"(token|key|secret|sig|auth|pass)", path.split("?", 1)[-1] if "?" in path else "", re.I):
        return "请求路径格式不安全"
    if method in ("GET", "HEAD"):
        return None
    if method == "POST" and host in ("github.com", "gitlab.com") and _GIT_FETCH_PATH.match(path.split("?", 1)[0]) \
            and path.split("?", 1)[0].endswith("git-upload-pack"):
        return None   # git clone / fetch 的 smart-HTTP 协商（只读）；git-receive-pack（push）在黑名单里
    return f"外联方法 / 路径不在白名单内: {method} {path[:80]}"


def _dequoted(text: str) -> str:
    out = []
    for ln in (text or "").split("\n"):
        try:
            out.append(" ".join(shlex.split(ln.replace("\\", ""), posix=True)))
        except ValueError:
            out.append(re.sub(r"[\"']", "", ln))
    return "\n".join(out)


def _match_header(line: str):
    """返回 (是否纯套话, 内容槽位 dict, 名字列表)；不是界面套话返回 None。"""
    if line.lower() in SHORT_LABELS or _TIME_LINE.match(line):
        return True, None, []
    if _SOURCE_LINE.match(line):
        return False, {}, []   # 来源聊天名是用户起的，参与黑名单扫描，但本身不算待审内容
    for rx in _HEADER_RES:
        m = rx.match(line)
        if not m:
            continue
        d = {k: v for k, v in m.groupdict().items() if v is not None}
        names = [v for k, v in d.items() if k.startswith("name")]
        if any(w.lower() in _COMMAND_WORDS for n in names for w in n.split()):
            continue   # 「rm needs approval」这类：名字位置是命令名，不当套话
        groups = {k: v for k, v in d.items() if not k.startswith("name")}
        return (not groups), groups, names
    return None


def classify(text: str, codes: list[str] | None = None, allow_build: bool = True,
             fields: list | None = None, summary: str = "", trusted_hosts=()) -> Verdict:
    """对一张审批卡的操作描述全文做三档判定。allow_build=False 时构建安装类规则不放行。

    fields: 外联卡详情里的 (键, 值)；summary: 助手写的说明（只过黑名单，不当作操作）；
    trusted_hosts: 主人信任的主机（只用于网络访问卡，必须有详情字段且方法是 GET / HEAD）。"""
    trusted = frozenset(h for h in (normalize_trusted_host(x) for x in (trusted_hosts or ())) if h)
    raw = normalize(text or "")
    fields = [(normalize(k), normalize(v)) for k, v in (fields or [])]
    summary = normalize(summary or "")
    codes = [normalize(c) for c in (codes or []) if c and c.strip()]
    if not raw.strip():
        return Verdict("unknown", "empty", "没有读到卡片描述文本")
    if len(raw) + sum(len(c) for c in codes) > MAX_CARD_TEXT:
        return Verdict("unknown", "too_long", "卡片文本过长，不自动判定")

    # 标题与来源说明常在同一行：按问号 / 句号断句（命令里出现问号会被拆开，只会变成待定，不会误放）
    lines = [seg.strip() for ln in raw.split("\n") for seg in re.split(r"(?<=[?？。])\s*", ln) if seg.strip()]
    parsed = []
    names: list[str] = []
    for line in lines:
        hm = _match_header(line)
        if hm:
            names += hm[2]
        if hm and hm[0]:
            # Muse 固定界面文案（如「需要批准。……发送功能会暂停……」）的固定部分不参与黑名单扫描，名字部分参与
            parsed.append(("pure", line, None))
        else:
            parsed.append(("content" if hm else "line", line, hm[1] if hm else None))
    access_header = any(k == "pure" and any(mk in ln.lower() for mk in _ACCESS_MARKERS) for k, ln, _ in parsed)

    # 套话模板的固定文字是 Muse 界面，不扫；只扫模板里的可变部分、其它行、代码块、说明、详情字段值。
    # git smart-HTTP 的 /git-upload-pack 是只读拉取，扫描前去掉这个后缀以免误判为 upload。
    scan = [ln for k, ln, g in parsed if k == "line"]
    scan += [v for k, ln, g in parsed if k == "content" for v in (g or {}).values()]
    # 来源说明行（「This task comes from the side chat "…"」）里是聊天标题，和助手说明一样按英文散文扫
    prose = [ln for k, ln, g in parsed if k == "content" and g == {}]
    if summary:
        prose.append(summary)
    scan += names + codes
    # 再扫一遍 shell 去引号后的样子：~/.s"sh"/id_"rsa" 在 shell 里就是 ~/.ssh/id_rsa
    scan += [_dequoted(x) for x in list(scan)]
    prose += [_dequoted(x) for x in list(prose)]
    scan += [re.sub(r"/(git-upload-pack|info/refs)$", "", v) for k, v in fields]
    hit = blacklist_hit("\n".join(scan)) or (blacklist_hit("\n".join(prose), prose=True) if prose else None)
    if hit:
        cid, desc, frag = hit
        return Verdict("block", cid, f"命中黑名单「{desc}」: {frag}")

    commands: list[str] = []
    rules: set[str] = set()
    for kind, line, groups in parsed:
        if kind == "pure":
            continue
        if kind == "content" and groups == {}:
            continue
        if kind == "content" and all(_segment_ok(v, commands, rules, k, trusted) for k, v in groups.items()):
            continue
        rid = command_rule(line)
        if rid:
            commands.append(line)
            rules.add(rid)
            continue
        if access_header and _HOST_LINE.match(line) and _host_ok(line):
            rules.add("net_access")
            continue
        return Verdict("unknown", "unrecognized", f"有不在白名单内的内容: {line[:120]}")

    for code in codes:
        for ln in [x.strip() for x in code.split("\n") if x.strip()]:
            if ln.lower() in SHORT_LABELS:
                continue
            rid = command_rule(ln)
            if not rid:
                return Verdict("unknown", "unrecognized", f"代码块里有不在白名单内的命令: {ln[:120]}")
            rules.add(rid)
            if ln not in commands:
                commands.append(ln)

    if not fields and any(k == "content" and "share information with" in ln.lower() for k, ln, g in parsed):
        return Verdict("unknown", "egress_fields", "外联卡没有读到详情字段（Host / Method / Path / Policy），不自动处理")
    if fields:
        title_hosts = {seg.lower() for k, ln, g in parsed if k == "content" for n, seg in (g or {}).items() if n == "host"}
        why = _fields_verdict(fields, title_hosts, trusted)
        if why:
            return Verdict("unknown", "egress_fields", why)
        host = next((normalize(v).strip().lower() for k, v in fields if normalize(k).strip().lower() == "host"), "")
        rules.add("net_access" if host in SAFE_HOSTS else "trusted_host")
    elif "trusted_host" in rules:
        return Verdict("unknown", "egress_fields", "信任主机的访问卡没有读到详情字段（Method / Path / Policy），不自动处理")
    if not commands and not rules & {"net_access", "trusted_host"}:
        return Verdict("unknown", "no_operation", "卡片里没有可识别的具体操作")
    if not allow_build and rules & BUILD_RULES:
        return Verdict("unknown", "build_disabled", "构建安装类命令的自动放行已关闭: " + ",".join(sorted(rules & BUILD_RULES)))
    return Verdict("allow", ",".join(sorted(rules)), "全部内容命中白名单", commands)


# ---------------------------------------------------------------------------
# 全放行模式：除了底线（付款、发送凭据）其它卡片一律放行。底线规则比黑名单窄：
# 登录页 / session / auth 这类说法不算；目标是信任主机时，凭据底线也不拦（发给你自己的服务器）。
# ---------------------------------------------------------------------------
FLOOR = [
    ("payment", "付款 / 下单 / 绑卡", BLACKLIST[[c for c, _, _ in BLACKLIST].index("payment")][2]
     + r"|\bplace\s+(an?\s+|the\s+)?orders?\b"),
    ("credential", "发送密码 / cookie / 密钥",
     r"cookie|\btokens?\b|token=|passw|\bpwd=|secret|credential|api[_ -]?key|apikey|private[_ -]?key|access[_ -]?key"
     r"|\.ssh\b|id_rsa|id_ed25519|id_ecdsa|\.netrc|\.git-credentials|\.aws\b|\.kube\b|\.docker/config|\.npmrc"
     r"|\.pypirc|\.gnupg|keychain|keyring|1password|bitwarden|lastpass|/proc/\S*environ|\.env\b|/etc/shadow"
     r"|authori[sz]ation|\bbearer\b|hatch_|凭据|憑證|密码|密碼|密钥|密鑰|令牌|口令|パスワード"),
]
_FLOOR_RE = [(cid, desc, re.compile(rx, re.I | re.M)) for cid, desc, rx in FLOOR]
# 说明文字里的普通用法：in order to / sort order / check out the page / spend time / ledger transactions
_FLOOR_PROSE_SKIP = {"order", "orders", "ordering", "check out", "checkout", "spend", "transaction", "book"}


def floor_hit(text: str, prose: bool = False, skip: tuple = ()) -> tuple[str, str, str] | None:
    t = normalize(text)
    for cid, desc, rx in _FLOOR_RE:
        if cid in skip:
            continue
        for m in rx.finditer(t):
            frag = m.group(0).strip()
            if prose and re.sub(r"\s+", " ", frag.lower()) in _FLOOR_PROSE_SKIP:
                continue
            return cid, desc, frag[:60]
    return None


def classify_allow_all(text: str, codes: list[str] | None = None, fields: list | None = None, summary: str = "",
                       trusted_hosts=()) -> Verdict:
    """全放行模式：只查底线（付款、发送凭据），其它全部放行。"""
    raw = normalize(text or "")
    codes = [normalize(c) for c in (codes or []) if c and c.strip()]
    fields = [(normalize(k), normalize(v)) for k, v in (fields or [])]
    summary = normalize(summary or "")
    if not (raw.strip() or summary.strip() or fields):
        return Verdict("unknown", "empty", "没有读到卡片描述文本")
    if len(raw) + len(summary) + sum(len(c) for c in codes) > MAX_CARD_TEXT * 2:
        return Verdict("unknown", "too_long", "卡片文本过长，不自动判定")
    trusted = frozenset(h for h in (normalize_trusted_host(x) for x in (trusted_hosts or ())) if h)
    host = next((v.strip().lower() for k, v in fields if k.strip().lower() == "host"), "")
    skip = ("credential",) if host and host in trusted else ()
    lines = [seg.strip() for ln in raw.split("\n") for seg in re.split(r"(?<=[?？。])\s*", ln) if seg.strip()]
    prose = [ln for ln in lines if _SOURCE_LINE.match(ln)] + ([summary] if summary else [])
    strict = [ln for ln in lines if not _SOURCE_LINE.match(ln)] + codes + [f"{k}: {v}" for k, v in fields]
    strict += [_dequoted(x) for x in list(strict)]
    prose += [_dequoted(x) for x in list(prose)]
    hit = floor_hit("\n".join(strict), skip=skip) or floor_hit("\n".join(prose), prose=True, skip=skip)
    if hit:
        cid, desc, frag = hit
        return Verdict("block", cid, f"全放行模式的底线「{desc}」: {frag}")
    return Verdict("allow", "allow_all", "全放行模式：没有碰到付款 / 发送凭据底线")


# ---------------------------------------------------------------------------
# 审计日志脱敏：即使卡片原文里带了密钥，也不落盘
# ---------------------------------------------------------------------------
_REDACT = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{6,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(cookie\s*:\s*)[^\n]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authori[sz]ation\s*:\s*)[^\n]+"), r"\1[REDACTED]"),
    # token=x / "token": "x" / password: 'x'（键名可带引号）
    (re.compile(r"(?i)([\"']?\b(?:(?:access_|refresh_|id_)?token|api[_-]?key|apikey|secret|password|passwd|pwd|sig"
                r"|signature|session(?:id)?|cookie|hatch_\w+|auth|credentials?)\b[\"']?\s*[=:]\s*)"
                r"(\"[^\"]*\"|'[^']*'|[^\s&;,}]+)"), r"\1[REDACTED]"),
    # curl -u user:pass / -ubob:pw / -u "bob:pw x" / --password xxx / --token=xxx
    (re.compile(r"(?i)((?:^|\s)(?:-u|--user|--pass(?:word)?|--token|--secret|--api-key|--auth|--oauth2-bearer)"
                r"(?:\s+|=)?)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_\w{16,}|sk-[A-Za-z0-9_\-]{12,}|m2a_[A-Za-z0-9_\-]{6,}"
                r"|xox[abprs]-[A-Za-z0-9\-]{8,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,}"
                r"|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,})"), "[REDACTED]"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/_\-]{48,}={0,2}(?![A-Za-z0-9])"), "[REDACTED]"),
]


def redact(text: str, limit: int = 2000) -> str:
    t = normalize(text or "")
    for rx, rep in _REDACT:
        t = rx.sub(rep, t)
    return t[:limit]
