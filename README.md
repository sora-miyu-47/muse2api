# MUSE2API

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker" alt="Docker" />
  <img src="https://img.shields.io/badge/API-OpenAI%20Compatible-green" alt="OpenAI API Compatible" />
  <img src="https://img.shields.io/badge/License-MIT-orange" alt="License" />
</p>

将 **[muse.ai](https://muse.ai/)** 网页端的前沿多模态能力逆向工程封装为标准的 **OpenAI 兼容 RESTful API**。通过无头浏览器 CDP 协议穿透、热备 WebSocket 隧道复用与动态 Session 管理，原生支持文本对话（2~3 秒级流式首字响应）、文生图、图生图编辑、文生视频、首帧图生视频，并提供多账号池亲和轮转、全自动 48 小时会话续期与云端 VM 唤醒保活，以及配套 Chrome 一键导号扩展。

---

## 🎬 推荐：COOL AI — 电商 AI 视频与图片一站式创作

上传一张商品图，就能做出口播带货视频、剧情带货短剧和整套电商详情页。

- **口播带货视频**：自动写脚本、分镜和台词，一键生成真人口播带货视频
- **剧情带货视频**：反转短剧、对话短剧、剧情植入，自动编剧、分镜、出片
- **电商详情图**：一张白底图，一键生成首图、场景图、卖点图、细节图、对比图整套
- **AI 图片与工具**：商品精修、GIF 动图、数字人、字幕擦除、画质增强

👉 立即体验：[www.coolai.mov](https://www.coolai.mov/?utm_source=github&utm_medium=readme&utm_campaign=muse2api)

### 🎬 Recommended: COOL AI — AI video & image studio for e-commerce

Upload one product photo and get talking-head sales videos, story-style ad shorts and a complete product detail-page image set.

- **Talking-head sales videos**: script, shots and lines written for you, generated in one click
- **Story ads**: twist, dialogue and product-placement shorts, scripted and storyboarded automatically
- **Product detail images**: hero, lifestyle, selling-point, detail and comparison images from one white-background photo
- **More tools**: product retouching, GIF animations, digital humans, subtitle removal, upscaling

👉 Try it: [www.coolai.mov](https://www.coolai.mov/?utm_source=github&utm_medium=readme&utm_campaign=muse2api)


---


## v1.6.12 升级事项

- **生成的图片恢复原图尺寸（#62）**：muse.ai 从 2026-11-19 起聊天里只显示约 498px 的缩略图，原图要点开图片查看器才会加载。图片任务现在会自动打开查看器取原图（实测 1344x1792）；取不到时仍返回缩略图，并在服务日志写一条提示。只更新服务即可，插件不用升级。

Generated images are full size again (#62): image tasks open muse.ai's image viewer to fetch the original instead of the ~498px chat thumbnail. Update the service only; the extension is unchanged.


## v1.6.11 升级事项

- **扩展必须手动升级至 1.0.3**：先更新服务，从管理页下载本实例的扩展包，替换原扩展目录后在浏览器扩展管理页重新加载；不同浏览器个人资料分别升级。无痕/InPrivate 使用时，需允许扩展在无痕窗口运行。导入只表示保存登录态，请继续测试账号。
- **检查更新不会自动改动代码或重启**：面板显示真实已安装版本和远端状态，由管理员手动确认升级；已有排队或运行任务时拒绝升级。镜像部署可设置 MUSE2API_MANAGED_DEPLOYMENT=1，通过重建镜像更新。
- **排队与生成分开计时**：管理页可设置独立排队时限，默认 3600 秒，0 表示不限；图片长任务仍推荐异步任务接口。
- **视频库使用缩略图**：源码部署需安装 FFmpeg；Docker 用户请重建镜像。仅更新 Python 源码不会为旧容器安装系统依赖。

Extension 1.0.3 requires a manual reload in every browser profile. Update checks are read-only; confirm upgrades explicitly. Rebuild Docker images for FFmpeg thumbnail support.


## 🌟 核心特性

- 💬 **标准对话接口（Chat Completions & Responses API）**
  - 完全兼容 `/v1/chat/completions` 与新版 Codex 默认使用的 `/v1/responses` 标准协议。
  - 原生支持 SSE 流式打字机输出（`stream=True`）与同步完整返回，内置热标签页与 Noise WebSocket 隧道亲和复用，**连续对话首字延迟仅需 2~3 秒**。
  - 支持多轮对话上下文、System Prompt 设定。
  - 内置模型智能别名映射，`gpt-4o`、`gpt-5`、`claude-sonnet-4`、`deepseek-chat` 等常用模型名自动路由。
- 🎨 **高质量生图与图像编辑（Images Generations & Edits）**
  - 完全兼容 `/v1/images/generations`（文生图）与 `/v1/images/edits`（图生图/参考图编辑）接口。
  - 支持 `1:1`、`16:9`、`9:16`、`4:3`、`3:4` 等多画幅生成，支持单图或多图参考直传与去水印纯净输出。
  - 支持 `url` 直链或 `b64_json` 两种返回格式，内置纯文本拒答秒级快速检测，杜绝队列死锁。
  - 图生图仅返回本次新生成的媒体：排除上传预览与历史附件，下载绑定选中的结果；参考图上传或提示词发送未确认时明确报错，不再静默返回原图。
- 🎬 **文生视频 / 图生视频（Videos）**
  - 原生对接 Muse 顶配视频生成模型，可传递 5 秒 / 6 秒 / 8 秒 / 10 秒的时长请求（实际成片时长以 Muse 上游输出为准）及 `9:16` 竖屏 / `16:9` 横屏视频生成。
  - 支持上传单张首帧参考图，或通过 `images` 数组上传多张内容与风格参考图；多图模式以第一张作为主要起始画面。
  - 异步任务架构（`/v1/videos` 创建任务 + `/v1/videos/{task_id}` 状态轮询）。
  - 内置媒体资源服务 `/v1/media/{filename}`，自动持久化存储生成的 MP4 / WebP 资源。
- ⚡ **真多账号并行并发（Multi-Account Parallel Execution）**
  - 基于 Chromium 原生 `Target.createBrowserContext` 隐身隔离容器，多任务在独立沙箱中并发执行。
  - 多账号同时生图、生视频、流式对话零互相阻塞，Cookie 与 Session 100% 隔离绝不串扰。
  - 内置智能账号冲突调度器，同账号自动互斥防踩踏，多账号自动并行跑满。
  - 可通过 `MUSE2API_CONCURRENCY` 随机器性能灵活调大并发上限（默认 2 并发）。
- 🔄 **多账号池与热连接亲和调度**
  - 支持导入无上限的 Muse 账号矩阵。
  - 基于热连接亲和（Warm-Tab Affinity）与 LRU 策略智能分发，兼顾 2 秒级极速响应与多号均衡消耗。
  - 遇到单号额度耗尽或会话异常时，自动标记并 0 秒无感故障转移至备用健康账号。
- 🛡️ **会话状态检测与云端 VM 保活**
  - 后台请求 `/api/session` 检查会话，并按需调用 `/api/hatch/vm/wake` 唤醒工作区；配置账号代理后，这些请求与浏览器使用同一出口。
  - 只保存上游实际返回的 Cookie 和到期时间，不会因检测成功而虚增有效期。上游未续签、会话被撤销或账号受限时，仍需在官网确认并重新导入。
- 🌐 **账号独立 HTTP / SOCKS5 代理**
  - 每个账号可配置不同的 HTTP 或 SOCKS5 代理及认证信息，并发任务的浏览器上下文与会话请求按账号隔离；代理失败不会静默回退直连。
- 🧩 **配套 Chrome 一键导号扩展**
  - 无需手工 F12 抓包，点一下扩展图标即刻将当前浏览器登录态（含 `HttpOnly` 核心 Cookie 与真实过期时间）提取并安全推送至账号池。
- 🖥️ **现代化深色运维面板（Web Console）与实时在线热升级**
  - 内置开箱即用的 Web UI，支持实时查看服务健康度、账号池额度与状态、一键全池保活、任务进度回放、媒体库管理与在线接口调试。
  - 媒体库的视频列表仅懒加载 JPEG 缩略图，点击封面或「打开」才加载该视频，关闭预览即释放播放器。缩略图由 FFmpeg 按需生成，缓存在 `data/thumbnails/`，删除媒体时同步清理；旧视频无需重新生成。Docker 镜像已包含 FFmpeg，手动部署需安装 `ffmpeg`；缺少依赖或视频损坏时显示播放占位，不会回退为预加载原视频。
  - **全网节点实时更新广播与一键升级**：当官方 GitHub 仓库发布新版本或修复时，所有已部署节点的管理后台顶部会自动弹出更新通知横幅，点击 **「⚡ 一键在线升级并重启」** 即可自动拉取最新代码并平滑重启（自动保留本地 `.env` 配置与账号数据）。

---

## 🚀 极速部署

### 方式一：Docker Compose（推荐，一行命令开箱即用）

1. **克隆代码并进入目录**：
   ```bash
   git clone https://github.com/czg86389-hub/muse2api.git
   cd muse2api
   ```

2. **配置环境变量（可选）**：
   ```bash
   cp .env.example .env
   # 按需编辑 .env，建议修改 MUSE2API_KEY 为你自己的管理密钥
   ```

   Docker Compose 会读取 `.env` 中的 `MUSE2API_KEY`，不会再被 Compose 文件中的示例值覆盖。

3. **启动容器**：
   ```bash
   docker compose up -d
   ```

4. **访问管理面板**：
   打开浏览器访问：`http://<你的服务器IP>:18610/admin?key=<你的MUSE2API_KEY>`

---

### 方式二：裸机 / VPS 部署（Ubuntu / Debian）

1. **安装系统依赖与 Chromium**：
   ```bash
   sudo apt-get update
   sudo apt-get install -y chromium ffmpeg fonts-wqy-zenhei python3 python3-pip python3-venv
   ```

2. **配置 Python 虚拟环境**：
   ```bash
   cd /opt/muse2api
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **配置 systemd 服务**：
   ```bash
   sudo cp deploy/muse2api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now muse2api
   ```

4. **Nginx 反向代理配置（重要：防止 502 超时与流式卡顿）**：
   如使用 Nginx / 宝塔 / 1Panel 反代，务必将 `proxy_read_timeout` 调大至 `600s` 并关闭 `proxy_buffering`（详见 `deploy/nginx.example.conf`）：
   ```nginx
   location / {
       proxy_pass http://127.0.0.1:18610;
       proxy_read_timeout 600s;      # 避免生图/视频耗时较长被 Nginx 报 502 Bad Gateway
       proxy_send_timeout 600s;
       proxy_buffering off;          # 保证 SSE 对话流式打字机 0 延迟吐字
       client_max_body_size 200M;    # 支持视频/音频等大参考素材上传
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }
   ```

---

## 🧩 账号导入（Chrome 扩展 / 油猴脚本）

> **v1.6.6 用户请务必手动升级插件：Chrome/Edge 扩展最低 1.0.2，油猴脚本最低 1.1.2。**
> 服务端更新不会自动替换已加载的扩展。下载本 Release 的 ZIP，覆盖原扩展目录文件，在 chrome://extensions / edge://extensions 点击“重新加载”；不同个人资料分别升级。弹窗标题旁应显示 **v1.0.2**。
> [下载扩展 1.0.2](https://github.com/czg86389-hub/muse2api/releases/download/v1.6.6/muse2api-chrome-extension-v1.6.6.zip)。只有 hatch_sess 是导入必要项；hatch_vml 和 hatch_gw 缺失不能据此判定未登录。重新导入后再点击账号“测试”。
>
> **Manual extension upgrade required:** extension 1.0.2+ / userscript 1.1.2+. A server update does not upgrade unpacked extensions. Replace files in the original folder and click Reload, separately for every browser profile.


### 方式 A：Chrome / Edge 扩展
项目内置了专用 Chrome 导号扩展（目录位于 `extension/`），告别复杂的 F12 Cookie 提取：

1. 打开 Chrome / Edge 浏览器，访问 `chrome://extensions`，开启右上角的 **「开发者模式」**。
2. 点击 **「加载已解压的扩展程序」**，选择本项目中的 `extension` 目录。
3. 在该浏览器中登录 [muse.ai](https://muse.ai/) 至聊天主界面。
4. 点击浏览器右上角插件图标，填入你的服务地址（例如 `http://1.2.3.4:18610`）和 `MUSE2API_KEY`。
5. 点击 **「读取并导入」**，秒级同步入库！

### 方式 B：Tampermonkey 油猴脚本（跨浏览器免安装扩展）
对于不想开启开发者模式或使用 Firefox / Safari 的用户，推荐直接使用油猴脚本一键安装：

👉 **[⚡ 点击一键安装油猴脚本 (Raw UserJS)](https://raw.githubusercontent.com/czg86389-hub/muse2api/main/tools/muse2api_cookie_importer.user.js)**

1. 在浏览器安装 [Tampermonkey](https://www.tampermonkey.net/) 插件。
2. 点击上方 **「⚡ 点击一键安装油猴脚本」** 链接，Tampermonkey 将自动弹出安装窗口，点击「安装」即可（无需手动复制粘贴代码）。
3. 打开 [muse.ai](https://muse.ai/) 网页，右下角将出现 **「⚡」** 悬浮图标，点击即可展开配置面板并一键推送入库（亦支持自动复制剪贴板兜底）。

---

## 📖 API 调用示例

### 账号独立代理 / Per-account proxy

在账号池点击账号旁的 **代理 / Proxy**：

1. 选择 **指定代理 / Use a proxy**，直接粘贴完整链接，例如 `socks5://your-user:your-password@proxy.example.com:1080`。用户名和密码会自动解析；也可展开可选的手动认证项分开填写。
2. 立即点击 **测试连通性 / Test connection**，无需先保存或重新打开窗口。结果分别显示代理连通性、出口 IP 与 Muse 会话状态；测试不同的未保存配置不会改变账号已保存的代理、健康状态或代理检测记录；测试内容与已保存代理一致时会更新该代理的检测记录。确认后再点击 **保存 / Save**，下次请求生效。
3. 继续使用账号的 **测试 / Test** 按钮，确认浏览器能加载聊天输入框。会话验证成功不保证上游一定允许某次图片或视频生成。

支持 HTTP 代理端点（可选 Basic 认证）与 SOCKS5 代理端点（可选用户名/密码认证），例如 `http://proxy.example.com:8080`、`socks5://proxy.example.com:1080` 或 `socks5h://proxy.example.com:1080`。SOCKS5 的目标主机名经代理解析；HTTPS 网站照常支持。**HTTPS 代理端点、VLESS、VMess 与订阅链接暂不支持直接填写**；使用 Clash/Mihomo 等工具时，应填部署服务器可访问的 HTTP 或 SOCKS5 代理入口。`127.0.0.1:7890` 指的是部署服务器自身，不是导入 Cookie 的电脑。没有配置代理的旧账号保持原有网络行为。

聊天、生图、视频、浏览器下载、账号检测、额度查询、会话续签与 VM 唤醒使用账号代理。代理断线、认证失败或浏览器上下文创建失败会报告错误，**不会静默回退直连**。账号切换同时切换代理。外部参考图在账号选取前按现有安全策略预取，继续执行公网地址、重定向与 DNS 重绑定防护，不承诺任意参考图 URL 都通过账号代理。

账号忙碌时修改代理会返回 HTTP 409，请等待当前任务结束。修改后，下次请求会重建连接，不复用旧节点。代理连通性与账号会话是不同状态：HTTP 407、连接超时不会直接把 Cookie 标成失效；代理测试也不会覆盖账号已有的认证结果。

完整链接中的认证信息优先于手动认证字段；用户名或密码中的 `@`、`#`、`/` 等特殊字符应使用 URL 百分号编码。保存后地址规范化为不含认证信息的形式，重新打开不会回显密码。

代理密码与 Cookie 一起保存在本机 `data/accounts.json`，应保护此目录及备份。接口、日志和页面不回显密码。修改时地址与用户名不变，密码留空表示保留；改变地址或用户名时应重新输入认证密码。选择 **默认网络 / Default network** 或 **移除代理 / Remove proxy** 清除配置并恢复默认网络。

管理 API 示例（需鉴权）：

```http
PATCH /admin/accounts/{account_id}
Content-Type: application/json
Authorization: Bearer <MUSE2API_KEY>

{
  "proxy": {
    "server": "http://proxy.example.com:8080",
    "username": "your-proxy-user",
    "password": "your-proxy-password"
  }
}
```

省略 `proxy` 不修改设置；提交 `{"proxy": null}` 移除代理。`POST /admin/accounts` 也接受同一 `proxy` 对象，包括为本次批量导入设置相同代理。响应仅包含服务器、用户名和 `has_password`，不返回密码。

```http
POST /admin/accounts/{account_id}/proxy/test
Authorization: Bearer <MUSE2API_KEY>
```

不带请求体时测试已保存代理。要测试尚未保存的代理，发送 `Content-Type: application/json` 和 `{"proxy":{"server":"socks5://your-user:your-password@proxy.example.com:1080"}}`；`server` 同样支持完整 HTTP/SOCKS5h 链接，旧版分栏认证仍兼容。响应 `tested_saved_proxy=false` 表示测试内容不同于当前保存代理，账号保存内容不变；为 `true` 时会更新当前代理的检测记录。

从 1.6.8 升级后，之前未保存检测结果的账号需要重新点击一次“测试连通性”。空记录会显示“代理未测试”，完成实际检测后才显示“代理已连通”或“代理未通过”，不会自动将未知状态标成成功。

先测试再保存时，服务端可沿用当前进程内 5 分钟内的实测记录；必须是同一账号、相同节点与认证、相同登录 Cookie。改动配置、换 Cookie、过期或服务重启后不会沿用旧成功。只复用实际结果，测试失败不会被改成成功；这不代表账号浏览器或生成能力已验证。

该测试通过所选代理访问无 Cookie 的 HTTPS 出口检测，再验证 Muse 会话；返回的 `proxy_reachable`、`exit_ip`、`session_ok` 与 `workspace_status` 分别表示各层结果。既无临时配置又无已保存代理时返回 400，账号忙碌时返回 409。此操作不生成内容，也不消耗图片/视频生成额度。

**English:** Each account can use its own HTTP proxy with optional Basic authentication or a SOCKS5 proxy with optional username/password authentication. Select **Use a proxy**, paste a full URL such as `socks5://your-user:your-password@proxy.example.com:1080`, and click **Test connection** immediately. Saving and reopening are not required. Tests of a different unsaved route leave the saved route, account health and saved test status unchanged. Testing the exact saved configuration updates its connectivity record; click **Save** separately to apply the route. Manual credential fields remain optional. Credentials in the URL take precedence; percent-encode special characters. Both `socks5://` and `socks5h://` proxy origins are accepted, and target hostnames are resolved by the proxy. HTTPS sites are supported; HTTPS proxy endpoints, VLESS/VMess and subscription URLs are not supported directly. The proxy address must be reachable from the deployment server. A proxy failure never falls back to direct access. Unconfigured accounts retain their existing network behavior. Active accounts cannot change proxies (HTTP 409); the next request recreates the context after a saved change. Keep the password blank only to preserve it with an unchanged server and username. Neither API responses nor logs expose it. Saving the exact configuration may adopt a server-observed result from the last five minutes in the same process, bound to the account, route, credentials and cookies. Changed/expired inputs never inherit success, and failed results remain failed. The test API accepts an optional `{"proxy":{"server":"socks5://your-user:your-password@proxy.example.com:1080"}}` body for a draft test; an empty body retains saved-proxy testing. The proxy test reports connectivity, egress IP and Muse session status separately; it does not prove generation capability or replace the account's browser test.

---

所有受保护接口均需在 Header 中携带：
```http
Authorization: Bearer <你的MUSE2API_KEY>
```

### 1. 对话补全（Chat Completions）

```bash
curl -X POST "http://localhost:18610/v1/chat/completions" \
  -H "Authorization: Bearer m2a_your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "muse-spark",
    "messages": [
      {"role": "user", "content": "写一首关于赛博朋克与霓虹夜雨的七言绝句"}
    ],
    "stream": false
  }'
```

#### 按 user 定向对话与人设 / Per-user routing and personas

带上 OpenAI 标准的 `user` 字段后，请求固定落到该 user 绑定的账号，并接着该 user 自己的 muse 线程聊：人设（自定义 system 提示词）只在新线程的第一条消息里注入一次，之后只发送新的消息。账号繁忙时排队，超时返回 429，绝不切换到其它账号。不带 `user` 的请求行为不变。详见 [CHAT_USERS.md](CHAT_USERS.md)。

With the standard OpenAI `user` field, a request always goes to that user's bound account and continues that user's own muse thread. The persona is injected once, when the thread is created; follow-ups send only the new turns. A busy account queues the request and then returns 429; it never switches accounts. Requests without `user` are unchanged. See [CHAT_USERS.md](CHAT_USERS.md).

```bash
curl -X PUT "http://localhost:18610/admin/chat-users/alice" \
  -H "Authorization: Bearer m2a_your_secret_key" -H "Content-Type: application/json" \
  -d '{"persona": "你是 Alice 的私人助理，名叫小A。"}'

curl -X POST "http://localhost:18610/v1/chat/completions" \
  -H "Authorization: Bearer m2a_your_secret_key" -H "Content-Type: application/json" \
  -d '{"model": "muse-spark", "user": "alice", "messages": [{"role": "user", "content": "你好"}]}'
```

### 2. 文生图（Image Generation）

```bash
curl -X POST "http://localhost:18610/v1/images/generations" \
  -H "Authorization: Bearer m2a_your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "muse-image",
    "prompt": "一只穿着反重力宇航服的机械柴犬，电影级光影，8k分辨率",
    "size": "16:9",
    "response_format": "url"
  }'
```

**响应示例**：
```json
{
  "created": 1790148495,
  "data": [
    {
      "revised_prompt": "一只穿着反重力宇航服的机械柴犬，电影级光影，8k分辨率",
      "url": "http://localhost:18610/v1/media/img_abc123.webp",
      "kind": "image",
      "bytes": 54210
    }
  ]
}
```

多图参考使用 `images` 数组（最多 10 个素材；单个不超过 40 MiB、合计不超过 100 MiB，详见下方「参考素材」）；服务会按数组顺序逐张上传，并在全部附件得到网页确认后才发送提示词。`images` 不可与 `image` / `reference_image` 等旧版单图字段混用：

```bash
curl -X POST "http://localhost:18610/v1/images/generations" \
  -H "Authorization: Bearer m2a_your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "muse-image",
    "prompt": "结合第一张图的主体与第二张图的配色生成海报",
    "images": [
      {"url": "https://example.com/subject.png"},
      {"url": "https://example.com/style.png"}
    ],
    "response_format": "url"
  }'
```

`/v1/images/edits` 的 multipart 请求可以重复提交同名的 `image` 字段：

```bash
curl -X POST "http://localhost:18610/v1/images/edits" \
  -H "Authorization: Bearer m2a_your_secret_key" \
  -F "prompt=结合两张参考图生成一张新图" \
  -F "image=@subject.png" \
  -F "image=@style.png"
```

### 3. 文生视频 / 图生视频（Videos）

- **第一步：创建生成任务**
  ```bash
  curl -X POST "http://localhost:18610/v1/videos" \
    -H "Authorization: Bearer m2a_your_secret_key" \
    -H "Content-Type: application/json" \
    -d '{
      "prompt": "金色的枫叶在微风中轻盈飘落，阳光穿透树梢",
      "duration": 5,
      "size": "16:9"
    }'
  ```
  返回任务 ID：`{"id": "task_xyz789", "status": "queued"}`

  多图参考视频在同一个请求中使用有序的 `images` 数组；这里支持的是多张图片作为视频参考，不支持上传视频文件作为参考：
  ```bash
  curl -X POST "http://localhost:18610/v1/videos" \
    -H "Authorization: Bearer m2a_your_secret_key" \
    -H "Content-Type: application/json" \
    -d '{
      "prompt": "让第一张图的主体在第二张图的场景与配色中运动",
      "images": [
        {"url": "https://example.com/start.png"},
        {"url": "https://example.com/style.png"}
      ],
      "duration": 6,
      "size": "16:9"
    }'
  ```

- **第二步：轮询任务进度**
  ```bash
  curl "http://localhost:18610/v1/videos/task_xyz789" \
    -H "Authorization: Bearer m2a_your_secret_key"
  ```
  完成时返回：
  ```json
  {
    "id": "task_xyz789",
    "status": "succeeded",
    "progress": 100,
    "result": {
      "url": "http://localhost:18610/v1/media/vid_xyz789.mp4"
    }
  }
  ```

---

## 🎞️ 参考素材：图片 / 视频 / 音频 / 文档

生图、图像编辑、图片任务与视频接口都可以附带参考素材，限制与 muse.ai 网页端一致：

| 项目 | 限制 |
|---|---|
| 数量 | 每次最多 10 个（所有字段合计） |
| 单个大小 | 40 MiB；合计 100 MiB |
| 图片 | jpg / png / gif / webp / heic / heif / avif |
| 视频 | mp4 / mov / webm / 3gp，时长不超过 120 秒（mp4/mov 会预先校验） |
| 音频 | mp3 / wav / m4a / ogg / flac / aac / opus |
| 文档 | pdf / doc / docx |

- JSON 字段：`images`（可混放任意素材）、`videos`、`audios`、`files`，按此顺序依次上传；每项可以是 URL、Data URL、Base64，或 `{"url": ...}` / `{"video_url": ...}` / `{"audio_url": ...}` 对象。
- 类型取 Data URL / 响应头 / multipart 声明的 MIME；声明为空或 `application/octet-stream` 时按文件头识别。
- `/v1/images/edits` 的 multipart 可重复提交 `image`、`video`、`audio`、`file` 字段。
- 视频任务若第一个素材是图片，以它作为主要起始画面；成品绝不会是本次上传的素材本身（按内容哈希排除）。

```bash
curl -X POST "http://localhost:18610/v1/videos"   -H "Authorization: Bearer m2a_your_secret_key"   -H "Content-Type: application/json"   -d '{
    "prompt": "参考视频的运镜节奏，配合音频的情绪，生成一段新的城市夜景",
    "videos": [{"url": "https://example.com/ref.mp4"}],
    "audios": [{"url": "https://example.com/bgm.mp3"}],
    "duration": 8,
    "size": "16:9"
  }'
```

Nginx 反代需把 `client_max_body_size` 调到 200M 左右，否则大素材会被 413 拒绝。

---

## ⚙️ 环境变量配置一览

| 变量名 | 默认值 | 作用与说明 |
|---|---|---|
| `MUSE2API_KEY` | 自动生成 | 管理控制台与 API 鉴权密钥（以 `m2a_` 开头） |
| `MUSE2API_HOST` | `127.0.0.1` | 监听 IP（Docker 内建议 `0.0.0.0`） |
| `MUSE2API_PORT` | `18610` | 服务运行端口 |
| `MUSE2API_PUBLIC_BASE` | `空` | 对外完整 URL 前缀，留空时前端自动识别访问来源 |
| `MUSE2API_CHROMIUM` | `chromium` | 浏览器可执行程序完整路径 |
| `MUSE2API_CDP_PORT` | `19210` | 内部 CDP 调试通信端口 |
| `MUSE2API_CONCURRENCY` | `2` | 最大并发生成任务数（支持随服务器资源自由调高，默认 2） |
| `MUSE2API_IMAGE_TIMEOUT` | `240` | 生图超时上限（秒） |
| `MUSE2API_VIDEO_TIMEOUT` | `600` | 生视频超时上限（秒） |
| `MUSE2API_CHAT_TIMEOUT` | `300` | 对话生成超时上限（秒） |
| `MUSE2API_CHAT_USER_ROUTING` | `1` | 按请求里的 `user` 字段定向账号与线程；`0` 忽略 `user`，全部走原来的无状态轮转 |
| `MUSE2API_CHAT_USER_AUTO_BIND` | `1` | 首次出现的 `user` 自动绑定一个账号；`0` 时只接受管理接口里配置过的 user |
| `MUSE2API_CHAT_USER_EXCLUSIVE` | `1` | 每个账号最多绑定一个 `user`；`0` 时可共用账号（各自仍是独立线程） |
| `MUSE2API_CHAT_USER_QUEUE_TIMEOUT` | `120` | 绑定账号繁忙时最多排队秒数，超时返回 429，不切换账号；`0` 不排队 |
| `MUSE2API_REF_IMAGE_LOCAL_FILES` | `0` | 默认禁止读取服务器本地路径；仅可信单用户部署可显式设为 `1` 恢复 |
| `MUSE2API_REF_IMAGE_PRIVATE_FETCH` | `0` | 默认仅允许公网 URL，并逐跳检查 DNS/重定向、固定已检查 IP、不使用环境代理；显式设为 `1` 才允许私网/本机 URL |
| `MUSE2API_AUTO_APPROVE` | `0` | 审批卡自动处理总闸门；`1` 才允许开启（管理页还能再关），见下文「审批卡自动批准」 |
| `MUSE2API_AUTO_APPROVE_DRY_RUN` | 空 | `1` 强制演练（只记日志不点）；`0`/空 由管理页决定，管理页默认演练 |
| `MUSE2API_AUTO_APPROVE_ACCOUNTS` | 空 | 允许看守的账号 id 或备注名（逗号分隔）；空 = 全部账号 |
| `MUSE2API_AUTO_APPROVE_BUILD` | 空 | `0` 强制不放行构建安装类命令（uv/pip/npm/make/pytest 等）；空 = 由管理页决定（默认放行） |
| `MUSE2API_AUTO_APPROVE_ALL` | 空 | `0` 强制关闭全放行模式；空 = 由管理页决定（默认关）。见下文「全放行模式」 |
| `MUSE2API_AUTO_APPROVE_HOSTS` | 空 | 信任主机（主机名或 IP，可带端口，逗号分隔），和管理页填的合在一起；访问这些主机的网络卡只放行 GET / HEAD |

两个开关默认均为 `0`：所有生图、图像编辑、图片任务及视频接口都禁止服务器本地路径和私网/本机 URL。Data URL、有效 Base64 和公网 URL 正常使用。只有确认调用方可信且确有需要时，才显式设为 `1` 恢复对应旧能力。
策略拒绝、下载失败、MIME 或大小不合规都会在提交任务前返回 HTTP 400，不会创建一个随后才失败的后台任务。

参考图安全回归检查（模拟 DNS 和 HTTP，无真实网络或账号）：

```bash
python tests/test_ref_image_safety.py
```

---

## 🛂 审批卡自动批准

小号在自己的 Muse 会话里执行命令时，页面会弹出 **Allow / Deny 审批卡**（例如 `git clone`、`uv`、`whoami`、`curl`）。没人点，生成就一直卡到超时；而这些卡片只有网关的浏览器能看到。开启本功能后，网关在**等待生成的过程中**每约 1.2 秒扫描一次当前页面，按规则处理审批卡：

| 档位 | 条件 | 处理 |
|---|---|---|
| 放行（allow） | 卡片里每一行都是 Muse 固定界面文案，或**整行完全匹配**白名单命令 / 白名单域名 | 只点**单次放行**按钮（`Allow` / `Allow once` / `允许一次` …），从不点 `Always allow`、`Allow for this task`、`Allow all once` 这类扩大授权的按钮 |
| 拦截（block） | 全文任意位置命中黑名单 | **永不自动批准**，什么都不点，停住等人工处理 |
| 待定（unknown） | 其他所有情况：有一行认不出来、没有具体操作、只有扩权按钮、详情折叠读不全、没有 Muse 审批卡标记、卡片区域过大 | 不点，记日志，生成继续等待（不会因为卡片在等而提前断线） |

审批卡是 Muse 的安全边界，自动批准等于拆掉一层保险，所以白名单宁窄勿宽，黑名单优先于白名单。另外几条硬规矩：

- 只有带 Muse 审批卡标记（`data-testid="hatch-inline-approval-card"`）的卡片才可能被点；页面上长得像卡片但没标记的块，只记一条「待定」、不记文字。
- 详情折叠着（有「Show approval details」或批次项未展开）就读不全操作，一律待定。真批模式下会尝试展开一次，展开失败仍然待定。
- 演练模式下**从不点放行 / 拒绝按钮**；只会点一次「See details」展开详情（等于看一眼，不是审批动作），否则读不到 Host / Method / Path。
- 每轮扫描最多点一次；批次卡等 Muse 重画后再点下一项。
- 按钮类型以看得见的文字为准，`aria-label` 只用于纯图标按钮。

### 白名单（放行）

| 规则 | 内容 |
|---|---|
| `readonly` | 查看类命令：`whoami` `id` `pwd` `ls` `cat` `head` `tail` `wc` `stat` `du` `df` `ps` `uname` `date` `which` `echo` `grep`/`rg` `find`（不含 `-exec`/`-delete`）等 |
| `version` | `python` / `node` / `npm` / `uv` / `git` / `pip` / `go` / `cargo` 等 `--version` |
| `git_read` | `git status/log/diff/show/branch(不删)/remote -v/rev-parse/ls-files/fetch/pull/submodule update` |
| `git_clone` | `git clone https://github.com/...` 或 `https://gitlab.com/...`；URL 不能带账号密码，不接受 ssh |
| `uv` / `pip` 【构建安装】 | `uv sync/lock/venv/add/tree`、`uv pip install <包名>`、`pip install <包名>`：只允许包名，禁止 URL、`git+`、`-r/-e/-c` 文件、`-i/--index-url`、自定义解释器路径 |
| `npm` 【构建安装】 | `npm ci`、`npm install [包名]`、`npm test`、`npm run build/test/lint`、`pnpm install`、`yarn install`；只认列出的选项，禁止 URL 包 |
| `build` 【构建安装】 | `python -m venv`、`pytest`、`make build/test/check/lint/all`、`cargo build/check/test`、`go build/test/vet` |
| `http_get` | `curl` / `wget` 只对白名单域名做 GET 下载；禁止 `-d -F -T -X -H -u -b -K`、管道、写隐藏文件或上级目录 |
| `net_access` | 网络外联卡（见下）：`Host` 在白名单域名内、`Policy` 是 `tool.exec`、`Method` 是 `GET`/`HEAD`，或是 github.com / gitlab.com 上 `POST …/git-upload-pack`（git clone / fetch 的只读协商）；`git-receive-pack`（push）在黑名单 |
| `trusted_host` | 网络访问卡（如 "Allow Muse to access 1.2.3.4?"）：`Host` 是你自己填的**信任主机**（管理页「信任主机」或 `.env` 的 `MUSE2API_AUTO_APPROVE_HOSTS`），必须读到详情字段，`Policy` 是 `tool.exec`，`Method` 只能是 `GET`/`HEAD`。助手说明里提到发凭据 / 删除 / 发消息等仍按黑名单拦截 |

白名单域名：`github.com`、`api.github.com`、`raw.githubusercontent.com`、`codeload.github.com`、`objects.githubusercontent.com`、`gitlab.com`、`pypi.org`、`files.pythonhosted.org`、`registry.npmjs.org`、`nodejs.org`、`www.python.org`、`docs.python.org`、`crates.io` 系列、`proxy.golang.org`、`sum.golang.org`、`go.dev`。

任何命令只要带了 `;` `&` `|` `>` `<` `$` 反引号、`$( )`、环境变量前缀（`FOO=1 cmd`）或未加引号的通配符（`*` `?` `[ ]`），一律不放行。每个命令只认上表里列出的选项，其它选项（例如 `--script-shell`、`--ext-diff`、`git -c`、`rg --pre`）一律不放行。

> **构建安装类的风险**：标了【构建安装】的规则会执行项目或依赖自带的脚本（npm 生命周期脚本、`setup.py`、Makefile、`build.rs`、测试代码），网关看不到这些内容。这组按需求默认放行；不需要时在管理页取消「放行构建安装类命令」，或在 `.env` 设 `MUSE2API_AUTO_APPROVE_BUILD=0`。

### 黑名单（永不自动批准）

| 类别 | 例子 |
|---|---|
| `delete` 删文件 / 删数据 | `rm`、`rmdir`、`shred`、`truncate`、`git clean`、`git reset --hard`、`find -delete`、`DROP TABLE`、delete / remove、删除 / 清空 |
| `message` 对外发消息 / 发邮件 / 分享 | send、email、Gmail、Slack、Telegram、post to、publish、share、`git push`、upload、发送 / 发邮件 / 分享 / 转发 |
| `credential` 读取或发送凭据 | cookie、token、password、secret、API key、`.ssh`、`id_rsa`、`.env`、`.netrc`、`printenv`/`env`、Authorization、Bearer、login、session、`hatch_*`、密码 / 令牌 / 登录 |
| `payment` 付款 / 绑卡 | pay、purchase、buy、checkout、order、billing、credit card、subscribe、book a flight、付款 / 支付 / 下单 / 绑卡 |
| `account` 改账号设置 / 改绑账号 | settings、account、profile、revoke、pair、connect your …、change password/email、改绑 / 绑定 / 账号 / 设置 |
| `remote_script` 来路不明的远程脚本 | `curl … \| sh`、`wget … \| bash`、`bash <(curl …)`、`eval`、`base64 -d`、`npx`、`uvx`、`pip install git+…` |
| `privilege` 提权 / 远程登录 / 持久化 | `sudo`、`su`、`ssh`、`scp`、`nc`、`crontab`、`systemctl`、`chown`、`chmod 777`、`kill` |

完整规则见 [`approval_rules.py`](approval_rules.py)。

### 全放行模式

管理页「审批卡」页签勾选「全放行模式」后，网关不再看白名单和黑名单：任何网址、IP、命令、删除、发消息的卡都点单次放行（「Allow once」/「Allow」，从不点「Always allow」）。只有两类底线仍然不点，留给你手动处理：

| 底线 | 例子 |
|---|---|
| `payment` 付款 / 下单 / 绑卡 | pay、purchase、buy、place an order、checkout、信用卡、充值、订阅 |
| `credential` 发送密码 / cookie / 密钥 | password、cookie、token、secret、API key、`~/.ssh`、`.env`、Authorization。目标是信任主机时不拦（发给你自己的服务器） |

说明文字里的普通用法（in order to、check out the page、login page）不算底线。没有 Muse 标记、文字过长、详情展开失败的卡仍然只记日志不点。审计日志照常记录，判定显示为 `allow_all`。

> **风险**：全放行后没有人工把关。小号浏览的网页如果藏了恶意指令，助手可能被诱导去删数据或发消息，网关不会拦。紧急关闭：取消勾选「全放行模式」或关总开关，立即生效。

### 怎么开、怎么关

开关分两层，**任何一层说「关」或「演练」就按更安全的一层执行**：

1. `.env`（Docker 部署时在 `docker-compose.yml` 同目录的 `.env`）：
   ```bash
   MUSE2API_AUTO_APPROVE=1            # 总闸门；0 = 完全关闭
   MUSE2API_AUTO_APPROVE_DRY_RUN=     # 留空由管理页决定；1 = 强制演练
   MUSE2API_AUTO_APPROVE_ACCOUNTS=    # 留空 = 全部账号；或填 小明,小红,小丽,小刚
   MUSE2API_AUTO_APPROVE_BUILD=       # 0 = 构建安装类命令不自动放行
   MUSE2API_AUTO_APPROVE_HOSTS=       # 你自己的服务器，例如 1.2.3.4,my.example.com:8443（只放行 GET / HEAD）
   ```
   改完重启：`docker compose up -d --build`（裸机部署重启服务）。
2. 管理页 → **审批卡** 页签：总开关、演练模式、放行构建安装类命令、按账号开关，保存后立即生效，存放在 `data/auto-approve.json`。

推荐顺序：先 `MUSE2API_AUTO_APPROVE=1` 跑**演练模式**（管理页默认），让小号跑几个会弹卡的任务，在审计日志里确认「放行」那几条全是你愿意放的；再在管理页关掉演练改为真批。

紧急关闭：管理页关总开关（立即生效），或 `.env` 设 `MUSE2API_AUTO_APPROVE=0` 后重启。

### 审计日志

每次判定都写入 `data/auto-approve-audit.jsonl`（超过 5 MB 轮转为 `.1`）。每条记录包含：账号 id 与备注名、时间、卡片原文（已脱敏）、判定档位与规则、模式（live / dry-run）、动作（`clicked` / `would-click` / `none` / `click-failed`）与按钮文案，以及卡片按钮列表和容器的 tag/role/testid（用于核对 DOM，同样脱敏）。日志只记卡片描述文本与判定结果，不记整页 DOM、cookie；没有 Muse 标记的块不记文字；卡片原文里的 token、密码、Bearer、`-u 用户:密码`、`"password": "…"`、`hatch_*` 等会先替换成 `[REDACTED]`。

查看与导出：管理页 → 审批卡 → 审计日志，可按账号、判定筛选，导出 CSV / JSONL。也可以直接调接口：

```bash
curl -H "Authorization: Bearer $MUSE2API_KEY" "http://127.0.0.1:18610/admin/auto-approve/audit?account=<账号id>&tier=allow"
curl -H "Authorization: Bearer $MUSE2API_KEY" -o audit.csv "http://127.0.0.1:18610/admin/auto-approve/audit/export?format=csv"
```

### 核对真实页面上的卡片

审批卡按 Muse 自己的标记识别：卡片容器 `[data-testid="hatch-inline-approval-card"]`（跳过 `data-hatch-background-approval-surface="true"` 的「N 项需要检阅」横幅），批次卡的每一项 `[role="button"][aria-expanded]`，主操作按钮 `[data-hatch-approval-primary-action="true"]`。这些标记取自已在 muse.ai 线上验证过的开源扩展 muse-auto-approve（MIT）；按钮文案（`Allow` / `Allow once` / `Deny` / `Always allow` / `Show approval details`，含简繁中文与日文）取自 muse.ai 公开前端包。没有标记时退回「同一块里同时有放行和拒绝按钮」的兜底识别。

和那个扩展的区别：扩展默认优先点 `Always allow`，本网关**只点单次放行**；发邮件、发帖这类连接器动作卡（主按钮写的是 "Send" 等动作）只记录、不点；批次卡一轮只点一项，等 Muse 重画后再点下一项。

线上实测（2026-11-25，alice 账号，让小号 `git clone` 一个 GitHub 仓库）弹出的卡片长这样：

```text
div[role=group][data-testid=hatch-inline-approval-card][data-hatch-approval-surface=chat]
  标题  Allow Muse to share information with github.com?
  说明  "Always allow" covers github.com and all its subdomains, not just this page.
  开关  div[role=button][aria-expanded=false]  助手写的用途说明 + See details
  详情  dl: Host=github.com / Grants=github.com and all subdomains / Method=POST
            Path=/astral-sh/uv-pre-commit/git-upload-pack / Policy=tool.exec
  按钮  Allow once[data-hatch-approval-primary-action] / Always allow this site / Deny
```

所以 git clone、uv、curl 触发的其实是「网络外联」卡，判定看详情里的结构化字段，不看助手写的用途说明（说明只过黑名单）。同一轮测试里 `whoami`、访问 `pypi.org` / `example.org` 没有弹卡。

任务卡住时，可以在机器上只读盘点当前页面上的卡片：

```bash
docker exec muse2api python tools/probe_approval_cards.py --tree
```

输出卡片文字（已脱敏）、按钮类型和容器结构，不点击任何按钮。

测试（不访问 Muse、不用真实账号）：

```bash
python tests/test_auto_approve.py
MUSE2API_CHROMIUM=/usr/bin/chromium python tests/test_auto_approve_browser.py
```

---

## 🔒 安全与隐私声明

- **零数据外泄**：本软件全部数据（包括账号凭据、任务队列、媒体文件）均持久化在本地 `data/` 目录中，不依赖任何第三方遥测或外部中转服务。
- **开源合规**：本项目仅供技术交流、系统自动化运维研究与自动化测试。请勿将本项目用于违反 Meta 平台服务条款或任何国家法律法规之用途。

---

## 👥 贡献者致谢 (Contributors)

感谢以下开发者对 MUSE2API 的代码贡献与功能优化（按 PR 合入顺序排列）：

- 🌟 **[@cpt-kenvie](https://github.com/cpt-kenvie)** (PR [#2](https://github.com/czg86389-hub/muse2api/pull/2)) —— 修复 Docker Compose 读取 `.env` 环境变量与示例配置覆盖问题
- 🌟 **[@djs-91](https://github.com/djs-91)** (PR [#9](https://github.com/czg86389-hub/muse2api/pull/9)) —— 修复未配置 `MUSE2API_PUBLIC_BASE` 时 Base URL 坍缩导致管理页地址解析异常
- 🌟 **[@toby-bridges](https://github.com/toby-bridges)** (PR [#8](https://github.com/czg86389-hub/muse2api/pull/8)) —— 适配 muse.ai 现网中文 UI、修复附件上传确认与 Stop 状态误判、强化视频成品与封面防误选
- 🌟 **[@LF2023](https://github.com/LF2023)** (PR [#18](https://github.com/czg86389-hub/muse2api/pull/18)) —— 修复视频生成仅凭 tid 命中封面静帧问题，规范预期匹配与防误选机制
- 🌟 **[@wuliaolaozi](https://github.com/wuliaolaozi)** (PR [#27](https://github.com/czg86389-hub/muse2api/pull/27)) —— 适配中英文额度查询，修复额度读取与管理页错误提示
- 🌟 **[@CarloCPP](https://github.com/CarloCPP)** (PR [#6](https://github.com/czg86389-hub/muse2api/pull/6), [#26](https://github.com/czg86389-hub/muse2api/pull/26)) —— 贡献 Tampermonkey 油猴一键导号脚本、放宽必要 Cookie 校验至 session 凭证与一键安装
- 🌟 **[@gr219](https://github.com/gr219)** (PR [#31](https://github.com/czg86389-hub/muse2api/pull/31)) —— 为管理后台及 Chrome 扩展提供中英文国际化双语动态切换支持
- 🌟 **[@Yeadon8888](https://github.com/Yeadon8888)** (PR [#32](https://github.com/czg86389-hub/muse2api/pull/32)) —— 增加有序多参考图生图、编辑与图生视频支持
- 🌟 **[@pandalaohe](https://github.com/pandalaohe)** (PR [#24](https://github.com/czg86389-hub/muse2api/pull/24)) —— 提供参考图本地文件与私网 URL 安全策略、重定向复查和 DNS 重绑定防护
- 🌟 **[@QuartzWarrior](https://github.com/QuartzWarrior)** (PR [#25](https://github.com/czg86389-hub/muse2api/pull/25)) —— 贡献账号独立 HTTP 代理基础、认证转接、配置界面与隔离回归测试
- [@Roins-hub](https://github.com/Roins-hub)：新版 Muse 输入区兼容、视频/音频/文档参考素材（PR #40）。

- [@WXJJ0520](https://github.com/WXJJ0520)：限定当前输入区域的发送按钮，修复侧栏历史误匹配并增加真实 Chromium 回归（PR [#48](https://github.com/czg86389-hub/muse2api/pull/48)）。

- [@Yeadon8888](https://github.com/Yeadon8888)：保留未分配会话响应中的 Cookie 轮换，避免后续继续使用失效旧值（PR [#60](https://github.com/czg86389-hub/muse2api/pull/60)）。
- [@ALight777](https://github.com/ALight777)：当前窗口 Cookie 存储区隔离、独立排队预算、真实版本报告与只读更新检查、视频缩略图（PR [#58](https://github.com/czg86389-hub/muse2api/pull/58)、[#55](https://github.com/czg86389-hub/muse2api/pull/55)、[#57](https://github.com/czg86389-hub/muse2api/pull/57)、[#51](https://github.com/czg86389-hub/muse2api/pull/51)）。

欢迎大家提交 PR 与 Issue，共同把项目打磨得更强更好用！

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源发布。


## 媒体选择回归测试

修复上传参考图被误判为生成结果、下载过程被页面其他媒体覆盖的问题。
测试使用独立临时 Chromium profile 和本地合成 DOM，不访问 Muse、不读取账号、不会消耗生成额度。
安装项目依赖和 Chromium 后，从仓库根目录运行：

```bash
python tests/test_media_selection.py
```

如浏览器不在 PATH，可设置 `MUSE2API_CHROMIUM` 为可执行文件路径。
覆盖上传预览排除、结果去重、历史附件排除、精确来源下载、视频来源保持、
禁止全局下载回退，以及参考图读取失败时中止。最终图片编辑效果仍需通过真实接口验收。


## v1.5.2：反向代理/CDN 后的长耗时生图

同步 OpenAI 图片接口仍保留兼容，但 CDN/客户端可能在生成结束前截断长请求。
生产客户端应使用短提交 + 轮询，而不是延长 HTTP 超时后重复生成：

1. `POST /v1/images/tasks`：JSON 与 `/v1/images/generations` 相同，可用 `reference_image` 传入单张参考图，或用 `images` 数组传入多张参考图；建议添加稳定的 `Idempotency-Key` 请求头。
2. 接收 HTTP 202 和 `id`，每 3 秒调用 `GET /v1/images/tasks/{id}`。
3. `status=completed` 时读取 `url` 或 `data[0]`；`status=failed` 时显示 `error`。查询失败只重试查询，不要重新 POST 生图。
4. 相同幂等键及相同输入返回原任务；同键不同输入返回 409；队列满返回 429。一个进程共享一个浏览器，最多接收 8 个未结束图片任务。

原 `/v1/images/generations` JSON 和 `/v1/images/edits` JSON/multipart 也可传 `async=true`，切换到同一异步处理。默认同步行为不变。
`timeout` 为排队及生成等待预算（1–600 秒），浏览器初始化与取回另有各自超时；客户端应继续轮询任务终态。
任务元数据持久化；进程重启时尚未完成的图片任务标记失败，不会悄悄再次生成。
管理页图片接口测试也已改为任务轮询。

回归检查（不消耗真实生成额度）：

```bash
python tests/test_async_images.py
python tests/test_vm_wait.py engine.py --assert
```

修复共享浏览器异常处理在解锁后重置其他任务的竞争；不再把页面侧栏残留的
`Connecting...` / `Still sending` 文本当作当前生图在 16 秒内失败的证据。


## v1.5.3：账号状态异常与自建实例排查

保活请求来自**部署服务器的出口**，并非导出 Cookie 的浏览器。作者服务器可用，不能证明另一台服务器的网络、地区、代理配置或同一账号会话也正常。

- `/api/session HTTP 401`：上游拒绝认证。先确认该账号能在 muse.ai 官网登录，再重新导入 Cookie。
- `HTTP 403`：访问被拒绝，可能涉及账号权限、服务器出口或地区/访问限制；**不等同于 Cookie 过期**。检查完整错误和部署网络，不要反复盲目重导。
- `HTTP 429`、`5xx`、超时、非 JSON 或未返回 `assigned`：本次保活未确认，不再假报成功或覆盖上次已确认的账号状态；备注显示诊断。原状态为“未检测”或“异常”时也不会被强行改成“可用”。
- 浏览器页面加载超时也不再直接当成认证失效；只有明确认证失败才标记账号异常。
- “可用”是最近一次已确认结果，不保证本次网络可达；“剩余有效期”是 Cookie 时间/估算值，不是服务端会话有效的证明。成功检测不再凭空延长 48 小时，续期以实际返回的 Cookie 为准。

更新到 v1.5.3 并重启服务后，点击账号“测试”重新确认。旧版已写入的异常不会被无条件洗成正常。鼠标悬停备注可查看完整错误；反馈请提供 HTTP 状态、版本与部署环境，**不要公开 Cookie、API Key 或带 key 的管理页链接**。

裸机 Git 部署：`git pull --ff-only` 后重启对应服务；Docker Compose：`git pull --ff-only && docker compose up -d --build`。请先保存本地自定义修改，保留 `.env` 与 `data/`。

不使用真实账号、不消耗生成额度的回归测试：

```bash
python tests/test_session_health.py
```
# MUSE2API 1.6.1

## 更新说明（2026-10-13）

- 修复多账号额度查询串读：额度查询绑定对应账号的浏览器页面，避免不同账号之间显示错误余额和用量。
- 额度读取失败或未读到有效数据时保留旧缓存，并明确报告读取失败，避免将无效结果当成实时额度。
- 修复保活成功误报：区分唤醒请求已接受与 VM 已运行，只有复核状态为 RUNNING 才报告唤醒成功。
- 管理页显示额度查询时间和过期提示；账号测试分别反馈会话有效性与额度读取状态。
- 新增离线回归测试，覆盖账号额度隔离及 VM 唤醒状态确认。

参考素材校验说明：视频必须含有可解析且不超过 120 秒的时长信息（MP4/MOV/3GP/WebM）；
缺失或损坏的时长信息会被拒绝。PDF 页数、文档解析和账号权限仍由 Muse 上游校验，
本项目的附件确认只表示文件进入输入区，不保证上游能够读取每一种文件。
Chromium 与服务必须能访问同一份素材文件；临时素材位于浏览器 profile 目录并在任务结束后清理。
