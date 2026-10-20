"""把 data.json 填进 template.html，生成同目录下的「报告.html」。
同目录有 main.jpg 时，把它嵌进报告当商品主图（发布后外链图片会被拦）。

用法：python3 render.py <ASIN 目录>/data.json
"""
import base64
import json
import pathlib
import sys

data_path = pathlib.Path(sys.argv[1]).resolve()
tpl = (pathlib.Path(__file__).resolve().parent / "template.html").read_text(encoding="utf-8")
data = json.loads(data_path.read_text(encoding="utf-8"))
img = data_path.parent / "main.jpg"
if img.exists():
    data["imageData"] = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode()
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
out = data_path.parent / "报告.html"
out.write_text(tpl.replace("/*DATA*/", blob), encoding="utf-8")
print(out)
