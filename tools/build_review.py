# -*- coding: utf-8 -*-
"""生成「审阅清单」单页 —— 把面向读者的文件（book/ 条目 + meta/ 前置章节 + README）
汇总成一页，供董老师逐条审阅。

设计原则：
- 只读 book/ 与 meta/，不新增、不改动任何事实（与 build_site.py 同）。
- 不产出到 site/（site/ 是对外发布目录，审阅清单属内部件，不得上线）。
- 「待审 / 已审」按正文里是否已落 `本条最后更新` 字段判定（2026-10-07 前按已移除的原署名判定，
  该署名已按 026 A 项全库移除），不靠人工维护的清单。

用法：
    python tools/build_review.py --out <输出html路径>
"""
import argparse
import glob
import html
import os
import re
import sys

try:
    import markdown
except ImportError:  # pragma: no cover
    print("需要 markdown 库：pip install markdown", file=sys.stderr)
    raise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
META = os.path.join(ROOT, "meta")
README = os.path.join(ROOT, "README.md")

RE_TITLE = re.compile(r"^#\s+(HK-\d{3})\s+(.+?)\s*$", re.M)
RE_RISK = re.compile(r"<!--\s*风险\s*=\s*(\S+)\s+阶段\s*=\s*(\S+)\s+焦虑\s*=\s*(\S+?)\s*-->")
RE_GRADE = re.compile(r"证据等级\*{0,2}\s*[:：]\s*\*{0,2}\s*([ABC])")

FIELDS = ["说人话", "要花什么", "换回什么", "红线提醒", "常见误传",
          "适用人群 + 入学年度", "解决什么焦虑 + 风险等级 + 决策阶段",
          "关键节点与时效", "证据等级 + 官方依据", "本条最后更新", "官方尚未公布／未写死的事项"]


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def split_field(text, name):
    """取某个 **字段** 到下一个 **字段** 之间的内容。"""
    m = re.search(r"^\*\*" + re.escape(name) + r"\*\*\s*$", text, re.M)
    if not m:
        return ""
    start = m.end()
    nxt = None
    for f in FIELDS:
        if f == name:
            continue
        m2 = re.search(r"^\*\*" + re.escape(f) + r"\*\*\s*$", text[start:], re.M)
        if m2 and (nxt is None or m2.start() < nxt):
            nxt = m2.start()
    body = text[start:start + nxt] if nxt is not None else text[start:]
    # 去掉尾部脚注分隔线
    body = re.split(r"\n---\n", body)[0]
    return body.strip()


def first_sentences(md_text, limit=300):
    """从「说人话」里取前两段，作为一句话结论。"""
    t = md_text.strip()
    # 去掉 markdown 强调标记，保留文字
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    plain = re.sub(r"`(.+?)`", r"\1", plain)
    paras = [p.strip() for p in plain.split("\n\n") if p.strip()]
    out = []
    for p in paras:
        out.append(p)
        if sum(len(x) for x in out) >= limit:
            break
    s = "\n\n".join(out)
    return s[:limit] + ("…" if len(s) > limit else "")


def bullet_count(md_text):
    return len(re.findall(r"^[-*]\s+", md_text, re.M)) + len(re.findall(r"^\d+\.\s+", md_text, re.M))


def link_count(md_text):
    return len(re.findall(r"<https?://", md_text)) + len(re.findall(r"\]\(https?://", md_text))


def parse_entry(path):
    text = read(path)
    name = os.path.basename(path)
    mt = RE_TITLE.search(text)
    mr = RE_RISK.search(text)
    mg = RE_GRADE.search(text)
    # 2026-10-07（026 A 项）：全库移除原署名后原判据消失，改用「本条最后更新」字段是否落地。
    signed = bool(re.search(r"本条最后更新", text))
    d = {
        "file": name,
        "no": int(name[:3]),
        "hk": mt.group(1) if mt else "HK-???",
        "title": mt.group(2) if mt else name,
        "risk": mr.group(1) if mr else "-",
        "stage": mr.group(2) if mr else "-",
        "anxiety": mr.group(3) if mr else "-",
        "grade": mg.group(1) if mg else "-",
        "chars": len(re.sub(r"\s", "", text)),
        "signed": signed,
        "lede": first_sentences(split_field(text, "说人话")),
        "pitfalls": split_field(text, "常见误传"),
        "pitfalls_n": bullet_count(split_field(text, "常见误传")),
        "pending": split_field(text, "官方尚未公布／未写死的事项"),
        "pending_n": bullet_count(split_field(text, "官方尚未公布／未写死的事项")),
        "sources": link_count(split_field(text, "证据等级 + 官方依据")),
        "body_md": text,
    }
    return d


def badge(label, val, cls=""):
    if not val or val == "-":
        return ""
    return f'<span class="b {cls}">{html.escape(label)} {html.escape(val)}</span>'


def render_entry(e, idx):
    md = markdown.markdown(e["body_md"], extensions=["tables", "fenced_code", "sane_lists"])
    lede = html.escape(e["lede"]).replace("\n\n", "<br><br>")
    pending = markdown.markdown(e["pending"], extensions=["sane_lists"]) if e["pending"] else "<p>（无）</p>"
    tag = ('<span class="tag todo">待审</span>' if not e["signed"]
           else '<span class="tag done">已署「董老师复核」</span>')
    return f"""
<article class="card" id="e{idx}">
  <header>
    <div class="h"><span class="hk">{e['hk']}</span><h3>{html.escape(e['title'])}</h3></div>
    <div class="meta">{tag}
      {badge('等级', e['grade'], 'g' + e['grade'])}
      {badge('风险', e['risk'])}
      {badge('阶段', e['stage'])}
      {badge('焦虑', e['anxiety'])}
      <span class="b">{e['chars']} 字</span>
      <span class="b">出处 {e['sources']}</span>
      <span class="b">官方未定 {e['pending_n']}</span>
      <span class="b">误传 {e['pitfalls_n']}</span>
    </div>
  </header>
  <div class="body">
    <div class="sec"><b>一句话结论</b><p class="lede">{lede}</p></div>
    <div class="sec"><b>本条标了「官方尚未公布」的（{e['pending_n']}）</b>{pending}</div>
    <details><summary>读全文（{e['chars']} 字）</summary><div class="full">{md}</div></details>
  </div>
  <footer><span class="path">book/{html.escape(e['file'])}</span></footer>
</article>"""


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f4f6f9;color:#1d2129;
 font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 6px}
.sub{color:#5b6676;margin:0 0 20px}
.stat{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 8px}
.stat div{background:#fff;border:1px solid #e3e8ef;border-radius:10px;padding:10px 16px;min-width:104px}
.stat b{display:block;font-size:22px;color:#12406e}
.stat span{color:#6b7686;font-size:12.5px}
.note{background:#fffbe8;border:1px solid #f0dfa8;border-radius:10px;padding:14px 18px;margin:18px 0 26px}
.note h4{margin:0 0 6px;font-size:15px}
.note p,.note li{margin:4px 0;color:#4a4327;font-size:14px}
ul.prio{margin:8px 0 2px;padding-left:20px}
ul.prio li{margin:5px 0}
ul.prio a{color:#12406e;font-weight:600;text-decoration:none}
ul.prio a:hover{text-decoration:underline}
ul.prio .why{display:block;color:#7a7250;font-size:12.5px}
h2.grp{font-size:19px;margin:34px 0 4px;padding-bottom:8px;border-bottom:2px solid #12406e}
h2.grp small{font-weight:400;color:#6b7686;font-size:13px;margin-left:8px}
.card{background:#fff;border:1px solid #e3e8ef;border-radius:12px;padding:16px 20px;margin:14px 0}
.card header .h{display:flex;align-items:baseline;gap:10px}
.card h3{font-size:17px;margin:0;line-height:1.5}
.hk{font-family:ui-monospace,Consolas,monospace;color:#12406e;font-weight:700;font-size:14px;white-space:nowrap}
.meta{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 2px}
.b{background:#eef2f7;color:#40506a;border-radius:6px;padding:2px 9px;font-size:12.5px}
.b.gA{background:#e6f4ea;color:#1e7a3c}.b.gB{background:#fff4e0;color:#9a6100}.b.gC{background:#fdeaea;color:#a52121}
.tag{border-radius:6px;padding:2px 10px;font-size:12.5px;font-weight:600}
.tag.todo{background:#fdeaea;color:#a52121}
.tag.done{background:#e6f4ea;color:#1e7a3c}
.body .sec{margin:12px 0}
.body .sec>b{display:block;font-size:13px;color:#6b7686;margin-bottom:4px}
.lede{margin:0;background:#f7f9fc;border-left:3px solid #12406e;padding:10px 14px;border-radius:0 8px 8px 0}
.body ul,.body ol{margin:6px 0;padding-left:22px}
details{margin-top:10px;border-top:1px dashed #e3e8ef;padding-top:10px}
summary{cursor:pointer;color:#12406e;font-weight:600;font-size:14px}
.full{margin-top:10px;background:#fbfcfe;border:1px solid #eef1f5;border-radius:8px;padding:6px 18px}
.full h1{font-size:19px}.full h2{font-size:16px}.full h3{font-size:15px}
.full code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:13px}
.full a{color:#12406e}
.card footer{margin-top:10px}
.path{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#93a0b2}
.top{position:sticky;top:0;background:#f4f6f9ee;backdrop-filter:blur(6px);padding:10px 0;border-bottom:1px solid #e3e8ef;margin-bottom:6px}
.top a{color:#12406e;text-decoration:none;font-size:13.5px;margin-right:16px}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "审阅清单.html"))
    args = ap.parse_args()

    files = sorted([f for f in glob.glob(os.path.join(BOOK, "*.md"))
                    if os.path.basename(f)[:3].isdigit()])
    entries = [parse_entry(f) for f in files]
    todo = [e for e in entries if not e["signed"]]
    done = [e for e in entries if e["signed"]]

    fronts = sorted(glob.glob(os.path.join(META, "front-*.md")))
    front_cards = []
    for fp in fronts:
        t = read(fp)
        mt = re.search(r"^#\s+(.+?)\s*$", t, re.M)
        title = mt.group(1) if mt else os.path.basename(fp)
        md = markdown.markdown(t, extensions=["tables", "fenced_code", "sane_lists"])
        n = len(re.sub(r"\s", "", t))
        front_cards.append(f"""<article class="card">
  <header><div class="h"><span class="hk">前置</span><h3>{html.escape(title)}</h3></div>
  <div class="meta"><span class="b">{n} 字</span><span class="b">面向读者</span></div></header>
  <div class="body"><details><summary>读全文（{n} 字）</summary><div class="full">{md}</div></details></div>
  <footer><span class="path">meta/{html.escape(os.path.basename(fp))}</span></footer>
</article>""")

    readme_md = markdown.markdown(read("README.md"), extensions=["tables", "fenced_code", "sane_lists"])
    readme_n = len(re.sub(r"\s", "", read(README)))

    tot_chars = sum(e["chars"] for e in entries)

    # 建议优先看：取证难度最高的三类（等级非 A / 官方未定最多 / 篇幅最长）
    prio = []
    for e in sorted([x for x in todo if x["grade"] != "A"], key=lambda x: x["grade"]):
        prio.append((f"{e['grade']} 级", e, "证据等级非 A：部分结论依赖非官方口径或旁证"))
    for e in sorted(todo, key=lambda x: -x["pending_n"])[:5]:
        prio.append((f"官方未定 {e['pending_n']} 项", e, "官方没给或没取到，需你判断口径是否可接受"))
    for e in sorted(todo, key=lambda x: -x["chars"])[:4]:
        prio.append((f"{e['chars']} 字", e, "篇幅最长，信息密度最高"))
    seen = set()
    prio_rows = []
    for tagtxt, e, why in prio:
        if e["no"] in seen:
            continue
        seen.add(e["no"])
        prio_rows.append(
            f'<li><a href="#e{todo.index(e)}"><b>{e["hk"]}</b> {html.escape(e["title"])}</a>'
            f'<span class="why">{html.escape(tagtxt)} · {html.escape(why)}</span></li>'
        )
    prio_html = ("<h4>建议优先看的这几条</h4><ul class=\"prio\">"
                 + "".join(prio_rows) + "</ul>") if prio_rows else ""

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>审阅清单 · 董老师香港留学指南</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>审阅清单 · 董老师香港留学指南</h1>
<p class="sub">面向读者的全部文件汇总 · 生成于 2026-10-07 · 共 {len(entries)} 条正文 + {len(front_cards)} 页前置 + README 1 份</p>

<div class="stat">
  <div><b>{len(entries)}</b><span>正文条目</span></div>
  <div><b style="color:#a52121">{len(todo)}</b><span>待你审（新写）</span></div>
  <div><b style="color:#1e7a3c">{len(done)}</b><span>已署「董老师复核」</span></div>
  <div><b>{len(front_cards)}</b><span>前置章节</span></div>
  <div><b>{tot_chars//10000} 万</b><span>正文总字数</span></div>
</div>

<div class="note">
  <h4>怎么审（约 10 分钟可扫完）</h4>
  <ul>
    <li><b>先看「待你审」{len(todo)} 条</b>——这是我新写的、尚未署名「董老师复核」的稿子。</li>
    <li>每条卡片给你三样：<b>一句话结论</b>（这条到底在说什么）、<b>本条标了「官方尚未公布」的地方</b>（我没能拿到官方原文、或官方本身不公布的）、<b>徽章</b>（证据等级 / 风险 / 阶段 / 出处数 / 误传数）。</li>
    <li>想细看，点每条下方「<b>读全文</b>」——正文就在卡片里，不用跳文件。</li>
    <li><b>「已署『董老师复核』」{len(done)} 条</b>是 WB4 已审过的，抽验即可，不必逐条重读。</li>
    <li>审完把「<b>哪几条要改、改什么</b>」告诉我即可，我按你的意见改，改完再回 WB4 复核。</li>
  </ul>
  {prio_html}
</div>

<div class="top"><a href="#todo">▸ 待你审 {len(todo)} 条</a><a href="#done">▸ 已审 {len(done)} 条</a><a href="#front">▸ 前置章节 {len(front_cards)} 页</a><a href="#readme">▸ README</a></div>

<h2 class="grp" id="todo">① 待你审（新写 · {len(todo)} 条）<small>重点看这一组</small></h2>
{''.join(render_entry(e, i) for i, e in enumerate(todo))}

<h2 class="grp" id="done">② 已署「董老师复核」（WB4 已审 · {len(done)} 条）<small>抽验即可</small></h2>
{''.join(render_entry(e, 1000 + i) for i, e in enumerate(done))}

<h2 class="grp" id="front">③ 书级前置章节（{len(front_cards)} 页）<small>导语 / 术语 / 证据 / 读法 / 免责 / 风险分档 / 条目示例</small></h2>
{''.join(front_cards)}

<h2 class="grp" id="readme">④ README（{readme_n} 字）<small>仓库门面，也是读者第一眼</small></h2>
<article class="card"><div class="body"><details open><summary>读全文</summary><div class="full">{readme_md}</div></details></div>
<footer><span class="path">README.md</span></footer></article>

</div></body></html>"""

    out = args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"审阅清单已生成：{out}")
    print(f"  正文 {len(entries)} 条（待审 {len(todo)} / 已审 {len(done)}）"
          f"｜ 前置 {len(front_cards)} 页 ｜ README 1")
    print(f"  正文总字数 {tot_chars}")


if __name__ == "__main__":
    main()
