"""模型通道（tag.py / project.py 共用）：直连 anthropic 兼容口或 OpenAI 兼容口，没 key 就走本机 Hermes 网关。

- 环境变量：VOC_LLM_API（anthropic / openai，不填按 base 猜）、VOC_LLM_BASE、VOC_LLM_KEY、VOC_LLM_MODEL
- 没设 VOC_LLM_KEY：读 ~/.hermes/profiles/<profile>/.env 的 API_SERVER_KEY，走 http://127.0.0.1:8642/p/<profile>/v1（profile = VOC_HERMES_PROFILE 或 voc.config.json hermes.profile，默认 voc）
- ask(system, user) 返回 (文本, {"in","out"})；网络 / 5xx / 429 最多重试 3 次，4xx 直接抛
- key 只在内存里，不打印、不落盘
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    import voccfg  # noqa: E402
    CFG = voccfg.load()
except Exception:  # 公开仓里 voccfg 在同目录；找不到配置就当空
    CFG = {}


def channel(model=None):
    api, base, key = os.environ.get("VOC_LLM_API"), os.environ.get("VOC_LLM_BASE"), os.environ.get("VOC_LLM_KEY")
    model = model or os.environ.get("VOC_LLM_MODEL")
    if not key:
        profile = os.environ.get("VOC_HERMES_PROFILE") or (CFG.get("hermes") or {}).get("profile", "voc")
        env = pathlib.Path.home() / ".hermes" / "profiles" / profile / ".env"
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            if line.startswith("API_SERVER_KEY="):
                key = line.split("=", 1)[1].strip()
        if not key:
            sys.exit("没有模型通道：设 VOC_LLM_BASE / VOC_LLM_KEY / VOC_LLM_MODEL，或把本机 Hermes 网关开起来（~/.hermes/profiles/<profile>/.env 里要有 API_SERVER_KEY）")
        api, base, model = "openai", f"http://127.0.0.1:8642/p/{profile}/v1", model or profile
    if not api:
        api = "anthropic" if "anthropic" in (base or "") else "openai"
    if not base:
        base = "https://api.anthropic.com" if api == "anthropic" else "https://api.openai.com/v1"
    if not model:
        sys.exit("没设模型名：VOC_LLM_MODEL")
    return {"api": api, "base": base.rstrip("/"), "key": key, "model": model}


def ask(ch, system, user, max_tokens=6000, temperature=0):
    """调一次模型，返回 (文本, 用量 dict)。"""
    for attempt in range(3):
        try:
            if ch["api"] == "anthropic":
                body = {"model": ch["model"], "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": [{"role": "user", "content": user}]}
                req = urllib.request.Request(ch["base"] + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                             headers={"x-api-key": ch["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=300).read())
                text = "".join(c.get("text", "") for c in r.get("content", []))
                u = r.get("usage", {})
                return text, {"in": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0)}
            body = {"model": ch["model"], "temperature": temperature, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            req = urllib.request.Request(ch["base"] + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": "Bearer " + ch["key"], "Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            text = r["choices"][0]["message"]["content"] or ""
            u = r.get("usage", {})
            return text, {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode("utf-8", "ignore")
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"模型接口返回 {e.code}：{msg}")
            err = f"{e.code} {msg}"
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
            err = repr(e)
        sys.stderr.write(f"  调用失败（第 {attempt + 1} 次）：{err}\n")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("模型连续 3 次没回")


def parse_json(text):
    """从模型回复里抠出第一个 JSON 数组 / 对象。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    i, j = s.find("["), s.rfind("]")
    io, jo = s.find("{"), s.rfind("}")
    if i != -1 and (io == -1 or i < io):
        return json.loads(s[i:j + 1])
    return json.loads(s[io:jo + 1])
