# VOC 工作台 · VOC Workbench

一个单页工作台，把 voc-agent 的分析结果和你本机的 VOC Agent（Hermes）放在一起用：看数据、问 Agent、现场加一个产品让 Agent 真实跑完分析。

## 有什么

| 页面 | 内容 |
|---|---|
| 首页 | VOC 数据看板：6 个核心指标、可按周切换的时间轴、这周的分析结论、近 12 周走势、声音来源、抱怨怎么变（瀑布图）、抱怨排名、用户旅程、各款式差评、退货原因码 × 真实原因、和竞品比（哑铃图） |
| 我的产品 | 自家产品和竞品列表；「+ 添加产品」粘贴 ASIN，交给 VOC Agent 现场分析，出报告后列表自动填回真实数字 |
| 产品详情 | 概况、用户在说什么、退货与换货、用户旅程、Alexa 怎么说、和竞品比、改动与效果 |
| 站外 VOC | Reddit：站内外对照、⑥ 用户旅程地图（情绪曲线）、⑦ 需求四象限、原声、全部讨论串 |
| VOC Agent | Agent 岗位卡：职责、入口、技能、数据权限、权限边界、工作架构 |
| 行动 / 新机会 / 设置 | 行动手册、ABA 机会、数据接入、运行记录（`voc-reports/runs.jsonl`）、本周群消息草稿（`skill/weekly.py` 起草，人改好点「发到群」才发）、**资产库**（`skill/timeline.py` 算的项目时间线 + 11 张功能价值卡） |

页面本身不带数据：启动 `serve.py` 时，它把 `voc.config.json`（口径、ASIN、飞书表）、`products.json`（产品列表展示行）、自家产品的 `dashboard.json`（按运行日锚定，`dashboard.py --as-of` 可改）/ `data.json` 的 `offsite` 块 / `alexa_compare.json`、`details`、`timeline.json` 注入页面。要一个能双击打开的离线版：`python3 workbench/build_export.py`。

## 怎么用

只看：`python3 workbench/build_export.py` 生成离线版再打开（或跑 serve.py 后在浏览器看）。

要问 Agent、现场加产品、发飞书群：启动本机服务。macOS 一条命令常驻（launchd，开机自起、挂了自动拉起）：

```bash
workbench/voc up
```

`workbench/voc status` 看工作台 / Hermes 网关 / 定时任务在不在；`restart` / `down` / `log` / `weekly`（立刻跑一次每周运转）/ `timeline`（重算资产库）。Linux 或临时跑：

```bash
python3 workbench/serve.py
```

然后打开 http://127.0.0.1:8790 。需要：

- 本机跑着 Hermes，profile 里装了 voc-agent 技能，并开了 API（`~/.hermes/profiles/<profile>/.env` 里有 `API_SERVER_KEY`）。密钥只在 serve.py 里读，不会发到浏览器。
- 拉评论用卖家精灵：Hermes 里接了卖家精灵 MCP。MCP 没加载上或报错时，Agent 会改用 `ss_pull.py` 直连（读同一份配置里的 key）。

环境变量（都可选）：

| 变量 | 作用 | 默认 |
|---|---|---|
| `VOC_CONFIG` | `voc.config.json` 的路径 | 从 workbench/ 往上找 |
| `VOC_DATA_DIR` | 每个 ASIN 的分析目录（`<ASIN>/data.json`、`报告.html`、`dashboard.json`、`timeline.json`、`runs.jsonl`） | 仓库根目录下的 `voc-reports/`（所有脚本同一个默认，见 `voccfg.data_dir`） |
| `VOC_OWN_ASIN` | 自家产品 ASIN（临时覆盖） | `voc.config.json` 的 `own.asin` |
| `VOC_HERMES_PROFILE` | Hermes profile 名 | `voc.config.json` 的 `hermes.profile` |
| `VOC_GROUP_CHAT_ID` | 飞书群 chat_id（临时覆盖） | `voc.config.json` 的 `feishu.group_chat_id`；都没有就不能发群 |
| `LARK_CLI` | lark-cli 路径 | 在 PATH 里找 |

飞书多维表格的链接和表 ID 写在 `voc.config.json` 的 `feishu` 段，填上以后「打开飞书」按钮才能直达。

## 文件

```
workbench/
├── index.html      # 工作台本体（单文件，自带深浅色；数据由 serve.py 注入）
├── serve.py        # 本机服务：注入数据；/api/agent 转给 Hermes，/api/product 和 /report/<ASIN> 给「添加产品」用，/api/post-to-group 人点按钮才发群
├── build_export.py # 生成离线版（和本机版同一份数据）
├── products.json   # 「我的产品」列表的展示行（真实分析过的 ASIN 会自动并进来）
├── dashboard.py    # 首页看板的数字：按运行日锚定 12 周（--as-of / VOC_AS_OF 可改）+ 近 12 个月 + 累计 + fresh，写 <ASIN>/dashboard.json；不带参数 = voc.config.json 里的自家产品
├── voccfg.py       # 读 voc.config.json（和 skill/voccfg.py 同一份）
├── ss_pull.py      # 卖家精灵直连拉评论（MCP 不可用时的兜底，自带重试）；--merge --new-only 周度增量并进 data.json
├── voc             # 一条命令：up（launchd 常驻）/ down / restart / status / weekly / timeline / log
└── base_template.py # 飞书三张表的 .base 模板：export（从你的表导结构）/ build / check / print → agent/feishu/
```

## 边界

- 数字都由脚本算，Agent 只读原话、归纳、写结论。
- 花钱的调用（卖家精灵等）先报次数，等人回「确认」。
- 发飞书群必须人在面板里点按钮；不改 listing、不发买家消息。
