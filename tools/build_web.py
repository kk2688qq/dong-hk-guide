# -*- coding: utf-8 -*-
"""
《董老师香港留学指南》多页站点生成器
====================================
输入：书稿目录下的 香港留学指南.md（build.py 装配产物，49 条）
输出：一个多页静态站点（左侧菜单 + 右侧内容），每个条目一个独立页面，
      面向搜索引擎与 AI 爬虫做收录（SEO 头 / JSON-LD / sitemap / robots）。

用法：
    python build_web.py [--out 输出目录] [--base 站点根URL]
默认输出到 ./_site/（与脚本同目录）。
"""
import os
import re
import io
import html
import json
import shutil
import argparse
import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MD = os.path.join(os.path.dirname(HERE), "香港留学指南-书稿", "香港留学指南.md")

# 站点根 URL（canonical / sitemap 用）。CI 里传 SITE_BASE_URL，与仓库 build_site.py 同一变量名。
BASE = (os.environ.get("SITE_BASE_URL") or "https://kk2688qq.github.io/dong-hk-guide").rstrip("/") + "/"
SITE_TITLE = "董老师香港留学指南"
SITE_DESC = ("讲香港读书这件事：中学插班、高考生申大学、本科申硕士、"
             "高才通/优才/受养人/IANG/永居身份规划、费用预算、防骗打假。"
             "49 条，每条写明花掉什么、换回什么、漏掉会怎样、官方依据是什么，"
             "来源只引香港入境处、教育局、各校官网和法例原文。")
LANG = "zh-Hans"
# 版本与更新时间：**从定稿正文解析**（单一来源，勿在此硬编码第二份）
VERSION = "v1.0"
LASTMOD = "2026-10-07"
RE_SRC_VERSION = re.compile(r"\*\*版本\*\*[：:]\s*([vV0-9.]+)")
RE_SRC_LASTMOD = re.compile(r"\*\*最后更新\*\*[：:]\s*(\d{4}-\d{2}-\d{2})")

# ── 字段定义 ────────────────────────────────────────────────────
FIELD_CLASS = {
    "说人话": "f-lede",
    "要花什么": "f-cost",
    "换回什么": "f-gain",
    "红线提醒": "f-red",
    "常见误传": "f-myth",
    "适用人群 + 阶段": "f-fit",
    "解决什么焦虑 + 风险等级 + 决策阶段": "f-qa",
    "关键节点与时效": "f-time",
    "证据等级 + 官方依据": "f-ev",
    "本条最后更新": "f-upd",
}
RISK_COLOR = {"高": "hi", "中": "mid", "低": "low"}

PAGEBREAK_RE = re.compile(r'^\s*<div style="page-break-after: always;"></div>\s*$')
RE_H1 = re.compile(r"^# (.+)$")
RE_PART = re.compile(r"^# (.+)$")
RE_SEC = re.compile(r"^## (.+)$")
RE_CHAP = re.compile(r"^## 第 (\d) 章 · (.+)$")
RE_ENTRY = re.compile(r"^### (HK-\d{3}) (.+)$")
RE_FIELD = re.compile(r"^#### (.+)$")
RE_META = re.compile(
    r"^>\s*`风险 = (.+?)`.*?`阶段 = (.+?)`.*?`焦虑 = (.+?)`")
RE_REF = re.compile(r"HK-(\d{3})(?!\d)")
RE_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


# ── 解析 ────────────────────────────────────────────────────────
def parse(md_path):
    """把主文件解析成页面树。"""
    with io.open(md_path, encoding="utf-8") as f:
        lines = f.read().replace("\r\n", "\n").split("\n")

    doc = {"intro": [], "parts": []}          # parts: [{title, secs:[{title,lines}]}]
    chapters = []                              # [{num,title,blurb,entries:[...]}]
    cur_part = None
    cur_sec = None
    cur_chap = None
    cur_entry = None
    started_part = False

    def push_part(title):
        nonlocal cur_part, cur_sec, cur_chap, cur_entry, started_part
        cur_part = {"title": title.strip(), "secs": []}
        doc["parts"].append(cur_part)
        cur_sec = None
        cur_chap = None
        cur_entry = None
        started_part = True

    for raw in lines:
        if PAGEBREAK_RE.match(raw):
            continue
        ln = raw.rstrip()

        m = RE_PART.match(ln)
        if m and not ln.startswith("##"):
            push_part(m.group(1))
            continue

        m = RE_CHAP.match(ln)
        if m:
            cur_chap = {"num": m.group(1), "title": m.group(2).strip(),
                        "blurb": "", "entries": []}
            chapters.append(cur_chap)
            cur_entry = None
            continue

        m = RE_ENTRY.match(ln)
        if m:
            if cur_chap is None:
                raise SystemExit("!! 条目出现在章节之外：%s" % ln)
            cur_entry = {"id": m.group(1), "title": m.group(2).strip(),
                         "meta": None, "fields": []}
            cur_chap["entries"].append(cur_entry)
            continue

        if cur_entry is not None:
            m = RE_META.match(ln)
            if m and cur_entry["meta"] is None:
                cur_entry["meta"] = (m.group(1).strip(), m.group(2).strip(),
                                     m.group(3).strip())
                continue
            m = RE_FIELD.match(ln)
            if m:
                cur_entry["fields"].append({"name": m.group(1).strip(), "lines": []})
                continue
            if cur_entry["fields"]:
                cur_entry["fields"][-1]["lines"].append(raw)
            # meta 之前/之后的游离行忽略（通常没有）
            continue

        if cur_chap is not None and cur_chap["entries"] == [] and not cur_chap["blurb"]:
            m = re.match(r"^>\s*(.+)$", ln)
            if m:
                cur_chap["blurb"] = re.sub(r"（本章 \d+ 条）$", "", m.group(1)).strip()
                continue

        if cur_part is not None:
            m = RE_SEC.match(ln)
            if m:
                cur_sec = {"title": m.group(1).strip(), "lines": []}
                cur_part["secs"].append(cur_sec)
                continue
            if cur_sec is not None:
                cur_sec["lines"].append(raw)
        else:
            doc["intro"].append(raw)

    return doc, chapters


# ── Markdown → HTML ────────────────────────────────────────────
def md2html(text):
    h = autolink(markdown.markdown(fix_link_lines(fix_urls(text)), extensions=["tables"]))
    # 表格包横向滚动壳：窄屏不撑破版面；列宽交还浏览器 auto 布局
    h = h.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    return ext_links(h)


# ── 链接处理 ───────────────────────────────────────────────────
# 书稿里有三类 URL 写法：<url> 角括号（markdown 原生认）、[文字](url)（书稿未用）、
# 以及大量裸 URL（markdown 不认，渲染成纯文本）——用户要求全文链接可点。

# 2026-10-08 全文链接核查发现的失效链接（已核实官方新址，逐个 WebFetch 验证过）。
# 书稿源修订后可移除；修订建议同步报协调人 WB4。
URL_FIXES = {
    "https://www.gov.hk/tc/residents/immigration/nonpermanent/applyextensionstay/studies.htm":
        "https://www.gov.hk/tc/residents/immigration/nonpermanent/applyextensionstay/students.htm",
    "https://www.immd.gov.hk/hkt/services/visas/dependant.html":
        "https://www.immd.gov.hk/hkt/services/visas/residence_as_dependant.html",
}

def fix_urls(text):
    for old, new in URL_FIXES.items():
        text = text.replace(old, new)
    return text
RE_BARE_URL = re.compile(r'https?://[^\s<>"\'「」『』”）”），。；、！？*]+')

def _url_repl(m):
    u = m.group(0)
    trail = ""
    while u and u[-1] in ".,;:!?" and u[-3:] != "...":
        trail = u[-1] + trail
        u = u[:-1]
    return '<a href="%s" rel="noopener">%s</a>%s' % (u, u, trail)

MD_URL_FROM_HTML = re.compile(r'https?://[^\s<>"\'「」『』”）”），。；、！？*]+')

TAG_SPLIT = re.compile(r'(<[^>]+>)')

def autolink(html_text):
    """把标签外的裸 URL 转成 <a>；跳过 <a> 内部（防嵌套）与 <pre>/<code>（保留代码原样）。"""
    out, in_code, in_a = [], False, False
    for seg in TAG_SPLIT.split(html_text):
        if seg.startswith("<"):
            low = seg.lower()
            if low.startswith("<pre") or low.startswith("<cod"):
                in_code = True
            elif low.startswith("</pre") or low.startswith("</cod"):
                in_code = False
            if low.startswith("<a ") or low == "<a>":
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            out.append(seg)
        elif in_code or in_a:
            out.append(seg)
        else:
            out.append(RE_BARE_URL.sub(_url_repl, seg))
    return "".join(out)

def fix_link_lines(md_text):
    """「在线版：URL ｜ GitHub：URL」挤在一行的，拆成两个独立段落（各自成行、各成链接）；
    行是 *斜体* 包裹时，结尾的孤立 * 一并清掉。"""
    return re.sub(
        r'在线版：(https?://[^\s　｜|*]+)[　\s]*[｜|][　\s]*GitHub：(https?://[^\s　｜|*]+)\*?',
        r'在线版：\1\n\nGitHub：\2',
        md_text)


def link_refs(html_text, ids):
    """把正文里的 HK-XXX 交叉引用变成站内链接（SEO 内链）。"""
    def rep(m):
        hid = "HK-" + m.group(1)
        if hid in ids:
            return '<a href="%s.html">%s</a>' % (hid.lower(), hid)
        return hid
    # 只替换文本中的大写 HK-XXX（我们生成的 href 都是小写，不会误伤）
    return RE_REF.sub(rep, html_text)


def clean_lines(lines):
    t = "\n".join(lines).strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


RE_A_ABS = re.compile(r'<a href="(https?://[^"]*)"([^>]*)>')

def ext_links(html_text):
    """站外链接（http/https 绝对地址）一律新窗口打开；站内相对链接不动。
    2026-10-08 董老师定：点击站外链接要新开窗口。"""
    def rep(m):
        attrs = m.group(2)
        if "target=" not in attrs:
            attrs += ' target="_blank"'
        if "noopener" not in attrs:
            attrs += ' rel="noopener"'
        return '<a href="%s"%s>' % (m.group(1), attrs)
    return RE_A_ABS.sub(rep, html_text)


def first_paragraph_text(md_text, limit=120):
    t = re.sub(r"\*\*([^*]*)\*\*", r"\1", md_text)
    t = re.sub(r"[#>`\[\]]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    for sep in ["。", "！？"]:
        pass
    # 取到第二个句号为止（两句话信息量更足），超长截断
    m = re.match(r"^(.*?[。！？].*?[。！？]?)", t)
    t = m.group(1) if m else t
    if len(t) > limit:
        t = t[:limit - 1].rstrip("，、；：") + "…"
    return t


# ── 侧边栏 ─────────────────────────────────────────────────────
def sidebar_html(active, chapters, pages_meta):
    """active: 当前页 slug（'index' / 'part-1' / 'hk-009'）"""
    def a(slug, label, cls=""):
        c = (" %s" % cls) if cls else ""
        cur = ' aria-current="page"' if slug == active else ""
        return '<a class="ni%s" href="%s.html"%s>%s</a>' % (c, slug, cur, label)

    out = []
    out.append('<a class="brand" href="index.html">')
    out.append('<span class="brand-t">董老师香港留学指南</span>')
    out.append('<span class="brand-s">%s · 49 条 · 可核回官方原文</span>' % VERSION)
    out.append("</a>")
    out.append('<input id="navq" type="search" placeholder="筛选条目…" aria-label="筛选侧栏条目">')
    out.append('<nav class="nav">')
    out.append('<p class="ng">开始</p>')
    out.append(a("index", "导读 · 这本书怎么用"))
    for p in pages_meta["parts"]:
        out.append(a(p["slug"], p["nav"]))
    for ch in chapters:
        out.append('<details class="ngroup" open data-ch="%s">' % ch["num"])
        out.append('<summary>第 %s 章 · %s<span class="tw" aria-hidden="true"></span></summary>'
                   % (ch["num"], html.escape(ch["title"])))
        for e in ch["entries"]:
            slug = e["id"].lower()
            cls = "e"
            risk = e["meta"][0] if e["meta"] else ""
            if risk in RISK_COLOR:
                cls += " r-" + RISK_COLOR[risk]
            out.append(a(slug, html.escape(e["title"]), cls))
        out.append("</details>")
    out.append("</nav>")
    out.append('<p class="foot">CC BY-NC-SA 4.0 · 每条可核回官方原文<br>'
               '联系董老师：微信 jack787300 / dxw22465</p>')
    return "\n".join(out)


# ── 页面骨架 ───────────────────────────────────────────────────
def page_shell(title, desc, slug, canonical_path, sidebar, main_html,
               jsonld, base=BASE, theme_css="", main_attr=""):
    css = CSS + theme_css
    main_html = ext_links(main_html)  # 站外链接统一新窗口（含页脚在线版/GitHub 等）
    js = JS
    jsonld_s = json.dumps(jsonld, ensure_ascii=False) if jsonld else ""
    ld = ('<script type="application/ld+json">%s</script>' % jsonld_s) if jsonld else ""
    return f"""<!DOCTYPE html>
<html lang="{LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{base}{canonical_path}">
<meta name="theme-color" content="#F6F7F9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#121417" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{SITE_TITLE}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{base}{canonical_path}">
<meta property="og:locale" content="zh_CN">
<link rel="sitemap" type="application/xml" href="sitemap.xml">
{ld}
<style>
{css}
</style>
</head>
<body>
<a class="skip" href="#main">跳到主要内容</a>
<header class="topbar">
  <button id="menubtn" aria-label="打开目录" aria-expanded="false" aria-controls="sidebar">☰ 目录</button>
  <a class="topbar-t" href="index.html">董老师香港留学指南</a>
  <button id="themebtn" aria-label="切换深浅色" aria-pressed="false">◐</button>
</header>
<div class="backdrop" id="backdrop" hidden></div>
<aside class="sidebar" id="sidebar">
{sidebar}
</aside>
<main class="main" id="main"{main_attr}>
{main_html}
</main>
<script>
{js}
</script>
</body>
</html>"""


def breadcrumb(items):
    """items: [(label, href|None)] → HTML + JSON-LD dict"""
    lis = []
    for label, href in items:
        if href:
            lis.append('<a href="%s">%s</a>' % (href, html.escape(label)))
        else:
            lis.append("<span>%s</span>" % html.escape(label))
    nav = ('<nav class="crumbs" aria-label="所在位置">%s</nav>'
           % (' <span class="sep">›</span> '.join(lis)))
    ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "name": label,
             **({"item": BASE + href} if href else {})}
            for i, (label, href) in enumerate(items)
        ],
    }
    return nav, ld


def chips(meta):
    if not meta:
        return ""
    risk, stage, anxiety = meta
    rc = RISK_COLOR.get(risk, "plain")
    return ('<div class="chips">'
            '<span class="chip c-%s">风险 %s</span>'
            '<span class="chip">阶段 %s</span>'
            '<span class="chip">焦虑 %s</span>'
            "</div>") % (rc, html.escape(risk), html.escape(stage), html.escape(anxiety))


def render_fields(entry, ids):
    out = []
    for f in entry["fields"]:
        cls = FIELD_CLASS.get(f["name"], "f-other")
        body = md2html(clean_lines(f["lines"]))
        if cls not in ("f-ev", "f-upd"):
            body = link_refs(body, ids)
        out.append('<section class="field %s">' % cls)
        out.append("<h2>%s</h2>" % html.escape(f["name"]))
        out.append('<div class="fb">%s</div>' % body)
        out.append("</section>")
    return "\n".join(out)


def entry_date(entry):
    for f in entry["fields"]:
        if f["name"] == "本条最后更新":
            m = RE_DATE.search("\n".join(f["lines"]))
            if m:
                return m.group(1)
    return LASTMOD


def entry_desc(entry):
    for f in entry["fields"]:
        if f["name"] == "说人话":
            return first_paragraph_text(clean_lines(f["lines"]))
    return SITE_DESC[:110]


# ── CSS / JS ───────────────────────────────────────────────────
CSS = r"""
:root{
  --bg:#F7F8FA; --surface:#FFFFFF; --surface-2:#EEF2F7;
  --ink:#0E1319; --ink2:#39424E; --ink3:#5B6470;
  --brand:#0A56A8; --brand-ink:#0A56A8; --brandsoft:#E8F1FB;
  --hi:#B3261E; --hibg:#FCEBE9;
  --mid:#8A5A00; --midbg:#FCF2DF;
  --low:#23663F; --lowbg:#E7F3EC;
  --line:#E3E7EC; --line-ui:#98A2AE;
  --code:#F1F3F6;
  --side-w:288px;
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
}
html.dark{
  --bg:#121417; --surface:#1A1D21; --surface-2:#22262B;
  --ink:#ECEFF2; --ink2:#BAC1C9; --ink3:#8E97A1;
  --brand:#7FB3EC; --brand-ink:#7FB3EC; --brandsoft:#17293C;
  --hi:#F2938A; --hibg:#3A2321;
  --mid:#E3B268; --midbg:#33291A;
  --low:#85CBA4; --lowbg:#1B2E24;
  --line:#2B3036; --line-ui:#565F6A;
  --code:#22262B;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.75 var(--font-sans);
}
a{color:var(--brand-ink); text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--brand); outline-offset:2px; border-radius:4px}
.skip{position:absolute; left:-9999px}
.skip:focus{left:12px; top:12px; z-index:60; background:var(--surface); padding:8px 14px; border-radius:8px}

/* ── 侧栏 ─────────────────────────────── */
.sidebar{
  position:fixed; inset:0 auto 0 0; width:var(--side-w); z-index:40;
  background:var(--surface); border-right:1px solid var(--line);
  display:flex; flex-direction:column; padding:14px 0 10px;
  overflow-y:auto; overscroll-behavior:contain;
}
.brand{display:block; padding:6px 18px 10px; border-bottom:1px solid var(--line); margin-bottom:10px}
.brand:hover{text-decoration:none}
.brand-t{display:block; font-size:17px; font-weight:700; color:var(--ink); line-height:1.4}
.brand-s{display:block; font-size:12px; color:var(--ink3); margin-top:2px}
#navq{
  display:block; width:auto; margin:0 14px 10px; padding:9px 12px;
  font:16px/1 var(--font-sans); color:var(--ink);
  background:var(--bg); border:1px solid var(--line-ui); border-radius:8px;
}
#navq::placeholder{color:var(--ink3)}
.nav{flex:1; padding:0 8px 8px}
.ng{
  margin:14px 10px 4px; font-size:12.5px; font-weight:600; color:var(--ink3);
  letter-spacing:.02em;
}
.ngroup{margin:8px 6px 2px}
.ngroup summary{
  list-style:none; cursor:pointer; user-select:none;
  display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding:7px 10px; border-radius:8px;
  font-size:12.5px; font-weight:700; color:var(--ink2); letter-spacing:.02em;
  line-height:1.45;
}
.ngroup summary::-webkit-details-marker{display:none}
.ngroup summary:hover{background:var(--surface-2)}
.ngroup summary .tw{flex:none; position:relative; width:10px; height:10px}
.ngroup summary .tw::before,.ngroup summary .tw::after{
  content:""; position:absolute; background:var(--ink3); border-radius:1px;
}
.ngroup summary .tw::before{left:0; top:4px; width:10px; height:2px}
.ngroup summary .tw::after{left:4px; top:0; width:2px; height:10px}
.ngroup[open] summary .tw::after{display:none}
.ngroup .ni{padding-left:18px}
.ni{
  display:flex; align-items:center; gap:8px;
  padding:7px 10px; margin:1px 0; border-radius:8px;
  font-size:14px; color:var(--ink2); line-height:1.45;
}
.ni:hover{background:var(--surface-2); text-decoration:none}
.ni[aria-current="page"]{background:var(--brandsoft); color:var(--brand-ink); font-weight:600}
.ni.e::before{content:"·"; color:var(--ink3); flex:none}
.ni.r-hi::before{color:var(--hi)}
.ni.r-mid::before{color:var(--mid)}
.ni.r-low::before{color:var(--low)}
.foot{padding:10px 18px 6px; font-size:12px; color:var(--ink3); border-top:1px solid var(--line)}

/* ── 主区 ─────────────────────────────── */
.main{margin-left:var(--side-w); padding:34px 40px 60px}
.wrap{max-width:720px; margin:0 auto}
.crumbs{font-size:13px; color:var(--ink3); margin-bottom:14px}
.crumbs a{color:var(--ink3)}
.crumbs .sep{margin:0 6px; color:var(--line-ui)}

article h1{font-size:25px; line-height:1.4; margin:0 0 14px; letter-spacing:.01em}
article h2{font-size:19px; line-height:1.45; margin:0 0 10px}
article h3{font-size:17px; margin:26px 0 8px}
article p{margin:0 0 14px; max-width:640px}
article ul,article ol{margin:0 0 14px; padding-left:1.5em; max-width:640px}
article li{margin:4px 0}
article hr{border:0; border-top:1px solid var(--line); margin:22px 0}
article code{
  font-size:.92em; background:var(--code); padding:2px 6px; border-radius:5px;
  font-family:ui-monospace,Consolas,monospace;
}
.tw{overflow-x:auto; margin:0 0 16px; -webkit-overflow-scrolling:touch}
article table{
  border-collapse:collapse; width:100%; margin:0; font-size:14.5px;
  background:var(--surface);
}
article th,article td{border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top}
/* 表格里的链接（HK-XXX 引用等）不许断行——防止「见」列被挤成 HK-/009 两行 */
article th a,article td a{white-space:nowrap}
article th{background:var(--surface-2); font-weight:600}
article blockquote{
  margin:0 0 14px; padding:10px 14px; border-left:3px solid var(--line-ui);
  color:var(--ink2); background:var(--surface); border-radius:0 8px 8px 0;
}
article img{max-width:100%}

.chips{display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px}
.chip{
  display:inline-block; padding:3px 12px; border-radius:999px;
  font-size:13px; background:var(--surface-2); color:var(--ink2);
  border:1px solid var(--line);
}
.chip.c-hi{background:var(--hibg); color:var(--hi); border-color:transparent; font-weight:600}
.chip.c-mid{background:var(--midbg); color:var(--mid); border-color:transparent; font-weight:600}
.chip.c-low{background:var(--lowbg); color:var(--low); border-color:transparent; font-weight:600}

/* 字段区块 */
.field{margin:0 0 18px}
.field>h2{font-size:15px; color:var(--ink3); font-weight:600; margin:0 0 8px; letter-spacing:.03em}
.field .fb>:last-child{margin-bottom:0}
.f-lede{background:var(--surface-2); border-radius:12px; padding:16px 20px; margin:0 0 22px}
.f-lede>h2{color:var(--brand-ink)}
.f-lede .fb p{font-size:17.5px; line-height:1.8; max-width:none}
.f-lede .fb ul{font-size:17px}
.f-red{background:var(--hibg); border-radius:12px; padding:14px 18px}
.f-red>h2{color:var(--hi)}
.f-myth{background:var(--midbg); border-radius:12px; padding:14px 18px}
.f-myth>h2{color:var(--mid)}
.f-ev,.f-upd{border-top:1px dashed var(--line); padding-top:12px}
.f-ev>h2,.f-upd>h2{font-size:13.5px}
.f-ev .fb,.f-upd .fb{font-size:13.5px; color:var(--ink3)}

/* 上/下篇与相关条目 */
.pn{display:flex; gap:12px; margin:34px 0 0; max-width:720px}
.pn a{
  flex:1; background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:10px 14px; font-size:14px; line-height:1.5;
}
.pn a:hover{text-decoration:none; border-color:var(--line-ui)}
.pn .dir{display:block; font-size:12px; color:var(--ink3)}
.pn .next{text-align:right; margin-left:auto}
.related{margin:26px 0 0; max-width:720px}
.related p{margin:0 0 8px; font-size:13.5px; color:var(--ink3); font-weight:600}
.related .rl{display:flex; flex-wrap:wrap; gap:8px}
.related .rl a{
  font-size:13px; padding:4px 12px; border-radius:999px;
  background:var(--surface); border:1px solid var(--line); color:var(--ink2);
}
.related .rl a:hover{text-decoration:none; border-color:var(--brand)}

/* 首页 hero */
.hero{background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:26px 26px 20px; margin-bottom:22px}
.hero h1{font-size:27px; margin:0 0 10px}
.hero .tagline{font-size:15px; color:var(--ink3); margin:0 0 12px}
.hero .vers{display:flex; flex-wrap:wrap; gap:8px; margin:0 0 12px}
.hero .contact{font-size:14px; color:var(--ink2); margin:0}
.sect{max-width:720px}

/* 页脚 */
.pfoot{margin:40px 0 0; padding-top:14px; border-top:1px solid var(--line);
  font-size:13px; line-height:2.1; color:var(--ink2); max-width:720px}

/* ── 顶栏（移动端） ────────────────────── */
.topbar{
  display:none; position:fixed; inset:0 0 auto 0; height:52px; z-index:50;
  background:var(--surface); border-bottom:1px solid var(--line);
  align-items:center; gap:10px; padding:0 12px;
}
.topbar-t{font-weight:700; font-size:16px; color:var(--ink); flex:1; text-align:center}
.topbar-t:hover{text-decoration:none}
#menubtn,#themebtn{
  border:1px solid var(--line-ui); background:var(--surface); color:var(--ink);
  border-radius:8px; padding:8px 12px; font:14px/1 var(--font-sans); min-height:40px;
}
.backdrop{position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:39}

/* ── 响应式（移动优先断点：min-width 递进） ── */
@media (max-width:900px){
  .topbar{display:flex}
  .sidebar{transform:translateX(-102%); transition:transform .25s ease; box-shadow:0 0 24px rgba(0,0,0,.18); width:min(320px,86vw)}
  .sidebar.open{transform:translateX(0)}
  body.navlock{overflow:hidden}
  .main{margin-left:0; padding:68px 16px 50px}
  article h1{font-size:22px}
  .f-lede .fb p{font-size:17px}
  .chgrid{grid-template-columns:1fr}
}
@media (min-width:901px) and (max-width:1100px){
  :root{--side-w:252px}
  .main{padding:30px 26px 50px}
}
@media (prefers-reduced-motion:reduce){
  .sidebar{transition:none}
}
"""

# ── 配色 / 设计元素主题 ────────────────────────────────────────
# 每套是一段追加在基础 CSS 之后的覆盖样式。
# 关键：侧栏与内容区必须有「结构级」区分（深色块 / 粗边线 / 浮起白板），
# 只靠浅色差不成立——基础版侧栏 #FFF 对页底 #F7F8FA 只有 1.04:1，肉眼无感。
THEMES = {}

THEMES["A"] = {
    "name": "A · 深色导航",
    "note": "侧栏深墨蓝实色块，与内容区 15.2:1；内容是一张浮起白卡",
    "css": r"""
/* ============ 主题 A · 深色导航 ============ */
:root{
  --bg:#F4F6F9; --surface:#FFFFFF; --surface-2:#F1F4F8;
  --ink:#0D1117; --ink2:#39424E; --ink3:#5A6470;
  --brand:#0B57B5; --brand-ink:#0B57B5; --brandsoft:#E8F1FB;
  --hi:#B3261E; --hibg:#FCEBE9; --mid:#8A5A00; --midbg:#FBF0DC;
  --low:#1F6640; --lowbg:#E6F2EA; --line:#E1E6EC; --line-ui:#98A2AE; --code:#F1F3F6;
  --sb-bg:#16202B; --sb-ink:#FFFFFF; --sb-ink2:#C6D2DF; --sb-ink3:#93A5B7;
  --sb-line:#2B3948; --sb-hover:rgba(255,255,255,.08);
  --sb-on-bg:#0B57B5; --sb-on-ink:#FFFFFF; --sb-accent:#6FB6FF;
}
html.dark{
  --bg:#0E1116; --surface:#171B21; --surface-2:#20252C;
  --ink:#ECEFF2; --ink2:#BAC1C9; --ink3:#8E97A1;
  --brand:#7FB3EC; --brand-ink:#7FB3EC; --brandsoft:#17293C;
  --hi:#F2938A; --hibg:#3A2321; --mid:#E3B268; --midbg:#33291A;
  --low:#85CBA4; --lowbg:#1B2E24; --line:#262C34; --line-ui:#565F6A; --code:#20252C;
  --sb-bg:#0B131B; --sb-ink:#F2F6FA; --sb-ink2:#B7C4D3; --sb-ink3:#8194A6;
  --sb-line:#1E2A36; --sb-hover:rgba(255,255,255,.07);
  --sb-on-bg:#13538F; --sb-on-ink:#FFFFFF; --sb-accent:#6FB6FF;
}
.sidebar{background:var(--sb-bg); border-right:0}
.brand{border-bottom:1px solid var(--sb-line)}
.brand-t{color:var(--sb-ink)}
.brand-s{color:var(--sb-ink3)}
#navq{background:rgba(255,255,255,.08); border-color:var(--sb-line); color:var(--sb-ink)}
#navq::placeholder{color:var(--sb-ink3)}
.ng{color:var(--sb-ink3)}
.ngroup summary{color:var(--sb-ink2)}
.ngroup summary:hover{background:var(--sb-hover)}
.ngroup summary .tw::before,.ngroup summary .tw::after{background:var(--sb-ink3)}
.ni{color:var(--sb-ink2); position:relative}
.ni:hover{background:var(--sb-hover); color:var(--sb-ink)}
.ni[aria-current="page"]{background:var(--sb-on-bg); color:var(--sb-on-ink); font-weight:600}
.ni[aria-current="page"]::after{
  content:""; position:absolute; left:-5px; top:6px; bottom:6px; width:3px;
  border-radius:2px; background:var(--sb-accent);
}
.ni.e::before{color:var(--sb-ink3)}
.ni[aria-current="page"]::before{color:var(--sb-on-ink)}
.foot{color:var(--sb-ink3); border-top:1px solid var(--sb-line)}
.wrap{
  background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:32px 36px 38px;
  box-shadow:0 1px 2px rgba(13,17,23,.05), 0 10px 30px -22px rgba(13,17,23,.28);
}
html.dark .wrap{box-shadow:none}
.hero{background:var(--surface-2); border:0; border-radius:10px}
.hero h1{border-left:5px solid var(--brand); padding-left:14px}
.f-lede{background:var(--brandsoft); box-shadow:inset 4px 0 0 var(--brand)}
@media (min-width:901px){
  .main{padding:26px 34px 64px}
  .wrap{max-width:760px}
}
""",
}

THEMES["B"] = {
    "name": "B · 暖纸手册",
    "note": "米黄侧栏 + 白纸内容，直角小圆角、细线框，像摊开的手册",
    "css": r"""
/* ============ 主题 B · 暖纸手册 ============ */
:root{
  --bg:#FBF7F0; --surface:#FFFFFF; --surface-2:#F7F2E8;
  --ink:#1A1614; --ink2:#4A423A; --ink3:#6B6157;
  --brand:#9A4A0F; --brand-ink:#9A4A0F; --brandsoft:#F7E9DA;
  --hi:#A32A1B; --hibg:#F9E7E3; --mid:#7A4A00; --midbg:#F6ECD8;
  --low:#1D6242; --lowbg:#E6F1EA; --line:#E7DCC6; --line-ui:#B9A583; --code:#F5EFE3;
  --sb-bg:#E9DCC4; --sb-ink:#1A1614; --sb-ink2:#463D33; --sb-ink3:#6B5B45;
  --sb-line:#CBB58F; --sb-hover:rgba(154,74,15,.10);
  --sb-on-bg:#D8C6A5; --sb-on-ink:#5A2A08; --sb-accent:#9A4A0F;
}
html.dark{
  --bg:#171310; --surface:#1F1A16; --surface-2:#282219;
  --ink:#F0E9E0; --ink2:#C4B8A8; --ink3:#9A8D7C;
  --brand:#E8A87C; --brand-ink:#E8A87C; --brandsoft:#33261B;
  --hi:#F2938A; --hibg:#3A2321; --mid:#E3B268; --midbg:#33291A;
  --low:#85CBA4; --lowbg:#1B2E24; --line:#302820; --line-ui:#5E5346; --code:#282219;
  --sb-bg:#1B1613; --sb-ink:#F0E9E0; --sb-ink2:#C4B8A8; --sb-ink3:#9A8D7C;
  --sb-line:#332A22; --sb-hover:rgba(232,168,124,.12);
  --sb-on-bg:#3A2A1C; --sb-on-ink:#F0C79E; --sb-accent:#E8A87C;
}
.sidebar{background:var(--sb-bg); border-right:1px solid var(--sb-line)}
.brand{border-bottom:1px solid var(--sb-line)}
.brand-t{color:var(--sb-ink)}
.brand-s{color:var(--sb-ink3)}
#navq{background:#FFFDF9; border:1px solid var(--sb-line); color:var(--ink)}
html.dark #navq{background:rgba(255,255,255,.07); color:var(--sb-ink)}
#navq::placeholder{color:var(--sb-ink3)}
.ng{color:var(--sb-ink3)}
.ngroup summary{color:var(--sb-ink); justify-content:flex-start; gap:8px}
.ngroup summary::before{
  content:""; width:9px; height:9px; border-radius:2px;
  background:var(--brand); flex:none;
}
.ngroup summary .tw{margin-left:auto}
.ngroup summary:hover{background:var(--sb-hover)}
.ngroup summary .tw::before,.ngroup summary .tw::after{background:var(--sb-ink3)}
.ni{color:var(--sb-ink2); border-radius:4px}
.ni:hover{background:var(--sb-hover); color:var(--sb-ink)}
.ni[aria-current="page"]{
  background:var(--sb-on-bg); color:var(--sb-on-ink); font-weight:600;
  box-shadow:inset 3px 0 0 var(--sb-accent);
}
.ni.e::before{color:var(--sb-ink3)}
.ni[aria-current="page"]::before{color:var(--sb-on-ink)}
.foot{color:var(--sb-ink3); border-top:1px solid var(--sb-line)}
.wrap{background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:30px 34px 36px}
.hero{background:var(--surface-2); border:1px dashed var(--line); border-radius:6px}
article h1{border-bottom:1px solid var(--line); padding-bottom:12px}
.f-lede{background:var(--brandsoft); box-shadow:inset 4px 0 0 var(--brand)}
article th{background:var(--surface-2)}
.f-lede,.f-red,.f-myth{border-radius:4px}
.chip{border-radius:4px}
.pn a{border-radius:4px}
.related .rl a{border-radius:4px}
@media (min-width:901px){
  .main{padding:30px 34px 60px}
  .wrap{max-width:740px}
}
""",
}

THEMES["C"] = {
    "name": "C · 靛蓝编码",
    "note": "靛灰底上浮两块白板；六章色彩编码，条目页标题带所属章色",
    "css": r"""
/* ============ 主题 C · 靛蓝编码 ============ */
:root{
  --bg:#E4E7F5; --surface:#FFFFFF; --surface-2:#F4F5FB;
  --ink:#12132A; --ink2:#3C3F5E; --ink3:#585C80;
  --brand:#4338CA; --brand-ink:#4338CA; --brandsoft:#EAE8FD;
  --hi:#BE123C; --hibg:#FCE7EE; --mid:#8A5A00; --midbg:#FBF0DC;
  --low:#0F766E; --lowbg:#E3F4F1; --line:#DDE1F1; --line-ui:#A6ADD4; --code:#F1F2FA;
  --sb-bg:#FFFFFF; --sb-ink:#12132A; --sb-ink2:#33365A; --sb-ink3:#585C80;
  --sb-line:#DDE1F1; --sb-hover:#F1F2FB;
  --sb-on-bg:#E7E5FC; --sb-on-ink:#3730A3; --sb-accent:#4338CA;
  --ch1:#1D4ED8; --ch2:#4338CA; --ch3:#6D28D9; --ch4:#0E7490; --ch5:#15803D; --ch6:#B45309;
}
html.dark{
  --bg:#0D0F1A; --surface:#171A28; --surface-2:#1F2333;
  --ink:#E9EAF4; --ink2:#B6BAD2; --ink3:#8A8FAC;
  --brand:#9C93F5; --brand-ink:#9C93F5; --brandsoft:#22244A;
  --hi:#F2938A; --hibg:#3A2321; --mid:#E3B268; --midbg:#33291A;
  --low:#85CBA4; --lowbg:#1B2E24; --line:#262B3D; --line-ui:#545B7C; --code:#1F2333;
  --sb-bg:#151827; --sb-ink:#E9EAF4; --sb-ink2:#B6BAD2; --sb-ink3:#8A8FAC;
  --sb-line:#262B3D; --sb-hover:#1F2333;
  --sb-on-bg:#2A2C5C; --sb-on-ink:#C7C2FA; --sb-accent:#9C93F5;
  --ch1:#8FA6FF; --ch2:#A79DFB; --ch3:#C0A8FA; --ch4:#6FD3E8; --ch5:#7DD9A6; --ch6:#EFB673;
}
.sidebar{background:var(--sb-bg); border-right:1px solid var(--sb-line)}
.brand{border-bottom:1px solid var(--sb-line)}
.brand-t{color:var(--sb-ink)}
.brand-s{color:var(--sb-ink3)}
#navq{background:var(--surface-2); border:1px solid var(--line-ui); color:var(--ink)}
#navq::placeholder{color:var(--sb-ink3)}
.ng{color:var(--sb-ink3)}
.ngroup{margin:10px 6px 4px}
.ngroup summary{color:var(--sb-ink); justify-content:flex-start; gap:9px}
.ngroup summary::before{
  content:""; width:4px; height:15px; border-radius:2px;
  background:var(--chc,#4338CA); flex:none;
}
.ngroup summary .tw{margin-left:auto}
.ngroup summary:hover{background:var(--sb-hover)}
.ngroup summary .tw::before,.ngroup summary .tw::after{background:var(--sb-ink3)}
.ngroup[data-ch="1"]{--chc:var(--ch1)}
.ngroup[data-ch="2"]{--chc:var(--ch2)}
.ngroup[data-ch="3"]{--chc:var(--ch3)}
.ngroup[data-ch="4"]{--chc:var(--ch4)}
.ngroup[data-ch="5"]{--chc:var(--ch5)}
.ngroup[data-ch="6"]{--chc:var(--ch6)}
.ni{color:var(--sb-ink2); border-radius:8px}
.ni:hover{background:var(--sb-hover); color:var(--sb-ink)}
.ni[aria-current="page"]{
  background:var(--sb-on-bg); color:var(--sb-on-ink); font-weight:600;
  box-shadow:inset 3px 0 0 var(--sb-accent);
}
.ni.e::before{color:var(--sb-ink3)}
.ni[aria-current="page"]::before{color:var(--sb-on-ink)}
.foot{color:var(--sb-ink3); border-top:1px solid var(--sb-line)}
.wrap{
  background:var(--surface); border-radius:16px; padding:36px 40px 42px;
  box-shadow:0 1px 2px rgba(18,19,42,.06), 0 14px 40px -26px rgba(18,19,42,.5);
}
html.dark .wrap{box-shadow:none}
.hero{border:0; background:var(--surface-2); border-radius:12px}
.wrap[data-ch] article h1{padding-left:16px; border-left:6px solid var(--chc,#4338CA)}
.wrap[data-ch="1"]{--chc:var(--ch1)}
.wrap[data-ch="2"]{--chc:var(--ch2)}
.wrap[data-ch="3"]{--chc:var(--ch3)}
.wrap[data-ch="4"]{--chc:var(--ch4)}
.wrap[data-ch="5"]{--chc:var(--ch5)}
.wrap[data-ch="6"]{--chc:var(--ch6)}
.f-lede{background:var(--brandsoft); box-shadow:inset 4px 0 0 var(--brand)}
.wrap[data-ch] .f-lede{box-shadow:inset 4px 0 0 var(--chc)}
.wrap[data-ch] .f-lede>h2{color:var(--chc)}
@media (min-width:901px){
  .main{padding:16px 20px 40px}
  .wrap{max-width:768px}
}
""",
}

THEMES["D"] = {
    "name": "D · 黑白线框",
    "note": "白底黑线、直角、章组黑底白字；红只留给红线提醒",
    "css": r"""
/* ============ 主题 D · 黑白线框 ============ */
:root{
  --bg:#F0F0F0; --surface:#FFFFFF; --surface-2:#F5F5F5;
  --ink:#111111; --ink2:#3D3D3D; --ink3:#5C5C5C;
  --brand:#111111; --brand-ink:#111111; --brandsoft:#EDEDED;
  --hi:#C42B1C; --hibg:#FBE9E7; --mid:#8A5A00; --midbg:#FBF0DC;
  --low:#2F6B4A; --lowbg:#E7F3EC; --line:#C9C9C9; --line-ui:#8A8A8A; --code:#F2F2F2;
  --sb-bg:#FFFFFF; --sb-ink:#111111; --sb-ink2:#3D3D3D; --sb-ink3:#5C5C5C;
  --sb-line:#111111; --sb-hover:#F0F0F0;
  --sb-on-bg:#111111; --sb-on-ink:#FFFFFF; --sb-accent:#C42B1C;
}
html.dark{
  --bg:#0F0F0F; --surface:#1A1A1A; --surface-2:#232323;
  --ink:#F2F2F2; --ink2:#C4C4C4; --ink3:#9A9A9A;
  --brand:#F2F2F2; --brand-ink:#F2F2F2; --brandsoft:#2A2A2A;
  --hi:#F2938A; --hibg:#3A2321; --mid:#E3B268; --midbg:#33291A;
  --low:#85CBA4; --lowbg:#1B2E24; --line:#3A3A3A; --line-ui:#6E6E6E; --code:#232323;
  --sb-bg:#141414; --sb-ink:#F2F2F2; --sb-ink2:#C4C4C4; --sb-ink3:#9A9A9A;
  --sb-line:#3A3A3A; --sb-hover:#232323;
  --sb-on-bg:#F2F2F2; --sb-on-ink:#111111; --sb-accent:#C42B1C;
}
.sidebar{background:var(--sb-bg); border-right:2px solid var(--sb-line)}
.brand{border-bottom:2px solid var(--sb-line)}
.brand-t{color:var(--sb-ink)}
.brand-s{color:var(--sb-ink3)}
#navq{background:var(--surface); border:1px solid var(--sb-line); border-radius:0; color:var(--ink)}
#navq::placeholder{color:var(--sb-ink3)}
.ng{color:var(--sb-ink3)}
.ngroup{margin:6px 6px 10px}
.ngroup summary{
  background:var(--sb-on-bg); color:var(--sb-on-ink); border-radius:0;
  padding:8px 11px; letter-spacing:.02em;
}
.ngroup summary:hover{background:var(--sb-on-bg); color:var(--sb-on-ink); opacity:.86}
.ngroup summary .tw::before,.ngroup summary .tw::after{background:var(--sb-on-ink)}
.ngroup .ni{padding-left:16px}
.ni{color:var(--sb-ink2); border-radius:0; border-left:3px solid transparent}
.ni:hover{background:var(--sb-hover); color:var(--sb-ink)}
.ni[aria-current="page"]{
  background:var(--sb-on-bg); color:var(--sb-on-ink); font-weight:700;
  border-left-color:var(--sb-accent);
}
.ni.e::before{color:var(--sb-ink3)}
.ni[aria-current="page"]::before{color:var(--sb-on-ink)}
.foot{color:var(--sb-ink3); border-top:2px solid var(--sb-line)}
.wrap{background:var(--surface); border:1px solid var(--line); border-radius:0; padding:30px 34px 38px}
.hero{background:var(--surface); border:0; border-left:6px solid var(--brand); border-radius:0; padding-left:24px}
article h1{border-bottom:3px solid var(--ink); padding-bottom:12px}
.field>h2{color:var(--ink)}
.f-lede{background:var(--brandsoft); border-left:4px solid var(--brand); border-radius:0}
.f-red{border-left:5px solid var(--hi); border-radius:0}
.f-myth{border-left:5px solid var(--mid); border-radius:0}
.chip{border-radius:2px; border-color:var(--line-ui)}
.pn a{border-radius:0}
.related .rl a{border-radius:2px}
article table{border:1px solid var(--ink)}
article th{background:var(--surface-2); border-bottom:2px solid var(--ink)}
@media (min-width:901px){
  .main{padding:26px 34px 60px}
  .wrap{max-width:740px}
}
""",
}

THEME_ORDER = ["A", "B", "C", "D"]

JS = r"""
(function(){
  var sb=document.getElementById('sidebar'),bd=document.getElementById('backdrop'),
      mb=document.getElementById('menubtn');
  function close(){sb.classList.remove('open');bd.hidden=true;document.body.classList.remove('navlock');mb.setAttribute('aria-expanded','false');}
  mb.addEventListener('click',function(){
    var open=sb.classList.toggle('open');
    bd.hidden=!open;document.body.classList.toggle('navlock',open);
    mb.setAttribute('aria-expanded',open?'true':'false');
  });
  bd.addEventListener('click',close);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
  // 侧栏筛选
  var q=document.getElementById('navq');
  if(q){q.addEventListener('input',function(){
    var v=q.value.trim().toLowerCase();
    sb.querySelectorAll('.nav .ni').forEach(function(a){
      a.style.display=(!v||a.textContent.toLowerCase().indexOf(v)>=0)?'':'none';
    });
    // 分组按可见条目决定去留（.ng 是纯标题组，.ngroup 是可折叠章组）
    sb.querySelectorAll('.nav .ng, .nav details.ngroup').forEach(function(g){
      var any=false, el=g.nextElementSibling, stop=g.tagName==='DETAILS'?'DETAILS':(g.classList.contains('ngroup')?'DETAILS':null);
      // details 组：条目在自身内部；标题组：条目跟在后面直到下一组
      if(g.tagName==='DETAILS'){
        g.querySelectorAll('.ni').forEach(function(a){if(a.style.display!=='none')any=true;});
      }else{
        while(el&&!el.classList.contains('ng')&&!(el.tagName==='DETAILS')){
          if(el.classList.contains('ni')&&el.style.display!=='none')any=true;
          el=el.nextElementSibling;
        }
      }
      g.style.display=any?'':'none';
      if(g.tagName==='DETAILS'&&v)g.open=true;
    });
  });}
  // 深浅色：跟随系统，点按钮强制反转并记忆
  var tb=document.getElementById('themebtn'),root=document.documentElement;
  try{var t=localStorage.getItem('theme');if(t)root.className=t;}catch(e){}
  function sync(){tb.setAttribute('aria-pressed',root.className==='dark'?'true':'false');}
  if(tb){tb.addEventListener('click',function(){
    var sysDark=window.matchMedia('(prefers-color-scheme: dark)').matches;
    var nowDark=root.className==='dark'||(root.className!=='light'&&sysDark);
    root.className=nowDark?'light':'dark';
    try{localStorage.setItem('theme',root.className);}catch(e){}
    sync();
  });}
  sync();
})();
"""


# ── 组装页面 ───────────────────────────────────────────────────
def pn_nav(entry, flat):
    """（2026-10-08 已停用：董老师要求去掉上一篇/下一篇）保留空实现防外部调用报错。"""
    return ""


def related_nav(entry, chapter):
    """（2026-10-08 已停用：董老师要求去掉同章其他条目）"""
    return ""


def build(md_path, out_dir, base=BASE, theme="default", ai_dir=None):
    global VERSION, LASTMOD
    theme_css = THEMES[theme]["css"] if theme in THEMES else ""
    doc, chapters = parse(md_path)
    if not base.endswith("/"):
        base += "/"
    # 版本/更新时间取自定稿正文（单一来源；取到就用，取不到保留默认值）
    raw_md = io.open(md_path, encoding="utf-8").read()
    mv, ml = RE_SRC_VERSION.search(raw_md), RE_SRC_LASTMOD.search(raw_md)
    if mv:
        VERSION = mv.group(1)
    if ml:
        LASTMOD = ml.group(1)

    # 主文件首行「# 书名」会被 parse 当成第 0 个部分——并回首页导读
    head = None
    if doc["parts"] and doc["parts"][0]["title"].startswith("董老师香港留学指南"):
        head = doc["parts"].pop(0)

    ids = set()
    for ch in chapters:
        for e in ch["entries"]:
            ids.add(e["id"])

    entry_by_id = {}
    entry_chapter = {}
    flat = []
    for ch in chapters:
        for e in ch["entries"]:
            entry_by_id[e["id"]] = e
            entry_chapter[e["id"]] = ch
            flat.append(e)

    pages_meta = {"parts": []}
    part_slugs = {0: "part-1", 1: "part-2", 3: "part-4", 4: "part-5"}
    # doc["parts"] 顺序：0=第一部分 1=第二部分 2=第三部分(正文，不单独成页) 3=第四 4=第五
    part_navs = ["使用指南 · 风险与信息源", "核心概念 · 证据与分档",
                 None, "许可与免责", "关于本书"]
    for i, p in enumerate(doc["parts"]):
        if i not in part_slugs:
            continue  # 第三部分 = 49 条条目页本身，不设阅读页
        pages_meta["parts"].append({"slug": part_slugs[i],
                                    "nav": part_navs[i] or p["title"],
                                    "title": p["title"]})

    os.makedirs(out_dir, exist_ok=True)
    written = []

    def write(name, title, desc, slug, canon, sidebar, main, jsonld, main_attr=""):
        htmltext = page_shell(title, desc, slug, canon, sidebar, main, jsonld, base,
                              theme_css, main_attr)
        with io.open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(htmltext)
        written.append(name)

    # 侧栏（每页重算 active）
    def sb(active):
        return sidebar_html(active, chapters, pages_meta)

    foot = ('<p class="pfoot">《董老师香港留学指南》%s · 最后更新 %s<br>'
            '内容采用 CC BY-NC-SA 4.0（可转载、需署名、不得商用）<br>'
            '数字以官方原文为准，引用前请回官方核对<br>'
            '联系董老师：微信 jack787300 / dxw22465 · 邮箱 kk2688@agent.qq.com</p>'
            % (VERSION, LASTMOD))

    # 1) 首页：导读 + 章节导航
    intro_secs = []
    if head:
        for s in head["secs"]:
            body = clean_lines(s["lines"])
            if not body:
                continue
            body = re.sub(r"^\*\*在线版（推荐）\*\*.*$", "", body, flags=re.M)
            body = re.sub(r"^\*\*GitHub 仓库\*\*.*$", "", body, flags=re.M)  # hero 已有链接，不重复
            # hero 已带这些信息，正文不重复
            body = re.sub(r"^\*[^\n]*插班[^\n]*\*$", "", body, flags=re.M)
            body = re.sub(r"^\*\*本文由董老师审核.*$", "", body, flags=re.M)
            body = re.sub(r"^\*\*版本\*\*.*$", "", body, flags=re.M)
            body = re.sub(r"^`版本 v1\.0`[^\n]*$", "", body, flags=re.M)
            intro_secs.append("<section><h2>%s</h2>%s</section>"
                              % (html.escape(s["title"]), link_refs(md2html(body), ids)))
    intro_html = "\n".join(intro_secs) or link_refs(md2html(clean_lines(doc["intro"])), ids)
    hero = """<div class="hero">
<h1>董老师香港留学指南</h1>
<p class="tagline">中学插班 · 本科申请 · 本科申硕 · 身份规划 · 费用预算 · 防骗打假</p>
<div class="vers">
<span class="chip c-low">%s</span><span class="chip">49 条收录</span>
<span class="chip">A 级官方信源 84%%</span><span class="chip">每条可核回官方原文</span>
</div>
<p class="contact"><a href="https://kk2688qq.github.io/dong-hk-guide/">在线版（永远是最新版）</a><br>
<a href="https://github.com/kk2688qq/dong-hk-guide">GitHub 仓库</a><br>
本文由董老师审核。更多问题请联系微信：jack787300、dxw22465，邮箱：kk2688@agent.qq.com</p>
</div>""" % VERSION
    index_main = ('<div class="wrap">%s<div class="sect">%s</div>%s</div>'
                  % (hero, intro_html, foot))
    idx_ld = {
        "@context": "https://schema.org", "@type": "Book",
        "name": SITE_TITLE, "author": {"@type": "Person", "name": "董老师"},
        "inLanguage": LANG, "license": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "description": SITE_DESC, "version": VERSION,
        "dateModified": LASTMOD, "url": base,
    }
    cr, crld = breadcrumb([("首页", None)])
    write("index.html", "%s — 49 条，每条可核回官方原文" % SITE_TITLE,
          SITE_DESC[:150], "index", "", sb("index"), index_main, idx_ld)

    # 2) 阅读页（第一/二/四/五部分）
    for i, p in enumerate(doc["parts"]):
        slug = part_slugs.get(i)
        if not slug:
            continue
        secs = []
        for s in p["secs"]:
            body = clean_lines(s["lines"])
            if not body:
                continue
            secs.append("<section><h2>%s</h2>%s</section>"
                        % (html.escape(s["title"]), link_refs(md2html(body), ids)))
        main = ('<div class="wrap"><nav class="crumbs" aria-label="所在位置">'
                '<a href="index.html">首页</a><span class="sep">›</span><span>%s</span></nav>'
                "<article><h1>%s</h1>%s</article>%s</div>%s"
                % (html.escape(p["title"]), html.escape(p["title"]),
                   "\n".join(secs), foot, ""))
        desc = first_paragraph_text(p["secs"][0]["lines"] and clean_lines(p["secs"][0]["lines"]) or SITE_DESC, 110) if p["secs"] else SITE_DESC[:110]
        ld = {"@context": "https://schema.org", "@type": "WebPage",
              "name": "%s：%s" % (SITE_TITLE, p["title"]),
              "description": desc, "inLanguage": LANG,
              "isPartOf": {"@type": "Book", "name": SITE_TITLE, "url": base},
              "dateModified": LASTMOD}
        _, crld = breadcrumb([("首页", "index.html"), (p["title"], None)])
        ld["about"] = crld  # 简化：面包屑并入 about（部分页不强制）
        write("%s.html" % slug, "%s：%s" % (SITE_TITLE, p["title"]),
              desc, slug, "%s.html" % slug, sb(slug), main, ld)

    # 3) 条目页 × 49
    for ch in chapters:
        for e in ch["entries"]:
            slug = e["id"].lower()
            chap_label = "第 %s 章 · %s" % (ch["num"], ch["title"])
            cr, crld = breadcrumb([("首页", "index.html"),
                                   (chap_label, None),
                                   ("%s %s" % (e["id"], e["title"]), None)])
            article = ['<div class="wrap" data-ch="%s">' % ch["num"]]
            article.append(cr)
            article.append("<article>")
            article.append("<h1>%s %s</h1>" % (e["id"], html.escape(e["title"])))
            article.append(chips(e["meta"]))
            article.append(render_fields(e, ids))
            article.append("</article>")
            # 2026-10-08 董老师定：去掉「上一篇/下一篇」与「同章其他条目」模块
            article.append(foot)
            article.append("</div>")
            title = "%s %s - %s" % (e["id"], e["title"], SITE_TITLE)
            desc = entry_desc(e)
            ld = {
                "@context": "https://schema.org",
                "@type": "TechArticle",
                "headline": "%s %s" % (e["id"], e["title"]),
                "description": desc,
                "inLanguage": LANG,
                "author": {"@type": "Person", "name": "董老师"},
                "publisher": {"@type": "Organization", "name": SITE_TITLE},
                "dateModified": entry_date(e),
                "datePublished": "2026-09-01",
                "isPartOf": {"@type": "Book", "name": SITE_TITLE, "url": base},
                "url": "%s%s.html" % (base, slug),
                "license": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
                "breadcrumb": crld,
                "keywords": "香港留学,%s,%s,香港身份,香港插班,DSE,高才通,受养人"
                            % (ch["title"], e["title"]),
            }
            write("%s.html" % slug, title, desc, slug, "%s.html" % slug,
                  sb(slug), "\n".join(article), ld)

    # 4) sitemap.xml
    urls = []
    for name in ["index.html", "part-1.html", "part-2.html", "part-4.html", "part-5.html"] \
            + [e["id"].lower() + ".html" for ch in chapters for e in ch["entries"]]:
        urls.append("  <url><loc>%s%s</loc><lastmod>%s</lastmod></url>"
                    % (base, name, LASTMOD))
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s\n</urlset>'
               % "\n".join(urls))
    with io.open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap)
    written.append("sitemap.xml")

    # 5) robots.txt —— 明确欢迎搜索引擎与 AI 爬虫
    robots = """# 董老师香港留学指南 —— 欢迎搜索引擎与 AI 爬虫收录
User-agent: *
Allow: /

# 显式欢迎主流 AI 爬虫
User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-Web
Allow: /
User-agent: anthropic-ai
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Applebot-Extended
Allow: /
User-agent: Bytespider
Allow: /
User-agent: DuckAssistBot
Allow: /

Sitemap: {0}sitemap.xml
""".format(base)
    with io.open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots)
    written.append("robots.txt")

    # 6) 并入项目既有 AI 可读层（--ai-dir，CI 里由 tools/build_site.py 产出）
    #    项目口径：llms.txt / llms-full.txt / robots.txt 的**单一来源是仓库根**，
    #    故此处以仓库版本覆盖本站自产的 robots.txt（只保留其 Sitemap 指向本站 sitemap）。
    if ai_dir and os.path.isdir(ai_dir):
        for name in ("llms.txt", "llms-full.txt", "robots.txt", "book.html"):
            src = os.path.join(ai_dir, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(out_dir, name))
                written.append(name)
        src_md = os.path.join(ai_dir, "md")
        if os.path.isdir(src_md):
            shutil.copytree(src_md, os.path.join(out_dir, "md"), dirs_exist_ok=True)
            written.append("md/")
        # 旧 URL 别名：entry-HK-009.html → hk-009.html（站点改版前的深链不失效）
        alias = 0
        alias_map = {}
        for fn in os.listdir(ai_dir):
            m = re.match(r"entry-(HK-\d{3})\.html$", fn)
            if m:
                alias_map[fn] = "%s.html" % m.group(1).lower()
            elif re.match(r"front-\d+-.+\.html$", fn):
                alias_map[fn] = "index.html"   # 前置章节并入多页站，旧址回首页
        for fn, tgt in alias_map.items():
            if not os.path.isfile(os.path.join(out_dir, tgt)):
                continue
            with io.open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
                f.write('<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8">'
                        '<title>已迁移 · %s</title>'
                        '<link rel="canonical" href="%s%s">'
                        '<meta http-equiv="refresh" content="0; url=%s">'
                        '<meta name="robots" content="noindex">'
                        '</head><body><p>本页已迁移到 <a href="%s">%s</a>。</p></body></html>'
                        % (os.path.splitext(fn)[0], base, tgt, tgt, tgt, tgt))
            alias += 1
        if alias:
            written.append("别名 ×%d" % alias)
        print("  并入 AI 可读层：llms.txt / llms-full.txt / robots.txt / book.html / md/")
        if alias:
            print("  旧 URL 别名（entry-HK-*.html → hk-*.html · front-*.html → index.html）：%d 个" % alias)

    print("生成 %d 个文件 → %s" % (len(written), out_dir))
    print("  条目页：%d · 阅读页：4 · 首页：1 · sitemap/robots：2"
          % sum(1 for w in written if w.startswith("hk-")))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=DEFAULT_MD)
    ap.add_argument("--out", default=os.path.join(HERE, "_site"))
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--theme", default="B", choices=["default"] + THEME_ORDER,
                    help="配色/设计元素主题：A 深色导航 / B 暖纸手册（默认，已拍板）/ C 靛蓝编码 / D 黑白线框")
    ap.add_argument("--ai-dir", default=None,
                    help="项目既有站点产物目录（含 llms.txt/llms-full.txt/robots.txt/book.html/md/"
                         "与 entry-HK-*.html），并入本站并生成旧 URL 别名。CI 里传 site-ai。")
    a = ap.parse_args()
    build(a.md, a.out, a.base, a.theme, a.ai_dir)
    if a.theme in THEMES:
        print("  主题：%s（%s）" % (THEMES[a.theme]["name"], THEMES[a.theme]["note"]))
