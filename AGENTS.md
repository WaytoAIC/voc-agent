# 给 AI 编程助手的说明

这个仓库是一套 VOC（用户声音）分析系统，三部分：

| 目录 | 是什么 |
|---|---|
| `skill/` | voc-agent 技能：给一个 ASIN，拉评论、打标签、脚本算数、出报告；含 Alexa 问答、站外 Reddit |
| `agent/` | VOC Agent 的 Hermes profile：岗位规则 `SOUL.md`（带占位符）、`distribution.yaml`、数据源示例、飞书多维表格结构 |
| `workbench/` | VOC 工作台：本机网页，连本机 Hermes，能问 Agent、现场加产品出报告 |

**用户让你「部署 / 搭建 / 装上 / 跑起来」时：严格按 `DEPLOY.md` 一步步做**，开工前先按它的「第 0 步」把要问的一次问完；每步做完跑该步的检查；最后跑 `bash scripts/doctor.sh`，没有 ❌ 才算完成。

**用户只想要分析能力（不要工作台、不要 Hermes）时**：`bash install.sh --target claude`（或 codex / openclaw），装完说「分析 B0XXXXXXXX」。

硬规则：

- 密钥只写进用户本机的 `~/.hermes/profiles/voc/.env` 或 `config.yaml`，不回显、不提交到仓库。
- 卖家精灵、TikHub、Alexa 采集按次计费：真实调用前说清次数，等用户确认。
- 所有条数、占比由 `skill/analyze.py`、`workbench/dashboard.py` 等脚本算，不要手算或估。
- 不改用户已有的 Hermes 配置和其他 profile；要改先问。
