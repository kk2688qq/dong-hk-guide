#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库内容编译成一个**可发布的静态站**（GitHub Pages 用）。

设计原则（与项目的「AI 可读层」一致）：
- **不新增任何事实**：只把 book/ 已有正文渲染成 HTML，数字与口径一律不动。
- **单一来源**：条目标题 / 风险导向 / 证据等级一律从 book/ 正文解析，
  对照表（docs/HK编号对照表.md）只用于「读者章（分类）」与「状态」。
- **对 AI 友好**：站点根目录落 llms.txt、robots.txt、llms-full.txt（全文合并），
  并提供 sitemap.xml。
- **对读者友好**：index.html 是目录页，每条一页，另有 book.html（单文件全书）。

用法：
    python tools/build_site.py            # 输出到 ./site
    python tools/build_site.py --out dist-site
环境变量：
    SITE_BASE_URL  站点绝对前缀（写 sitemap 与 canonical 用），默认
                   https://kk2688qq.github.io/dong-hk-guide
    SITE_BOOK_HTML 可选：已有的单文件全书 HTML 路径（如 dist/HKStudyGuide.html），
                   存在则复制为 site/book.html
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("需要 markdown 库：pip3 install markdown")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
META = os.path.join(ROOT, "meta")
DOCS = os.path.join(ROOT, "docs")
CATALOG = os.path.join(DOCS, "HK编号对照表.md")
BASE_URL = os.environ.get("SITE_BASE_URL", "https://kk2688qq.github.io/dong-hk-guide").rstrip("/")
BOOK_TITLE = "董老师香港留学指南"

# 读者章（分类）与对照表解析：**单一来源在 tools/catalog.py**（零依赖），
# 这里只做转出，供 build_reader.py 沿用 `from build_site import GROUPS, group_of` 的调用方式。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import (  # noqa: E402
    GROUP_DESC,
    GROUP_NAMES,
    GROUPS,
    group_of,
    load_catalog,
    version_info,
)

# 版本号：**单一来源是 meta/about.md**（与 readme_sync.py 同源，026 C-2 / 判例 15）。
VERSION, VERSION_DATE = version_info()
VERSION_LINE = f"版本 {VERSION} · {VERSION_DATE}" if VERSION else ""

# 对外联系方式（全库统一，判例 24 同期口径；改这里前先改 README / meta/about.md 并同步）
CONTACT = "微信 jack787300、dxw22465 ｜ 邮箱 kk2688@agent.qq.com"

# ---------------------------------------------------------------- 解析

RE_TITLE = re.compile(r"^#\s+(HK-\d{3})\s+(.+?)\s*$")
RE_RISK_TAG = re.compile(r"<!--\s*风险\s*=\s*(\S+)\s+阶段\s*=\s*(\S+)\s+焦虑\s*=\s*(\S+?)\s*-->")
RE_GRADE = re.compile(r"证据等级\*{0,2}\s*[:：]\s*\*{0,2}\s*([ABC])")
RE_LEDE = re.compile(r"\*\*说人话\*\*\s*\n+(.+?)(?=\n\s*\n)", re.S)
RE_WHO = re.compile(r"\*\*谁该看\*\*\s*[:：]?\s*(.+?)(?=\n|$)")
RE_LASTCHECK = re.compile(r"最后更新\s*[:：]\s*(\d{4}-\d{2}-\d{2})")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_entry(name: str, text: str) -> dict:
    first = text.split("\n", 1)[0]
    m = RE_TITLE.match(first)
    hk = m.group(1) if m else name[:3]
    title = m.group(2) if m else first.lstrip("# ").strip()

    risk, stage, anxiety = "", "", ""
    mr = RE_RISK_TAG.search(text)
    if mr:
        risk, stage, anxiety = mr.groups()

    mg = RE_GRADE.search(text)
    grade = mg.group(1) if mg else ""

    ml = RE_LEDE.search(text)
    lede = re.sub(r"\s+", " ", ml.group(1)).strip() if ml else ""
    # 说人话首段常是多段：只取到第一个句号群，控制卡片高度
    if len(lede) > 160:
        cut = lede.find("。", 100)
        lede = lede[: cut + 1] if cut != -1 else lede[:160] + "…"

    mw = RE_WHO.search(text)
    who = re.sub(r"\s+", " ", mw.group(1)).strip() if mw else ""

    mc = RE_LASTCHECK.search(text)
    last = mc.group(1) if mc else ""

    return {
        "file": name,
        "num": name[:3],
        "hk": hk,
        "title": title,
        "risk": risk,
        "stage": stage,
        "anxiety": anxiety,
        "grade": grade,
        "lede": lede,
        "who": who,
        "last": last,
        "text": text,
    }


# ---------------------------------------------------------------- 分组
# **读者章**（2026-10-07 董老师定：「按用户对需求来分类，分成章节」）。
# 定义已抽到 tools/catalog.py（单一来源，零依赖）：每条归哪一章写在
# docs/HK编号对照表.md 的「读者章」列，章节顺序与副标题写在 catalog.GROUPS。
# 2026-10-07 前的旧分组按「主题」（升学 / 身份 / 共同）划分，家长和本科生
# 混在同一章；现按读者角色分章：张三是来看本科的、李四是来看申硕的。



# ---------------------------------------------------------------- 渲染

CSS = """
:root{--fg:#1a1a1a;--bg:#fff;--mut:#666;--line:#e6e6e6;--card:#fafbfc;--acc:#0b5cad}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e8;--bg:#16181c;--mut:#9aa1ab;
--line:#2c3038;--card:#1b1e23;--acc:#6db3f2}}
*{box-sizing:border-box}
body{max-width:820px;margin:0 auto;padding:28px 18px 80px;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
line-height:1.85;-webkit-text-size-adjust:100%}
h1{font-size:1.65em;line-height:1.35;margin:0 0 .3em}
h2{font-size:1.25em;margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.3em}
h3{font-size:1.06em;margin-top:1.6em}
p{margin:.75em 0}
table{border-collapse:collapse;width:100%;margin:1.2em 0;font-size:.92em;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--card);font-weight:500}
blockquote{margin:1.2em 0;padding:.6em 1em;border-left:3px solid var(--line);
background:var(--card);color:var(--mut)}
code{background:var(--card);padding:.1em .35em;border-radius:3px;font-size:.9em;
word-break:break-all}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
hr{border:0;border-top:1px solid var(--line);margin:2.2em 0}
.lede{font-size:.98em;color:var(--mut)}
.gdesc{font-size:.92em;color:var(--mut);margin:-2px 0 12px}
.intro{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin:1.2em 0}
.card{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:.7em 0;
background:var(--card)}
.card h3{margin:0 0 .25em;font-size:1.02em}
.badges{margin:.4em 0 .5em;font-size:.78em;color:var(--mut)}
.badge{display:inline-block;border:1px solid var(--line);border-radius:999px;
padding:.1em .6em;margin:0 .35em .3em 0;white-space:nowrap}
.r-高{border-color:#d9534f;color:#d9534f}
.r-中{border-color:#d9a441;color:#d9a441}
.r-低{border-color:#4f9d69;color:#4f9d69}
nav.toc{font-size:.95em}
nav.toc a{display:block;padding:.15em 0}
footer{margin-top:3em;padding-top:1em;border-top:1px solid var(--line);font-size:.85em;
color:var(--mut)}
.top{font-size:.88em;color:var(--mut);margin-bottom:1.4em}
/* 检索筛选（2026-10-07 加）：纯前端，数据全部取自正文解析，不新增事实 */
.filters{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
padding:.7em 0 .6em;margin:0 0 1.2em}
.filters input[type=search]{width:100%;padding:.5em .7em;font-size:1em;border:1px solid var(--line);
border-radius:6px;background:var(--card);color:var(--fg);font-family:inherit}
.frow{display:flex;flex-wrap:wrap;gap:.35em;align-items:center;margin-top:.5em;font-size:.9em}
.frow b{color:var(--mut);font-weight:400;margin-right:.15em}
.fbtn{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;
padding:.15em .6em;cursor:pointer;font-size:.92em;font-family:inherit}
.fbtn[aria-pressed=true]{border-color:var(--acc);color:var(--acc);font-weight:600}
.fcount{color:var(--mut);font-size:.85em;margin-top:.45em}
.card[hidden],section.grp[hidden]{display:none}
"""

FILTER_JS = """
<script>
(function(){
  var q=document.getElementById('q'), cnt=document.getElementById('cnt');
  if(!q||!cnt) return;
  var state={risk:'',stage:'',grade:''};
  var cards=[].slice.call(document.querySelectorAll('.card[data-hk]'));
  var groups=[].slice.call(document.querySelectorAll('section.grp'));
  function low(s){return (s||'').toLowerCase();}
  function apply(){
    var kw=low(q.value.trim()), n=0;
    cards.forEach(function(c){
      var ok=(!kw||low(c.getAttribute('data-q')).indexOf(kw)>=0)
        &&(!state.risk||c.getAttribute('data-risk')===state.risk)
        &&(!state.stage||c.getAttribute('data-stage')===state.stage)
        &&(!state.grade||c.getAttribute('data-grade')===state.grade);
      c.hidden=!ok;
      if(ok) n++;
    });
    groups.forEach(function(g){
      var vis=g.querySelectorAll('.card[data-hk]:not([hidden])').length;
      g.hidden=!vis;
      var s=g.querySelector('.cnt');
      if(s) s.textContent='（'+vis+' 条）';
    });
    cnt.textContent='当前显示 '+n+' / '+cards.length+' 条';
  }
  [].slice.call(document.querySelectorAll('.fbtn')).forEach(function(b){
    b.addEventListener('click',function(){
      var f=b.getAttribute('data-f');
      state[f]=b.getAttribute('data-v');
      [].slice.call(document.querySelectorAll('.fbtn[data-f="'+f+'"]')).forEach(function(x){
        x.setAttribute('aria-pressed', x===b?'true':'false');
      });
      apply();
    });
  });
  q.addEventListener('input',apply);
  apply();
})();
</script>
"""


def md2html(text: str) -> str:
    return markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"], output_format="html5"
    )


def page(title: str, body: str, desc: str = "", canonical: str = "") -> str:
    d = html.escape(desc or f"{BOOK_TITLE} · {title}")
    can = f'\n<link rel="canonical" href="{html.escape(canonical)}">' if canonical else ""
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{d}">
{can}
<style>{CSS}</style>
</head>
<body>
{body}
<footer>
<p>{html.escape(BOOK_TITLE)} · 免费 · 可查证 · 可转发</p>
<p>{VERSION_LINE}　·　{CONTACT}</p>
<p>每条正文末尾都附<b>官方原文链接</b>，可自行核对。核实记录公开在仓库
<a href="https://github.com/kk2688qq/dong-hk-guide/tree/main/docs/核实记录">docs/核实记录/</a>。</p>
<p>本指南只写查得到官方原文的内容，<b>不构成法律、移民或教育建议</b>；个案请向学校、入境处或专业人士确认。</p>
<p>仓库：<a href="https://github.com/kk2688qq/dong-hk-guide">github.com/kk2688qq/dong-hk-guide</a>
· AI 可读入口：<a href="llms.txt">llms.txt</a> · <a href="llms-full.txt">llms-full.txt</a></p>
</footer>
</body>
</html>
"""


def badges(e: dict) -> str:
    out = []
    if e["risk"]:
        out.append(f'<span class="badge r-{html.escape(e["risk"])}">风险 {html.escape(e["risk"])}</span>')
    if e["stage"]:
        out.append(f'<span class="badge">{html.escape(e["stage"])}</span>')
    if e["anxiety"]:
        out.append(f'<span class="badge">{html.escape(e["anxiety"])}</span>')
    if e["grade"]:
        out.append(f'<span class="badge">证据 {html.escape(e["grade"])}</span>')
    return "".join(out)


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "site"))
    args = ap.parse_args()
    out = args.out
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    os.makedirs(os.path.join(out, "md"))

    catalog = load_catalog()
    entries = []
    for name in sorted(os.listdir(BOOK)):
        if not (name.endswith(".md") and name[:3].isdigit()):
            continue
        e = parse_entry(name, read(os.path.join(BOOK, name)))
        e["track"] = catalog.get(e["hk"], {}).get("track", "")
        e["group"] = group_of(e["track"])
        entries.append(e)

    # 原始 Markdown 一并发布（AI 与读者都能直接取纯文本）
    for e in entries:
        shutil.copyfile(os.path.join(BOOK, e["file"]), os.path.join(out, "md", e["file"]))

    # 单文件全书（可选）
    book_html = os.environ.get("SITE_BOOK_HTML") or os.path.join(ROOT, "dist", "HKStudyGuide.html")
    if os.path.isfile(book_html):
        shutil.copyfile(book_html, os.path.join(out, "book.html"))

    # 前置章节（开篇 / 术语表 / 证据分级 / 使用方法 / 免责声明）
    fronts = []
    if os.path.isdir(META):
        for name in sorted(f for f in os.listdir(META) if f.startswith("front-") and f.endswith(".md")):
            text = read(os.path.join(META, name))
            h1 = re.search(r"^#\s+(.+)$", text.split("\n", 1)[0])
            label = h1.group(1).strip() if h1 else name
            stem = os.path.splitext(name)[0]
            fronts.append({"name": name, "stem": stem, "label": label, "text": text})
            body = (
                f'<p class="top"><a href="index.html">← 目录</a></p>\n'
                f"{md2html(text)}"
            )
            with open(os.path.join(out, f"{stem}.html"), "w", encoding="utf-8") as fh:
                fh.write(page(f"{label} · {BOOK_TITLE}", body, canonical=f"{BASE_URL}/{stem}.html"))

    # 逐条页面
    for e in entries:
        body_md = md2html(e["text"])
        ver = ""
        rec = os.path.join(DOCS, "核实记录", f"{e['num']}-")
        recdir = os.path.join(DOCS, "核实记录")
        if os.path.isdir(recdir):
            hit = [f for f in os.listdir(recdir) if f.startswith(e["num"] + "-")]
            if hit:
                ver = (
                    ' · 核实记录：<a href="https://github.com/kk2688qq/dong-hk-guide/blob/main/'
                    f'docs/核实记录/{hit[0]}">仓库内公开</a>'
                )
        body = (
            f'<p class="top"><a href="index.html">← 目录</a>'
            f' · <a href="md/{html.escape(e["file"])}">本文 Markdown</a>{ver}</p>\n'
            f"{body_md}"
        )
        with open(os.path.join(out, f"entry-{e['hk']}.html"), "w", encoding="utf-8") as fh:
            fh.write(
                page(
                    f"{e['hk']} {e['title']} · {BOOK_TITLE}",
                    body,
                    desc=e["lede"] or e["title"],
                    canonical=f"{BASE_URL}/entry-{e['hk']}.html",
                )
            )

    # 目录页
    parts = [
        f"<h1>{html.escape(BOOK_TITLE)}</h1>",
        '<p class="lede">一份免费、可查证、随手可转发的中国香港升学与身份决策指南。'
        "每条统一回答四个问题：花掉什么、换回什么、漏掉会怎样、官方依据是什么。"
        "<b>只写查得到官方原文的内容。</b></p>",
        '<p class="lede">面向中国内地家庭：中学择校插班 / 高考生申请港校本科 / 本科申硕 / 身份规划。'
        "<b>范围仅中国香港</b>，不含其他地区。</p>",
    ]
    if fronts:
        parts.append('<div class="intro"><b>先读这几页</b><nav class="toc">')
        for f in fronts:
            parts.append(f'<a href="{f["stem"]}.html">· {html.escape(f["label"])}</a>')
        parts.append("</nav></div>")

    dl = (
        '<div class="intro"><b>下载与订阅</b><br>'
        "单文件下载（链接永久指向最新版）："
        '<a href="https://github.com/kk2688qq/dong-hk-guide/releases/download/book-latest/HKStudyGuide.html">HTML</a> · '
        '<a href="https://github.com/kk2688qq/dong-hk-guide/releases/download/book-latest/HKStudyGuide.pdf">PDF</a> · '
        '<a href="https://github.com/kk2688qq/dong-hk-guide/releases/download/book-latest/HKStudyGuide.epub">EPUB</a>'
    )
    if os.path.isfile(os.path.join(out, "book.html")):
        dl += ' · <a href="book.html">本站在线全书</a>'
    dl += (
        '<br>给 AI 用的：<a href="llms.txt">llms.txt</a> · <a href="llms-full.txt">llms-full.txt</a> · '
        '<a href="sitemap.xml">sitemap.xml</a></div>'
    )
    parts.append(dl)

    # 检索筛选（纯前端）：筛选项的取值全部来自正文解析，不新增事实
    def fbtn(field: str, value: str, label: str, pressed: bool = False) -> str:
        pr = "true" if pressed else "false"
        return (
            f'<button class="fbtn" data-f="{field}" data-v="{html.escape(value)}" '
            f'aria-pressed="{pr}">{html.escape(label)}</button>'
        )

    parts.append('<div class="filters">')
    parts.append(
        '<input type="search" id="q" autocomplete="off" '
        'placeholder="搜关键词：高才通 / 留位费 / 插班 / 学费 / 受养人 …（按风险与阶段筛在下面）">'
    )
    for field, label, values in (
        ("risk", "风险", ("高", "中", "低")),
        ("stage", "阶段", ("要不要去", "怎么申请", "怎么选", "怎么落地")),
        ("grade", "证据", ("A", "B", "C")),
    ):
        parts.append(f'<div class="frow"><b>{label}</b>{fbtn(field, "", "全部", True)}')
        for v in values:
            parts.append(fbtn(field, v, v))
        parts.append("</div>")
    parts.append('<div class="fcount" id="cnt"></div>')
    parts.append("</div>")

    for gi, (gname, gdesc) in enumerate(GROUPS, 1):
        bucket = [e for e in entries if e["group"] == gname]
        if not bucket:
            continue
        parts.append(
            f'<section class="grp" id="grp-{gi}" data-group="{html.escape(gname)}">'
        )
        parts.append(
            f"<h2>第 {gi} 章 · {html.escape(gname)}"
            f'<span class="lede cnt">（{len(bucket)} 条）</span></h2>'
        )
        parts.append(f'<div class="gdesc">{html.escape(gdesc)}</div>')
        for e in bucket:
            who = f'<div class="lede">{html.escape(e["who"])}</div>' if e["who"] else ""
            lede = f'<div class="lede">{html.escape(e["lede"])}</div>' if e["lede"] else ""
            q = re.sub(r"\s+", " ", f'{e["hk"]} {e["title"]} {e["lede"]} {e["who"]}').strip()
            parts.append(
                f'<div class="card" data-hk="{e["hk"]}"'
                f' data-risk="{html.escape(e["risk"])}"'
                f' data-stage="{html.escape(e["stage"])}"'
                f' data-grade="{html.escape(e["grade"])}"'
                f' data-anx="{html.escape(e["anxiety"])}"'
                f' data-q="{html.escape(q, quote=True)}">'
                f'<h3><a href="entry-{e["hk"]}.html">'
                f'{e["hk"]} {html.escape(e["title"])}</a></h3>'
                f'<div class="badges">{badges(e)}</div>{lede}{who}</div>'
            )
        parts.append("</section>")
    # 未分组兜底
    placed = {g for g, _ in GROUPS}
    rest = [e for e in entries if e["group"] not in placed]
    if rest:
        parts.append('<section class="grp" data-group="其他">')
        parts.append("<h2>其他</h2>")
        for e in rest:
            parts.append(
                f'<div class="card" data-hk="{e["hk"]}"><h3><a href="entry-{e["hk"]}.html">'
                f'{e["hk"]} {html.escape(e["title"])}</a></h3></div>'
            )
        parts.append("</section>")

    parts.append(FILTER_JS)

    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(
            page(
                BOOK_TITLE,
                "\n".join(parts),
                desc="免费、可查证、随手可转发的中国香港升学与身份决策指南。只写查得到官方原文的内容。",
                canonical=f"{BASE_URL}/",
            )
        )

    # 站点根：AI 可读层
    for f in ("llms.txt", "robots.txt"):
        src = os.path.join(ROOT, f)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(out, f))

    # llms-full.txt：全文合并（AI 一次取完）
    full = [f"# {BOOK_TITLE}", "", f"> 站点：{BASE_URL}/ ｜ 共 {len(entries)} 条", ""]
    for f in fronts:
        full += ["", "---", "", f["text"]]
    for e in entries:
        full += ["", "---", "", e["text"]]
    with open(os.path.join(out, "llms-full.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(full).rstrip() + "\n")

    # robots.txt 追加 sitemap（若尚未声明）
    rp = os.path.join(out, "robots.txt")
    if os.path.isfile(rp):
        t = read(rp)
        if "Sitemap:" not in t:
            with open(rp, "a", encoding="utf-8") as fh:
                fh.write(f"\nSitemap: {BASE_URL}/sitemap.xml\n")

    # sitemap.xml
    urls = [f"{BASE_URL}/"]
    urls += [f"{BASE_URL}/{f['stem']}.html" for f in fronts]
    urls += [f"{BASE_URL}/entry-{e['hk']}.html" for e in entries]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"  <url><loc>{html.escape(u)}</loc></url>")
    sm.append("</urlset>")
    with open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sm) + "\n")

    print(f"站点已生成：{out}")
    print(f"  条目 {len(entries)} 条 ｜ 前置章节 {len(fronts)} 页 ｜ sitemap {len(urls)} 个 URL")
    print(f"  index.html / entry-HK-*.html / md/*.md / llms.txt / llms-full.txt / robots.txt / sitemap.xml")
    if os.path.isfile(os.path.join(out, "book.html")):
        print("  book.html（单文件全书，来自 dist/HKStudyGuide.html）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
