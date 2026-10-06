#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""协作通道一致性巡检（WB2 建，2026-10-06）

做什么：
    比对三处镜像的**文件清单与 md5**——WB2 权威镜像 / WB4 本地镜像 / 香港服务器，
    报出「某处缺件」与「md5 不一致」。覆盖 `WB4-to-WB2/` 与 `WB2-to-WB4/` 两个通道目录。

为什么要有它：
    W5 裁定「三方同步是发出方义务」，但已两次复发（106 只落本地两处、117 报三处而 WB2 镜像缺），
    每次都是**接收方兜底补齐**。人眼核不住，就把它变成机器巡检——判例 15：
    同一判定逻辑只许一处实现；能机器判的，别用人判。

用法：
    python tools/handoff_audit.py            # 全量巡检
    python tools/handoff_audit.py --quiet    # 只报问题（供定时/提交前钩子用）

退出码：0 = 三处完全一致；1 = 有缺件或 md5 不一致；2 = 连不上服务器（无法判定）
"""
import hashlib
import os
import subprocess
import sys

KEY = os.path.expanduser("~/.ssh/id_ed25519_hk")
HOST = "root@43.132.236.108"
REMOTE_BASE = "/opt/knowledge-base/handoff"
BASE = "C:/Users/Administrator/WorkBuddy"
MIRROR_A = BASE + "/2026-09-19-08-45-55/私密空间/handoff"   # WB2 权威镜像
MIRROR_B = BASE + "/deepseek-wb4/私密空间/handoff"          # WB4 本地镜像
CHANNELS = ["WB4-to-WB2", "WB2-to-WB4"]
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15"]
SKIP = {"交接日志.md"}  # 追加型共用日志：三处本就允许不同（各方在自己那侧追加）


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def local_listing(root):
    """目录 → {文件名: md5}（只收文件，跳过子目录）。"""
    out = {}
    d = os.path.join(root)
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if os.path.isfile(p) and name not in SKIP:
            out[name] = md5_file(p)
    return out


def remote_listing(channel):
    """服务器侧目录 → {文件名: md5}；连不上时返回 None。"""
    cmd = ["ssh"] + SSH_OPTS + ["-i", KEY, HOST,
           f"cd '{REMOTE_BASE}/{channel}' 2>/dev/null && md5sum * 2>/dev/null"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60,
                           encoding="utf-8", errors="replace")
    except Exception as exc:            # noqa: BLE001
        print(f"[连不上] {channel}：{exc}")
        return None
    if r.returncode != 0 and not r.stdout.strip():
        print(f"[服务器无此目录或为空] {channel}（rc={r.returncode}）")
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            digest, name = parts
            name = name.lstrip("*").strip()
            if name not in SKIP:
                out[name] = digest
    return out


def audit(quiet=False):
    print("协作通道一致性巡检 · 权威镜像 / WB4 镜像 / 香港服务器")
    print("=" * 64)
    problems = 0
    unreachable = 0
    for ch in CHANNELS:
        a = local_listing(os.path.join(MIRROR_A, ch))
        b = local_listing(os.path.join(MIRROR_B, ch))
        s = remote_listing(ch)
        if s is None:
            unreachable += 1
            continue
        names = sorted(set(a) | set(b) | set(s))
        row_problems = []
        for n in names:
            where = []
            if n not in a:
                where.append("权威镜像缺")
            if n not in b:
                where.append("WB4镜像缺")
            if n not in s:
                where.append("服务器缺")
            vals = {k: v for k, v in (("权威", a.get(n)), ("WB4", b.get(n)), ("服务器", s.get(n))) if v}
            if len(set(vals.values())) > 1:
                where.append("md5 不一致（" + " / ".join(f"{k}={v[:8]}" for k, v in vals.items()) + "）")
            if where:
                row_problems.append((n, "；".join(where)))
        flag = "✅" if not row_problems else "⚠️"
        print(f"\n{flag} {ch}  权威 {len(a)} / WB4 {len(b)} / 服务器 {len(s)} 个文件")
        if row_problems:
            problems += len(row_problems)
            for n, why in row_problems:
                print(f"     ✗ {n}\n        → {why}")

    print("\n" + "=" * 64)
    if unreachable:
        print(f"⚠️ 有 {unreachable} 个通道连不上服务器——本次**无法判定**，请重跑")
        return 2
    if problems:
        print(f"⚠️ 发现 {problems} 处不一致。修复原则（判例 15 / W5）：")
        print("   · 缺件 → 以**存在处**为准补齐其余两处（纯镜像动作）；")
        print("   · 由**发出方**补齐并披露，接收方不长期兜底（W5：同步是发出方义务）；")
        print("   · 补完重跑本脚本，须三方一致。")
        return 1
    print("✅ 三处完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(audit(quiet="--quiet" in sys.argv))
