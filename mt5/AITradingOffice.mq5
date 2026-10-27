//+------------------------------------------------------------------+
//|                                          AITradingOffice.mq5     |
//|   EA DUY NHẤT cho "Văn phòng AI Trading 2D" trên VPS Exness:      |
//|   (1) CẦU NỐI GIÁ: đẩy bid/ask realtime + nến M5/M15/H1/H4 lên    |
//|       server qua POST /api/push_price  (mặc định BẬT)             |
//|   (2) KHỚP LỆNH: poll GET /api/signals, đặt lệnh theo SL/TP của   |
//|       kèo, báo kết quả về POST /api/execution (mặc định DryRun)   |
//+------------------------------------------------------------------+
//  CÀI ĐẶT BẮT BUỘC TRƯỚC KHI CHẠY
//  1. MT5: Tools > Options > Expert Advisors
//       [x] Allow WebRequest for listed URL  ->  thêm  http://IP_SERVER:8080
//       (phải trùng scheme + host + port với input ServerUrl, không có dấu / cuối)
//       [x] Allow automated trading  (chỉ cần khi muốn EA đặt lệnh)
//  2. Kéo EA vào 1 chart bất kỳ, chỉ cần điền ServerUrl. MỌI CẤU HÌNH KHÁC
//     (symbol, ngưỡng tự tin, rủi ro, DryRun...) EA tự tải từ server mỗi
//     ConfigRefreshSec giây -> chỉnh trong nút "Cài Đặt" trên web, không cần
//     vào lại EA.
//  3. Muốn EA đặt lệnh trên demo: bật "Algo Trading" trong MT5, rồi trên web
//     đặt EA DryRun=Tắt + EnableTrading=Bật.
//
//  KÈO "MỚI": EA nhớ id lớn nhất đã xử lý trong GlobalVariable
//  "AITO_LastId_<magic>" nên restart terminal không đặt trùng.
//  Muốn xử lý lại từ đầu: xoá biến đó trong Tools > Global Variables (F3).
//
//  ---------------------------------------------------------------
//  MẪU JSON /api/signals?limit=5 mà parser phải đọc được (có object
//  lồng "indicators"/"votes" cần bỏ qua, có null, có chuỗi unicode):
//
//  [
//    {"id": 12, "created_at": "2026-10-23 19:40:13", "asset": "XAUUSD",
//     "symbol": "binance:PAXGUSDT", "timeframe": "5m", "action": "BUY",
//     "confidence": 84, "entry": 4041.31, "stop_loss": 4036.36,
//     "take_profit_1": 4050.23, "take_profit_2": 4054.19, "rr1": 1.8,
//     "rr2": 2.6, "lot_size": 2.018, "risk_amount": 1000.0,
//     "summary": "Giá \"test\" \\ escape é", "lesson_learned": null,
//     "indicators": {"price": 4041.31, "vwap": {"mid": 4040.1, "up": 4045.2}},
//     "votes": {"vwap_analyst": {"vote": "BUY", "conf": 70}},
//     "telegram_sent": 1},
//    {"id": 11, "created_at": "2026-10-23 19:34:39", "asset": "BTCUSDT",
//     "action": "SELL", "confidence": 71, "entry": 81769.8,
//     "stop_loss": 81914.7, "take_profit_1": 81490.0, "take_profit_2": 81366.1,
//     "lot_size": 6.447, "indicators": {}, "votes": {}, "telegram_sent": 0}
//  ]
//
//  Kỳ vọng: JsonSplitArray -> 2 object; JsonGetInt(obj,"id")=12/11;
//  JsonGetString(obj,"action")="BUY"/"SELL"; JsonGetDouble(obj,"entry")=4041.31;
//  JsonGetString(obj,"lesson_learned")="" (null); key "price" trong
//  "indicators" KHÔNG bị nhận nhầm là key cấp 1.
//  EA tự chạy test này khi khởi động
//  và in kết quả PASS/FAIL ra tab Experts.
//  ---------------------------------------------------------------
#property copyright "AI Trading Office"
#property link      "https://github.com/"
#property version   "1.30"
#define  EA_VERSION  "1.30"
#property description "Cầu nối giá realtime + khớp lệnh (demo) cho AI Trading Office server"

#include <Trade\Trade.mqh>

//--- INPUT (chỉ 3 tham số; mọi thứ khác tải từ server GET /api/ea/config) ---
input string   ServerUrl          = "http://127.0.0.1:8080"; // URL server (không có / cuối)
input string   BridgeToken        = "";                      // bridge_token (nếu server đặt, tuỳ chọn)
input int      ConfigRefreshSec   = 60;                      // Chu kỳ tải lại cấu hình từ server (giây)

//--- CẤU HÌNH TẢI TỪ SERVER (giá trị dưới chỉ là mặc định khi chưa kết nối được) ---
int      PollSeconds        = 15;      // Chu kỳ hỏi kèo (giây)
int      WebTimeoutMs       = 8000;    // Timeout WebRequest (ms)
bool     ReportExecutions   = true;    // POST kết quả về /api/execution
bool     EnablePriceBridge  = true;    // Đẩy bid/ask + nến lên server
int      TickIntervalMs     = 1000;    // Chu kỳ đẩy tick (ms)
int      CandleIntervalSec  = 15;      // Chu kỳ đẩy nến (giây)
int      BridgeBars         = 300;     // Số nến mỗi khung
int      MinConfidence      = 80;      // Chỉ vào kèo có confidence >=
int      MaxSignalAgeSec    = 300;     // Bỏ kèo cũ hơn (giây)
string   GoldSymbol         = "XAUUSD";// Symbol broker cho asset XAUUSD
string   BtcSymbol          = "BTCUSD";// Symbol broker cho asset BTCUSDT
int      MaxOpenPerSymbol   = 1;       // Số kèo đang mở tối đa / symbol
bool     UseServerLot       = false;   // true: dùng lot_size của server
double   RiskPercent        = 1.0;     // false: % balance rủi ro theo khoảng SL
bool     SplitTP            = true;    // 2 lệnh: TP1 + TP2, dời BE khi TP1 chạm
int      BreakEvenBufferPts = 0;       // Điểm cộng thêm khi dời SL về hoà vốn
double   MaxDailyLossPercent= 3.0;     // Lỗ trong ngày >= % này thì ngừng (0=tắt)
bool     DryRun             = true;    // true: chỉ in log, KHÔNG đặt lệnh
bool     EnableTrading      = false;   // phải true (và DryRun=false) mới đặt lệnh
long     MagicNumber        = 20261023;// Magic của EA
int      SlippagePoints     = 30;      // Trượt giá cho phép (points)
const bool RunJsonSelfTest  = true;    // Chạy test parser JSON khi OnInit
bool     g_cfgLoaded        = false;   // đã tải được cấu hình từ server ít nhất 1 lần
datetime g_lastCfgFetch     = 0;
string   g_cfgSummary       = "chưa tải";

//--- GLOBAL ----------------------------------------------------------
CTrade   g_trade;
string   g_gvLastId;            // tên GlobalVariable lưu id kèo cuối
long     g_lastId   = 0;
bool     g_haltDay  = false;    // đã chạm MaxDailyLossPercent hôm nay
int      g_haltDayOfYear = -1;
string   g_lastErrorText = "";
datetime g_lastPoll       = 0;    // lần poll kèo gần nhất
datetime g_lastCandlePush = 0;    // lần đẩy nến gần nhất
int      g_bridgeErrors   = 0;
string   g_bridgeStatus   = "";

//--- UI / thống kê cho bảng điều khiển trên chart ---
#define  UI_PREFIX   "AITO_UI_"
#define  UI_FRAME_MS 200                 // khung hình animation (ms)
bool     g_showPanel      = true;        // tải từ server: show_panel
double   g_scale          = 1.0;         // tải từ server: panel_scale
int      g_px             = 12;          // toạ độ góc trên trái của bảng
int      g_py             = 28;
ulong    g_frame          = 0;
ulong    g_lastTickMs     = 0;           // lần đẩy tick gần nhất (GetTickCount64)
ulong    g_cfgTryMs       = 0;           // lần thử tải cấu hình gần nhất
datetime g_lastServerOk   = 0;           // lần cuối server trả 200 (giờ VPS)
long     g_latencyMs      = 0;           // độ trễ request gần nhất
long     g_pushTotal      = 0;
long     g_pushOk         = 0;
int      g_lastBridgeCode = 200;
string   g_lastBridgeErr  = "";
datetime g_lastBridgeErrAt= 0;
long     g_serverOffset   = 0;           // giờ server - giờ VPS (giây)
// kèo mới nhất từ server
long     g_sigId          = 0;
string   g_sigAction      = "";
string   g_sigAsset       = "";
string   g_sigTf          = "";
int      g_sigConf        = 0;
double   g_sigEntry       = 0, g_sigSL = 0, g_sigTP1 = 0, g_sigTP2 = 0;
datetime g_sigCreated     = 0;
ulong    g_sigAnimStart   = 0;
// giá
double   g_prevBid[2]     = {0, 0};
ulong    g_flashMs[2]     = {0, 0};
bool     g_flashUp[2]     = {true, true};
// lãi lỗ cache
ulong    g_pnlMs          = 0;
double   g_pnlToday       = 0;
int      g_openCount      = 0;
// dòng chữ chạy
string   g_ticker         = "Khởi động EA...";
// khoá 1 bản EA duy nhất trên terminal (gắn nhiều chart thì chỉ 1 bản làm việc)
#define  LOCK_OWNER  "AITO_Owner"
#define  LOCK_BEAT   "AITO_OwnerBeat"
double   g_token          = 0;      // mã ngẫu nhiên của bản EA này
bool     g_isMaster       = false;
datetime g_lastFullPush   = 0;      // lần gửi đủ BridgeBars nến gần nhất
bool     g_needFull       = true;   // lần sau phải gửi đủ (khởi động / vừa lỗi)
ulong    g_lastAccountMs  = 0;      // lần gửi thông tin tài khoản gần nhất
long     g_lastHistReqId  = 0;      // yêu cầu thống kê đã xử lý gần nhất
ulong    g_lockMs         = 0;

//+------------------------------------------------------------------+
//| JSON MINI PARSER (đủ cho mảng object phẳng + bỏ qua object lồng)  |
//+------------------------------------------------------------------+
// Bỏ qua khoảng trắng từ vị trí i
int JsonSkipWs(const string s, int i)
  {
   int n = StringLen(s);
   while(i < n)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == ' ' || c == '\t' || c == '\r' || c == '\n') i++;
      else break;
     }
   return i;
  }

// Trả về vị trí ngay sau chuỗi JSON bắt đầu tại i (s[i] == '"'); -1 nếu lỗi
int JsonSkipString(const string s, int i)
  {
   int n = StringLen(s);
   if(i >= n || StringGetCharacter(s, i) != '"') return -1;
   i++;
   while(i < n)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '\\') { i += 2; continue; }
      if(c == '"') return i + 1;
      i++;
     }
   return -1;
  }

// Trả về vị trí ngay sau giá trị JSON bắt đầu tại i (object/array/string/number/literal)
int JsonSkipValue(const string s, int i)
  {
   int n = StringLen(s);
   i = JsonSkipWs(s, i);
   if(i >= n) return -1;
   ushort c = StringGetCharacter(s, i);
   if(c == '"') return JsonSkipString(s, i);
   if(c == '{' || c == '[')
     {
      int depth = 0;
      while(i < n)
        {
         c = StringGetCharacter(s, i);
         if(c == '"')
           {
            i = JsonSkipString(s, i);
            if(i < 0) return -1;
            continue;
           }
         if(c == '{' || c == '[') depth++;
         else if(c == '}' || c == ']')
           {
            depth--;
            if(depth == 0) return i + 1;
           }
         i++;
        }
      return -1;
     }
   // number / true / false / null
   while(i < n)
     {
      c = StringGetCharacter(s, i);
      if(c == ',' || c == '}' || c == ']' || c == ' ' || c == '\r' || c == '\n' || c == '\t') break;
      i++;
     }
   return i;
  }

int HexToInt(const string hex)
  {
   int v = 0;
   int n = StringLen(hex);
   for(int i = 0; i < n; i++)
     {
      ushort c = StringGetCharacter(hex, i);
      int d = 0;
      if(c >= '0' && c <= '9') d = c - '0';
      else if(c >= 'a' && c <= 'f') d = 10 + c - 'a';
      else if(c >= 'A' && c <= 'F') d = 10 + c - 'A';
      else return v;
      v = v * 16 + d;
     }
   return v;
  }

// Giải mã chuỗi JSON (đã có dấu " hai đầu) -> chuỗi thường
string JsonDecodeString(const string raw)
  {
   int n = StringLen(raw);
   if(n < 2) return "";
   string out = "";
   int i = 1;
   while(i < n - 1)
     {
      ushort c = StringGetCharacter(raw, i);
      if(c == '\\' && i + 1 < n - 1)
        {
         ushort e = StringGetCharacter(raw, i + 1);
         if(e == 'n')      out += "\n";
         else if(e == 't') out += "\t";
         else if(e == 'r') out += "\r";
         else if(e == 'b') out += " ";
         else if(e == 'f') out += " ";
         else if(e == 'u' && i + 5 < n - 1)
           {
            int code = HexToInt(StringSubstr(raw, i + 2, 4));
            out += ShortToString((ushort)code);
            i += 6;
            continue;
           }
         else out += ShortToString(e);   // \" \\ \/
         i += 2;
         continue;
        }
      out += ShortToString(c);
      i++;
     }
   return out;
  }

// Tách mảng JSON cấp 1 thành các chuỗi object "{...}". Trả về số object.
int JsonSplitArray(const string s, string &objs[])
  {
   ArrayResize(objs, 0);
   int n = StringLen(s);
   int i = JsonSkipWs(s, 0);
   if(i >= n || StringGetCharacter(s, i) != '[') return 0;
   i++;
   while(i < n)
     {
      i = JsonSkipWs(s, i);
      if(i >= n) break;
      ushort c = StringGetCharacter(s, i);
      if(c == ']') break;
      if(c == ',') { i++; continue; }
      int end = JsonSkipValue(s, i);
      if(end <= i) break;          // JSON hỏng -> tránh lặp vô hạn
      if(c == '{')
        {
         int k = ArraySize(objs);
         ArrayResize(objs, k + 1);
         objs[k] = StringSubstr(s, i, end - i);
        }
      i = end;
     }
   return ArraySize(objs);
  }

// Tìm giá trị thô (raw token) của key ở cấp 1 trong object. "" nếu không có.
string JsonGetRaw(const string obj, const string key)
  {
   int n = StringLen(obj);
   int i = JsonSkipWs(obj, 0);
   if(i >= n || StringGetCharacter(obj, i) != '{') return "";
   i++;
   while(i < n)
     {
      i = JsonSkipWs(obj, i);
      if(i >= n) break;
      ushort c = StringGetCharacter(obj, i);
      if(c == '}') break;
      if(c == ',') { i++; continue; }
      if(c != '"') return "";          // JSON hỏng
      int kend = JsonSkipString(obj, i);
      if(kend < 0) return "";
      string k = JsonDecodeString(StringSubstr(obj, i, kend - i));
      i = JsonSkipWs(obj, kend);
      if(i >= n || StringGetCharacter(obj, i) != ':') return "";
      i = JsonSkipWs(obj, i + 1);
      int vend = JsonSkipValue(obj, i);
      if(vend < i) return "";
      if(k == key) return StringSubstr(obj, i, vend - i);
      i = vend;
     }
   return "";
  }

string JsonGetString(const string obj, const string key, const string def = "")
  {
   string raw = JsonGetRaw(obj, key);
   if(raw == "" || raw == "null") return def;
   if(StringGetCharacter(raw, 0) == '"') return JsonDecodeString(raw);
   return raw;
  }

double JsonGetDouble(const string obj, const string key, double def = 0.0)
  {
   string raw = JsonGetRaw(obj, key);
   if(raw == "" || raw == "null" || raw == "true" || raw == "false") return def;
   if(StringGetCharacter(raw, 0) == '"') raw = JsonDecodeString(raw);
   if(raw == "") return def;
   return StringToDouble(raw);
  }

long JsonGetInt(const string obj, const string key, long def = 0)
  {
   string raw = JsonGetRaw(obj, key);
   if(raw == "" || raw == "null") return def;
   if(raw == "true") return 1;
   if(raw == "false") return 0;
   if(StringGetCharacter(raw, 0) == '"') raw = JsonDecodeString(raw);
   if(raw == "") return def;
   return (long)MathRound(StringToDouble(raw));
  }

// Escape chuỗi để nhét vào JSON gửi đi
string JsonEscape(const string s)
  {
   string out = "";
   int n = StringLen(s);
   for(int i = 0; i < n; i++)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')       out += "\\\"";
      else if(c == '\\') out += "\\\\";
      else if(c == '\n') out += "\\n";
      else if(c == '\r') out += "\\r";
      else if(c == '\t') out += "\\t";
      else if(c < 32)    out += " ";
      else out += ShortToString(c);
     }
   return out;
  }

// Parse "YYYY-MM-DD HH:MM:SS" (hoặc dấu '.' / 'T') -> datetime; 0 nếu lỗi
datetime ParseServerTime(const string s)
  {
   if(StringLen(s) < 16) return 0;
   MqlDateTime dt;
   ZeroMemory(dt);
   dt.year = (int)StringToInteger(StringSubstr(s, 0, 4));
   dt.mon  = (int)StringToInteger(StringSubstr(s, 5, 2));
   dt.day  = (int)StringToInteger(StringSubstr(s, 8, 2));
   dt.hour = (int)StringToInteger(StringSubstr(s, 11, 2));
   dt.min  = (int)StringToInteger(StringSubstr(s, 14, 2));
   dt.sec  = (StringLen(s) >= 19) ? (int)StringToInteger(StringSubstr(s, 17, 2)) : 0;
   if(dt.year < 2000 || dt.mon < 1 || dt.mon > 12 || dt.day < 1 || dt.day > 31) return 0;
   return StructToTime(dt);
  }

//+------------------------------------------------------------------+
//| JSON SELF TEST                                                   |
//+------------------------------------------------------------------+
bool Check(const string name, bool cond)
  {
   if(!cond) Print("[AITO] TEST FAIL: ", name);
   return cond;
  }

bool JsonSelfTest()
  {
   string sample = ""
      + "[\n"
      + " {\"id\": 12, \"created_at\": \"2026-10-23 19:40:13\", \"asset\": \"XAUUSD\","
      + "  \"symbol\": \"binance:PAXGUSDT\", \"timeframe\": \"5m\", \"action\": \"BUY\","
      + "  \"confidence\": 84, \"entry\": 4041.31, \"stop_loss\": 4036.36,"
      + "  \"take_profit_1\": 4050.23, \"take_profit_2\": 4054.19, \"rr1\": 1.8,"
      + "  \"rr2\": 2.6, \"lot_size\": 2.018, \"risk_amount\": 1000.0,"
      + "  \"summary\": \"Gi\\u00e1 \\\"test\\\" \\\\ escape\", \"lesson_learned\": null,"
      + "  \"indicators\": {\"price\": 4041.31, \"vwap\": {\"mid\": 4040.1, \"up\": [1,2,{\"x\":\"]}\"}]}},"
      + "  \"votes\": {\"vwap_analyst\": {\"vote\": \"BUY\", \"conf\": 70}},"
      + "  \"telegram_sent\": 1},\n"
      + " {\"id\": 11, \"created_at\": \"2026-10-23 19:34:39\", \"asset\": \"BTCUSDT\","
      + "  \"action\": \"SELL\", \"confidence\": 71, \"entry\": 81769.8,"
      + "  \"stop_loss\": 81914.7, \"take_profit_1\": 81490.0, \"take_profit_2\": 81366.1,"
      + "  \"lot_size\": 6.447, \"indicators\": {}, \"votes\": {}, \"telegram_sent\": 0}\n"
      + "]";
   string objs[];
   int cnt = JsonSplitArray(sample, objs);
   bool ok = true;
   ok = Check("split count == 2", cnt == 2) && ok;
   if(cnt != 2) return false;
   ok = Check("id[0] == 12", JsonGetInt(objs[0], "id") == 12) && ok;
   ok = Check("id[1] == 11", JsonGetInt(objs[1], "id") == 11) && ok;
   ok = Check("action[0] == BUY", JsonGetString(objs[0], "action") == "BUY") && ok;
   ok = Check("action[1] == SELL", JsonGetString(objs[1], "action") == "SELL") && ok;
   ok = Check("entry[0] == 4041.31", MathAbs(JsonGetDouble(objs[0], "entry") - 4041.31) < 1e-6) && ok;
   ok = Check("tp2[1] == 81366.1", MathAbs(JsonGetDouble(objs[1], "take_profit_2") - 81366.1) < 1e-6) && ok;
   ok = Check("confidence[0] == 84", JsonGetInt(objs[0], "confidence") == 84) && ok;
   ok = Check("lesson_learned null -> \"\"", JsonGetString(objs[0], "lesson_learned") == "") && ok;
   ok = Check("nested key 'price' not at level 1", JsonGetRaw(objs[0], "price") == "") && ok;
   ok = Check("nested key 'vote' not at level 1", JsonGetRaw(objs[0], "vote") == "") && ok;
   ok = Check("telegram_sent[0] == 1", JsonGetInt(objs[0], "telegram_sent") == 1) && ok;
   ok = Check("created_at parse", ParseServerTime(JsonGetString(objs[0], "created_at")) == D'2026.10.23 19:40:13') && ok;
   string summ = JsonGetString(objs[0], "summary");
   ok = Check("summary unescape", StringFind(summ, "\"test\" \\ escape") >= 0) && ok;
   ok = Check("missing key -> default", JsonGetDouble(objs[1], "risk_amount", -1.0) == -1.0) && ok;
   Print("[AITO] JSON self test: ", ok ? "PASS" : "FAIL");
   return ok;
  }

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
string BuildHeaders(bool isPost)
  {
   string h = "";
   if(isPost) h += "Content-Type: application/json\r\n";
   if(BridgeToken != "") h += "X-Bridge-Token: " + BridgeToken + "\r\n";
   return h;
  }

// Trả về HTTP status; body ra tham chiếu. -1 nếu WebRequest lỗi.
int HttpGet(const string url, string &body)
  {
   char data[];
   char result[];
   string resHeaders;
   ArrayResize(data, 0);
   ResetLastError();
   ulong t0 = GetTickCount64();
   int code = WebRequest("GET", url, BuildHeaders(false), WebTimeoutMs, data, result, resHeaders);
   g_latencyMs = (long)(GetTickCount64() - t0);
   if(code == 200) g_lastServerOk = TimeLocal();
   if(code == -1)
     {
      int err = GetLastError();
      g_lastErrorText = "WebRequest GET lỗi " + IntegerToString(err) +
                        (err == 4014 ? " (URL chưa được thêm vào Tools > Options > Expert Advisors > Allow WebRequest)" : "");
      Print("[AITO] ", g_lastErrorText, " url=", url);
      body = "";
      return -1;
     }
   body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return code;
  }

int HttpPostJson(const string url, const string json, string &body, int timeoutMs = 0)
  {
   char data[];
   char result[];
   string resHeaders;
   int len = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 0) ArrayResize(data, len - 1);   // bỏ ký tự NUL cuối
   ResetLastError();
   ulong t0 = GetTickCount64();
   int code = WebRequest("POST", url, BuildHeaders(true), timeoutMs > 0 ? timeoutMs : WebTimeoutMs, data, result, resHeaders);
   g_latencyMs = (long)(GetTickCount64() - t0);
   if(code == 200) g_lastServerOk = TimeLocal();
   if(code == -1)
     {
      int err = GetLastError();
      g_lastErrorText = "WebRequest lỗi " + IntegerToString(err) + (err == 5203 ? " (timeout/mất mạng)" : "");
      Print("[AITO] WebRequest POST lỗi ", err, " url=", url);
      body = "";
      return -1;
     }
   body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return code;
  }

//+------------------------------------------------------------------+
//| SYMBOL / LOT / PRICE HELPERS                                      |
//+------------------------------------------------------------------+
string MapAssetToSymbol(const string asset)
  {
   if(asset == "XAUUSD") return GoldSymbol;
   if(asset == "BTCUSDT" || asset == "BTCUSD") return BtcSymbol;
   return "";
  }

double NormalizeLot(const string sym, double lot)
  {
   double vmin  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(vstep <= 0) vstep = vmin > 0 ? vmin : 0.01;
   lot = MathFloor(lot / vstep + 1e-9) * vstep;
   if(lot < vmin) lot = vmin;
   if(vmax > 0 && lot > vmax) lot = vmax;
   // làm tròn theo số chữ số của step
   int digits = 0;
   double st = vstep;
   while(st < 1.0 && digits < 8) { st *= 10.0; digits++; }
   return NormalizeDouble(lot, digits);
  }

double NormalizePrice(const string sym, double price)
  {
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   return NormalizeDouble(price, digits);
  }

// Lot theo % rủi ro và khoảng SL (giá)
double LotByRisk(const string sym, double slDistance)
  {
   if(slDistance <= 0) return 0.0;
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmt   = balance * RiskPercent / 100.0;
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0.0;
   double lossPerLot = slDistance / tickSize * tickValue;
   if(lossPerLot <= 0) return 0.0;
   return riskAmt / lossPerLot;
  }

// Ép SL/TP tối thiểu cách giá hiện tại stops level; trả false nếu SL sai phía
bool AdjustStops(const string sym, bool isBuy, double &sl, double &tp)
  {
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   int    stops = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   double minDist = (stops + 1) * point;
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   if(isBuy)
     {
      if(sl >= ask) return false;              // SL ngược phía
      if(sl > bid - minDist) sl = bid - minDist;
      if(tp > 0 && tp < ask + minDist) tp = ask + minDist;
     }
   else
     {
      if(sl <= bid) return false;
      if(sl < ask + minDist) sl = ask + minDist;
      if(tp > 0 && tp > bid - minDist) tp = bid - minDist;
     }
   sl = NormalizePrice(sym, sl);
   tp = NormalizePrice(sym, tp);
   return true;
  }

// Lấy signal id từ comment "AITO#123" / "AITO#123/TP1"; 0 nếu không phải
long SignalIdFromComment(const string comment)
  {
   int p = StringFind(comment, "AITO#");
   if(p < 0) return 0;
   string rest = StringSubstr(comment, p + 5);
   int slash = StringFind(rest, "/");
   if(slash >= 0) rest = StringSubstr(rest, 0, slash);
   return StringToInteger(rest);
  }

// Đếm số kèo (signal id khác nhau) đang mở trên symbol với magic của EA.
// SplitTP tạo 2 vị thế cùng 1 kèo -> tính là 1.
int CountOpenSignals(const string sym)
  {
   long ids[];
   ArrayResize(ids, 0);
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym) continue;
      long sid = SignalIdFromComment(PositionGetString(POSITION_COMMENT));
      if(sid == 0) sid = -(long)ticket;      // broker xoá comment -> đếm riêng từng vị thế
      bool found = false;
      for(int k = 0; k < ArraySize(ids); k++) if(ids[k] == sid) { found = true; break; }
      if(!found)
        {
         int n = ArraySize(ids);
         ArrayResize(ids, n + 1);
         ids[n] = sid;
        }
     }
   return ArraySize(ids);
  }

bool SignalAlreadyOpen(long signalId)
  {
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      if(SignalIdFromComment(PositionGetString(POSITION_COMMENT)) == signalId) return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| DAILY LOSS GUARD                                                  |
//+------------------------------------------------------------------+
// Lợi nhuận đã chốt hôm nay (theo giờ server broker) của các lệnh magic EA
double RealizedToday()
  {
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime dayStart = StructToTime(dt);
   if(!HistorySelect(dayStart, now + 60)) return 0.0;
   double sum = 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != MagicNumber) continue;
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT && entry != DEAL_ENTRY_OUT_BY) continue;
      sum += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
     }
   return sum;
  }

double FloatingOfEA()
  {
   double sum = 0.0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   return sum;
  }

// true nếu được phép giao dịch tiếp hôm nay
bool DailyLossOk()
  {
   if(MaxDailyLossPercent <= 0) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(g_haltDay && g_haltDayOfYear != dt.day_of_year)
     {
      g_haltDay = false;          // sang ngày mới -> mở lại
      Print("[AITO] Ngày mới, mở lại giao dịch.");
     }
   if(g_haltDay) return false;
   double realized = RealizedToday();
   double floating = FloatingOfEA();
   double pnl = realized + floating;
   double balanceStart = AccountInfoDouble(ACCOUNT_BALANCE) - realized;
   if(balanceStart <= 0) return true;
   double lossPct = -pnl / balanceStart * 100.0;
   if(lossPct >= MaxDailyLossPercent)
     {
      g_haltDay = true;
      g_haltDayOfYear = dt.day_of_year;
      Print(StringFormat("[AITO] ⛔ Lỗ trong ngày %.2f%% >= %.2f%% -> NGỪNG giao dịch đến ngày mai (realized %.2f, floating %.2f)",
                         lossPct, MaxDailyLossPercent, realized, floating));
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| BREAK-EVEN: TP2 còn mở mà TP1 cùng kèo đã đóng -> dời SL về BE     |
//+------------------------------------------------------------------+
void ManageBreakEven()
  {
   if(!SplitTP) return;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      string comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(comment, "/TP2") < 0) continue;
      long sid = SignalIdFromComment(comment);
      if(sid == 0) continue;
      // còn TP1 cùng kèo đang mở?
      bool tp1Open = false;
      for(int k = 0; k < total; k++)
        {
         ulong t2 = PositionGetTicket(k);
         if(t2 == 0 || t2 == ticket) continue;
         if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
         string c2 = PositionGetString(POSITION_COMMENT);
         if(StringFind(c2, "/TP1") >= 0 && SignalIdFromComment(c2) == sid) { tp1Open = true; break; }
        }
      // PositionGetTicket(k) trong vòng lặp con đã đổi position được chọn -> chọn lại
      if(!PositionSelectByTicket(ticket)) continue;
      if(tp1Open) continue;
      string sym   = PositionGetString(POSITION_SYMBOL);
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      bool   isBuy = (ptype == POSITION_TYPE_BUY);
      double be    = isBuy ? open + BreakEvenBufferPts * point : open - BreakEvenBufferPts * point;
      be = NormalizePrice(sym, be);
      // đã ở BE hoặc tốt hơn
      if(isBuy  && sl >= be - point / 2) continue;
      if(!isBuy && sl > 0 && sl <= be + point / 2) continue;
      double newSl = be, newTp = tp;
      if(!AdjustStops(sym, isBuy, newSl, newTp))
        {
         Print("[AITO] BE kèo #", sid, ": SL ", DoubleToString(be, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
               " chưa hợp lệ với giá hiện tại, thử lại sau.");
         continue;
        }
      if(isBuy  && newSl < be) { continue; } // bị ép xuống dưới BE do stops level -> đợi
      if(!isBuy && newSl > be) { continue; }
      if(DryRun)
        {
         Print("[AITO][DRY] Dời SL về hoà vốn ticket ", ticket, " kèo #", sid, " SL=", newSl);
         continue;
        }
      if(g_trade.PositionModify(ticket, newSl, tp))
         Print("[AITO] ✅ Dời SL về hoà vốn ticket ", ticket, " kèo #", sid, " SL=", newSl);
      else
         Print("[AITO] ❌ PositionModify ticket ", ticket, " lỗi ", g_trade.ResultRetcode(), " ", g_trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
//| REPORT -> POST /api/execution                                     |
//+------------------------------------------------------------------+
void ReportExecution(long signalId, const string sym, const string action, double volume,
                     ulong ticket, double price, double sl, double tp, int retcode,
                     const string error, const string comment)
  {
   if(!ReportExecutions) return;
   string json = "{"
      + "\"signal_id\":" + IntegerToString(signalId) +
      ",\"ticket\":" + IntegerToString((long)ticket) +
      ",\"symbol\":\"" + JsonEscape(sym) + "\"" +
      ",\"action\":\"" + JsonEscape(action) + "\"" +
      ",\"volume\":" + DoubleToString(volume, 3) +
      ",\"price\":" + DoubleToString(price, 5) +
      ",\"sl\":" + DoubleToString(sl, 5) +
      ",\"tp\":" + DoubleToString(tp, 5) +
      ",\"retcode\":" + IntegerToString(retcode) +
      ",\"error\":\"" + JsonEscape(error) + "\"" +
      ",\"dry_run\":" + (DryRun ? "true" : "false") +
      ",\"magic\":" + IntegerToString(MagicNumber) +
      ",\"account\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) +
      ",\"comment\":\"" + JsonEscape(comment) + "\"" +
      ",\"terminal_time\":\"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\"" +
      "}";
   string body;
   int code = HttpPostJson(ServerUrl + "/api/execution", json, body);
   if(code != 200)
      Print("[AITO] Báo cáo /api/execution thất bại code=", code, " body=", StringSubstr(body, 0, 200));
  }

//+------------------------------------------------------------------+
//| ĐẶT 1 LỆNH THỊ TRƯỜNG                                             |
//+------------------------------------------------------------------+
// Trả về ticket vị thế (0 nếu lỗi/dry-run). error ra tham chiếu.
ulong PlaceMarket(long signalId, const string sym, bool isBuy, double lot, double sl, double tp,
                  const string comment, string &error, int &retcode, double &fillPrice)
  {
   error = ""; retcode = 0; fillPrice = 0;
   string action = isBuy ? "BUY" : "SELL";
   double price = isBuy ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   if(DryRun)
     {
      Print(StringFormat("[AITO][DRY] %s %s %.3f lot @%s SL=%s TP=%s (%s)", action, sym, lot,
                         DoubleToString(price, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                         DoubleToString(sl, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                         DoubleToString(tp, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), comment));
      fillPrice = price;
      ReportExecution(signalId, sym, action, lot, 0, price, sl, tp, 0, "dry_run", comment);
      return 0;
     }
   g_trade.SetTypeFillingBySymbol(sym);
   bool ok = isBuy ? g_trade.Buy(lot, sym, price, sl, tp, comment)
                   : g_trade.Sell(lot, sym, price, sl, tp, comment);
   retcode = (int)g_trade.ResultRetcode();
   bool done = ok && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_DONE_PARTIAL || retcode == TRADE_RETCODE_PLACED);
   ulong ticket = done ? g_trade.ResultOrder() : 0;
   fillPrice = g_trade.ResultPrice();
   if(!done)
     {
      error = "retcode " + IntegerToString(retcode) + ": " + g_trade.ResultRetcodeDescription();
      Print("[AITO] ❌ ", action, " ", sym, " lỗi ", error);
     }
   else
      Print(StringFormat("[AITO] ✅ %s %s %.3f lot ticket=%I64u khớp %s SL=%s TP=%s", action, sym,
                         g_trade.ResultVolume(), ticket,
                         DoubleToString(fillPrice, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                         DoubleToString(sl, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                         DoubleToString(tp, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS))));
   ReportExecution(signalId, sym, action, lot, ticket, fillPrice, sl, tp, retcode, error, comment);
   return ticket;
  }

//+------------------------------------------------------------------+
//| XỬ LÝ 1 KÈO                                                       |
//+------------------------------------------------------------------+
void ProcessSignal(const string obj, datetime serverNow)
  {
   long   id      = JsonGetInt(obj, "id");
   string asset   = JsonGetString(obj, "asset");
   string action  = JsonGetString(obj, "action");
   int    conf    = (int)JsonGetInt(obj, "confidence");
   double entry   = JsonGetDouble(obj, "entry");
   double slSrv   = JsonGetDouble(obj, "stop_loss");
   double tp1     = JsonGetDouble(obj, "take_profit_1");
   double tp2     = JsonGetDouble(obj, "take_profit_2");
   double lotSrv  = JsonGetDouble(obj, "lot_size");
   string created = JsonGetString(obj, "created_at");
   string tag     = StringFormat("kèo #%I64d %s %s conf=%d", id, asset, action, conf);

   StringToUpper(action);
   if(action != "BUY" && action != "SELL")
     {
      Print("[AITO] Bỏ qua ", tag, ": action không phải BUY/SELL.");
      return;
     }
   if(conf < MinConfidence)
     {
      Print("[AITO] Bỏ qua ", tag, ": confidence < ", MinConfidence, ".");
      return;
     }
   datetime createdAt = ParseServerTime(created);
   long age = (createdAt > 0) ? (long)(serverNow - createdAt) : -1;
   if(createdAt == 0 || age > MaxSignalAgeSec)
     {
      Print("[AITO] Bỏ qua ", tag, ": tuổi kèo ", age, "s > ", MaxSignalAgeSec, "s (created_at=", created, ").");
      ReportExecution(id, MapAssetToSymbol(asset), action, 0, 0, 0, slSrv, tp1, 0, "skipped: stale " + IntegerToString(age) + "s", "");
      return;
     }
   string sym = MapAssetToSymbol(asset);
   if(sym == "")
     {
      Print("[AITO] Bỏ qua ", tag, ": asset không map được symbol.");
      return;
     }
   if(!SymbolSelect(sym, true) || SymbolInfoInteger(sym, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
     {
      Print("[AITO] Bỏ qua ", tag, ": symbol ", sym, " không có trong Market Watch hoặc không cho giao dịch.");
      ReportExecution(id, sym, action, 0, 0, 0, slSrv, tp1, 0, "symbol unavailable: " + sym, "");
      return;
     }
   if(SignalAlreadyOpen(id))
     {
      Print("[AITO] Bỏ qua ", tag, ": đã có vị thế của kèo này.");
      return;
     }
   int openCnt = CountOpenSignals(sym);
   if(openCnt >= MaxOpenPerSymbol)
     {
      Print("[AITO] Bỏ qua ", tag, ": ", sym, " đang mở ", openCnt, " kèo >= MaxOpenPerSymbol.");
      ReportExecution(id, sym, action, 0, 0, 0, slSrv, tp1, 0, "skipped: max open per symbol", "");
      return;
     }
   if(!DailyLossOk())
     {
      Print("[AITO] Bỏ qua ", tag, ": đã chạm giới hạn lỗ ngày.");
      ReportExecution(id, sym, action, 0, 0, 0, slSrv, tp1, 0, "skipped: daily loss limit", "");
      return;
     }
   if(!DryRun && !EnableTrading)
     {
      Print("[AITO] Bỏ qua ", tag, ": EnableTrading=false.");
      return;
     }
   if(!DryRun && (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) == 0 || MQLInfoInteger(MQL_TRADE_ALLOWED) == 0 || AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) == 0))
     {
      Print("[AITO] Bỏ qua ", tag, ": terminal/tài khoản chưa cho phép Algo Trading.");
      ReportExecution(id, sym, action, 0, 0, 0, slSrv, tp1, 0, "algo trading disabled in terminal", "");
      return;
     }

   bool   isBuy = (action == "BUY");
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double mkt = isBuy ? ask : bid;

   // SL/TP: giữ khoảng cách của server so với entry, áp lên giá thị trường hiện tại
   double slDist  = MathAbs(entry - slSrv);
   double tp1Dist = MathAbs(tp1 - entry);
   double tp2Dist = MathAbs(tp2 - entry);
   if(slDist <= 0 || tp1Dist <= 0)
     {
      Print("[AITO] Bỏ qua ", tag, ": SL/TP server không hợp lệ (entry=", entry, " sl=", slSrv, " tp1=", tp1, ").");
      ReportExecution(id, sym, action, 0, 0, mkt, slSrv, tp1, 0, "invalid sl/tp in signal", "");
      return;
     }
   double sl   = isBuy ? mkt - slDist  : mkt + slDist;
   double tpA  = isBuy ? mkt + tp1Dist : mkt - tp1Dist;
   double tpB  = (tp2Dist > 0) ? (isBuy ? mkt + tp2Dist : mkt - tp2Dist) : 0.0;
   sl  = NormalizePrice(sym, sl);
   tpA = NormalizePrice(sym, tpA);
   tpB = NormalizePrice(sym, tpB);

   // Lot
   double lot = UseServerLot ? lotSrv : LotByRisk(sym, slDist);
   if(lot <= 0)
     {
      Print("[AITO] Bỏ qua ", tag, ": lot tính ra <= 0.");
      ReportExecution(id, sym, action, 0, 0, mkt, sl, tpA, 0, "lot <= 0", "");
      return;
     }
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   bool split = SplitTP && tpB > 0 && (lot / 2.0) >= vmin;
   Print(StringFormat("[AITO] %s | giá %s | lot raw %.4f | SL %s | TP1 %s | TP2 %s | split=%s | tuổi %ds",
                      tag, DoubleToString(mkt, digits), lot, DoubleToString(sl, digits),
                      DoubleToString(tpA, digits), DoubleToString(tpB, digits), split ? "yes" : "no", (int)age));

   string err; int rc; double fill;
   if(!split)
     {
      double lotOne = NormalizeLot(sym, lot);
      double slOne = sl, tpOne = tpA;
      if(!AdjustStops(sym, isBuy, slOne, tpOne))
        {
         Print("[AITO] Bỏ qua ", tag, ": SL sai phía so với giá hiện tại.");
         ReportExecution(id, sym, action, lotOne, 0, mkt, slOne, tpOne, 0, "sl on wrong side", "");
         return;
        }
      PlaceMarket(id, sym, isBuy, lotOne, slOne, tpOne, "AITO#" + IntegerToString(id), err, rc, fill);
      return;
     }
   double l1 = NormalizeLot(sym, lot / 2.0);
   double l2 = NormalizeLot(sym, lot - l1);
   double s1 = sl, t1 = tpA;
   double s2 = sl, t2 = tpB;
   if(!AdjustStops(sym, isBuy, s1, t1) || !AdjustStops(sym, isBuy, s2, t2))
     {
      Print("[AITO] Bỏ qua ", tag, ": SL sai phía so với giá hiện tại.");
      ReportExecution(id, sym, action, l1 + l2, 0, mkt, sl, tpA, 0, "sl on wrong side", "");
      return;
     }
   ulong tk1 = PlaceMarket(id, sym, isBuy, l1, s1, t1, "AITO#" + IntegerToString(id) + "/TP1", err, rc, fill);
   if(!DryRun && tk1 == 0)
     {
      Print("[AITO] Lệnh TP1 thất bại -> không đặt lệnh TP2 của ", tag);
      return;
     }
   PlaceMarket(id, sym, isBuy, l2, s2, t2, "AITO#" + IntegerToString(id) + "/TP2", err, rc, fill);
  }

//+------------------------------------------------------------------+
//| POLL                                                              |
//+------------------------------------------------------------------+
datetime FetchServerTime()
  {
   string body;
   int code = HttpGet(ServerUrl + "/api/health", body);
   if(code != 200) return 0;
   // /api/health là object, không phải array -> đọc trực tiếp
   return ParseServerTime(JsonGetString(body, "time"));
  }

void PollSignals()
  {
   string body;
   int code = HttpGet(ServerUrl + "/api/signals?limit=5", body);
   if(code != 200)
     {
      Print("[AITO] GET /api/signals code=", code, (body != "" ? " body=" + StringSubstr(body, 0, 200) : ""));
      return;
     }
   string objs[];
   int n = JsonSplitArray(body, objs);
   if(n == 0) return;

   // "bây giờ" theo đồng hồ server để tính tuổi kèo (tránh lệch múi giờ VPS/server)
   datetime serverNow = FetchServerTime();
   if(serverNow == 0) serverNow = TimeLocal();
   else g_serverOffset = (long)(serverNow - TimeLocal());
   UiStoreLatestSignal(objs[0]);   // server trả DESC -> phần tử 0 là kèo mới nhất

   // Server trả DESC theo id -> xử lý từ cũ đến mới
   long maxId = g_lastId;
   for(int i = n - 1; i >= 0; i--)
     {
      long id = JsonGetInt(objs[i], "id");
      if(id <= g_lastId) continue;
      ProcessSignal(objs[i], serverNow);
      if(id > maxId) maxId = id;
     }
   if(maxId != g_lastId)
     {
      g_lastId = maxId;
      GlobalVariableSet(g_gvLastId, (double)g_lastId);
     }
  }

//+------------------------------------------------------------------+
//| CẤU HÌNH TỪ SERVER                                                |
//+------------------------------------------------------------------+
bool JsonGetBool(const string obj, const string key, bool def)
  {
   string raw = JsonGetRaw(obj, key);
   if(raw == "") return def;
   if(raw == "true" || raw == "1") return true;
   if(raw == "false" || raw == "0" || raw == "null") return false;
   return def;
  }

// Tải GET /api/ea/config, áp vào biến toàn cục. Trả về true nếu thành công.
bool FetchServerConfig(bool verbose)
  {
   string body;
   int code = HttpGet(ServerUrl + "/api/ea/config", body);
   if(code != 200 || StringLen(body) < 10)
     {
      if(verbose) Print("[AITO] Không tải được cấu hình (code=", code, "), dùng giá trị hiện tại.");
      return false;
     }
   long   oldMagic  = MagicNumber;
   string oldGold   = GoldSymbol, oldBtc = BtcSymbol;

   PollSeconds         = (int)JsonGetInt(body, "poll_seconds", PollSeconds);
   WebTimeoutMs        = (int)JsonGetInt(body, "web_timeout_ms", WebTimeoutMs);
   ReportExecutions    = JsonGetBool(body, "report_executions", ReportExecutions);
   EnablePriceBridge   = JsonGetBool(body, "enable_price_bridge", EnablePriceBridge);
   TickIntervalMs      = (int)JsonGetInt(body, "tick_interval_ms", TickIntervalMs);
   CandleIntervalSec   = (int)JsonGetInt(body, "candle_interval_sec", CandleIntervalSec);
   BridgeBars          = (int)JsonGetInt(body, "bridge_bars", BridgeBars);
   MinConfidence       = (int)JsonGetInt(body, "min_confidence", MinConfidence);
   MaxSignalAgeSec     = (int)JsonGetInt(body, "max_signal_age_sec", MaxSignalAgeSec);
   GoldSymbol          = JsonGetString(body, "gold_symbol", GoldSymbol);
   BtcSymbol           = JsonGetString(body, "btc_symbol", BtcSymbol);
   MaxOpenPerSymbol    = (int)JsonGetInt(body, "max_open_per_symbol", MaxOpenPerSymbol);
   UseServerLot        = JsonGetBool(body, "use_server_lot", UseServerLot);
   RiskPercent         = JsonGetDouble(body, "risk_percent", RiskPercent);
   SplitTP             = JsonGetBool(body, "split_tp", SplitTP);
   BreakEvenBufferPts  = (int)JsonGetInt(body, "breakeven_buffer_pts", BreakEvenBufferPts);
   MaxDailyLossPercent = JsonGetDouble(body, "max_daily_loss_pct", MaxDailyLossPercent);
   DryRun              = JsonGetBool(body, "dry_run", DryRun);
   EnableTrading       = JsonGetBool(body, "enable_trading", EnableTrading);
   MagicNumber         = JsonGetInt(body, "magic", MagicNumber);
   SlippagePoints      = (int)JsonGetInt(body, "slippage_points", SlippagePoints);

   if(PollSeconds < 3) PollSeconds = 3;
   if(TickIntervalMs < 200) TickIntervalMs = 200;
   if(CandleIntervalSec < 5) CandleIntervalSec = 5;
   if(BridgeBars < 50) BridgeBars = 50;

   // áp dụng thay đổi
   if(GoldSymbol != oldGold || !g_cfgLoaded)
      if(!SymbolSelect(GoldSymbol, true)) Print("[AITO] ⚠️ Không tìm thấy symbol vàng ", GoldSymbol);
   if(BtcSymbol != "" && (BtcSymbol != oldBtc || !g_cfgLoaded))
      if(!SymbolSelect(BtcSymbol, true)) Print("[AITO] ⚠️ Không tìm thấy symbol BTC ", BtcSymbol);
   if(MagicNumber != oldMagic || !g_cfgLoaded)
     {
      g_trade.SetExpertMagicNumber((ulong)MagicNumber);
      g_gvLastId = "AITO_LastId_" + IntegerToString(MagicNumber);
      if(GlobalVariableCheck(g_gvLastId)) g_lastId = (long)GlobalVariableGet(g_gvLastId);
      else GlobalVariableSet(g_gvLastId, 0.0);
     }
   g_trade.SetDeviationInPoints((ulong)SlippagePoints);
   // timer chạy cố định UI_FRAME_MS; tick/poll được điều tiết trong OnTimer
   bool   oldShow  = g_showPanel;
   g_showPanel = JsonGetBool(body, "show_panel", g_showPanel);
   g_scale     = JsonGetDouble(body, "panel_scale", g_scale);
   if(g_scale < 0.6) g_scale = 0.6;
   if(g_scale > 2.0) g_scale = 2.0;
   if(oldShow && !g_showPanel) UiDeleteAll();
   if(!oldShow && g_showPanel) Comment("");
   bool first = !g_cfgLoaded;
   g_cfgLoaded = true;
   g_lastCfgFetch = TimeLocal();
   if(first) UiTicker("Đã kết nối server, tải cấu hình thành công");
   g_cfgSummary = StringFormat("gold=%s btc=%s bridge=%s minConf=%d dryRun=%s trading=%s risk=%.1f%% splitTP=%s",
                               GoldSymbol, BtcSymbol, EnablePriceBridge ? "on" : "off", MinConfidence,
                               DryRun ? "on" : "off", EnableTrading ? "on" : "off", RiskPercent, SplitTP ? "on" : "off");
   if(verbose || first) Print("[AITO] Cấu hình từ server: ", g_cfgSummary);
   if(first && DryRun) Print("[AITO] ⚠️ DryRun=true: chỉ in log, không đặt lệnh. Đổi trong Cài đặt trên web.");
   return true;
  }

//+------------------------------------------------------------------+
//| PRICE BRIDGE — đẩy giá realtime lên server                        |
//+------------------------------------------------------------------+
string BrD(double v, int digits) { return DoubleToString(v, digits); }

string BridgeTfName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M5:  return "5m";
      case PERIOD_M15: return "15m";
      case PERIOD_H1:  return "1h";
      case PERIOD_H4:  return "4h";
     }
   return "";
  }

// JSON phần "asset","symbol","tick":{...} (không có ngoặc nhọn bao ngoài)
string BridgeTickJson(const string asset, const string sym)
  {
   MqlTick t;
   if(!SymbolInfoTick(sym, t)) return "";
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double last = (t.last > 0) ? t.last : (t.bid + t.ask) / 2.0;
   MqlRates h1[];
   double changePct = 0, high24 = t.bid, low24 = t.bid, vol24 = 0;
   int n = CopyRates(sym, PERIOD_H1, 0, 25, h1);   // thứ tự cũ -> mới
   if(n > 1)
     {
      double base = h1[0].close;
      if(base > 0) changePct = (last - base) / base * 100.0;
      high24 = h1[1].high; low24 = h1[1].low;
      for(int i = 1; i < n; i++)
        {
         if(h1[i].high > high24) high24 = h1[i].high;
         if(h1[i].low  < low24)  low24  = h1[i].low;
         vol24 += (double)h1[i].tick_volume;
        }
      if(last > high24) high24 = last;
      if(last < low24)  low24  = last;
     }
   return StringFormat("\"asset\":\"%s\",\"symbol\":\"%s\",\"tick\":{\"bid\":%s,\"ask\":%s,\"last\":%s,\"change_pct\":%s,\"high24\":%s,\"low24\":%s,\"volume24\":%s}",
                       asset, sym, BrD(t.bid, digits), BrD(t.ask, digits), BrD(last, digits), BrD(changePct, 4),
                       BrD(high24, digits), BrD(low24, digits), BrD(vol24, 0));
  }

string BridgeCandlesJson(const string sym, ENUM_TIMEFRAMES tf, int bars)
  {
   MqlRates r[];
   int n = CopyRates(sym, tf, 0, bars, r);
   if(n < (bars >= 30 ? 30 : 1)) return "";
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   string s = "[";
   for(int i = 0; i < n; i++)
     {
      double v = (r[i].real_volume > 0) ? (double)r[i].real_volume : (double)r[i].tick_volume;
      s += StringFormat("{\"t\":%d,\"o\":%s,\"h\":%s,\"l\":%s,\"c\":%s,\"v\":%s}",
                        (int)r[i].time, BrD(r[i].open, digits), BrD(r[i].high, digits), BrD(r[i].low, digits), BrD(r[i].close, digits), BrD(v, 0));
      if(i < n - 1) s += ",";
     }
   return s + "]";
  }

bool BridgePost(const string json)
  {
   string body;
   int code = HttpPostJson(ServerUrl + "/api/push_price", json, body);
   g_pushTotal++;
   if(code == 200) g_pushOk++;
   if(code != 200)
     {
      g_lastBridgeCode  = code;
      g_lastBridgeErrAt = TimeLocal();
      g_lastBridgeErr   = (code == -1 ? g_lastErrorText :
                           (code >= 1000 ? "MT5 trả mã " + IntegerToString(code) + " (không phải từ server)"
                                         : "HTTP " + IntegerToString(code) + " " + StringSubstr(body, 0, 60)));
      g_bridgeErrors++;
      if(g_bridgeErrors == 1 || g_bridgeErrors % 60 == 0)
         Print("[AITO] Bridge lỗi (code=", code, ") lần ", g_bridgeErrors, ": ", StringSubstr(body, 0, 150));
      return false;
     }
   if(g_bridgeErrors > 0) Print("[AITO] Bridge kết nối lại OK.");
   g_bridgeErrors = 0;
   return true;
  }

void RunPriceBridge()
  {
   if(!EnablePriceBridge) return;
   bool pushCandles = (TimeLocal() - g_lastCandlePush >= CandleIntervalSec);
   // Gửi đủ nến mỗi 5 phút hoặc sau lỗi; các lần khác chỉ gửi 3 nến cuối (server tự gộp)
   bool full = g_needFull || (TimeLocal() - g_lastFullPush >= 300);
   int  bars = full ? BridgeBars : 3;
   bool allOk = true;
   ENUM_TIMEFRAMES tfs[4] = {PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4};
   string assets[2];
   string symbols[2];
   assets[0] = "XAUUSD";  symbols[0] = GoldSymbol;   // MQL5 không cho khởi tạo mảng bằng input
   assets[1] = "BTCUSDT"; symbols[1] = BtcSymbol;
   for(int i = 0; i < 2; i++)
     {
      if(symbols[i] == "") continue;
      string tick = BridgeTickJson(assets[i], symbols[i]);
      if(tick == "") continue;
      if(pushCandles)
        {
         for(int k = 0; k < 4; k++)
           {
            string candles = BridgeCandlesJson(symbols[i], tfs[k], bars);
            if(candles == "") continue;
            if(!BridgePost("{" + tick + ",\"tf\":\"" + BridgeTfName(tfs[k]) + "\",\"candles\":" + candles + "}"))
               allOk = false;
           }
        }
      else
         BridgePost("{" + tick + "}");
     }
   if(pushCandles)
     {
      g_lastCandlePush = TimeLocal();
      if(full && allOk) { g_lastFullPush = TimeLocal(); g_needFull = false; }
      if(!allOk) g_needFull = true;
      UiTicker("Đã gửi nến M5/M15/H1/H4 của " + GoldSymbol + (BtcSymbol != "" ? " và " + BtcSymbol : ""));
     }
   g_bridgeStatus = StringFormat("Bridge: %s%s | lỗi liên tiếp %d | nến lần cuối %s",
                                 GoldSymbol, (BtcSymbol != "" ? " + " + BtcSymbol : ""), g_bridgeErrors,
                                 TimeToString(g_lastCandlePush, TIME_SECONDS));
  }

//+------------------------------------------------------------------+
//| BẢNG ĐIỀU KHIỂN TRÊN CHART (đồ hoạ + animation)                    |
//+------------------------------------------------------------------+
#define CLR_BG       C'13,18,32'
#define CLR_CARD     C'22,30,52'
#define CLR_CARD2    C'28,38,64'
#define CLR_LINE     C'45,58,92'
#define CLR_TEXT     C'232,238,250'
#define CLR_MUTED    C'136,148,178'
#define CLR_GREEN    C'46,204,113'
#define CLR_RED      C'255,92,92'
#define CLR_AMBER    C'245,182,60'
#define CLR_BLUE     C'77,163,255'
#define CLR_GOLD     C'255,205,80'
#define CLR_BTC      C'247,147,26'

int S(double v) { return (int)MathRound(v * g_scale); }

color UiMix(color a, color b, double t)
  {
   if(t < 0) t = 0;
   if(t > 1) t = 1;
   int ar = (int)a & 0xFF, ag = ((int)a >> 8) & 0xFF, ab = ((int)a >> 16) & 0xFF;
   int br = (int)b & 0xFF, bg = ((int)b >> 8) & 0xFF, bb = ((int)b >> 16) & 0xFF;
   int r = (int)MathRound(ar + (br - ar) * t);
   int g = (int)MathRound(ag + (bg - ag) * t);
   int bl = (int)MathRound(ab + (bb - ab) * t);
   return (color)(r | (g << 8) | (bl << 16));
  }

void UiRect(const string id, int x, int y, int w, int h, color bg, color border = clrNONE)
  {
   string n = UI_PREFIX + id;
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, n, OBJPROP_BACK, false);
     }
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, g_px + S(x));
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, g_py + S(y));
   ObjectSetInteger(0, n, OBJPROP_XSIZE, MathMax(1, S(w)));
   ObjectSetInteger(0, n, OBJPROP_YSIZE, MathMax(1, S(h)));
   ObjectSetInteger(0, n, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, n, OBJPROP_COLOR, border == clrNONE ? bg : border);
   ObjectSetInteger(0, n, OBJPROP_WIDTH, 1);
  }

void UiText(const string id, int x, int y, const string text, color clr, int size,
            const string font = "Segoe UI", ENUM_ANCHOR_POINT anchor = ANCHOR_LEFT_UPPER)
  {
   string n = UI_PREFIX + id;
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, n, OBJPROP_BACK, false);
     }
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, g_px + S(x));
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, g_py + S(y));
   ObjectSetString(0, n, OBJPROP_TEXT, StringSubstr(text, 0, 63));   // OBJ_LABEL tối đa 63 ký tự
   ObjectSetString(0, n, OBJPROP_FONT, font);
   ObjectSetInteger(0, n, OBJPROP_FONTSIZE, MathMax(6, S(size)));
   ObjectSetInteger(0, n, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, n, OBJPROP_ANCHOR, anchor);
  }

// Thanh tiến trình: nền + phần đã chạy
void UiBar(const string id, int x, int y, int w, int h, double ratio, color fill, color bg = CLR_LINE)
  {
   if(ratio < 0) ratio = 0;
   if(ratio > 1) ratio = 1;
   UiRect(id + "_bg", x, y, w, h, bg);
   UiRect(id + "_fg", x, y, (int)MathMax(1, w * ratio), h, ratio <= 0.001 ? bg : fill);
  }

void UiDeleteAll() { ObjectsDeleteAll(0, UI_PREFIX); ChartRedraw(); }

void UiTicker(const string msg) { g_ticker = TimeToString(TimeLocal(), TIME_SECONDS) + "  " + msg; }

string UiAgo(long sec)
  {
   if(sec < 0) sec = 0;
   if(sec < 60)   return IntegerToString(sec) + " giây trước";
   if(sec < 3600) return IntegerToString(sec / 60) + " phút trước";
   return IntegerToString(sec / 3600) + " giờ trước";
  }

void UiStoreLatestSignal(const string obj)
  {
   long id = JsonGetInt(obj, "id");
   if(id <= 0) return;
   if(id != g_sigId)
     {
      g_sigAnimStart = GetTickCount64();
      if(g_sigId != 0)
         UiTicker("Kèo mới #" + IntegerToString(id) + " " + JsonGetString(obj, "action") + " " +
                  JsonGetString(obj, "asset") + " " + IntegerToString(JsonGetInt(obj, "confidence")) + "%");
     }
   g_sigId      = id;
   g_sigAction  = JsonGetString(obj, "action", "WAIT");
   g_sigAsset   = JsonGetString(obj, "asset");
   g_sigTf      = JsonGetString(obj, "timeframe");
   g_sigConf    = (int)JsonGetInt(obj, "confidence");
   g_sigEntry   = JsonGetDouble(obj, "entry");
   g_sigSL      = JsonGetDouble(obj, "stop_loss");
   g_sigTP1     = JsonGetDouble(obj, "take_profit_1");
   g_sigTP2     = JsonGetDouble(obj, "take_profit_2");
   g_sigCreated = ParseServerTime(JsonGetString(obj, "created_at"));
  }

void UiPriceCard(int idx, const string sym, const string label, color accent, int x, int y, int w, int h, ulong nowMs)
  {
   string k = "pc" + IntegerToString(idx);
   if(sym == "")
     {
      UiRect(k + "_bg", x, y, w, h, CLR_CARD, CLR_LINE);
      UiRect(k + "_ac", x, y, 4, h, CLR_LINE);
      UiText(k + "_nm", x + 14, y + 8, label, CLR_MUTED, 9, "Segoe UI Semibold");
      UiText(k + "_px", x + 14, y + 28, "Không dùng", CLR_MUTED, 14, "Segoe UI");
      UiText(k + "_ar", x + w - 14, y + 30, " ", CLR_MUTED, 14, "Segoe UI", ANCHOR_RIGHT_UPPER);
      UiText(k + "_sb", x + 14, y + 58, "Server lấy giá từ Binance", CLR_MUTED, 8);
      return;
     }
   MqlTick t;
   bool ok = SymbolInfoTick(sym, t);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(ok && g_prevBid[idx] > 0 && t.bid != g_prevBid[idx])
     {
      g_flashMs[idx] = nowMs;
      g_flashUp[idx] = (t.bid > g_prevBid[idx]);
     }
   if(ok) g_prevBid[idx] = t.bid;
   double fade = (double)(nowMs - g_flashMs[idx]) / 900.0;   // 0 -> 1 trong 0.9s
   color flash = g_flashUp[idx] ? CLR_GREEN : CLR_RED;
   color border = (g_flashMs[idx] > 0 && fade < 1) ? UiMix(flash, CLR_LINE, fade) : CLR_LINE;
   color pxClr  = (g_flashMs[idx] > 0 && fade < 1) ? UiMix(flash, CLR_TEXT, fade) : CLR_TEXT;

   UiRect(k + "_bg", x, y, w, h, CLR_CARD, border);
   UiRect(k + "_ac", x, y, 4, h, accent);
   UiText(k + "_nm", x + 14, y + 8, label + "  ·  " + sym, accent, 9, "Segoe UI Semibold");
   UiText(k + "_px", x + 14, y + 26, ok ? DoubleToString(t.bid, digits) : "--", pxClr, 17, "Consolas");
   UiText(k + "_ar", x + w - 14, y + 28, g_flashUp[idx] ? "▲" : "▼", g_flashUp[idx] ? CLR_GREEN : CLR_RED, 14, "Segoe UI", ANCHOR_RIGHT_UPPER);
   double spread = ok ? t.ask - t.bid : 0;
   UiText(k + "_sb", x + 14, y + 58, ok ? "Ask " + DoubleToString(t.ask, digits) + "   Spread " + DoubleToString(spread, digits) : "Chưa có tick",
          CLR_MUTED, 8, "Consolas");
  }

void UiDraw()
  {
   if(!g_showPanel) return;
   ulong nowMs = GetTickCount64();
   g_frame++;
   double ph = (double)(nowMs % 1600) / 1600.0;                     // pha 0..1 cho nhịp đập
   double pulse = 0.5 + 0.5 * MathSin(ph * 2 * M_PI);
   bool online = g_cfgLoaded && (TimeLocal() - g_lastServerOk) <= 20;
   color stClr = online ? CLR_GREEN : CLR_RED;
   int W = 480;

   // ---- khung nền ----
   UiRect("bg", 0, 0, W, 470, CLR_BG, CLR_LINE);

   // ---- HEADER ----
   UiRect("hd", 0, 0, W, 48, CLR_CARD2);
   UiRect("hd_ac", 0, 0, W, 3, UiMix(CLR_BLUE, CLR_AMBER, pulse));   // dải màu chuyển động
   UiText("hd_t", 16, 9, "AI TRADING OFFICE", CLR_TEXT, 13, "Segoe UI Black");
   UiText("hd_s", 16, 29, "Cầu nối giá MT5  ·  " + AccountInfoString(ACCOUNT_SERVER), CLR_MUTED, 8);
   UiText("hd_dot", W - 112, 24, "●", UiMix(stClr, CLR_BG, online ? 0.55 * (1 - pulse) : (g_frame % 4 < 2 ? 0.0 : 0.8)),
          (int)(11 + 5 * pulse), "Segoe UI", ANCHOR_CENTER);
   UiText("hd_st", W - 98, 15, online ? "ONLINE" : "OFFLINE", stClr, 12, "Segoe UI Black");

   // ---- KẾT NỐI ----
   int y = 58;
   UiRect("cn_bg", 10, y, W - 20, 46, CLR_CARD, CLR_LINE);
   UiText("cn_l", 22, y + 6, "MÁY CHỦ", CLR_MUTED, 7, "Segoe UI Semibold");
   UiText("cn_u", 22, y + 21, ServerUrl, CLR_TEXT, 10, "Consolas");
   string ping = online ? "Ping " + IntegerToString(g_latencyMs) + " ms" : "Mất kết nối";
   UiText("cn_p", W - 22, y + 6, ping, online ? (g_latencyMs < 400 ? CLR_GREEN : CLR_AMBER) : CLR_RED, 10, "Segoe UI Semibold", ANCHOR_RIGHT_UPPER);
   UiText("cn_c", W - 22, y + 25, g_cfgLoaded ? "Cấu hình tải " + UiAgo((long)(TimeLocal() - g_lastCfgFetch)) : "Đang thử kết nối...",
          CLR_MUTED, 8, "Segoe UI", ANCHOR_RIGHT_UPPER);

   // ---- GIÁ REALTIME ----
   y = 114;
   int cw = (W - 30) / 2;
   UiPriceCard(0, GoldSymbol, "VÀNG", CLR_GOLD, 10, y, cw, 78, nowMs);
   UiPriceCard(1, BtcSymbol, "BITCOIN", CLR_BTC, 20 + cw, y, cw, 78, nowMs);

   // ---- CẦU NỐI GIÁ ----
   y = 202;
   UiRect("br_bg", 10, y, W - 20, 70, CLR_CARD, CLR_LINE);
   string spin[4] = {"◐", "◓", "◑", "◒"};
   bool bridgeOn = EnablePriceBridge && online;
   UiText("br_sp", 22, y + 6, bridgeOn ? spin[(int)(g_frame / 2) % 4] : "○", bridgeOn ? CLR_BLUE : CLR_MUTED, 10);
   UiText("br_t", 40, y + 7, EnablePriceBridge ? "ĐANG ĐẨY GIÁ LÊN SERVER" : "ĐẨY GIÁ: TẮT", CLR_MUTED, 7, "Segoe UI Semibold");
   double okPct = g_pushTotal > 0 ? 100.0 * g_pushOk / g_pushTotal : 100.0;
   UiText("br_n", W - 22, y + 5, "Đã gửi " + IntegerToString(g_pushTotal) + "  ·  thành công " + DoubleToString(okPct, 1) + "%",
          okPct >= 99 ? CLR_GREEN : (okPct >= 90 ? CLR_AMBER : CLR_RED), 8, "Segoe UI Semibold", ANCHOR_RIGHT_UPPER);
   double cr = CandleIntervalSec > 0 ? (double)(TimeLocal() - g_lastCandlePush) / CandleIntervalSec : 0;
   UiText("br_cl", 22, y + 25, "Nến kế tiếp", CLR_MUTED, 8);
   UiBar("br_cb", 100, y + 29, W - 132, 7, cr, CLR_BLUE);
   bool recentErr = g_lastBridgeErrAt > 0 && (TimeLocal() - g_lastBridgeErrAt) < 300;
   string errLine = recentErr ? "Lỗi " + UiAgo((long)(TimeLocal() - g_lastBridgeErrAt)) + ": " + g_lastBridgeErr
                              : "Không có lỗi trong 5 phút qua";
   UiText("br_e", 22, y + 46, errLine, recentErr ? (g_bridgeErrors > 0 ? CLR_RED : CLR_AMBER) : CLR_GREEN, 8);

   // ---- KÈO MỚI NHẤT ----
   y = 282;
   UiRect("sg_bg", 10, y, W - 20, 92, CLR_CARD, CLR_LINE);
   UiText("sg_t", 22, y + 6, "KÈO MỚI NHẤT TỪ VĂN PHÒNG AI", CLR_MUTED, 7, "Segoe UI Semibold");
   if(g_sigId > 0)
     {
      color ac = g_sigAction == "BUY" ? CLR_GREEN : (g_sigAction == "SELL" ? CLR_RED : CLR_AMBER);
      double pop = MathMin(1.0, (double)(nowMs - g_sigAnimStart) / 1000.0);       // 0 -> 1 khi có kèo mới
      color badge = pop < 1 ? UiMix(CLR_TEXT, ac, pop) : ac;
      long age = (long)(TimeLocal() + g_serverOffset - g_sigCreated);
      UiText("sg_id", W - 22, y + 6, "#" + IntegerToString(g_sigId) + "  ·  " + UiAgo(age), CLR_MUTED, 8, "Segoe UI", ANCHOR_RIGHT_UPPER);
      UiRect("sg_bd", 22, y + 24, 86, 30, badge);
      UiText("sg_ac", 65, y + 39, g_sigAction, CLR_BG, 13, "Segoe UI Black", ANCHOR_CENTER);
      UiText("sg_as", 120, y + 24, g_sigAsset + "  " + g_sigTf, CLR_TEXT, 10, "Segoe UI Semibold");
      // thanh độ tự tin chạy dần từ 0 lên khi có kèo mới
      double cshow = g_sigConf * (pop < 1 ? (1 - MathPow(1 - pop, 3)) : 1);
      UiBar("sg_cf", 120, y + 44, 220, 8, cshow / 100.0, ac);
      UiRect("sg_th", 120 + (int)(220 * MinConfidence / 100.0), y + 40, 2, 16, CLR_TEXT);       // vạch ngưỡng EA
      UiText("sg_cp", 350, y + 38, IntegerToString((int)MathRound(cshow)) + "%", ac, 12, "Segoe UI Black");
      int d = (StringFind(g_sigAsset, "BTC") >= 0) ? 1 : 2;
      UiText("sg_px", 22, y + 64, "Entry " + DoubleToString(g_sigEntry, d) + "   SL " + DoubleToString(g_sigSL, d) +
             "   TP1 " + DoubleToString(g_sigTP1, d) + "   TP2 " + DoubleToString(g_sigTP2, d), CLR_TEXT, 8, "Consolas");
      bool pass = (g_sigAction == "BUY" || g_sigAction == "SELL") && g_sigConf >= MinConfidence;
      string vd = pass ? "✔ Đạt ngưỡng, EA sẽ vào lệnh" :
                  (g_sigAction == "WAIT" ? "WAIT · không vào lệnh" : "Chưa đạt ngưỡng " + IntegerToString(MinConfidence) + "%");
      UiText("sg_vd", W - 22, y + 24, vd,
             pass ? CLR_GREEN : CLR_MUTED, 8, "Segoe UI Semibold", ANCHOR_RIGHT_UPPER);
     }
   else
     {
      UiText("sg_id", W - 22, y + 6, " ", CLR_MUTED, 8, "Segoe UI", ANCHOR_RIGHT_UPPER);
      UiRect("sg_bd", 22, y + 24, 86, 30, CLR_LINE);
      UiText("sg_ac", 65, y + 39, "...", CLR_MUTED, 13, "Segoe UI Black", ANCHOR_CENTER);
      UiText("sg_as", 120, y + 24, "Chưa có kèo nào", CLR_MUTED, 10, "Segoe UI Semibold");
      UiBar("sg_cf", 120, y + 44, 220, 8, 0, CLR_LINE);
      UiRect("sg_th", 120 + (int)(220 * MinConfidence / 100.0), y + 40, 2, 16, CLR_MUTED);
      UiText("sg_cp", 350, y + 38, " ", CLR_MUTED, 12);
      UiText("sg_px", 22, y + 64, "Bấm Họp Kèo trên web hoặc bật Auto-Pilot", CLR_MUTED, 8);
      UiText("sg_vd", W - 22, y + 24, " ", CLR_MUTED, 8, "Segoe UI", ANCHOR_RIGHT_UPPER);
     }

   // ---- CHẾ ĐỘ GIAO DỊCH ----
   y = 384;
   if(nowMs - g_pnlMs > 2000)
     {
      g_pnlMs = nowMs;
      g_pnlToday = RealizedToday() + FloatingOfEA();
      g_openCount = CountOpenSignals(GoldSymbol) + (BtcSymbol != "" ? CountOpenSignals(BtcSymbol) : 0);
     }
   bool live = !DryRun && EnableTrading;
   string mode = live ? "LIVE" : (DryRun ? "DRY RUN" : "TẮT");
   color mc = live ? UiMix(CLR_RED, C'120,20,20', pulse) : (DryRun ? CLR_AMBER : CLR_MUTED);
   UiRect("md_bg", 10, y, W - 20, 50, CLR_CARD, live ? mc : CLR_LINE);
   UiRect("md_bd", 22, y + 10, 92, 30, mc);
   UiText("md_tx", 68, y + 25, mode, CLR_BG, 11, "Segoe UI Black", ANCHOR_CENTER);
   UiText("md_d1", 126, y + 8, live ? "EA ĐƯỢC PHÉP ĐẶT LỆNH" : (DryRun ? "Chỉ ghi log, KHÔNG đặt lệnh" : "Khớp lệnh đang tắt"),
          live ? CLR_RED : CLR_TEXT, 9, "Segoe UI Semibold");
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   UiText("md_d2", 126, y + 27, "Lệnh mở " + IntegerToString(g_openCount) + "  ·  Hôm nay " +
          (g_pnlToday >= 0 ? "+" : "") + DoubleToString(g_pnlToday, 2) + " " + cur + "  ·  Rủi ro " + DoubleToString(RiskPercent, 1) + "%",
          g_pnlToday > 0 ? CLR_GREEN : (g_pnlToday < 0 ? CLR_RED : CLR_MUTED), 8);

   // ---- FOOTER: chữ chạy + đếm ngược hỏi kèo ----
   y = 442;
   string tape = g_ticker + "      •      ";
   int L = StringLen(tape);
   int off = L > 0 ? (int)((g_frame / 2) % L) : 0;
   UiText("ft_tx", 14, y, StringSubstr(tape + tape, off, 62), CLR_MUTED, 8, "Consolas");
   double pr = PollSeconds > 0 ? (double)(TimeLocal() - g_lastPoll) / PollSeconds : 0;
   UiBar("ft_pb", 10, y + 18, W - 20, 3, pr, UiMix(CLR_BLUE, CLR_GREEN, pr), CLR_CARD);

   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| THÔNG TIN TÀI KHOẢN -> server (POST /api/push_account)             |
//+------------------------------------------------------------------+
string AccD(double v, int d = 2) { return DoubleToString(v, d); }

string DealReasonTxt(long r, const string cmt)
  {
   if(r == DEAL_REASON_TP || StringFind(cmt, "[tp") >= 0) return "TP";
   if(r == DEAL_REASON_SL || StringFind(cmt, "[sl") >= 0) return "SL";
   if(r == DEAL_REASON_SO || StringFind(cmt, "[so") >= 0) return "SO";
   return "MANUAL";
  }

ulong    g_lastClosedDeal = 0;
datetime g_lastClosedScan = 0;

string BuildRecentClosedJson()
  {
   datetime now = TimeCurrent();
   if(g_lastClosedScan != 0 && now - g_lastClosedScan < 6) return "[]";
   g_lastClosedScan = now;
   datetime from = now - 3 * 86400;
   if(!HistorySelect(from, now + 60)) return "[]";
   int n = HistoryDealsTotal();
   // Lần đầu khởi động: quét 20 deal đóng gần nhất của EA để đồng bộ trạng thái SL/TP lên server;
   // các lần sau chỉ gửi deal đóng mới (ticket > g_lastClosedDeal)
   ulong maxDeal = g_lastClosedDeal;
   string arr = "";
   int added = 0;
   for(int i = n - 1; i >= 0 && added < 20; i--)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if(g_lastClosedDeal > 0 && d <= g_lastClosedDeal) break;
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT && entry != DEAL_ENTRY_OUT_BY) continue;
      long pid = HistoryDealGetInteger(d, DEAL_POSITION_ID);
      if(pid <= 0) continue;
      long mg = HistoryDealGetInteger(d, DEAL_MAGIC);
      string cmt = HistoryDealGetString(d, DEAL_COMMENT);
      double openPrice = 0;
      string openCmt = "";
      long openType = -1;
      // Tìm deal IN của cùng position để lấy comment gốc "AITO#<id>/TP1" và giá mở cửa
      for(int k = i - 1; k >= 0; k--)
        {
         ulong din = HistoryDealGetTicket(k);
         if(din == 0) continue;
         if(HistoryDealGetInteger(din, DEAL_POSITION_ID) != pid) continue;
         if(HistoryDealGetInteger(din, DEAL_ENTRY) == DEAL_ENTRY_IN)
           {
            openPrice = HistoryDealGetDouble(din, DEAL_PRICE);
            openCmt = HistoryDealGetString(din, DEAL_COMMENT);
            openType = HistoryDealGetInteger(din, DEAL_TYPE);
            if(mg == 0) mg = HistoryDealGetInteger(din, DEAL_MAGIC);
            break;
           }
        }
      if(mg != MagicNumber && StringFind(openCmt, "AITO#") < 0 && StringFind(cmt, "AITO#") < 0) continue;
      string sym = HistoryDealGetString(d, DEAL_SYMBOL);
      int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double net = HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) +
                   HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_FEE);
      long rsn = HistoryDealGetInteger(d, DEAL_REASON);
      string rsnTxt = DealReasonTxt(rsn, cmt);
      string fullCmt = (openCmt != "" ? openCmt : cmt);
      long sid = SignalIdFromComment(fullCmt);
      string side = (openType == DEAL_TYPE_BUY ? "BUY" : (openType == DEAL_TYPE_SELL ? "SELL" :
                    (HistoryDealGetInteger(d, DEAL_TYPE) == DEAL_TYPE_SELL ? "BUY" : "SELL")));
      if(added > 0) arr += ",";
      arr += "{\"deal_ticket\":" + IntegerToString((long)d) +
             ",\"position\":" + IntegerToString(pid) +
             ",\"signal_id\":" + IntegerToString(sid) +
             ",\"symbol\":\"" + JsonEscape(sym) + "\"" +
             ",\"side\":\"" + side + "\"" +
             ",\"volume\":" + AccD(HistoryDealGetDouble(d, DEAL_VOLUME), 2) +
             ",\"open_price\":" + AccD(openPrice, dg) +
             ",\"close_price\":" + AccD(HistoryDealGetDouble(d, DEAL_PRICE), dg) +
             ",\"net\":" + AccD(net, 2) +
             ",\"reason\":\"" + rsnTxt + "\"" +
             ",\"comment\":\"" + JsonEscape(fullCmt) + "\"" +
             ",\"close_time\":\"" + TimeToString((datetime)HistoryDealGetInteger(d, DEAL_TIME), TIME_DATE | TIME_SECONDS) + "\"}";
      if(d > maxDeal) maxDeal = d;
      added++;
     }
   if(maxDeal > g_lastClosedDeal) g_lastClosedDeal = maxDeal;
   else if(g_lastClosedDeal == 0 && n > 0) g_lastClosedDeal = HistoryDealGetTicket(n - 1);
   return "[" + arr + "]";
  }

string BuildAccountJson()
  {
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string modeTxt = (mode == ACCOUNT_TRADE_MODE_DEMO ? "demo" : (mode == ACCOUNT_TRADE_MODE_CONTEST ? "contest" : "real"));
   double realized = RealizedToday();
   double floatingEa = FloatingOfEA();
   string js = "{";
   js += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   js += ",\"ea_version\":\"" + EA_VERSION + "\"";
   js += ",\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"";
   js += ",\"company\":\"" + JsonEscape(AccountInfoString(ACCOUNT_COMPANY)) + "\"";
   js += ",\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\"";
   js += ",\"trade_mode\":\"" + modeTxt + "\"";
   js += ",\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE));
   js += ",\"balance\":" + AccD(AccountInfoDouble(ACCOUNT_BALANCE));
   js += ",\"equity\":" + AccD(AccountInfoDouble(ACCOUNT_EQUITY));
   js += ",\"margin\":" + AccD(AccountInfoDouble(ACCOUNT_MARGIN));
   js += ",\"free_margin\":" + AccD(AccountInfoDouble(ACCOUNT_MARGIN_FREE));
   js += ",\"margin_level\":" + AccD(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL));
   js += ",\"profit\":" + AccD(AccountInfoDouble(ACCOUNT_PROFIT));
   js += ",\"ea_realized_today\":" + AccD(realized);
   js += ",\"ea_floating\":" + AccD(floatingEa);
   js += ",\"ea_magic\":" + IntegerToString(MagicNumber);
   js += ",\"terminal_time\":\"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\"";
   js += ",\"positions\":[";
   int total = PositionsTotal(), added = 0;
   for(int i = 0; i < total && added < 50; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      int d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      long type = PositionGetInteger(POSITION_TYPE);
      if(added > 0) js += ",";
      js += "{\"ticket\":" + IntegerToString((long)ticket);
      js += ",\"symbol\":\"" + JsonEscape(sym) + "\"";
      js += ",\"type\":\"" + (type == POSITION_TYPE_BUY ? "BUY" : "SELL") + "\"";
      js += ",\"volume\":" + AccD(PositionGetDouble(POSITION_VOLUME), 2);
      js += ",\"open\":" + AccD(PositionGetDouble(POSITION_PRICE_OPEN), d);
      js += ",\"current\":" + AccD(PositionGetDouble(POSITION_PRICE_CURRENT), d);
      js += ",\"sl\":" + AccD(PositionGetDouble(POSITION_SL), d);
      js += ",\"tp\":" + AccD(PositionGetDouble(POSITION_TP), d);
      js += ",\"profit\":" + AccD(PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP));
      js += ",\"magic\":" + IntegerToString(PositionGetInteger(POSITION_MAGIC));
      js += ",\"comment\":\"" + JsonEscape(PositionGetString(POSITION_COMMENT)) + "\"";
      js += ",\"time\":\"" + TimeToString((datetime)PositionGetInteger(POSITION_TIME), TIME_DATE | TIME_SECONDS) + "\"}";
      added++;
     }
   js += "]";
   string closedJson = BuildRecentClosedJson();
   if(closedJson != "[]") js += ",\"recent_closed\":" + closedJson;
   js += "}";
   return js;
  }

//+------------------------------------------------------------------+
//| LỊCH SỬ GIAO DỊCH THEO MAGIC (chỉ chạy khi dashboard yêu cầu)      |
//+------------------------------------------------------------------+
string DealTypeTxt(long t) { return t == DEAL_TYPE_BUY ? "buy" : (t == DEAL_TYPE_SELL ? "sell" : "other"); }

bool PosIdInList(const long &ids[], long id)
  {
   for(int i = ArraySize(ids) - 1; i >= 0; i--) if(ids[i] == id) return true;
   return false;
  }

void HandleHistoryRequest(const string req)
  {
   long id = JsonGetInt(req, "id");
   if(id <= 0 || id == g_lastHistReqId) return;      // chỉ bỏ qua yêu cầu ĐÃ GỬI THÀNH CÔNG
   string ackBody;
   int ack = HttpPostJson(ServerUrl + "/api/push_history", "{\"id\":" + IntegerToString(id) + ",\"stage\":\"ack\"}", ackBody);
   Print("[AITO] Nhận yêu cầu thống kê #", id, " -> xác nhận với server code=", ack);
   long magic = JsonGetInt(req, "magic");
   string sFrom = JsonGetString(req, "from"), sTo = JsonGetString(req, "to");
   datetime from = StringToTime(sFrom), to = StringToTime(sTo);
   if(StringLen(sTo) <= 10) to += 86399;          // chỉ có ngày -> hết ngày đó
   datetime now = TimeCurrent() + 3600;
   if(to > now || to <= 0) to = now;
   UiTicker("Đang gửi lịch sử magic " + IntegerToString(magic) + " từ " + sFrom + " cho thống kê");
   ulong t0 = GetTickCount64();

   // 1) số dư đầu kỳ = số dư hiện tại - mọi biến động tiền từ 'from' tới nay (mọi magic, cả nạp/rút)
   double change = 0;
   if(HistorySelect(from, TimeCurrent() + 3600))
     {
      int nAll = HistoryDealsTotal();
      for(int i = 0; i < nAll; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0) continue;
         change += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) +
                   HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_FEE);
        }
     }
   double balNow = AccountInfoDouble(ACCOUNT_BALANCE);

   // 2) vị thế thuộc magic: tìm các deal vào lệnh (lùi 60 ngày để bắt lệnh mở trước kỳ)
   long posIds[];
   ArrayResize(posIds, 0);
   datetime look = (from > 60 * 86400) ? (datetime)(from - 60 * 86400) : (datetime)0;
   if(HistorySelect(look, to))
     {
      int n = HistoryDealsTotal();
      for(int i = 0; i < n; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0) continue;
         long typ = HistoryDealGetInteger(d, DEAL_TYPE);
         if(typ != DEAL_TYPE_BUY && typ != DEAL_TYPE_SELL) continue;
         if(magic != 0 && HistoryDealGetInteger(d, DEAL_MAGIC) != magic) continue;
         long pid = HistoryDealGetInteger(d, DEAL_POSITION_ID);
         if(!PosIdInList(posIds, pid)) { int k = ArraySize(posIds); ArrayResize(posIds, k + 1); posIds[k] = pid; }
        }
     }

   // 3) các deal trong kỳ của những vị thế đó (kể cả deal đóng tay có magic 0)
   string arr = "";
   int cnt = 0, skipped = 0;
   if(HistorySelect(from, to))
     {
      int n = HistoryDealsTotal();
      int startIdx = 0;
      for(int i = startIdx; i < n; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0) continue;
         long typ = HistoryDealGetInteger(d, DEAL_TYPE);
         if(typ != DEAL_TYPE_BUY && typ != DEAL_TYPE_SELL) continue;
         long pid = HistoryDealGetInteger(d, DEAL_POSITION_ID);
         if(!PosIdInList(posIds, pid)) continue;
         if(cnt >= 5000) { skipped++; continue; }
         long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
         string sym = HistoryDealGetString(d, DEAL_SYMBOL);
         string dCmt = HistoryDealGetString(d, DEAL_COMMENT);
         long dRsn = HistoryDealGetInteger(d, DEAL_REASON);
         int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         if(cnt > 0) arr += ",";
         arr += "{\"ticket\":" + IntegerToString((long)d) +
                ",\"position\":" + IntegerToString(pid) +
                ",\"time\":" + IntegerToString((long)HistoryDealGetInteger(d, DEAL_TIME)) +
                ",\"type\":\"" + DealTypeTxt(typ) + "\"" +
                ",\"entry\":\"" + (entry == DEAL_ENTRY_IN ? "in" : "out") + "\"" +
                ",\"symbol\":\"" + JsonEscape(sym) + "\"" +
                ",\"volume\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_VOLUME), 2) +
                ",\"price\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_PRICE), dg) +
                ",\"profit\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_PROFIT), 2) +
                ",\"commission\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_COMMISSION), 2) +
                ",\"swap\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_SWAP), 2) +
                ",\"fee\":" + DoubleToString(HistoryDealGetDouble(d, DEAL_FEE), 2) +
                ",\"reason\":\"" + (entry == DEAL_ENTRY_IN ? "" : DealReasonTxt(dRsn, dCmt)) + "\"" +
                ",\"comment\":\"" + JsonEscape(dCmt) + "\"" +
                ",\"magic\":" + IntegerToString(HistoryDealGetInteger(d, DEAL_MAGIC)) + "}";
         cnt++;
        }
     }
   string js = "{\"id\":" + IntegerToString(id) + ",\"magic\":" + IntegerToString(magic) +
               ",\"from\":\"" + sFrom + "\",\"to\":\"" + sTo + "\"" +
               ",\"from_ts\":" + IntegerToString((long)from) + ",\"to_ts\":" + IntegerToString((long)to) +
               ",\"balance_now\":" + DoubleToString(balNow, 2) +
               ",\"balance_at_from\":" + DoubleToString(balNow - change, 2) +
               ",\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\"" +
               ",\"truncated\":" + (skipped > 0 ? "true" : "false") +
               ",\"deals\":[" + arr + "]}";
   string body;
   int code = HttpPostJson(ServerUrl + "/api/push_history", js, body, 30000);    // gói lớn: chờ tối đa 30s
   bool ok = (code == 200 && StringFind(body, "\"ok\": true") >= 0);
   Print("[AITO] Gửi lịch sử magic ", magic, " (", sFrom, " -> ", sTo, "): ", cnt, " deal, ",
         StringLen(js) / 1024, " KB, ", GetTickCount64() - t0, " ms, code=", code, " ", StringSubstr(body, 0, 160));
   if(ok)
     {
      g_lastHistReqId = id;
      UiTicker("Đã gửi " + IntegerToString(cnt) + " deal cho thống kê");
     }
   else
     {
      // báo lỗi về server bằng gói nhỏ để dashboard hiện đúng nguyên nhân; server sẽ gửi lại yêu cầu sau 25s
      string why = (code == -1 ? g_lastErrorText : "HTTP " + IntegerToString(code) + " " + StringSubstr(body, 0, 120));
      string eb;
      HttpPostJson(ServerUrl + "/api/push_history", "{\"id\":" + IntegerToString(id) + ",\"stage\":\"error\",\"error\":\"" +
                   JsonEscape(why) + "\",\"size_kb\":" + IntegerToString(StringLen(js) / 1024) + "}", eb);
      UiTicker("Gửi lịch sử lỗi: " + why);
     }
  }

void PushAccount()
  {
   string body;
   int code = HttpPostJson(ServerUrl + "/api/push_account", BuildAccountJson(), body);
   if(code != 200 && (g_frame % 50 == 0))
      Print("[AITO] Gửi thông tin tài khoản lỗi code=", code, " ", StringSubstr(body, 0, 120));
   if(code == 200)
     {
      string req = JsonGetRaw(body, "history_request");     // server chỉ gửi kèm khi bạn bấm xem thống kê
      if(StringLen(req) > 2 && req != "null") HandleHistoryRequest(req);
     }
  }

//+------------------------------------------------------------------+
//| KHOÁ MỘT BẢN EA DUY NHẤT                                          |
//+------------------------------------------------------------------+
// Trả về true nếu bản này là bản chính. Bản chính ghi nhịp tim mỗi giây;
// nếu nhịp tim cũ hơn 15s (bản chính bị gỡ / terminal treo) thì bản khác tiếp quản.
bool UpdateMasterLock()
  {
   ulong nowMs = GetTickCount64();
   if(nowMs - g_lockMs < 1000) return g_isMaster;
   g_lockMs = nowMs;
   if(!GlobalVariableCheck(LOCK_OWNER)) GlobalVariableSet(LOCK_OWNER, 0);
   double owner = GlobalVariableGet(LOCK_OWNER);
   double beat  = GlobalVariableCheck(LOCK_BEAT) ? GlobalVariableGet(LOCK_BEAT) : 0;
   bool was = g_isMaster;
   if(owner == g_token)
      g_isMaster = true;
   else if(owner == 0 || (double)TimeLocal() - beat > 15)
      g_isMaster = GlobalVariableSetOnCondition(LOCK_OWNER, g_token, owner);   // nguyên tử: chỉ 1 bản thắng
   else
      g_isMaster = false;
   if(g_isMaster) GlobalVariableSet(LOCK_BEAT, (double)TimeLocal());
   if(g_isMaster != was)
     {
      UiDeleteAll();
      Print(g_isMaster ? "[AITO] Bản EA này là BẢN CHÍNH (đẩy giá + khớp lệnh)."
                       : "[AITO] Đã có AITradingOffice chạy ở chart khác -> bản này chuyển STANDBY, không làm gì.");
     }
   return g_isMaster;
  }

void UiDrawStandby()
  {
   int W = 480;
   UiRect("sb_bg", 0, 0, W, 112, CLR_BG, CLR_AMBER);
   UiRect("sb_ac", 0, 0, W, 3, CLR_AMBER);
   UiText("sb_t", 16, 12, "AI TRADING OFFICE", CLR_TEXT, 13, "Segoe UI Black");
   UiRect("sb_bd", W - 128, 12, 112, 26, CLR_AMBER);
   UiText("sb_bt", W - 72, 25, "STANDBY", CLR_BG, 11, "Segoe UI Black", ANCHOR_CENTER);
   UiText("sb_l1", 16, 50, "EA đang chạy ở một chart khác trên terminal này.", CLR_TEXT, 10, "Segoe UI Semibold");
   UiText("sb_l2", 16, 70, "Bản này không đẩy giá, không đặt lệnh để tránh lệnh trùng.", CLR_MUTED, 9);
   UiText("sb_l3", 16, 88, "Hãy gỡ EA khỏi chart này (chỉ cần 1 chart).", CLR_AMBER, 9);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| EVENTS                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_gvLastId = "AITO_LastId_" + IntegerToString(MagicNumber);
   if(GlobalVariableCheck(g_gvLastId)) g_lastId = (long)GlobalVariableGet(g_gvLastId);
   else GlobalVariableSet(g_gvLastId, 0.0);
   g_trade.SetExpertMagicNumber((ulong)MagicNumber);
   g_trade.SetDeviationInPoints((ulong)SlippagePoints);
   g_trade.SetAsyncMode(false);

   if(RunJsonSelfTest && !JsonSelfTest())
     {
      Print("[AITO] Parser JSON lỗi -> dừng EA.");
      return INIT_FAILED;
     }
   if(StringLen(ServerUrl) > 0 && StringGetCharacter(ServerUrl, StringLen(ServerUrl) - 1) == '/')
     {
      Print("[AITO] ServerUrl không được có dấu / ở cuối.");
      return INIT_PARAMETERS_INCORRECT;
     }
   Print("[AITO] Khởi động. server=", ServerUrl, " | mọi cấu hình khác tải từ ", ServerUrl, "/api/ea/config");
   Comment("");
   MathSrand((uint)(GetTickCount() ^ (uint)ChartID()));
   g_token = 1 + MathRand() * 32768.0 + MathRand() + (double)(GetTickCount() % 1000) * 1073741824.0;
   if(!UpdateMasterLock())
     {
      EventSetMillisecondTimer(UI_FRAME_MS);
      UiDrawStandby();
      return INIT_SUCCEEDED;      // bản phụ: chỉ hiện STANDBY, không kết nối server
     }
   g_cfgTryMs = GetTickCount64();
   if(!FetchServerConfig(true))
     {
      Print("[AITO] Chưa kết nối được server. Kiểm tra Allow WebRequest và URL. Sẽ thử lại mỗi 10s.");
      UiTicker("Chưa kết nối được server, kiểm tra Allow WebRequest và ServerUrl");
     }
   g_lastPoll = 0;
   EventSetMillisecondTimer(UI_FRAME_MS);   // nhịp chung cho animation, đẩy giá và hỏi kèo
   UiDraw();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(GlobalVariableCheck(LOCK_OWNER) && GlobalVariableGet(LOCK_OWNER) == g_token)
      GlobalVariableSet(LOCK_OWNER, 0);   // nhả khoá cho bản khác tiếp quản ngay
   UiDeleteAll();
   Comment("");
   Print("[AITO] Dừng EA, lastId=", g_lastId, " reason=", reason);
  }

void OnTimer()
  {
   if(!UpdateMasterLock()) { UiDrawStandby(); return; }
   ulong nowMs = GetTickCount64();
   // tải cấu hình: chưa kết nối thì thử lại mỗi 10s, đã kết nối thì mỗi ConfigRefreshSec
   if(!g_cfgLoaded)
     {
      if(nowMs - g_cfgTryMs >= 10000) { g_cfgTryMs = nowMs; FetchServerConfig(true); }
     }
   else if(TimeLocal() - g_lastCfgFetch >= ConfigRefreshSec)
      FetchServerConfig(false);

   if(g_cfgLoaded)
     {
      if(EnablePriceBridge && nowMs - g_lastTickMs >= (ulong)TickIntervalMs)
        {
         g_lastTickMs = nowMs;
         RunPriceBridge();
        }
      if(nowMs - g_lastAccountMs >= 2000)
        {
         g_lastAccountMs = nowMs;
         PushAccount();
        }
      if(TimeLocal() - g_lastPoll >= PollSeconds)
        {
         g_lastPoll = TimeLocal();
         ManageBreakEven();
         PollSignals();
        }
     }

   if(g_showPanel)
      UiDraw();
   else
      Comment(StringFormat("AI Trading Office → %s\n%s\nKhớp lệnh: %s | lastId=%I64d\nCấu hình server (%s): %s",
              ServerUrl, (EnablePriceBridge ? g_bridgeStatus : "Bridge: TẮT"),
              (DryRun ? "DryRun (chỉ log)" : (EnableTrading ? "BẬT" : "TẮT")), g_lastId,
              TimeToString(g_lastCfgFetch, TIME_MINUTES), g_cfgSummary));
  }

void OnTick()
  {
   // không dùng tick; mọi việc chạy theo timer
  }
//+------------------------------------------------------------------+
