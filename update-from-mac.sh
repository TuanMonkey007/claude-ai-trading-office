#!/usr/bin/env bash
# update-from-mac.sh
# Chạy trên Mac: commit & push code lên GitHub, sau đó deploy lên VPS Windows.
# Dùng: ./update-from-mac.sh "commit message"   (bỏ trống để tự sinh message)

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# Cấu hình (có thể override bằng biến môi trường hoặc tham số)
VPS_USER="${VPS_USER:-Administrator}"
VPS_HOST="${VPS_HOST:-180.93.54.27}"
VPS_SSH_PORT="${VPS_SSH_PORT:-22}"
VPS_DEPLOY_SCRIPT="${VPS_DEPLOY_SCRIPT:-C:/ai-office/deploy-windows.ps1}"
MSG="${1:-}"

echo "=== Update from Mac → GitHub → VPS Windows ==="

# 1. Kiểm tra có thay đổi không
if [[ -z $(git status --porcelain) ]]; then
    echo "✅ Không có thay đổi nào để commit."
    exit 0
fi

echo "📝 Các file thay đổi:"
git status --short

# 2. Commit
if [[ -z "$MSG" ]]; then
    MSG="Update $(date '+%Y-%m-%d %H:%M')"
fi
git add -A
git commit -m "$MSG"

# 3. Push lên GitHub
echo "📤 Push lên GitHub..."
git push origin main

# 4. Deploy trên VPS Windows
echo "🚀 Deploy trên VPS Windows..."
if ! nc -vz -G 5 "${VPS_HOST}" "${VPS_SSH_PORT}" 2>/dev/null; then
    echo "⚠️ SSH ${VPS_HOST}:${VPS_SSH_PORT} không tiếp cận được."
    echo "   Code đã push GitHub. Sau khi VPS chạy, chạy thủ công:"
    echo "   powershell -ExecutionPolicy Bypass -File C:/ai-office/deploy-windows.ps1"
    exit 0
fi

ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "${VPS_SSH_PORT}" \
    "${VPS_USER}@${VPS_HOST}" \
    "powershell -ExecutionPolicy Bypass -File ${VPS_DEPLOY_SCRIPT}"

echo "✅ Hoàn tất update + deploy!"