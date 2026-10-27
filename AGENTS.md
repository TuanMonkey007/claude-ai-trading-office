# AGENTS.md — Quy ước làm việc cho dự án AI Trading Office

## Ngôn ngữ
- Trả lời người dùng bằng tiếng Việt. Giữ nguyên định dạng số/giá trị gốc.

## Sau MỖI lần thay đổi code (bắt buộc)
1. **Liệt kê rõ những file đã sửa/tạo** ở cuối câu trả lời (đường dẫn tương đối), ví dụ:
   - `server.py`
   - `static/index.html`
2. **Nêu file nào cần đẩy lên server và có cần restart không**, ví dụ:
   - Cần đẩy: `server.py`, `static/index.html` → restart để nạp `server.py` mới.
3. Chạy kiểm tra tối thiểu trước khi báo xong:
   - `python3 -c "import ast; ast.parse(open('server.py',encoding='utf-8').read())"` (cú pháp Python)
   - Nếu sửa JS trong `static/index.html`: trích `<script>` rồi `node --check` (nếu có node).

## Cập nhật lên server
- Server CentOS chạy **Docker compose** tại `/home/ai-office`, code được mount trực tiếp.
- Từ Mac: chạy `./deploy.sh` (đẩy file đã đổi + `docker compose restart` + health check).
  - `./deploy.sh --dry-run` để xem trước; `./deploy.sh --skills` để đẩy cả `skills/` (GHI ĐÈ nhật ký tự học).
- **Không bao giờ đẩy** `data/` (DB + `config.json` chứa API key) hay `.env` (mật khẩu dashboard).
- Sửa `server.py` luôn cần restart container. Sửa `skills/` hoặc `data/config.json` không cần build lại.

## Bảo mật
- Không commit/log API key, bot token, mật khẩu. `data/config.json` chứa secret thật → đã bị `.gitignore` chặn.
- Server mặc định không mật khẩu nếu thiếu `OFFICE_ADMIN_PASSWORD` — luôn nhắc khi mở cổng ra Internet.

## Kiến trúc (bản đồ nhanh)
- `server.py`: backend 100% stdlib. Khối: config → DB (SQLite) → state → market (MT5→Binance→Yahoo) → quant engine (chỉ báo + vote_*) → LLM router (`call_free_llm`) → Hermes SKILL.md → PNG chart → Telegram → workflow 5 bước → HTTP handler.
- `static/index.html`: dashboard 1 file (Canvas 2D + bảng + Cài đặt).
- `mt5/AITradingOffice.mq5`: EA — cầu nối giá + khớp lệnh (DryRun mặc định).
- Thứ tự gọi nhà cung cấp LLM: config `llm_provider_order` (kéo thả trong Cài đặt AI).
