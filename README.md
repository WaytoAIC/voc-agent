## 🚀 Way to AIC | 通往 AI 电商之路
---
### 🌐 官网 Website
- https://waytoaic.com
- https://www.waytoaic.com
---

### 👥 社群招募 Community
`Way to AIC 社群招募 | WaytoAIC.com`

<p align="center">
  <img src="https://github.com/user-attachments/assets/d9f8bbf4-2056-4780-975d-86c885b52bab" width="70%">
</p>

---

### 📣 公众号 WeChat Official Account
`维正 WaytoAIC`

<p align="center">
  <img src="https://github.com/user-attachments/assets/71c71a5c-e68a-4f30-9afb-f2b056619991" width="300">
</p>

---

### 🧠 知识星球 Xiaozhixing
`AI电商之路 WaytoAIC`

<p align="center">
  <img src="https://github.com/user-attachments/assets/9eccef07-0e84-45a7-a415-affcb18c928d" width="200">
  <img src="https://github.com/user-attachments/assets/4e99fbc3-1981-4fee-b113-c9821141102d" width="400">
</p>

---

### 🧩 About Way to AIC

**AIC = AI Commerce**

在 AI 重塑商业的时代，我们希望和每一个拥抱 AI 的卖家：

- 找到场景
- 定义问题
- 积累能力
- 设计系统

共同通往 AI 电商之路。

> Way to AIC 不是教学，不是工具，
> 而是一条所有电商人共同走的进化之路。

### WaytoAIC 理念 | Principles

| 中文 | English |
|---|---|
| 场景先于方法 | Context before method |
| AI 的价值来自真实业务场景，而不是技术本身。 | AI creates value through real business contexts, not through technology alone. |
| 问题先于答案 | Problem before answer |
| 定义问题，比拥有工具更重要。 | Defining the problem matters more than collecting tools. |
| 系统胜过技巧 | System over tricks |
| 技巧是术，系统才是道，决定卖家的上限。 | Tricks are tactical; systems define long-term leverage and ceiling. |
| 共创优于独行 | Co-creation over solo progress |
| 我们相信，真正的进化发生在共同探索的过程中。 | Real evolution happens through shared exploration. |

---

# VOC Agent · 亚马逊评论分析 Skill

给一个亚马逊 ASIN，Agent 自己拉评论、读懂、算数，出一页 VOC 报告；之后你可以一直追问：最大的问题是什么、先改哪几件、是不是某个款式的问题、哪一段体验最差、和竞品比差在哪、主图该写什么。

Give the agent an Amazon ASIN. It pulls the reviews, reads them, runs the numbers, and produces a one-page VOC report. Then keep asking follow-up questions in plain language.

## ⚡ 一键安装 Quick Install

```bash
# Claude Code（默认）
curl -fsSL https://raw.githubusercontent.com/WaytoAIC/voc-agent/main/install.sh | bash

# Codex
curl -fsSL https://raw.githubusercontent.com/WaytoAIC/voc-agent/main/install.sh | bash -s -- --target codex

# OpenClaw
curl -fsSL https://raw.githubusercontent.com/WaytoAIC/voc-agent/main/install.sh | bash -s -- --target openclaw

# 固定版本 Pin a version
curl -fsSL https://raw.githubusercontent.com/WaytoAIC/voc-agent/main/install.sh | bash -s -- --ref v1.0.0
```

装好后重启 Agent，说一句：**「分析 B0FMJCMKY1」**。

After installing, restart your agent and say: **"Analyze B0FMJCMKY1"**.

**前提 Requirements**
- Python 3（只用标准库，不用 pip 装任何东西）
- 已接好[卖家精灵 MCP](https://www.sellersprite.com/)，用来拉商品详情和评论。没有的话，也可以把导出的评论表格交给 Agent，按样例的字段整理成 `data.json`。

---

## 中文说明

### 报告里有什么

| 区块 | 用的方法 | 回答的问题 |
|---|---|---|
| 一句话结论 + 反直觉发现 | 主题归类 + 夸还是骂 | 用户最在意什么；有没有藏在好评里的问题 |
| 先改哪几件 | 帕累托（二八） | 几个问题占了八成抱怨；提到它的人平均几星 |
| 最该改的 / 用户最喜欢的 | 主题归类 | 每个问题该谁改、怎么改；好评怎么用到主图和五点 |
| 按款式看 | 下钻（父体 → 款式） | 问题是全线的，还是集中在某个颜色、规格 |
| 用户旅程 | 旅程地图 + 满意度 | 从为什么买到用了几个月，哪一段最差 |
| 和竞品比 | 竞品对标 | 同一个问题，我和竞品各有多少人在说；哪些是短板、哪些是卖点 |
| 建议的行动 / 全部原话 | — | 先做什么；每个结论都能翻回原话 |

### 分工：AI 读懂，脚本算数

- **AI 负责**：读原话、写中文意思、打标签、写建议。
- **`analyze.py` 负责**：所有条数、占比、排序、满意度，AI 不手算，也不改脚本算出的数。
- 每次跑脚本先做体检：没打标签的评论、没定阶段的标签、名称对不上的，会直接提示。

### 常用说法

- 「分析 B0xxxxxxxx」
- 「先改哪几件？」「是不是灰色款的问题？」「哪一段体验最差？」
- 「和这两个竞品比：B0xxxx、B0xxxx」
- 「起草一条行动」「用好评写主图文案」

### 边界

- 只写本地文件；不发消息、不改 listing、不动广告，最多起草，交给人决定。
- 「和竞品比」只说比例差多少。某个问题让星级掉多少，只靠评论算不出来，需要亚马逊官方评论主题（SP-API Customer Feedback）。
- 送测（Vine）评论单独记，不进分析；不保留买家名字。

### 目录

```
skill/
├── SKILL.md          # Agent 的工作说明
├── analyze.py        # 算数：体检、二八、款式下钻、旅程满意度、竞品对比
├── render.py         # 把 data.json 填进模板，生成「报告.html」
├── template.html     # 报告模板（自带深浅色）
└── examples/B0FMJCMKY1/   # 完整样例：data.json + 报告.html
```

样例是一款公开在售的黄麻楼梯踏板，只用于演示分析流程。

---

## English

### What the report covers

| Section | Method | Question it answers |
|---|---|---|
| Summary + insight | Topic tagging + sentiment | What customers care about most; problems hiding in 4–5 star reviews |
| Fix these first | Pareto (80/20) | Which few problems make up 80% of complaints; average stars of reviews that mention each |
| Problems / praises | Topic tagging | Who should fix what; how to reuse praise in images and bullets |
| By variant | Drill-down (parent → variant) | Whether a problem is product-wide or limited to one color or size |
| Customer journey | Journey map + satisfaction score | From why they bought to months of use, which stage is worst |
| Vs. competitors | Competitive benchmark | Share of reviews mentioning each topic, mine vs. each competitor; weaknesses and selling points |
| Actions / all quotes | — | What to do first; every claim traces back to the original review |

### Division of labor

- **The AI** reads reviews, writes a Chinese summary per review, tags them, and drafts recommendations.
- **`analyze.py`** computes every count, share, ranking, and score. The AI never does the math itself.
- Each run starts with a data check that flags untagged reviews, tags without a journey stage, and names that don't match a tag.

### Limits

- Writes local files only. It never sends messages, edits listings, or touches ads; it drafts and leaves decisions to a human.
- Competitor comparison reports share differences only. Star-rating impact needs Amazon's official review topics (SP-API Customer Feedback).
- Vine reviews are tracked separately and excluded; reviewer names are not kept.

The bundled example is a publicly listed jute stair tread, used only to demonstrate the workflow.

## License

MIT · © 2026 Way to AIC
