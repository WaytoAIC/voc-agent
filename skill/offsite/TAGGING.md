# 站外 VOC · Reddit 打标规则

先把 `raw.json` 里的帖子分成几份（每份 20–30 个讨论串，存 `parts/part<N>.json`），一份一份读，或交给子任务并行读。
每份输出 `parts/tags<N>.json`，最后合并成 `tags.json`：`{ "<帖子id>": {标签}, ... }`，每个输入的帖子都要有一条。

产品是什么、买家是谁：看 `config.json` 的 `product`。

每条标签：
```json
{
  "relevant": true,
  "neg": [], "pos": [], "persona": [], "alt": [],
  "brand": [],
  "gist": "一句中文，说这个讨论串在聊什么、结论是什么（≤40 字）",
  "quotes": [{"topic": "某个标签", "en": "原文一句（≤200 字符，原样摘）", "zh": "中文翻译", "url": "评论或帖子的 permalink"}]
}
```

规则：
- `relevant`：讨论的是**这个产品或同一个需求**才算 true；只是碰巧出现了关键词（比如木工做楼梯踏步、和楼梯无关的地毯清洁）→ false，其余字段留空。
- `neg` `pos` `persona` `alt` 只能用 `config.json` 的 `taxonomy` 里的词，不能自造；没有就留空。整串（帖子 + 评论）里有人明确说到就算。
  真有反复出现、词表里没有的说法，先停下来告诉用户，加进 `taxonomy`（并补 `stage_of`、`needs`）后再打。
- `brand`：被点名的品牌或店铺原样写（如 Ruggable、Amazon Basics），没有留空。
- `quotes`：每个相关讨论串挑 0–2 句最有信息量的原话，`topic` 用它对应的标签词。必须是输入里的原文，不能编。
  **`title_is_summary: true` 的标题和 `summary` 字段是 Sorftime 写的 AI 摘要，不是用户原话，不能进 `quotes`**；只能用正文 `text` 和评论。
- 不判断数量和占比，数字由 `analyze_offsite.py` 算。
