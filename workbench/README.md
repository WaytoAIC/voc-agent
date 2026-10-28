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
| 行动 / 新机会 / 设置 | 行动手册、ABA 机会、数据接入与运行记录 |

页面里自带一套楼梯踏板的案例数据（自家产品是课程案例，5 个竞品用公开评论分析），可以直接打开看。

## 怎么用

只看：直接用浏览器打开 `index.html`。

要问 Agent、现场加产品、发飞书群：启动本机服务。

```bash
python3 workbench/serve.py
```

然后打开 http://127.0.0.1:8790 。需要：

- 本机跑着 Hermes，profile 里装了 voc-agent 技能，并开了 API（`~/.hermes/profiles/<profile>/.env` 里有 `API_SERVER_KEY`）。密钥只在 serve.py 里读，不会发到浏览器。
- 拉评论用卖家精灵：Hermes 里接了卖家精灵 MCP。MCP 没加载上或报错时，Agent 会改用 `ss_pull.py` 直连（读同一份配置里的 key）。

环境变量（都可选）：

| 变量 | 作用 | 默认 |
|---|---|---|
| `VOC_DATA_DIR` | 每个 ASIN 的分析目录（`<ASIN>/data.json`、`报告.html`） | 仓库根目录下的 `现场分析/` |
| `VOC_HERMES_PROFILE` | Hermes profile 名 | `voc` |
| `VOC_GROUP_CHAT_ID` | 飞书群 chat_id；不填就不能发群 | 空 |
| `VOC_GROUP_NAME` | 群名 | `VOC专项群` |
| `LARK_CLI` | lark-cli 路径 | 在 PATH 里找 |

飞书多维表格的链接写在 `index.html` 的 `FS_URL`、`FS_T`，填上以后「打开飞书」按钮才能直达。

## 文件

```
workbench/
├── index.html     # 工作台本体（单文件，自带深浅色）
├── serve.py       # 本机服务：/api/agent 转给 Hermes，/api/product 和 /report/<ASIN> 给「添加产品」用，/api/post-to-group 人点按钮才发群
├── dashboard.py   # 首页看板的数字（含按周快照），写 <ASIN>/dashboard.json
└── ss_pull.py     # 卖家精灵直连拉评论（MCP 不可用时的兜底，自带重试）
```

## 边界

- 数字都由脚本算，Agent 只读原话、归纳、写结论。
- 花钱的调用（卖家精灵等）先报次数，等人回「确认」。
- 发飞书群必须人在面板里点按钮；不改 listing、不发买家消息。
