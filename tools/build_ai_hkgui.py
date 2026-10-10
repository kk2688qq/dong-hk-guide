#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为自有域名主站 hkgui.xinfide.com 生成 AI 可读层（llms.txt / llms-full.txt / 404.html）。

为什么需要单独一份
------------------
仓库根的 `llms.txt` 是 **GitHub 站**的单一来源，其中的目录链接是**相对路径**
（`./book/xxx.md`、`./README.md`、`./docs/...`）—— 这些路径在自有域名站上全部是死链。
本脚本在同一批数据上重写链接目标，**不新增、不改动任何事实、数字与口径**：

- `./book/<文件名>.md`        → `./hk-XXX.html`（本站条目页，编号由正文首行 `# HK-NNN` 解析）
- `./README.md`、`./book/`     → `./index.html`
- `./docs/**`、`./CLAUDE.md` 等 → GitHub 仓库对应绝对地址（本站没有这些路径）

`llms-full.txt`（全文合并，供 AI 一次取完）与 `404.html` 同样由本脚本产出。

用法：
    python tools/build_ai_hkgui.py --out _site-hkgui [--base https://hkgui.xinfide.com]

2026-10-10 WB2 建（配合 hkgui 主站）。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
REPO_WEB = "https://github.com/kk2688qq/dong-hk-guide"
GH = {"book/": "./index.html", "README.md": "./index.html"}

RE_TITLE = re.compile(r"^#\s+(HK-\d{3})\s+(.+?)\s*$")


def read(path: str) -> str:
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def collect_entries():
    """扫描 book/，返回 [(hk, title, text, book_filename)]，按 HK 编号排序。"""
    items = []
    for fn in sorted(os.listdir(BOOK)):
        if not fn.endswith(".md"):
            continue
        txt = read(os.path.join(BOOK, fn))
        m = RE_TITLE.match(txt.split("\n", 1)[0])
        if not m:
            print("  ! 跳过（首行不是 '# HK-NNN 标题'）：%s" % fn)
            continue
        items.append({"hk": m.group(1), "title": m.group(2).strip(),
                      "text": txt, "file": fn})
    items.sort(key=lambda x: x["hk"])
    return items


def rewrite_links(src: str, entries) -> str:
    """把仓库根 llms.txt 的相对链接改成自有域名站上有效的目标。

    只改 markdown 链接的**目标**（`](...)`），不动链接文本与一切正文，
    因此不会触碰任何事实、数字与口径。
    """
    by_file = {e["file"]: e["hk"].lower() for e in entries}

    def mark(m):
        url = m.group(1).strip()
        if url in ("./README.md", "./book/"):
            return "](./index.html)"
        if url.startswith("./book/") and url.endswith(".md"):
            hk = by_file.get(url[len("./book/"):])
            return "](./%s.html)" % hk if hk else m.group(0)
        if url.startswith("./docs/"):
            return "](%s/tree/main/docs/%s)" % (REPO_WEB, url[len("./docs/"):])
        if url.startswith("./"):
            name = url[2:]
            if name in ("CLAUDE.md", "GITHUB发布操作手册.md"):
                return "](%s/blob/main/%s)" % (REPO_WEB, name)
        return m.group(0)

    out = re.sub(r"\]\(([^)\s]+)\)", mark, src)

    # 两处入口的**链接文本**同步改写成本站语境（目标已由上面统一重写）
    out = out.replace("- [README（总览 + 全量目录 + 怎么用）](./index.html)",
                      "- [首页（总览 + 全量目录）](./index.html)")
    out = out.replace("- [book/（全部条目正文，Markdown）](./index.html)",
                      "- [条目页（每条一页，HTML）](./index.html)")
    return out


def build_llms_full(entries, base: str) -> str:
    head = [
        "# 董老师香港留学指南2026",
        "",
        "> 站点：%s/ ｜ 共 %d 条" % (base.rstrip("/"), len(entries)),
        "",
        "本文件为全书条目正文合并版，供 AI 一次性读取。原始来源同一批书稿，"
        "条目页与 AI 索引见站点根 llms.txt。",
        "",
    ]
    body = []
    for e in entries:
        body += ["", "---", "", e["text"].rstrip()]
    return "\n".join(head + body).rstrip() + "\n"


def build_404(base: str) -> str:
    b = base.rstrip("/")
    return """<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>页面不存在 · 董老师香港留学指南2026</title>
<style>
  :root{--ink:#26221c;--sub:#6b6154;--line:#e2d9c9;--paper:#faf6ee;--accent:#8a5a2b}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);
       font:16px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;padding:32px}
  .box{max-width:560px;width:100%;text-align:center}
  .code{font-size:64px;font-weight:700;letter-spacing:2px;color:var(--accent);margin:0 0 8px}
  h1{font-size:20px;margin:0 0 12px}
  p{color:var(--sub);margin:0 0 24px}
  a.btn{display:inline-block;padding:10px 22px;border:1px solid var(--line);border-radius:999px;
        color:var(--ink);text-decoration:none;background:#fff}
  a.btn:hover{border-color:var(--accent);color:var(--accent)}
  .hot{margin-top:32px;padding-top:20px;border-top:1px solid var(--line);
       font-size:14px;color:var(--sub);text-align:left}
  .hot b{display:block;margin-bottom:8px;color:var(--ink);font-size:15px}
  .hot a{display:block;color:var(--accent);text-decoration:none;padding:3px 0}
  .hot a:hover{text-decoration:underline}
</style>
</head>
<body>
  <div class="box">
    <p class="code">404</p>
    <h1>这个页面不存在</h1>
    <p>链接可能已经更新，或者地址打错了一个字符。</p>
    <a class="btn" href="/">回到指南首页</a>
    <div class="hot">
      <b>常被查的几条</b>
      <a href="/hk-002.html">赴港读本科一年要花多少钱</a>
      <a href="/hk-019.html">高才通 A 类：过去一年收入要达到多少</a>
      <a href="/hk-034.html">内地生插班香港中学：笔试和面试考什么</a>
      <a href="/hk-063.html">一年制港硕怎么选</a>
      <div style="margin-top:10px">站内入口：<a href="/" style="display:inline">首页</a>
        ｜ <a href="/sitemap.xml" style="display:inline">站点地图</a>
        ｜ <a href="/llms.txt" style="display:inline">AI 索引</a></div>
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site-hkgui"))
    ap.add_argument("--base", default=os.environ.get("SITE_BASE_URL", "https://hkgui.xinfide.com"))
    a = ap.parse_args()

    out = a.out
    if not os.path.isdir(out):
        sys.exit("目标目录不存在（请先跑 build_web.py）：%s" % out)

    entries = collect_entries()
    print("解析条目：%d 条" % len(entries))

    src_llms = read(os.path.join(ROOT, "llms.txt"))
    llms = rewrite_links(src_llms, entries)
    with io.open(os.path.join(out, "llms.txt"), "w", encoding="utf-8") as fh:
        fh.write(llms)

    with io.open(os.path.join(out, "llms-full.txt"), "w", encoding="utf-8") as fh:
        fh.write(build_llms_full(entries, a.base))

    with io.open(os.path.join(out, "404.html"), "w", encoding="utf-8") as fh:
        fh.write(build_404(a.base))

    # 死链自检：本站不存在的**相对**路径不应残留在链接目标里
    leftover = [u for u in re.findall(r"\]\(([^)\s]+)\)", llms)
                if u.startswith("./") and u != "./index.html"
                and not re.match(r"\./hk-\d{3}\.html$", u)]
    print("llms.txt 写入 %d 字节 ｜ llms-full.txt %d 字节 ｜ 404.html 就绪"
          % (len(llms.encode("utf-8")),
             os.path.getsize(os.path.join(out, "llms-full.txt"))))
    if leftover:
        print("  ! 仍有未重写的相对链接：%s" % leftover[:5])
        return 1
    print("  ✓ 链接自检通过（无 ./book/ ./docs/ 等失效相对路径）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
