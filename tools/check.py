#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""香港留学指南 · 质检四件套

用法：
    python tools/check.py            # 跑全部检查
    python tools/check.py --only schema refs links promise

设计原则（见设计文档第 5 节）：**故意不挡发布**。
发现问题照报，但退出码恒为 0——门禁只管新增内容的质量，
不管已发布内容的可用性。否则一个人没补完就卡住整个项目。

依赖：仅标准库。链接巡检需要网络，其余离线可跑。
"""

import argparse
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
DOCS = os.path.join(ROOT, "docs", "核实记录")
WHITELIST_DOMAINS = (
    "immd.gov.hk", "edb.gov.hk", "ugc.edu.hk", "info.gov.hk",
    "gov.hk", "elegislation.gov.hk", "censtatd.gov.hk",
    "hkengage.gov.hk", "crossboundaryservices.gov.hk",
    # 大学官网（注意：各校招生页常用独立子域，如 join.hkust.edu.hk）
    "hku.hk", "cuhk.edu.hk", "ust.hk", "hkust.edu.hk",
    "polyu.edu.hk", "cityu.edu.hk", "hkbu.edu.hk",
    "hkmu.edu.hk", "ln.edu.hk", "eduhk.hk", "hkse.edu.hk", "hkcc.edu.hk",
)
# 内容分发渠道（可写进正文，不是依据来源）
CHANNELS = ("zhihu.com", "xiaohongshu.com", "douyin.com", "mp.weixin.qq.com")

PROMISE_WORDS = (
    "保录取", "保过", "百分百", "100%", "一定能", "保证获批", "稳过",
    "包过", "包录取", "包获批", "绝对没问题", "零风险", "一定能拿",
)
REQUIRED_FIELDS = (
    "适用人群", "要花什么", "换回什么", "关键节点与时效",
    "官方依据", "证据等级", "常见误传", "最后核实日期", "待核实",
)
STALE_DAYS = 90
# 部分大学官网会拒绝非浏览器 UA（返回 403），巡检必须带上浏览器标识
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

problems = {k: [] for k in ("schema", "refs", "links", "promise", "staleness", "coverage")}


def entries():
    if not os.path.isdir(BOOK):
        return []
    return sorted(f for f in os.listdir(BOOK) if f.endswith(".md") and f[:3].isdigit())


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- schema
def check_schema(files):
    for name in files:
        text = read(os.path.join(BOOK, name))
        missing = [f for f in REQUIRED_FIELDS if f not in text]
        if missing:
            problems["schema"].append(f"{name} 缺字段：{'、'.join(missing)}")
        if not re.search(r"\*\*证据等级\*\*：\s*[ABC]", text):
            problems["schema"].append(f"{name} 证据等级格式不对（应形如 **证据等级**：A）")
        if "本条目由" not in text or "核对" not in text:
            problems["schema"].append(f"{name} 末尾缺「本条目由…核对…」署名")
        # 标题：条目标题不应带品牌词（设计文档铁律一）
        title = text.split("\n")[0]
        if "董老师" in title:
            problems["schema"].append(f"{name} 标题带品牌词，违反铁律一（标题按用户搜索词写）")
        # 证据等级与信源域名是否匹配
        m = re.search(r"\*\*证据等级\*\*：\s*([ABC])", text)
        if m and m.group(1) == "A":
            links = re.findall(r"<(https?://[^>]+)>", text)
            if links:
                bad = [
                    u for u in links
                    if not any(d in u for d in WHITELIST_DOMAINS)
                    and not any(c in u for c in CHANNELS)
                ]
                if bad:
                    problems["schema"].append(
                        f"{name} 标 A 级但存在非白名单域名：{bad[0][:60]}"
                    )


# ---------------------------------------------------------------- refs
def check_refs(files):
    """引用守恒：每个「见第 NNN 条」必须对应真实存在的编号。"""
    nums = {name[:3] for name in files}
    for name in files:
        text = read(os.path.join(BOOK, name))
        for ref in re.findall(r"见第\s*(\d{3})\s*条", text):
            if ref not in nums:
                problems["refs"].append(f"{name} 引用了不存在的条目：第 {ref} 条")
    # 核实记录是否与条目一一对应
    have = set()
    if os.path.isdir(DOCS):
        have = {f[:3] for f in os.listdir(DOCS) if f.endswith(".md")}
    for num in sorted(nums):
        if num not in have:
            problems["refs"].append(f"第 {num} 条缺少对应的核实记录（docs/核实记录/{num}-*.md）")


# ---------------------------------------------------------------- links
def check_links(files, network=False, timeout=20):
    """巡检官方链接。

    注意两种结果的区别（2026-10-05 实测）：
    - 403 / URLError 往往是**反爬或本机 TLS 环境限制**，不等于链接已死；
    - 404 / 410 才是真死链。
    因此本检查只报告状态码，**判定死链必须人工二次确认**。
    """
    seen = {}
    for name in files:
        text = read(os.path.join(BOOK, name))
        for url in re.findall(r"<(https?://[^>]+)>", text):
            seen.setdefault(url, []).append(name)
    for url, srcs in sorted(seen.items()):
        if not network:
            print(f"  · 待检链接 {len(seen)} 条（加 --network 实际访问）")
            break
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            "Accept-Language": "zh-HK,zh-CN;q=0.9,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 400:
                    problems["links"].append(
                        f"{url} → HTTP {resp.status}（{','.join(srcs)}）"
                        f"{'  [可能是反爬，非死链]' if resp.status != 404 else '  [死链]'}"
                    )
        except urllib.error.HTTPError as exc:
            tag = "死链" if exc.code == 404 else "可能是反爬，非死链"
            problems["links"].append(
                f"{url} → HTTP {exc.code}（{','.join(srcs)}）  [{tag}]"
            )
        except Exception as exc:  # noqa: BLE001
            problems["links"].append(
                f"{url} → {type(exc).__name__}（{','.join(srcs)}）  "
                f"[连接层失败，常见于本机 TLS/网络环境限制，不能据此判死链]"
            )
        time.sleep(0.5)


# ---------------------------------------------------------------- promise
def check_promise(files):
    for name in files:
        text = read(os.path.join(BOOK, name))
        hits = [w for w in PROMISE_WORDS if w in text]
        if hits:
            problems["promise"].append(f"{name} 出现承诺性表述：{'、'.join(hits)}")


# ---------------------------------------------------------------- staleness
def check_staleness(files):
    today = date.today()
    for name in files:
        text = read(os.path.join(BOOK, name))
        m = re.search(r"\*\*最后核实日期\*\*：\s*(\d{4}-\d{2}-\d{2})", text)
        if not m:
            problems["staleness"].append(f"{name} 读不出最后核实日期")
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        age = (today - d).days
        if age > STALE_DAYS:
            problems["staleness"].append(
                f"{name} 已 {age} 天未复核（超过 {STALE_DAYS} 天红线）"
            )
        elif age < 0:
            problems["staleness"].append(f"{name} 核实日期在未来，疑似写错")


# ---------------------------------------------------------------- coverage
def check_coverage(files):
    """误传覆盖率目标 ≥ 50%；A级占比目标 ≥ 60%。"""
    if not files:
        return
    with_misinfo = 0
    level_a = 0
    for name in files:
        text = read(os.path.join(BOOK, name))
        body = re.split(r"\*\*常见误传\*\*", text)
        if len(body) > 1 and len(body[1].strip()) > 40:
            with_misinfo += 1
        if re.search(r"\*\*证据等级\*\*：\s*A", text):
            level_a += 1
    n = len(files)
    rate_mis = with_misinfo / n * 100
    rate_a = level_a / n * 100
    if rate_mis < 50:
        problems["coverage"].append(
            f"「常见误传」覆盖率 {rate_mis:.0f}%（{with_misinfo}/{n}），目标 ≥ 50%"
        )
    if rate_a < 60:
        problems["coverage"].append(f"A 级占比 {rate_a:.0f}%（{level_a}/{n}），目标 ≥ 60%")
    return rate_mis, rate_a


# ---------------------------------------------------------------- run
TITLES = {
    "schema": "Schema 完整性（11 字段 / 署名 / 标题铁律 / 等级与信源匹配）",
    "refs": "引用守恒（交叉引用 + 核实记录一一对应）",
    "links": "链接巡检（官方链接是否还活着）",
    "promise": "承诺性表述扫描（保录取 / 百分百 / 稳过）",
    "staleness": f"核实时效（{STALE_DAYS} 天红线）",
    "coverage": "质量覆盖率（误传 ≥50% / A 级 ≥60%）",
}


def main():
    ap = argparse.ArgumentParser(description="香港留学指南质检四件套")
    ap.add_argument("--only", nargs="*", choices=list(TITLES), help="只跑指定检查")
    ap.add_argument("--network", action="store_true", help="实际访问链接（慢，默认只统计）")
    args = ap.parse_args()

    files = entries()
    print(f"\n香港留学指南 · 质检报告  {date.today()}")
    print(f"条目数：{len(files)}")
    if not files:
        print("book/ 里还没有条目。")
        return
    for f in files:
        print(f"  · {f}")

    todo = args.only or list(TITLES)
    stats = None
    if "schema" in todo:
        check_schema(files)
    if "refs" in todo:
        check_refs(files)
    if "links" in todo:
        check_links(files, network=args.network)
    if "promise" in todo:
        check_promise(files)
    if "staleness" in todo:
        check_staleness(files)
    if "coverage" in todo:
        stats = check_coverage(files)

    print()
    for key, title in TITLES.items():
        if key not in todo:
            continue
        issues = problems[key]
        if not issues:
            print(f"[通过] {title}")
        else:
            print(f"[提示 {len(issues)} 项] {title}")
            for it in issues:
                print(f"    - {it}")

    if stats:
        print(f"\n覆盖率：常见误传 {stats[0]:.0f}% ｜ A 级 {stats[1]:.0f}%")
    print("\n说明：这些问题不阻断发布（见脚本头部设计原则）。红线的处理是改内容，不是停下项目。\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
