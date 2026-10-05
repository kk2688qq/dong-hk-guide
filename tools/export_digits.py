#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出「文案数字校验包」（WB4-010 裁定 W1=C3 的落地件，2026-10-06 建立）

用法：
    python tools/export_digits.py

做什么：
    把 book/ 里每条正文出现过的**数字主张**（与 check_copy.py 同一套抽取口径：
    ≥3 位、排除年份 / 编号引用 / 条目编号）抽出来，连同**上下文片段**，
    导出成一个自包含 JSON——小红书专家拿到它即可**本地比对文案数字**，
    不再需要仓库访问权、也不用排队等 WB2 复跑（WB2 只做终审抽验）。

为什么每个数字带上下文：
    「数字对、口径错」（本地生数当非本地生数、旧学年当新学年）判例 8 同样要拦；
    光有数字列表查不出这种错，上下文片段供比对语义。

正文更新后重跑本脚本即可刷新；以 JSON 内 generated / source_commit 为准。
输出：docs/校验包/文案数字校验包-<日期>.json
"""
import json
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
OUTDIR = os.path.join(ROOT, "docs", "校验包")
REPO = "https://github.com/kk2688qq/dong-hk-guide"

RE_TITLE = re.compile(r"^#\s+(HK-\d{3}[^\n]*)$", re.M)
RE_MDNOISE = re.compile(r"[#*`>|\\\[\]]")
USAGE = (
    "文案定稿前自查三步："
    "① 按文案里标注的「对应 HK-0XX」在本包 entries 里找到该条目；"
    "② 把文案里出现的数字（≥3 位，年份/条目编号除外）逐个在 digits[].n 里找原样数字；"
    "③ 数字在 → 再用 ctx 核对口径（是否同一个口径：本地生 vs 非本地生、哪一学年、单位是万还是元）。"
    "查不到、或口径对不上 → 记下「数字 + 所在句子 + 对应 HK」，提交 WB4 转 WB2，不要自行改数字。"
    "本包是快照：正文更新后 WB2 会重出新包，以 generated / source_commit 为准。"
)


def git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def ctx_of(body, m, span=28):
    lo, hi = max(0, m.start() - span), min(len(body), m.end() + span)
    s = RE_MDNOISE.sub("", body[lo:hi])
    s = re.sub(r"\s+", " ", s).strip()
    return ("…" if lo > 0 else "") + s + ("…" if hi < len(body) else "")


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from check_copy import digits_to_check, known_code_numbers

    codes = known_code_numbers()
    entries = {}
    for name in sorted(os.listdir(BOOK)):
        if not (name[:3].isdigit() and name.endswith(".md")):
            continue
        with open(os.path.join(BOOK, name), encoding="utf-8") as fh:
            text = fh.read()
        tm = RE_TITLE.search(text)
        title = tm.group(1).strip() if tm else name
        hk = title.split()[0] if title.split() else name[:3]
        digs = []
        for n in digits_to_check(text, codes):
            m = re.search(re.escape(n), text)
            digs.append({"n": n, "ctx": ctx_of(text, m) if m else ""})
        entries[hk] = {
            "file": name,
            "title": title,
            "url": REPO + "/blob/main/book/" + name,
            "digit_count": len(digs),
            "digits": digs,
        }

    pkg = {
        "generated": str(date.today()),
        "source_commit": git_commit(),
        "repo": REPO,
        "purpose": "小红书文案逐数字自查包（判例 8 双向比对的正方向数据；WB4-010 裁定 W1=C3 落地件）",
        "rule": "文案每个数字必须能在对应条目正文原样找到，不许四舍五入/取整/换算；"
                "打假句也不写正文没有的具体数字（判例 14），改写错数字的「类别」。",
        "usage": USAGE,
        "entry_count": len(entries),
        "entries": entries,
    }

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, f"文案数字校验包-{date.today().isoformat()}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, ensure_ascii=False, indent=1)

    total = sum(e["digit_count"] for e in entries.values())
    print(f"已导出：{out}")
    print(f"条目 {len(entries)} 条，数字主张共 {total} 个（来源 commit {pkg['source_commit']}）")
    for hk, e in entries.items():
        print(f"  {hk}  {e['file']}  {e['digit_count']} 个数字")


if __name__ == "__main__":
    main()
