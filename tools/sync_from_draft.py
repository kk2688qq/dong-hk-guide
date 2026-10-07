#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按定稿整份覆盖 book/（董老师 2026-10-07 定的工作方式）。

背景（为什么有这个脚本）
------------------------
定稿（WB4 装配的《董老师香港留学指南》单文件）与仓库 `book/*.md` **同源同序**，
只差一层「呈现方言」：

| 定稿（读者版）                                   | 仓库（作者版，机器可校验）              |
| ------------------------------------------------ | --------------------------------------- |
| `### HK-005 标题`                                | `# HK-005 标题`                         |
| ``> `风险 = 中`　·　`阶段 = …`　·　`焦虑 = …` ``  | `<!-- 风险=中 阶段=要不要去 焦虑=取舍 -->` |
| `#### 说人话`（9 个字段标题）                     | `**说人话**`                             |
| 段尾 `<div style="page-break-after: always;">`   | 无                                       |

以前的做法是**一条一条比着改**（今天为同步 026 改了 91 个文件）——慢，而且容易漏
（内部术语那 9 处就是这么漏的）。**现在改成整份覆盖**：定稿为准 → 逐条反变换 → 覆盖
`book/*.md`。默认只做 **dry-run**（报告会动哪些文件、增删多少字符），加 `--write` 才落盘。

用法
----
    python tools/sync_from_draft.py                       # dry-run，默认读通道里的定稿
    python tools/sync_from_draft.py --write               # 落盘
    python tools/sync_from_draft.py --draft <路径> --write   # 指定定稿
    python tools/sync_from_draft.py --check               # 只回退出码（0=完全一致）

不覆盖的部分（如实说明，不静默丢东西）
--------------------------------------
- 定稿里的**前置/后置章节**（第一部分～第五部分）对应的是 `meta/*.md`，**结构不是
  1:1**（定稿把 8 个 meta 文件重排成 5 个部分），本脚本**不碰 meta/**，只在报告里
  列出「已忽略的段落数」。
- `docs/`、`tools/`、`README` 等非正文文件不在范围内。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, "book")
# 默认定稿：优先仓库内的收编副本（CI 可用；2026-10-08 起发布件也以它为源），
# 没有再退回通道里的权威镜像（WB2 侧本机）。
_REPO_DRAFT = os.path.join(ROOT, "release", "定稿-董老师香港留学指南.md")
_HANDOFF_DRAFT = os.path.join(
    os.path.expanduser("~"),
    "WorkBuddy", "2026-09-19-08-45-55", "私密空间", "handoff", "WB4-to-WB2",
    "董老师香港留学指南-v1.0（49条全文）.md",
)
DEFAULT_DRAFT = _REPO_DRAFT if os.path.isfile(_REPO_DRAFT) else _HANDOFF_DRAFT

# 定稿侧的结构行
RE_ENTRY = re.compile(r"^#{1,6}\s+(HK-\d{3})\s+(.+?)\s*$")
RE_RISK_Q = re.compile(
    r"^>\s*`风险\s*=\s*([^`]+)`\s*·\s*`阶段\s*=\s*([^`]+)`\s*·\s*`焦虑\s*=\s*([^`]+)`\s*$"
)
RE_FIELD4 = re.compile(r"^#{4}\s+(.+?)\s*$")
# 切段边界：part(H1) / chapter(H2) / entry(H3)。H4 是条目内的字段标题，不是边界。
RE_ANY_H = re.compile(r"^#{1,3}\s+\S")
RE_PAGEBREAK = re.compile(r'^\s*<div\s+style="page-break-after:\s*always;"\s*>\s*</div>\s*$')

# 只允许这 9 个字段标题被反变换；出现别的 H4 就报错（避免把正文里的四级标题误转）
FIELD_LABELS = {
    "说人话", "要花什么", "换回什么", "红线提醒", "常见误传",
    "解决什么焦虑 + 风险等级 + 决策阶段", "关键节点与时效",
    "证据等级 + 官方依据", "本条最后更新",
}

# ---- 结构性挪移：只有「显式规则」能表达，不能靠机械反变换 ----
# 定稿把 HK-030 拆成两处：条目头（说人话 / 要花什么 / 换回什么）+ **章级块**
# （`## 一、材料清单总表…` 起到该块末尾的编者按，含条目剩下的字段）。
# 仓库侧 030 是这两段拼起来的。不写这条规则，机械覆盖会把 5276 字删成 408 字。
EXTRA_BLOCKS = {
    "HK-030": {"start": "## 一、材料清单总表（按阶段，可打印）", "stop": "### HK-043"},
}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split_draft(text):
    """定稿 → {HK 编号: 段落文本}，并给出被忽略的前置/后置段落数。

    切段的边界是**任意 ≤H3 标题**（part = H1、chapter = H2、entry = H3），
    不能只用「下一个 ### HK-」——书里**最后一条**（HK-026）后面直接接
    「第四部分 · 许可与免责」「第五部分 · 关于这本书」，只找 ### 会把它吞进来（实测越界）。
    """
    lines = text.split("\n")
    marks = []
    for i, ln in enumerate(lines):
        if RE_ANY_H.match(ln):
            marks.append((i, RE_ENTRY.match(ln)))
    segments, ignored = {}, 0
    for k, (i, m) in enumerate(marks):
        if not (m and lines[i].startswith("### ")):
            continue
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        segments.setdefault(m.group(1), []).append("\n".join(lines[i:end]))
    covered = set()
    for k, (i, m) in enumerate(marks):
        if m and lines[i].startswith("### "):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
            covered.update(range(i, end))
    for i, ln in enumerate(lines):
        if i not in covered and re.match(r"^#{1,3}\s+\S", ln):
            ignored += 1
    return {k: v[0] for k, v in segments.items()}, ignored


def convert_line(ln, hk, problems):
    """单行反变换。返回 None 表示该行丢弃（分页符）。"""
    if RE_PAGEBREAK.match(ln):
        return None
    m = RE_ENTRY.match(ln)
    if hk and m and m.group(1) == hk and ln.startswith("### "):
        return f"# {hk} {m.group(2)}"
    m = RE_RISK_Q.match(ln)
    if m:
        return f"<!-- 风险={m.group(1)} 阶段={m.group(2)} 焦虑={m.group(3)} -->"
    m = RE_FIELD4.match(ln)
    if m:
        label = m.group(1)
        if label not in FIELD_LABELS:
            problems.append(f"{hk or '块'} 出现未知的 #### 标题（不入字段白名单）：{label}")
        return f"**{label}**"
    return ln


def _tidy(out):
    """收尾：去掉段尾的 --- / 空行（仓库文件以编者行结尾）。"""
    while out and not out[-1].strip():
        out.pop()
    while out and out[-1].strip() == "---":
        out.pop()
        while out and not out[-1].strip():
            out.pop()
    # 仓库 book/*.md 的历史约定是**末尾不带换行**（实测：末字节是汉字/星号，非 0a）。
    # 为免一次覆盖把 49 个文件全变成「改了末行」，这里跟随既有约定，由调用方决定收尾。
    return "\n".join(out)


def to_repo(seg, hk, problems):
    """定稿条目段 → 仓库正文（反变换）。"""
    out = [x for x in (convert_line(l, hk, problems) for l in seg.split("\n")) if x is not None]
    return _tidy(out)


def extra_block(lines, start, stop, problems):
    """取定稿里 [start 标题, stop 标题) 之间的整块，并做同样的行级反变换。

    终止条件 = 先遇到 `### HK-`（下一条目）/ `## 第 N 章`（下一章）/ `# `（下一部分）
    为止——**不能见 `## ` 就停**（HK-030 的块自带 `## 一、` 与 `## 二、` 两级小节），
    也不能只写死一个 stop 字符串（实测写成 `## 第 2 章` 时会把 HK-043 全条吞进来）。
    stop 只作**期望值**用，实际边界以上面三条为准。
    """
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == start.strip())
    except StopIteration:
        return None
    j = len(lines)
    for k in range(i + 1, len(lines)):
        s = lines[k].strip()
        if s.startswith("### HK-") or s.startswith("# ") or re.match(r"^##\s*第\s*\d+\s*章", s):
            j = k
            break
    body = [x for x in (convert_line(l, None, problems) for l in lines[i:j]) if x is not None]
    if stop and not lines[j].strip().startswith(stop.strip()):
        # 边界与预期不符：报出来，不静默
        print(f"    （提示：{start} 的块止于「{lines[j].strip()[:30]}」，"
              f"与预期的「{stop}」不同——规则可能需要更新）")
    return _tidy(body)


def hk_of(name):
    t = read(os.path.join(BOOK, name))
    m = re.match(r"^#\s+(HK-\d{3})\s", t)
    return m.group(1) if m else None


def flat(s):
    """去空白 + 去 markdown 强调符，用于判「只是排版差异」还是「内容真变了」。"""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"^\s*<div[^>]*>\s*</div>\s*$", "", s, flags=re.M)
    s = re.sub(r"[*`_]", "", s)
    return re.sub(r"\s+", "", s)


def main():
    ap = argparse.ArgumentParser(description="按定稿整份覆盖 book/")
    ap.add_argument("--draft", default=DEFAULT_DRAFT, help="定稿单文件路径")
    ap.add_argument("--write", action="store_true", help="落盘（默认只 dry-run）")
    ap.add_argument("--check", action="store_true", help="只回退出码：0=完全一致")
    ap.add_argument("--shrink", type=float, default=0.8,
                    help="内容缩水到原文件的这个比例以下就拒绝覆盖（默认 0.8）")
    args = ap.parse_args()

    if not os.path.isfile(args.draft):
        print(f"[错] 定稿不存在：{args.draft}")
        return 2
    draft, ignored = split_draft(read(args.draft))
    print(f"定稿：{args.draft}")
    print(f"  · 解析到条目 {len(draft)} 条；忽略前置/后置段落 {ignored} 处（对应 meta/，本脚本不碰）")

    repo = {}
    for name in sorted(os.listdir(BOOK)):
        if name.endswith(".md") and name[:3].isdigit():
            hk = hk_of(name)
            if hk:
                repo[hk] = name
    print(f"  · 仓库 book/ 条目 {len(repo)} 条")

    only_draft = sorted(set(draft) - set(repo))
    only_repo = sorted(set(repo) - set(draft))
    if only_draft:
        print(f"  ! 只在定稿里有：{only_draft}")
    if only_repo:
        print(f"  ! 只在仓库里有：{only_repo}")

    problems, changed, same, refused = [], [], 0, []
    dlines = read(args.draft).split("\n")
    for hk in sorted(set(draft) & set(repo)):
        name = repo[hk]
        want = to_repo(draft[hk], hk, problems)
        # 结构性挪移：按显式规则把章级块拼回条目
        if hk in EXTRA_BLOCKS:
            blk = extra_block(dlines, EXTRA_BLOCKS[hk]["start"],
                              EXTRA_BLOCKS[hk]["stop"], problems)
            if blk is None:
                problems.append(
                    f"{hk} 的章级块「{EXTRA_BLOCKS[hk]['start']}」在定稿里找不到"
                    f"——规则失效，本条目跳过（请更新 EXTRA_BLOCKS）"
                )
                continue
            want = want + "\n\n---\n\n" + blk
        path = os.path.join(BOOK, name)
        have = read(path)
        if have.rstrip("\n") == want.rstrip("\n"):
            same += 1
            continue
        # 安全闸：内容显著缩水 = 定稿把这块内容挪去了别处（章级章节等），
        # 机械覆盖会**删掉**它。拒绝覆盖并报出来，交人/规则处理。
        # 实测：HK-030 的两个附表在定稿里被提成 `## 一、材料清单总表` 与
        # `## 二、家长最常问的 20 个问题`，缩水到 8%。
        fa, fb = len(flat(have)), len(flat(want))
        if fb < fa * args.shrink:
            refused.append((name, fa, fb))
            continue
        tail = "\n" if have.endswith("\n") else ""
        changed.append((name, len(have.split("\n")), len(want.split("\n")), want + tail, path))

    print()
    for p in problems:
        print(f"  ! {p}")
    for name, fa, fb in refused:
        print(f"  ! 拒绝覆盖 {name}：内容由 {fa} 字缩到 {fb} 字"
              f"（疑结构性挪移，不是编辑差异）——需单独规则或人工裁定")
    for name, hl, dl, _, _ in changed:
        print(f"  · 待覆盖 {name}：{hl} 行 → {dl} 行")
    print(f"\n合计：一致 {same} 条，待覆盖 {len(changed)} 条，"
          f"拒绝 {len(refused)} 条，异常 {len(problems)} 处")
    if args.check:
        return 1 if (changed or problems or refused) else 0
    if not args.write:
        print("（dry-run：未落盘。确认无误后加 --write）")
        return 0
    for _, _, _, want, path in changed:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(want)
    print(f"已覆盖 {len(changed)} 个文件。请跑 tools/check.py 验收。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
