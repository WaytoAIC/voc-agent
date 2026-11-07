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

## 第 4.5 步：建口径文件 voc.config.json

```bash
cp <仓库目录>/skill/voc.config.example.json <仓库目录>/voc.config.json
```

这是整套系统唯一的口径来源：标签词表、每个标签属于哪一段旅程、6 段旅程、该谁改、阈值、自家 / 竞品 ASIN、飞书表和群。先把 `own.asin`、`competitors` 换成用户的；标签词表第一次分析时可以先用样例的，分析自己品类时再改。以后改口径只改这一个文件，脚本、报告、工作台一起变。

**检查**：`python3 -m json.tool <仓库目录>/voc.config.json >/dev/null` 没报错；`own.asin` 是用户的 ASIN。

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
cd <仓库目录> && python3 workbench/serve.py
```

浏览器打开 http://127.0.0.1:8790 。自家产品、群、飞书表都从 `voc.config.json` 读（环境变量 `VOC_OWN_ASIN` 等只做临时覆盖）。这个终端别关；以后每次开机都要跑这一条（或者让 AI 帮你做成开机自启）。

**检查**：

```bash
curl -s http://127.0.0.1:8790/api/health
```

返回里有 `"hermes": true`。页面右上角点「问 Agent」，问一句「你能做什么」，能流式回答就通了。

## 第 7.5 步：打标签用哪个模型

`skill/tag.py` 负责把评论打上标签。它调模型的方式二选一：

- **什么都不设**：自动走本机 Hermes 网关（第 6 步），用 Hermes 自己配的模型。最省事。
- **直接调模型接口**（更稳、可评测，推荐）：在跑工作台和 Hermes 的那个 shell 环境里设四个变量，例如 OpenAI 兼容口
  `VOC_LLM_API=openai VOC_LLM_BASE=https://api.openai.com/v1 VOC_LLM_KEY=<密钥> VOC_LLM_MODEL=<模型名>`，
  或 Anthropic 兼容口 `VOC_LLM_API=anthropic VOC_LLM_BASE=https://api.anthropic.com VOC_LLM_KEY=<密钥> VOC_LLM_MODEL=<模型名>`。
  密钥只放 shell 环境或本机 env 文件，不进仓库。

**检查**：`python3 skill/tag.py eval --n 10`（用自带的 10 条金标试打，约 1 次调用）能打印「一致率」一行。

## 第 8 步：第一次分析（跑通全流程）

1. 工作台 → **我的产品** → 「+ 添加产品」，粘贴一个竞品 ASIN，点「添加」。
2. 右边 Agent 面板会说要调卖家精灵几次（一般最多 11 次：商品详情 1 + 评论 10 页），回「确认」。
3. 3–10 分钟后，列表里这一行变成真实数据，点它打开报告（`<仓库目录>/现场分析/<ASIN>/报告.html`）。
4. 对每个竞品重复；最后对**自家产品**也跑一次，并在面板里说：「把自家产品和这几个竞品对比，跑 analyze.py --vs」。
5. 生成首页看板（自家产品要有近 8 周以上的评论，数字才有意义）：

```bash
cd <仓库目录> && python3 workbench/dashboard.py 现场分析/<自家ASIN>/data.json
```

刷新工作台，首页就换成自家产品的看板；产品列表里会自动出现所有分析过的 ASIN。

**检查**：`<仓库目录>/现场分析/` 下每个 ASIN 都有 `data.json` 和 `报告.html`；首页标题下写的是你自己的数据。

## 第 8.5 步（可选）：导入退货 / 买家消息，关掉演示数据

- 自家后台能导出退货报告（带 customer-comments 列）、换货表、买家消息时：
  `python3 skill/import_events.py <表格.csv> --asin <自家ASIN>`（换货 `--type 换货`，消息 `--type 买家消息`），再 `python3 skill/tag.py 现场分析/<自家ASIN>/data.json --events` 把备注读成真实原因，最后重跑 `workbench/dashboard.py`。工作台「退货与换货」页就有数了；不导的话那一页会写明去哪接。
- 工作台默认带楼梯踏板的演示展示行（`workbench/products.json`，课堂用）。接了自己的产品后，把 `voc.config.json` 的 `workbench.demo` 改成 `false`（或启动时 `VOC_DEMO=0`），列表就只剩你真实分析过的 ASIN。

**检查**：工作台「我的产品」里没有「亚麻楼梯踏板 / 转角落地垫 / 夜光楼梯踏板」这几行演示产品；自家产品的「退货与换货」页有数字，或写着「还没有退货 / 换货 / 买家消息：…」。

## 第 8.6 步（可选）：对外演示但不暴露店铺——脱敏投影

只在「要拿真实数据对外讲课 / 演示，又不能让人认出是哪家店」时做；自己内部用跳过。

1. 真实 ASIN 单独拉到私有目录（不进 git）：`VOC_DATA_DIR=voc-reports/_real python3 workbench/ss_pull.py <真实ASIN> --pages 10 --merge`，再 `python3 <skill>/tag.py voc-reports/_real/<真实ASIN>/data.json`
2. 写私有参数 `voc-reports/_real/projection.json`：
   ```json
   {"real": "<真实ASIN>", "alias": "<对外用的假ASIN>", "k": 8, "dateShiftDays": -16, "seed": "任意字符串",
    "product": {"brand": "自家品牌", "name": "产品中文名", "title": "通用英文标题", "parent": "<假ASIN>"},
    "banned": ["品牌名", "店铺名", "子ASIN…", "MSKU…"]}
   ```
   k = 类目中位产品的月评论增速 ÷ 自家真实月评论增速，定一次就别改。
3. `voc.config.json`：`own.asin` 填假 ASIN，`own.projection = {"enabled": true, "private": "voc-reports/_real/projection.json"}`
4. `python3 <skill>/project.py --check`：生成别名 data.json 并核对（分布一致、每周条数 = 真实 × k、无敏感词、无原话重合）。以后 `weekly.py` 每周自动重投。
5. 对外口径固定一句：**真实产品数据，经脱敏与等比扩增至类目中位规模**（产品页顶部会显示），倍数不说。判断看 `projection.realByWeek`，真实样本不到 5 条的周别下结论。

## 第 9 步（可选）：接飞书

1. **建机器人**：飞书开放平台建「企业自建应用」→ 开启机器人能力 → 事件订阅选「长连接」，订阅接收消息事件 → 开权限（以后台实际名称为准）：收发消息、读群消息里 @ 它的消息、读群信息、多维表格读写、云文档读写 → 发布版本。
2. **写进 profile**：`~/.hermes/profiles/voc/.env` 按 `.env.EXAMPLE` 填 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_ALLOWED_USERS`（谁能私聊它）；建一个 VOC 专项群，把机器人拉进去，群 chat_id 填 `FEISHU_HOME_CHANNEL`。然后 `hermes gateway restart`。
3. **建多维表格**：按 `agent/feishu/schema.json` 建一个「VOC工作台」多维表格，三张表（VOC 事件明细、行动手册、站外 VOC · Reddit），字段和选项照抄；在文档的「…→ 添加文档应用」里把机器人加成可管理。读写用 lark-cli 的机器人身份：

```bash
HERMES_HOME=~/.hermes/profiles/voc lark-cli config bind --source hermes --identity bot-only
```

4. **填占位符**：SOUL.md 里飞书两节的 `{{BASE_TOKEN}}`、三个 `{{TABLE_...}}`、`{{LARK_CLI}}`、`{{HERMES_PROFILE_DIR}}`、`{{OWNER_OPEN_ID}}`、`{{OWNER_NAME}}`、`{{GROUP_NAME}}`、`{{GROUP_CHAT_ID}}`。
5. **工作台连飞书**：在 `voc.config.json` 的 `feishu` 段填 `wiki_url`（多维表格链接）、`base`、三个 `tables`、`group_chat_id`（人点按钮才发群）。页面里不用改任何东西。

**检查**：飞书私聊它「你能做什么」能回；群里 @ 它能回；它往「VOC 事件明细」写一行测试数据、写入方是「VOC Agent」，然后删掉。

## 第 9.5 步（可选）：每周自动运转

一条命令把一周的事跑完：增量拉评论（自家 + 竞品，按日期倒序只拉到已有评论为止）→ 只给新评论打标 → 算数 / 报告 / 看板 → 行动卡 pull / readback / check → 新评论和新退货写进飞书「VOC 事件明细」→ 起草群消息（不自动发，工作台设置页「本周群消息草稿」点了才发）。

```bash
python3 skill/weekly.py --dry-run     # 先看流程通不通：不调卖家精灵、不调模型、不写飞书
python3 skill/weekly.py               # 真跑
```

- 结果写 `voc-reports/runs.jsonl`（工作台设置页「运行记录」读它），完整日志在 `voc-reports/_runs/`。
- 口径在 `voc.config.json` 的 `weekly` 段：每个 ASIN 最多翻几页（默认 3，一页 20 条）、要不要刷新详情、竞品拉不拉、写不写飞书、到期判断写不写回（默认只打印）、要不要重建离线版。
- 打标模型通道照第 7.5 步设环境变量；没设就走本机 Hermes 网关。
- **定时**：把它挂到 Hermes 的 cron（纯脚本模式，不走模型；电脑合盖错过的会在下次唤醒时补跑）。先写一个包装脚本 `~/.hermes/profiles/voc/scripts/voc-weekly.sh`：

```bash
#!/bin/bash
cd <仓库目录> || exit 1
export VOC_LLM_API=... VOC_LLM_BASE=... VOC_LLM_KEY=... VOC_LLM_MODEL=...   # 第 7.5 步那套；不设就走 Hermes 网关
python3 skill/weekly.py > /tmp/voc-weekly.out 2>&1; rc=$?
grep -E "^(完成|记录|== |  跳过|  出错)" /tmp/voc-weekly.out | tail -12; exit $rc
```

```bash
chmod +x ~/.hermes/profiles/voc/scripts/voc-weekly.sh
HERMES_HOME=~/.hermes/profiles/voc hermes cron create "0 9 * * 1" --name "VOC 每周运转" --no-agent --script voc-weekly.sh --deliver local
```

`--deliver local` 是不往任何群发运行摘要；想让摘要进飞书群就改成 `--deliver feishu:<群 chat_id>`（群消息草稿本身仍然要人点）。`hermes cron list / run / pause` 管理。

**检查**：`python3 skill/weekly.py --dry-run` 退出码 0；工作台设置页「运行记录」多了一行、「本周群消息草稿」有内容；`hermes cron list` 里有「VOC 每周运转」。

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
| 首页还是案例数据 | `voc.config.json` 的 `own.asin` 没改成自己的，或还没跑第 8 步的 `dashboard.py` |
| 脚本提示「没找到 voc.config.json，先用样例」 | 还没做第 4.5 步；或者不是在仓库目录下跑的（也可以设环境变量 `VOC_CONFIG=<路径>`） |
| 首页数字很小或很多 0 | 自家产品近几周评论太少；接上自家店铺的退货、买家消息（比如紫鸟 SP-API）会更准 |
| 飞书里它不回 | 发消息的人不在 `FEISHU_ALLOWED_USERS`；或应用权限、版本没发布 |
