#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""香港留学指南 · 质检四件套

用法：
    python tools/check.py            # 跑全部检查
    python tools/check.py --only schema refs links promise

设计原则（见设计文档第 5 节）：**故意不挡发布**。
发现问题照报，但退出码恒为 0——门禁只管新增内容的质量，
不管已发布内容的可用性。否则一个人没补完就卡住整个项目。

字段标准：v1.3 设计文档第 7 节「融合 12 字段」（2026-10-05 起生效）。
编号标准：方案 A（文件名三位顺延号 + 内容层 HK 编号 + 对照表），
          标题只出现 HK 编号且放最前，文件号不进标题。

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
CATALOG = os.path.join(ROOT, "docs", "HK编号对照表.md")
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

# v1.3 12 字段（字段 1「编号 + 标题」由标题正则单独校验，字段 10/11 为合并字段）
REQUIRED_FIELDS = (
    ("2 适用人群 + 阶段", r"适用人群\s*\+\s*阶段"),
    ("3 口径 + 性价比档", r"口径\s*\+\s*性价比档"),
    ("4 要花什么", r"要花什么"),
    ("5 换回什么", r"换回什么"),
    ("6 说人话", r"说人话"),
    ("7 关键节点与时效", r"关键节点与时效"),
    ("8 红线提醒", r"红线提醒"),
    ("9 常见误传", r"常见误传"),
    ("10 证据等级 + 官方依据", r"官方依据"),
    ("11 最后核实日期 + 核实人", r"最后核实日期"),
    ("12 待核实标记", r"待核实"),
)
# 证据等级写法兼容：**证据等级**：A ／ 证据等级：**A**
RE_EVIDENCE = re.compile(r"证据等级\*{0,2}\s*[:：]\s*\*{0,2}\s*([ABC])")
# 标题（方案 A）：必须以 HK 编号开头
RE_TITLE_HK = re.compile(r"^#\s+(HK-\d{3})\s+\S")
# 成本标签注释（设计文档 6.4 排序铁律的机器可读形式）
RE_COST_TAG = re.compile(r"<!--\s*成本标签\s*:")
# 成本标签值域（设计文档 6.3；2026-10-05 定死，「长/短」作废 → 判例 10）
COST_DOMAIN = (
    ("钱", ("0", "少", "多")),
    ("时间", ("少", "中", "多")),
    ("精力", ("否", "些", "是")),
    ("收益", ("大", "中", "小")),
    ("口径", ("结果", "金钱", "时间精力", "安全合规")),
)
RE_COST_KV = re.compile(r"(钱|时间|精力|收益|口径)\s*=\s*(\S+)")
# 性价比档（字段 3 的文本形式），用于与成本标签做 6.4 一致性校验（判例 11）
RE_TIER = re.compile(r"性价比档\*{0,2}\s*[:：]\s*\*{0,2}\s*(极高|高|一般)")
# 交叉引用：见第 003 条 ／ 见第 HK-023 条
RE_REF = re.compile(r"见第\s*(?:HK-)?(\d{3})\s*条")

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


def load_catalog():
    """读 HK编号对照表 → {HK 编号: {num, topic, track, status}}。表不存在时返回 None。"""
    if not os.path.isfile(CATALOG):
        return None
    mapping = {}
    for line in read(CATALOG).splitlines():
        m = re.match(
            r"\|\s*(HK-\d{3})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)",
            line,
        )
        if not m:
            continue
        hk, num, topic, track, status = (g.strip() for g in m.groups())
        mapping[hk] = {
            "num": num if re.fullmatch(r"\d{3}", num) else None,
            "topic": topic,
            "track": track,
            "status": status,
        }
    return mapping


# ---------------------------------------------------------------- schema
def check_schema(files):
    for name in files:
        text = read(os.path.join(BOOK, name))
        for label, pattern in REQUIRED_FIELDS:
            if not re.search(pattern, text):
                problems["schema"].append(f"{name} 缺字段：{label}")

        # 字段 1：标题必须是「HK 编号 + 标题」，且标题里不得再出现裸文件号
        title = text.split("\n")[0]
        m = RE_TITLE_HK.match(title)
        if not m:
            problems["schema"].append(
                f"{name} 标题未按方案 A 起头（应形如「# HK-019 标题」）：{title[:40]}"
            )
        else:
            rest = RE_TITLE_HK.sub("", title).strip()
            if re.search(r"\b\d{3}\b", rest):
                problems["schema"].append(
                    f"{name} 标题里出现了文件号（方案 A 要求文件号不进标题）：{title[:40]}"
                )
        if "董老师" in title:
            problems["schema"].append(f"{name} 标题带品牌词，违反铁律一（标题按用户搜索词写）")

        if not RE_EVIDENCE.search(text):
            problems["schema"].append(f"{name} 证据等级格式不对（应形如「证据等级：**A**」）")
        if "本条目由" not in text or "核对" not in text:
            problems["schema"].append(f"{name} 末尾缺「本条目由…核对…」署名")
        mt = RE_COST_TAG.search(text)
        if not mt:
            problems["schema"].append(f"{name} 缺成本标签注释（<!-- 成本标签: 钱=… 时间=… 精力=… 收益=… 口径=… -->）")
        else:
            tag_line = text[mt.start():].split("\n", 1)[0]
            pairs = dict(RE_COST_KV.findall(tag_line))
            for key, domain in COST_DOMAIN:
                val = pairs.get(key)
                if val is None:
                    problems["schema"].append(
                        f"{name} 成本标签缺「{key}=」（五要素齐全：钱/时间/精力/收益/口径）"
                    )
                elif val not in domain:
                    problems["schema"].append(
                        f"{name} 成本标签「{key}={val}」超出值域（设计文档 6.3："
                        f"{'/'.join(domain)}）——「长/短」已作废，时间一律用「多」"
                    )
            # 成本标签 ↔ 性价比档 内部一致性（设计文档 6.4 合成规则）
            # 极高 ⇔ 收益大 且 三项成本全为零；两个方向都要查（判例 11）
            mtier = RE_TIER.search(text)
            if mtier:
                tier = mtier.group(1)
                zero_cost = (
                    pairs.get("钱") == "0"
                    and pairs.get("时间") == "少"
                    and pairs.get("精力") == "否"
                )
                big_gain = pairs.get("收益") == "大"
                if tier == "极高" and not (zero_cost and big_gain):
                    problems["schema"].append(
                        f"{name} 性价比档＝极高，但成本标签不是「钱=0 时间=少 精力=否 收益=大」"
                        f"（现为 {' '.join(f'{k}={pairs.get(k)}' for k, _ in COST_DOMAIN)}）"
                        f"——6.4 规定极高＝收益大且三项成本全为零，见判例 10、11"
                    )
                if tier != "极高" and zero_cost and big_gain:
                    problems["schema"].append(
                        f"{name} 成本标签是「钱=0 时间=少 精力=否 收益=大」（三项全零＋收益大），"
                        f"按 6.4 性价比档应为「极高」，现为「{tier}」"
                    )

        # 证据等级与信源域名是否匹配
        me = RE_EVIDENCE.search(text)
        if me and me.group(1) == "A":
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
    """引用守恒：交叉引用必须存在；HK 编号必须与对照表一致；核实记录一一对应。"""
    nums = {name[:3] for name in files}
    catalog = load_catalog()
    if catalog is None:
        problems["refs"].append("docs/HK编号对照表.md 不存在（方案 A 要求对照表入库）")
        catalog = {}
    hk_to_num = {hk: v["num"] for hk, v in catalog.items() if v["num"]}
    # 反向：文件号 → HK 编号
    num_to_hk = {num: hk for hk, num in hk_to_num.items()}
    # HK 编号的纯数字部分 → 文件号（交叉引用「见第 HK-023 条」时用）
    hk_digits_to_num = {hk.split("-")[1]: num for hk, num in hk_to_num.items()}

    for name in files:
        text = read(os.path.join(BOOK, name))
        title = text.split("\n")[0]
        tm = RE_TITLE_HK.match(title)
        # 本条目 HK 编号必须在对照表里有登记，且文件号与对照表一致
        if tm:
            hk = tm.group(1)
            if catalog and hk not in catalog:
                problems["refs"].append(f"{name} 的 HK 编号 {hk} 未登记在 docs/HK编号对照表.md")
            elif catalog.get(hk, {}).get("num") and catalog[hk]["num"] != name[:3]:
                problems["refs"].append(
                    f"{name} 的 HK 编号 {hk} 在对照表里对应文件号 {catalog[hk]['num']}，与实际文件号不符"
                )
        # 交叉引用：既可能写文件号，也可能写 HK 编号（如「见第 HK-023 条」）
        for ref in RE_REF.findall(text):
            ok_file = ref in nums
            ok_hk = ref in hk_digits_to_num and hk_digits_to_num[ref] in nums
            if not (ok_file or ok_hk):
                problems["refs"].append(f"{name} 引用了不存在的条目：第 {ref} 条")

    # 对照表标了文件号的行，对应文件必须存在
    for hk, num in hk_to_num.items():
        if num not in nums:
            problems["refs"].append(
                f"对照表登记 {hk} → {num}，但 book/ 里没有 {num}-*.md"
            )

    # 核实记录是否与条目一一对应
    have = set()
    if os.path.isdir(DOCS):
        have = {f[:3] for f in os.listdir(DOCS) if f.endswith(".md")}
    for num in sorted(nums):
        if num not in have:
            problems["refs"].append(f"第 {num} 条缺少对应的核实记录（docs/核实记录/{num}-*.md）")
    return num_to_hk


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
                        f"{'  [死链]' if resp.status in (404, 410) else '  [可能是反爬，非死链]'}"
                    )
        except urllib.error.HTTPError as exc:
            tag = "死链" if exc.code in (404, 410) else "可能是反爬，非死链"
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
# 反面引用豁免：条目主题本身若是「揭穿某类承诺」（如 HK-011 保录不可信、
# HK-028 误传总汇），词只能出现在否定语境里——此时不计为违规。
# 判据：命中词前后 30 字符窗口内出现下列否定/警示词之一。
RE_NEGATION = re.compile(
    r"不|无|没|假|骗|违规|违法|犯罪|别|切勿|禁止|骗局|不可信|绝无|否认|揭穿|揭"
)


def check_promise(files):
    for name in files:
        text = read(os.path.join(BOOK, name))
        hits = []
        for w in PROMISE_WORDS:
            for m in re.finditer(re.escape(w), text):
                lo = max(0, m.start() - 30)
                hi = min(len(text), m.end() + 30)
                if RE_NEGATION.search(text[lo:hi]):
                    continue  # 否定语境中的反面引用，不算承诺
                hits.append(w)
                break
        if hits:
            problems["promise"].append(f"{name} 出现承诺性表述：{'、'.join(hits)}")


# ---------------------------------------------------------------- staleness
def check_staleness(files):
    today = date.today()
    for name in files:
        text = read(os.path.join(BOOK, name))
        m = re.search(r"最后核实日期\*{0,2}\s*[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})", text)
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
        body = re.split(r"常见误传\*{0,2}", text)
        if len(body) > 1 and len(body[1].strip()) > 40:
            with_misinfo += 1
        me = RE_EVIDENCE.search(text)
        if me and me.group(1) == "A":
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


# ---------------------------------------------------------------- release
RE_REVIEWED = re.compile(r"最后核实日期\*{0,2}\s*[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})")


def release_list(files):
    """生成「放行候选」表——把「哪条可以出小红书文案」变成机器可判定，不再靠人记。

    放行前置（四条，缺一不放）：
      1. 该书条目在 book/ 里已有正文；
      2. 证据等级 A 或 B；
      3. 有最后核实日期，且未过 90 天红线；
      4. 工程质检该条自身无问题（12 字段齐全 / 无承诺词 / HK 编号与对照表一致）。

    这样 WB4 出放行单时只需从「可放行」行里挑，不必回头看正文——
    也就不会再出现「给了 10 条、其中 7 条没有正文」的返工。
    """
    catalog = load_catalog() or {}
    today = date.today()
    rows = []
    for name in files:
        text = read(os.path.join(BOOK, name))
        title = text.split("\n")[0]
        tm = RE_TITLE_HK.match(title)
        hk = tm.group(1) if tm else "—"
        topic = re.sub(r"^#\s+HK-\d{3}\s+", "", title).strip()
        meta = catalog.get(hk, {})
        me = RE_EVIDENCE.search(text)
        level = me.group(1) if me else "?"

        dm = RE_REVIEWED.search(text)
        if dm:
            days = (today - datetime.strptime(dm.group(1), "%Y-%m-%d").date()).days
            reviewed = f"{dm.group(1)}（{days} 天前）"
        else:
            days, reviewed = None, "—"

        misinfo = "有" if len(re.split(r"常见误传\*{0,2}", text)) > 1 and \
            len(re.split(r"常见误传\*{0,2}", text)[1].strip()) > 40 else "无"

        why = []
        if hk == "—":
            why.append("标题缺 HK 编号")
        if level not in ("A", "B"):
            why.append(f"证据等级 {level}（需 A/B）")
        if days is None:
            why.append("缺最后核实日期")
        elif days > STALE_DAYS or days < 0:
            why.append(f"核实日期异常（{days} 天）")
        for label, pattern in REQUIRED_FIELDS:
            if not re.search(pattern, text):
                why.append(f"缺字段 {label}")
        if [w for w in PROMISE_WORDS if w in text]:
            why.append("含承诺性表述")
        if meta.get("num") and meta["num"] != name[:3]:
            why.append("与对照表文件号不一致")

        rows.append({
            "hk": hk, "num": name[:3], "topic": topic,
            "track": meta.get("track", "—"), "level": level,
            "reviewed": reviewed, "misinfo": misinfo,
            "ok": not why, "why": "；".join(why),
        })
    return rows


def render_release(rows):
    out = [
        "# 放行候选（自动生成，请勿手改）",
        "",
        f"> 由 `tools/check.py --release` 于 {date.today()} 生成。",
        "> **放行前置四条**：条目已入 `book/` ｜ 证据等级 A/B ｜ 有最后核实日期且未过 90 天 ｜ 工程质检无问题。",
        "> **放行单怎么出**：从下表的「可放行」行里挑，填最后一列「本轮指定钩子角度」，作为信件回复即可。**每批 3 条**。",
        "",
        "| HK 编号 | 文件号 | 主题 | 主线 | 证据等级 | 最后核实 | 误传素材 | 判定 | 本轮指定钩子角度 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        mark = "可放行" if r["ok"] else f"不可：{r['why']}"
        out.append(
            f"| {r['hk']} | {r['num']} | {r['topic']} | {r['track']} | "
            f"{r['level']} | {r['reviewed']} | {r['misinfo']} | {mark} |  |"
        )
    ready = [r["hk"] for r in rows if r["ok"]]
    out += [
        "",
        f"**可放行 {len(ready)} / 共 {len(rows)} 条**："
        f"{'、'.join(ready) if ready else '（无）'}",
    ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- run
TITLES = {
    "schema": "Schema 完整性（12 字段 / 编号方案 A / 成本标签 / 署名 / 等级与信源匹配）",
    "refs": "引用守恒（交叉引用 + HK 编号与对照表一致 + 核实记录一一对应）",
    "links": "链接巡检（官方链接是否还活着）",
    "promise": "承诺性表述扫描（保录取 / 百分百 / 稳过）",
    "staleness": f"核实时效（{STALE_DAYS} 天红线）",
    "coverage": "质量覆盖率（误传 ≥50% / A 级 ≥60%）",
}


def main():
    ap = argparse.ArgumentParser(description="香港留学指南质检四件套")
    ap.add_argument("--only", nargs="*", choices=list(TITLES), help="只跑指定检查")
    ap.add_argument("--network", action="store_true", help="实际访问链接（慢，默认只统计）")
    ap.add_argument("--release", action="store_true",
                    help="生成放行候选表（docs/放行候选.md），供 WB4 出放行单")
    args = ap.parse_args()

    files = entries()
    print(f"\n香港留学指南 · 质检报告  {date.today()}")
    print(f"条目数：{len(files)}")
    if not files:
        print("book/ 里还没有条目。")
        return
    for f in files:
        print(f"  · {f}")

    if args.release:
        md = render_release(release_list(files))
        out_path = os.path.join(ROOT, "docs", "放行候选.md")
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md)
        print("\n" + md)
        print(f"已写入 {out_path}\n")

    todo = args.only or ([] if args.release else list(TITLES))
    stats = None
    num_to_hk = {}
    if "schema" in todo:
        check_schema(files)
    if "refs" in todo:
        num_to_hk = check_refs(files)
    if "links" in todo:
        check_links(files, network=args.network)
    if "promise" in todo:
        check_promise(files)
    if "staleness" in todo:
        check_staleness(files)
    if "coverage" in todo:
        stats = check_coverage(files)

    if num_to_hk:
        print("\n编号映射（方案 A）")
        for num, hk in sorted(num_to_hk.items()):
            print(f"  · {num} → {hk}")

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
