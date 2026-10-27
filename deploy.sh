#!/usr/bin/env bash
# ============================================================================
# deploy.sh — Đẩy code từ Mac lên server CentOS (Docker compose) rồi restart.
#
#   ./deploy.sh              # đẩy file đã đổi + restart + health check
#   ./deploy.sh --dry-run     # chỉ LIỆT KÊ file sẽ đẩy, không thay đổi gì
#   ./deploy.sh --skills      # đẩy cả skills/ (GHI ĐÈ nhật ký tự học trên server!)
#   ./deploy.sh --no-restart  # đẩy file nhưng không restart
#   ./deploy.sh --setup-key   # cài SSH key (1 lần) để lần sau KHÔNG hỏi mật khẩu
#
# SSH: script dùng ControlMaster nên dù chưa cài key cũng chỉ hỏi mật khẩu
# MỘT lần cho mỗi lần chạy. Cài key bằng --setup-key để không hỏi nữa.
#
# Cấu hình trong .deploy.env (xem .deploy.env.example). KHÔNG bao giờ đẩy
# data/ và .env: đó là DB, config.json (chứa API key) và mật khẩu dashboard
# đang sống trên server.
# ============================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

DRY=0
SKILLS_FORCE=0
RESTART=1
SETUP_KEY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY=1 ;;
    --skills)     SKILLS_FORCE=1 ;;
    --no-restart) RESTART=0 ;;
    --setup-key)  SETUP_KEY=1 ;;
    -h|--help)    sed -n '3,15p' "$0"; exit 0 ;;
    *) echo "Tham số lạ: $arg (dùng --help)"; exit 2 ;;
  esac
done

# ---- nạp cấu hình ----
if [ -f .deploy.env ]; then
  set -a; . ./.deploy.env; set +a
fi
: "${SERVER_USER:=root}"
: "${SERVER_HOST:?Chưa đặt SERVER_HOST trong .deploy.env}"
: "${SSH_PORT:=22}"
: "${REMOTE_DIR:=/home/ai-office}"
: "${HEALTH_URL:=http://127.0.0.1:8080/api/health}"
: "${SYNC_SKILLS:=0}"
[ "$SKILLS_FORCE" = 1 ] && SYNC_SKILLS=1

# Một phiên SSH dùng chung (ControlMaster): chỉ hỏi mật khẩu MỘT lần cho cả
# rsync + restart + health check, thay vì hỏi lại ở mỗi kết nối.
CTL_PATH="${TMPDIR:-/tmp}/aito-ssh-%r@%h:%p"
SSH_OPTS=(-p "${SSH_PORT}" -o ControlMaster=auto -o "ControlPath=${CTL_PATH}" -o ControlPersist=60)
SSH=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")
RSYNC_SSH="ssh ${SSH_OPTS[*]}"
TARGET="${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

command -v rsync >/dev/null 2>&1 || { echo "❌ Mac thiếu rsync."; exit 1; }

if [ "$SETUP_KEY" = 1 ]; then
  if [ ! -f "$HOME/.ssh/id_ed25519.pub" ] && [ ! -f "$HOME/.ssh/id_rsa.pub" ]; then
    echo "→ Chưa có SSH key, tạo mới (~/.ssh/id_ed25519)..."
    ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519"
  fi
  echo "→ Cài SSH public key lên ${SERVER_USER}@${SERVER_HOST} (hỏi mật khẩu 1 lần cuối)..."
  if ssh-copy-id -p "${SSH_PORT}" "${SERVER_USER}@${SERVER_HOST}"; then
    echo "✅ Đã cài key. Từ giờ ./deploy.sh sẽ KHÔNG hỏi mật khẩu nữa."
    exit 0
  fi
  echo "❌ Cài key thất bại."; exit 1
fi

cleanup() { ssh "${SSH_OPTS[@]}" -O exit "${SERVER_USER}@${SERVER_HOST}" >/dev/null 2>&1 || true; }
trap cleanup EXIT
# Mở master trước (hỏi mật khẩu 1 lần nếu chưa có key), các lệnh sau tái dùng socket.
ssh "${SSH_OPTS[@]}" -fN "${SERVER_USER}@${SERVER_HOST}"

# ---- tập loại trừ (bảo vệ dữ liệu sống trên server) ----
EXCLUDES=(
  --exclude 'data/'
  --exclude '.env'
  --exclude '.git/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.DS_Store'
  --exclude '*.log'
  --exclude 'office.db*'
  --exclude '.deploy.env'
)
if [ "$SYNC_SKILLS" != "1" ]; then
  EXCLUDES+=( --exclude 'skills/' )   # giữ nhật ký Hermes tự học trên server
fi

echo "→ Server : ${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}  (Docker compose)"
[ "$SYNC_SKILLS" = "1" ] && echo "⚠ SYNC_SKILLS=1: sẽ GHI ĐÈ skills/ trên server (mất bài học tự học mới)."

if [ "$DRY" = 1 ]; then
  echo "→ CHẾ ĐỘ THỬ (không thay đổi gì). Các file SẼ được đẩy:"
  rsync -azn --itemize-changes "${EXCLUDES[@]}" -e "$RSYNC_SSH" ./ "$TARGET" \
    | grep -E '^[<>ch]' || true
  echo "→ (Bỏ chú thích --dry-run để đẩy thật.)"
  exit 0
fi

if ! "${SSH[@]}" "command -v rsync >/dev/null 2>&1"; then
  echo "❌ Server chưa có rsync. Chạy trên server:  yum install -y rsync"
  exit 1
fi

echo "→ Đang đẩy file thay đổi..."
CHANGED="$(rsync -az --itemize-changes --delete "${EXCLUDES[@]}" -e "$RSYNC_SSH" ./ "$TARGET" \
  | grep -vE '^\.d' || true)"
if [ -n "$CHANGED" ]; then
  echo "$CHANGED"
  echo "→ $(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ') mục đã cập nhật."
else
  echo "→ Không có file nào thay đổi."
fi

if [ "$RESTART" = 0 ]; then
  echo "→ Bỏ qua restart (--no-restart). Nhớ restart để nạp server.py mới."
  exit 0
fi

echo "→ Restart Docker compose trên server..."
"${SSH[@]}" "cd '${REMOTE_DIR}' && { docker compose restart || docker compose up -d; }"

echo "→ Health check..."
sleep 3
if "${SSH[@]}" "curl -fsS '${HEALTH_URL}'" >/dev/null 2>&1; then
  echo "✅ Xong. Server đã chạy code mới."
else
  echo "⚠ Health check thất bại. Xem log: ssh -p ${SSH_PORT} ${SERVER_USER}@${SERVER_HOST} \"cd ${REMOTE_DIR} && docker compose logs --tail=50\""
  exit 1
fi
