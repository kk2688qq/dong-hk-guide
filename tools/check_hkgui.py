#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hkgui 站点质检：sitemap↔文件、canonical 自指、JSON-LD 合法性、站内死链、元信息。
在服务器上对 /var/www/hkgui 就地检查（无需公网解析）。
2026-10-10 WB2。
"""
import io
import json
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/var/www/hkgui"
BASE = "https://hkgui.xinfide.com"

htmls = sorted(f for f in os.listdir(ROOT) if f.endswith(".html"))
problems = []
stats = {"html": len(htmls), "sitemap_urls": 0, "links_checked": 0,
         "jsonld": 0, "no_title": 0, "no_desc": 0}


def read(p):
    with io.open(os.path.join(ROOT, p), encoding="utf-8") as fh:
        return fh.read()


# ① sitemap ↔ 实际文件
sm = read("sitemap.xml")
urls = re.findall(r"<loc>([^<]+)</loc>", sm)
stats["sitemap_urls"] = len(urls)
for u in urls:
    p = u.replace(BASE + "/", "").strip() or "index.html"
    p = p.split("#")[0].split("?")[0]
    if not os.path.isfile(os.path.join(ROOT, p)):
        problems.append("sitemap 指向的文件不存在：%s" % u)

# sitemap 是否漏了条目页（noindex 的单文件版与 404 页不要求进 sitemap）
in_sm = set(u.replace(BASE + "/", "") for u in urls)
for f in htmls:
    if f in ("404.html",):
        continue
    head_txt = read(f)[:3000]
    if 'name="robots" content="noindex"' in head_txt:
        continue
    if f not in in_sm and not f.startswith(("hub-", "part-")):
        problems.append("条目页未进 sitemap：%s" % f)

# ② 逐页检查
for f in htmls:
    t = read(f)
    noindex = 'name="robots" content="noindex"' in t[:3000]

    # canonical 自指（noindex 页与 404 不要求）
    mc = re.search(r'<link rel="canonical" href="([^"]+)"', t)
    if not noindex and f != "404.html":
        if not mc:
            problems.append("缺 canonical：%s" % f)
        elif mc.group(1) != "%s/%s" % (BASE, f) and mc.group(1) != BASE + "/":
            problems.append("canonical 非自指：%s → %s" % (f, mc.group(1)))

    # title / description
    if not re.search(r"<title>[^<]+</title>", t):
        stats["no_title"] += 1
        problems.append("缺 title：%s" % f)
    if not noindex and not re.search(r'<meta name="description" content="[^"]+"', t):
        stats["no_desc"] += 1
        problems.append("缺 description：%s" % f)

    # JSON-LD 合法性
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
        stats["jsonld"] += 1
        try:
            d = json.loads(m.group(1))
            if not d.get("@type"):
                problems.append("JSON-LD 无 @type：%s" % f)
        except Exception as e:
            problems.append("JSON-LD 解析失败：%s（%s）" % (f, e))

    # 站内链接死链
    for m in re.finditer(r'href="([^"]+)"', t):
        h = m.group(1)
        if h.startswith(("http://", "https://", "mailto:", "#", "javascript:")):
            continue
        p = h.split("#")[0].split("?")[0]
        if not p:
            continue
        stats["links_checked"] += 1
        tgt = p[1:] if p.startswith("/") else os.path.normpath(os.path.join(os.path.dirname(f), p))
        if not os.path.exists(os.path.join(ROOT, tgt)):
            problems.append("死链：%s → %s" % (f, h))

print("=" * 62)
print("hkgui 站点质检报告 · %s" % ROOT)
print("=" * 62)
print("HTML 页数：%d ｜ sitemap URL：%d ｜ 检查站内链接：%d ｜ JSON-LD 块：%d"
      % (stats["html"], stats["sitemap_urls"], stats["links_checked"], stats["jsonld"]))
if stats["no_title"] or stats["no_desc"]:
    print("缺 title：%d ｜ 缺 description：%d" % (stats["no_title"], stats["no_desc"]))
print("-" * 62)
if problems:
    print("发现问题 %d 项：" % len(problems))
    for p in problems[:60]:
        print("  ✗", p)
    if len(problems) > 60:
        print("  … 另有 %d 项" % (len(problems) - 60))
else:
    print("✓ 全部通过：无死链 / canonical 全自指 / JSON-LD 全合法 / 元信息齐全")
