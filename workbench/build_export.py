"""导出离线版工作台：把当前数据注入页面，写到 导出/VOC工作台.html（能直接双击打开、能传到 claude.ai 当 artifact）。

用法：python3 workbench/build_export.py [--out 导出/VOC工作台.html]
数据和本机版完全同源（voc.config.json / products.json / dashboard.json / offsite / alexa_compare.json），只是没有「问 Agent」和接口。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import serve  # noqa: E402

out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else serve.ROOT / "导出" / "VOC工作台.html"
out.write_text(serve.render_page(), encoding="utf-8")
print(f"{out}  {out.stat().st_size // 1024} KB")
