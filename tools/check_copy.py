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
# 数字主张：≥3 位整数（滤掉「2 倍」「3 条」这类小数字噪声）+ **带小数点的数**
# （2026-10-06 小红书 112 反馈补：倍数列 4.6/4.65/5.05/5.25/5.3、百分数 85.6/91.5
#   只有 1–2 位整数部分，被 ≥3 位口径整类漏掉——而「取整的 5 倍」正是判例 8 的高危区）
RE_NUM = re.compile(r"\d[\d,]{2,}|\d+\.\d+")
RE_HK = re.compile(r"HK-(\d{3})")
# 「对应 001」这类声明（文案里作者自己标的对应关系）
RE_FILE_HINT = re.compile(r"对应\s*(\d{3})")
# 排除项：条目编号自身（HK-019 的 019）、年份、纯序号
IGNORE = {"2026", "2027", "2025", "2024", "10", "05"}
# 数字前面出现这些字样的，是「编号引用」不是「数字主张」，不查
# （ID(C)1026＝官方指南版本号、国标码 81002＝院校代码——都是编号，2026-10-06 补）
RE_NUM_LEAD = re.compile(
    r"(?:HK-|对应\s*|编号\s*|摘自\s*|见\s*第\s*|ID\s*\([A-Z]\)\s*|国标码\s*|"
    r"版本\s*|§\s*|v\s*|`)\s*$"  # 版本号/条款号前缀（小数口径补收后需一并豁免）
)
# 附录段：不是「发布用文案」，里面的数字常属别的条目 → 一律跳过比对
# （2026-10-05 修：原本这些段会被按段体里随机出现的 HK 编号错误映射，
#   例如「未改动项汇总」提到 HK-019 就被映射到 001，把 002 的宿舍数字报成「查不到」）
RE_APPENDIX = re.compile(
    r"(未改动项汇总|改动清单|变更清单|修改清单|发布顺序|待办|下一步|附注|备注说明|"
    r"版本说明|核对说明|定稿说明|免责|使用说明|写作说明)"
)


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
    """按小标题切段，并带上层级（便于子节继承父节的条目映射）。"""
    marks = [(m.start(), m.group(0)) for m in re.finditer(r"^(#{2,4})\s+.*$", text, re.M)]
    if not marks:
        return [("（全文）", text, 2)]
    secs = []
    for i, (pos, title) in enumerate(marks):
        level = len(title) - len(title.lstrip("#"))
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        secs.append((title.strip(), text[pos:end], level))
    return secs


def find_target(sec_title, sec_body, catalog, inherited=None):
    """定位这一段对应哪条正文。

    只用**声明式**信息定位，不在段体里乱搜 HK 编号——段体里出现的 HK 编号是
    「交叉引用」，不代表「本段就属于那条」（2026-10-05 修的错映射根源）。
    顺序：① 「对应 NNN」声明 → ② 段标题里的 HK 编号 → ③ 继承父节映射。
    """
    for m in RE_FILE_HINT.finditer(sec_title + "\n" + sec_body):
        name, txt = entry_text(m.group(1))
        if txt:
            return m.group(1), name, txt
    for m in RE_HK.finditer(sec_title):
        hk = "HK-" + m.group(1)
        num = catalog.get(hk)
        if num:
            name, txt = entry_text(num)
            if txt:
                return num, name, txt
    if inherited:
        return inherited
    return None, None, None


def wan_variants(n):
    """金额「万」口径换算候选（封面规范 v3 第 5 条唯一允许的换算）。

    `4.95万` → 正文原样写 `49,500`；`1.5万` → `15,000`。仅当数字后**紧跟「万」**时启用，
    倍数（4.6 倍）、百分比（85.6%）一律不豁免——那是判例 8 要拦的取整高危区。
    """
    try:
        v = int(round(float(n.replace(",", "")) * 10000))
    except ValueError:
        return []
    return [f"{v:,}", str(v)]


def digit_found(n, body, entry):
    """数字 n 是否能在该条正文里找到（含金额万口径换算豁免）。"""
    cands = [n]
    if re.search(re.escape(n) + r"\s*万", body):
        cands += wan_variants(n)
    return any(c in entry or c.replace(",", "") in entry.replace(",", "") for c in cands)


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
    current = None          # 当前大节的映射，供其下的子节继承
    current_level = 0
    for title, body, level in split_sections(text):
        if RE_APPENDIX.search(title):
            print(f"⏭️  {title[:48]}  →（附录段／非发布文案，跳过比对）")
            continue
        # 子节（层级更深）继承所属大节的条目；大节自己重新定位
        inherit = current if (current is not None and level > current_level) else None
        num, name, entry = find_target(title, body, catalog, inherited=inherit)
        if entry is None:
            hks = list(dict.fromkeys(re.findall(r"HK-\d{3}", title + "\n" + body)))
            tip = f"（段内提到 {', '.join(hks)}，可据此人工指认）" if hks else ""
            print(f"[无法定位] {title[:48]} —— 该段未标注对应条目，请人工确认{tip}"
                  f"；发布用文案段建议写成「（对应 NNN）」")
            continue
        if current is None or level <= current_level:
            current, current_level = (num, name, entry), level
        nums = digits_to_check(body, codes)
        missing = [n for n in nums if not digit_found(n, body, entry)]
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
