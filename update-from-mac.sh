#!/usr/bin/env bash
# update-from-mac.sh
# Chạy trên Mac: commit & push code lên GitHub, sau đó SSH vào VPS chạy deploy

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# Cấu hình
VPS_USER="Administrator"          # user Windows (thường là Administrator)
VPS_HOST="<VPS_PUBLIC_IP>"        # IP public VPS Windows
VPS_DEPLOY_SCRIPT="C:/ai-office/deploy-windows.ps1"

echo "=== Update from Mac to GitHub + Deploy to VPS ==="

# 1. Kiểm tra git status
if [[ -z $(git status --porcelain) ]]; then
    echo "Không có thay đổi nào để commit."
    exit 0
fi

echo "📝 Các file thay đổi:"
git status --short

# 2. Commit
read -p "Nhập commit message: " MSG
if [[ -z "$MSG" ]]; then
    MSG="Update $(date '+%Y-%m-%d %H:%M')"
fi

git add -A
git commit -m "$MSG"

# 3. Push lên GitHub
echo "📤 Push lên GitHub..."
git push origin main

# 4. Deploy trên VPS Windows qua SSH (PowerShell Remoting hoặc SSH)
echo "🚀 Deploy trên VPS Windows..."
ssh -o StrictHostKeyChecking=accept-new "${VPS_USER}@${VPS_HOST}" \
    "powershell -ExecutionPolicy Bypass -File ${VPS_DEPLOY_SCRIPT}"

echo "✅ Hoàn tất update + deploy!"