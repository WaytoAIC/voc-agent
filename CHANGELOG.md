# Changelog

## Unreleased

## v1.2.0 · 2026-10-28

- 新增「站外 VOC · Reddit」一步（`offsite/`）：`collect_reddit.py` 用 reddit-readonly 采集（设了 `SORFTIME_KEY` 全站搜索先走 Sorftime），`TAGGING.md` 规定 AI 怎么打标，`analyze_offsite.py` 算全部数字，`to_feishu.py` 可选写飞书。品类相关的词表、环节、需求清单都放在每个产品的 `config.json`，附楼梯踏板样例。
  Added an off-site VOC step for Reddit (`offsite/`): collect via reddit-readonly (Sorftime leads all-Reddit search when `SORFTIME_KEY` is set), tag per `TAGGING.md`, compute everything in `analyze_offsite.py`, optionally write to Feishu. Category-specific vocabulary, stages and needs live in a per-product `config.json`; a stair-tread example is included.
- 站外分析补上 **⑥ 用户旅程地图（情绪曲线）** 和 **⑦ 需求四象限（需求地图）**，都和站内评论同口径对照；另有站内外同一问题的占比对照、「只有站外在说」的问题。
  The off-site analysis adds the journey emotion curve and the need quadrant, both compared with on-site reviews on the same formula, plus an on/off-site share comparison and problems raised only off-site.
- 报告新增「站外 VOC · Reddit」一块；追问可以问「站外在说什么」。
  New report section "Off-site VOC · Reddit"; follow-ups can ask what is being said off-site.

## v1.1.1 · 2026-10-27

- 用户旅程图补上旅程线：把每一段的满意度连成一条线，体验在哪一段掉下去一眼能看出来。
  The journey chart now draws the journey line, connecting each stage's satisfaction score so drops stand out.

## v1.1.0 · 2026-10-27

- 新增「Alexa 问答」一步：用 apinsight 向亚马逊 Alexa（原 Rufus）提 24 道核心题，`alexa_import.py` 读进 data.json，AI 写中文意思、标签和与评论的对照。
  Added an optional Alexa Q&A step: ask Amazon's Alexa (formerly Rufus) 24 core questions via apinsight, import with `alexa_import.py`, and have the AI summarize, tag, and compare each answer against the reviews.
- `analyze.py` 新增 Alexa 对照：评论里的问题 Alexa 提没提、它多说了什么；不计入任何条数。
  `analyze.py` adds an Alexa cross-check: which review problems Alexa mentions and what it adds. It never enters any count.
- 报告新增「Alexa 怎么跟买家说」一块；样例 B0FMJCMKY1 附 24 条真实问答。
  New report section "What Alexa tells shoppers"; the B0FMJCMKY1 example now includes 24 real answers.
- 报告模板补上 UTF-8 声明，本地直接打开不再乱码。
  The report template now declares UTF-8, so it opens correctly from disk.

## v1.0.0 · 2026-10-20

- 首次发布：给一个 ASIN，拉评论、打标签、出一页 VOC 报告，并支持追问。
  First release: pull reviews for an ASIN, tag them, produce a one-page VOC report, and answer follow-up questions.
- `analyze.py` 负责全部算数：体检、帕累托（二八）、款式下钻、用户旅程满意度、竞品对比。
  `analyze.py` computes everything: data check, Pareto, variant drill-down, journey satisfaction, competitor comparison.
- 报告模板支持深浅色；附完整样例 B0FMJCMKY1。
  Report template with light and dark themes; full example B0FMJCMKY1 included.
