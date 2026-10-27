# SKILL: XAUUSD VWAP Playbook (Vàng)

> Sách Đỏ Hermes — quy tắc kỷ luật giao dịch Vàng (XAU/USD, proxy PAXGUSDT / GC=F).
> Agent `hermes_scribe` đọc file này TRƯỚC mỗi phiên họp và ghi bài học mới SAU mỗi phiên.

## 1. Bối cảnh & khung thời gian
- Khung phân tích chính: `15m` (có thể đổi 5m / 1h / 4h trong Cài đặt).
- Vàng nhạy với DXY, lợi suất trái phiếu 10 năm, tin Fed/CPI/NFP. Tránh vào lệnh 15 phút trước và sau tin đỏ.
- Phiên có thanh khoản tốt nhất: London (14h–17h VN) và New York (19h30–23h VN).

## 2. Hệ quy chiếu VWAP
- **Session VWAP** là trục giá trị của ngày. Giá trên VWAP → ưu tiên BUY; giá dưới VWAP → ưu tiên SELL.
- **Biên trên +1.5σ**: vùng quá mua theo dòng tiền. KHÔNG BUY đuổi tại đây, chờ hồi về VWAP.
- **Biên dưới -1.5σ**: vùng quá bán. KHÔNG SELL đuổi, chờ nảy về VWAP.
- Setup đẹp nhất: giá hồi về chạm VWAP trong xu hướng EMA rõ ràng và nảy lại (VWAP bounce).

## 3. Bộ lọc xác nhận
- **EMA 20 / 50 / 200** phải xếp tầng cùng hướng với lệnh (20>50>200 cho BUY, ngược lại cho SELL).
- **RSI(14)**: không BUY khi RSI > 72, không SELL khi RSI < 28.
- **SMC**: ưu tiên lệnh sau khi có Liquidity Sweep (quét Swing High/Low 20 nến rồi đóng ngược) hoặc BOS cùng hướng.
- Cần **≥ 2/3 chuyên viên** (VWAP, SMC, Trend) đồng thuận mới được vào lệnh. Mâu thuẫn → WAIT.

## 4. Quản trị vốn (bắt buộc)
- Stop Loss = **1.5 × ATR(14)** tính từ entry.
- Take Profit 1 = **1.8R**, Take Profit 2 = **2.6R**. Chốt 50% tại TP1, dời SL về hòa vốn.
- Rủi ro tối đa **1% quỹ / lệnh**. Lot = (Quỹ × 1%) / (khoảng SL × 100 oz).
- Tối đa 2 lệnh Vàng mở cùng lúc. Thua 3 lệnh liên tiếp → nghỉ hết ngày.

## 5. Điều cấm
- Không gỡ lỗ bằng cách tăng lot.
- Không dời SL ra xa hơn kế hoạch ban đầu.
- Không giao dịch khi ATR(14) > 1.5% giá (biến động bất thường) trừ khi có xác nhận 3/3 phiếu.

## Nhật ký Tự Học (Hermes Loop)
- [2026-01-01 00:00:00] (WAIT 50%) Khởi tạo sổ tay. Mọi bài học sau mỗi phiên họp sẽ được Hermes ghi nối tiếp bên dưới.
- [2026-10-23 19:13:38] (WAIT 50%) [XAUUSD DOWNTREND] WAIT | Phiếu: VWAP=BUY, SMC=WAIT, Trend=SELL | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:21:01] (WAIT 60%) [XAUUSD SIDEWAY] WAIT | Phiếu: VWAP=BUY, SMC=WAIT, Trend=WAIT | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:26:11] (BUY 71%) [XAUUSD SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:26:43] (BUY 71%) [XAUUSD SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:32:49] (BUY 71%) [XAUUSD SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:34:06] (BUY 71%) [XAUUSD SIDEWAY] BUY | Phiếu: VWAP=BUY, SMC=WAIT, Trend=BUY | Kỷ luật: chỉ vào lệnh khi ≥2 phiếu đồng thuận, SL=1.5×ATR, không giao dịch khi RSI cực đoan (>72 hoặc <28).
- [2026-10-23 19:40:12] (WAIT 70%) Chỉ vào lệnh khi có ít nhất 2/3 chuyên viên đồng thuận để tránh giao dịch trong môi trường không xác định.
- [2026-10-23 19:50:36] (BUY 82%) Khi ít nhất 2 chuyên viên đồng thuận mua và không có tín hiệu bán rõ ràng, nên tuân thủ vào lệnh ngay sau khi giá xác nhận trên VWAP và EMA hỗ trợ, đồng thời giữ kỷ luật SL và TP theo quy tắc.
- [2026-10-23 20:09:46] (WAIT 75%) Luôn tuân thủ quy tắc đồng thuận 2/3 chuyên viên; tuyệt đối không vào lệnh khi thị trường Sideway và các chỉ báo kỹ thuật mâu thuẫn.
- [2026-10-23 20:15:13] (WAIT 70%) Luôn tuân thủ quy tắc EMA xếp tầng; dù có đồng thuận chuyên viên, nếu điều kiện này không đáp ứng thì nên chờ.
- [2026-10-23 20:22:03] (BUY 82%) Khi giá tiếp cận biên trên +1.5σ, dù có tín hiệu mua, cần kiên trì chờ phản hồi về VWAP để tránh mua ở mức quá mua.
- [2026-10-23 20:53:39] (WAIT 80%) Tuyệt đối giữ kỷ luật WAIT khi nhận thấy sự phân hóa hoàn toàn giữa 3 chuyên viên (1 BUY, 1 WAIT, 1 SELL) và các đường EMA đan quấn trong vùng Sideway.
- [2026-10-23 21:12:46] (WAIT 70%) Luôn tuân thủ quy tắc RSI; ngay cả khi đa số chuyên viên đồng thuận bán, nếu RSI <28 thì phải chờ để tránh vi phạm kỷ luật.
- [2026-10-23 21:44:06] (SELL 80%) Luôn chờ đồng thuận ít nhất 2/3 chuyên viên và không vào lệnh khi chỉ có một tín hiệu mạnh mà các chỉ báo khác chưa khớp.
- [2026-10-23 21:57:22] (SELL 85%) Khi các chỉ báo dòng tiền (VWAP) và xu hướng (EMA) đồng thuận giảm, đồng thời không vi phạm ngưỡng RSI quá bán, việc vào lệnh theo dòng chủ đạo mang lại xác suất thắng cao.
