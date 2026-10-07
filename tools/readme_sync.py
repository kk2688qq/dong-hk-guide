#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""README 自动回填（WB4 017 阶段 1「止血」）

问题（028 实测）：README 写着「已收录 3 条 / 全部为 A 级」，实际已是 18 条、A 级 78%
——**双重漂移**（条数 + 等级），且目录表只列 3 条。根因：README 靠人手改，没人改就烂。

处理：把 README 里三块「机器可判定」的内容，按 `book/` 实际内容重写——
  1) 状态行（最后更新 / 已收录 N 条 / A 级 x% / 待核实项）
  2) 章节导览（按你是谁读：六章各含哪几条 —— 归章读对照表「读者章」列，2026-10-07 加）
  3) 目录表（HK 编号 | 条目 | 证据 | 最后核对）

由 CI（`.github/workflows/book.yml`）在每次 push 后执行并回提交。
**只在 markers 之间改写，markers 之外一个字不动。**

机器验收（017 判据）：
  README 条数      ==  ls book/*.md | wc -l
  README A 级百分比 ==  脚本算出的值
  README 章节导览   ==  对照表「读者章」列的分组结果（六章合计 == 总条数）

用法：
    python tools/readme_sync.py            # 回填
    python tools/readme_sync.py --check    # 只校验是否已同步（未同步则退出码 1）
"""

import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import GROUPS, group_of, load_catalog  # noqa: E402  （单一来源：读者章）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
README = os.path.join(ROOT, "README.md")
LLMS = os.path.join(ROOT, "llms.txt")

RE_TITLE_HK = re.compile(r"^#\s+(HK-\d{3})\s+(.+)$")
RE_EVIDENCE = re.compile(r"证据等级\*{0,2}\s*[:：]\s*\*{0,2}\s*([ABC])")
RE_REVIEWED = re.compile(r"最后核实日期\*{0,2}\s*[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})")

STATUS_START = "<!-- README:STATUS:START -->"
STATUS_END = "<!-- README:STATUS:END -->"
TOC_START = "<!-- README:TOC:START -->"
TOC_END = "<!-- README:TOC:END -->"
LEAD_START = "<!-- README:LEAD:START -->"
LEAD_END = "<!-- README:LEAD:END -->"
CHAPS_START = "<!-- README:CHAPTERS:START -->"
CHAPS_END = "<!-- README:CHAPTERS:END -->"



def entries():
    if not os.path.isdir(BOOK):
        return []
    return sorted(f for f in os.listdir(BOOK) if f.endswith(".md") and f[:3].isdigit())


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def collect():
    """返回 [{hk, num, title, link, level, reviewed, a, chapter}]"""
    catalog = load_catalog()
    rows = []
    for name in entries():
        text = read(os.path.join(BOOK, name))
        first = text.split("\n", 1)[0]
        m = RE_TITLE_HK.match(first)
        hk = m.group(1) if m else "—"
        title = m.group(2).strip() if m else first.lstrip("# ").strip()
        # 去掉标题里可能出现的「：…」之外的多余空白
        title = re.sub(r"\s+", " ", title)
        me = RE_EVIDENCE.search(text)
        level = me.group(1) if me else "?"
        mr = RE_REVIEWED.search(text)
        reviewed = mr.group(1) if mr else "—"
        link = "./book/" + name
        chapter = group_of(catalog.get(hk, {}).get("track", ""))
        rows.append({
            "hk": hk, "num": name[:3], "title": title, "link": link,
            "level": level, "reviewed": reviewed, "a": level == "A",
            "chapter": chapter,
        })
    return rows


def render_lead(rows, today=None):
    """README 顶部导语——**条数由脚本回填**，避免「README 说 45 条、实际 46 条」这类漂移。"""
    n = len(rows)
    return (
        f"{LEAD_START}\n"
        f"> 一份**免费、可查证、随手可转发**的中国香港升学与身份决策指南。讲**中学插班、高考申大学、本科申硕、"
        f"高才通／优才／受养人／IANG／永居**，以及费用、住宿和「保录」「内推」这类骗局。**已收录 {n} 条**（持续增加）。\n"
        f"> **每条**写明**花掉什么、换回什么、漏掉会怎样、官方依据是什么**；来源**只引官方文件和院校官网**。\n"
        f"> **不用全做**：这是按**风险高低**排好的**备选单**，不是任务清单——**挑走一条就算数**。\n"
        f"{LEAD_END}"
    )


def render_status(rows, today=None):
    n = len(rows)
    a = sum(1 for r in rows if r["a"])
    pct = round(a / n * 100) if n else 0
    today = today or date.today().isoformat()
    return (
        f"{STATUS_START}\n"
        f"**最后更新：{today} ｜ 已收录：{n} 条 ｜ A 级官方信源 {pct}% ｜ "
        f"待核实项：公开显示在各条目内**\n"
        f"{STATUS_END}"
    )


def render_toc(rows):
    # 按 HK 编号数值升序（读者视角；HK-002 排在 HK-019 之前）
    def key(r):
        m = re.search(r"(\d+)$", r["hk"])
        return (0, int(m.group(1))) if m else (1, r["num"])
    out = [
        TOC_START,
        "| HK 编号 | 条目 | 证据 | 最后核对 |",
        "| --- | --- | --- | --- |",
    ]
    for r in sorted(rows, key=key):
        out.append(f"| {r['hk']} | [{r['title']}]({r['link']}) | {r['level']} | {r['reviewed']} |")
    out.append(TOC_END)
    return "\n".join(out)


def render_chapters(rows):
    """「按你是谁读」章节导览——**章节归属由脚本回填**，杜绝「README 说 5 章、实际 6 章」漂移。

    归章读 docs/HK编号对照表.md 的「读者章」列，章序与副标题读 tools/catalog.py 的 GROUPS。
    读者先认自己（张三是来看本科的、李四是来看申硕的），只看自己那一章。
    """
    def hk_key(r):
        m = re.search(r"(\d+)$", r["hk"])
        return (0, int(m.group(1))) if m else (1, r["num"])

    out = [
        CHAPS_START,
        "**先认自己**：全书按**读这本书的是谁**分成六章。找到你那一行，点 HK 编号直接看——别的章不用管。",
        "",
        "| 章 | 这一章是给谁的 | 包含条目（点编号直接看） |",
        "| --- | --- | --- |",
    ]
    counts = []
    for gi, (gname, gdesc) in enumerate(GROUPS, 1):
        bucket = sorted([r for r in rows if r["chapter"] == gname], key=hk_key)
        if not bucket:
            continue
        counts.append(f"第 {gi} 章 {len(bucket)} 条")
        links = " · ".join(f"[{r['hk']}]({r['link']})" for r in bucket)
        out.append(f"| **第 {gi} 章 · {gname}** | {gdesc} | {links} |")
    rest = sorted([r for r in rows if r["chapter"] not in [g for g, _ in GROUPS]], key=hk_key)
    if rest:  # 理论上不该出现（check.py 会拦），但绝不静默丢条目
        links = " · ".join(f"[{r['hk']}]({r['link']})" for r in rest)
        out.append(f"| **未归章**（待修） | —— | {links} |")
    out += [
        "",
        f"> 合计 **{len(rows)} 条**（{' ｜ '.join(counts)}）。**一条只归一章**，"
        "章归属由 `docs/HK编号对照表.md` 的「读者章」列决定，本表由 CI 自动回填、不手改。",
        CHAPS_END,
    ]
    return "\n".join(out)


def replace_block(text, start, end, new):
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pat.search(text):
        raise SystemExit(f"README 缺少标记对：{start} … {end}（请先在 README 里补上）")
    return pat.sub(lambda _: new, text, count=1)


def render_llms(rows, today=None):
    """生成 llms.txt（llmstxt.org 约定）——「AI 可读层」的零成本部分（WB4 017 阶段 2）。

    供 AI 联网检索 / 导入时快速定位：项目是什么、有哪些条目、依据与纠错在哪。
    """
    today = today or date.today().isoformat()
    n = len(rows)
    base = "https://github.com/kk2688qq/dong-hk-guide"
    out = [
        "# 董老师香港留学指南（Dong's Hong Kong Study Guide）",
        "",
        "> 一份免费、可查证、随手可转发的中国香港升学与身份决策指南。每条统一回答四个问题："
        "花掉什么、换回什么、漏掉会怎样、官方依据是什么。只写查得到官方原文的内容。",
        "",
        f"面向中国内地家庭：中学择校插班 / 高考生申请港校本科 / 本科申硕 / 身份规划。"
        f"**范围仅中国香港**，不含其他地区。共 {n} 条，更新于 {today}。",
        "",
        "证据分级：**A**＝官方原文（入境处、教育局、教资会、联招处、考评局、大学官网、"
        "香港法例库、政府新闻公报）；**B**＝官方二手（统计报告 / 问答页）；**C**＝作者经验（显式标注）。"
        "查不到原文的数字一律标「待核实」，不凭记忆填。",
        "",
        "## 指南全文",
        "",
        "- [README（总览 + 全量目录 + 怎么用）](./README.md)",
        "- [book/（全部条目正文，Markdown）](./book/)",
        "- 单文件下载（链接永久指向最新版）：",
        f"  - HTML：{base}/releases/download/book-latest/HKStudyGuide.html",
        f"  - PDF：{base}/releases/download/book-latest/HKStudyGuide.pdf",
        f"  - EPUB：{base}/releases/download/book-latest/HKStudyGuide.epub",
        "",
        f"## 条目（{n} 条）",
        "",
    ]

    def key(r):
        m = re.search(r"(\d+)$", r["hk"])
        return (0, int(m.group(1))) if m else (1, r["num"])

    for r in sorted(rows, key=key):
        out.append(f"- [{r['hk']} {r['title']}]({r['link']})（证据 {r['level']}，最后核对 {r['reviewed']}）")
    out += [
        "",
        "## 核实与纠错",
        "",
        "- 每条含「常见误传」（网络流传说法 ↔ 官方原文对照）与「最后核实日期 + 核实人」。",
        "- [核实记录 ./docs/核实记录/](./docs/核实记录/)——每个数字出自哪份官方文件，含刻意未写死的项与原因。",
        "- [纠错台账 ./docs/纠错台账.md](./docs/纠错台账.md)——被质疑过、核查过、修正过或被驳回的记录（只追加）。",
        "- 发现问题：在本仓库开 issue，或微信 **jack787300**。",
        "",
        "## Optional",
        "",
        "- [CLAUDE.md（写作与维护规则 / 判例集）](./CLAUDE.md)",
        "- [GITHUB发布操作手册.md](./GITHUB发布操作手册.md)",
        "",
    ]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="README 自动回填")
    ap.add_argument("--check", action="store_true", help="只校验，不回写")
    args = ap.parse_args()

    rows = collect()
    if not rows:
        raise SystemExit("book/ 里没有条目，README 不回填。")

    text = read(README)
    new = replace_block(text, LEAD_START, LEAD_END, render_lead(rows))
    new = replace_block(new, STATUS_START, STATUS_END, render_status(rows))
    new = replace_block(new, CHAPS_START, CHAPS_END, render_chapters(rows))
    new = replace_block(new, TOC_START, TOC_END, render_toc(rows))

    llms = render_llms(rows)
    llms_old = read(LLMS) if os.path.isfile(LLMS) else None

    n = len(rows)
    a = sum(1 for r in rows if r["a"])
    print(f"book/ 条目数：{n} ｜ A 级：{a}（{round(a/n*100)}%）")

    if args.check:
        ok = (new == text) and (llms_old == llms)
        if ok:
            print("[通过] README 与 llms.txt 均与 book/ 一致")
            return 0
        if new != text:
            print("[不同步] README 与 book/ 不一致（跑一次 tools/readme_sync.py 回填）")
        if llms_old != llms:
            print("[不同步] llms.txt 与 book/ 不一致（跑一次 tools/readme_sync.py 回填）")
        return 1

    changed = []
    if new != text:
        with open(README, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        changed.append("README.md")
    if llms_old != llms:
        with open(LLMS, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(llms)
        changed.append("llms.txt")
    print(f"[回填] {'、'.join(changed)}" if changed else "[无变化] README / llms.txt 均已同步")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
