#!/usr/bin/env bash
# update-from-mac.sh
# Chạy trên Mac: commit & push code lên GitHub, sau đó deploy lên VPS Windows.
# Dùng: ./update-from-mac.sh "commit message"   (bỏ trống để tự sinh message)
#
# Cấu hình VPS (VPS_USER, VPS_HOST, VPS_SSH_PORT, VPS_DEPLOY_SCRIPT) đặt trong
# .deploy.env (xem .deploy.env.example, đã bị .gitignore) — không hardcode IP ở đây.
# Trước khi `git add -A`, script in danh sách file và TỪ CHỐI nếu thấy file nghi chứa
# bí mật (.env, .deploy.env, data/, *.db, API key / bot token trong nội dung).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if [ -f .deploy.env ]; then
    set -a; . ./.deploy.env; set +a
fi
VPS_USER="${VPS_USER:-Administrator}"
VPS_HOST="${VPS_HOST:-}"
VPS_SSH_PORT="${VPS_SSH_PORT:-22}"
VPS_DEPLOY_SCRIPT="${VPS_DEPLOY_SCRIPT:-C:/ai-office/deploy-windows.ps1}"
MSG="${1:-}"

echo "=== Update from Mac → GitHub → VPS Windows ==="

# 1. Kiểm tra có thay đổi không
if [[ -z $(git status --porcelain) ]]; then
    echo "✅ Không có thay đổi nào để commit."
    exit 0
fi

echo "📝 Các file sẽ được commit (git add -A):"
git status --short --untracked-files=all

# 2. Chặn file nghi chứa bí mật (tên file + nội dung)
FILES=()
while IFS= read -r -d '' f; do FILES+=("$f"); done < <(
    { git diff -z --name-only --diff-filter=d HEAD 2>/dev/null || true
      git ls-files -z --others --exclude-standard; } | sort -zu
)

BAD=()
for f in ${FILES[@]+"${FILES[@]}"}; do
    base="${f##*/}"
    case "$f" in
        data/*|*/data/*)                         BAD+=("$f  (thư mục data/)"); continue ;;
    esac
    case "$base" in
        *.example)                               ;;
        .env|.env.*|.deploy.env|.deploy.env.*)   BAD+=("$f  (file môi trường)"); continue ;;
        *.db|*.db-*|*.sqlite|*.sqlite3)          BAD+=("$f  (cơ sở dữ liệu)"); continue ;;
    esac
    if [ -f "$f" ] && grep -IqE 'AIza[0-9A-Za-z_-]{30,}|gsk_[A-Za-z0-9]{20,}|sk-or-[A-Za-z0-9_-]{20,}|[0-9]{8,10}:[A-Za-z0-9_-]{35}' -- "$f"; then
        BAD+=("$f  (nội dung giống API key / bot token)")
    fi
done

if [ "${#BAD[@]}" -gt 0 ]; then
    echo "❌ Từ chối commit: phát hiện file nghi chứa bí mật:"
    printf '   - %s\n' "${BAD[@]}"
    echo "   Gỡ bí mật / thêm vào .gitignore rồi chạy lại. Không có gì được add hay commit."
    exit 1
fi

# 3. Commit (set -e: lỗi là dừng, không push / deploy)
if [[ -z "$MSG" ]]; then
    MSG="Update $(date '+%Y-%m-%d %H:%M')"
fi
git add -A
if ! git commit -m "$MSG"; then
    echo "❌ git commit thất bại. Dừng, không push / deploy."
    exit 1
fi

# 4. Push lên GitHub
echo "📤 Push lên GitHub..."
if ! git push origin main; then
    echo "❌ git push thất bại. Commit vẫn nằm ở máy local; sửa lỗi rồi push lại. Không deploy."
    exit 1
fi

# 5. Deploy trên VPS Windows
if [[ -z "$VPS_HOST" ]]; then
    echo "⚠️ Chưa đặt VPS_HOST trong .deploy.env (xem .deploy.env.example). Code đã push GitHub."
    echo "   Trên VPS chạy thủ công: powershell -ExecutionPolicy Bypass -File ${VPS_DEPLOY_SCRIPT}"
    exit 1
fi

echo "🚀 Deploy trên VPS Windows..."
if ! nc -vz -G 5 "${VPS_HOST}" "${VPS_SSH_PORT}" 2>/dev/null; then
    echo "⚠️ SSH ${VPS_HOST}:${VPS_SSH_PORT} không tiếp cận được."
    echo "   Code đã push GitHub. Sau khi VPS chạy, chạy thủ công:"
    echo "   powershell -ExecutionPolicy Bypass -File ${VPS_DEPLOY_SCRIPT}"
    exit 0
fi

ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "${VPS_SSH_PORT}" \
    "${VPS_USER}@${VPS_HOST}" \
    "powershell -ExecutionPolicy Bypass -File ${VPS_DEPLOY_SCRIPT}"

echo "✅ Hoàn tất update + deploy!"
