#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键词映射表渲染器（《董老师香港留学指南2026》）
================================================
单一来源：meta/seo-keywords.json。本脚本只做两件事——
  1) 校验：JSON 的 slug 与 book/ 目录条目一一对应（多一个少一个都报错）；
  2) 渲染：输出给董老师审阅的 Markdown 表格，以及给生成器消费的紧凑结构。

用法：
    python tools/render_seo_table.py [--json meta/seo-keywords.json]
                                     [--out 关键词映射表.md]
"""
import os
import re
import io
import sys
import json
import glob
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

RE_ID = re.compile(r"HK-(\d{3})")


def book_ids():
    """从 book/ 解析出全部条目 slug → 标题（slug 与站点 URL 一致：hk-0xx）。"""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "book", "*.md"))):
        txt = io.open(f, encoding="utf-8").read()
        m = re.search(r"^#\s+(HK-\d{3})\s+(.+)$", txt, re.M)
        if not m:
            print("  [warn] 未解析到编号/标题：%s" % os.path.basename(f), file=sys.stderr)
            continue
        out[m.group(1).lower()] = m.group(2).strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(ROOT, "meta", "seo-keywords.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "关键词映射表.md"))
    a = ap.parse_args()

    data = json.load(io.open(a.json, encoding="utf-8"))
    entries = data["entries"]
    hubs = data["hubs"]
    ids = book_ids()

    missing = sorted(set(ids) - set(entries))
    extra = sorted(set(entries) - set(ids))
    if missing or extra:
        print("✗ 校验失败：书稿 %d 条 / 词表 %d 条" % (len(ids), len(entries)))
        if missing:
            print("  词表缺：%s" % "、".join(missing))
        if extra:
            print("  词表多（书稿无此条）：%s" % "、".join(extra))
        return 1

    by_hub = {}
    for slug, e in entries.items():
        by_hub.setdefault(e["hub"], []).append(slug)

    lines = []
    lines.append("# 《董老师香港留学指南2026》关键词映射表")
    lines.append("")
    lines.append("生成：`tools/render_seo_table.py`（单一来源 `meta/seo-keywords.json`）· 2026-10-10")
    lines.append("")
    lines.append("**校验**：书稿 %d 条 ↔ 词表 %d 条，一一对应 ✓" % (len(ids), len(entries)))
    lines.append("")
    lines.append("## 一、聚合页（hub）总览")
    lines.append("")
    lines.append("| 聚合页 | 主词 | 覆盖条目 | 长尾词 |")
    lines.append("| --- | --- | --- | --- |")
    for h, meta in hubs.items():
        n = len(by_hub.get(h, []))
        lines.append("| %s（%s） | %s | %d 条 | %s |"
                     % (meta["title"], h, meta["k"], n, "／".join(meta["lt"])))
    lines.append("")
    lines.append("## 二、逐条映射（按条目编号排序）")
    lines.append("")

    for h, meta in hubs.items():
        slugs = sorted(by_hub.get(h, []), key=lambda s: int(s.split("-")[1]))
        lines.append("### %s　`%s`　%d 条" % (meta["title"], h, len(slugs)))
        lines.append("")
        lines.append("| 编号 | 原条目标题 | 主搜索词 | 长尾词 | 建议 SEO 标题 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for s in slugs:
            e = entries[s]
            lines.append("| %s | %s | %s | %s | %s |"
                         % (s.upper(), ids[s], e["k"], "／".join(e["lt"]), e["t"]))
        lines.append("")

    txt = "\n".join(lines) + "\n"
    io.open(a.out, "w", encoding="utf-8").write(txt)
    print("✓ 校验通过：%d 条，全部命中" % len(entries))
    print("✓ 已写出：%s（%d 行）" % (a.out, txt.count("\n")))
    for h, meta in hubs.items():
        print("    %-10s %d 条" % (h, len(by_hub.get(h, []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
