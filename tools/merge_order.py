#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按「读者章」顺序输出产物合并计划（供 CI 生成 PDF / EPUB 的 dist/full.md）。

## 为什么需要这个脚本

单文件 HTML（阅读器）是**按读者章分组渲染**的，但 PDF / EPUB 走的是另一条路：
把 `meta/front-*.md` + `book/*.md` 顺序拼成一个线性 Markdown，再交给 pandoc。

此前是按**文件号顺序**拼（001, 002, 003 …）。结果是同一个项目里两套阅读顺序：

- 阅读器（在线版 / 单文件 HTML）：按读者章 —— 第 1 章中学插班、第 2 章申本科 …
- PDF / EPUB：按写作顺序 —— HK-019(001) 排在 HK-001(004) 前面

读者按角色来找自己那一章，翻到的却是「先写的在前」，会迷路。
本脚本让两条路**同序同标题**：章内按 HK 编号升序，章首插入章节标题与副标题。

## 单一来源

- 每条归哪一章 → `docs/HK编号对照表.md` 的「读者章」列（`build_site.load_catalog`）
- 章节顺序与副标题 → `build_site.GROUPS`
本脚本不自己维护任何分类表，避免「同一事实两处实现」。

## 输出（TSV，CI 用 while read 消费）

    CHAPTER\t第 1 章｜我孩子在读中小学\t孩子读小学 / 初中，在考虑插班去香港读中学
    FILE\tbook/031-受养人签证子女考港校联招居港规定怎么算.md
    ...

## 用法

    python3 tools/merge_order.py                    # 只列文件路径（按读者章顺序）
    python3 tools/merge_order.py --with-chapters     # 附 CHAPTER 行（CI 用）
    python3 tools/merge_order.py --check             # 只做校验，退出码非 0 表示有问题
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import GROUP_NAMES, GROUPS, ROOT, UNGROUPED, group_of, load_catalog  # noqa: E402

BOOK = os.path.join(ROOT, "book")
RE_TITLE_HK = re.compile(r"^#\s+(HK-\d{3})\s")


def collect() -> list[dict]:
    """[{file, hk, chapter}]，按「读者章顺序 → 章内 HK 编号升序」排好。"""
    catalog = load_catalog()
    rows = []
    for name in sorted(f for f in os.listdir(BOOK) if f.endswith(".md") and f[:3].isdigit()):
        text = open(os.path.join(BOOK, name), encoding="utf-8").read()
        m = RE_TITLE_HK.match(text.split("\n", 1)[0])
        hk = m.group(1) if m else ""
        track = catalog.get(hk, {}).get("track", "")
        rows.append({"file": f"book/{name}", "hk": hk, "chapter": group_of(track)})

    def sort_key(r: dict):
        gname = r["chapter"]
        names = [g for g, _ in GROUPS]
        gi = names.index(gname) if gname in names else len(names)
        num = int(r["hk"][3:]) if re.fullmatch(r"HK-\d{3}", r["hk"]) else 999
        return (gi, num, r["file"])

    return sorted(rows, key=sort_key)


def main() -> int:
    ap = argparse.ArgumentParser(description="按读者章输出合并顺序")
    ap.add_argument("--with-chapters", action="store_true", help="附 CHAPTER 行（CI 用）")
    ap.add_argument("--check", action="store_true", help="只校验分类，不输出合并计划")
    args = ap.parse_args()

    rows = collect()
    if not rows:
        print("book/ 里没有条目", file=sys.stderr)
        return 1

    # 分类问题（未登记 / 读者章取值非法）**只报告，不中断合并**——
    # 与 tools/check.py 同一条设计原则：`set -e` + `exit 1` 在这里会卡住
    # **整本书**的发布，只因某条新条目忘了登记分类，代价不对等。
    # 处理办法：把可疑条目放进末尾的「未归类（待修）」章——不静默丢，
    # 产物里一眼能看见，check.py 的 chapters 项同时报错。
    bad = [r for r in rows if r["chapter"] == UNGROUPED]
    unassigned = [r for r in rows if not r["hk"]]
    for r in unassigned:
        print(f"::warning::{r['file']} 首行不是「# HK-nnn 标题」，无法确定读者章", file=sys.stderr)
    for r in bad:
        print(
            f"::warning::{r['hk']}（{r['file']}）在对照表里没有合法的「读者章」取值，"
            f"暂放「未归类（待修）」；合法取值：{' / '.join(GROUP_NAMES)}",
            file=sys.stderr,
        )
    if args.check:
        if bad or unassigned:
            return 1
        print(f"[通过] {len(rows)} 条全部归入合法读者章", file=sys.stderr)
        return 0

    out = []
    for gi, (gname, gdesc) in enumerate(GROUPS, 1):
        bucket = [r for r in rows if r["chapter"] == gname]
        if not bucket:
            continue
        if args.with_chapters:
            out.append(f"CHAPTER\t第 {gi} 章｜{gname}\t{gdesc}")
        for r in bucket:
            out.append(f"FILE\t{r['file']}")

    # 未归类的兜底：**绝不静默丢条目**，单独成章让它在产物里可见
    if bad or unassigned:
        if args.with_chapters:
            out.append(
                "CHAPTER\t未归类（待修）\t"
                "这些条目还没在 docs/HK编号对照表.md 里登记合法的「读者章」，先放在这里"
            )
        for r in bad + unassigned:
            out.append(f"FILE\t{r['file']}")

    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    # newline="\n" 必须有：Windows 上文本模式会把 "\n" 翻成 "\r\n"，
    # 下游 `read -r` 拿到带 \r 的文件名会「文件不存在」（2026-10-07 实测踩到）。
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main())
