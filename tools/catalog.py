#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容层的**单一来源**：路径 + 读者章（分类）+ 对照表解析。

为什么单独一个模块：`build_site.py`（站点）、`build_reader.py`（阅读器）、
`readme_sync.py`（README 回填）、`merge_order.py`（PDF/EPUB 合并顺序）
都要用同一套分类。若各自 import `build_site`，就会连带 import `markdown` ——
于是「只想读一下对照表」的脚本也依赖渲染库，CI 里平白多一个失败面
（2026-10-07 实测：合并步骤因此报「需要 markdown 库」而中断）。
本模块**零第三方依赖**，只读文本。

**读者章（分类）**是 2026-10-07 董老师定的：按「读这本书的是谁、他要办哪件事」
分章——张三是来看本科留学、李四是来看申请硕士，各读各的那一章。

单一来源约定：
- 每条归哪一章 → `docs/HK编号对照表.md` 的「读者章」列（内容层，人写）
- 章节顺序与副标题（「这一章是给谁的」）→ 本模块的 `GROUPS`
任何地方都不许再写第二份分类表。校验见 `tools/check.py` 的 chapters 项。
"""

from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
META = os.path.join(ROOT, "meta")
DOCS = os.path.join(ROOT, "docs")
CATALOG = os.path.join(DOCS, "HK编号对照表.md")

# ---------------------------------------------------------------- 读者章
# 章节名必须与对照表「读者章」列的取值**逐字一致**（check.py 校验）。
# 顺序 ＝ 阅读顺序：从年龄最小的读者（孩子读中小学）到通用收口。
GROUPS = (
    ("我孩子在读中小学", "孩子读小学 / 初中，在考虑插班去香港读中学"),
    ("申香港本科", "孩子高中在读或应届高考，要申香港本科"),
    ("读国际课程申港校", "孩子读 A-Level / IB / AP，要申香港的大学"),
    ("申香港硕士", "本人本科在读或已毕业，要申香港硕士"),
    ("办香港身份", "本人或家人要办香港身份（高才通 / 优才 / 专才 / 受养人 / 永居）"),
    ("防骗 · 通用 · 抵港之后", "所有人都要看：中介合同、保录骗局、假学历后果、抵港必办、常见误传"),
)
GROUP_NAMES = tuple(name for name, _ in GROUPS)
GROUP_DESC = dict(GROUPS)
UNGROUPED = "其他"


def group_of(track: str) -> str:
    """对照表「读者章」列 → 章节名。取值不合法时返回「其他」（check.py 会报错）。"""
    return track if track in GROUP_NAMES else UNGROUPED


# ---------------------------------------------------------------- 对照表
def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_catalog() -> dict:
    """读对照表 → {HK号: {num, topic, track, status}}。表不存在时返回空 dict。

    列序：| HK 编号 | 文件号 | 主题 | 读者章 | 状态 |
    """
    out: dict = {}
    if not os.path.isfile(CATALOG):
        return out
    for line in read(CATALOG).splitlines():
        m = re.match(
            r"\|\s*(HK-\d{3})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)", line
        )
        if not m:
            continue
        hk, num, topic, track, status = (g.strip() for g in m.groups())
        out[hk] = {
            "num": num if re.fullmatch(r"\d{3}", num) else None,
            "topic": topic,
            "track": track,
            "status": status,
        }
    return out
