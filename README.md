# 🏢 Văn Phòng AI Trading & Đầu Tư 2D (Multi-Agent Virtual Office)

Hệ thống phân tích **Vàng (XAUUSD)** và **Bitcoin (BTCUSDT)** chạy 24/7, hoàn toàn miễn phí, mô phỏng một công ty đầu tư
dưới dạng bản đồ 2D top-down với 7 phòng ban và 11 nhân vật AI chibi, kèm cơ chế tự học kiểu Hermes (`SKILL.md` Learning Loop).

- **Backend** `server.py`: 100% Python 3 Standard Library (không `pip install`), ~30 MB RAM.
- **Frontend** `static/index.html`: single-file HTML5 + Canvas 2D 1440×810, Dark Mode, 60 fps.
- **Database** SQLite `data/office.db`, cấu hình `data/config.json`, playbook `skills/*.md`.

## Chạy nhanh (macOS / Windows / Linux)

```bash
python3 server.py
```

Mở trình duyệt: <http://localhost:8080>

Không cần API key: hệ thống dùng **Built-in Quant AI** (VWAP + SMC + EMA/RSI + ATR). Nhập key Gemini / Groq / OpenRouter
trong nút **🔑 Cài Đặt** để LLM chủ trì cuộc họp Bull vs Bear.

## CentOS 7 (đặt trong /home)

> Hướng dẫn đầy đủ từng bước, gồm cả port forwarding trên FortiGate cho VPS Exness: xem [DEPLOY-CENTOS.md](DEPLOY-CENTOS.md).

```bash
sudo yum install -y python3            # Python 3.6 có sẵn trên CentOS 7 là đủ
mkdir -p /home/ai-office && cd /home/ai-office
# copy server.py, static/, skills/ vào đây
nohup python3 server.py > office.log 2>&1 &
```

Nếu máy chủ thiếu CA bundle (lỗi SSL): `export OFFICE_INSECURE_SSL=1` trước khi chạy.

Chạy như dịch vụ systemd:

```ini
[Unit]
Description=AI Trading Office
After=network.target
[Service]
WorkingDirectory=/home/ai-office
ExecStart=/usr/bin/python3 /home/ai-office/server.py
Restart=always
Environment=TZ=Asia/Ho_Chi_Minh
[Install]
WantedBy=multi-user.target
```

## Docker

```bash
cp .env.example .env   # sửa OFFICE_ADMIN_PASSWORD
docker compose up -d --build
```

`./data` và `./skills` được mount ra ngoài nên dữ liệu và bài học tự học không mất khi rebuild.

## Cập nhật code lên server (một lệnh từ Mac)

Sau khi đã cài server lần đầu (xem [DEPLOY-CENTOS.md](DEPLOY-CENTOS.md)), mỗi lần sửa code chỉ cần:

```bash
./deploy.sh            # đẩy file đã đổi + restart docker compose + health check
./deploy.sh --dry-run  # xem trước sẽ đẩy file nào, không thay đổi gì
```

- Cấu hình host/đường dẫn trong `.deploy.env` (copy từ `.deploy.env.example`, đã bị `.gitignore`).
- **Không bao giờ đẩy** `data/` (DB + `config.json` chứa key) hay `.env` (mật khẩu dashboard) — script tự loại trừ.
- `skills/` mặc định **không** đẩy để giữ nhật ký tự học Hermes trên server; chỉ đẩy khi cần bằng `./deploy.sh --skills` (sẽ ghi đè).
- Server cần có `rsync` (`yum install -y rsync` nếu thiếu). Sửa `server.py` phải restart container; sửa `skills/`/`data/config.json` thì không.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `OFFICE_PORT` | `8080` | Cổng HTTP |
| `OFFICE_HOST` | `0.0.0.0` | Địa chỉ bind |
| `OFFICE_STEP_DELAY` | `2.5` | Giây nghỉ giữa các bước để nhân vật kịp di chuyển |
| `OFFICE_INSECURE_SSL` | – | `1` để bỏ xác thực SSL (CentOS 7 cũ) |
| `OFFICE_HTTP_LOG` | – | `1` để in log HTTP |
| `OFFICE_ADMIN_PASSWORD` | – | Mật khẩu dashboard (HTTP Basic Auth). Bắt buộc khi mở cổng ra Internet |
| `OFFICE_ADMIN_USER` | `admin` | Tên đăng nhập dashboard |

## Nguồn dữ liệu miễn phí

| Dữ liệu | Nguồn chính | Fallback |
|---|---|---|
| Nến OHLCV 5m/15m/1h/4h | Binance `/api/v3/klines` (`PAXGUSDT`, `BTCUSDT`) | Yahoo Finance Chart (`GC=F`, `BTC-USD`) |
| Biến động 24h | Binance `/api/v3/ticker/24hr` | Tính từ nến Yahoo |
| Tin tức vĩ mô | CryptoCompare `/data/v2/news/` (cần key miễn phí, tuỳ chọn) | RSS Yahoo Finance (GC=F, BTC-USD) → CoinDesk → CoinTelegraph → tin offline |

Chỉ báo tự tính bằng Python thuần: Session VWAP ±1.5σ, EMA 20/50/200, RSI(14), ATR(14), Swing High/Low 20 nến,
Liquidity Sweep, BOS.

## MetaTrader 5 trên VPS Exness: một EA duy nhất `mt5/AITradingOffice.mq5`

Binance/Yahoo chỉ cho giá PAXG hoặc GC=F, lệch vài USD so với XAUUSD của broker và trễ tới 45 giây.
EA `mt5/AITradingOffice.mq5` chạy trong MetaTrader 5 trên VPS (không cần cài Python) và làm hai việc:

1. **Cầu nối giá realtime** (mặc định BẬT): đẩy bid/ask mỗi 1 giây và nến 5m/15m/1h/4h mỗi 15 giây lên `POST /api/push_price`. Server **ưu tiên MT5 → Binance → Yahoo**; bridge ngừng quá `bridge_stale_sec` (mặc định 90s) thì tự về Binance, chạy lại thì tự về MT5. Thẻ ticker hiện "🟢 MT5 realtime" kèm Bid / Ask / Spread, header hiện "MT5 ✓", xem `GET /api/bridge/status`.
2. **Khớp lệnh demo** (mặc định TẮT bằng `DryRun=true`): hỏi `GET /api/signals?limit=5` mỗi `PollSeconds` giây, chỉ vào **kèo mới** (id lớn hơn id đã xử lý, nhớ trong GlobalVariable `AITO_LastId_<magic>` nên restart không đặt trùng), action BUY/SELL, `confidence ≥ MinConfidence`, tuổi kèo < `MaxSignalAgeSec` (tính theo đồng hồ server qua `/api/health`).

### Cài đặt

1. Copy `mt5/AITradingOffice.mq5` vào `MQL5/Experts/` (File > Open Data Folder), mở MetaEditor và nhấn **Compile** (F7).
2. **Tools > Options > Expert Advisors**: tick **Allow WebRequest for listed URL**, bấm **Add** thêm `http://IP_SERVER:8080` (đúng scheme + host + port như input `ServerUrl`, **không** có dấu `/` cuối). Thiếu bước này `WebRequest` trả lỗi 4014 và EA ghi rõ trong tab Experts. Tick thêm **Allow automated trading** chỉ khi muốn EA đặt lệnh.
3. Kéo EA vào một chart bất kỳ. **EA chỉ có 3 input**: `ServerUrl` (bắt buộc), `BridgeToken` (nếu server đặt token), `ConfigRefreshSec` (mặc định 60).
4. **Mọi cấu hình khác chỉnh trên web**: nút 🔑 Cài Đặt > mục "8. EA MetaTrader 5". EA tải lại mỗi `ConfigRefreshSec` giây và áp dụng ngay, không cần vào lại EA. Header dashboard hiện "EA ✓ hh:mm" là thời điểm EA tải cấu hình gần nhất.
5. **Chỉ cần giá realtime**: để nguyên mặc định (Đẩy giá = Bật, DryRun). Góc chart hiện trạng thái bridge và cấu hình đang dùng.
6. **Muốn thử khớp lệnh trên demo**: bật nút **Algo Trading** trong MT5, trên web chọn "Chế độ khớp lệnh = Thật" **và** "Cho phép đặt lệnh = Bật".

### Cấu hình EA trên server (`GET /api/ea/config`)

Lưu trong `data/config.json` với tiền tố `ea_`, EA nhận JSON phẳng không có tiền tố:

| Mục trên web / key | Mặc định | Ý nghĩa |
|---|---|---|
| Symbol vàng / BTC (`gold_symbol`, `btc_symbol`) | `XAUUSDm` / `BTCUSDm` | Tên symbol trong Market Watch của broker; BTC trống = lấy từ Binance |
| Đẩy giá realtime (`enable_price_bridge`) | Bật | Cầu nối giá lên server |
| Chu kỳ tick / nến (`tick_interval_ms`, `candle_interval_sec`, `bridge_bars`) | 1000 / 15 / 300 | Tần suất đẩy giá và số nến mỗi khung |
| Chế độ khớp lệnh (`dry_run`) | DryRun | Chỉ in log, không đặt lệnh (vẫn báo về server với `error="dry_run"`) |
| Cho phép đặt lệnh (`enable_trading`) | Tắt | Phải Bật và tắt DryRun mới gửi lệnh thật |
| EA chỉ vào kèo ≥ % (`min_confidence`) | 80 | Độc lập với ngưỡng gửi Telegram |
| Bỏ kèo cũ hơn (`max_signal_age_sec`) | 300 | Tính theo đồng hồ server qua `/api/health` |
| Chu kỳ hỏi kèo (`poll_seconds`) | 15 | |
| Số kèo mở tối đa / symbol (`max_open_per_symbol`) | 1 | 2 lệnh SplitTP cùng kèo tính là 1 |
| Khối lượng (`use_server_lot`, `risk_percent`) | tính lại, 1.0% | `false` = % balance MT5 / khoảng SL theo tick value của broker |
| Chia TP1/TP2 (`split_tp`, `breakeven_buffer_pts`) | Bật, 0 | Khi lệnh TP1 đóng, SL lệnh TP2 dời về hoà vốn |
| Ngừng khi lỗ ngày ≥ % (`max_daily_loss_pct`) | 3.0 | Chỉ tính lệnh của EA; 0 = tắt |
| Magic, trượt giá (`magic`, `slippage_points`) | 20261023, 30 | Comment lệnh là `AITO#<id>`, `/TP1`, `/TP2` |
| Bảng điều khiển trên chart (`show_panel`, `panel_scale`) | Bật, 1.0 | Bảng đồ hoạ có animation: trạng thái ONLINE, giá nháy màu, thống kê đẩy giá, kèo mới nhất, chế độ DRY RUN/LIVE. Cỡ 0.6–2.0 |

EA nhớ id kèo cuối trong GlobalVariable `AITO_LastId_<magic>`; muốn xử lý lại từ đầu thì xoá biến đó (F3).
Lot được chuẩn hoá theo `SYMBOL_VOLUME_MIN/STEP/MAX`; SL/TP giữ nguyên khoảng cách so với entry của kèo nhưng áp lên
giá thị trường lúc khớp, được làm tròn theo `digits` và ép tối thiểu cách giá `SYMBOL_TRADE_STOPS_LEVEL`.

### Theo dõi tài khoản MT5 trên dashboard

EA gửi mỗi 2 giây: số tài khoản, server, loại DEMO/REAL, đòn bẩy, balance, equity, margin, free margin, margin level,
lãi/lỗ đang mở, lãi/lỗ hôm nay của riêng EA và danh sách lệnh đang mở (lệnh của EA có nhãn **EA**). Dashboard hiện khu
**💼 Tài khoản MT5** với biểu đồ equity (1 điểm/phút, lưu 30 ngày ở bảng `account_history`), két quỹ trong văn phòng 2D
hiện số dư. Tuỳ chọn **Tính khối lượng theo số dư MT5** (tab Quỹ, mặc định bật) cho Robot Quản Trị Vốn tính lot theo
balance thật thay vì vốn nhập tay.

### Thống kê chiến thuật theo magic (chỉ lấy khi bấm xem)

Nút **📈 Thống kê bot** trong khu Tài khoản MT5: chọn magic (0 = mọi lệnh) và khoảng thời gian (hôm nay, 7/30/90 ngày,
tháng này/trước, từ đầu năm, toàn bộ hoặc tuỳ chọn). Server tạo yêu cầu, trả kèm trong phản hồi lần gửi số dư kế tiếp
của EA (khoảng 2 giây); EA lúc đó mới đọc lịch sử deal và gửi về một lần qua `POST /api/push_history`, không gửi liên tục.

- Lọc theo vị thế của magic nên lệnh bạn đóng tay (deal đóng có magic 0) vẫn được tính; lệnh mở trước kỳ nhưng đóng trong kỳ cũng được tính.
- Chỉ số: lãi/lỗ ròng (đã trừ commission, swap, fee), % lợi nhuận so với số dư đầu kỳ, max drawdown (USD và %), số lệnh, tỷ lệ thắng, profit factor, lãi/lỗ trung bình, kỳ vọng mỗi lệnh, lệnh lãi/lỗ lớn nhất, chuỗi thua dài nhất, recovery factor.
- Biểu đồ đường 3 chế độ: **Lãi lỗ tích luỹ**, **Balance** (số dư đầu kỳ + lãi lỗ của magic), **Drawdown**; rê chuột để xem chi tiết. Cột lãi/lỗ theo ngày (theo tuần nếu khoảng > 120 ngày), bảng theo symbol, theo chiều BUY/SELL và 100 lệnh đóng gần nhất.
- Mốc ngày theo giờ server broker. Tối đa 5.000 deal mỗi lần.
- API: `POST /api/stats/request {"magic", "from": "YYYY.MM.DD", "to": "YYYY.MM.DD"}`, `GET /api/stats/result?id=`.

### Báo kết quả về server

Sau mỗi lần đặt (hoặc bỏ qua) kèo, EA `POST /api/execution` với `signal_id, ticket, symbol, action, volume, price, sl, tp,
retcode, error, dry_run, magic, account, comment`. Server lưu vào bảng `executions` trong `data/office.db`, 🐷 `vault_piggy`
ghi log trong Phòng Két, và `GET /api/executions?limit=50[&signal_id=12]` để xem lại.

Lưu ý: thời gian nến MT5 theo giờ server broker, nên "Session VWAP" tính từ 00:00 giờ broker thay vì 00:00 UTC.

### Thay thế: script Python `mt5_bridge.py`

Chỉ đẩy giá, dành cho ai chạy server ngay trên máy Windows có MT5 và không muốn dùng EA:

```bash
pip install MetaTrader5
python mt5_bridge.py --server http://IP_SERVER:8080 --gold XAUUSD --btc BTCUSD
```

> ⚠️ EA đặt lệnh thật bằng tiền thật khi tắt DryRun. Hãy test trên tài khoản demo Exness trước. Kèo chỉ mang tính tham khảo.

## Telegram: nhận kèo, lọc ngưỡng và lắng nghe tin

- **Lọc kèo gửi đi**: trong Cài đặt đặt "Chỉ gửi kèo khi độ tự tin ≥ %" (mặc định 75) và "Gửi cả kèo WAIT?" (mặc định không). Kèo bị lọc vẫn lưu vào SQLite và hiện trên dashboard, chỉ không bắn Telegram.
- **Lắng nghe tin**: bot dùng long-polling `getUpdates`. Bot chỉ đọc được:
  1. Kênh / nhóm mà bạn **thêm bot làm admin** (kênh người khác không thêm được bot thì không đọc được).
  2. Tin bạn **forward** từ bất kỳ kênh nào vào chat riêng với bot: đây là cách nhanh nhất để nạp tin từ kênh không phải của bạn.
- Tin nhận được gắn 🔥 nếu chứa từ khoá vàng/BTC/Fed/CPI..., được đưa lên đầu phần "Tin vĩ mô" trong prompt LLM, và Built-in Quant AI dùng điểm cảm tính (bull/bear) để cộng/trừ độ tự tin.
- Trường "Chỉ nghe các kênh" nhận id hoặc @username, phân cách bằng dấu phẩy. Để trống = nghe tất cả.
- Nếu cần đọc tự động kênh công khai mà không thể thêm bot, cần một **user session** (Telethon/MTProto), không làm được bằng Bot API và stdlib; xem mục Mở rộng.

## Bộ não AI (Multi-LLM Router)

Thứ tự mặc định trong `call_free_llm()`: **Gemini (xoay vòng nhiều model)** → **Groq** (`openai/gpt-oss-120b`) →
**OpenRouter** (`deepseek/deepseek-chat:free`) → **Custom/Ollama** (OpenAI-compatible) → **Built-in Quant AI**.

> **Thứ tự này đổi được**: vào 🔑 Cài Đặt > tab **AI & API Key** > mục **5. Thứ tự gọi nhà cung cấp** rồi **kéo thả** (hoặc bấm ▲▼)
> để xếp nhà cung cấp bạn tin cậy nhất lên đầu; lưu ở `llm_provider_order` trong `data/config.json`. Nhà cung cấp chưa có key
> vẫn giữ vị trí nhưng tự bị bỏ qua khi gọi; Built-in Quant AI luôn là chốt chặn cuối. Nhờ vậy có thể đặt model/mô hình
> ổn định nhất làm nơi chốt kèo, chỉ rơi xuống các nguồn khác khi lỗi hoặc hết hạn mức.

### Gemini xoay vòng nhiều model free

Mỗi model Gemini có hạn mức riêng mỗi ngày (ví dụ Gemini 3 Flash chỉ 20 request/ngày, 3.1 Flash Lite 500, Gemma 14.400).
Server giữ một danh sách model theo thứ tự ưu tiên (🔑 Cài Đặt AI & API > bảng model) và với mỗi phiên họp:

- Bỏ qua model đang tắt, đang nghỉ, đã chạm RPD (request/ngày) hoặc RPM (request/phút) đặt trong bảng.
- Gọi model kế tiếp. Lỗi **429 hết lượt ngày** → nghỉ tới 0h giờ Pacific (14h–15h giờ VN). **429 theo phút** → nghỉ theo `retryDelay` Google trả về. **503 quá tải** → nghỉ 2 phút. **404 model không còn mở** → nghỉ 24h.
- Thử tối đa `gemini_max_attempts` model (mặc định 5) rồi mới rơi xuống Groq.
- Cách chọn: **Ưu tiên** (model tốt nhất còn lượt) hoặc **Rải đều** (luân phiên mọi model còn lượt).
- Số request đã dùng mỗi model mỗi ngày lưu ở bảng `llm_usage` trong `data/office.db`, không mất khi restart.
- Nút **🔍 Dò model từ Google** thêm model mới mà key của bạn thấy (để tắt sẵn); bấm **Test** từng model rồi bật.
- API: `GET /api/llm/models`, `POST /api/gemini/discover`, `POST /api/gemini/test {"model": "..."}`, `POST /api/gemini/reset_cooldown`.

Lấy key miễn phí:
- Gemini: <https://aistudio.google.com/apikey> (xem hạn mức từng model tại AI Studio > Usage / Rate limits)
- Groq: <https://console.groq.com/keys>
- OpenRouter: <https://openrouter.ai/keys>
- Telegram Bot: chat với [@BotFather](https://t.me/BotFather), lấy Chat ID qua [@userinfobot](https://t.me/userinfobot)

## Cơ cấu agent

| Agent | Phòng | Vai trò |
|---|---|---|
| 🟣 `vwap_hunter` Bé Tím VWAP | Kỹ Thuật | Vị trí giá so với Session VWAP ±1.5σ |
| 🩷 `smc_sniper` Bé Hồng SMC | Kỹ Thuật | Quét thanh khoản, BOS, vùng discount/premium |
| 🟢 `trend_radar` Bé Xanh Trend | Kỹ Thuật | EMA 20/50/200 + RSI |
| 🦅 `htf_scout` Ưng Khung Lớn | Kỹ Thuật | Xu hướng H1 và H4 (EMA50/200 + 2 đỉnh / 2 đáy fractal gần nhất). Có **veto**: cấm lệnh ngược xu hướng khi H1 và H4 cùng hướng |
| 🐱 `regime_meter` Mèo Đo Nhịp | Kỹ Thuật | Trạng thái thị trường `trend` / `range` / `high_vol` từ ADX(14), percentile độ rộng Bollinger(20,2) trong 100 nến, ATR hiện tại so với trung bình. Có **cờ chặn** khi spread MT5 > 2× median ~1 giờ gần nhất, ATR ≥ 2.5× trung bình hoặc nến hiện tại dài ≥ 3×ATR |
| 🦊 `level_mapper` Cáo Mốc Giá | Kỹ Thuật | Đỉnh/đáy/giá mở cửa ngày trước và giá mở cửa hôm nay (theo giờ nến MT5), vùng phiên Á (00–07h UTC), phiên hiện tại, số tròn (XAU bội 10/50, BTC bội 1000), khoảng cách tới mức gần nhất tính theo ATR. Bỏ phiếu khi giá bật/bị đạp tại mức hoặc phá vỡ rồi giữ được; WAIT khi giá kẹt giữa hai mức mạnh cách nhau < 3×ATR |
| 🟠 `chief_strategist` Trưởng Nhóm Cam | Kỹ Thuật | Chủ trì họp, gộp phiếu, chốt kèo |
| 🤖 `risk_guard` Robot Quản Trị | Rủi Ro | SL / TP / khối lượng |
| 📕 `hermes_scribe` Sách Đỏ Hermes | Thư Viện | Nạp và ghi `SKILL.md` |
| 🦉 `macro_owl` Cú Mèo Vĩ Mô | Tin Vĩ Mô | Nến, tin tức, Telegram |
| 🐷 `vault_piggy` Heo Vàng Thủ Quỹ | Két Quỹ | Lưu kèo, Telegram, nhận báo cáo EA |

Ưng Khung Lớn và Cáo Mốc Giá đọc nến H1/H4 mà EA đã đẩy vào `MT5_FEED` (không đổi giao thức EA). Thiếu nến H1/H4 thì agent bỏ phiếu WAIT, không veto.
Giờ phiên tính theo UTC; độ lệch giờ server broker so với UTC được ước lượng tự động từ nến M5/M15 mới nhất.

**Gộp phiếu (Built-in Quant AI).** Điểm = Σ trọng số × (+1 BUY / −1 SELL / 0 WAIT), chia cho tổng trọng số 6 agent.
BUY khi điểm ≥ `quant_consensus` (mặc định 0.4), SELL khi ≤ −0.4, còn lại WAIT; trạng thái `high_vol` cộng thêm 0.1 vào ngưỡng.

| Trọng số gốc | VWAP 1.0 | SMC 1.2 | Trend 1.0 | Khung lớn 1.2 | Nhịp 0.8 | Mốc giá 1.0 |
|---|---|---|---|---|---|---|
| × khi `trend` | 1.2 | 0.9 | 1.3 | 1.3 | 1 | 0.9 |
| × khi `range` | 0.9 | 1.3 | 0.6 | 0.8 | 1 | 1.4 |

Veto khung lớn và cờ chặn của Mèo Đo Nhịp **ép WAIT** cả khi quyết định đến từ LLM. Prompt gửi LLM có số liệu H1/H4, trạng thái thị trường, mức giá, phiên và điểm đồng thuận.

**Chấm điểm agent** (`GET /api/agents/scorecard`, tab 🧩 Agent trong Cài Đặt AI). Chỉ chấm kèo BUY/SELL đã có lệnh khớp thật trong bảng
`executions` (bỏ DryRun, bỏ lệnh lỗi; kèo tách TP1/TP2 tính một lần theo lệnh TP1). Kết quả lấy từ lịch sử EA gửi về khi bấm 📈 Thống kê bot
(position lãi ròng > 0 = đúng); chưa có lịch sử thì dò nến MT5 sau lúc khớp: chạm TP1 trước SL là đúng, cùng một nến chạm cả hai tính sai.
Kết quả lưu ở bảng `signal_outcomes`. Phiếu WAIT và kèo cũ chưa có phiếu của agent mới không được tính cho agent đó.
Bật `agent_auto_weight` (mặc định tắt) thì trọng số mỗi agent nhân thêm hệ số `tỷ lệ đúng / 50%`, giới hạn 0.5–1.5, chỉ áp dụng khi agent có từ 20 phiếu.

## Luồng 5 bước

1. 🦉 `macro_owl` kéo nến & tin tức.
2. 🟣🩷🟢🦅🐱🦊 6 chuyên viên Phòng Kỹ Thuật bầu BUY / SELL / WAIT độc lập (Ưng Khung Lớn có thể veto, Mèo Đo Nhịp có thể chặn), Trưởng Nhóm tính điểm đồng thuận có trọng số.
3. 📕 `hermes_scribe` nạp `skills/<asset>.md` để kiểm tra kỷ luật.
4. 🚶 Cả văn phòng đi qua hành lang vào Phòng Họp, tranh luận Bull vs Bear, Trưởng Nhóm chốt.
5. 🤖 `risk_guard` tính SL (1.5×ATR) / TP1 (1.8R) / TP2 (2.6R) / Lot → 📕 Hermes ghi bài học → 🐷 `vault_piggy` lưu SQLite + Telegram → nếu confidence ≥ 75% cả phòng sang Party ăn mừng.

## API

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/state` | Trạng thái văn phòng, agent, logs, thị trường |
| GET | `/api/market?symbol=XAUUSD&tf=15m` | Nến + chỉ báo |
| GET | `/api/signals` | Danh sách kèo đã lưu |
| GET | `/api/skills`, `/api/skills/<file>` | Thư viện SKILL.md |
| GET/POST | `/api/config` | Cấu hình (key được che khi GET) |
| POST | `/api/meeting` `{"asset":"XAUUSD"}` | Triệu tập họp |
| POST | `/api/autopilot` `{"enabled":true}` | Bật/tắt Auto-Pilot |
| POST | `/api/llm/test`, `/api/telegram/test` | Kiểm tra kết nối |
| POST | `/api/push_price` | Nhận tick/nến từ `mt5_bridge.py` |
| GET | `/api/bridge/status` | Trạng thái kết nối MT5 |
| GET | `/api/ea/config` | Cấu hình EA tải về (JSON phẳng) |
| POST | `/api/push_account` | EA gửi balance, equity, margin, lệnh đang mở mỗi 2 giây |
| POST | `/api/execution` | EA MT5 báo kết quả đặt lệnh (lưu bảng `executions`) |
| GET | `/api/executions?limit=50&signal_id=` | Lịch sử khớp lệnh của EA |
| GET | `/api/agents/scorecard?refresh=1` | Số phiếu, tỷ lệ đúng, hệ số và trọng số hiện tại của 6 agent bỏ phiếu |

## Cấu trúc thư mục

```
.
├── server.py
├── mt5/AITradingOffice.mq5   # EA duy nhất cho VPS: đẩy giá realtime + khớp lệnh demo (DryRun mặc định)
├── mt5_bridge.py             # thay thế bằng Python nếu server chạy cùng máy Windows có MT5
├── static/index.html
├── skills/
│   ├── xauusd-vwap-playbook.md
│   └── btcusdt-momentum-playbook.md
├── data/            # office.db + config.json (tự tạo)
├── Dockerfile
├── docker-compose.yml
└── README.md
```

> ⚠️ Hệ thống chỉ mang tính tham khảo & học tập, không phải lời khuyên đầu tư. Server không tự đặt lệnh; chỉ EA `mt5/AITradingOffice.mq5` khi tắt DryRun mới gửi lệnh lên MT5.
