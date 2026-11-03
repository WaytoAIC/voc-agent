# 站外 VOC · Reddit 打标规则

输入：`offsite/parts/part<N>.json`，每个元素是一个讨论串（帖子 + 评论）。
输出：`offsite/parts/tags<N>.json`，一个对象：`{ "<帖子id>": {标签}, ... }`，每个输入的帖子都要有一条；最后合并成 `offsite/tags.json`。

我们的产品：见根目录 `voc.config.json` 的 `product`。

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
- `relevant`：讨论的是**这个产品要解决的事**（楼梯防滑踏板 / 楼梯地毯 / 楼梯防滑）才算 true。木工做楼梯踏步（结构件）、楼梯翻新刷漆、和楼梯无关的地毯清洁 → false，其余字段留空。
- `neg` `pos` **只能用 `voc.config.json` 里 `tags.neg` / `tags.pos` 的词**（站内站外同一套）；`persona` `alt` 只能用 `offsite/config.json` 里的词。不能自造；没有就留空。整串（帖子 + 评论）里有人明确说到就算。遇到词表没有的说法：先把它加进 `voc.config.json`（或加成别名），再用。
- `brand`：被点名的品牌或店铺原样写（如 Ruggable、Amazon Basics），没有留空。
- `quotes`：每个相关讨论串挑 0–2 句最有信息量的买家原话，`topic` 用它对应的标签词。不要编，必须是输入里的原文。
- 不判断数量和占比，数字由 `analyze_offsite.py` 算。
