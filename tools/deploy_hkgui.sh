#!/usr/bin/env bash
# 《董老师香港留学指南2026》自有域名主站 · 一键部署
# =================================================
# 用法：  tools/deploy_hkgui.sh            # 构建 + 全量推送
#         tools/deploy_hkgui.sh --dry      # 只构建，看差异不推送
#
# 站点：https://hkgui.xinfide.com  →  服务器 /var/www/hkgui（腾讯云香港 43.132.236.108）
# 说明：内容源与关键词表都在本仓库，**同一事实只一处实现**：
#       release/定稿-董老师香港留学指南.md（正文）、meta/seo-keywords.json（SEO 与聚合页）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$ROOT/_site-hkgui"
HOST="root@43.132.236.108"
KEY="$HOME/.ssh/id_ed25519_hk"
REMOTE_DIR="/var/www/hkgui"
BASE="https://hkgui.xinfide.com/"
PY="${PY:-python3}"

DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

echo "① 构建（关键词表 + 聚合页 + 留言/统计）"
rm -rf "$OUT"
"$PY" "$HERE/build_web.py" \
  --md "$ROOT/release/定稿-董老师香港留学指南.md" \
  --out "$OUT" \
  --base "$BASE" \
  --seo-map "$ROOT/meta/seo-keywords.json" \
  --feedback

echo "①.5 AI 可读层（llms.txt / llms-full.txt / 404.html）"
# 仓库根的 llms.txt 是 GitHub 站的单一来源，其中的相对链接（./book/*.md、./docs/…）
# 在自有域名站上是死链；build_ai_hkgui.py 只重写链接目标，事实与数字一字不动。
"$PY" "$HERE/build_ai_hkgui.py" --out "$OUT" --base "$BASE"

echo "② 本地自检"
for f in index.html sitemap.xml robots.txt llms.txt llms-full.txt 404.html hk-002.html hub-undergrad.html; do
  [ -f "$OUT/$f" ] || { echo "  ✗ 缺文件：$f"; exit 1; }
done
echo "  文件数：$(ls "$OUT" | wc -l) · sitemap URL：$(grep -c '<url>' "$OUT/sitemap.xml")"

if [ "$DRY" = "1" ]; then
  echo "③ --dry：跳过推送。产物在 $OUT"
  exit 0
fi

echo "③ 推送 → $HOST:$REMOTE_DIR"
# 本机（Windows/Git Bash）没有 rsync，服务器有：打包用 tar 送上去，再在服务器端
# 用 rsync 做增量+删除，保证远端与本地产物严格一致。
# BingSiteAuth.xml 是 GitHub 站的验证文件（token 与站点绑定），不带过来；
# 自有域名站的 Bing 验证走 DNS TXT。IndexNow 密钥文件照带。
SSHOPT="ssh -i $KEY -o StrictHostKeyChecking=no"
ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" 'rm -rf /var/www/hkgui.new && mkdir -p /var/www/hkgui.new'
tar czf - -C "$OUT" --exclude 'BingSiteAuth.xml' . \
  | ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" 'tar xzf - -C /var/www/hkgui.new'
ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" \
  'rsync -a --delete /var/www/hkgui.new/ /var/www/hkgui/ && rm -rf /var/www/hkgui.new && chown -R ubuntu:ubuntu /var/www/hkgui'

echo "④ 线上自检（DNS 未生效时用 Host 头直连服务器）"
curl -s -o /dev/null -w "  首页 HTTP:%{http_code}\n" -m 15 "$BASE" 2>/dev/null || true
curl -s -o /dev/null -w "  Host 头直连 HTTP:%{http_code}\n" -m 15 \
  -H "Host: hkgui.xinfide.com" "http://43.132.236.108/" || true
curl -s -m 15 -H "Host: hkgui.xinfide.com" "http://43.132.236.108/api/health" && echo ""
echo "✓ 部署完成：$BASE"
