#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 book/ 编译成**读者视图**单页（对照《高性价比人生指南》的阅读模型）。

为什么另起一个生成器，而不是改造 build_site.py：
build_site.py 出的是「目录页 + 每条一页」——读者点进去看到的仍是 12 个字段平铺
的长文。本脚本按对照项目的做法，把每条压成**一张卡**：

    序号 + 标题
    徽章行（风险 / 决策阶段 / 证据等级 / 焦虑类型）
    ▸ 说人话（主角位，读者只看这一行就够拿主意）
    ▸ 折叠：要花什么 / 换回什么 / 红线提醒 / 常见误传 / 待核实
    ▸ 折叠：官方依据与审核信息（证据等级 + 官方依据 / 关键节点与时效 /
            适用人群 + 入学年度 / 风险等级与决策阶段 / 最后核实日期 + 核实人）

产物是**自包含单文件**：CSS/JS/正文全部内联，双击就开、断网可用、可直接转发。
同一个文件既是网站首页（site/index.html），也是 Release 里那份可下载 HTML。

设计原则（与全项目一致）：
- **不新增任何事实**：所有文字、数字、徽章取值一律从 book/ 正文解析；
- **单一来源**：主线分组取自 docs/HK编号对照表.md，标题/风险/证据取自正文。
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import sys

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("需要 markdown 库：pip3 install markdown")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_site import GROUPS, group_of, load_catalog  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
META = os.path.join(ROOT, "meta")
SITE = "https://kk2688qq.github.io/dong-hk-guide"
REPO = "https://github.com/kk2688qq/dong-hk-guide"
BOOK_TITLE = "董老师香港留学指南"

RE_TITLE = re.compile(r"^#\s+(HK-\d{3})\s+(.+?)\s*$")
RE_RISK = re.compile(r"<!--\s*风险\s*=\s*(\S+)\s+阶段\s*=\s*(\S+)\s+焦虑\s*=\s*(\S+?)\s*-->")
RE_FIELD = re.compile(r"^\*\*(?!说人话$)([^*\n]{2,40})\*\*\s*$", re.M)
RE_URL = re.compile(r"(?<![=\"'>])\b(https?://[^\s<>\"'）)】\]]+)")

# 字段 → 归到哪一栏。读者栏默认在「说人话」下面第一层折叠；
# 依据栏是「要核对才看」的东西，收进第二层，避免第一屏被审核字段淹没。
READER_FIELDS = [
    ("要花什么", "代价"),
    ("换回什么", "拿到什么"),
    ("红线提醒", "别踩的坑"),
    ("常见误传", "听起来很对、其实不对"),
    ("待核实", "还没核到的"),
]
EVIDENCE_FIELDS = [
    ("证据等级 + 官方依据", "证据等级与官方依据"),
    ("关键节点与时效", "关键节点与时效"),
    ("适用人群 + 入学年度", "谁该看 · 适用哪一年"),
    ("解决什么焦虑 + 风险等级 + 决策阶段", "风险等级与决策阶段"),
    ("最后核实日期 + 核实人", "最后核实日期与核实人"),
]

RISK_ORDER = {"高": 0, "中": 1, "低": 2}
STAGES = ("要不要去", "怎么申请", "怎么选", "怎么落地")


# ---------------------------------------------------------------- 解析
def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split_fields(text: str) -> tuple[str, str, dict]:
    """→ (标题, 说人话, {字段名: 正文})。"""
    first = text.split("\n", 1)[0]
    m = RE_TITLE.match(first)
    title = m.group(2) if m else first.lstrip("# ").strip()

    body = text[text.find("\n") :]
    marks = [(m.start(), m.group(1)) for m in RE_FIELD.finditer(body)]
    lede = ""
    ml = re.search(r"\*\*说人话\*\*\s*\n+(.+?)(?=\n\*\*[^*\n]{2,40}\*\*\s*$|\Z)", body, re.S | re.M)
    if ml:
        lede = ml.group(1).strip()
        body = body[: ml.start()] + body[ml.end() :]
        marks = [(m.start(), m.group(1)) for m in RE_FIELD.finditer(body)]

    fields: dict = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        chunk = body[pos:end]
        chunk = chunk.split("\n", 1)[1] if "\n" in chunk else ""
        fields[name] = chunk.strip()
    return title, lede, fields


def md2html(text: str) -> str:
    if not text:
        return ""
    out = markdown.markdown(
        text, extensions=["tables", "sane_lists"], output_format="html5"
    )
    # 裸链接补成可点（正文里官方依据大量使用 <https://…>，markdown 已处理；
    # 少数写成裸 URL 的这里兜一下），已位于 href/src 里的不重复处理。
    out = RE_URL.sub(
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        out,
    )
    # 兜底：不要让上面那次替换把已经生成的 <a href="..."> 再包一层
    out = out.replace('href="<a href="', 'href="').replace('">">', '">')
    return out


def plain(text: str) -> str:
    """去掉 markdown 记号，供搜索索引与折叠摘要用。"""
    t = re.sub(r"`([^`]*)`", r"\1", text)
    t = re.sub(r"\*\*([^*]*)\*\*", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<([^>]+)>", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def load_entries() -> list[dict]:
    catalog = load_catalog()
    out = []
    for path in sorted(glob.glob(os.path.join(BOOK, "*.md"))):
        text = read(path)
        name = os.path.basename(path)
        m = RE_TITLE.match(text.split("\n", 1)[0])
        if not m:
            continue
        hk, title = m.group(1), m.group(2)
        lede_raw, fields = split_fields(text)[1:]
        risk, stage, anxiety = "", "", ""
        mr = RE_RISK.search(text)
        if mr:
            risk, stage, anxiety = mr.groups()
        mg = re.search(r"证据等级\*{0,2}\s*[:：]\s*\*{0,2}\s*([ABC])", text)
        grade = mg.group(1) if mg else ""
        cat = catalog.get(hk, {})
        track = cat.get("track", "")
        out.append(
            {
                "hk": hk,
                "file": name,
                "title": title,
                "risk": risk,
                "stage": stage,
                "anxiety": anxiety,
                "grade": grade,
                "group": group_of(track),
                "lede": lede_raw,
                "fields": fields,
                "num": name[:3],
            }
        )
    out.sort(key=lambda e: (e["hk"]))
    return out


# ---------------------------------------------------------------- 渲染
def badges(e: dict) -> str:
    def b(cls: str, text: str, tip: str = "") -> str:
        t = f' title="{html.escape(tip)}"' if tip else ""
        return f'<span class="bdg {cls}"{t}>{html.escape(text)}</span>'

    out = []
    if e["risk"]:
        out.append(b(f"r-{e['risk']}", f"风险 {e['risk']}"))
    if e["grade"]:
        out.append(b("grade", f"证据 {e['grade']} 级", "A＝官方原文；B＝官方二手；C＝作者经验"))
    if e["stage"]:
        out.append(b("plain", e["stage"]))
    if e["anxiety"]:
        out.append(b("plain", f"{e['anxiety']}"))
    return "".join(out)


def card(e: dict, idx: int) -> str:
    read_rows = []
    for name, label in READER_FIELDS:
        v = e["fields"].get(name, "")
        if not v:
            continue
        read_rows.append(
            f'<section class="row"><h4>{html.escape(label)}'
            f'<span class="src-name">{html.escape(name)}</span></h4>'
            f'<div class="body">{md2html(v)}</div></section>'
        )
    ev_rows = []
    for name, label in EVIDENCE_FIELDS:
        v = e["fields"].get(name, "")
        if not v:
            continue
        ev_rows.append(
            f'<section class="row"><h4>{html.escape(label)}</h4>'
            f'<div class="body">{md2html(v)}</div></section>'
        )
    others = [
        k
        for k in e["fields"]
        if k not in dict(READER_FIELDS) and k not in dict(EVIDENCE_FIELDS)
    ]
    for name in others:
        ev_rows.append(
            f'<section class="row"><h4>{html.escape(name)}</h4>'
            f'<div class="body">{md2html(e["fields"][name])}</div></section>'
        )

    more = (
        f'<details class="fold"><summary>展开明细（{len(read_rows)} 栏：'
        f'代价 · 拿到什么 · 别踩的坑 · 误传 · 待核实）</summary>'
        f'<div class="fold-in">{"".join(read_rows)}</div></details>'
        if read_rows
        else ""
    )
    ev = (
        f'<details class="fold ev"><summary>官方依据与审核信息</summary>'
        f'<div class="fold-in">{"".join(ev_rows)}</div></details>'
        if ev_rows
        else ""
    )
    return f"""<article class="card" id="{e['hk']}" data-hk="{e['hk']}"
 data-risk="{html.escape(e['risk'])}" data-stage="{html.escape(e['stage'])}"
 data-grade="{html.escape(e['grade'])}" data-group="{html.escape(e['group'])}">
  <header class="ch">
    <span class="idx">{idx}</span>
    <h3>{html.escape(e['title'])}<a class="perma" href="#{e['hk']}" aria-label="本条链接">#</a></h3>
  </header>
  <div class="bdgs">{badges(e)}<span class="bdg id">{e['hk']}</span></div>
  <div class="lede">{md2html(e['lede'])}</div>
  {more}
  {ev}
</article>"""


CSS = """
:root{
  --bg:#fff; --fg:#1c1f23; --fg2:#4a5057; --mut:#7a828b; --line:#e4e6e9;
  --card:#fbfbfc; --card2:#f5f6f8; --acc:#0b5cad; --acc-soft:#eaf2fb;
  --r-hi:#c0392b; --r-hi-bg:#fdeeec; --r-md:#a86a00; --r-md-bg:#fdf4e4;
  --r-lo:#3f7a58; --r-lo-bg:#edf5f0;
  --radius:12px; --wrap:820px;
}
@media (prefers-color-scheme: dark){
  html:not(.light){
    --bg:#17191c; --fg:#e8eaed; --fg2:#c3c8ce; --mut:#9aa2ab; --line:#2c3035;
    --card:#1e2124; --card2:#24282c; --acc:#7fb3ec; --acc-soft:#1d2a3a;
    --r-hi:#f08b80; --r-hi-bg:#3a2320; --r-md:#e0ab5a; --r-md-bg:#332a1b;
    --r-lo:#7ec59b; --r-lo-bg:#1d2f25;
  }
}
html.dark{
  --bg:#17191c; --fg:#e8eaed; --fg2:#c3c8ce; --mut:#9aa2ab; --line:#2c3035;
  --card:#1e2124; --card2:#24282c; --acc:#7fb3ec; --acc-soft:#1d2a3a;
  --r-hi:#f08b80; --r-hi-bg:#3a2320; --r-md:#e0ab5a; --r-md-bg:#332a1b;
  --r-lo:#7ec59b; --r-lo-bg:#1d2f25;
  color-scheme:dark;
}
html.light{color-scheme:light}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
  "Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 20px 96px}

/* 页头 */
.top{border-bottom:1px solid var(--line);background:var(--bg);
  position:sticky;top:0;z-index:20;backdrop-filter:blur(8px)}
.top-in{max-width:var(--wrap);margin:0 auto;padding:12px 20px;
  display:flex;align-items:center;gap:14px}
.brand{font-weight:700;font-size:17px;letter-spacing:-.01em;color:var(--fg);white-space:nowrap}
.brand:hover{text-decoration:none}
.top .sp{flex:1}
.search{position:relative;flex:1;max-width:340px}
.search input{width:100%;height:38px;padding:0 12px 0 34px;border-radius:9px;
  border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;font-size:14px}
.search input:focus{outline:0;border-color:var(--acc);background:var(--bg)}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);
  width:15px;height:15px;stroke:var(--mut);fill:none;stroke-width:2}
.theme{flex:none;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);
  background:var(--card);color:var(--fg2);cursor:pointer;font-size:15px;line-height:1}
.theme:hover{border-color:var(--acc);color:var(--acc)}

/* 首屏 */
.hero{padding:34px 0 6px}
.hero h1{font-size:27px;line-height:1.4;margin:0 0 10px;letter-spacing:-.02em}
.hero p{margin:0 0 12px;color:var(--fg2);font-size:15.5px}
.howto{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;margin:16px 0 4px;font-size:14.5px;color:var(--fg2);line-height:1.8}
.howto b{color:var(--fg)}
.howto p{margin:0 0 8px}
.howto p:last-child{margin:0}
.dl{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}
.dl a{border:1px solid var(--line);background:var(--card);border-radius:999px;
  padding:6px 14px;font-size:13.5px;color:var(--fg2)}
.dl a:hover{border-color:var(--acc);color:var(--acc);text-decoration:none}
.dl a b{color:var(--acc);font-weight:600}

/* 筛选条 */
.filters{position:sticky;top:63px;z-index:19;background:var(--bg);
  border-bottom:1px solid var(--line);padding:10px 0 12px;margin-bottom:8px}
.frow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:7px}
.frow>b{font-size:12.5px;color:var(--mut);font-weight:600;min-width:34px}
.fbtn{border:1px solid var(--line);background:var(--card);color:var(--fg2);
  border-radius:999px;padding:4px 12px;font:inherit;font-size:13px;cursor:pointer;
  transition:all .15s}
.fbtn:hover{border-color:var(--acc);color:var(--acc)}
.fbtn[aria-pressed="true"]{background:var(--acc-soft);border-color:var(--acc);color:var(--acc);font-weight:600}
.fstat{font-size:13px;color:var(--mut);margin-top:2px}
.fstat b{color:var(--fg);font-weight:600}

/* 主线标题 */
.grp{margin:34px 0 0}
.grp>h2{font-size:19px;margin:0 0 4px;padding-top:16px;border-top:2px solid var(--fg);
  letter-spacing:-.01em;display:flex;align-items:baseline;gap:10px}
.grp>h2 .n{margin-left:auto;font-size:13px;color:var(--mut);font-weight:400}
.grp>.gd{color:var(--fg2);font-size:14.5px;margin:0 0 16px}

/* 卡片 */
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);
  border-radius:var(--radius);padding:20px 22px 16px;margin:0 0 14px}
.card[data-risk="高"]{border-left-color:var(--r-hi)}
.card[data-risk="中"]{border-left-color:var(--r-md)}
.card[data-risk="低"]{border-left-color:var(--r-lo)}
.card[hidden]{display:none}
.ch{display:flex;align-items:flex-start;gap:11px;margin-bottom:8px}
.idx{flex:none;width:26px;height:26px;border-radius:8px;background:var(--card2);
  color:var(--mut);display:grid;place-items:center;font-size:12.5px;
  font-variant-numeric:tabular-nums;margin-top:3px}
.ch h3{margin:0;font-size:18.5px;line-height:1.5;font-weight:650;letter-spacing:-.01em}
.perma{opacity:0;margin-left:7px;color:var(--mut);font-weight:400}
.card:hover .perma{opacity:1}
.bdgs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px 37px}
.bdg{font-size:12px;line-height:1.7;border-radius:999px;padding:1px 9px;
  border:1px solid var(--line);background:var(--bg);color:var(--fg2)}
.bdg.r-高{background:var(--r-hi-bg);border-color:transparent;color:var(--r-hi);font-weight:600}
.bdg.r-中{background:var(--r-md-bg);border-color:transparent;color:var(--r-md);font-weight:600}
.bdg.r-低{background:var(--r-lo-bg);border-color:transparent;color:var(--r-lo);font-weight:600}
.bdg.grade{background:var(--acc-soft);border-color:transparent;color:var(--acc);font-weight:600}
.bdg.id{color:var(--mut);font-variant-numeric:tabular-nums}

/* 说人话 = 主角 */
.lede{margin:0;font-size:16.5px;line-height:1.95;color:var(--fg);
  background:var(--bg);border:1px solid var(--line);border-left:3px solid var(--acc);
  border-radius:10px;padding:14px 16px}
.lede p{margin:0 0 8px}
.lede p:last-child{margin:0}

/* 折叠 */
details.fold{margin:12px 0 0;border-top:1px solid var(--line)}
details.fold>summary{cursor:pointer;list-style:none;padding:11px 2px;font-size:14px;
  font-weight:600;color:var(--fg2);display:flex;align-items:center;gap:8px}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"▸";color:var(--mut);font-size:12px;
  transition:transform .18s;display:inline-block}
details.fold[open]>summary::before{transform:rotate(90deg)}
details.fold>summary:hover{color:var(--acc)}
details.fold.ev>summary{font-weight:500;color:var(--mut)}
.fold-in{padding:2px 0 6px}
.row{padding:11px 0;border-top:1px dashed var(--line)}
.row:first-child{border-top:0}
.row h4{margin:0 0 6px;font-size:14px;font-weight:650;color:var(--fg);
  display:flex;align-items:baseline;gap:8px}
.row h4 .src-name{font-size:11.5px;font-weight:400;color:var(--mut);
  border:1px solid var(--line);border-radius:4px;padding:0 5px}
.row .body{font-size:15px;line-height:1.9;color:var(--fg2)}
.row .body>p:first-child{margin-top:0}
.row .body>p:last-child{margin-bottom:0}
.row .body p{margin:.5em 0}
.row .body ul,.row .body ol{padding-left:1.4em;margin:.4em 0}
.row .body li{margin:.25em 0}
.row .body strong{color:var(--fg)}
.row .body blockquote{margin:.6em 0;padding:2px 0 2px 12px;border-left:3px solid var(--line);color:var(--mut)}
.row .body code{background:var(--card2);padding:1px 5px;border-radius:4px;font-size:.9em}
.row .body table{border-collapse:collapse;width:100%;margin:.7em 0;font-size:14px}
.row .body th,.row .body td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
.row .body th{background:var(--card2);font-weight:600}

/* 尾 */
.foot{margin-top:56px;padding-top:22px;border-top:1px solid var(--line);
  font-size:13.5px;color:var(--mut);line-height:1.9}
.foot a{color:var(--fg2)}
.totop{position:fixed;right:22px;bottom:22px;width:42px;height:42px;border-radius:50%;
  border:1px solid var(--line);background:var(--card);color:var(--fg2);cursor:pointer;
  font-size:18px;display:none;place-items:center;box-shadow:0 2px 10px rgba(0,0,0,.08)}
.totop.on{display:grid}
mark.hit{background:#ffe9a8;color:inherit;border-radius:3px}
@media (prefers-color-scheme: dark){mark.hit{background:#5c4a12}}
@media (max-width:640px){
  .hero h1{font-size:23px}
  .card{padding:16px 15px 12px;border-radius:10px}
  .bdgs{margin-left:0}
  .ch h3{font-size:17px}
  .lede{font-size:16px;padding:12px 13px}
  .filters{top:61px;overflow-x:auto}
  .search{max-width:none}
  .brand{font-size:15px}
}
@media print{
  .top,.filters,.totop,.perma{display:none!important}
  body{font-size:11pt}
  .card{border:1px solid #ddd;break-inside:avoid;page-break-inside:avoid}
  details.fold{display:block}
  details.fold>.fold-in{display:block!important}
  .lede{background:#fff}
  a{color:#000;text-decoration:none}
  .card::after{content:"来源：" attr(data-hk);font-size:8pt;color:#666}
}
"""

JS = r"""
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var state={q:'',risk:'',stage:'',grade:''};
  var stat=document.getElementById('fstat');
  var groups=[].slice.call(document.querySelectorAll('.grp'));

  // 搜索索引在运行时从卡片自身文本构建 —— 不把正文再抄一份进 data-q，
  // 文件因此小一半；折叠区里的文字也照样能被搜到（textContent 含未展开内容）。
  cards.forEach(function(c){
    c._hay=(c.textContent||'').toLowerCase().replace(/\s+/g,' ');
  });

  function norm(s){return (s||'').toLowerCase();}

  function apply(){
    var q=norm(state.q.trim());
    var n=0;
    cards.forEach(function(c){
      var ok=true;
      if(state.risk && c.dataset.risk!==state.risk) ok=false;
      if(ok && state.stage && c.dataset.stage!==state.stage) ok=false;
      if(ok && state.grade && c.dataset.grade!==state.grade) ok=false;
      if(ok && q && (c._hay||'').indexOf(q)===-1) ok=false;
      c.hidden=!ok;
      if(ok) n++;
    });
    groups.forEach(function(g){
      var vis=g.querySelectorAll('.card:not([hidden])').length;
      g.hidden = vis===0;
      var k=g.querySelector('.n');
      if(k) k.textContent='显示 '+vis+' / '+g.querySelectorAll('.card').length+' 条';
    });
    if(stat){
      stat.innerHTML = (n===cards.length)
        ? '共 <b>'+cards.length+'</b> 条'
        : '筛出 <b>'+n+'</b> 条，共 '+cards.length+' 条'+
          (n===0?' —— <a href="#" id="clr">清掉筛选</a>':'');
      var clr=document.getElementById('clr');
      if(clr) clr.onclick=function(ev){ev.preventDefault();reset();};
    }
  }
  function reset(){
    state={q:'',risk:'',stage:'',grade:''};
    var s=document.getElementById('q'); if(s) s.value='';
    [].forEach.call(document.querySelectorAll('.fbtn'),function(b){
      b.setAttribute('aria-pressed', b.dataset.v==='' ? 'true':'false');
    });
    apply();
  }
  [].forEach.call(document.querySelectorAll('.fbtn'),function(b){
    b.addEventListener('click',function(){
      var f=b.dataset.f, v=b.dataset.v;
      state[f]=v;
      [].forEach.call(document.querySelectorAll('.fbtn[data-f="'+f+'"]'),function(x){
        x.setAttribute('aria-pressed', x===b?'true':'false');
      });
      apply();
    });
  });
  var s=document.getElementById('q');
  if(s){
    s.addEventListener('input',function(){state.q=s.value;apply();});
    document.addEventListener('keydown',function(e){
      if(e.key==='/' && document.activeElement!==s){e.preventDefault();s.focus();}
      if(e.key==='Escape' && document.activeElement===s){s.value='';state.q='';apply();s.blur();}
    });
    // 支持 ?q=… 深链（README / 转发链接里带上关键词）
    var m=/[?&]q=([^&]+)/.exec(location.search);
    if(m){ s.value=decodeURIComponent(m[1].replace(/\+/g,' ')); state.q=s.value; }
  }
  apply();

  // 折叠「展开全部 / 收起全部」
  var all=document.getElementById('foldall');
  if(all){
    all.addEventListener('click',function(ev){
      ev.preventDefault();
      var open=all.dataset.open!=='1';
      [].forEach.call(document.querySelectorAll('details.fold'),function(d){d.open=open;});
      all.dataset.open=open?'1':'0';
      all.textContent=open?'收起全部明细':'展开全部明细';
    });
  }

  var tt=document.getElementById('totop');
  function onScroll(){ if(tt) tt.classList.toggle('on', window.scrollY>700); }
  window.addEventListener('scroll',onScroll,{passive:true}); onScroll();
  if(tt) tt.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});

  // 深浅色：跟随系统，点一下强制反转，再点回跟随（记忆在 localStorage）
  var tb=document.getElementById('theme');
  if(tb){
    tb.addEventListener('click',function(){
      var d=document.documentElement;
      var sysDark=window.matchMedia('(prefers-color-scheme: dark)').matches;
      var nowDark = d.className==='dark' || (d.className!=='light' && sysDark);
      d.className = nowDark ? 'light' : 'dark';
      try{localStorage.setItem('theme', d.className);}catch(e){}
    });
  }
})();
"""


def fbtn(field: str, value: str, label: str, pressed: bool = False) -> str:
    pr = "true" if pressed else "false"
    return (
        f'<button class="fbtn" data-f="{field}" data-v="{html.escape(value)}" '
        f'aria-pressed="{pr}">{html.escape(label)}</button>'
    )


def build_page(entries: list[dict], online: bool, stamp: str = "") -> str:
    toc = []
    body = []
    for gname, _ in GROUPS:
        bucket = [e for e in entries if e["group"] == gname]
        if not bucket:
            continue
        body.append(
            f'<section class="grp" data-group="{html.escape(gname)}">'
            f"<h2>{html.escape(gname)}<span class=\"n\"></span></h2>"
            + "".join(card(e, i + 1) for i, e in enumerate(bucket))
            + "</section>"
        )
        toc.append(
            f"{html.escape(gname)}（{len(bucket)} 条）"
        )
    placed = {g for g, _ in GROUPS}
    rest = [e for e in entries if e["group"] not in placed]
    if rest:
        body.append(
            '<section class="grp" data-group="其他"><h2>其他<span class="n"></span></h2>'
            + "".join(card(e, i + 1) for i, e in enumerate(rest))
            + "</section>"
        )

    n = len(entries)
    grade_a = sum(1 for e in entries if e["grade"] == "A")
    ratio = f"{round(grade_a * 100 / n)}%" if n else "—"
    dl = (
        f'<a href="{REPO}/releases/download/book-latest/HKStudyGuide.html"><b>单文件 HTML</b>'
        "（就是这个页面，可离线）</a>"
        f'<a href="{REPO}/releases/download/book-latest/HKStudyGuide.pdf"><b>PDF</b>（A4，可打印）</a>'
        f'<a href="{REPO}/releases/download/book-latest/HKStudyGuide.epub"><b>EPUB</b>（Kindle / 微信读书）</a>'
        f'<a href="{REPO}">GitHub 仓库</a>'
    )
    note = (
        ""
        if online
        else f'<br>这是<b>离线副本</b>，生成于 {stamp}。正文会继续更新，'
        f'以 <a href="{SITE}">在线版</a> 为准。'
    )

    page = f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BOOK_TITLE} · {n} 条可查证的香港升学与身份决策</title>
<meta name="description" content="免费、可查证的中国香港升学与身份决策指南：{n} 条，覆盖中学插班、高考申本科、本科申硕、高才通／优才／受养人／IANG／永居，以及费用、住宿与「保录」「内推」骗局。每条只写查得到官方原文的内容。">
<meta name="theme-color" content="#0b5cad" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#17191c" media="(prefers-color-scheme: dark)">
<script>(function(){{try{{var s=localStorage.getItem('theme');
if(s==='dark')document.documentElement.className='dark';
else if(s==='light')document.documentElement.className='light';}}catch(e){{}}}})();</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%230b5cad'/%3E%3Cpath d='M20 32h24M32 20v24' stroke='white' stroke-width='7' stroke-linecap='round'/%3E%3C/svg%3E">
{'<link rel="canonical" href="' + SITE + '/">' if online else ''}
<style>{CSS}</style>
</head>
<body>
<header class="top"><div class="top-in">
  <a class="title brand" href="#top">{BOOK_TITLE}</a>
  <span class="sp"></span>
  <div class="search">
    <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
    <input id="q" type="search" autocomplete="off" placeholder="搜：高才通 / 留位费 / 插班 / 学费 / 受养人">
  </div>
  <button class="theme" id="theme" aria-label="切换深浅色" title="切换深浅色">◐</button>
</div></header>

<div class="wrap" id="top">
  <div class="hero">
    <h1>{BOOK_TITLE}</h1>
    <p>一份免费、可查证、随手可转发的中国香港升学与身份决策指南。讲中学插班、高考申大学、本科申硕、高才通／优才／受养人／IANG／永居，以及费用、住宿和「保录」「内推」这类骗局。</p>
    <p>每条写明<b>要花什么、换回什么、漏掉会怎样</b>，来源只引官方文件和院校官网。已收录 <b>{n}</b> 条，A 级官方信源 {ratio}。</p>

    <div class="howto">
      <p><b>怎么看最快</b>：每条第一块的<b>方框</b>就是「说人话」——把这一条的关键结论压成几句话，只看它就够拿主意。要核对数字、要看官方原文，再展开下面的折叠。</p>
      <p><b>不用全做</b>：这是按风险高低排好的<b>备选单</b>，不是任务清单。挑走一条就算数。</p>
      <p><b>怎么筛</b>：上面搜关键词；下面按<b>风险、决策阶段、证据等级</b>筛；按 <b>/</b> 直接跳到搜索框。<a href="#" id="foldall" data-open="0">展开全部明细</a>（PDF 打印用）。</p>
    </div>

    <div class="dl">{dl}</div>
  </div>

  <div class="filters">
    <div class="frow"><b>风险</b>{fbtn('risk','','全部',True)}{fbtn('risk','高','高')}{fbtn('risk','中','中')}{fbtn('risk','低','低')}</div>
    <div class="frow"><b>阶段</b>{fbtn('stage','','全部',True)}{''.join(fbtn('stage',s,s) for s in STAGES)}</div>
    <div class="frow"><b>证据</b>{fbtn('grade','','全部',True)}{fbtn('grade','A','A 级官方原文')}{fbtn('grade','B','B 级')}{fbtn('grade','C','C 级')}</div>
    <div class="fstat" id="fstat">共 <b>{n}</b> 条</div>
  </div>

  {''.join(body)}

  <div class="foot">
    <p><b>{BOOK_TITLE}</b>｜每条都由作者打开官方原文逐句核对后收录，核实记录公开在仓库 <code>docs/核实记录/</code>，包括哪些数字查不到、为什么没写。</p>
    <p>内容许可 CC BY-NC-SA 4.0：可自由转载，需署名并附仓库链接，不得商用。<br>
    作者：董老师，中国香港及海外身份与教育规划顾问｜微信 jack787300｜邮箱 kk2688@qq.com。<br>
    本指南不构成任何申请承诺；具体个案以香港入境事务处及院校官方要求为准。{note}</p>
  </div>
</div>
<button class="totop" id="totop" aria-label="回到顶部">↑</button>
<script>{JS}</script>
</body>
</html>
"""
    return page


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site", help="输出目录")
    ap.add_argument("--name", default="index.html", help="输出文件名")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="标注为「离线副本」（页脚提示以在线版为准）",
    )
    ap.add_argument("--stamp", default="", help="离线副本的生成时间文案")
    args = ap.parse_args()

    entries = load_entries()
    if not entries:
        sys.exit("book/ 下没有解析到任何条目")
    page = build_page(entries, online=not args.offline, stamp=args.stamp)
    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, args.name)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(page)
    kb = len(page.encode("utf-8")) / 1024
    print(f"读者视图已生成：{dst}")
    print(f"  {len(entries)} 条｜{kb:.0f} KB｜自包含单文件（双击即开，可离线、可转发）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
