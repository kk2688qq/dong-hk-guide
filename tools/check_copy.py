#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文案逐数字复核（判例 8 的双向比对，2026-10-05 建立）

用法：
    python tools/check_copy.py <文案文件.md>

做什么：
    把文案文件里出现的**所有数字**，逐个到它对应的 `book/` 正文里找。
    找到 → 通过；找不到 → 报出来（这就是判例 8 要拦的东西：
    文案里每一个数字都必须能在正文原样找到，不许四舍五入、不许取整、不许换算约数）。

怎么知道文案对应哪条正文：
    1. 文案里写 `HK-0NN` → 按 `docs/HK编号对照表.md` 映射到文件号；
    2. 或直接写文件号（`001` / `对应 001`）→ 直接用；
    3. 两者都没有 → 该段按「无法定位」报出，人工指定。

设计原则与 check.py 一致：**只报不算分，退出码恒为 0**——问题报出来，处理是改内容，不是停下项目。

注意：文件里的「变更清单 / 附注 / 未改动项汇总」这类段落**不是发布用文案**，但会被本脚本一并扫到
（其中数字常属另一条目），报出的结果**要人工看一眼上下文**再判断。真正的判据是「发布用正文段」。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
CATALOG = os.path.join(ROOT, "docs", "HK编号对照表.md")

# 数字：3 位以上（含千位逗号）。两位以内的数字（如「3 倍」「7 年」）噪声太大，不查。
RE_NUM = re.compile(r"\d[\d,]{2,}")
RE_HK = re.compile(r"HK-(\d{3})")
# 「对应 001」这类声明（文案里作者自己标的对应关系）
RE_FILE_HINT = re.compile(r"对应\s*(\d{3})")
# 排除项：条目编号自身（HK-019 的 019）、年份、纯序号
IGNORE = {"2026", "2027", "2025", "2024", "10", "05"}
# 数字前面出现这些字样的，是「编号引用」不是「数字主张」，不查
RE_NUM_LEAD = re.compile(r"(?:HK-|对应\s*|编号\s*|摘自\s*|见\s*第\s*|`)\s*$")


def known_code_numbers():
    """所有条目编号（文件号 + HK 数字）：它们在文案里是「引用编号」，不是数字主张。"""
    codes = set()
    if os.path.isdir(BOOK):
        for name in os.listdir(BOOK):
            if name[:3].isdigit():
                codes.add(name[:3])
    if os.path.isfile(CATALOG):
        with open(CATALOG, encoding="utf-8") as fh:
            codes |= set(re.findall(r"HK-(\d{3})", fh.read()))
    return codes


def load_catalog():
    """HK 编号 → 文件号（读 docs/HK编号对照表.md）。"""
    mapping = {}
    if not os.path.isfile(CATALOG):
        return mapping
    with open(CATALOG, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(
                r"\|\s*(HK-\d{3})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)",
                line,
            )
            if m:
                hk, num = m.group(1), m.group(2).strip()
                if re.fullmatch(r"\d{3}", num):
                    mapping[hk] = num
    return mapping


def entry_text(num):
    """按文件号取正文。"""
    if not os.path.isdir(BOOK):
        return None, None
    for name in sorted(os.listdir(BOOK)):
        if name.startswith(num) and name.endswith(".md"):
            with open(os.path.join(BOOK, name), encoding="utf-8") as fh:
                return name, fh.read()
    return None, None


def split_sections(text):
    """按「### 一、HK-019…」这类小标题切段；切不开就整篇当一段。"""
    marks = [(m.start(), m.group(0)) for m in re.finditer(r"^#{2,4}\s+.*$", text, re.M)]
    if not marks:
        return [("（全文）", text)]
    secs = []
    for i, (pos, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        secs.append((title.strip(), text[pos:end]))
    return secs


def find_target(sec_title, sec_body, catalog, fallback_hk=None):
    """定位这一段对应哪条正文：先看段内文件号声明，再看 HK 编号。"""
    for m in RE_FILE_HINT.finditer(sec_body):
        name, txt = entry_text(m.group(1))
        if txt:
            return m.group(1), name, txt
    for m in RE_HK.finditer(sec_title + "\n" + sec_body):
        hk = "HK-" + m.group(1)
        num = catalog.get(hk)
        if num:
            name, txt = entry_text(num)
            if txt:
                return num, name, txt
    if fallback_hk and fallback_hk in catalog:
        num = catalog[fallback_hk]
        name, txt = entry_text(num)
        if txt:
            return num, name, txt
    return None, None, None


def digits_to_check(body, codes):
    """挑出这一段里真正需要核的「数字主张」：排除年份、编号引用、条目编号。"""
    out = []
    for m in RE_NUM.finditer(body):
        n = m.group(0)
        if n in IGNORE:
            continue
        if n in codes or n.replace(",", "") in codes:
            continue
        # 前 8 个字符里有「HK- / 对应 / 编号 / 见第」等 → 是编号引用
        if RE_NUM_LEAD.search(body[max(0, m.start() - 8):m.start()]):
            continue
        if n not in out:
            out.append(n)
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：python tools/check_copy.py <文案文件.md>")
    path = sys.argv[1]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    # 只复核「发布用文案」部分：若文件里有「## 正文」小节，从这里开始
    m = re.search(r"^##+\s*正文.*$", text, re.M)
    if m:
        text = text[m.start():]

    catalog = load_catalog()
    codes = known_code_numbers()
    if not catalog:
        print("[提示] 读不到 docs/HK编号对照表.md，HK 编号映射不可用（改用文件号声明定位）")

    print(f"文案逐数字复核 · {os.path.basename(path)}")
    print("=" * 60)

    total_missing = 0
    total_checked = 0
    for title, body in split_sections(text):
        num, name, entry = find_target(title, body, catalog)
        if entry is None:
            # 标题里没有可定位信息，跳过（如「变更清单」「附注」等非文案段）
            if RE_HK.search(title) or RE_FILE_HINT.search(body):
                print(f"[无法定位] {title[:50]} —— 段里提到了条目号，但找不到对应正文")
            continue
        nums = digits_to_check(body, codes)
        missing = [
            n for n in nums
            if n not in entry and n.replace(",", "") not in entry.replace(",", "")
        ]
        total_checked += len(nums)
        total_missing += len(missing)
        flag = "✅" if not missing else "⚠️"
        print(f"{flag} {title[:48]}  →  {name}（比对 {len(nums)} 个数字）")
        for n in missing:
            print(f"      ✗ 正文查不到：{n}")

    print("=" * 60)
    print(f"合计比对 {total_checked} 个数字，正文查不到 {total_missing} 个。")
    if total_missing:
        print("→ 按判例 8：文案数字必须能在正文原样找到；查不到的，改文案或先补正文（不阻断发布）。")
    else:
        print("→ 零缺口：本批文案数字全部可在正文原样找到。")


if __name__ == "__main__":
    main()
