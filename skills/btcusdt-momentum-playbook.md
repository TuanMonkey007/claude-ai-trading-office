# SKILL: BTCUSDT Momentum Playbook (Bitcoin)

> Sách Đỏ Hermes — quy tắc kỷ luật giao dịch Bitcoin (BTC/USDT trên Binance, fallback BTC-USD Yahoo).
> Agent `hermes_scribe` đọc file này TRƯỚC mỗi phiên họp và ghi bài học mới SAU mỗi phiên.

## 1. Bối cảnh & khung thời gian
- BTC chạy 24/7, khung chính `15m`; dùng `1h`/`4h` để xác định xu hướng lớn.
- Biến động mạnh quanh phiên mở cửa Mỹ (20h30 VN) và lúc tin ETF / Fed / CPI.
- Theo dõi funding rate & dòng tiền ETF qua tin tức CryptoCompare trước khi vào lệnh.

## 2. Hệ quy chiếu Momentum
- **EMA 20 > 50 > 200** = xu hướng tăng → chỉ tìm BUY khi giá hồi về EMA20/50 hoặc VWAP.
- **EMA 20 < 50 < 200** = xu hướng giảm → chỉ tìm SELL khi giá hồi lên EMA20/50 hoặc VWAP.
- **Session VWAP** là mốc giá trị trong ngày; breakout kèm volume qua biên ±1.5σ theo hướng xu hướng là tín hiệu momentum.
- **RSI(14)**: vùng 40–60 là vùng nạp đà tốt; RSI > 75 hoặc < 25 → không đuổi lệnh.

## 3. Bộ lọc SMC
- Sweep Swing Low 20 nến rồi đóng nến phục hồi → bẫy Bear → ưu tiên BUY.
- Sweep Swing High 20 nến rồi đóng nến giảm → bẫy Bull → ưu tiên SELL.
- BOS (đóng nến vượt Swing High/Low) xác nhận lực chủ động; chờ retest rồi mới vào.
- Cần **≥ 2/3 chuyên viên** đồng thuận. Nếu Trend và SMC ngược nhau → WAIT.

## 4. Quản trị vốn (bắt buộc)
- Stop Loss = **1.5 × ATR(14)**.
- TP1 = **1.8R**, TP2 = **2.6R**. Chốt 50% tại TP1, dời SL về hòa vốn.
- Rủi ro **1% quỹ / lệnh**. Lot (BTC) = (Quỹ × 1%) / khoảng SL.
- Không dùng đòn bẩy quá 5x. Không mở quá 2 lệnh BTC cùng chiều.

## 5. Điều cấm
- Không FOMO khi nến 15m tăng/giảm > 2% trong 1 nến; chờ nến tiếp theo.
- Không vào lệnh khi ATR(14) > 2% giá trừ khi 3/3 phiếu đồng thuận.
- Không giao dịch ngược xu hướng 4h nếu confidence < 80%.

## Nhật ký Tự Học (Hermes Loop)
- [2026-01-01 00:00:00] (WAIT 50%) Khởi tạo sổ tay. Mọi bài học sau mỗi phiên họp sẽ được Hermes ghi nối tiếp bên dưới.
- [2026-10-23 19:14:53] (SELL 85%) [BTCUSDT SIDEWAY] SELL | Phiếu: VWAP=SELL, SMC=SELL, Trend=SELL | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:21:34] (SELL 71%) [BTCUSDT SIDEWAY] SELL | Phiếu: VWAP=SELL, SMC=WAIT, Trend=SELL | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:27:16] (WAIT 52%) [BTCUSDT SIDEWAY] WAIT | Phiếu: VWAP=BUY, SMC=SELL, Trend=WAIT | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:33:21] (BUY 71%) [BTCUSDT SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:34:37] (BUY 71%) [BTCUSDT SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:40:52] (BUY 72%) Khi thị trường sideway và giá sát kháng cự Swing High, chỉ giải ngân BUY khi có 2/3 phiếu đồng thuận và RSI dưới 70, luôn tuân thủ dừng lỗ 1.5x ATR để phòng ngừa quét râu.
- [2026-10-23 19:51:20] (WAIT 70%) Chỉ vào lệnh khi có ít nhất 2 phiếu đồng thuận và tránh giao dịch khi không có breakout rõ ràng.
- [2026-10-23 20:10:27] (WAIT 60%) Chỉ vào lệnh khi có ít nhất 2 trong 3 chuyên viên đồng thuận và không vi phạm quy tắc kỷ luật; nếu chưa đạt, cần chờ tín hiệu breakout rõ ràng.
- [2026-10-23 20:15:52] (WAIT 70%) Cần ít nhất 2/3 phiếu đồng thuận mới vào lệnh, tránh giao dịch khi chỉ có một quan điểm hỗ trợ để giảm rủi ro.
- [2026-10-23 20:22:54] (BUY 72%) Trong biên độ Sideway, khi giá vượt trên Session VWAP và đạt 2/3 phiếu đồng thuận BUY với RSI < 70, ưu tiên giao dịch theo dòng tiền và đặt SL chuẩn 1.5x ATR để tránh quét râu nhiễu.
- [2026-10-23 20:54:15] (WAIT 70%) Chỉ vào lệnh khi có ít nhất 2/3 chuyên viên đồng thuận và tránh mua khi giá đã vượt quá ngưỡng +1.5σ mà chưa có dấu hiệu quay lại.
- [2026-10-23 21:13:21] (BUY 78%) Khi có đa số đồng thuận mua nhưng giá vẫn dưới VWAP, cần cân nhắc mức discount và không vội vào lệnh nếu không có breakout rõ ràng; chờ xác nhận giá chạm hoặc vượt VWAP để tăng độ tin cậy.
- [2026-10-23 21:44:48] (WAIT 65%) Chỉ vào lệnh khi có ít nhất 2/3 chuyên viên đồng thuận và có breakout rõ ràng để tránh rủi ro khi thị trường còn trong vùng side‑way.
- [2026-10-23 21:58:15] (BUY 75%) Khi có sự đồng thuận 2/3 từ các chuyên viên về xu hướng và VWAP, cần tuân thủ mở lệnh theo đà dòng tiền nhưng phải quản trị chặt chẽ bằng SL chuẩn 1.5x ATR.
