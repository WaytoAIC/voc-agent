# Changelog

## v1.9.0 · 2026-11-07

- 新增 **脱敏投影 `skill/project.py`**（配 `skill/llm.py` 共用模型通道）：把真实自家数据投成可对外演示的数据——原话由模型改写（意思、星级、标签、款式不变）、每条按固定倍数 k 扩成多条变体、日期整体平移、产品换别名；改写结果缓存，每周只改写新评论；`--check` 核对星级 / 标签 / 款式 / 送测分布与真实一致、每周条数 = 真实 × k、无敏感词、变体与真原话无连续 8 词重合。`weekly.py` 多一步「投影」；`voc.config.json` 加 `own.projection`（默认关）；别名 data.json 带 `projection.realByWeek`，看板 `kpi.voices.realNow` 给真实样本量，群草稿真实不足 5 条会提示别下结论。示例自家从此是真实产品的投影，口径「真实产品数据，经脱敏与等比扩增至类目中位规模」。DEPLOY 第 8.6 步、README「数据口径」说明。
  New `skill/project.py` (with the shared model client `skill/llm.py`) projects a seller's real own-product data into a demo-safe dataset: review texts are paraphrased by the model (meaning, star, tags and variant unchanged), every row is expanded into k variants, dates are shifted and the product gets an alias; paraphrases are cached so weekly runs only rewrite new reviews. `--check` verifies that star / tag / variant / Vine distributions match the real data, weekly counts equal real × k, and no banned term or 8-word run from the real text leaks. `weekly.py` gained a projection step, `voc.config.json` an `own.projection` section (off by default), the alias data.json carries `projection.realByWeek`, the dashboard `kpi.voices.realNow`, and the weekly draft warns when the real sample is under 5. The bundled own product is now such a projection of a real listing.
- 投影也覆盖退货 / 换货 / 买家消息：真实 events（`import_events.py … --out voc-reports/_real/<真实ASIN>/data.json` 导入，`tag.py --events` 读过备注）按同一个 k 扩增，原因码 / 真实原因 / 款式继承，备注由模型改写（并行、每 20 条落缓存）；款式归一同时认卖家精灵写法和后台 MSKU 写法（颜色 → 中文、片数、落地垫、夜光）；`--check` 对事件也核对类型 / 原因码 / 真实原因 / 款式分布与条数。`import_events.py` 码表加 `POOR_FIT`。
  Events (returns / exchanges / buyer messages) are projected too with the same k, notes paraphrased in parallel with incremental caching; the variant normalizer understands both SellerSprite and back-office MSKU spellings; `--check` covers event distributions and counts; `import_events.py` maps `POOR_FIT`.
- 产品详情页顶部显示 `product.note`（数据口径）；`detail.py` 把 `note` / `projection` 带给工作台。
  The product page shows `product.note` (data provenance); `detail.py` passes `note` / `projection` to the workbench.

## v1.8.1 · 2026-11-07

- **增量拉评论去重修正**（`workbench/ss_pull.py --merge --new-only`）。首次真跑暴露两处漏洞：① 早期手工整理的 data.json 里原话被压缩 / 截断过，精确文本键对不上，旧评论被当新评论重复并入；② 个别旧行时间戳和卖家精灵原始值差 1 小时跨了天。现在去重键 = 星级 + 原话前 160 字，日期按 26 小时容差比；没有 `title` 字段的旧行再按「同星级 + 日期容差 + 旧文本实词 ≥ 50% 出现在原话里」认作同一条，并顺手把原话换成真原文、补 `title`（zh / tags / id 不动），`pulled.lastPull.upgraded` 记条数。
  Dedup fix for the incremental pull: review texts in hand-built data.json files were condensed or truncated and some timestamps were off by an hour across midnight, so known reviews were re-added as new. The key is now star + first 160 chars with a 26-hour date tolerance, and legacy rows (no `title`) are matched by star, date tolerance and ≥ 50 % content-word overlap, then upgraded to the verbatim text (`pulled.lastPull.upgraded` counts them).
- `skill/events_to_feishu.py` 回填事件 ID 前检查该 ID 是否已被同一 data.json 里别的评论占用，撞号记 `dupInData` 并报出来、不写。
  The Feishu writer no longer back-fills an event id already used by another review in the same data.json; collisions are reported as `dupInData`.

## v1.8.0 · 2026-11-07

- 新增 **每周运转 `skill/weekly.py`**：一条命令串起 增量拉评论（`workbench/ss_pull.py --merge --new-only`：按日期倒序只拉到已有评论为止，直接并进 data.json，新评论排最前、详情顺手刷新）→ `tag.py` 只给新评论打标 → analyze / render / dashboard → `actions.py pull / readback / check` → 入飞书 → 群消息草稿。每一步失败不拦后面，结果一行写进 `voc-reports/runs.jsonl`（工作台设置页「运行记录」），完整日志在 `voc-reports/_runs/`；`--dry-run` 不调任何接口。口径在 `voc.config.json` 新增的 `weekly` 段；DEPLOY 第 9.5 步给出挂 Hermes cron 的做法（纯脚本模式）。
  New weekly runner `skill/weekly.py`: incremental review pull (`workbench/ss_pull.py --merge --new-only` stops at the first page of already-known reviews and merges straight into data.json), tagging of new reviews only, analyze / render / dashboard, action-card pull / readback / check, Feishu sync and a group-message draft. Steps are isolated, every run appends one line to `voc-reports/runs.jsonl` (shown on the workbench settings page), `--dry-run` touches no API; settings live in the new `weekly` section of `voc.config.json`, and DEPLOY step 9.5 shows how to schedule it with Hermes cron.
- 新增 **评论入飞书 `skill/events_to_feishu.py`**：自家 + 竞品已打标的评论和导入过的退货 / 换货 / 买家消息，一条一行写进「VOC 事件明细」；事件 ID `R-<ASIN>-NNN` / `E-<ASIN>-<id>`，按事件 ID 和「子ASIN + 原话」去重并把表里已有行的 ID 回填进 data.json；问题分类 / 阶段 / 该谁改 用到的新选项先补进字段再写（飞书不会自动建选项）。
  New `skill/events_to_feishu.py` writes tagged reviews and imported returns / exchanges / buyer messages into the Feishu events table one row each, deduplicated by event id and by child ASIN + verbatim text (back-filling ids into data.json), and adds missing select options to the fields before writing.
- 工作台设置页新增 **本周群消息草稿**：`weekly.py` 起草，人改好点「发到群」才发（离线版只显示）。`serve.py` 的 `/api/status` 多了 `draft` / `draftAt`。
  The settings page now shows the weekly group-message draft with a send button that only acts on a click; `/api/status` gained `draft` / `draftAt`.
- `data.schema.json`：评论的 `id`（飞书事件 ID）和 `tagger` 字段说明；`pulled.lastPull` 记录每次增量拉了几页、新增几条、为什么停。
  Schema notes for review `id` / `tagger` and `pulled.lastPull`.


## v1.7.0 · 2026-11-07

- 工作台 **产品详情页和设置页不再写死任何数字**：新增 `skill/detail.py` 从 data.json（calc / journey）、竞品、行动卡算出概况、用户在说什么、退货与换货、用户旅程、和竞品比；`serve.py` 注入 `details` / `status`，并提供 `/api/detail?asin=`、`/api/status`。哪一块没数据就显示「还没有 … ：去哪接」，竞品也能进详情页。
  The workbench product and settings pages no longer embed any numbers: new `skill/detail.py` computes overview, voice themes, returns, journey and competitor comparison from data.json (calc / journey), competitors and action cards; `serve.py` injects `details` / `status` and serves `/api/detail?asin=` and `/api/status`. Every block without data shows an empty state that says how to get it; competitor products open the detail page too.
- 新增 **演示数据开关** `workbench.demo`（`voc.config.json`，或 `VOC_DEMO=0/1`）：关掉后 `workbench/products.json` 的演示行不再注入，列表只剩真实分析过的 ASIN。
  New demo switch `workbench.demo` (or `VOC_DEMO=0/1`): off hides the demo rows in `workbench/products.json`, leaving only analyzed ASINs.
- 新增 **退货 / 换货 / 买家消息导入** `skill/import_events.py`（FBA 退货报告、赛狐 / 领星导出、买家消息表；原因码翻中文、按类型 + 日期 + 款式 + 订单号去重、订单号不存）和 `tag.py --events`（把备注读成一个一级标签写进 `real`，买家消息记提问主题）。`dashboard.py` / `detail.py` 的退货块按 `real` 算。
  New `import_events.py` for returns / exchanges / buyer messages from exported spreadsheets (FBA return report, Sellfox / Lingxing exports, message exports; reason codes translated, deduplicated, order ids never stored) and `tag.py --events`, which reads each note into one first-level tag (`real`; buyer messages get the question topic). Dashboard and detail use `real` for the returns blocks.
- 产品列表：真实产品显示本周新评论、近 30 天退货 / 换货件数、按款式展开（评论占比、差评占比、退货、换货、最大问题）。缺失的数据文件接口返回空 JSON，不再在控制台报 404。
  Product lists show weekly new reviews, 30-day returns / exchanges and a per-variant breakdown for real products; missing data files return empty JSON instead of 404.


## v1.6.0 · 2026-11-07

- 新增 **打标脚本 `skill/tag.py`**：分批把评论交给模型（OpenAI / Anthropic 兼容口，或本机 Hermes 网关），只收 `voc.config.json` 词表里的一级词（别名自动换、词表外说法只汇总不写入），逐条校验、坏的重打、覆盖率低于验收线自动补跑，默认只处理还没打过标的评论（增量）。打标不再在对话里手写。
  New tagging script `skill/tag.py`: batched model calls (OpenAI- or Anthropic-compatible endpoints, or the local Hermes gateway), vocabulary-only tags with alias folding, per-item validation and retries, an automatic extra pass when coverage falls below the acceptance line, and incremental runs by default. Tagging is no longer done by hand in chat.
- 新增 **金标评测**：`skill/examples/golden.json`（50 条，按星级分层）+ `tag.py eval`，报 Jaccard、完全一致率、好坏方向一致率，验收线在 `acceptance.eval_jaccard` / `eval_polarity_pct`；`tag.py golden-build` 从自己复核过的数据建金标集。
  Golden-set evaluation: `skill/examples/golden.json` (50 reviews, stratified by star) plus `tag.py eval`, reporting Jaccard, exact-match and polarity agreement against configurable lines; `tag.py golden-build` builds a golden set from your own reviewed data.
- 词表新增兜底标签「总体满意」「总体不满」，只给没说具体内容的泛泛评论；`voccfg.canonicalize` 现在会按词表给用到的标签补阶段。
  Two fallback tags for reviews with no specific content; `voccfg.canonicalize` now fills journey stages for every used tag from the vocabulary.


## v1.5.0 · 2026-11-05

- 新增 **唯一口径文件 `voc.config.json`**（样例 `skill/voc.config.example.json`，加载器 `voccfg.py`）：一级标签词表 + 别名合并表、旅程 6 段（为什么买 → 选购比较 → 收货安装 → 日常使用 → 用了很久 → 再买或拆掉）、该谁改、阈值、自家 / 竞品 ASIN、飞书表和群。`analyze.py`、`dashboard.py`、站外脚本、`serve.py` 全部读它；站内、竞品、站外 Reddit 用同一套标签。
  New single source of truth `voc.config.json` (example in `skill/voc.config.example.json`, loader `voccfg.py`): first-level tags with alias merging, the six journey stages, owners, thresholds, own/competitor ASINs, Feishu table IDs. Every script and the workbench read it; on-site, competitor and Reddit tagging share one vocabulary.
- 站外 VOC 的词表、环节、需求组、飞书 ID 从 `offsite/config.json` 移到 `voc.config.json`；`offsite/config.json` 只留搜什么、去哪搜、人群 / 替代方案和每段的机会建议。情绪分改成和站内同一个公式。
  Off-site taxonomy, stages, needs and Feishu IDs moved from `offsite/config.json` into `voc.config.json`; the per-product file keeps only queries, subreddits, persona/alt words and per-stage opportunities. The emotion score now uses the same formula as on-site.
- 工作台页面不再内嵌任何数据：`serve.py` 启动时注入配置、产品列表（`products.json`）、看板、站外、Alexa；新增 `build_export.py` 生成同源离线版。页面 678KB → 328KB。
  The workbench page embeds no data any more: `serve.py` injects config, products, dashboard, off-site and Alexa at load; `build_export.py` writes an offline copy from the same sources.
- 新增 **优先级分**（`calc.priority` = 提到占比 × 低星占比）和 **按月看**（`calc.monthly`），报告「先改哪几件」多两列、多一块「按月看」。
  New priority score (share of reviews × low-star rate) and a monthly slice of every problem; the report shows both.
- 新增 **零付费入口** `skill/import_reviews.py`（评论 CSV → data.json 骨架）和 `skill/data.schema.json`；`analyze.py` 先校验结构再算。
  New zero-cost entry: `import_reviews.py` turns a review CSV into a data.json skeleton; `analyze.py` validates the structure first.
- 新增 **行动闭环** `skill/actions.py`（接飞书「行动项跟踪」表）：镜像、到期读回（评论占比类指标自动算实际值和判断，只写两个 AI 字段）、巡检四种卡住、动作—结果曲线；工作台「行动」页改读真实卡片。
  New action loop `actions.py` for the Feishu action table: mirror, due-date read-back (computes actual value and verdict for review-share metrics, writes only the two AI fields), stuck-card checks, action-vs-result curve; the workbench actions page now reads real cards.
- 体检新增打标覆盖率（验收线 `acceptance.tag_coverage_pct`）、词表外标签、该谁改校验。
  Data check now reports tag coverage against the acceptance line, out-of-vocabulary tags and unknown owners.

## v1.4.0 · 2026-10-28

- 新增 **一键部署**：`DEPLOY.md` 是给 AI 编程助手照着做的部署指南（先问清、每步验收、密钥只进本机）；`AGENTS.md`（`CLAUDE.md` 指向它）告诉 AI 收到「部署」时按它做；`scripts/doctor.sh` 逐项自检。
  One-step deployment: `DEPLOY.md` is a step-by-step guide for AI coding assistants (ask first, verify every step, keys stay local); `AGENTS.md` (with `CLAUDE.md` pointing to it) routes "deploy" requests there; `scripts/doctor.sh` checks everything.
- 新增 `agent/`：VOC Agent 的 Hermes profile，`hermes profile install ./agent` 一条命令装好；岗位规则 `SOUL.md` 带占位符，附数据源示例和飞书三张表的结构。
  New `agent/`: the VOC Agent as a Hermes profile distribution, installable with `hermes profile install ./agent`; a placeholder `SOUL.md`, a data-source example and the Feishu table schema.
- 工作台接你自己的数据：分析过的 ASIN 自动进产品列表；设 `VOC_OWN_ASIN` 并跑 `dashboard.py` 后首页换成自家产品的看板；评论少的产品也不会报错。
  The workbench now loads your own data: analyzed ASINs join the product list automatically, and with `VOC_OWN_ASIN` plus `dashboard.py` the home dashboard switches to your product; sparse products no longer break it.

## v1.3.0 · 2026-10-28

- 开源 **VOC 工作台**（`workbench/`）：首页数据看板（按周切换的时间轴、分析结论、瀑布图、哑铃图等）、我的产品、产品详情、站外 VOC（Reddit 情绪曲线、需求四象限）、Agent 岗位卡，自带楼梯踏板案例数据。
  Open-sourced the **VOC Workbench** (`workbench/`): a home dashboard with a weekly time axis, findings, waterfall and dumbbell charts; products; product detail; off-site VOC (Reddit emotion curve, need quadrant); and the agent's role card, with a stair-tread case built in.
- `serve.py` 把工作台接到本机 Hermes：问 Agent 流式回答；「+ 添加产品」交给 VOC Agent 现场跑完分析，出报告后列表自动填回真实数字；发飞书群必须人点按钮。
  `serve.py` connects the workbench to a local Hermes: streamed answers, "+ Add product" runs a real analysis and fills the list back in when the report is ready, and group posts need a human click.
- `ss_pull.py`：卖家精灵 MCP 没加载上或报错时的直连兜底，自带重试。
  `ss_pull.py`: a direct Seller Sprite fallback with retries for when the MCP is missing or failing.

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
