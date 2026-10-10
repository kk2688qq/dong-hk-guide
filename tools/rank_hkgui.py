#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
条目访问排行榜（《董老师香港留学指南2026》自有域名站）
=====================================================
读服务器上 kb-api 的计数（GET /api/stats），只看本指南站的键（hg- 前缀），
按条目/聚合页分组排出榜单。给董老师看「哪些条目真有人搜、真有人读」。

用法：
    python tools/rank_hkgui.py                 # 打榜单到终端
    python tools/rank_hkgui.py --out 排行.md    # 同时写文件
    python tools/rank_hkgui.py --top 20
"""
import os
import io
import sys
import json
import argparse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.environ.get("HKGUI_STATS_URL", "http://43.132.236.108/api/stats")
HOST_HEADER = os.environ.get("HKGUI_HOST", "hkgui.xinfide.com")


def fetch_stats():
    req = urllib.request.Request(API, headers={"Host": HOST_HEADER})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def load_titles():
    """slug → 条目标题 / 聚合页标题（来自关键词表，单一来源）。"""
    p = os.path.join(ROOT, "meta", "seo-keywords.json")
    data = json.load(io.open(p, encoding="utf-8"))
    t = {}
    for slug, e in data["entries"].items():
        t["hg-" + slug] = e["t"]
    for hs, h in data["hubs"].items():
        t["hg-hub-" + hs] = h["title"]
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--top", type=int, default=0, help="只列前 N 条（0＝全部）")
    a = ap.parse_args()

    counts = fetch_stats().get("counts", {})
    mine = {k: v for k, v in counts.items() if k.startswith("hg-")}
    titles = load_titles()

    rows = sorted(mine.items(), key=lambda kv: -kv[1])
    total = sum(v for _, v in rows)
    if a.top:
        rows = rows[: a.top]

    lines = ["# 指南站条目访问排行", "",
             "数据源：`%s`（只统计 hg- 前缀，即 hkgui.xinfide.com 的条目页／聚合页）" % API,
             "", "**累计去重访问**：%d 次 · 有访问的页面：%d 个" % (total, len(mine)), "",
             "| # | 页面 | 访问 |", "| --- | --- | --- |"]
    for i, (k, v) in enumerate(rows, 1):
        label = titles.get(k, "(未在关键词表中的键)")
        lines.append("| %d | %s | %d |" % (i, label, v))

    txt = "\n".join(lines) + "\n"
    print(txt)
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(txt)
        print("已写出：%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
