# 部署指南：搭出你自己的 VOC 工作台 + VOC Agent

> **怎么用这份文档**：把这个仓库地址发给你的 AI 编程助手（Claude Code、Codex 等），说一句：
>
> 「按 https://github.com/WaytoAIC/voc-agent 的 DEPLOY.md，帮我把 VOC 工作台和 VOC Agent 搭起来。」
>
> 它会按下面的步骤一步步做，每步做完自己检查，需要你提供的东西会一次问清楚。

搭完你会有：

- **VOC Agent**：跑在你电脑上的 Hermes 里，会读评论、退货、Alexa 问答、Reddit，用脚本算数、给结论和要做的事；可选接到飞书，在群里 @ 它就回答。
- **VOC 工作台**：本机网页 http://127.0.0.1:8790 。看板、产品列表、站外 VOC、问 Agent；粘贴一个 ASIN，Agent 现场跑完分析出报告。

---

## 给 AI 的执行规则

1. **先问再做**：开工前按「第 0 步」把要问的一次问完，不要做到一半再问。
2. **每步都验收**：每一步最后都有「检查」，没通过就修，修不好就停下告诉用户卡在哪、试过什么。全部做完跑 `bash scripts/doctor.sh`，必须没有 ❌。
3. **密钥只进本机文件**：用户给的 key、App Secret 只写进 `~/.hermes/profiles/voc/.env` 或 `config.yaml`，不回显到对话里、不写进仓库、不 commit。
4. **花钱的调用先问**：卖家精灵、TikHub、Alexa 采集都按次计费，第一次真实调用前说清调用几次，等用户确认。
5. **不碰用户已有的东西**：用户原有的 Hermes 配置、别的 profile、默认 profile 的设置，只追加不改写；要改先问。
6. 命令里的 `<仓库目录>` 指 clone 下来的本仓库路径。

---

## 第 0 步：先问用户这几件事

| 问什么 | 用在哪 | 没有怎么办 |
|---|---|---|
| 电脑系统（macOS / Linux） | 装 Hermes、网关常驻 | Windows 用 WSL |
| 有没有装过 Hermes | 第 2 步 | 没装就第 2 步装 |
| 用哪家大模型（Hermes 要一个能用的模型和 key） | 第 2 步 `hermes setup` | 必须有 |
| **卖家精灵 MCP key** | 拉亚马逊评论 | 必须有（卖家精灵后台申请 MCP key） |
| 自家产品 ASIN（1 个就行）和 2–5 个竞品 ASIN | 第 8 步第一次分析 | 可以先只分析竞品 |
| 要不要接飞书（群里 @ 它、多维表格存数据） | 第 9 步 | 不接也能用，跳过第 9 步 |
| 可选：Sorftime key、TikHub key | 多平台数据、拉 Reddit | 不填就用免费通道或跳过 |

---

## 第 1 步：拿到仓库

```bash
git clone https://github.com/WaytoAIC/voc-agent.git ~/voc-agent
```

**检查**：`ls ~/voc-agent` 能看到 `agent/ skill/ workbench/ DEPLOY.md`。

## 第 2 步：装 Hermes（装过就跳过）

按 Hermes 官方文档安装（需要 0.22 以上），装好后配置模型：

```bash
hermes setup
```

**检查**：`hermes --version` 有输出；`hermes chat -z "你好"` 能回话。

## 第 3 步：装 VOC Agent（Hermes profile）

```bash
hermes profile install <仓库目录>/agent --alias -y
```

它会建一个叫 `voc` 的 profile（`~/.hermes/profiles/voc/`），装上岗位规则 `SOUL.md`，生成一份 `.env.EXAMPLE`，并建一个 `voc` 命令（以后 `voc chat` 或 `hermes -p voc chat` 就是和 VOC Agent 说话）。

新 profile 要单独选一次模型：

```bash
hermes -p voc model
```

然后开 API，让工作台能连上它：

1. 生成两串随机密钥：`openssl rand -hex 24`（跑两次）。
2. 写进 `~/.hermes/profiles/voc/.env`：

```
API_SERVER_KEY=<第一串>
API_SERVER_HOST=127.0.0.1
```

3. 写进 `~/.hermes/.env`（网关总开关，已有就不动）：

```
API_SERVER_KEY=<第二串>
API_SERVER_HOST=127.0.0.1
```

**检查**：`ls ~/.hermes/profiles/voc` 有 `SOUL.md`、`.env`；两个 `.env` 里都有 `API_SERVER_KEY`（不要把值打印出来）。

## 第 4 步：装技能、填岗位规则

```bash
bash <仓库目录>/install.sh --repo <仓库目录> --dest ~/.hermes/profiles/voc/skills/ecommerce
```

再打开 `~/.hermes/profiles/voc/SOUL.md` 填占位符：

| 占位符 | 填什么 |
|---|---|
| `{{DATA_DIR}}` | `<仓库目录>/现场分析`（每个 ASIN 的分析结果放这里，没有就建） |
| `{{REPO_DIR}}` | `<仓库目录>` |
| 飞书那两节里的 `{{...}}` | 第 9 步再填；**不接飞书就把这两节整节删掉** |

```bash
mkdir -p <仓库目录>/现场分析
```

**检查**：`~/.hermes/profiles/voc/skills/ecommerce/voc-agent/SKILL.md` 存在；`grep -c "{{" ~/.hermes/profiles/voc/SOUL.md`，不接飞书时应为 0。

## 第 5 步：接数据源

把 `agent/mcp.example.yaml` 里的 `sellersprite`（必需）和 `sorftime`（可选）写进 `~/.hermes/profiles/voc/config.yaml` 的 `mcp_servers:` 下，`<...>` 换成用户给的 key。刚装的 profile 没有 `config.yaml` 就新建，只写 `mcp_servers` 这一段（Hermes 会和默认配置合并）；已经有就只追加这一段，**不要整个替换**。

**检查**：

```bash
hermes -p voc mcp test sellersprite
```

能列出工具（里面有 `review`、`asin_detail`）就是通了。卖家精灵偶尔很慢（单次 15–25 秒，握手可能超过 60 秒）或报 500，超时就把 `connect_timeout` 调到 120 再试，或者稍后再试；分析时 Agent 也会自动改用 `workbench/ss_pull.py` 直连。

## 第 6 步：启动 Hermes 网关（常驻）

```bash
hermes gateway install
```

```bash
hermes gateway start
```

macOS 用 launchd、Linux 用 systemd，开机自启、崩了自动重启。只想临时跑：`hermes gateway run`（前台）。

**检查**：

```bash
curl -s http://127.0.0.1:8642/v1/health
```

有返回就是在线。

## 第 7 步：启动工作台

```bash
cd <仓库目录> && VOC_OWN_ASIN=<自家产品 ASIN> python3 workbench/serve.py
```

浏览器打开 http://127.0.0.1:8790 。这个终端别关；以后每次开机都要跑这一条（或者让 AI 帮你做成开机自启）。

**检查**：

```bash
curl -s http://127.0.0.1:8790/api/health
```

返回里有 `"hermes": true`。页面右上角点「问 Agent」，问一句「你能做什么」，能流式回答就通了。

## 第 8 步：第一次分析（跑通全流程）

1. 工作台 → **我的产品** → 「+ 添加产品」，粘贴一个竞品 ASIN，点「添加」。
2. 右边 Agent 面板会说要调卖家精灵几次（一般最多 11 次：商品详情 1 + 评论 10 页），回「确认」。
3. 3–10 分钟后，列表里这一行变成真实数据，点它打开报告（`<仓库目录>/现场分析/<ASIN>/报告.html`）。
4. 对每个竞品重复；最后对**自家产品**也跑一次，并在面板里说：「把自家产品和这几个竞品对比，跑 analyze.py --vs」。
5. 生成首页看板（自家产品要有近 8 周以上的评论，数字才有意义）：

```bash
cd <仓库目录> && python3 workbench/dashboard.py 现场分析/<自家ASIN>/data.json --vs 现场分析/<竞品1>/data.json 现场分析/<竞品2>/data.json
```

刷新工作台，首页就换成自家产品的看板；产品列表里会自动出现所有分析过的 ASIN。

**检查**：`<仓库目录>/现场分析/` 下每个 ASIN 都有 `data.json` 和 `报告.html`；首页标题下写的是你自己的数据。

## 第 9 步（可选）：接飞书

1. **建机器人**：飞书开放平台建「企业自建应用」→ 开启机器人能力 → 事件订阅选「长连接」，订阅接收消息事件 → 开权限（以后台实际名称为准）：收发消息、读群消息里 @ 它的消息、读群信息、多维表格读写、云文档读写 → 发布版本。
2. **写进 profile**：`~/.hermes/profiles/voc/.env` 按 `.env.EXAMPLE` 填 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_ALLOWED_USERS`（谁能私聊它）；建一个 VOC 专项群，把机器人拉进去，群 chat_id 填 `FEISHU_HOME_CHANNEL`。然后 `hermes gateway restart`。
3. **建多维表格**：按 `agent/feishu/schema.json` 建一个「VOC工作台」多维表格，三张表（VOC 事件明细、行动手册、站外 VOC · Reddit），字段和选项照抄；在文档的「…→ 添加文档应用」里把机器人加成可管理。读写用 lark-cli 的机器人身份：

```bash
HERMES_HOME=~/.hermes/profiles/voc lark-cli config bind --source hermes --identity bot-only
```

4. **填占位符**：SOUL.md 里飞书两节的 `{{BASE_TOKEN}}`、三个 `{{TABLE_...}}`、`{{LARK_CLI}}`、`{{HERMES_PROFILE_DIR}}`、`{{OWNER_OPEN_ID}}`、`{{OWNER_NAME}}`、`{{GROUP_NAME}}`、`{{GROUP_CHAT_ID}}`。
5. **工作台连飞书**：启动工作台时加 `VOC_GROUP_CHAT_ID=<群 chat_id>`（人点按钮才发群）；`workbench/index.html` 里的 `FS_URL`、`FS_T` 填多维表格链接和两个 table_id。

**检查**：飞书私聊它「你能做什么」能回；群里 @ 它能回；它往「VOC 事件明细」写一行测试数据、写入方是「VOC Agent」，然后删掉。

## 第 10 步：验收

```bash
bash <仓库目录>/scripts/doctor.sh
```

没有 ❌ 就是搭好了。再亲手走一遍：工作台加一个新 ASIN → 回「确认」→ 出报告。

---

## 常见问题

| 现象 | 原因和办法 |
|---|---|
| 工作台打不开 | `serve.py` 没在跑，重新跑第 7 步那条命令 |
| 面板显示连不上 Agent | `curl http://127.0.0.1:8642/v1/health` 不通就 `hermes gateway restart`；通了就检查 profile 的 `API_SERVER_KEY` |
| 加产品后一直「分析中」 | 多半在等你在右边面板回「确认」 |
| 卖家精灵报 500 / 工具列表里没有它 | 对方偶发故障；Agent 会改用 `workbench/ss_pull.py` 直连，或稍后再试 |
| 首页还是案例数据 | 启动工作台时没加 `VOC_OWN_ASIN`，或还没跑第 8 步的 `dashboard.py` |
| 首页数字很小或很多 0 | 自家产品近几周评论太少；接上自家店铺的退货、买家消息（比如紫鸟 SP-API）会更准 |
| 飞书里它不回 | 发消息的人不在 `FEISHU_ALLOWED_USERS`；或应用权限、版本没发布 |
