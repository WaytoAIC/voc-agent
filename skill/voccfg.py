"""读 voc.config.json（VOC 唯一真相源），并把一份 data.json 里的标签、阶段换成统一词表。

用法（脚本里）：
    import voccfg
    cfg = voccfg.load(path)              # 从 path 往上找 voc.config.json；也认环境变量 VOC_CONFIG
    notes = voccfg.canonicalize(d, cfg)  # 原地把 d 的标签 / 阶段换成一级词；返回改了什么（给体检打印）
    voccfg.vocab(cfg)                    # (neg 集合, pos 集合, tag→阶段)
"""
import json
import os
import pathlib
import sys

NAME = "voc.config.json"
_cache = {}


def find(start=None):
    env = os.environ.get("VOC_CONFIG")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env).resolve()
    starts = [pathlib.Path(start).resolve() if start else None, pathlib.Path(__file__).resolve(), pathlib.Path.cwd()]
    for s in starts:
        if not s:
            continue
        for p in [s, *s.parents]:
            if (p / NAME).exists():
                return p / NAME
    me = pathlib.Path(__file__).resolve().parent
    for example in (me / "voc.config.example.json", me.parent / "skill" / "voc.config.example.json"):
        if example.exists():                  # 公开版：没建 voc.config.json 就先用 skill 自带的样例，并提醒
            sys.stderr.write(f"⚠ 没找到 {NAME}，先用样例 {example}；正式用请复制一份到项目根目录改成自己的\n")
            return example
    raise FileNotFoundError(f"找不到 {NAME}：放在项目根目录，或设环境变量 VOC_CONFIG")


def load(start=None):
    p = find(start)
    if p not in _cache:
        _cache[p] = json.loads(p.read_text(encoding="utf-8"))
        _cache[p]["_path"] = str(p)
    return _cache[p]


def vocab(cfg):
    neg, pos = cfg["tags"]["neg"], cfg["tags"]["pos"]
    return set(neg), set(pos), {**neg, **pos}


def _alias(cfg, kind):
    return {k: v for k, v in cfg[kind]["alias"].items() if not k.startswith("_")}


def tag(cfg, t):
    """一个标签名 → 一级标签名（没有别名就原样返回）。"""
    return _alias(cfg, "tags").get(t, t)


def stage(cfg, s):
    return _alias(cfg, "stages").get(s, s)


def _dedupe(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def canonicalize(d, cfg):
    """原地改 d：tagsNeg / tagsPos / tagStage / stages / reviews[].tags / problems / praises / alexa.items[].tags。
    返回 notes：{"aliased": {旧: 新}, "notInVocab": [...], "stageAliased": {旧: 新}}。"""
    ta, sa = _alias(cfg, "tags"), _alias(cfg, "stages")
    neg, pos, stage_of = vocab(cfg)
    used_alias, used_stage = {}, {}

    def T(t):
        if t in ta:
            used_alias[t] = ta[t]
            return ta[t]
        return t

    def S(s):
        if s in sa:
            used_stage[s] = sa[s]
            return sa[s]
        return s

    for k in ("tagsNeg", "tagsPos"):
        if k in d:
            d[k] = _dedupe([T(t) for t in d[k]])
    for r in d.get("reviews", []):
        if r.get("tags"):
            r["tags"] = _dedupe([T(t) for t in r["tags"]])
    for grp in ("problems", "praises"):
        for item in d.get(grp, []):
            old = item.get("tag", item.get("name"))
            new = T(old)
            if new != item.get("name"):
                item["tag"] = new
            elif "tag" in item and item["tag"] == item["name"]:
                item.pop("tag")
    if d.get("tagStage"):
        ts = {}
        for t, s in d["tagStage"].items():
            ts[T(t)] = S(s)
        # 一级词表里定了阶段的，以词表为准
        for t in list(ts):
            if t in stage_of:
                ts[t] = stage_of[t]
        d["tagStage"] = ts
    d["stages"] = list(cfg["stages"]["order"])
    for it in (d.get("alexa") or {}).get("items", []):
        if it.get("tags"):
            it["tags"] = _dedupe([T(t) for t in it["tags"]])
    known = neg | pos
    used = {t for r in d.get("reviews", []) for t in r.get("tags", [])} | set(d.get("tagsNeg", [])) | set(d.get("tagsPos", []))
    return {"aliased": used_alias, "stageAliased": used_stage, "notInVocab": sorted(used - known)}
