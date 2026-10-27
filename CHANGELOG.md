# Changelog

## Unreleased

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
