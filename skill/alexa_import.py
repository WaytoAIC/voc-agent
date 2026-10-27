"""把 apinsight 采集的 Alexa 问答读进 data.json 的 alexa 块。

用法：python3 alexa_import.py <apinsight 批次目录或 results.jsonl> <ASIN>/data.json [--source 说明]

只搬原始问答：题目、分类、英文回答。中文意思、标签、和评论对比的结论
（zh / tags / stance / findings）由 AI 读完回答后再填；已经填过的不会被覆盖。
"""
import json
import pathlib
import sys


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    src = pathlib.Path(args[0])
    if src.is_dir():
        src = src / "results.jsonl"
    data_path = pathlib.Path(args[1])
    d = json.loads(data_path.read_text(encoding="utf-8"))
    asin = d["product"]["asin"]

    rows = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("asin") not in (None, asin) or not (r.get("answer") or "").strip():
            continue
        rows.append(r)
    if not rows:
        sys.exit(f"{src} 里没有 {asin} 的有效回答")

    old = {i["q"]: i for i in d.get("alexa", {}).get("items", [])}
    items = []
    for r in rows:
        q = r["question"].strip()
        prev = old.get(q, {})
        items.append({
            "q": q,
            "category": r.get("category", ""),
            "answer": r["answer"].strip(),
            "zh": prev.get("zh", ""),
            "tags": prev.get("tags", []),
            "stance": prev.get("stance", ""),
        })

    alexa = d.get("alexa", {})
    alexa["items"] = items
    alexa.setdefault("findings", [])
    alexa["price"] = rows[0].get("price") or alexa.get("price")
    if "--source" in args:
        alexa["source"] = args[args.index("--source") + 1]
    alexa.setdefault("source", f"Alexa for Shopping · {src.parent.name}")
    d["alexa"] = alexa
    data_path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    todo = sum(1 for i in items if not i["zh"])
    print(f"读入 {len(items)} 条 Alexa 回答；待填中文意思和标签 {todo} 条 → {data_path}")


if __name__ == "__main__":
    main()
