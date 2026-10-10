#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 book/ 编译成**读者视图**单页（对照《高性价比人生指南》的阅读模型）。

为什么另起一个生成器，而不是改造 build_site.py：
build_site.py 出的是「目录页 + 每条一页」——读者点进去看到的仍是 12 个字段平铺
的长文。本脚本按对照项目的做法，把每条压成**一张卡**：

    序号 + 标题
    徽章行（风险 / 决策阶段 / 证据等级 / 焦虑类型）
    ▸ 说人话（主角位，读者只看这一行就够拿主意）
    ▸ 折叠：要花什么 / 换回什么 / 红线提醒 / 常见误传 / 官方尚未公布
    ▸ 折叠：官方依据与审核信息（证据等级 + 官方依据 / 关键节点与时效 /
            适用人群 + 入学年度 / 风险等级与决策阶段 / 本条最后更新）

产物是**自包含单文件**：CSS/JS/正文全部内联，双击就开、断网可用、可直接转发。
同一个文件既是网站首页（site/index.html），也是 Release 里那份可下载 HTML。

设计原则（与全项目一致）：
- **不新增任何事实**：所有文字、数字、徽章取值一律从 book/ 正文解析；
- **单一来源**：**读者章（分类）取自 docs/HK编号对照表.md 的「读者章」列**，
  章节顺序与副标题取自 build_site.GROUPS；标题/风险/证据取自正文。
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
from catalog import GROUPS, group_of, load_catalog  # noqa: E402  （单一来源：读者章）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
META = os.path.join(ROOT, "meta")
SITE = "https://kk2688qq.github.io/dong-hk-guide"
REPO = "https://github.com/kk2688qq/dong-hk-guide"
BOOK_TITLE = "董老师香港留学指南2026"

RE_TITLE = re.compile(r"^#\s+(HK-\d{3})\s+(.+?)\s*$")
RE_RISK = re.compile(r"<!--\s*风险\s*=\s*(\S+)\s+阶段\s*=\s*(\S+)\s+焦虑\s*=\s*(\S+?)\s*-->")
RE_FIELD = re.compile(r"^\*\*(?!说人话$)([^*\n]{2,40})\*\*\s*$", re.M)
RE_URL = re.compile(r"(?<![=\"'>])\b(https?://[^\s<>\"'）)】\]]+)")
# markdown 列表项（"− xxx" / "1. xxx"）——用来数「红线提醒有几条」「误传有几条」，
# 结果只写进折叠头，不改正文一个字。
RE_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+\S", re.M)

# 字段 → 归到哪一栏。读者栏默认在「说人话」下面第一层折叠；
# 依据栏是「要核对才看」的东西，收进第二层，避免第一屏被审核字段淹没。
READER_FIELDS = [
    ("要花什么", "代价"),
    ("换回什么", "拿到什么"),
    ("红线提醒", "别踩的坑"),
    ("常见误传", "听起来很对、其实不对"),
    ("官方尚未公布／未写死的事项", "官方尚未公布／未写死的"),
]
EVIDENCE_FIELDS = [
    ("证据等级 + 官方依据", "证据等级与官方依据"),
    ("关键节点与时效", "关键节点与时效"),
    ("适用人群 + 入学年度", "谁该看 · 适用哪一年"),
    ("解决什么焦虑 + 风险等级 + 决策阶段", "风险等级与决策阶段"),
]
# 「本条最后更新」不折叠：它是**信任凭据**，应当被看见但不该占主位，
# 故提到卡片页脚一行小字（见设计规范 §4.2④）。仍走同一份正文，不新增事实。
FOOT_FIELD = "本条最后更新"

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


def count_items(text: str) -> int:
    """数 markdown 列表项条数（只用于折叠头上的「含 N 条…」提示）。"""
    return len(RE_LIST_ITEM.findall(text or ""))


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
    if e["stage"]:
        out.append(b("plain", e["stage"]))
    if e["anxiety"]:
        out.append(b("plain", f"{e['anxiety']}"))
    # 证据等级排最后：先让读者看清"这条是什么情况"，再告诉他"可信到什么程度"。
    if e["grade"]:
        out.append(b("grade", f"证据 {e['grade']} 级", "A＝官方原文；B＝官方二手；C＝作者经验"))
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
        if k not in dict(READER_FIELDS)
        and k not in dict(EVIDENCE_FIELDS)
        and k != FOOT_FIELD
    ]
    for name in others:
        ev_rows.append(
            f'<section class="row"><h4>{html.escape(name)}</h4>'
            f'<div class="body">{md2html(e["fields"][name])}</div></section>'
        )

    # 折叠头写明「里面有什么、有几条」：读者**不展开**也知道这条有没有坑。
    # 这比把「红线提醒」默认展开更省首屏高度（设计规范 §4.2③）。
    sig = []
    n_red = count_items(e["fields"].get("红线提醒", ""))
    n_myth = count_items(e["fields"].get("常见误传", ""))
    if n_red:
        sig.append(f'<span class="warn">含 {n_red} 条红线提醒</span>')
    if n_myth:
        sig.append(f"{n_myth} 条常见误传")

    more = (
        f'<details class="fold"><summary><span>展开明细'
        f'{" · " + " · ".join(sig) if sig else ""}</span></summary>'
        f'<div class="fold-in">{"".join(read_rows)}</div></details>'
        if read_rows
        else ""
    )
    ev_label = "官方依据与审核信息"
    if e["grade"]:
        ev_label += f"（证据 {e['grade']} 级）"
    ev = (
        f'<details class="fold ev"><summary><span>{html.escape(ev_label)}</span></summary>'
        f'<div class="fold-in">{"".join(ev_rows)}</div></details>'
        if ev_rows
        else ""
    )
    # 核实凭据：页脚一行小字，常显（信任信息可见，但不占主位）
    foot_raw = e["fields"].get(FOOT_FIELD, "")
    foot = f'<div class="cfoot">{md2html(foot_raw)}</div>' if foot_raw else ""

    return f"""<article class="card" id="{e['hk']}" data-hk="{e['hk']}"
 data-risk="{html.escape(e['risk'])}" data-stage="{html.escape(e['stage'])}"
 data-grade="{html.escape(e['grade'])}" data-group="{html.escape(e['group'])}">
  <header class="ch">
    <span class="idx" aria-hidden="true">{idx}</span>
    <h3>{html.escape(e['title'])}<a class="perma" href="#{e['hk']}" aria-label="本条链接">#</a></h3>
    <span class="card-no" title="正文编号">{e['hk']}</span>
  </header>
  <div class="bdgs">{badges(e)}</div>
  <div class="lede">{md2html(e['lede'])}</div>
  {more}
  {ev}
  {foot}
</article>"""


CSS = """
:root{
  /* ---------- 底与面：三层分离 ----------
     卡片浮起来靠的是底色分层，不是阴影（深色模式下阴影几乎不可见）。
     现状 --card #fbfbfc 压在白底上只有 1.03:1，"50 条糊成一片"就是它。 */
  --bg:#F6F7F9; --surface:#FFFFFF; --surface-2:#F1F3F6;
  /* ---------- 文字（全部 ≥4.5:1） ---------- */
  --fg:#14181D; --fg2:#3E4650; --mut:#5F6771;
  /* ---------- 线 ----------
     --line    只画装饰线（分隔、卡片边框），不承载信息；
     --line-ui 画"需要被看见"的边界（输入框、按钮），必须 ≥3:1。两者不可混用。 */
  --line:#E4E8EC; --line-ui:#8A94A0;
  /* ---------- 品牌 ---------- */
  --acc:#0B5CAD; --acc-soft:#EAF2FB; --acc-hover:#0A4E93; --focus:#0B5CAD;
  /* ---------- 风险语义：按中国大陆习惯，红＝需警惕 ---------- */
  --r-hi:#B3261E; --r-hi-bg:#FDECEA;
  --r-md:#8A5A00; --r-md-bg:#FDF3E2;
  --r-lo:#2F6B4A; --r-lo-bg:#EAF5EF;
  --hl:#FFE9A8;
  /* ---------- 字体：全系统字体，零外链（顺序不能反，否则后面的匹配不到） ---------- */
  --font-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","HarmonyOS Sans SC",
    "MiSans","Hiragino Sans GB","Microsoft YaHei","Source Han Sans SC",
    "Noto Sans CJK SC",sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono",Consolas,"Cascadia Mono",monospace;
  /* ---------- 字号刻度（移动优先 + 流式） ----------
     硬规则：「说人话」永远 ≥ 卡片标题。移动端 17.5 vs 17，主角胜出。 */
  --fs-display:clamp(24px,6.2vw,32px); --fs-h2:clamp(18px,4.8vw,21px);
  --fs-lede:clamp(17.5px,4.5vw,19px);  --fs-h3:clamp(17px,4.3vw,18.5px);
  --fs-body:16px; --fs-sm:14px; --fs-xs:11.5px; --fs-2xs:11px;
  /* ---------- 形 ---------- */
  --radius:14px; --radius-sm:10px; --radius-pill:999px;
  --shadow-1:0 1px 2px rgba(16,24,40,.04);
  --shadow-2:0 4px 12px rgba(16,24,40,.08);
  /* ---------- 版心 ----------
     --measure 620px：16px 正文 ≈ 38.8 字/行、19px 说人话 ≈ 32.6 字/行，
     都落在中文舒适行宽 25–38 字内（现状 776px ≈ 48.5 字，属丢行区）。 */
  --wrap:720px; --measure:620px;
  /* 顶栏实测高度：供 sticky 筛选条对齐，由 JS 写入，未启 JS 时用下面的兜底值 */
  --hdr-h:92px;
  color-scheme:light;
}
/* 深色（轨一）：跟随系统，浏览器直接打开时生效 */
@media (prefers-color-scheme: dark){
  html:not(.light){
    --bg:#121417; --surface:#1A1D21; --surface-2:#22262B;
    --fg:#E9ECEF; --fg2:#BAC1C9; --mut:#8E97A1;
    --line:#2B3036; --line-ui:#616B77;
    --acc:#7FB3EC; --acc-soft:#17293C; --focus:#7FB3EC;
    --r-hi:#F2938A; --r-hi-bg:#3A2321;
    --r-md:#E3B268; --r-md-bg:#33291A;
    --r-lo:#85CBA4; --r-lo-bg:#1B2E24;
    --hl:#5C4A12; --shadow-1:none; --shadow-2:none;
    color-scheme:dark;
  }
}
/* 深色（轨二）：手动切换。微信内置浏览器**不跟随系统**，只走这条，故为主路径。 */
html.dark{
  --bg:#121417; --surface:#1A1D21; --surface-2:#22262B;
  --fg:#E9ECEF; --fg2:#BAC1C9; --mut:#8E97A1;
  --line:#2B3036; --line-ui:#616B77;
  --acc:#7FB3EC; --acc-soft:#17293C; --focus:#7FB3EC;
  --r-hi:#F2938A; --r-hi-bg:#3A2321;
  --r-md:#E3B268; --r-md-bg:#33291A;
  --r-lo:#85CBA4; --r-lo-bg:#1B2E24;
  --hl:#5C4A12; --shadow-1:none; --shadow-2:none;
  color-scheme:dark;
}
html.light{color-scheme:light}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);
  font:var(--fs-body)/1.85 var(--font-sans);-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none;overflow-wrap:anywhere}
@media (hover:hover){a:hover{text-decoration:underline;text-underline-offset:3px}}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* ================================================================
   移动优先：基础样式全部写给手机（375–430px 是主场景，微信内置浏览器）
   向上用 min-width 增强。不要反过来写"桌面 + max-width 打补丁"，
   否则 641–819px（平板/横屏/折叠屏）会落进两不管的错位区间。
   ================================================================ */
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 16px 72px}

/* ---------- 顶栏：手机两行（品牌+开关 / 搜索独占一行） ---------- */
.top{border-bottom:1px solid var(--line);background:var(--bg);
  position:sticky;top:0;z-index:20}
@supports ((backdrop-filter:blur(8px)) or (-webkit-backdrop-filter:blur(8px))){
  /* 微信部分安卓内核不支持 backdrop-filter：不写死，靠 @supports 兜底 */
  .top{background:color-mix(in srgb,var(--bg) 90%,transparent);
    backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
}
.top-in{max-width:var(--wrap);margin:0 auto;padding:8px 16px 10px;
  display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.brand{order:1;flex:1 1 auto;min-width:0;font-weight:700;font-size:15px;
  letter-spacing:-.01em;color:var(--fg);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.top .sp{display:none}
.theme{order:2;flex:none;width:44px;height:44px;border-radius:var(--radius-sm);
  border:1px solid var(--line-ui);background:var(--surface);color:var(--fg2);
  cursor:pointer;font-size:16px;line-height:1;transition:border-color 180ms,color 180ms}
@media (hover:hover){.theme:hover{border-color:var(--acc);color:var(--acc)}}
.search{order:3;flex:1 0 100%;position:relative}
.search input{width:100%;height:44px;padding:0 12px 0 36px;
  border-radius:var(--radius-sm);border:1.5px solid var(--line-ui);
  background:var(--surface);color:var(--fg);font:16px/1 var(--font-sans);
  -webkit-appearance:none;appearance:none}
/* ↑ 字号必须 ≥16px：iOS 与微信在聚焦小于 16px 的输入框时会把整页放大，版面会歪 */
.search input:focus{outline:0;border-color:var(--acc);box-shadow:0 0 0 2px var(--acc-soft)}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);
  width:16px;height:16px;stroke:var(--mut);fill:none;stroke-width:2;pointer-events:none}

/* ---------- 首屏 ---------- */
.hero{padding:22px 0 4px}
.hero h1{font-size:var(--fs-display);line-height:1.3;margin:0 0 10px;letter-spacing:-.02em}
.hero p{margin:0 0 10px;color:var(--fg2);font-size:15px;line-height:1.85;
  max-width:var(--measure)}
.hero p b{color:var(--fg)}
/* 「怎么看最快」默认收起：手机上常显会吃掉 200px+，把第一张卡推到第二屏。
   JS 在 ≥768px 时自动展开；没 JS 就是收起状态，内容仍全文在 DOM 里（可搜、可抓）。 */
details.howto{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--radius-sm);margin:16px 0 0;max-width:var(--measure)}
details.howto>summary{cursor:pointer;list-style:none;min-height:44px;padding:12px 14px;
  display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);font-weight:600;
  color:var(--fg2)}
details.howto>summary::-webkit-details-marker{display:none}
details.howto>summary::before{content:"▸";color:var(--mut);font-size:12px;flex:none;
  transition:transform 180ms ease}
details.howto[open]>summary::before{transform:rotate(90deg)}
@media (hover:hover){details.howto>summary:hover{color:var(--acc)}}
.howto-in{padding:0 14px 14px;font-size:var(--fs-sm);color:var(--fg2);line-height:1.85;
  border-top:1px dashed var(--line);margin-top:0;padding-top:12px}
.howto-in p{margin:0 0 8px}
.howto-in p:last-child{margin:0}
.howto-in b{color:var(--fg)}
/* 下载胶囊：手机上横滚一行不换行（换行会把首屏撑高） */
.dl{display:flex;flex-wrap:nowrap;gap:8px;margin:14px 0 0;overflow-x:auto;
  padding-bottom:4px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.dl::-webkit-scrollbar{display:none}
.dl a{flex:none;display:inline-flex;align-items:center;height:40px;padding:0 14px;
  border:1px solid var(--line-ui);background:var(--surface);
  border-radius:var(--radius-pill);font-size:13.5px;color:var(--fg2)}
.dl a b{color:var(--acc);font-weight:600}

/* ---------- 筛选条 ----------
   手机上把「风险/阶段/证据」三组压成一条可横滚的带子；
   否则三行堆叠会给 sticky 区带来 130px+ 的常驻高度，把内容挤没。 */
.filters{position:sticky;top:var(--hdr-h);z-index:19;background:var(--bg);
  border-bottom:1px solid var(--line);padding:8px 0;margin-bottom:10px;
  display:flex;align-items:center;gap:10px}
@supports ((backdrop-filter:blur(8px)) or (-webkit-backdrop-filter:blur(8px))){
  .filters{background:color-mix(in srgb,var(--bg) 94%,transparent);
    backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
}
.frows{flex:1 1 auto;min-width:0;display:flex;gap:14px;overflow-x:auto;
  scrollbar-width:none;-webkit-overflow-scrolling:touch}
.frows::-webkit-scrollbar{display:none}
.frow{display:flex;flex-wrap:nowrap;align-items:center;gap:6px;flex:none}
.frow>b{font-size:var(--fs-xs);color:var(--mut);font-weight:600;white-space:nowrap}
.fbtn{flex:none;height:40px;padding:0 13px;border-radius:var(--radius-pill);
  border:1px solid var(--line-ui);background:var(--surface);color:var(--fg2);
  font:600 13px/1 var(--font-sans);cursor:pointer;white-space:nowrap;
  transition:background-color 180ms,border-color 180ms,color 180ms,transform 120ms}
.fbtn:active{transform:scale(.96)}
@media (hover:hover){.fbtn:hover{border-color:var(--acc);color:var(--acc)}}
.fbtn[aria-pressed="true"]{background:var(--acc-soft);border-color:var(--acc);
  color:var(--acc);font-weight:600}
.fstat{flex:none;font-size:var(--fs-2xs);color:var(--mut);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.fstat b{color:var(--fg);font-weight:600}
.fstat a{color:var(--acc)}

/* ---------- 读者章（分类）：章首标签 + 顶部章节导航 ---------- */
.grp>h2 .chn{font:600 var(--fs-xs)/1.6 var(--font-sans);color:var(--acc);
  border:1px solid var(--acc);border-radius:var(--radius-pill);padding:1px 9px;white-space:nowrap}
.chaps{margin:14px 0 2px}
.chaps .ct{font-size:var(--fs-sm);color:var(--fg2);margin-bottom:8px}
.chaps .ct b{color:var(--fg)}
.crows{display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;padding-bottom:4px;
  scrollbar-width:none;-webkit-overflow-scrolling:touch}
.crows::-webkit-scrollbar{display:none}
.crows a{flex:none;display:inline-flex;align-items:center;gap:7px;height:40px;padding:0 13px;
  border:1px solid var(--line-ui);background:var(--surface);border-radius:var(--radius-pill);
  font-size:13.5px;color:var(--fg2)}
.crows a b{color:var(--acc);font-weight:600}
.crows a .cn{font-size:var(--fs-2xs);color:var(--mut);font-variant-numeric:tabular-nums}

/* ---------- 读者章分组 ---------- */
.grp{margin:26px 0 0}
.grp[hidden]{display:none}
.grp>h2{font-size:var(--fs-h2);margin:0 0 4px;padding-top:14px;border-top:2px solid var(--fg);
  letter-spacing:-.01em;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.grp>h2 .n{margin-left:auto;font-size:var(--fs-xs);color:var(--mut);font-weight:400}
.grp>.gd{color:var(--fg2);font-size:var(--fs-sm);margin:0 0 14px;max-width:var(--measure)}

/* ---------- 卡片 ---------- */
.card{background:var(--surface);border:1px solid var(--line);
  border-left:4px solid var(--line);border-radius:var(--radius);
  padding:16px;margin:0 0 12px;box-shadow:var(--shadow-1)}
.card[data-risk="高"]{border-left-color:var(--r-hi)}
.card[data-risk="中"]{border-left-color:var(--r-md)}
.card[data-risk="低"]{border-left-color:var(--r-lo)}
.card[hidden]{display:none}
/* 标题行：序号（左·弱）+ 标题（撑满）+ 正文编号（右挂）。
   编号从徽章行挪上来，省掉一整行，也把第一眼还给标题和「说人话」。 */
.ch{display:flex;align-items:baseline;gap:10px;margin-bottom:6px}
.ch .idx{flex:none;font:400 var(--fs-2xs)/1.6 var(--font-mono);color:var(--mut);
  font-variant-numeric:tabular-nums}
.ch h3{margin:0;flex:1;min-width:0;font-size:var(--fs-h3);line-height:1.5;font-weight:650;
  letter-spacing:-.01em}
.card-no{flex:none;font:400 var(--fs-2xs)/1.6 var(--font-mono);color:var(--mut);
  white-space:nowrap;font-variant-numeric:tabular-nums}
.perma{opacity:0;margin-left:6px;color:var(--mut);font-weight:400}
@media (hover:hover){.card:hover .perma{opacity:1}}
.bdgs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.bdg{font-size:var(--fs-xs);line-height:1.7;border-radius:var(--radius-pill);
  padding:1px 9px;border:1px solid var(--line);background:var(--bg);color:var(--fg2)}
.bdg.r-高{background:var(--r-hi-bg);border-color:transparent;color:var(--r-hi);font-weight:600}
.bdg.r-中{background:var(--r-md-bg);border-color:transparent;color:var(--r-md);font-weight:600}
.bdg.r-低{background:var(--r-lo-bg);border-color:transparent;color:var(--r-lo);font-weight:600}
.bdg.grade{background:var(--acc-soft);border-color:transparent;color:var(--acc);font-weight:600}

/* ---------- ★ 主角：说人话 ----------
   字号大于标题、底色内嵌、左侧 4px 品牌条。全站最大的正文就是它。
   不做 ::first-line 加重——中文窄屏下首行会被截成半句，反而造成断句错觉。 */
.lede{margin:0;font-size:var(--fs-lede);line-height:1.95;color:var(--fg);
  background:var(--surface-2);border-left:4px solid var(--acc);
  border-radius:var(--radius-sm);padding:16px 18px;max-width:var(--measure)}
.lede p{margin:0 0 8px}
.lede p:last-child{margin:0}

/* ---------- 折叠 ---------- */
details.fold{margin:14px 0 0;border-top:1px solid var(--line)}
details.fold>summary{cursor:pointer;list-style:none;min-height:44px;padding:10px 2px;
  font-size:var(--fs-sm);font-weight:600;color:var(--fg2);
  display:flex;align-items:center;gap:8px}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"▸";color:var(--mut);font-size:12px;flex:none;
  transition:transform 180ms ease}
details.fold[open]>summary::before{transform:rotate(90deg)}
@media (hover:hover){details.fold>summary:hover{color:var(--acc)}}
/* summary 是 flex 容器：文案必须包在一个 <span> 里，
   否则裸文本节点会被拆成多个 flex 项，窄屏换行后断在词中间。 */
details.fold>summary>span{min-width:0}
.warn{color:var(--r-hi);font-weight:600}
details.fold.ev>summary{font-weight:500;color:var(--mut)}
.fold-in{padding:2px 0 6px;max-width:var(--measure)}
.row{padding:11px 0;border-top:1px dashed var(--line)}
.row:first-child{border-top:0}
.row h4{margin:0 0 6px;font-size:var(--fs-sm);font-weight:650;color:var(--fg);
  display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.row h4 .src-name{font-size:var(--fs-2xs);font-weight:400;color:var(--mut);
  border:1px solid var(--line);border-radius:4px;padding:0 5px}
.row .body{font-size:var(--fs-body);line-height:1.9;color:var(--fg2)}
.row .body>p:first-child{margin-top:0}
.row .body>p:last-child{margin-bottom:0}
.row .body p{margin:.5em 0}
.row .body ul,.row .body ol{padding-left:1.4em;margin:.4em 0}
.row .body li{margin:.25em 0}
.row .body strong{color:var(--fg)}
.row .body blockquote{margin:.6em 0;padding:2px 0 2px 12px;
  border-left:3px solid var(--line);color:var(--mut)}
.row .body code{background:var(--surface-2);padding:1px 5px;border-radius:4px;
  font-size:.9em;font-family:var(--font-mono)}
.row .body table{border-collapse:collapse;width:100%;margin:.7em 0;font-size:14px;
  display:block;overflow-x:auto}
.row .body th,.row .body td{border:1px solid var(--line);padding:6px 9px;
  text-align:left;vertical-align:top}
.row .body th{background:var(--surface-2);font-weight:600}

/* 卡片页脚：核实凭据提到明处（信任信息该被看见，但不该占主位） */
.cfoot{margin-top:12px;padding-top:10px;border-top:1px dashed var(--line);
  font-size:var(--fs-2xs);color:var(--mut);line-height:1.7}
.cfoot p{display:inline;margin:0}
.cfoot p+p::before{content:" · ";color:var(--line-ui)}

/* ---------- 页脚与回顶 ---------- */
.foot{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);
  font-size:var(--fs-sm);color:var(--mut);line-height:1.9}
.foot a{color:var(--fg2)}
.foot code{background:var(--surface-2);padding:1px 5px;border-radius:4px;
  font-family:var(--font-mono);font-size:.92em}
.totop{position:fixed;right:16px;bottom:16px;width:44px;height:44px;border-radius:50%;
  border:1px solid var(--line-ui);background:var(--surface);color:var(--fg2);
  cursor:pointer;font-size:18px;display:none;place-items:center;
  box-shadow:var(--shadow-2);z-index:19}
.totop.on{display:grid}
mark.hit{background:var(--hl);color:inherit;border-radius:3px}

/* ================================================================
   576px：横屏手机 / 折叠屏——顶栏合并为一行
   ================================================================ */
@media (min-width:576px){
  .top-in{flex-wrap:nowrap;gap:12px}
  .brand{order:0;flex:none;font-size:16px;overflow:visible}
  .top .sp{display:block;order:0;flex:1}
  .search{order:0;flex:0 1 300px}
  .theme{order:0}
  .dl{flex-wrap:wrap;overflow:visible}
}
/* ================================================================
   768px：平板起——容器 720px、文字块限宽、筛选条回到竖排三行
   ================================================================ */
@media (min-width:768px){
  :root{--hdr-h:64px}
  .wrap{padding:0 24px 88px}
  .top-in{padding:10px 24px}
  .brand{font-size:17px}
  .hero h1{margin:0 0 12px}
  .filters{display:block;padding:10px 0 12px}
  .frows{display:block;overflow:visible;flex:none}
  .frow{flex-wrap:wrap;margin-bottom:7px}
  .fbtn{height:36px}
  .fstat{display:block;margin-top:2px}
  .card{padding:24px}
  .grp{margin:34px 0 0}
}
/* ================================================================
   1024px+：桌面——卡片 hover 抬升（只在真有 hover 的设备上启用）
   ================================================================ */
@media (min-width:1024px) and (hover:hover){
  .card{transition:transform 200ms cubic-bezier(.2,.6,.3,1),box-shadow 200ms,border-color 200ms}
  .card:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);border-color:var(--line-ui)}
}

/* ---------- 降低动效：尊重系统偏好 ---------- */
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{transition-duration:.01ms!important;animation-duration:.01ms!important;
    animation-iteration-count:1!important;scroll-behavior:auto!important}
  .card:hover{transform:none}
}

/* ---------- 打印 / 存 PDF：折叠一律展开，别把内容印丢 ---------- */
@media print{
  .top,.filters,.totop,.perma{display:none!important}
  body{background:#fff;color:#000;font-size:11pt}
  .wrap{max-width:none;padding:0}
  .card{border:1px solid #ddd;box-shadow:none;break-inside:avoid;page-break-inside:avoid}
  details.fold,details.howto{display:block}
  details.fold>.fold-in,details.howto>.howto-in{display:block!important}
  details.fold>summary::before,details.howto>summary::before{content:""}
  .frows{display:block;overflow:visible}
  .lede{background:#fff;border-left:3px solid #0b5cad}
  .ch .idx,.card-no{color:#666}
  mark.hit{background:transparent}
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
  function isDark(){
    var d=document.documentElement;
    var sysDark=window.matchMedia('(prefers-color-scheme: dark)').matches;
    return d.className==='dark' || (d.className!=='light' && sysDark);
  }
  function syncTheme(){
    if(!tb) return;
    var dark=isDark();
    // 状态不只写在视觉上：读屏用户要靠 aria 才知道当前是深还是浅
    tb.setAttribute('aria-pressed', dark?'true':'false');
    tb.textContent = dark ? '◑' : '◐';
    tb.title = tb.getAttribute('aria-label') = dark ? '当前深色，点击切换浅色' : '当前浅色，点击切换深色';
  }
  if(tb){
    tb.addEventListener('click',function(){
      document.documentElement.className = isDark() ? 'light' : 'dark';
      try{localStorage.setItem('theme', document.documentElement.className);}catch(e){}
      syncTheme();
    });
  }
  syncTheme();

  // 顶栏实测高度 → 写进 --hdr-h，供 sticky 筛选条对齐。
  // 写死像素会在字体/横竖屏变化时错位，量一次最稳。
  var topBar=document.querySelector('.top');
  function syncHdr(){
    if(topBar) document.documentElement.style.setProperty('--hdr-h', topBar.offsetHeight+'px');
  }
  syncHdr();
  window.addEventListener('resize', syncHdr, {passive:true});
  window.addEventListener('orientationchange', syncHdr, {passive:true});
  window.addEventListener('load', syncHdr);

  // 「怎么看最快」：手机上保持收起（省首屏高度），桌面自动展开（空间够）
  var ht=document.getElementById('howto');
  if(ht && window.matchMedia('(min-width:768px)').matches) ht.open=true;
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
    # 读者章（分类）：归章读 docs/HK编号对照表.md 的「读者章」列；
    # GROUPS 只给顺序与副标题（详见 build_site.GROUPS 注释）。
    for gi, (gname, gdesc) in enumerate(GROUPS, 1):
        bucket = [e for e in entries if e["group"] == gname]
        if not bucket:
            continue
        body.append(
            f'<section class="grp" id="grp-{gi}" data-group="{html.escape(gname)}">'
            f'<h2><span class="chn">第 {gi} 章</span>{html.escape(gname)}'
            f'<span class="n"></span></h2>'
            f'<p class="gd">{html.escape(gdesc)}</p>'
            + "".join(card(e, i + 1) for i, e in enumerate(bucket))
            + "</section>"
        )
        toc.append(
            f'<a href="#grp-{gi}"><b>第 {gi} 章</b>{html.escape(gname)}'
            f'<span class="cn">{len(bucket)}</span></a>'
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

    chaps = ""
    if toc:
        chaps = (
            '<nav class="chaps" aria-label="按你是谁读">'
            '<div class="ct"><b>按你是谁读</b>——'
            "全书按读者分章，只看你那一章，别的不用管</div>"
            '<div class="crows">' + "".join(toc) + "</div></nav>"
        )

    page = f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BOOK_TITLE} · {n} 条可查证的香港升学与身份决策</title>
<meta name="description" content="免费、可查证的中国香港升学与身份决策指南：{n} 条，覆盖中学插班、高考申本科、本科申硕、高才通／优才／受养人／IANG／永居，以及费用、住宿与中介招生骗局。每条只写查得到官方原文的内容。">
<meta name="theme-color" content="#0b5cad" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#121417" media="(prefers-color-scheme: dark)">
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
    <label class="sr-only" for="q">搜索条目、关键词或机构名</label>
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
    <input id="q" type="search" autocomplete="off" placeholder="搜：高才通 / 留位费 / 插班 / 学费 / 受养人">
  </div>
  <button class="theme" id="theme" aria-label="切换深浅色" title="切换深浅色">◐</button>
</div></header>

<div class="wrap" id="top">
  <div class="hero">
    <h1>{BOOK_TITLE}</h1>
    <p>一份免费、可查证、随手可转发的中国香港升学与身份决策指南。讲中学插班、高考申大学、本科申硕、高才通／优才／受养人／IANG／永居，以及费用、住宿和中介招生这类骗局。</p>
    <p>每条写明<b>要花什么、换回什么、漏掉会怎样</b>，来源只引官方文件和院校官网。已收录 <b>{n}</b> 条，A 级官方信源 {ratio}。</p>

    <!-- 手机端默认收起：常显会吃掉 200px+，把第一张卡推到第二屏。
         ≥768px 由 JS 自动展开；无 JS 时为收起，正文仍全文在 DOM 里（可搜、可抓）。 -->
    <details class="howto" id="howto">
      <summary>怎么看最快 · 怎么筛 · 不想全做也行</summary>
      <div class="howto-in">
        <p><b>先认自己：</b>全书按<b>读这本书的是谁</b>分成六章（孩子在读中小学 / 申本科 / 读国际课程 / 申硕士 / 办身份 / 防骗与通用）。<b>只看你那一章</b>，别的不用管——上面那条带子就是章节入口。</p>
        <p><b>怎么看最快</b>：每条第一块的<b>方框</b>就是「说人话」——把这一条的关键结论压成几句话，只看它就够拿主意。要核对数字、要看官方原文，再展开下面的折叠。</p>
        <p><b>不用全做</b>：这是按风险高低排好的<b>备选单</b>，不是任务清单。挑走一条就算数。</p>
        <p><b>怎么筛</b>：上面搜关键词；下面按<b>风险、决策阶段、证据等级</b>筛；按 <b>/</b> 直接跳到搜索框。<a href="#" id="foldall" data-open="0">展开全部明细</a>（PDF 打印用）。</p>
      </div>
    </details>

    <div class="dl">{dl}</div>
  </div>

  {chaps}

  <div class="filters">
    <div class="frows">
      <div class="frow"><b>风险</b>{fbtn('risk','','全部',True)}{fbtn('risk','高','高')}{fbtn('risk','中','中')}{fbtn('risk','低','低')}</div>
      <div class="frow"><b>阶段</b>{fbtn('stage','','全部',True)}{''.join(fbtn('stage',s,s) for s in STAGES)}</div>
      <div class="frow"><b>证据</b>{fbtn('grade','','全部',True)}{fbtn('grade','A','A 级官方原文')}{fbtn('grade','B','B 级')}{fbtn('grade','C','C 级')}</div>
    </div>
    <div class="fstat" id="fstat" role="status" aria-live="polite">共 <b>{n}</b> 条</div>
  </div>

  {''.join(body)}

  <div class="foot">
    <p><b>{BOOK_TITLE}</b>｜每条都由作者打开官方原文逐句核对后收录，核实记录公开在仓库 <code>docs/核实记录/</code>，包括哪些数字查不到、为什么没写。</p>
    <p>内容许可 CC BY-NC-SA 4.0：可自由转载，需署名并附仓库链接，不得商用。<br>
    作者：董老师，中国香港及海外身份与教育规划顾问｜微信 jack787300、dxw22465｜邮箱 kk2688@agent.qq.com。<br>
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
