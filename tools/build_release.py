# -*- coding: utf-8 -*-
"""按定稿整份直出发布件（HTML / PDF / EPUB）——董老师 2026-10-08 定。

背景：Release 上的 PDF/EPUB/HTML 此前由 CI 从仓库文件**重新拼装**（head.md +
front-* + 按「读者章」重排的 book/ + about + 纠错台账），结构与定稿不一致。
董老师定：「GitHub 上的 PDF 和其它的几个文件，就按定稿的《香港留学指南》
内容和格式来做」——即**以定稿为唯一源**，不再重新拼装。

定稿本身是一份完整的成书稿：封面（书名/副题/版本行/联系方式）、五个部分、
章级 H2、49 条正文（`### HK-xxx`）。**分页由版式层负责**（判例 27，2026-10-08
董老师定：源文件不再带分页符号）——`assets/book-style.html` 的 `@media print`
让目录与每个章节级标题各自另起一页。本脚本做三件事：

1. HKStudyGuide.html —— 定稿 → 自包含线性 HTML（封面 + 目录 + 正文，样式内嵌）。
   取代旧的「阅读器」（build_reader.py 产物，2026-10-08 董老师停用）。
2. HKStudyGuide.pdf —— print.html 经 Chrome 无头打印（本机）；
   CI 上继续用 weasyprint 吃同一个 print.html（weasyprint 支持页码 counter）。
3. HKStudyGuide.epub —— 定稿经 pandoc（pypandoc-binary）。

用法：
    python tools/build_release.py --draft release/定稿-董老师香港留学指南.md \
        --out dist [--html] [--pdf] [--epub]   # 默认三样全做

验收内建：产物生成后自检（PDF 页数/关键词、EPUB 结构、HTML 外部引用数）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import urllib.parse

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLE = os.path.join(ROOT, "assets", "book-style.html")
DEFAULT_DRAFT = os.path.join(ROOT, "release", "定稿-董老师香港留学指南.md")
TITLE = "董老师香港留学指南"

# 旧稿里可能残留的显式分页符（判例 27 起源文件不再写；这里只做兼容与兜底）
RE_PAGEBREAK = re.compile(r'<div style="page-break-after: always;"></div>')

# Chrome / Edge 的候选路径（Windows 本机打印 PDF 用）
_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def style_css() -> str:
    """book-style.html 里只取 <style>（尾部的浮动按钮 <script> 打印时会真执行，
    必须剥掉；weasyprint 忽略 JS 所以 CI 侧不受影响，Chrome 会受）。"""
    html = read(STYLE)
    m = re.search(r"<style>(.*?)</style>", html, flags=re.S)
    if not m:
        raise SystemExit("[错] assets/book-style.html 里没找到 <style> 块")
    return m.group(1)


def _slugify_factory():
    """markdown 的 toc 扩展默认 slugify 会把中文全剥掉，导致 id 重复/为空。
    用「顺序号 + 内容摘要」保证稳定且唯一。"""
    counter = {"n": 0}

    def slugify(value: str, separator: str) -> str:
        counter["n"] += 1
        digest = hashlib.md5(value.encode("utf-8")).hexdigest()[:8]
        return f"h{counter['n']:03d}-{digest}"

    return slugify


def render_body(md_text: str):
    """定稿 markdown → (正文 HTML, 目录 HTML)。"""
    md = markdown.Markdown(
        extensions=["tables", "toc"],
        extension_configs={
            "toc": {"slugify": _slugify_factory(), "toc_depth": "1-2"},
        },
    )
    body = md.convert(md_text)
    return body, build_toc_html(md.toc_tokens)


def build_toc_html(tokens) -> str:
    """不带 <h2>目录</h2>——assets/book-style.html 里有 nav#TOC::before{content:"目录"}，
    自己再写一个就会出现两个「目录」（实测踩过）。"""
    parts = ['<nav id="TOC">', "<ul>"]

    def walk(items):
        for t in items:
            parts.append(f'<li><a href="#{t["id"]}">{t["name"]}</a>')
            if t.get("children"):
                parts.append("<ul>")
                walk(t["children"])
                parts.append("</ul>")
            parts.append("</li>")

    walk(tokens)
    parts.append("</ul></nav>")
    return "\n".join(parts)


def inject_toc(body: str, toc_html: str) -> str:
    """把目录插在封面之后、正文之前。

    2026-10-08 起源文件不再带分页符号（判例 27），定位改用**结构**：
    第 2 个 `<h1>` 之前（第 1 个是封面书名，第 2 个是「# 第一部分」）。
    目录本身另起一页由 assets/book-style.html 的 `nav#TOC{page-break-before}`
    承担——所以这里不再注入任何分页符。
    """
    hits = list(RE_PAGEBREAK.finditer(body))
    if len(hits) >= 2:
        # 兼容旧稿：源里还留着分页符时按旧法定位（封面后第一处）
        return body[:hits[1].end()] + "\n\n" + toc_html + "\n\n" + body[hits[1].end():]
    h1s = [m.start() for m in re.finditer(r"<h1[ >]", body)]
    if len(h1s) >= 2:
        pos = h1s[1]
        return body[:pos] + toc_html + "\n\n" + body[pos:]
    print("  ! 没找到封面后的第一个 h1，目录放在最前")
    return toc_html + "\n\n" + body


def build_html(draft: str, out_dir: str) -> str:
    body, toc = render_body(draft)
    body = inject_toc(body, toc)
    # 扉页标题挂 title 类（样式里 h1.title 居中大字；pandoc 会自动挂，
    # 我们自己转换就得手动挂，否则扉页是一行不起眼的小标题——实测踩过。
    # 注意 markdown 产物带 id 属性，不能直接 replace "<h1>"）。
    body = re.sub(r"<h1(?![^>]*class=)", '<h1 class="title"', body, count=1)
    html = (
        "<!doctype html>\n"
        '<html lang="zh-Hans">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{TITLE}</title>\n"
        f"<style>{style_css()}</style>\n"
        "</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    )
    path = os.path.join(out_dir, "HKStudyGuide.html")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    # 同一份作为 PDF 打印输入
    with open(os.path.join(out_dir, "print.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    return path


def build_pdf(out_dir: str) -> str:
    src = os.path.abspath(os.path.join(out_dir, "print.html"))
    dst = os.path.abspath(os.path.join(out_dir, "HKStudyGuide.pdf"))
    browser = next((b for b in _BROWSERS if os.path.isfile(b)), None)
    if browser is None:
        raise SystemExit("[错] 找不到 Chrome/Edge，无法本机打印 PDF（CI 上请用 weasyprint）")
    file_url = "file:///" + urllib.parse.quote(src.replace("\\", "/"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf=" + dst,
        file_url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not os.path.isfile(dst) or os.path.getsize(dst) < 100_000:
        raise SystemExit(f"[错] PDF 打印失败：{r.stderr[-400:]}")
    return dst


def build_epub(draft_path: str, out_dir: str) -> str:
    import pypandoc  # pypandoc-binary 自带 pandoc 可执行文件

    dst = os.path.join(out_dir, "HKStudyGuide.epub")
    pypandoc.convert_file(
        draft_path,
        "epub",
        format="gfm",
        outputfile=dst,
        extra_args=[
            "--toc", "--toc-depth=2",
            "--metadata", f"title={TITLE}",
            "--metadata", "lang=zh-Hans",
            "--metadata", "creator=董老师",
        ],
    )
    return dst


def verify(out_dir: str) -> None:
    """产物自检：外部引用、内部术语、PDF 页数与抽样、EPUB 结构。"""
    problems = []

    html_path = os.path.join(out_dir, "HKStudyGuide.html")
    html = read(html_path)
    ext = re.findall(r'(?:src|href)="(?!#)([^":]+)"', html)
    ext = [u for u in ext if not u.startswith(("http", "mailto:"))]
    if ext:
        problems.append(f"HTML 残留外部引用 {len(ext)} 个：{ext[:5]}")
    n_pb = len(RE_PAGEBREAK.findall(html))
    if n_pb:
        problems.append(f"HTML 里残留 {n_pb} 处显式分页符（判例 27：分页归版式层）")
    for bad in ("WB2", "WB4", "判例"):
        if bad in html:
            problems.append(f"HTML 含内部术语「{bad}」")

    pdf_path = os.path.join(out_dir, "HKStudyGuide.pdf")
    if os.path.isfile(pdf_path):
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        n = len(reader.pages)
        sample = reader.pages[0].extract_text() or ""
        mid = reader.pages[n // 2].extract_text() or ""
        last = reader.pages[-1].extract_text() or ""
        print(f"  · PDF：{n} 页；首页抽样「{sample[:40]!r}」")
        if "留学指南" not in sample:
            problems.append("PDF 首页没抽到书名（可能字体/渲染异常）")
        if len(mid.strip()) < 50:
            problems.append("PDF 中间页文字过少（可能乱码或空白页）")
        whole = sample + mid + last
        for bad in ("WB2", "WB4", "判例"):
            if bad in whole:
                problems.append(f"PDF 含内部术语「{bad}」")

    epub_path = os.path.join(out_dir, "HKStudyGuide.epub")
    if os.path.isfile(epub_path):
        import zipfile

        with zipfile.ZipFile(epub_path) as zf:
            names = zf.namelist()
            ok_mimetype = "mimetype" in names
            content = [n for n in names if n.endswith((".xhtml", ".html"))]
            text = "".join(zf.read(n).decode("utf-8", "ignore") for n in content[:8])
        print(f"  · EPUB：{len(names)} 个内部文件，正文页 {len(content)} 个")
        if not ok_mimetype:
            problems.append("EPUB 缺 mimetype")
        if "HK-" not in text:
            problems.append("EPUB 前几个正文页没抽到条目编号")

    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        raise SystemExit(1)
    print("  ✓ 自检通过（无外部引用 / 无内部术语 / PDF 与 EPUB 结构正常）")


def main():
    ap = argparse.ArgumentParser(description="按定稿整份直出发布件（HTML/PDF/EPUB）")
    ap.add_argument("--draft", default=DEFAULT_DRAFT, help="定稿 md 路径")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"), help="输出目录")
    ap.add_argument("--html", action="store_true", help="只做 HTML（默认全做）")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--epub", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.draft):
        raise SystemExit(f"[错] 定稿不存在：{args.draft}")
    os.makedirs(args.out, exist_ok=True)
    draft = read(args.draft)
    print(f"定稿：{args.draft}（{len(draft)} 字符，md5 {hashlib.md5(draft.encode()).hexdigest()[:8]}）")

    do_all = not (args.html or args.pdf or args.epub)
    if do_all or args.html:
        p = build_html(draft, args.out)
        print(f"  ✓ HTML  {os.path.basename(p)}  {os.path.getsize(p):,} 字节")
    if do_all or args.pdf:
        p = build_pdf(args.out)
        print(f"  ✓ PDF   {os.path.basename(p)}  {os.path.getsize(p):,} 字节")
    if do_all or args.epub:
        p = build_epub(args.draft, args.out)
        print(f"  ✓ EPUB  {os.path.basename(p)}  {os.path.getsize(p):,} 字节")
    if not args.no_verify:
        verify(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
