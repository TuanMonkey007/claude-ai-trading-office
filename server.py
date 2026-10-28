#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Văn Phòng AI Trading & Đầu Tư 2D (Multi-Agent Virtual Office)
Backend: 100% Python Standard Library (http.server, urllib, sqlite3, json, threading, math, ssl)
Chạy: python3 server.py  -> http://localhost:8080
"""
import os
import sys
import json
import math
import re
import zlib
import struct
import base64
import hmac
import ssl
import time
import sqlite3
import threading
import traceback
import urllib.request
import urllib.parse
import urllib.error
import hashlib
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer          # Python >= 3.7
except ImportError:                                      # CentOS 7 (Python 3.6)
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    """Đọc .env cạnh server.py (KEY=VALUE) để NSSM/Windows cũng có OFFICE_ADMIN_PASSWORD.
    Bỏ dòng trống/comment, bỏ tiền tố 'export ', bỏ nháy bao quanh; KHÔNG ghi đè biến môi trường đã có."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except Exception:
        return 0
    n = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if not key or not all(ch.isalnum() or ch == "_" for ch in key):
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key not in os.environ:
            os.environ[key] = val
            n += 1
    return n


load_dotenv(os.path.join(BASE_DIR, ".env"))
DATA_DIR = os.path.join(BASE_DIR, "data")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(DATA_DIR, "office.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
HOST = os.environ.get("OFFICE_HOST", "0.0.0.0")
# Mật khẩu dashboard (HTTP Basic Auth, user "admin"). Để trống = không khoá (chỉ nên dùng trong LAN).
ADMIN_USER = os.environ.get("OFFICE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("OFFICE_ADMIN_PASSWORD", "")
# Các endpoint EA được gọi bằng X-Bridge-Token thay cho mật khẩu dashboard
EA_PATHS = ("/api/push_price", "/api/push_account", "/api/push_history", "/api/ea/config", "/api/signals", "/api/execution", "/api/health")
PORT = int(os.environ.get("OFFICE_PORT", "8080"))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SKILLS_DIR, exist_ok=True)

# SSL context: dùng CA hệ thống, fallback unverified cho CentOS 7 cũ thiếu CA bundle
try:
    SSL_CTX = ssl.create_default_context()
except Exception:
    SSL_CTX = ssl._create_unverified_context()
if os.environ.get("OFFICE_INSECURE_SSL") == "1":
    SSL_CTX = ssl._create_unverified_context()

# ============================================================================
# 0. CẤU HÌNH
# ============================================================================
DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model": "gemini-3.6-flash",       # (cũ) chỉ dùng khi gemini_models trống
    "gemini_strategy": "priority",            # priority: ưu tiên model tốt trước | round_robin: rải đều
    "gemini_max_attempts": 5,                 # số model thử tối đa trong 1 phiên họp
    "gemini_models": [],                      # danh sách model xoay vòng (tự tạo mặc định nếu trống)
    "groq_api_key": "",
    "groq_model": "openai/gpt-oss-120b",
    "openrouter_api_key": "",
    "openrouter_model": "deepseek/deepseek-chat:free",
    "custom_api_url": "",
    "custom_api_key": "",
    "custom_model": "llama3",
    "telegram_bot_token": "",
    "cryptocompare_api_key": "",
    "bridge_token": "",
    "ea_poll_seconds": 15, "ea_web_timeout_ms": 8000, "ea_report_executions": True,
    "ea_enable_price_bridge": True, "ea_tick_interval_ms": 1000, "ea_candle_interval_sec": 15, "ea_bridge_bars": 300,
    "ea_min_confidence": 80, "ea_max_signal_age_sec": 300, "ea_gold_symbol": "XAUUSDm", "ea_btc_symbol": "BTCUSDm",
    "ea_max_open_per_symbol": 1, "ea_use_server_lot": False, "ea_risk_percent": 1.0, "ea_split_tp": True,
    "ea_breakeven_buffer_pts": 0, "ea_max_daily_loss_pct": 3.0, "ea_dry_run": True, "ea_enable_trading": False,
    "ea_magic": 20261023, "ea_slippage_points": 30, "ea_show_panel": True, "ea_panel_scale": 1.0,
    "bridge_stale_sec": 90,
    "use_mt5_balance": True,                  # tính lot theo số dư thật của tài khoản MT5 (nếu EA đang gửi)
    "price_source": "mt5_only",               # mt5_only: chỉ giá MT5 | auto: MT5 -> Binance -> Yahoo
    "btc_binance_fallback": False,            # mt5_only + BTCUSDT: cho phép dự phòng Binance khi MT5 chưa có BTC (mặc định TẮT)
    "telegram_chat_id": "",
    "telegram_min_confidence": 75,
    "telegram_send_wait": False,
    "telegram_send_photo": True,              # gửi kèm ảnh chụp biểu đồ kèo và lý do vào lệnh qua Telegram
    "telegram_alert_sl_tp": True,             # tự động bắn thông báo + ảnh biểu đồ sang Telegram khi lệnh dính SL / chạm TP
    "telegram_listen": True,
    "telegram_news_chats": "",
    "account_balance": 10000.0,
    "risk_per_trade_pct": 1.0,
    "timeframe": "15m",
    "auto_pilot": False,
    "auto_interval_min": 30,
    "quant_consensus": 0.4,                   # ngưỡng đồng thuận = |điểm có trọng số| / tổng trọng số
    "agent_auto_weight": True,                # tự động điều chỉnh trọng số agent theo tỷ lệ thắng/thua SL/TP thực tế (từ 5 phiếu)
    "llm_provider_order": ["gemini", "groq", "openrouter", "custom"],  # thứ tự gọi nhà cung cấp LLM khi ra quyết định (kéo thả trong Cài đặt)
}
SECRET_KEYS = ["gemini_api_key", "groq_api_key", "openrouter_api_key",
               "custom_api_key", "telegram_bot_token", "cryptocompare_api_key", "bridge_token"]
# Nhà cung cấp LLM có thể chọn thứ tự ưu tiên; Built-in Quant AI luôn là chốt chặn cuối cùng.
LLM_PROVIDERS = ("gemini", "groq", "openrouter", "custom")
CONFIG_LOCK = threading.Lock()


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        save_config(cfg)
    return cfg


def save_config(cfg):
    with CONFIG_LOCK:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


CONFIG = load_config()


def masked_config():
    out = dict(CONFIG)
    for k in SECRET_KEYS:
        v = out.get(k, "")
        out[k] = ("•" * 8 + v[-4:]) if v else ""
        out[k + "_set"] = bool(v)
    return out


# ============================================================================
# 1. DATABASE SQLITE
# ============================================================================
DB_LOCK = threading.Lock()
_LOG_INSERT_COUNT = 0


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    with DB_LOCK:
        conn = db_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            asset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT,
            action TEXT NOT NULL,
            confidence INTEGER,
            entry REAL, stop_loss REAL, take_profit_1 REAL, take_profit_2 REAL,
            rr1 REAL, rr2 REAL, lot_size REAL, risk_amount REAL,
            summary TEXT, bull_argument TEXT, bear_argument TEXT,
            lesson_learned TEXT, risk_note TEXT,
            llm_provider TEXT, indicators_json TEXT, votes_json TEXT,
            telegram_sent INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS account_history (
            ts INTEGER NOT NULL, login INTEGER, balance REAL, equity REAL, margin REAL
        );
        CREATE INDEX IF NOT EXISTS idx_acc_ts ON account_history (ts);
        CREATE TABLE IF NOT EXISTS llm_usage (
            day TEXT NOT NULL, model TEXT NOT NULL, ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0,
            last_status TEXT, last_error TEXT, cooldown_until REAL DEFAULT 0, last_used TEXT,
            PRIMARY KEY (day, model)
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, agent TEXT, room TEXT, message TEXT
        );
        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            signal_id INTEGER,
            ticket INTEGER,
            symbol TEXT, action TEXT,
            volume REAL, price REAL, sl REAL, tp REAL,
            retcode INTEGER, error TEXT,
            dry_run INTEGER DEFAULT 0,
            magic INTEGER, account INTEGER, comment TEXT,
            terminal_time TEXT, raw_json TEXT,
            status TEXT DEFAULT 'open',
            close_price REAL DEFAULT 0,
            close_time TEXT DEFAULT '',
            profit REAL DEFAULT 0,
            exit_reason TEXT DEFAULT '',
            deal_ticket INTEGER DEFAULT 0,
            telegram_alerted INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_exec_sig ON executions (signal_id);
        CREATE INDEX IF NOT EXISTS idx_exec_ticket ON executions (ticket);
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            signal_id INTEGER PRIMARY KEY,
            outcome TEXT NOT NULL,
            source TEXT, detail TEXT, evaluated_at TEXT,
            exit_reason TEXT DEFAULT '',
            close_price REAL DEFAULT 0,
            close_time TEXT DEFAULT '',
            net_profit REAL DEFAULT 0,
            lesson_logged INTEGER DEFAULT 0,
            telegram_alerted INTEGER DEFAULT 0
        );
        """)
        # Tự động nâng cấp bảng cũ nếu CSDL đã tạo từ phiên bản trước
        for sql in (
            "ALTER TABLE executions ADD COLUMN status TEXT DEFAULT 'open'",
            "ALTER TABLE executions ADD COLUMN close_price REAL DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN close_time TEXT DEFAULT ''",
            "ALTER TABLE executions ADD COLUMN profit REAL DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN exit_reason TEXT DEFAULT ''",
            "ALTER TABLE executions ADD COLUMN deal_ticket INTEGER DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN telegram_alerted INTEGER DEFAULT 0",
            "ALTER TABLE signal_outcomes ADD COLUMN exit_reason TEXT DEFAULT ''",
            "ALTER TABLE signal_outcomes ADD COLUMN close_price REAL DEFAULT 0",
            "ALTER TABLE signal_outcomes ADD COLUMN close_time TEXT DEFAULT ''",
            "ALTER TABLE signal_outcomes ADD COLUMN net_profit REAL DEFAULT 0",
            "ALTER TABLE signal_outcomes ADD COLUMN lesson_logged INTEGER DEFAULT 0",
            "ALTER TABLE signal_outcomes ADD COLUMN telegram_alerted INTEGER DEFAULT 0",
        ):
            try:
                conn.execute(sql)
            except Exception:
                pass
        conn.commit()
        conn.close()


def db_insert_signal(sig):
    with DB_LOCK:
        conn = db_conn()
        cur = conn.execute("""INSERT INTO signals
            (created_at, asset, symbol, timeframe, action, confidence, entry, stop_loss,
             take_profit_1, take_profit_2, rr1, rr2, lot_size, risk_amount, summary,
             bull_argument, bear_argument, lesson_learned, risk_note, llm_provider,
             indicators_json, votes_json, telegram_sent)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            sig["created_at"], sig["asset"], sig["symbol"], sig["timeframe"], sig["action"],
            sig["confidence"], sig["entry"], sig["stop_loss"], sig["take_profit_1"],
            sig["take_profit_2"], sig["rr1"], sig["rr2"], sig["lot_size"], sig["risk_amount"],
            sig["summary"], sig["bull_argument"], sig["bear_argument"], sig["lesson_learned"],
            sig["risk_note"], sig["llm_provider"], json.dumps(sig["indicators"], ensure_ascii=False),
            json.dumps(sig["votes"], ensure_ascii=False), 1 if sig.get("telegram_sent") else 0))
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid


def db_get_signal(signal_id):
    with DB_LOCK:
        conn = db_conn()
        r = conn.execute("SELECT * FROM signals WHERE id=?", (int(signal_id),)).fetchone()
        conn.close()
    if not r:
        return None
    d = dict(r)
    try:
        d["indicators"] = json.loads(d.pop("indicators_json") or "{}")
        d["votes"] = json.loads(d.pop("votes_json") or "{}")
    except Exception:
        d["indicators"], d["votes"] = {}, {}
    return d


def db_list_signals(limit=30):
    with DB_LOCK:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        sids = [r["id"] for r in rows]
        exec_map = {}
        oc_map = {}
        if sids:
            ph = ",".join("?" for _ in sids)
            for er in conn.execute("SELECT * FROM executions WHERE signal_id IN (%s) ORDER BY id ASC" % ph, sids).fetchall():
                ed = dict(er)
                ed.pop("raw_json", None)
                exec_map.setdefault(ed["signal_id"], []).append(ed)
            for ocr in conn.execute("SELECT * FROM signal_outcomes WHERE signal_id IN (%s)" % ph, sids).fetchall():
                oc_map[ocr["signal_id"]] = dict(ocr)
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["indicators"] = json.loads(d.pop("indicators_json") or "{}")
            d["votes"] = json.loads(d.pop("votes_json") or "{}")
        except Exception:
            d["indicators"], d["votes"] = {}, {}
        exs = exec_map.get(d["id"], [])
        d["executions"] = exs
        oc = oc_map.get(d["id"])
        # Nếu chưa có outcome lưu DB nhưng kèo là BUY/SELL, dò nến nhanh để hiển thị trạng thái chạm SL/TP
        if not oc and d.get("action") in ("BUY", "SELL"):
            try:
                oc = evaluate_signal_sl_tp(d, exs)
            except Exception:
                oc = None
        d["outcome_info"] = oc
        out.append(d)
    return out


def db_insert_log(ts, agent, room, message):
    global _LOG_INSERT_COUNT
    try:
        with DB_LOCK:
            conn = db_conn()
            conn.execute("INSERT INTO logs (ts, agent, room, message) VALUES (?,?,?,?)",
                         (ts, agent, room, message))
            _LOG_INSERT_COUNT += 1
            if _LOG_INSERT_COUNT % 100 == 0:
                conn.execute("DELETE FROM logs WHERE id < (SELECT MAX(id) FROM logs) - 5000")
            conn.commit()
            conn.close()
    except Exception:
        pass


def _num(v, cast=float, default=None):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def db_insert_execution(body):
    """Lưu kết quả đặt lệnh do EA (mt5/AITradingOffice.mq5) gửi về POST /api/execution."""
    dry = 1 if body.get("dry_run") in (True, 1, "1", "true") else 0
    ticket = _num(body.get("ticket"), int, 0)
    err = str(body.get("error") or "")[:500]
    if dry or err == "dry_run":
        st = "dry_run"
    elif ticket > 0 and not err:
        st = "open"
    elif err.startswith("skipped"):
        st = "skipped"
    else:
        st = "error"
    row = {
        "created_at": now_iso(),
        "signal_id": _num(body.get("signal_id"), int, 0),
        "ticket": ticket,
        "symbol": str(body.get("symbol") or "")[:32],
        "action": str(body.get("action") or "")[:8].upper(),
        "volume": _num(body.get("volume"), float, 0.0),
        "price": _num(body.get("price"), float, 0.0),
        "sl": _num(body.get("sl"), float, 0.0),
        "tp": _num(body.get("tp"), float, 0.0),
        "retcode": _num(body.get("retcode"), int, 0),
        "error": err,
        "dry_run": dry,
        "magic": _num(body.get("magic"), int, 0),
        "account": _num(body.get("account"), int, 0),
        "comment": str(body.get("comment") or "")[:64],
        "terminal_time": str(body.get("terminal_time") or "")[:32],
        "raw_json": json.dumps(body, ensure_ascii=False)[:4000],
        "status": st,
        "close_price": _num(body.get("close_price"), float, 0.0),
        "close_time": str(body.get("close_time") or "")[:32],
        "profit": _num(body.get("profit"), float, 0.0),
        "exit_reason": str(body.get("exit_reason") or "")[:24],
        "deal_ticket": _num(body.get("deal_ticket"), int, 0),
    }
    with DB_LOCK:
        conn = db_conn()
        cur = conn.execute("""INSERT INTO executions
            (created_at, signal_id, ticket, symbol, action, volume, price, sl, tp, retcode, error,
             dry_run, magic, account, comment, terminal_time, raw_json, status, close_price, close_time,
             profit, exit_reason, deal_ticket)
            VALUES (:created_at, :signal_id, :ticket, :symbol, :action, :volume, :price, :sl, :tp,
                    :retcode, :error, :dry_run, :magic, :account, :comment, :terminal_time, :raw_json,
                    :status, :close_price, :close_time, :profit, :exit_reason, :deal_ticket)""", row)
        conn.commit()
        row["id"] = cur.lastrowid
        conn.close()
    return row


def db_list_executions(limit=50, signal_id=None, only_entered=False):
    with DB_LOCK:
        conn = db_conn()
        if signal_id:
            rows = conn.execute("SELECT * FROM executions WHERE signal_id=? ORDER BY id DESC LIMIT ?",
                                (signal_id, limit)).fetchall()
        elif only_entered:
            rows = conn.execute(
                "SELECT * FROM executions WHERE (ticket > 0 OR dry_run = 1) AND status NOT IN ('skipped','error') ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("raw_json", None)
        out.append(d)
    return out


# ============================================================================
# 2. TRẠNG THÁI VĂN PHÒNG (dùng cho Canvas 2D)
# ============================================================================
AGENTS = {
    "vwap_hunter":     {"name": "Bé Tím VWAP",        "home": "ta_room",      "emoji": "🟣"},
    "smc_sniper":      {"name": "Bé Hồng SMC",        "home": "ta_room",      "emoji": "🩷"},
    "trend_radar":     {"name": "Bé Xanh Trend",      "home": "ta_room",      "emoji": "🟢"},
    "chief_strategist": {"name": "Trưởng Nhóm Cam",   "home": "ta_room",      "emoji": "🟠"},
    "risk_guard":      {"name": "Robot Quản Trị Vốn", "home": "risk_room",    "emoji": "🤖"},
    "hermes_scribe":   {"name": "Sách Đỏ Hermes",     "home": "library_room", "emoji": "📕"},
    "macro_owl":       {"name": "Cú Mèo Vĩ Mô",       "home": "news_room",    "emoji": "🦉"},
    "vault_piggy":     {"name": "Heo Vàng Thủ Quỹ",   "home": "vault_room",   "emoji": "🐷"},
    "htf_scout":       {"name": "Ưng Khung Lớn",      "home": "ta_room",      "emoji": "🦅"},
    "regime_meter":    {"name": "Mèo Đo Nhịp",        "home": "ta_room",      "emoji": "🐱"},
    "level_mapper":    {"name": "Cáo Mốc Giá",        "home": "ta_room",      "emoji": "🦊"},
    "volume_whale":    {"name": "Cá Voi Volume",      "home": "ta_room",      "emoji": "🐳"},
}
# Các agent bỏ phiếu ở Bước 2 (thứ tự hiển thị) và nhãn ngắn
VOTERS = ("vwap_hunter", "smc_sniper", "trend_radar", "htf_scout", "regime_meter", "level_mapper", "volume_whale")
VOTE_LABELS = {"vwap_hunter": "VWAP", "smc_sniper": "SMC", "trend_radar": "Trend",
               "htf_scout": "Khung lớn", "regime_meter": "Nhịp", "level_mapper": "Mốc giá", "volume_whale": "Volume"}
ROOMS = ["ta_room", "risk_room", "library_room", "news_room", "meeting_room", "party_room", "vault_room"]

STATE_LOCK = threading.Lock()
STATE = {
    "workflow_step": 0,
    "workflow_label": "Sẵn sàng",
    "running": False,
    "current_asset": None,
    "auto_pilot": bool(CONFIG.get("auto_pilot")),
    "next_auto_run": None,
    "agents": {aid: {"id": aid, "name": a["name"], "room": a["home"], "status": "idle",
                     "bubble": "", "tasks": 0} for aid, a in AGENTS.items()},
    "room_tasks": {r: 0 for r in ROOMS},
    "markets": {},
    "news": [],
    "last_signal": None,
    "last_error": "",
    "server_started": datetime.now(timezone.utc).isoformat(),
}
LOGS = deque(maxlen=300)


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(agent, message, room=None):
    ts = now_iso()
    room = room or (STATE["agents"].get(agent, {}).get("room") if agent in STATE["agents"] else "office")
    entry = {"ts": ts, "agent": agent, "name": AGENTS.get(agent, {}).get("name", agent),
             "room": room, "message": message}
    LOGS.append(entry)
    db_insert_log(ts, agent, room, message)
    print("[%s] %-18s %s" % (ts, agent, message), flush=True)


def set_agent(aid, room=None, status=None, bubble=None, tasks=None):
    with STATE_LOCK:
        a = STATE["agents"][aid]
        if room is not None:
            a["room"] = room
        if status is not None:
            a["status"] = status
        if bubble is not None:
            a["bubble"] = bubble
        if tasks is not None:
            a["tasks"] = tasks
        # cập nhật huy hiệu phòng
        rt = {r: 0 for r in ROOMS}
        for ag in STATE["agents"].values():
            if ag["status"] != "idle":
                rt[ag["room"]] = rt.get(ag["room"], 0) + max(1, ag["tasks"])
        STATE["room_tasks"] = rt


def set_step(step, label):
    with STATE_LOCK:
        STATE["workflow_step"] = step
        STATE["workflow_label"] = label


def move_all(room, status="walking", bubble=""):
    for aid in AGENTS:
        set_agent(aid, room=room, status=status, bubble=bubble)


def send_home(status="idle"):
    for aid, a in AGENTS.items():
        set_agent(aid, room=a["home"], status=status, bubble="", tasks=0)


# ============================================================================
# 3. NGUỒN DỮ LIỆU THỊ TRƯỜNG (Binance -> Yahoo fallback), tin tức
# ============================================================================
ASSETS = {
    "XAUUSD": {"label": "Vàng XAU/USD", "binance": "PAXGUSDT", "yahoo": "GC=F", "unit": "oz",
               "contract": 100.0, "pip": 0.01, "decimals": 2},
    "BTCUSDT": {"label": "Bitcoin BTC/USDT", "binance": "BTCUSDT", "yahoo": "BTC-USD", "unit": "BTC",
                "contract": 1.0, "pip": 0.1, "decimals": 1},
}
TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
YAHOO_RANGE = {"5m": "5d", "15m": "5d", "1h": "1mo", "4h": "3mo"}
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AITradingOffice/1.0"


def http_get_json(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=dict({"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url, payload, headers=None, timeout=60):
    body = json.dumps(payload).encode("utf-8")
    h = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_form_file(url, fields, field_name, filename, raw_bytes, mime="image/png", timeout=25):
    boundary = "----AITOBoundary%d" % int(time.time() * 1000)
    chunks = []
    for k, v in (fields or {}).items():
        if v is None:
            continue
        chunks.append(("--" + boundary + "\r\n").encode("utf-8"))
        chunks.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode("utf-8"))
        chunks.append(str(v).encode("utf-8") + b"\r\n")
    chunks.append(("--" + boundary + "\r\n").encode("utf-8"))
    chunks.append(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (field_name, filename)).encode("utf-8"))
    chunks.append(("Content-Type: %s\r\n\r\n" % mime).encode("utf-8"))
    chunks.append(raw_bytes + b"\r\n")
    chunks.append(("--" + boundary + "--\r\n").encode("utf-8"))
    body = b"".join(chunks)
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "multipart/form-data; boundary=" + boundary,
        "Content-Length": str(len(body)),
    }, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


_BINANCE_HOSTS = ["https://api.binance.com", "https://api1.binance.com", "https://data-api.binance.vision"]
_BINANCE_FAST_HOST = {"host": None}


def fetch_binance(asset, tf, limit=300):
    sym = ASSETS[asset]["binance"]
    hosts = list(_BINANCE_HOSTS)
    fast = _BINANCE_FAST_HOST.get("host")
    if fast in hosts:
        hosts.remove(fast)
        hosts.insert(0, fast)
    last_err = None
    for host in hosts:
        try:
            res_box = {"kl": None, "tk": None, "err": None}

            def _get_kl(h=host):
                try:
                    res_box["kl"] = http_get_json("%s/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (h, sym, tf, limit), timeout=8)
                except Exception as ex:
                    res_box["err"] = ex

            def _get_tk(h=host):
                try:
                    res_box["tk"] = http_get_json("%s/api/v3/ticker/24hr?symbol=%s" % (h, sym), timeout=6)
                except Exception:
                    res_box["tk"] = None

            t1 = threading.Thread(target=_get_kl, daemon=True)
            t2 = threading.Thread(target=_get_tk, daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=9)
            t2.join(timeout=7)
            if res_box["err"] or not res_box["kl"]:
                raise res_box["err"] or RuntimeError("empty klines")
            kl = res_box["kl"]
            candles = [{"t": int(k[0]) // 1000, "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                        "c": float(k[4]), "v": float(k[5])} for k in kl]
            tk = res_box["tk"]
            if tk and "lastPrice" in tk:
                ticker = {"price": float(tk["lastPrice"]), "change_pct": float(tk["priceChangePercent"]),
                          "high24": float(tk["highPrice"]), "low24": float(tk["lowPrice"]),
                          "volume24": float(tk["volume"])}
            else:
                day_ago = candles[-1]["t"] - 86400
                day = [c for c in candles if c["t"] >= day_ago] or candles[-24:]
                base = day[0]["o"]
                ticker = {"price": candles[-1]["c"],
                          "change_pct": (candles[-1]["c"] - base) / base * 100.0 if base else 0.0,
                          "high24": max(c["h"] for c in day), "low24": min(c["l"] for c in day),
                          "volume24": sum(c["v"] for c in day)}
            _BINANCE_FAST_HOST["host"] = host
            return candles, ticker, "binance:" + sym
        except Exception as e:
            last_err = e
    raise RuntimeError("Binance fail: %s" % last_err)


def fetch_yahoo(asset, tf):
    sym = ASSETS[asset]["yahoo"]
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s" % (
        urllib.parse.quote(sym), tf, YAHOO_RANGE.get(tf, "5d"))
    data = http_get_json(url)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    candles = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or q["open"][i] is None:
            continue
        candles.append({"t": int(t), "o": float(q["open"][i]), "h": float(q["high"][i]),
                        "l": float(q["low"][i]), "c": float(q["close"][i]),
                        "v": float(q["volume"][i] or 0)})
    meta = res.get("meta", {})
    price = float(meta.get("regularMarketPrice") or candles[-1]["c"])
    prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or candles[0]["c"])
    # Tính 24h từ nến
    day_ago = candles[-1]["t"] - 86400
    base = next((c["c"] for c in candles if c["t"] >= day_ago), prev)
    last24 = [c for c in candles if c["t"] >= day_ago] or candles[-20:]
    ticker = {"price": price, "change_pct": (price - base) / base * 100 if base else 0.0,
              "high24": max(c["h"] for c in last24), "low24": min(c["l"] for c in last24),
              "volume24": sum(c["v"] for c in last24)}
    return candles[-300:], ticker, "yahoo:" + sym


# ---- Nguồn MT5 (đẩy từ mt5_bridge.py hoặc EA AITradingOffice.mq5) ----
MT5_FEED = {}          # {(asset, tf): {"ts": epoch, "candles": [...], "symbol": "XAUUSD"}}
MT5_TICK = {}          # {asset: {"ts": epoch, "bid":..., "ask":..., "last":..., "spread":..., "change_pct":..., "high24":..., "low24":..., "symbol":...}}
MT5_LOCK = threading.Lock()
SPREAD_HIST = {}       # {asset: deque[spread]} lấy mẫu ≥ 5s/lần, giữ ~1 giờ để tính median
SPREAD_LAST = {}
MT5_CACHE_FILE = os.path.join(DATA_DIR, "mt5_feed_cache.json")
_MT5_SAVE_TS = {"t": 0.0}


def load_mt5_cache():
    """Khôi phục nến MT5 từ đĩa khi vừa khởi động lại server.py để không phải chờ chu kỳ 5 phút gửi full nến của EA."""
    if not os.path.exists(MT5_CACHE_FILE):
        return
    try:
        with open(MT5_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        now = time.time()
        with MT5_LOCK:
            for k, v in (raw.get("ticks") or {}).items():
                if k in ASSETS and isinstance(v, dict) and now - float(v.get("ts") or 0) < 3600:
                    MT5_TICK[k] = v
            for k_str, v in (raw.get("feeds") or {}).items():
                if ":" not in k_str or not isinstance(v, dict):
                    continue
                asset, tf = k_str.split(":", 1)
                if asset in ASSETS and tf in TF_SECONDS and len(v.get("candles") or []) >= 30:
                    MT5_FEED[(asset, tf)] = v
    except Exception as e:
        print("load_mt5_cache:", e)


def _save_mt5_cache_throttled(force=False):
    now = time.time()
    if not force and now - _MT5_SAVE_TS["t"] < 20.0:
        return
    _MT5_SAVE_TS["t"] = now
    try:
        with MT5_LOCK:
            payload = {
                "ticks": dict(MT5_TICK),
                "feeds": {"%s:%s" % (a, tf): v for (a, tf), v in MT5_FEED.items()},
            }
        tmp = MT5_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, MT5_CACHE_FILE)
    except Exception:
        pass


def mt5_push(payload):
    """Nhận dữ liệu từ bridge: {"asset","symbol","tick":{bid,ask,last,change_pct,high24,low24,volume24},"tf","candles":[{t,o,h,l,c,v}]}"""
    asset = str(payload.get("asset", "")).upper()
    if asset not in ASSETS:
        raise ValueError("asset phải là XAUUSD hoặc BTCUSDT")
    now = time.time()
    sym = str(payload.get("symbol") or asset)
    tf = payload.get("tf")
    candles = payload.get("candles") or []
    need_full = False
    with MT5_LOCK:
        tick = payload.get("tick")
        if tick and tick.get("bid") is not None:
            bid, ask = float(tick["bid"]), float(tick.get("ask") or tick["bid"])
            MT5_TICK[asset] = {"ts": now, "symbol": sym, "bid": bid, "ask": ask,
                               "last": float(tick.get("last") or (bid + ask) / 2.0), "spread": round(ask - bid, 5),
                               "change_pct": float(tick.get("change_pct") or 0.0),
                               "high24": float(tick.get("high24") or bid), "low24": float(tick.get("low24") or bid),
                               "volume24": float(tick.get("volume24") or 0.0)}
            if now - SPREAD_LAST.get(asset, 0) >= 5:
                SPREAD_LAST[asset] = now
                SPREAD_HIST.setdefault(asset, deque(maxlen=720)).append(MT5_TICK[asset]["spread"])
        if tf in TF_SECONDS and candles:
            clean = []
            for c in candles:
                clean.append({"t": int(c["t"]), "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]),
                              "c": float(c["c"]), "v": float(c.get("v") or 0.0)})
            old = MT5_FEED.get((asset, tf))
            if len(clean) >= 30 or not old:
                merged = {c["t"]: c for c in clean}                       # gói đầy đủ
            else:
                merged = {c["t"]: c for c in old["candles"]}              # gói vài nến cuối -> gộp vào
                merged.update({c["t"]: c for c in clean})
            rows = sorted(merged.values(), key=lambda x: x["t"])[-400:]
            if len(rows) >= 30:
                MT5_FEED[(asset, tf)] = {"ts": now, "candles": rows, "symbol": sym}
            else:
                # Server vừa restart nên chưa có đủ 30 nến mà EA chỉ gửi gói 3 nến -> báo need_full để EA gửi ngay 300 nến
                need_full = True
    if tf in TF_SECONDS and candles and not need_full:
        _save_mt5_cache_throttled(force=(len(candles) >= 30))
    # Cập nhật tức thì giá bid/ask/spread trên STATE["markets"] mà không cần tính lại toàn bộ 400 nến mỗi tick
    if tick and tick.get("bid") is not None:
        with STATE_LOCK:
            m = STATE["markets"].get(asset)
            if m and m.get("ticker"):
                tk_live = MT5_TICK.get(asset)
                if tk_live:
                    m["ticker"].update({"price": tk_live["last"], "bid": tk_live["bid"], "ask": tk_live["ask"],
                                        "spread": tk_live["spread"], "change_pct": tk_live["change_pct"],
                                        "high24": tk_live["high24"], "low24": tk_live["low24"], "volume24": tk_live["volume24"]})
                    m["stale"] = False
    return {"ok": not need_full, "need_full": need_full, "asset": asset, "tf": tf, "candles": len(candles)}


# ---- Tài khoản MT5 (EA gửi mỗi 2s) ----
MT5_ACCOUNT = {"ts": 0, "data": None}
EQUITY_HIST = deque(maxlen=1440)        # 1 điểm / phút, giữ 24h trong RAM
EQUITY_LAST = {"t": 0}
ACCOUNT_CURRENCY_RE = re.compile(r"^[A-Z]{3,5}$")
ACCOUNT_TRADE_MODES = ("demo", "real", "contest")


def account_push(body):
    acc = {}
    for k in ("login", "leverage", "ea_magic"):
        acc[k] = int(body.get(k) or 0)
    for k in ("server", "company", "currency", "trade_mode", "terminal_time", "ea_version"):
        acc[k] = str(body.get(k) or "")[:80]
    # currency / trade_mode được dashboard hiển thị khắp nơi -> chỉ nhận giá trị hợp lệ, còn lại bỏ
    rejected = []
    if acc["currency"] and not ACCOUNT_CURRENCY_RE.match(acc["currency"]):
        rejected.append("currency")
        acc["currency"] = ""
    if acc["trade_mode"] and acc["trade_mode"] not in ACCOUNT_TRADE_MODES:
        rejected.append("trade_mode")
        acc["trade_mode"] = ""
    for k in ("balance", "equity", "margin", "free_margin", "margin_level", "profit", "ea_realized_today", "ea_floating"):
        acc[k] = float(body.get(k) or 0)
    pos = []
    for it in (body.get("positions") or [])[:50]:
        pos.append({"ticket": int(it.get("ticket") or 0), "symbol": str(it.get("symbol", ""))[:30],
                    "type": "BUY" if it.get("type") == "BUY" else "SELL", "volume": float(it.get("volume") or 0),
                    "open": float(it.get("open") or 0), "current": float(it.get("current") or 0),
                    "sl": float(it.get("sl") or 0), "tp": float(it.get("tp") or 0), "profit": float(it.get("profit") or 0),
                    "magic": int(it.get("magic") or 0), "comment": str(it.get("comment", ""))[:40],
                    "time": str(it.get("time", ""))[:20]})
    acc["positions"] = pos
    acc["received_at"] = now_iso()
    now = time.time()
    with MT5_LOCK:
        MT5_ACCOUNT["ts"] = now
        MT5_ACCOUNT["data"] = acc
        if now - EQUITY_LAST["t"] >= 60:
            EQUITY_LAST["t"] = now
            EQUITY_HIST.append({"t": int(now), "balance": acc["balance"], "equity": acc["equity"]})
            try:
                with DB_LOCK:
                    conn = db_conn()
                    conn.execute("INSERT INTO account_history (ts, login, balance, equity, margin) VALUES (?,?,?,?,?)",
                                 (int(now), acc["login"], acc["balance"], acc["equity"], acc["margin"]))
                    conn.execute("DELETE FROM account_history WHERE ts < ?", (int(now) - 30 * 86400,))
                    conn.commit()
                    conn.close()
            except Exception as e:
                print("account_history:", e)
    # Nếu EA gửi kèm danh sách deal vừa đóng (SL/TP/BE/Manual), đồng bộ ngay vào bảng executions & signal_outcomes
    recent_closed = body.get("recent_closed")
    if recent_closed and isinstance(recent_closed, list):
        try:
            sync_closed_deals(recent_closed)
        except Exception as e:
            print("sync_closed_deals:", e)
    if rejected:
        return {"ok": True, "rejected": rejected}
    return {"ok": True}


def account_snapshot():
    with MT5_LOCK:
        d = MT5_ACCOUNT["data"]
        age = time.time() - MT5_ACCOUNT["ts"] if MT5_ACCOUNT["ts"] else None
        hist = list(EQUITY_HIST)[-360:]
    if not d:
        return None
    out = dict(d)
    out["age_sec"] = int(age) if age is not None else None
    out["online"] = age is not None and age < 30
    out["history"] = hist
    return out


def account_load_history():
    """Nạp lại 24h lịch sử equity từ SQLite khi khởi động."""
    try:
        with DB_LOCK:
            conn = db_conn()
            rows = conn.execute("SELECT ts, balance, equity FROM account_history WHERE ts >= ? ORDER BY ts",
                                (int(time.time()) - 86400,)).fetchall()
            conn.close()
        for r in rows:
            EQUITY_HIST.append({"t": r["ts"], "balance": r["balance"], "equity": r["equity"]})
    except Exception as e:
        print("load history:", e)


def mt5_balance():
    with MT5_LOCK:
        d = MT5_ACCOUNT["data"]
        fresh = MT5_ACCOUNT["ts"] and time.time() - MT5_ACCOUNT["ts"] < 120
    return d["balance"] if (d and fresh) else None


# ---- Thống kê lịch sử theo magic: chỉ lấy khi người dùng bấm xem ----
HIST_REQ = {"cur": None}       # yêu cầu gần nhất: {id, magic, from, to, status, created, picked, result, error}
HIST_LOCK = threading.Lock()


def stats_request(magic, dfrom, dto):
    with HIST_LOCK:
        rid = int(time.time() * 1000)
        HIST_REQ["cur"] = {"id": rid, "magic": int(magic), "from": dfrom, "to": dto, "status": "pending",
                           "created": time.time(), "picked": 0, "acked": 0, "tries": 0, "result": None, "error": "",
                           "last_ea_error": ""}
    log("vault_piggy", "📈 Yêu cầu EA gửi lịch sử magic %s từ %s đến %s" % (magic or "tất cả", dfrom, dto), room="vault_room")
    return rid


def stats_pending_for_ea():
    """Gắn vào phản hồi /api/push_account. Gửi lại nếu EA nhận mà 25s chưa trả kết quả."""
    with HIST_LOCK:
        r = HIST_REQ["cur"]
        if not r or r["status"] != "pending" or time.time() - r["created"] > 300:
            return None
        if r["picked"] and time.time() - r["picked"] < 25:
            return None
        r["picked"] = time.time()
        r["tries"] += 1
        log("vault_piggy", "📤 Đã chuyển yêu cầu thống kê #%d cho EA (lần %d)" % (r["id"], r["tries"]), room="vault_room")
        return {"id": r["id"], "magic": r["magic"], "from": r["from"], "to": r["to"]}


def _deal_net(d):
    return float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)


def compute_stats(p):
    deals = sorted(p.get("deals") or [], key=lambda d: (int(d.get("time") or 0), int(d.get("ticket") or 0)))
    start_bal = float(p.get("balance_at_from") or 0)
    # gom theo position
    pos = {}
    for d in deals:
        pid = int(d.get("position") or d.get("ticket") or 0)
        t = pos.setdefault(pid, {"position": pid, "symbol": d.get("symbol", ""), "side": "", "volume": 0.0, "open_time": 0,
                                 "close_time": 0, "open_price": 0.0, "close_price": 0.0, "net": 0.0, "closed": False,
                                 "reason": "", "comment": "", "deal_ticket": 0})
        t["net"] += _deal_net(d)
        if d.get("entry") == "in":
            t["side"] = d.get("type", "").upper()
            t["volume"] += float(d.get("volume") or 0)
            t["open_time"] = t["open_time"] or int(d["time"])
            t["open_price"] = float(d.get("price") or 0)
            if d.get("comment"):
                t["comment"] = str(d.get("comment"))
        else:
            t["closed"] = True
            t["close_time"] = int(d["time"])
            t["close_price"] = float(d.get("price") or 0)
            t["deal_ticket"] = int(d.get("ticket") or 0)
            if d.get("reason"):
                t["reason"] = str(d.get("reason"))
            if d.get("comment") and not t["comment"]:
                t["comment"] = str(d.get("comment"))
            if not t["side"]:      # lệnh mở trước khoảng thời gian: deal đóng SELL => vị thế BUY
                t["side"] = "BUY" if d.get("type") == "sell" else "SELL"
            if not t["volume"]:
                t["volume"] = float(d.get("volume") or 0)
    trades = sorted([t for t in pos.values() if t["closed"]], key=lambda t: t["close_time"])
    # đường lãi lỗ tích luỹ + drawdown theo từng deal có tiền
    curve, cum, peak, max_dd, max_dd_pct = [], 0.0, 0.0, 0.0, 0.0
    for d in deals:
        net = _deal_net(d)
        if abs(net) < 1e-9:
            continue
        cum += net
        peak = max(peak, cum)
        dd = cum - peak
        base = start_bal + peak
        ddp = dd / base * 100 if base > 0 else 0.0
        max_dd = min(max_dd, dd)
        max_dd_pct = min(max_dd_pct, ddp)
        curve.append({"t": int(d["time"]), "cum": round(cum, 2), "dd": round(dd, 2), "ddp": round(ddp, 3),
                      "bal": round(start_bal + cum, 2)})
    if len(curve) > 1500:
        step = len(curve) / 1500.0
        curve = [curve[int(i * step)] for i in range(1500)] + [curve[-1]]
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    gp, gl = sum(wins), sum(losses)
    streak = max_streak = 0
    for t in trades:
        streak = streak + 1 if t["net"] <= 0 else 0
        max_streak = max(max_streak, streak)
    # theo ngày / tuần
    span_days = (int(p.get("to_ts") or 0) - int(p.get("from_ts") or 0)) / 86400.0
    weekly = span_days > 120
    buckets = {}
    for t in trades:
        dt = datetime.fromtimestamp(t["close_time"], timezone.utc)
        if weekly:
            from datetime import timedelta
            dt = dt - timedelta(days=dt.weekday())
        key = dt.strftime("%Y-%m-%d")
        b = buckets.setdefault(key, {"label": key, "pnl": 0.0, "trades": 0})
        b["pnl"] += t["net"]
        b["trades"] += 1
    by_symbol, by_side = {}, {}
    for t in trades:
        for grp, k in ((by_symbol, t["symbol"]), (by_side, t["side"] or "?")):
            g = grp.setdefault(k, {"key": k, "trades": 0, "net": 0.0, "wins": 0})
            g["trades"] += 1
            g["net"] += t["net"]
            g["wins"] += 1 if t["net"] > 0 else 0
    net = sum(_deal_net(d) for d in deals)
    n = len(trades)
    summary = {
        "net": round(net, 2), "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "profit_factor": round(gp / abs(gl), 2) if gl < 0 else None,
        "trades": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_win": round(gp / len(wins), 2) if wins else 0.0, "avg_loss": round(gl / len(losses), 2) if losses else 0.0,
        "best": round(max(wins), 2) if wins else 0.0, "worst": round(min(losses), 2) if losses else 0.0,
        "expectancy": round(net / n, 2) if n else 0.0,
        "max_dd": round(max_dd, 2), "max_dd_pct": round(max_dd_pct, 2),
        "recovery_factor": round(net / abs(max_dd), 2) if max_dd < 0 else None,
        "max_loss_streak": max_streak,
        "return_pct": round(net / start_bal * 100, 2) if start_bal > 0 else None,
        "start_balance": round(start_bal, 2), "end_balance": round(start_bal + net, 2),
        "balance_now": float(p.get("balance_now") or 0), "currency": str(p.get("currency") or "") if ACCOUNT_CURRENCY_RE.match(str(p.get("currency") or "")) else "",
        "deals": len(deals), "truncated": bool(p.get("truncated")),
    }
    recent = [dict(t, net=round(t["net"], 2)) for t in trades[-100:]][::-1]
    return {"summary": summary, "curve": curve, "buckets": sorted(buckets.values(), key=lambda b: b["label"]),
            "bucket_unit": "tuần" if weekly else "ngày",
            "by_symbol": sorted(by_symbol.values(), key=lambda g: g["net"]),
            "by_side": list(by_side.values()), "trades": recent,
            "magic": p.get("magic"), "from": p.get("from"), "to": p.get("to"), "server_time_note": "giờ server broker"}


def stats_receive(p):
    with HIST_LOCK:
        r = HIST_REQ["cur"]
        if not r or int(p.get("id") or 0) != r["id"]:
            return {"ok": False, "error": "yêu cầu đã cũ"}
        stage = p.get("stage")
        if stage == "ack":
            r["acked"] = time.time()
            return {"ok": True}
        if stage == "error":
            r["last_ea_error"] = "%s (gói %s KB)" % (str(p.get("error", ""))[:200], p.get("size_kb", "?"))
            r["picked"] = time.time() - 20          # cho EA thử lại sau ~5s
            log("vault_piggy", "⚠️ EA gửi lịch sử lỗi: %s" % r["last_ea_error"], room="vault_room")
            if r["tries"] >= 3:
                r["status"], r["error"] = "error", "EA gửi lịch sử thất bại 3 lần: " + r["last_ea_error"]
            return {"ok": True}
    try:
        res = compute_stats(p)
        with HIST_LOCK:
            r["result"], r["status"] = res, "done"
        try:
            n_out = outcomes_from_history(res["trades"])
            if n_out:
                log("vault_piggy", "🎯 Cập nhật kết quả SL/TP của %d kèo từ lịch sử giao dịch." % n_out, room="vault_room")
        except Exception as e:
            print("outcomes_from_history:", e)
        sm = res["summary"]
        log("vault_piggy", "📈 Thống kê magic %s: %d lệnh, lãi/lỗ %+.2f %s, DD tối đa %.2f (%.2f%%)" % (
            r["magic"] or "tất cả", sm["trades"], sm["net"], sm["currency"], sm["max_dd"], sm["max_dd_pct"]), room="vault_room")
        return {"ok": True}
    except Exception as e:
        traceback.print_exc()
        with HIST_LOCK:
            r["status"], r["error"] = "error", str(e)[:200]
        return {"ok": False, "error": str(e)[:200]}


def stats_status(rid):
    with HIST_LOCK:
        r = HIST_REQ["cur"]
        if not r or r["id"] != rid:
            return {"status": "missing"}
        out = {"status": r["status"], "error": r["error"], "waited": int(time.time() - r["created"]),
               "picked": bool(r["picked"]), "acked": bool(r["acked"]), "tries": r["tries"],
               "since_pick": int(time.time() - r["picked"]) if r["picked"] else None, "ea_error": r["last_ea_error"]}
        if r["status"] == "done":
            out["result"] = r["result"]
        return out


EA_INT_KEYS = ("ea_poll_seconds", "ea_web_timeout_ms", "ea_tick_interval_ms", "ea_candle_interval_sec", "ea_bridge_bars",
               "ea_min_confidence", "ea_max_signal_age_sec", "ea_max_open_per_symbol", "ea_breakeven_buffer_pts",
               "ea_magic", "ea_slippage_points")
EA_FLOAT_KEYS = ("ea_risk_percent", "ea_max_daily_loss_pct", "ea_panel_scale")
EA_BOOL_KEYS = ("ea_show_panel", "ea_report_executions", "ea_enable_price_bridge", "ea_use_server_lot", "ea_split_tp", "ea_dry_run", "ea_enable_trading")


def ea_config():
    """JSON phẳng cho EA mt5/AITradingOffice.mq5: bỏ tiền tố ea_."""
    out = {}
    for k in DEFAULT_CONFIG:
        if k.startswith("ea_"):
            out[k[3:]] = CONFIG.get(k, DEFAULT_CONFIG[k])
    out["server_time"] = now_iso()
    return out


def mt5_status():
    stale = float(CONFIG.get("bridge_stale_sec") or 90)
    now = time.time()
    out = {}
    with MT5_LOCK:
        for asset in ASSETS:
            t = MT5_TICK.get(asset)
            feeds = {tf: int(now - f["ts"]) for (a, tf), f in MT5_FEED.items() if a == asset}
            out[asset] = {"connected": bool(t and now - t["ts"] < stale), "age_sec": int(now - t["ts"]) if t else None,
                          "symbol": t["symbol"] if t else None, "bid": t["bid"] if t else None, "ask": t["ask"] if t else None,
                          "spread": t["spread"] if t else None, "feeds": feeds}
    return out


def fetch_mt5(asset, tf):
    stale = float(CONFIG.get("bridge_stale_sec") or 90)
    with MT5_LOCK:
        f = MT5_FEED.get((asset, tf))
        t = MT5_TICK.get(asset)
    now = time.time()
    candle_stale = max(stale, TF_SECONDS.get(tf, 300))
    if not f or now - f["ts"] > candle_stale:
        raise RuntimeError("MT5 chưa đẩy nến %s %s (hoặc quá %ds)" % (asset, tf, candle_stale))
    if CONFIG.get("price_source", "mt5_only") == "mt5_only" and not (t and now - t["ts"] < stale):
        raise RuntimeError("MT5 không có tick %s trong %ds (EA mất kết nối?)" % (asset, stale))
    # Chỉ sao chép nông danh sách và clone riêng nến cuối cùng để tiết kiệm CPU/RAM
    raw_candles = f["candles"]
    candles = list(raw_candles[:-1]) + [dict(raw_candles[-1])]
    if t and now - t["ts"] < stale:
        # cập nhật nến cuối bằng tick mới nhất để giá realtime
        last = candles[-1]
        last["c"] = t["last"]
        if t["last"] > last["h"]:
            last["h"] = t["last"]
        if t["last"] < last["l"]:
            last["l"] = t["last"]
        ticker = {"price": t["last"], "bid": t["bid"], "ask": t["ask"], "spread": t["spread"],
                  "change_pct": t["change_pct"], "high24": t["high24"], "low24": t["low24"], "volume24": t["volume24"]}
    else:
        day = [c for c in candles if c["t"] >= candles[-1]["t"] - 86400] or candles[-20:]
        base = day[0]["o"]
        ticker = {"price": candles[-1]["c"], "change_pct": (candles[-1]["c"] - base) / base * 100 if base else 0.0,
                  "high24": max(c["h"] for c in day), "low24": min(c["l"] for c in day),
                  "volume24": sum(c["v"] for c in day)}
    return candles, ticker, "mt5:" + f["symbol"]


MARKET_CACHE = {}
MARKET_CACHE_LOCK = threading.Lock()
_IND_CACHE = {}        # {(asset, tf): {"sig": tuple, "ind": dict}}


def fetch_market(asset, tf, max_age=45, publish=True):
    """publish=False: chỉ lấy dữ liệu (khung phụ H1/H4), không ghi đè ticker khung chính trên dashboard."""
    key = (asset, tf)
    stale_cfg = float(CONFIG.get("bridge_stale_sec") or 90)
    with MT5_LOCK:
        mt5_live = (asset, tf) in MT5_FEED and time.time() - MT5_FEED[(asset, tf)]["ts"] < stale_cfg
    if mt5_live:
        max_age = min(max_age, 1.5)   # MT5 online: làm tươi mượt mỗi 1.5s, kết hợp _IND_CACHE chống tính lặp
    mt5_only = CONFIG.get("price_source", "mt5_only") == "mt5_only"
    # mt5_only = CHỈ giá MT5. Dự phòng Binance cho BTCUSDT chỉ khi bật riêng btc_binance_fallback (mặc định tắt)
    btc_fb = mt5_only and asset == "BTCUSDT" and bool(CONFIG.get("btc_binance_fallback", False))
    with MARKET_CACHE_LOCK:
        c = MARKET_CACHE.get(key)
        if c and time.time() - c["ts"] < max_age and (not mt5_only or c["data"]["source"].startswith("mt5:") or btc_fb):
            return c["data"]
    errors = []
    fns = (fetch_mt5, fetch_binance) if btc_fb else ((fetch_mt5,) if mt5_only else (fetch_mt5, fetch_binance, fetch_yahoo))
    for fn in fns:
        try:
            candles, ticker, source = fn(asset, tf)
            if len(candles) < 30:
                raise RuntimeError("Quá ít nến (%d)" % len(candles))
            off = broker_offset_or_utc(asset, "VWAP phiên") if source.startswith("mt5:") else 0
            last_c = candles[-1]
            prev_t = candles[-2]["t"] if len(candles) > 1 else 0
            # Chữ ký nến: nếu nến cuối chưa đổi OHLC (hoặc biến động < 1e-6) thì tái sử dụng kết quả chỉ báo đã tính
            ind_sig = (source, len(candles), prev_t, last_c["t"],
                       round(last_c["o"], 4), round(last_c["h"], 4), round(last_c["l"], 4), round(last_c["c"], 4), off)
            with MARKET_CACHE_LOCK:
                ic = _IND_CACHE.get(key)
            if ic and ic.get("sig") == ind_sig:
                ind = ic["ind"]
            else:
                ind = compute_indicators(candles, utc_offset_hours=off)
                with MARKET_CACHE_LOCK:
                    _IND_CACHE[key] = {"sig": ind_sig, "ind": ind}
            data = {"asset": asset, "label": ASSETS[asset]["label"], "timeframe": tf, "source": source,
                    "ticker": ticker, "indicators": ind, "candles_count": len(candles),
                    "candles": candles[-65:], "fetched_at": now_iso(), "source_errors": errors}
            with MARKET_CACHE_LOCK:
                MARKET_CACHE[key] = {"ts": time.time(), "data": data, "all": candles}
            if publish:
                with STATE_LOCK:
                    STATE["markets"][asset] = {k: v for k, v in data.items() if k != "candles"}
            return data
        except Exception as e:
            errors.append("%s: %s" % (fn.__name__, e))
    if mt5_only:
        if publish:
            with STATE_LOCK:
                m = STATE["markets"].get(asset)
                if m:
                    m["stale"] = True
        raise RuntimeError("Chưa có giá MT5 realtime cho %s khung %s, không họp để tránh dùng giá sai. "
                           "Kiểm tra EA trên VPS. (%s)" % (asset, tf, " | ".join(errors)))
    with MARKET_CACHE_LOCK:
        c = MARKET_CACHE.get(key)
    if c:
        return c["data"]
    raise RuntimeError("Không lấy được dữ liệu %s: %s" % (asset, " | ".join(errors)))


def market_full(asset, tf, publish=False):
    """Như fetch_market nhưng trả thêm toàn bộ nến (tới 400) cho các agent cần lịch sử dài."""
    data = fetch_market(asset, tf, publish=publish)
    with MARKET_CACHE_LOCK:
        c = MARKET_CACHE.get((asset, tf))
    full = c.get("all") if c and c.get("data") is data else None
    return data, (full or data["candles"])


def prefetch_timeframes(asset, tfs=("5m", "15m", "1h", "4h"), main_tf=None):
    """Kéo song song nhiều khung thời gian vào MARKET_CACHE để bước họp đa khung không phải chờ tuần tự."""
    threads = []
    for t in set(tfs):
        if t not in TF_SECONDS:
            continue
        pub = (t == main_tf)
        th = threading.Thread(target=lambda _t=t, _p=pub: _safe_prefetch(asset, _t, _p), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(timeout=10)


def _safe_prefetch(asset, tf, publish):
    try:
        fetch_market(asset, tf, publish=publish)
    except Exception:
        pass


FALLBACK_NEWS = [
    {"title": "Fed giữ lập trường thận trọng, thị trường chờ dữ liệu lạm phát CPI", "source": "offline",
     "url": "", "published": ""},
    {"title": "Dòng tiền ETF Bitcoin tiếp tục là biến số chính của xu hướng trung hạn", "source": "offline",
     "url": "", "published": ""},
    {"title": "Vàng được hỗ trợ bởi nhu cầu trú ẩn và mua ròng của các ngân hàng trung ương", "source": "offline",
     "url": "", "published": ""},
    {"title": "Chỉ số DXY và lợi suất trái phiếu 10 năm là hai biến cần theo dõi cho XAU", "source": "offline",
     "url": "", "published": ""},
]
NEWS_CACHE = {"ts": 0, "items": []}
RSS_FEEDS = [
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F,BTC-USD&region=US&lang=en-US"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
]


def fetch_rss(name, url, limit=5):
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for it in root.findall(".//item")[:limit]:
        title = (it.findtext("title") or "").strip()
        if title:
            out.append({"title": title, "source": name, "url": (it.findtext("link") or "").strip(),
                        "published": (it.findtext("pubDate") or "")[:22]})
    return out


def fetch_news(max_age=600):
    """CryptoCompare (key tuỳ chọn) -> RSS miễn phí (Yahoo/CoinDesk/CoinTelegraph) -> offline."""
    if time.time() - NEWS_CACHE["ts"] < max_age and NEWS_CACHE["items"]:
        return NEWS_CACHE["items"]
    items = []
    try:
        url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
        key = CONFIG.get("cryptocompare_api_key") or ""
        if key:
            url += "&api_key=" + urllib.parse.quote(key)
        data = http_get_json(url)
        for n in data.get("Data", [])[:12]:
            items.append({"title": n.get("title", ""), "source": n.get("source", ""), "url": n.get("url", ""),
                          "published": datetime.fromtimestamp(n.get("published_on", 0)).strftime("%H:%M %d/%m")})
    except Exception as e:
        print("news cryptocompare fallback:", str(e)[:80])
    if not items:
        for name, url in RSS_FEEDS:
            try:
                items.extend(fetch_rss(name, url))
            except Exception as e:
                print("news rss %s fallback: %s" % (name, str(e)[:80]))
    tg = telegram_news()
    items = tg + [i for i in items if i["title"] not in {t["title"] for t in tg}]
    if items:
        NEWS_CACHE["ts"] = time.time()
        NEWS_CACHE["items"] = items
        with STATE_LOCK:
            STATE["news"] = items
        return items
    with STATE_LOCK:
        STATE["news"] = FALLBACK_NEWS
    return FALLBACK_NEWS


# ============================================================================
# 4. QUANT ENGINE (Python thuần — đã tối ưu O(N) & chuẩn hoá múi giờ UTC)
# ============================================================================
def ema(values, period):
    """EMA chuẩn: khởi tạo bằng SMA của `period` nến đầu tiên để tránh lệch pha EMA200."""
    n = len(values)
    if not n:
        return []
    k = 2.0 / (period + 1)
    k1 = 1.0 - k
    if n <= period:
        out = [values[0]]
        for v in values[1:]:
            out.append(v * k + out[-1] * k1)
        return out
    seed = sum(values[:period]) / float(period)
    out = [values[0]] * period
    out[period - 1] = seed
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * k1
        out.append(prev)
    return out


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    avg_g, avg_l = gains / period, losses / period
    p_1 = period - 1
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            avg_g = (avg_g * p_1 + d) / period
            avg_l = (avg_l * p_1) / period
        else:
            avg_g = (avg_g * p_1) / period
            avg_l = (avg_l * p_1 - d) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def true_ranges(candles):
    return [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(candles, candles[1:])]


def atr(candles, period=14, trs=None):
    if len(candles) < period + 1:
        return candles[-1]["h"] - candles[-1]["l"]
    if trs is None:
        trs = true_ranges(candles)
    a = sum(trs[:period]) / float(period)
    p_1 = period - 1
    for tr in trs[period:]:
        a = (a * p_1 + tr) / float(period)
    return a


def session_vwap(candles, sigma_mult=1.5, utc_offset_hours=0):
    """VWAP phiên hiện tại (chuẩn hoá về 00:00 UTC theo độ lệch giờ broker) + dải ±σ."""
    off_sec = int(utc_offset_hours * 3600)
    last_utc = candles[-1]["t"] - off_sec
    day_start_utc = last_utc - (last_utc % 86400)
    day_start_raw = day_start_utc + off_sec
    sess = [c for c in candles if c["t"] >= day_start_raw]
    if len(sess) < 5:
        sess = candles[-48:]
    pv, vol, pv2 = 0.0, 0.0, 0.0
    for c in sess:
        tp = (c["h"] + c["l"] + c["c"]) / 3.0
        v = c["v"] if c["v"] > 0 else 1.0
        pv += tp * v
        vol += v
        pv2 += tp * tp * v
    vwap = pv / vol
    var = max(pv2 / vol - vwap * vwap, 0.0)
    sd = math.sqrt(var)
    return vwap, vwap + sigma_mult * sd, vwap - sigma_mult * sd, sd, len(sess)


def wilder_series(values, period):
    """Làm trơn kiểu Wilder (như ATR/RSI). Trả list dài len(values) - period + 1."""
    if len(values) < period:
        return []
    first = sum(values[:period]) / float(period)
    out = [first]
    p_1 = period - 1
    inv_p = 1.0 / float(period)
    prev = first
    for v in values[period:]:
        prev = (prev * p_1 + v) * inv_p
        out.append(prev)
    return out


def adx(candles, period=14, trs=None):
    """ADX(14) Wilder + DI+/DI-. Tái sử dụng chuỗi `trs` nếu đã tính sẵn."""
    if len(candles) < period * 2 + 1:
        return 0.0, 0.0, 0.0, []
    pdm, mdm = [], []
    for p, c in zip(candles, candles[1:]):
        up, dn = c["h"] - p["h"], p["l"] - c["l"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    if trs is None:
        trs = true_ranges(candles)
    tr_s = wilder_series(trs, period)
    p_s = wilder_series(pdm, period)
    m_s = wilder_series(mdm, period)
    dx, pdi, mdi = [], 0.0, 0.0
    for a, pp, mm in zip(tr_s, p_s, m_s):
        pdi = 100.0 * pp / a if a else 0.0
        mdi = 100.0 * mm / a if a else 0.0
        s_di = pdi + mdi
        dx.append(100.0 * abs(pdi - mdi) / s_di if s_di else 0.0)
    adx_s = wilder_series(dx, period)
    return (adx_s[-1] if adx_s else 0.0), pdi, mdi, tr_s


def bollinger_stats(closes, period=20, mult=2.0, lookback=100):
    """Độ rộng Bollinger (% so với dải giữa) và percentile trong `lookback` nến — tối ưu cửa sổ trượt O(N)."""
    n = len(closes)
    if n < period:
        last_p = closes[-1] if closes else 0.0
        return 0.0, 50.0, last_p, last_p, last_p
    start_end = max(period, n - lookback + 1)
    first_start = start_end - period
    w0 = closes[first_start:start_end]
    s1 = sum(w0)
    s2 = sum(x * x for x in w0)
    inv_p = 1.0 / float(period)
    widths = []
    m = s1 * inv_p
    sd = math.sqrt(max(0.0, s2 * inv_p - m * m))
    widths.append(2.0 * mult * sd / m * 100.0 if m else 0.0)
    for idx in range(start_end, n):
        old_v = closes[idx - period]
        new_v = closes[idx]
        s1 += new_v - old_v
        s2 += new_v * new_v - old_v * old_v
        m = s1 * inv_p
        sd = math.sqrt(max(0.0, s2 * inv_p - m * m))
        widths.append(2.0 * mult * sd / m * 100.0 if m else 0.0)
    cur = widths[-1]
    pct = sum(1 for x in widths if x <= cur) * 100.0 / len(widths)
    return cur, pct, m + mult * sd, m, m - mult * sd


def swing_points(candles, k=2):
    """Đỉnh/đáy fractal: cao (thấp) nhất trong k nến mỗi bên."""
    highs, lows = [], []
    for i in range(k, len(candles) - k):
        ch, cl = candles[i]["h"], candles[i]["l"]
        win = candles[i - k:i + k + 1]
        if ch >= max(c["h"] for c in win):
            highs.append(ch)
        if cl <= min(c["l"] for c in win):
            lows.append(cl)
    return highs, lows


def compute_indicators(candles, utc_offset_hours=0):
    closes = [c["c"] for c in candles]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    vwap, vup, vlo, sd, n_sess = session_vwap(candles, sigma_mult=1.5, utc_offset_hours=utc_offset_hours)
    trs = true_ranges(candles)
    r = rsi(closes, 14)
    adx14, pdi, mdi, tr_s = adx(candles, 14, trs=trs)
    a = tr_s[-1] if tr_s else atr(candles, 14, trs=trs)
    last20 = candles[-21:-1] if len(candles) > 21 else candles[:-1]
    swing_high = max(c["h"] for c in last20)
    swing_low = min(c["l"] for c in last20)
    price = closes[-1]
    prev_close = closes[-2]
    # Cấu trúc EMA
    if e20[-1] > e50[-1] > e200[-1]:
        structure = "UPTREND"
    elif e20[-1] < e50[-1] < e200[-1]:
        structure = "DOWNTREND"
    else:
        structure = "SIDEWAY"
    # Vị trí giá so với VWAP
    if price > vup:
        vwap_zone = "ABOVE_UPPER"
    elif price > vwap:
        vwap_zone = "ABOVE_VWAP"
    elif price > vlo:
        vwap_zone = "BELOW_VWAP"
    else:
        vwap_zone = "BELOW_LOWER"
    # Liquidity sweep: nến gần nhất đâm qua swing rồi đóng ngược lại
    last = candles[-1]
    sweep = "NONE"
    if last["h"] > swing_high and last["c"] < swing_high:
        sweep = "SWEEP_HIGH"
    elif last["l"] < swing_low and last["c"] > swing_low:
        sweep = "SWEEP_LOW"
    # BOS (break of structure)
    bbw, bbw_pct, bb_up, bb_mid, bb_lo = bollinger_stats(closes)
    atr_s = tr_s[-100:] if tr_s else []
    atr_ratio = atr_s[-1] / (sum(atr_s) / len(atr_s)) if atr_s and sum(atr_s) > 0 else 1.0
    bos = "NONE"
    if last["c"] > swing_high:
        bos = "BULLISH_BOS"
    elif last["c"] < swing_low:
        bos = "BEARISH_BOS"

    # Phân tích Khối lượng & VSA (Volume Spread Analysis — Cá Voi Volume)
    vols_prev20 = [max(float(c.get("v") or 0.0), 0.0) for c in (candles[-21:-1] if len(candles) > 21 else candles[:-1])]
    vol_ma20 = (sum(vols_prev20) / len(vols_prev20)) if vols_prev20 and sum(vols_prev20) > 0 else max(float(last.get("v") or 1.0), 1.0)
    vol_cur = max(float(last.get("v") or 0.0), 0.0)
    vol_ratio = vol_cur / vol_ma20 if vol_ma20 > 0 else 1.0
    vols_last3 = [max(float(c.get("v") or 0.0), 0.0) for c in candles[-3:]]
    vol_ratio_3 = (sum(vols_last3) / max(1, len(vols_last3))) / vol_ma20 if vol_ma20 > 0 else 1.0

    # Ước lượng Volume Delta (chênh lệch dòng tiền mua/bán chủ động trên 10 nến gần nhất)
    buy_vol_10, sell_vol_10 = 0.0, 0.0
    for c in candles[-10:]:
        v_c = max(float(c.get("v") or 0.0), 0.0)
        rng_c = c["h"] - c["l"]
        if rng_c > 0:
            buy_frac = (c["c"] - c["l"]) / rng_c
        else:
            buy_frac = 0.5
        buy_vol_10 += v_c * buy_frac
        sell_vol_10 += v_c * (1.0 - buy_frac)
    tot_vol_10 = buy_vol_10 + sell_vol_10
    vol_delta_ratio = (buy_vol_10 - sell_vol_10) / tot_vol_10 if tot_vol_10 > 0 else 0.0

    # Tín hiệu VSA (Volume Spread Analysis) trên nến hiện tại
    bar_rng = max(last["h"] - last["l"], 1e-9)
    body = abs(last["c"] - last["o"])
    body_ratio = body / bar_rng
    upper_wick = (last["h"] - max(last["o"], last["c"])) / bar_rng
    lower_wick = (min(last["o"], last["c"]) - last["l"]) / bar_rng
    last_range_atr = (last["h"] - last["l"]) / a if a else 0.0

    if vol_ratio >= 1.5 and (lower_wick >= 0.45 or sweep == "SWEEP_LOW"):
        vsa_signal = "ABSORPTION_BULL"     # Cao trào hấp thụ cầu dưới đáy (Stopping Volume Bullish)
    elif vol_ratio >= 1.5 and (upper_wick >= 0.45 or sweep == "SWEEP_HIGH"):
        vsa_signal = "ABSORPTION_BEAR"     # Cao trào hấp thụ cung trên đỉnh (Upthrust / Stopping Volume Bearish)
    elif vol_ratio >= 1.35 and body_ratio >= 0.55 and last["c"] > last["o"]:
        vsa_signal = "HIGH_VOL_BULL"       # Nến tăng thân rộng kèm Volume đột biến (Marubozu cầu mạnh)
    elif vol_ratio >= 1.35 and body_ratio >= 0.55 and last["c"] < last["o"]:
        vsa_signal = "HIGH_VOL_BEAR"       # Nến giảm thân rộng kèm Volume đột biến (Marubozu cung mạnh)
    elif bos == "BULLISH_BOS" and vol_ratio < 0.85:
        vsa_signal = "WEAK_BREAKOUT_UP"    # Phá đỉnh nhưng cạn cầu (No Demand / Fakeout cảnh báo)
    elif bos == "BEARISH_BOS" and vol_ratio < 0.85:
        vsa_signal = "WEAK_BREAKOUT_DOWN"  # Phá đáy nhưng cạn cung (No Supply / Fakeout cảnh báo)
    elif vol_ratio >= 1.6 and body_ratio < 0.30 and last_range_atr < 0.9:
        vsa_signal = "EFFORT_NO_RESULT"    # Volume rất lớn nhưng thân nến hẹp (hấp thụ ngầm)
    elif vol_ratio < 0.65:
        vsa_signal = "LOW_VOL"             # Thanh khoản cạn kiệt
    else:
        vsa_signal = "NORMAL"

    return {
        "price": price, "prev_close": prev_close,
        "vwap": vwap, "vwap_upper": vup, "vwap_lower": vlo, "vwap_sd": sd,
        "vwap_zscore": round((price - vwap) / sd, 2) if sd > 0 else 0.0,
        "vwap_session_bars": n_sess,
        "ema20": e20[-1], "ema50": e50[-1], "ema200": e200[-1],
        "rsi14": r, "atr14": a,
        "swing_high": swing_high, "swing_low": swing_low,
        "structure": structure, "vwap_zone": vwap_zone, "sweep": sweep, "bos": bos,
        "ema20_slope": (e20[-1] - e20[-4]) / e20[-4] * 100 if len(e20) > 4 else 0.0,
        # Trạng thái thị trường (Mèo Đo Nhịp)
        "adx14": adx14, "plus_di": pdi, "minus_di": mdi,
        "bb_width": bbw, "bb_width_pct": bbw_pct, "bb_upper": bb_up, "bb_mid": bb_mid, "bb_lower": bb_lo,
        "atr_ratio": atr_ratio, "last_range_atr": last_range_atr,
        # Khối lượng & VSA (Cá Voi Volume)
        "vol_current": round(vol_cur, 2),
        "vol_ma20": round(vol_ma20, 2),
        "vol_ratio": round(vol_ratio, 2),
        "vol_ratio_3": round(vol_ratio_3, 2),
        "vol_delta_ratio": round(vol_delta_ratio, 3),
        "vsa_signal": vsa_signal,
    }


# ---- Phiếu bầu từng chuyên viên ----
def vote_vwap(ind):
    p, v, up, lo = ind["price"], ind["vwap"], ind["vwap_upper"], ind["vwap_lower"]
    vr = ind.get("vol_ratio", 1.0)
    dist = (p - v) / v * 100
    if ind["vwap_zone"] == "ABOVE_VWAP" and p < up:
        if vr < 0.65 and ind.get("vol_delta_ratio", 0) < -0.1:
            return "WAIT", "Giá %.2f trên VWAP %.2f nhưng RVOL chỉ %.2f× TB20 và dòng tiền âm → thiếu cầu đẩy, WAIT." % (p, v, vr)
        return "BUY", "Giá %.2f nằm trên VWAP %.2f (+%.2f%%, RVOL %.2f×) chưa chạm biên trên %.2f → thiên BUY theo dòng tiền." % (p, v, dist, vr, up)
    if ind["vwap_zone"] == "BELOW_VWAP" and p > lo:
        if vr < 0.65 and ind.get("vol_delta_ratio", 0) > 0.1:
            return "WAIT", "Giá %.2f dưới VWAP %.2f nhưng RVOL chỉ %.2f× TB20 và áp lực bán yếu → WAIT." % (p, v, vr)
        return "SELL", "Giá %.2f nằm dưới VWAP %.2f (%.2f%%, RVOL %.2f×) chưa chạm biên dưới %.2f → thiên SELL theo dòng tiền." % (p, v, dist, vr, lo)
    if ind["vwap_zone"] == "ABOVE_UPPER":
        return "WAIT", "Giá vượt biên trên +1.5σ (%.2f) → vùng quá mua theo VWAP, chờ hồi về trục rồi mới BUY." % up
    return "WAIT", "Giá thủng biên dưới -1.5σ (%.2f) → vùng quá bán theo VWAP, chờ nảy về trục rồi mới SELL." % lo


def vote_smc(ind):
    vr = ind.get("vol_ratio", 1.0)
    if ind["sweep"] == "SWEEP_LOW":
        return "BUY", "Phát hiện quét thanh khoản dưới Swing Low %.2f rồi đóng nến ngược lên (RVOL %.2f×) → bẫy Bear, ưu tiên BUY." % (ind["swing_low"], vr)
    if ind["sweep"] == "SWEEP_HIGH":
        return "SELL", "Phát hiện quét thanh khoản trên Swing High %.2f rồi đóng nến ngược xuống (RVOL %.2f×) → bẫy Bull, ưu tiên SELL." % (ind["swing_high"], vr)
    if ind["bos"] == "BULLISH_BOS":
        if vr < 0.8:
            return "WAIT", "Giá vượt Swing High %.2f (BOS) nhưng Volume yếu (RVOL %.2f× < 0.8×) → nghi ngờ bẫy phá vỡ giả (Fakeout), WAIT." % (ind["swing_high"], vr)
        return "BUY", "Giá phá vỡ cấu trúc (BOS) lên trên Swing High %.2f kèm Volume xác nhận (RVOL %.2f×) → lực mua chủ động." % (ind["swing_high"], vr)
    if ind["bos"] == "BEARISH_BOS":
        if vr < 0.8:
            return "WAIT", "Giá thủng Swing Low %.2f (BOS) nhưng Volume yếu (RVOL %.2f× < 0.8×) → nghi ngờ bẫy phá vỡ giả (Fakeout), WAIT." % (ind["swing_low"], vr)
        return "SELL", "Giá phá vỡ cấu trúc (BOS) xuống dưới Swing Low %.2f kèm Volume xác nhận (RVOL %.2f×) → lực bán chủ động." % (ind["swing_low"], vr)
    rng = ind["swing_high"] - ind["swing_low"]
    pos = (ind["price"] - ind["swing_low"]) / rng * 100 if rng > 0 else 50
    if pos < 25 and ind["structure"] == "UPTREND":
        return "BUY", "Giá ở %.0f%% đáy dải Swing (%.2f–%.2f) trong xu hướng tăng → vùng discount, ưu tiên BUY." % (pos, ind["swing_low"], ind["swing_high"])
    if pos > 75 and ind["structure"] == "DOWNTREND":
        return "SELL", "Giá ở %.0f%% đỉnh dải Swing (%.2f–%.2f) trong xu hướng giảm → vùng premium, ưu tiên SELL." % (pos, ind["swing_low"], ind["swing_high"])
    return "WAIT", "Giá đang ở %.0f%% dải Swing (%.2f–%.2f), chưa có BOS hay sweep rõ ràng → WAIT." % (pos, ind["swing_low"], ind["swing_high"])


def vote_trend(ind):
    r = ind["rsi14"]
    if ind["structure"] == "UPTREND":
        if r > 72:
            return "WAIT", "EMA20>EMA50>EMA200 (tăng) nhưng RSI %.1f quá mua → chờ hồi, không đuổi giá." % r
        return "BUY", "Cấu trúc EMA 20/50/200 xếp tầng tăng, RSI %.1f còn dư địa → BUY theo xu hướng." % r
    if ind["structure"] == "DOWNTREND":
        if r < 28:
            return "WAIT", "EMA20<EMA50<EMA200 (giảm) nhưng RSI %.1f quá bán → chờ nảy, không bán đuổi." % r
        return "SELL", "Cấu trúc EMA 20/50/200 xếp tầng giảm, RSI %.1f còn dư địa → SELL theo xu hướng." % r
    if ind["price"] > ind["ema50"] and r > 55:
        return "BUY", "EMA chưa xếp tầng nhưng giá trên EMA50 %.2f và RSI %.1f nghiêng Bull → BUY nhẹ." % (ind["ema50"], r)
    if ind["price"] < ind["ema50"] and r < 45:
        return "SELL", "EMA chưa xếp tầng nhưng giá dưới EMA50 %.2f và RSI %.1f nghiêng Bear → SELL nhẹ." % (ind["ema50"], r)
    return "WAIT", "EMA đan xen (sideway), RSI %.1f trung tính → WAIT chờ phá vỡ." % r


def vote_volume(ind, candles):
    """Cá Voi Volume (🐳): Phân tích Khối lượng & VSA (Relative Volume, Volume Delta 10 nến, Climax/Absorption, Fakeout)."""
    vr = float(ind.get("vol_ratio") or 1.0)
    vr3 = float(ind.get("vol_ratio_3") or 1.0)
    vdelta = float(ind.get("vol_delta_ratio") or 0.0)
    vsa = str(ind.get("vsa_signal") or "NORMAL")
    info = {
        "vol_current": ind.get("vol_current", 0.0),
        "vol_ma20": ind.get("vol_ma20", 0.0),
        "vol_ratio": vr,
        "vol_ratio_3": vr3,
        "vol_delta_ratio": vdelta,
        "vsa_signal": vsa,
        "fakeout_warning": vsa in ("WEAK_BREAKOUT_UP", "WEAK_BREAKOUT_DOWN"),
    }
    head = "RVOL %.2f× TB20 (3 nến %.2f×), Delta dòng tiền %+.0f%%, VSA=%s" % (vr, vr3, vdelta * 100, vsa)
    if vsa == "ABSORPTION_BULL":
        return "BUY", "%s → Cao trào hấp thụ cầu dưới đáy (Stopping Volume rút chân mạnh), cá voi gom hàng → BUY." % head, info
    if vsa == "ABSORPTION_BEAR":
        return "SELL", "%s → Cao trào hấp thụ cung trên đỉnh (Upthrust rút đầu mạnh), cá voi xả hàng → SELL." % head, info
    if vsa == "HIGH_VOL_BULL":
        return "BUY", "%s → Nến tăng thân rộng kèm Volume bùng nổ xác nhận dòng tiền mua chủ động → BUY." % head, info
    if vsa == "HIGH_VOL_BEAR":
        return "SELL", "%s → Nến giảm thân rộng kèm Volume bùng nổ xác nhận dòng tiền bán chủ động → SELL." % head, info
    if vsa in ("WEAK_BREAKOUT_UP", "WEAK_BREAKOUT_DOWN"):
        return "WAIT", "%s → Phá vỡ cấu trúc nhưng cạn Volume (No Demand/Supply) → cảnh báo bẫy Fakeout, WAIT." % head, info
    if vsa == "EFFORT_NO_RESULT":
        return "WAIT", "%s → Volume đột biến nhưng thân nến hẹp (Nỗ lực không thành kết quả) → đang giằng co hấp thụ, WAIT." % head, info
    if vr < 0.65 and vr3 < 0.75:
        return "WAIT", "%s → Thanh khoản thị trường đang cạn kiệt, dễ trượt giá hoặc quét râu → WAIT." % head, info
    if vr3 >= 1.15 and vdelta >= 0.16 and ind["price"] >= ind["vwap"]:
        return "BUY", "%s → Dòng tiền 10 nến nghiêng hẳn về phe Mua và giữ trên VWAP → BUY." % head, info
    if vr3 >= 1.15 and vdelta <= -0.16 and ind["price"] <= ind["vwap"]:
        return "SELL", "%s → Dòng tiền 10 nến nghiêng hẳn về phe Bán và nằm dưới VWAP → SELL." % head, info
    if vdelta >= 0.24 and ind["structure"] == "UPTREND":
        return "BUY", "%s → Lực mua chủ động áp đảo (+%.0f%%) đồng pha xu hướng tăng → BUY." % (head, vdelta * 100), info
    if vdelta <= -0.24 and ind["structure"] == "DOWNTREND":
        return "SELL", "%s → Lực bán chủ động áp đảo (%.0f%%) đồng pha xu hướng giảm → SELL." % (head, vdelta * 100), info
    return "WAIT", "%s → Chưa thấy dòng tiền đột biến hay tín hiệu VSA rõ rệt → WAIT." % head, info


# ---- 4 agent mở rộng: Khung lớn, Trạng thái thị trường, Mức giá & phiên, Cá Voi Volume ----
BROKER_OFFSET_FILE = os.path.join(DATA_DIR, "broker_utc_offset.json")
BROKER_OFFSET = {}          # {asset: {"off": int, "ts": epoch lần cuối xác nhận}}
BROKER_OFFSET_LOCK = threading.Lock()
_BROKER_OFFSET_WARNED = set()


def load_broker_offsets():
    try:
        with open(BROKER_OFFSET_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    with BROKER_OFFSET_LOCK:
        for a, v in (raw or {}).items():
            try:
                off = int(v.get("off"))
            except Exception:
                continue
            if a in ASSETS and -12 <= off <= 14:
                BROKER_OFFSET[a] = {"off": off, "ts": float(v.get("ts") or 0)}


def _remember_broker_offset(asset, off):
    now = time.time()
    with BROKER_OFFSET_LOCK:
        old = BROKER_OFFSET.get(asset)
        BROKER_OFFSET[asset] = {"off": off, "ts": now}
        # chỉ ghi đĩa khi offset đổi (đổi giờ mùa hè/đông) hoặc mỗi giờ một lần
        dirty = not old or old["off"] != off or now - old["ts"] > 3600
        snap = dict(BROKER_OFFSET) if dirty else None
    if old and old["off"] != off:
        log("level_mapper", "🕒 Lệch giờ broker %s đổi từ UTC%+d sang UTC%+d." % (asset, old["off"], off), room="ta_room")
    if snap is not None:
        try:
            tmp = BROKER_OFFSET_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f)
            os.replace(tmp, BROKER_OFFSET_FILE)
        except Exception as e:
            print("save broker offset:", e)


def broker_utc_offset(asset):
    """Giờ nến MT5 là giờ server broker. Ước lượng lệch so với UTC (giờ) từ nến M5/M15 mới nhất.
    Feed cũ/không đo được -> trả offset hợp lệ gần nhất (nhớ cả qua restart, lưu ở data/).
    Chưa từng đo được -> trả None (KHÔNG âm thầm coi là UTC+0); người gọi tự quyết định."""
    with MT5_LOCK:
        feeds = [(MT5_FEED.get((asset, tf)), TF_SECONDS[tf]) for tf in ("5m", "15m")]
    for f, sec in feeds:
        if not f or not f.get("candles") or time.time() - f["ts"] > 600:
            continue
        diff = f["candles"][-1]["t"] + sec / 2.0 - f["ts"]
        off = int(round(diff / 3600.0))
        if -12 <= off <= 14 and abs(diff - off * 3600) <= sec / 2.0 + 120:
            _remember_broker_offset(asset, off)
            return off
    with BROKER_OFFSET_LOCK:
        last = BROKER_OFFSET.get(asset)
    return last["off"] if last else None


def broker_offset_or_utc(asset, who=""):
    """Dùng cho chỉ báo/hiển thị khi vẫn phải tính tiếp: chưa biết offset thì tạm coi UTC nhưng CẢNH BÁO 1 lần."""
    off = broker_utc_offset(asset)
    if off is not None:
        _BROKER_OFFSET_WARNED.discard(asset)
        return off
    if asset not in _BROKER_OFFSET_WARNED:
        _BROKER_OFFSET_WARNED.add(asset)
        log("level_mapper", "⚠️ Chưa đo được lệch giờ broker %s (feed M5/M15 cũ) → tạm coi giờ nến là UTC%s." % (
            asset, " cho " + who if who else ""), room="ta_room")
    return 0


load_broker_offsets()


def htf_trend(asset, tf):
    """Xu hướng 1 khung lớn: EMA50/200 + cấu trúc 2 đỉnh / 2 đáy fractal gần nhất."""
    data, candles = market_full(asset, tf)
    ind = data["indicators"]
    price, e50, e200 = ind["price"], ind["ema50"], ind["ema200"]
    ema_pt = 1 if (e50 > e200 and price > e50) else (-1 if (e50 < e200 and price < e50) else 0)
    highs, lows = swing_points(candles[-120:])
    if len(highs) >= 2 and len(lows) >= 2:
        hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
        structure = "HH_HL" if hh and hl else ("LH_LL" if not hh and not hl else "MIXED")
    else:
        structure = "UNCLEAR"
    st_pt = 1 if structure == "HH_HL" else (-1 if structure == "LH_LL" else 0)
    if ema_pt + st_pt >= 1 and min(ema_pt, st_pt) >= 0:
        bias = "UP"
    elif ema_pt + st_pt <= -1 and max(ema_pt, st_pt) <= 0:
        bias = "DOWN"
    else:
        bias = "FLAT"
    return {"tf": tf, "bias": bias, "price": price, "ema50": e50, "ema200": e200, "structure": structure,
            "last_high": highs[-1] if highs else None, "last_low": lows[-1] if lows else None,
            "bars": len(candles), "source": data["source"]}


def vote_htf(asset):
    """Ưng Khung Lớn: BUY/SELL theo H1 + H4. veto = hướng lệnh bị cấm vì ngược cả H1 lẫn H4."""
    info = {"h1": None, "h4": None, "veto": None, "errors": []}
    for tf, key in (("1h", "h1"), ("4h", "h4")):
        try:
            info[key] = htf_trend(asset, tf)
        except Exception as e:
            info["errors"].append("%s: %s" % (tf, str(e)[:140]))
    h1, h4 = info["h1"], info["h4"]
    if not h1 or not h4:
        return "WAIT", "Thiếu nến %s → không đánh giá được khung lớn, WAIT và không veto." % (
            "/".join(t for t, k in (("H1", "h1"), ("H4", "h4")) if not info[k])), info
    name = {"UP": "tăng", "DOWN": "giảm", "FLAT": "đi ngang"}
    desc = "H1 %s (EMA50 %.2f / EMA200 %.2f, %s) · H4 %s (EMA50 %.2f / EMA200 %.2f, %s)" % (
        name[h1["bias"]], h1["ema50"], h1["ema200"], h1["structure"],
        name[h4["bias"]], h4["ema50"], h4["ema200"], h4["structure"])
    b1, b4 = h1["bias"], h4["bias"]
    if b1 == b4 == "UP":
        info["veto"] = "SELL"
        return "BUY", "%s → cả hai khung lớn tăng, ưu tiên BUY, cấm SELL ngược xu hướng." % desc, info
    if b1 == b4 == "DOWN":
        info["veto"] = "BUY"
        return "SELL", "%s → cả hai khung lớn giảm, ưu tiên SELL, cấm BUY ngược xu hướng." % desc, info
    if b4 != "FLAT" and b1 == "FLAT":
        v = "BUY" if b4 == "UP" else "SELL"
        return v, "%s → H4 dẫn hướng, H1 đang tích luỹ → nghiêng %s." % (desc, v), info
    if b4 == "FLAT" and b1 != "FLAT":
        return "WAIT", "%s → chỉ H1 có hướng, H4 đi ngang → chưa đủ xác nhận." % desc, info
    if b1 == b4 == "FLAT":
        return "WAIT", "%s → khung lớn không có xu hướng rõ." % desc, info
    return "WAIT", "%s → H1 ngược H4, đang là nhịp điều chỉnh → WAIT." % desc, info


def spread_stats(asset):
    stale = float(CONFIG.get("bridge_stale_sec") or 90)
    with MT5_LOCK:
        hist = sorted(SPREAD_HIST.get(asset, ()))
        t = MT5_TICK.get(asset)
    cur = t["spread"] if t and time.time() - t["ts"] < stale else None
    med = hist[len(hist) // 2] if hist else None
    return cur, med, len(hist)


def vote_regime(asset, ind):
    """Mèo Đo Nhịp: regime trend / range / high_vol từ ADX, độ rộng Bollinger, ATR; chặn khi spread hoặc biến động bất thường."""
    adx14, bbp, ratio = ind.get("adx14", 0.0), ind.get("bb_width_pct", 50.0), ind.get("atr_ratio", 1.0)
    if ratio >= 1.8 or (bbp >= 95 and ratio >= 1.4):
        regime = "high_vol"
    elif adx14 >= 25:
        regime = "trend"
    else:
        regime = "range"
    reasons = []
    cur, med, n = spread_stats(asset)
    if cur is not None and med and n >= 12 and cur > 2 * med:
        reasons.append("spread %s > 2× median %s" % ("{:g}".format(cur), "{:g}".format(med)))
    if ratio >= 2.5:
        reasons.append("ATR gấp %.1f lần trung bình" % ratio)
    if ind.get("last_range_atr", 0) >= 3.0:
        reasons.append("nến hiện tại dài %.1f×ATR" % ind["last_range_atr"])
    info = {"regime": regime, "adx14": round(adx14, 1), "plus_di": round(ind.get("plus_di", 0), 1),
            "minus_di": round(ind.get("minus_di", 0), 1), "bb_width_pct": round(bbp, 1), "atr_ratio": round(ratio, 2),
            "spread": cur, "spread_median": med, "spread_samples": n, "blocked": bool(reasons), "block_reasons": reasons}
    head = "ADX %.1f (DI+ %.1f / DI- %.1f), độ rộng BB ở percentile %.0f, ATR %.2f× TB" % (
        adx14, info["plus_di"], info["minus_di"], bbp, ratio)
    if reasons:
        return "WAIT", "%s → CHẶN vào lệnh: %s." % (head, "; ".join(reasons)), info
    if regime == "high_vol":
        return "WAIT", "%s → biến động cao, SL dễ bị quét → WAIT." % head, info
    if regime == "trend":
        v = "BUY" if ind.get("plus_di", 0) > ind.get("minus_di", 0) else "SELL"
        return v, "%s → thị trường CÓ XU HƯỚNG, %s đang trội → %s." % (head, "DI+" if v == "BUY" else "DI-", v), info
    up, lo = ind.get("bb_upper"), ind.get("bb_lower")
    pb = (ind["price"] - lo) / (up - lo) if up and lo and up > lo else 0.5
    info["percent_b"] = round(pb, 2)
    if pb <= 0.15:
        return "BUY", "%s → ĐI NGANG, giá sát biên dưới Bollinger (%%B %.2f) → mua hồi về giữa dải." % (head, pb), info
    if pb >= 0.85:
        return "SELL", "%s → ĐI NGANG, giá sát biên trên Bollinger (%%B %.2f) → bán hồi về giữa dải." % (head, pb), info
    return "WAIT", "%s → ĐI NGANG, giá giữa dải Bollinger (%%B %.2f) → WAIT." % (head, pb), info


ROUND_STEPS = {"XAUUSD": ((50, True), (10, False)), "BTCUSDT": ((1000, True),)}
SESSIONS_UTC = ((0, 7, "Á"), (7, 12, "London"), (12, 16, "London + New York"), (16, 21, "New York"), (21, 24, "Chuyển phiên"))


def current_session(ts=None):
    h = datetime.fromtimestamp(ts or time.time(), timezone.utc).hour
    for a, b, name in SESSIONS_UTC:
        if a <= h < b:
            return name, h
    return "?", h


def price_levels(asset, ind, candles):
    """Đỉnh/đáy/mở cửa ngày trước & hôm nay (theo giờ nến MT5), vùng phiên Á (UTC), số tròn.
    major=True: mức mạnh, dùng cho luật "giá kẹt giữa hai mức"; mọi mức đều dùng để soi phản ứng giá."""
    off = broker_offset_or_utc(asset, "mức giá phiên Á")
    days = sorted(set(c["t"] // 86400 for c in candles))
    cur_day = days[-1]
    prev_days = [d for d in days if d < cur_day]
    levels = []
    if prev_days:
        prev = [c for c in candles if c["t"] // 86400 == prev_days[-1]]
        levels += [("Đỉnh ngày trước", max(c["h"] for c in prev), True), ("Đáy ngày trước", min(c["l"] for c in prev), True),
                   ("Mở cửa ngày trước", prev[0]["o"], False)]
    today = [c for c in candles if c["t"] // 86400 == cur_day]
    levels.append(("Mở cửa hôm nay", today[0]["o"], False))      # giá mở cửa: chỉ xét phản ứng, không tính "kẹt"
    now = time.time()
    utc_day = now - now % 86400
    asia = [c for c in candles if utc_day <= c["t"] - off * 3600 < utc_day + 7 * 3600]
    asia_info = None
    if asia:
        asia_info = {"high": max(c["h"] for c in asia), "low": min(c["l"] for c in asia), "bars": len(asia),
                     "done": now >= utc_day + 7 * 3600}
        levels += [("Đỉnh phiên Á", asia_info["high"], True), ("Đáy phiên Á", asia_info["low"], True)]
    p = ind["price"]
    for step, major in ROUND_STEPS.get(asset, ()):
        lo = math.floor(p / step) * step
        levels += [("Số tròn", lo, major), ("Số tròn", lo + step, major)]
    # gộp các mức sát nhau (< 0.2 ATR)
    a = ind["atr14"] or 1e-9
    merged = []
    for name, price, major in sorted(levels, key=lambda x: x[1]):
        if merged and price - merged[-1]["price"] < 0.2 * a:
            m = merged[-1]
            if name not in m["name"]:
                m["name"] += " + " + name
            m["major"] = m["major"] or major
        else:
            merged.append({"name": name, "price": price, "major": major})
    return merged, asia_info, off


def vote_levels(asset, ind, main_candles):
    """Cáo Mốc Giá: bỏ phiếu khi giá phản ứng tại mức, WAIT khi giá kẹt giữa hai mức gần nhau."""
    try:
        _, h1 = market_full(asset, "1h")
        src = "H1"
    except Exception:
        h1, src = main_candles, "khung chính"
    levels, asia, off = price_levels(asset, ind, h1)
    p, a = ind["price"], ind["atr14"] or 1e-9
    vr = ind.get("vol_ratio", 1.0)
    session, hour = current_session()
    d = ASSETS[asset]["decimals"]
    sup = max((l for l in levels if l["price"] <= p), key=lambda l: l["price"], default=None)
    res = min((l for l in levels if l["price"] > p), key=lambda l: l["price"], default=None)
    msup = max((l for l in levels if l["major"] and l["price"] <= p), key=lambda l: l["price"], default=None)
    mres = min((l for l in levels if l["major"] and l["price"] > p), key=lambda l: l["price"], default=None)
    near = min(levels, key=lambda l: abs(l["price"] - p))
    info = {"session": session, "utc_hour": hour, "broker_utc_offset": off, "source": src, "asia": asia,
            "levels": [dict(l, price=round(l["price"], d), dist_atr=round((l["price"] - p) / a, 2)) for l in levels],
            "support": round(sup["price"], d) if sup else None, "support_name": sup["name"] if sup else "",
            "resistance": round(res["price"], d) if res else None, "resistance_name": res["name"],
            "nearest": near["name"], "nearest_dist_atr": round(abs(near["price"] - p) / a, 2), "reaction": "NONE"} if res else {
            "session": session, "utc_hour": hour, "broker_utc_offset": off, "source": src, "asia": asia,
            "levels": [dict(l, price=round(l["price"], d), dist_atr=round((l["price"] - p) / a, 2)) for l in levels],
            "support": round(sup["price"], d) if sup else None, "support_name": sup["name"] if sup else "",
            "resistance": None, "resistance_name": "",
            "nearest": near["name"], "nearest_dist_atr": round(abs(near["price"] - p) / a, 2), "reaction": "NONE"}
    head = "Phiên %s (%02dh UTC). Mức gần nhất: %s %.*f (cách %.1f ATR)" % (
        session, hour, near["name"], d, near["price"], info["nearest_dist_atr"])
    if msup and mres and (mres["price"] - msup["price"]) < 3 * a:
        info["reaction"] = "SQUEEZE"
        return "WAIT", "%s. Giá kẹt giữa %s %.*f và %s %.*f (chỉ %.1f ATR) → không đủ chỗ cho SL/TP, WAIT." % (
            head, msup["name"], d, msup["price"], mres["name"], d, mres["price"], (mres["price"] - msup["price"]) / a), info
    recent = main_candles[-3:]
    last = main_candles[-1]
    low3, high3 = min(c["l"] for c in recent), max(c["h"] for c in recent)
    # phá vỡ trước: đóng cửa 3 nến trước còn ở phía bên kia mức thì không phải "bật lại"
    if len(main_candles) >= 3:
        c0 = main_candles[-3]["c"]
        for l in levels:
            if c0 < l["price"] < p - 0.15 * a and last["l"] > l["price"] - 0.1 * a:
                info["reaction"] = "BREAKOUT_UP"
                if (session in ("Á", "Chuyển phiên") and asset == "XAUUSD") or vr < 0.75:
                    return "WAIT", "%s. Giá vượt %s %.*f nhưng thanh khoản mỏng (phiên %s, RVOL %.2f×) → dễ là phá vỡ giả, WAIT." % (head, l["name"], d, l["price"], session, vr), info
                return "BUY", "%s. Giá phá lên và giữ trên %s %.*f (RVOL %.2f×) → mức cũ thành hỗ trợ, BUY." % (head, l["name"], d, l["price"], vr), info
            if p + 0.15 * a < l["price"] < c0 and last["h"] < l["price"] + 0.1 * a:
                info["reaction"] = "BREAKOUT_DOWN"
                if (session in ("Á", "Chuyển phiên") and asset == "XAUUSD") or vr < 0.75:
                    return "WAIT", "%s. Giá thủng %s %.*f nhưng thanh khoản mỏng (phiên %s, RVOL %.2f×) → dễ là phá vỡ giả, WAIT." % (head, l["name"], d, l["price"], session, vr), info
                return "SELL", "%s. Giá thủng và nằm dưới %s %.*f (RVOL %.2f×) → mức cũ thành kháng cự, SELL." % (head, l["name"], d, l["price"], vr), info
    if sup and p - sup["price"] <= 0.8 * a and low3 <= sup["price"] + 0.15 * a and p >= sup["price"] + 0.1 * a and last["c"] >= last["o"]:
        info["reaction"] = "BOUNCE_SUPPORT"
        return "BUY", "%s. Giá thử %s %.*f rồi bật lên, nến đóng xanh → phản ứng mua tại hỗ trợ." % (head, sup["name"], d, sup["price"]), info
    if res and res["price"] - p <= 0.8 * a and high3 >= res["price"] - 0.15 * a and p <= res["price"] - 0.1 * a and last["c"] <= last["o"]:
        info["reaction"] = "REJECT_RESISTANCE"
        return "SELL", "%s. Giá chạm %s %.*f rồi bị đạp xuống, nến đóng đỏ → phản ứng bán tại kháng cự." % (head, res["name"], d, res["price"]), info
    return "WAIT", "%s. Hỗ trợ %s, kháng cự %s, giá chưa phản ứng tại mức nào → WAIT." % (
        head, ("%s %.*f" % (sup["name"], d, sup["price"])) if sup else "—", ("%s %.*f" % (res["name"], d, res["price"])) if res else "—"), info


def safe_vote(aid, fn, *args):
    """Agent lỗi thì bỏ phiếu WAIT thay vì làm hỏng cả phiên họp."""
    try:
        return fn(*args)
    except Exception as e:
        traceback.print_exc()
        return "WAIT", "Lỗi khi tính: %s → WAIT." % str(e)[:160], {"error": str(e)[:200]}


# ---- Trọng số & ngưỡng đồng thuận ----
BASE_WEIGHTS = {"vwap_hunter": 1.0, "smc_sniper": 1.2, "trend_radar": 1.0,
                "htf_scout": 1.2, "regime_meter": 0.8, "level_mapper": 1.0, "volume_whale": 1.1}
REGIME_MULT = {
    "trend": {"vwap_hunter": 1.2, "trend_radar": 1.3, "htf_scout": 1.3, "smc_sniper": 0.9, "level_mapper": 0.9, "volume_whale": 1.2},
    "range": {"smc_sniper": 1.3, "level_mapper": 1.4, "trend_radar": 0.6, "vwap_hunter": 0.9, "htf_scout": 0.8, "volume_whale": 1.1},
    "high_vol": {"volume_whale": 1.3},
}


def agent_weights(regime=None):
    factors = agent_weight_factors() if CONFIG.get("agent_auto_weight", True) else {}
    return {aid: round(w * REGIME_MULT.get(regime, {}).get(aid, 1.0) * factors.get(aid, 1.0), 3)
            for aid, w in BASE_WEIGHTS.items()}


def ta_guards(action, ta):
    """Lý do bắt buộc WAIT: veto khung lớn, cờ chặn của Mèo Đo Nhịp, hoặc cảnh báo Fakeout cạn Volume."""
    if action not in ("BUY", "SELL") or not ta:
        return []
    out = []
    htf = ta.get("htf") or {}
    if htf.get("veto") == action:
        out.append("Ưng Khung Lớn veto %s vì ngược xu hướng cả H1 lẫn H4" % action)
    reg = ta.get("regime") or {}
    if reg.get("blocked"):
        out.append("Mèo Đo Nhịp chặn: %s" % "; ".join(reg.get("block_reasons") or []))
    vol = ta.get("volume") or {}
    if action == "BUY" and vol.get("vsa_signal") == "WEAK_BREAKOUT_UP":
        out.append("Cá Voi Volume chặn BUY: phá đỉnh nhưng Volume yếu (RVOL %.2f× < 0.85×), nguy cơ bẫy Bull Trap" % float(vol.get("vol_ratio") or 0))
    elif action == "SELL" and vol.get("vsa_signal") == "WEAK_BREAKOUT_DOWN":
        out.append("Cá Voi Volume chặn SELL: phá đáy nhưng Volume yếu (RVOL %.2f× < 0.85×), nguy cơ bẫy Bear Trap" % float(vol.get("vol_ratio") or 0))
    return out


def enforce_guards(decision, ta):
    reasons = ta_guards(decision.get("action"), ta)
    if not reasons:
        return decision
    d = dict(decision)
    d["summary"] = "%s ⛔ Ép WAIT (đề xuất gốc %s %d%%): %s." % (
        d.get("summary", ""), d["action"], int(d.get("confidence") or 0), " | ".join(reasons))
    d["action"] = "WAIT"
    d["confidence"] = min(int(d.get("confidence") or 50), 60)
    d["guards"] = reasons
    return d


def consensus(votes, regime=None, loss_streak=0):
    """Điểm có trọng số: Σ w·(+1 BUY / -1 SELL / 0 WAIT), chia cho tổng trọng số các agent đã bỏ phiếu."""
    w = agent_weights(regime)
    score = sum(w.get(aid, 1.0) * (1 if v == "BUY" else -1 if v == "SELL" else 0) for aid, (v, _) in votes.items())
    total = sum(w.get(aid, 1.0) for aid in votes) or 1.0
    th = float(CONFIG.get("quant_consensus") or 0.4)
    if regime == "high_vol":
        th += 0.1
    if loss_streak >= 2:
        th += min(0.15, 0.05 * (loss_streak - 1))  # Chuỗi thua liên tiếp -> tự động siết ngưỡng đồng thuận chặt hơn
    ratio = score / total
    action = "BUY" if ratio >= th else ("SELL" if ratio <= -th else "WAIT")
    return {"score": round(score, 3), "total_weight": round(total, 3), "ratio": round(ratio, 3), "threshold": round(th, 3),
            "action": action, "weights": {aid: w.get(aid, 1.0) for aid in votes}, "regime": regime, "loss_streak": loss_streak}


def quant_decision(asset, ind, votes, news_titles, skill_text, sentiment=0, ta=None):
    """Built-in Quant AI: không cần API Key. sentiment: điểm tin Telegram (-N..+N).
    ta: ngữ cảnh 4 agent mở rộng {"htf", "regime", "levels", "volume"} + lịch sử SL/TP."""
    ta = ta or {}
    regime = (ta.get("regime") or {}).get("regime")
    mem = ta.get("memory") or {}
    loss_streak = int(mem.get("loss_streak") or 0)
    cs = consensus(votes, regime, loss_streak=loss_streak)
    action, ratio = cs["action"], cs["ratio"]
    buy_n = sum(1 for v, _ in votes.values() if v == "BUY")
    sell_n = sum(1 for v, _ in votes.values() if v == "SELL")
    conf = 50 + int(min(abs(ratio), 0.8) / 0.8 * 35)
    # Thưởng/phạt theo RSI, ATR, Volume & lịch sử SL/TP
    if action == "BUY" and ind["rsi14"] > 70:
        conf -= 8
    if action == "SELL" and ind["rsi14"] < 30:
        conf -= 8
    atr_pct = ind["atr14"] / ind["price"] * 100
    if atr_pct > 1.5:
        conf -= 5
    vr = float(ind.get("vol_ratio") or 1.0)
    if action != "WAIT":
        if vr >= 1.25:
            conf += 4
        elif vr < 0.7:
            conf -= 6
    if loss_streak >= 2 and action != "WAIT":
        conf -= min(10, 3 * loss_streak)
    if sentiment and action != "WAIT":
        aligned = (sentiment > 0 and action == "BUY") or (sentiment < 0 and action == "SELL")
        conf += 5 if aligned else -7
    conf = max(50, min(95, conf))
    bull_pts = [m for v, m in votes.values() if v == "BUY"]
    bear_pts = [m for v, m in votes.values() if v == "SELL"]
    bull = " ".join(bull_pts) if bull_pts else "Phe Mua chưa có luận điểm mạnh: giá %.2f chưa cho tín hiệu đồng thuận trên VWAP/EMA/Volume." % ind["price"]
    bear = " ".join(bear_pts) if bear_pts else "Phe Bán chưa có luận điểm mạnh: chưa thấy BOS giảm hay sweep đỉnh quanh %.2f." % ind["swing_high"]
    summary = ("Trưởng nhóm tổng hợp %d phiếu BUY / %d phiếu SELL / %d phiếu. Điểm có trọng số %+.2f / %.2f = %+.0f%% (ngưỡng ±%.0f%%%s). "
               "Cấu trúc %s, giá ở vùng %s, RSI %.1f, ATR %.2f (%.2f%%), RVOL %.2f× (%s). Quyết định: %s với độ tự tin %d%%." % (
                   buy_n, sell_n, len(votes), cs["score"], cs["total_weight"], ratio * 100, cs["threshold"] * 100,
                   ", thị trường %s" % regime if regime else "", ind["structure"], ind["vwap_zone"],
                   ind["rsi14"], ind["atr14"], atr_pct, vr, ind.get("vsa_signal", "NORMAL"), action, conf))
    if loss_streak >= 2:
        summary += " ⚠️ Bộ nhớ thực chiến ghi nhận chuỗi %d lệnh SL gần nhất → đã nâng ngưỡng đồng thuận lên ±%.0f%%." % (loss_streak, cs["threshold"] * 100)
    if news_titles:
        summary += " Tin vĩ mô đáng chú ý: \"%s\"." % news_titles[0][:90]
    if sentiment:
        summary += " Cảm tính tin Telegram: %s (%+d)." % ("nghiêng Bull" if sentiment > 0 else "nghiêng Bear", sentiment)
    lesson = ("[%s %s%s] %s | RVOL %.2f× (%s) | Phiếu: %s | Kỷ luật: chỉ vào lệnh khi điểm đồng thuận ≥ ngưỡng, có Volume xác nhận, không ngược H1+H4." % (
                  asset, ind["structure"], "/" + regime if regime else "", action, vr, ind.get("vsa_signal", "NORMAL"),
                  ", ".join("%s=%s" % (VOTE_LABELS.get(aid, aid), v) for aid, (v, _) in votes.items())))
    decision = {"action": action, "confidence": conf, "bull_argument": bull, "bear_argument": bear,
                "summary": summary, "lesson_learned": lesson}
    return enforce_guards(decision, ta)


def refresh_ticker_for_plan(asset, ind, analysis_ticker):
    """Lấy lại tick MT5 mới nhất ngay trước khi tính entry/SL/TP (cuộc họp kéo dài vài chục giây, giá đã chạy).
    Trả (ticker dùng cho risk_plan, ghi chú cảnh báo hoặc "")."""
    stale = float(CONFIG.get("bridge_stale_sec") or 90)
    with MT5_LOCK:
        t = MT5_TICK.get(asset)
        t = dict(t) if t else None
    if not t or time.time() - t["ts"] >= stale:
        if CONFIG.get("price_source", "mt5_only") == "mt5_only":
            return analysis_ticker, "⚠️ Không lấy lại được tick MT5 mới (quá %ds) → entry/SL/TP theo giá lúc phân tích." % stale
        return analysis_ticker, ""
    live = dict(analysis_ticker or {})
    live.update({"price": t["last"], "bid": t["bid"], "ask": t["ask"], "spread": t["spread"]})
    ref = float(ind.get("price") or (analysis_ticker or {}).get("price") or 0.0)
    a = float(ind.get("atr14") or 0.0)
    drift = t["last"] - ref
    if ref > 0 and a > 0 and abs(drift) > 0.5 * a:
        d = ASSETS[asset]["decimals"]
        return live, "⚠️ Giá đã chạy %+.*f (%.2f×ATR) từ lúc phân tích (%.*f → %.*f): kèo có thể đã trễ, cân nhắc chờ hồi." % (
            d, drift, abs(drift) / a, d, ref, d, t["last"])
    return live, ""


def risk_plan(asset, action, ind, cfg, ticker=None):
    """Robot Quản Trị Vốn: SL = 1.5×ATR, TP1 = 1.8R, TP2 = 2.6R, Lot theo % rủi ro.
    Có bid/ask từ MT5 thì entry BUY = ask, SELL = bid (đúng giá khớp lệnh market)."""
    price = ind["price"]
    if ticker and ticker.get("bid") and ticker.get("ask"):
        price = ticker["ask"] if action == "BUY" else (ticker["bid"] if action == "SELL" else price)
    a = ind["atr14"]
    sl_dist = 1.5 * a
    balance = float(cfg.get("account_balance") or 10000)
    real_bal = mt5_balance() if cfg.get("use_mt5_balance", True) else None
    if real_bal:
        balance = real_bal
    risk_pct = float(cfg.get("risk_per_trade_pct") or 1.0)
    risk_amt = balance * risk_pct / 100.0
    contract = ASSETS[asset]["contract"]
    if action == "BUY":
        sl, tp1, tp2 = price - sl_dist, price + 1.8 * sl_dist, price + 2.6 * sl_dist
    elif action == "SELL":
        sl, tp1, tp2 = price + sl_dist, price - 1.8 * sl_dist, price - 2.6 * sl_dist
    else:
        sl, tp1, tp2 = price - sl_dist, price + 1.8 * sl_dist, price + 2.6 * sl_dist
    lot = risk_amt / (sl_dist * contract) if sl_dist > 0 else 0.0
    lot = math.floor(lot * 1000) / 1000.0
    note = ("Rủi ro %.1f%% của %s $%s = $%.2f. SL cách entry %.2f (1.5×ATR %.2f). "
            "Khối lượng %.3f lot (1 lot = %s %s). TP1 R:R 1:1.8, TP2 R:R 1:2.6. %s" % (
                risk_pct, "số dư MT5" if real_bal else "quỹ", "{:,.0f}".format(balance), risk_amt, sl_dist, a, lot, "{:g}".format(contract),
                ASSETS[asset]["unit"],
                "WAIT → không vào lệnh, chỉ lưu kế hoạch tham khảo." if action == "WAIT" else "Đã duyệt."))
    d = ASSETS[asset]["decimals"]
    return {"entry": round(price, d), "stop_loss": round(sl, d), "take_profit_1": round(tp1, d),
            "take_profit_2": round(tp2, d), "rr1": 1.8, "rr2": 2.6, "lot_size": lot,
            "risk_amount": round(risk_amt, 2), "sl_distance": round(sl_dist, d), "risk_note": note}


# ---- Chấm điểm agent & Lịch sử chạm SL/TP của các lệnh đã vào ----
SCORE_MIN_VOTES = 5
SCORE_CACHE = {"ts": 0, "data": None}
SCORE_LOCK = threading.Lock()


def db_outcomes():
    with DB_LOCK:
        conn = db_conn()
        rows = conn.execute("SELECT * FROM signal_outcomes").fetchall()
        conn.close()
    return {r["signal_id"]: dict(r) for r in rows}


def db_set_outcome(signal_id, outcome, source, detail="", exit_reason="", close_price=0.0, close_time="", net_profit=0.0, trigger_hooks=True):
    """Ghi kết quả kèo. Không ghi đè cờ lesson_logged/telegram_alerted (chỉ đổi bằng UPDATE ... WHERE cờ=0)."""
    sid = int(signal_id)
    new_reason = str(exit_reason or "")[:32]
    with DB_LOCK:
        conn = db_conn()
        old = conn.execute("SELECT exit_reason FROM signal_outcomes WHERE signal_id=?", (sid,)).fetchone()
        prev_reason = str(old["exit_reason"] or "") if old else ""
        conn.execute("INSERT OR IGNORE INTO signal_outcomes (signal_id, outcome) VALUES (?, ?)", (sid, outcome))
        conn.execute("""UPDATE signal_outcomes SET outcome=?, source=?, detail=?, evaluated_at=?, exit_reason=?,
                        close_price=?, close_time=?, net_profit=? WHERE signal_id=?""",
                     (outcome, source, str(detail or "")[:300], now_iso(), new_reason, float(close_price or 0.0),
                      str(close_time or "")[:32], float(net_profit or 0.0), sid))
        # Nếu trạng thái nâng cấp từ TP1 (đang chạy) sang TP1+TP2 hoặc TP1+BE hoàn tất thì cho phép bắn thông báo cập nhật thêm 1 lần
        if prev_reason and prev_reason != new_reason and ("còn" in prev_reason or prev_reason == "TP1") and new_reason in ("TP1+TP2", "TP1+BE", "TP2"):
            conn.execute("UPDATE signal_outcomes SET telegram_alerted=0 WHERE signal_id=?", (sid,))
        conn.commit()
        conn.close()
    if trigger_hooks and outcome in ("win", "loss"):
        try:
            on_signal_outcome_recorded(sid)
        except Exception as e:
            print("on_signal_outcome_recorded error:", e)


def signal_has_real_execution(conn, signal_id):
    return conn.execute("""SELECT 1 FROM executions WHERE signal_id=? AND dry_run=0 AND ticket>0
                           AND (error IS NULL OR error='') LIMIT 1""", (int(signal_id),)).fetchone() is not None


def _claim_outcome_flag(sid, flag):
    """Đặt cờ 0 -> 1 nguyên tử. True = luồng này giành được quyền xử lý (ghi bài học / gửi Telegram)."""
    with DB_LOCK:
        conn = db_conn()
        cur = conn.execute("UPDATE signal_outcomes SET %s=1 WHERE signal_id=? AND %s=0" % (flag, flag), (sid,))
        conn.commit()
        n = cur.rowcount
        conn.close()
    return n == 1


def _release_outcome_flag(sid, flag):
    with DB_LOCK:
        conn = db_conn()
        conn.execute("UPDATE signal_outcomes SET %s=0 WHERE signal_id=?" % flag, (sid,))
        conn.commit()
        conn.close()


def on_signal_outcome_recorded(signal_id):
    """Khi 1 kèo chạm SL hoặc TP:
    1) Kèo có lệnh khớp thật hoặc đã gửi Telegram: phân tích hậu kiểm và ghi vào bộ não SKILL.md.
    2) Kèo đã gửi Telegram (telegram_sent=1): bắn thông báo kèm ảnh biểu đồ kết quả sang Telegram."""
    sid = int(signal_id)
    with DB_LOCK:
        conn = db_conn()
        oc_row = conn.execute("SELECT * FROM signal_outcomes WHERE signal_id=?", (sid,)).fetchone()
        real_ex = signal_has_real_execution(conn, sid)
        conn.close()
    if not oc_row:
        return
    oc = dict(oc_row)
    if oc.get("outcome") not in ("win", "loss"):
        return
    sig = db_get_signal(sid)
    if not sig:
        return
    tg_sent = bool(int(sig.get("telegram_sent") or 0))
    if not (real_ex or tg_sent):
        return          # kèo chỉ nằm trên dashboard: không học, không báo

    # 1. Tự học hậu kiểm vào SKILL.md (chỉ ghi 1 lần khi kèo có kết quả)
    if not int(oc.get("lesson_logged") or 0) and _claim_outcome_flag(sid, "lesson_logged"):
        try:
            lesson_line = append_outcome_lesson(sig, oc)
            if lesson_line:
                log("hermes_scribe", "🧠 Hậu kiểm kèo #%d (%s) → đã nạp bài học thực chiến vào %s." % (
                    sid, oc.get("exit_reason") or oc.get("outcome"), SKILL_FILES.get(sig["asset"], "SKILL.md")), room="library_room")
        except Exception as e:
            _release_outcome_flag(sid, "lesson_logged")
            print("append_outcome_lesson error:", e)

    # 2. Bắn thông báo chạm SL / TP sang Telegram (chỉ kèo đã gửi Telegram, 1 lần cho mỗi mốc kết quả)
    if tg_sent and not int(oc.get("telegram_alerted") or 0) and CONFIG.get("telegram_alert_sl_tp", True) \
            and _claim_outcome_flag(sid, "telegram_alerted"):
        ok = False
        try:
            ok, msg = send_telegram_sl_tp_alert(CONFIG, sig, oc)
            if ok:
                log("vault_piggy", "📨 Đã báo Telegram kết quả kèo #%d chạm %s (%s)." % (
                    sid, oc.get("exit_reason") or oc.get("outcome"), msg), room="vault_room")
        except Exception as e:
            print("send_telegram_sl_tp_alert error:", e)
        if not ok:
            _release_outcome_flag(sid, "telegram_alerted")


def _infer_exit_reason(action, open_price, close_price, sl, tp, comment="", raw_reason="", net_profit=0.0):
    """Suy luận lý do đóng lệnh (TP1 / TP2 / TP / SL / BE / MANUAL / SO) từ dữ liệu deal hoặc khoảng cách giá."""
    r = str(raw_reason or "").upper().strip()
    cmt = str(comment or "").upper()
    leg = "TP1" if "/TP1" in cmt else ("TP2" if "/TP2" in cmt else "")
    if r in ("TP1", "TP2", "BE", "SO"):
        return r
    if r == "TP" or "[TP" in cmt:
        return leg or "TP"
    if r == "SL" or "[SL" in cmt:
        if open_price > 0 and close_price > 0:
            # Nếu đã dời SL về hoà vốn (BE): giá đóng rất sát giá mở hoặc lệnh có lãi nhẹ dù chạm SL
            sl_dist = abs(open_price - sl) if sl > 0 else 0.0
            diff = abs(close_price - open_price)
            if (sl_dist > 0 and diff <= sl_dist * 0.18) or (leg == "TP2" and net_profit >= -0.5):
                return "BE"
        return "SL"
    # Nếu không có cờ reason từ MT5, suy luận từ giá đóng so với SL và TP
    if close_price > 0 and (sl > 0 or tp > 0):
        tol = max(abs(open_price) * 0.0004, 0.15) if open_price > 0 else 0.5
        if tp > 0 and abs(close_price - tp) <= tol:
            return leg or "TP"
        if sl > 0 and abs(close_price - sl) <= tol:
            if open_price > 0 and abs(close_price - open_price) <= tol:
                return "BE"
            return "SL"
        if open_price > 0 and abs(close_price - open_price) <= tol * 0.5:
            return "BE"
    if r == "MANUAL":
        return "MANUAL"
    return (leg if net_profit > 0 and leg else ("TP" if net_profit > 0 else ("SL" if net_profit < 0 else "BE")))


def _fmt_epoch_time(ts_val):
    if not ts_val:
        return ""
    if isinstance(ts_val, str) and len(ts_val) >= 10 and not ts_val.isdigit():
        return ts_val[:19].replace(".", "-")
    try:
        return datetime.fromtimestamp(int(float(ts_val)), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_val)[:19]


def sync_closed_deals(closed_list):
    """Đồng bộ danh sách các lệnh đã đóng từ EA (qua /api/push_account hoặc /api/push_history) vào bảng executions & signal_outcomes."""
    if not closed_list:
        return 0
    updated_signals = set()
    newly_logged = []
    with DB_LOCK:
        conn = db_conn()
        for item in closed_list:
            pos_id = int(item.get("position") or item.get("ticket") or 0)
            if pos_id <= 0:
                continue
            ex = conn.execute("SELECT * FROM executions WHERE ticket=? ORDER BY id DESC LIMIT 1", (pos_id,)).fetchone()
            close_p = float(item.get("close_price") or item.get("price") or 0.0)
            net = float(item.get("net") if item.get("net") is not None else item.get("profit") or 0.0)
            close_t = _fmt_epoch_time(item.get("close_time") or item.get("time"))
            deal_tk = int(item.get("deal_ticket") or 0)
            raw_reason = str(item.get("reason") or "")
            cmt = str(item.get("comment") or (ex["comment"] if ex else "") or "")
            if ex:
                was_open = (ex["status"] != "closed")
                open_p = float(ex["price"] or item.get("open_price") or 0.0)
                sl_p = float(ex["sl"] or item.get("sl") or 0.0)
                tp_p = float(ex["tp"] or item.get("tp") or 0.0)
                reason = _infer_exit_reason(ex["action"], open_p, close_p, sl_p, tp_p, cmt, raw_reason, net)
                conn.execute("""UPDATE executions
                    SET status='closed', close_price=?, close_time=?, profit=?, exit_reason=?, deal_ticket=?
                    WHERE id=?""", (close_p, close_t, round(net, 2), reason, deal_tk, ex["id"]))
                if ex["signal_id"]:
                    updated_signals.add(int(ex["signal_id"]))
                if was_open:
                    newly_logged.append((ex["signal_id"], ex["symbol"], ex["action"], pos_id, reason, close_p, net))
            else:
                # Nếu EA đóng lệnh mà trước đó chưa có dòng execution (ví dụ DB mới nhưng có comment AITO#<id>)
                sid = int(item.get("signal_id") or 0)
                if not sid and "AITO#" in cmt:
                    try:
                        rest = cmt.split("AITO#", 1)[1].split("/")[0].strip()
                        sid = int("".join(ch for ch in rest if ch.isdigit()) or 0)
                    except Exception:
                        sid = 0
                if sid > 0:
                    open_p = float(item.get("open_price") or 0.0)
                    sl_p = float(item.get("sl") or 0.0)
                    tp_p = float(item.get("tp") or 0.0)
                    side = str(item.get("side") or item.get("action") or "BUY").upper()
                    reason = _infer_exit_reason(side, open_p, close_p, sl_p, tp_p, cmt, raw_reason, net)
                    conn.execute("""INSERT INTO executions
                        (created_at, signal_id, ticket, symbol, action, volume, price, sl, tp, retcode, error,
                         dry_run, magic, account, comment, terminal_time, raw_json, status, close_price, close_time,
                         profit, exit_reason, deal_ticket)
                        VALUES (?,?,?,?,?,?,?,?,?,10009,'',0,?,?,?,'','{}','closed',?,?,?,?,?)""",
                                 (close_t or now_iso(), sid, pos_id, str(item.get("symbol") or "")[:32], side,
                                  float(item.get("volume") or 0.0), open_p, sl_p, tp_p,
                                  int(item.get("magic") or 0), int(item.get("account") or 0), cmt[:64],
                                  close_p, close_t, round(net, 2), reason, deal_tk))
                    updated_signals.add(sid)
                    newly_logged.append((sid, str(item.get("symbol") or ""), side, pos_id, reason, close_p, net))
        conn.commit()
        conn.close()

    # Tổng hợp kết quả đóng lệnh cho từng signal_id vừa cập nhật
    for sid in updated_signals:
        _recompute_signal_outcome_from_executions(sid)
    if updated_signals:
        SCORE_CACHE["ts"] = 0
    for sid, sym, act, tk, rsn, cp, net in newly_logged[:10]:
        icon = "🏆" if rsn in ("TP", "TP1", "TP2") else ("🛡️" if rsn == "BE" else ("🛑" if rsn == "SL" else "📌"))
        log("vault_piggy", "%s Lệnh #%d (kèo #%d %s %s) đã đóng: chạm %s @%s · Lãi/lỗ: %+.2f USD" % (
            icon, tk, sid, sym, act, rsn, "{:g}".format(cp), net), room="vault_room")
    return len(updated_signals)


def _recompute_signal_outcome_from_executions(signal_id):
    """Gộp tất cả lệnh khớp thật của 1 kèo (kể cả kèo tách 2 lệnh TP1 + TP2) để lưu vào signal_outcomes."""
    with DB_LOCK:
        conn = db_conn()
        exs = conn.execute("""SELECT * FROM executions
            WHERE signal_id=? AND dry_run=0 AND ticket>0 AND (error IS NULL OR error='')
            ORDER BY id ASC""", (int(signal_id),)).fetchall()
        conn.close()
    if not exs:
        return None
    closed = [e for e in exs if e["status"] == "closed"]
    if not closed:
        return None
    total_net = sum(float(e["profit"] or 0.0) for e in closed)
    reasons = [str(e["exit_reason"] or "") for e in closed if e["exit_reason"]]
    # Ghép nhãn lý do đóng (ví dụ TP1+TP2, TP1+BE, SL, TP1 (TP2 đang mở))
    uniq_r = []
    for r in reasons:
        if r and r not in uniq_r:
            uniq_r.append(r)
    exit_label = "+".join(uniq_r) if uniq_r else ("TP" if total_net > 0 else "SL")
    if len(closed) < len(exs):
        exit_label += " (còn %d lệnh mở)" % (len(exs) - len(closed))
    last_c = closed[-1]
    outcome = "win" if (total_net > 0 or any(r in ("TP", "TP1", "TP2") for r in reasons)) else "loss"
    detail = "Đóng %d/%d lệnh (%s) @%s · Lãi/lỗ ròng: %+.2f USD" % (
        len(closed), len(exs), exit_label, "{:g}".format(float(last_c["close_price"] or 0.0)), total_net)
    db_set_outcome(signal_id, outcome, "mt5_deal", detail, exit_reason=exit_label,
                   close_price=float(last_c["close_price"] or 0.0), close_time=str(last_c["close_time"] or ""),
                   net_profit=round(total_net, 2))
    return outcome


def executed_signals():
    """Kèo BUY/SELL có lệnh khớp thật (không dry_run, có ticket, không lỗi) hoặc kèo BUY/SELL đã được chấm điểm SL/TP."""
    with DB_LOCK:
        conn = db_conn()
        rows = conn.execute("""SELECT s.id AS signal_id, s.asset, s.action, s.entry, s.stop_loss, s.take_profit_1,
                   s.take_profit_2, s.votes_json, s.created_at, e.ticket, e.price AS exec_price, e.sl AS exec_sl,
                   e.tp AS exec_tp, e.status AS exec_status, e.exit_reason, e.close_price, e.close_time,
                   e.profit AS exec_profit, e.created_at AS exec_at
            FROM executions e JOIN signals s ON s.id = e.signal_id
            WHERE s.action IN ('BUY','SELL') AND e.dry_run = 0 AND e.ticket > 0 AND (e.error IS NULL OR e.error = '')
            ORDER BY e.id""").fetchall()
        # Bổ sung các kèo BUY/SELL ĐÃ GỬI TELEGRAM có kết quả dò nến (kèo chỉ nằm trên dashboard không tính điểm)
        oc_rows = conn.execute("""SELECT s.id AS signal_id, s.asset, s.action, s.entry, s.stop_loss, s.take_profit_1,
                   s.take_profit_2, s.votes_json, s.created_at
            FROM signal_outcomes o JOIN signals s ON s.id = o.signal_id
            WHERE s.action IN ('BUY','SELL') AND o.outcome IN ('win','loss') AND s.telegram_sent = 1
            ORDER BY s.id""").fetchall()
        conn.close()
    out = {}
    for r in rows:
        if r["signal_id"] not in out:
            d = dict(r)
            try:
                d["votes"] = json.loads(d.pop("votes_json") or "{}")
            except Exception:
                d["votes"] = {}
            out[r["signal_id"]] = d
    for r in oc_rows:
        if r["signal_id"] not in out:
            d = dict(r)
            try:
                d["votes"] = json.loads(d.pop("votes_json") or "{}")
            except Exception:
                d["votes"] = {}
            d.update({"ticket": 0, "exec_price": d["entry"], "exec_sl": d["stop_loss"], "exec_tp": d["take_profit_1"],
                      "exec_status": "closed", "exit_reason": "", "close_price": 0.0, "close_time": "",
                      "exec_profit": 0.0, "exec_at": d["created_at"]})
            out[r["signal_id"]] = d
    return list(out.values())


def outcomes_from_history(trades):
    """Lịch sử EA gửi về (POST /api/push_history): đồng bộ cả vào executions lẫn signal_outcomes."""
    if not trades:
        return 0
    return sync_closed_deals(trades)


def evaluate_signal_sl_tp(sig_dict, exs=None):
    """Dò nến sau thời điểm ra kèo (hoặc khớp lệnh) xem giá đã chạm SL, TP1 hay TP2 chưa."""
    action = sig_dict.get("action")
    if action not in ("BUY", "SELL"):
        return None
    asset = sig_dict.get("asset", "XAUUSD")
    real_ex = [e for e in (exs or []) if not e.get("dry_run") and (e.get("ticket") or 0) > 0 and not e.get("error")]
    # Nếu có lệnh thật đang mở hoặc đã đóng trên MT5
    if real_ex:
        closed_ex = [e for e in real_ex if e.get("status") == "closed"]
        if closed_ex:
            net = sum(float(e.get("profit") or 0.0) for e in closed_ex)
            rsns = [e.get("exit_reason") or ("TP" if (e.get("profit") or 0) > 0 else "SL") for e in closed_ex]
            r_lbl = "+".join(dict.fromkeys(rsns))
            if len(closed_ex) < len(real_ex):
                r_lbl += " (1 lệnh đang mở)"
            return {"signal_id": sig_dict.get("id"), "outcome": "win" if net > 0 or "TP" in r_lbl else "loss",
                    "source": "mt5_deal", "exit_reason": r_lbl,
                    "close_price": closed_ex[-1].get("close_price") or 0.0,
                    "close_time": closed_ex[-1].get("close_time") or "",
                    "net_profit": round(net, 2),
                    "detail": "Khớp thật #%s · Đóng: %s (%+.2f USD)" % (real_ex[0]["ticket"], r_lbl, net)}
    t_str = (real_ex[0].get("created_at") if real_ex else None) or sig_dict.get("created_at") or ""
    try:
        start = time.mktime(time.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None
    entry = float(sig_dict.get("entry") or 0.0)
    exec_p = float(real_ex[0].get("price") or 0.0) if real_ex else 0.0
    shift = (exec_p - entry) if (exec_p > 0 and entry > 0) else 0.0
    sl = float((real_ex[0].get("sl") if real_ex and real_ex[0].get("sl") else 0.0) or (float(sig_dict.get("stop_loss") or 0.0) + shift))
    tp1 = float(sig_dict.get("take_profit_1") or 0.0) + shift
    tp2 = float(sig_dict.get("take_profit_2") or 0.0) + shift
    if sl <= 0 or tp1 <= 0:
        return None
    buy = (action == "BUY")
    # Nến MT5 mang giờ broker: chưa từng đo được offset hợp lệ thì KHÔNG dò (dò lệch giờ = chấm SL/TP sai)
    mt5_off = broker_utc_offset(asset)
    for tf in ("5m", "15m", "1h"):
        off = mt5_off
        with MT5_LOCK:
            f = MT5_FEED.get((asset, tf))
            candles = list(f["candles"]) if f else []
        if not candles:
            with MARKET_CACHE_LOCK:
                mc = MARKET_CACHE.get((asset, tf))
                if mc and mc.get("all"):
                    candles = list(mc["all"])
                    if not str(mc["data"].get("source", "")).startswith("mt5:"):
                        off = 0                      # Binance/Yahoo: giờ nến đã là UTC
        if candles and off is None:
            continue
        if not candles or candles[0]["t"] - off * 3600 > start:
            continue
        hit_tp1 = False
        tp1_time = ""
        for c in candles:
            ct = c["t"] - off * 3600
            if ct + TF_SECONDS[tf] <= start:
                continue
            ts_str = datetime.fromtimestamp(ct).strftime("%Y-%m-%d %H:%M:%S")
            if not hit_tp1:
                h_sl = c["l"] <= sl if buy else c["h"] >= sl
                h_tp1 = c["h"] >= tp1 if buy else c["l"] <= tp1
                if h_sl and h_tp1:
                    return {"signal_id": sig_dict.get("id"), "outcome": "loss", "source": "candles",
                            "exit_reason": "SL", "close_price": sl, "close_time": ts_str, "net_profit": 0.0,
                            "detail": "Nến %s chạm cả SL và TP1 cùng lúc → tính chạm SL @%s" % (tf, "{:g}".format(round(sl, 2)))}
                if h_sl:
                    return {"signal_id": sig_dict.get("id"), "outcome": "loss", "source": "candles",
                            "exit_reason": "SL", "close_price": sl, "close_time": ts_str, "net_profit": 0.0,
                            "detail": "Dò nến %s: chạm SL @%s lúc %s" % (tf, "{:g}".format(round(sl, 2)), ts_str[11:16])}
                if h_tp1:
                    hit_tp1 = True
                    tp1_time = ts_str
                    if tp2 > 0 and ((buy and c["h"] >= tp2) or (not buy and c["l"] <= tp2)):
                        return {"signal_id": sig_dict.get("id"), "outcome": "win", "source": "candles",
                                "exit_reason": "TP2", "close_price": tp2, "close_time": ts_str, "net_profit": 0.0,
                                "detail": "Dò nến %s: chạm cả TP1 & TP2 @%s lúc %s" % (tf, "{:g}".format(round(tp2, 2)), ts_str[11:16])}
            else:
                # Sau khi chạm TP1, kiểm tra chạm TP2 hay quay về Entry (BE)
                be_level = exec_p if exec_p > 0 else entry
                h_tp2 = tp2 > 0 and (c["h"] >= tp2 if buy else c["l"] <= tp2)
                h_be = (c["l"] <= be_level if buy else c["h"] >= be_level)
                if h_tp2:
                    return {"signal_id": sig_dict.get("id"), "outcome": "win", "source": "candles",
                            "exit_reason": "TP1+TP2", "close_price": tp2, "close_time": ts_str, "net_profit": 0.0,
                            "detail": "Dò nến %s: chạm TP1 rồi chạm tiếp TP2 @%s lúc %s" % (tf, "{:g}".format(round(tp2, 2)), ts_str[11:16])}
                if h_be:
                    return {"signal_id": sig_dict.get("id"), "outcome": "win", "source": "candles",
                            "exit_reason": "TP1+BE", "close_price": tp1, "close_time": tp1_time, "net_profit": 0.0,
                            "detail": "Dò nến %s: đã chạm TP1 @%s, phần TP2 dời hoà vốn (BE)" % (tf, "{:g}".format(round(tp1, 2)))}
        if hit_tp1:
            return {"signal_id": sig_dict.get("id"), "outcome": "win", "source": "candles",
                    "exit_reason": "TP1", "close_price": tp1, "close_time": tp1_time, "net_profit": 0.0,
                    "detail": "Dò nến %s: đã chạm TP1 @%s lúc %s (TP2 đang chạy)" % (tf, "{:g}".format(round(tp1, 2)), tp1_time[11:16])}
        return {"signal_id": sig_dict.get("id"), "outcome": "pending", "source": "candles",
                "exit_reason": "OPEN", "close_price": 0.0, "close_time": "", "net_profit": 0.0,
                "detail": "Đang chạy — giá chưa chạm SL hay TP1"}
    return None


def check_open_signals_sl_tp():
    """Quét định kỳ các kèo BUY/SELL chưa kết thúc để phát hiện sớm khi nến chạm SL/TP1/TP2,
    tự động ghi bài học vào SKILL.md và bắn cảnh báo Telegram."""
    with DB_LOCK:
        conn = db_conn()
        rows = conn.execute("""SELECT s.id, s.asset, s.action, s.entry, s.stop_loss, s.take_profit_1, s.take_profit_2,
                   s.created_at, o.outcome, o.exit_reason
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.id
            WHERE s.action IN ('BUY', 'SELL')
              AND (o.outcome IS NULL OR o.outcome = 'pending' OR o.exit_reason = 'TP1')
            ORDER BY s.id DESC LIMIT 20""").fetchall()
        conn.close()
    if not rows:
        return 0
    updated = 0
    for r in rows:
        sid = r["id"]
        if broker_utc_offset(r["asset"]) is None and CONFIG.get("price_source", "mt5_only") == "mt5_only":
            continue        # chưa từng có offset giờ broker hợp lệ -> chưa đánh giá được bằng nến MT5
        with DB_LOCK:
            conn = db_conn()
            exs = [dict(x) for x in conn.execute("SELECT * FROM executions WHERE signal_id=? ORDER BY id ASC", (sid,)).fetchall()]
            conn.close()
        res = evaluate_signal_sl_tp(dict(r), exs)
        if not res or res["outcome"] not in ("win", "loss"):
            continue
        if r["outcome"] == res["outcome"] and (r["exit_reason"] or "") == (res.get("exit_reason") or ""):
            continue
        db_set_outcome(sid, res["outcome"], res.get("source", "candles"), res.get("detail", ""),
                       exit_reason=res.get("exit_reason", ""), close_price=res.get("close_price", 0.0),
                       close_time=res.get("close_time", ""), net_profit=res.get("net_profit", 0.0),
                       trigger_hooks=True)
        updated += 1
    if updated:
        SCORE_CACHE["ts"] = 0
    return updated


def evaluate_by_candles(s):
    """Dò nến MT5 sau lúc khớp cho kèo đã vào lệnh thật."""
    sig_like = {
        "id": s["signal_id"], "asset": s["asset"], "action": s["action"],
        "entry": s["entry"], "stop_loss": s["stop_loss"],
        "take_profit_1": s["take_profit_1"], "take_profit_2": s.get("take_profit_2") or 0.0,
        "created_at": s["exec_at"],
    }
    ex_like = [{"ticket": s["ticket"], "price": s["exec_price"], "sl": s["exec_sl"],
                "created_at": s["exec_at"], "dry_run": 0, "status": s.get("exec_status", "open"),
                "exit_reason": s.get("exit_reason", ""), "close_price": s.get("close_price", 0.0),
                "close_time": s.get("close_time", ""), "profit": s.get("exec_profit", 0.0)}]
    res = evaluate_signal_sl_tp(sig_like, ex_like)
    if not res or res["outcome"] == "pending":
        return None, (res["detail"] if res else "chưa chạm SL/TP1"), None
    return res["outcome"], res["detail"], res


def sl_tp_history(limit=100):
    """Danh sách lịch sử SL/TP của các lệnh đã vào (kèm thông tin kèo gốc và kết quả đóng lệnh)."""
    with DB_LOCK:
        conn = db_conn()
        rows = conn.execute("""SELECT e.*, s.asset, s.timeframe, s.confidence, s.entry AS sig_entry,
                   s.stop_loss AS sig_sl, s.take_profit_1 AS sig_tp1, s.take_profit_2 AS sig_tp2,
                   o.outcome AS sig_outcome, o.exit_reason AS sig_exit_reason, o.detail AS sig_outcome_detail
            FROM executions e
            LEFT JOIN signals s ON s.id = e.signal_id
            LEFT JOIN signal_outcomes o ON o.signal_id = e.signal_id
            WHERE (e.ticket > 0 OR e.dry_run = 1) AND e.status NOT IN ('skipped', 'error')
            ORDER BY e.id DESC LIMIT ?""", (int(limit),)).fetchall()
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("raw_json", None)
        # Nếu lệnh đang open hoặc dry_run và chưa có exit_reason, bổ sung kết quả dò nến từ signal_outcomes
        if d.get("status") != "closed" and d.get("sig_exit_reason"):
            d["candle_exit_reason"] = d["sig_exit_reason"]
        out.append(d)
    return out


def sl_tp_memory_block(asset=None, limit=8):
    """Trích xuất bộ nhớ thực chiến từ lịch sử chạm SL/TP gần nhất để nạp vào bộ não LLM & Quant AI."""
    with DB_LOCK:
        conn = db_conn()
        if asset:
            rows = conn.execute("""SELECT s.id, s.asset, s.timeframe, s.action, s.confidence, s.entry, s.stop_loss,
                       s.take_profit_1, s.indicators_json, s.votes_json, o.outcome, o.exit_reason, o.close_price,
                       o.close_time, o.net_profit, o.detail
                FROM signal_outcomes o JOIN signals s ON s.id = o.signal_id
                WHERE s.asset=? AND o.outcome IN ('win','loss') AND (s.telegram_sent = 1 OR EXISTS (SELECT 1 FROM executions e WHERE e.signal_id = s.id AND e.dry_run = 0
                       AND e.ticket > 0 AND (e.error IS NULL OR e.error = '')))
                ORDER BY s.id DESC LIMIT ?""", (asset, int(limit))).fetchall()
        else:
            rows = conn.execute("""SELECT s.id, s.asset, s.timeframe, s.action, s.confidence, s.entry, s.stop_loss,
                       s.take_profit_1, s.indicators_json, s.votes_json, o.outcome, o.exit_reason, o.close_price,
                       o.close_time, o.net_profit, o.detail
                FROM signal_outcomes o JOIN signals s ON s.id = o.signal_id
                WHERE o.outcome IN ('win','loss') AND (s.telegram_sent = 1 OR EXISTS (SELECT 1 FROM executions e WHERE e.signal_id = s.id AND e.dry_run = 0
                       AND e.ticket > 0 AND (e.error IS NULL OR e.error = '')))
                ORDER BY s.id DESC LIMIT ?""", (int(limit),)).fetchall()
        conn.close()
    if not rows:
        return {"wins": 0, "losses": 0, "win_rate": None, "loss_streak": 0, "win_streak": 0,
                "text": "- Chưa có lịch sử chạm SL/TP đã đóng cho tài sản này."}
    wins = sum(1 for r in rows if r["outcome"] == "win")
    losses = len(rows) - wins
    win_rate = round(wins * 100.0 / len(rows), 1)
    loss_streak, win_streak = 0, 0
    for r in rows:
        if r["outcome"] == "loss":
            if win_streak == 0:
                loss_streak += 1
            else:
                break
        else:
            if loss_streak == 0:
                win_streak += 1
            else:
                break
    lines = ["- Thống kê %d kèo %s gần nhất đã đóng: %d Thắng (TP) / %d Thua (SL) — Winrate %.1f%% | Chuỗi hiện tại: %s" % (
        len(rows), asset or "toàn bộ", wins, losses, win_rate,
        ("🛑 %d lệnh SL liên tiếp (CẦN THẬN TRỌNG CAO)" % loss_streak) if loss_streak > 0 else ("🏆 %d lệnh TP liên tiếp" % win_streak))]
    for r in rows[:5]:
        try:
            ind_j = json.loads(r["indicators_json"] or "{}")
            votes_j = json.loads(r["votes_json"] or "{}")
        except Exception:
            ind_j, votes_j = {}, {}
        wrong_ag = [VOTE_LABELS.get(a, a) for a, v in votes_j.items()
                    if v in ("BUY", "SELL") and ((v == r["action"]) != (r["outcome"] == "win"))]
        right_ag = [VOTE_LABELS.get(a, a) for a, v in votes_j.items()
                    if v in ("BUY", "SELL") and ((v == r["action"]) == (r["outcome"] == "win"))]
        vr_txt = "RVOL %.2f×" % float(ind_j.get("vol_ratio") or 1.0) if ind_j.get("vol_ratio") else ""
        rsn = r["exit_reason"] or ("TP" if r["outcome"] == "win" else "SL")
        lines.append("  • Kèo #%d %s (%d%%) → Chạm %s @%s (%s, %s %s) | Đúng: %s | Sai: %s" % (
            r["id"], r["action"], int(r["confidence"] or 0), rsn,
            "{:g}".format(float(r["close_price"] or r["entry"] or 0)),
            "THẮNG" if r["outcome"] == "win" else "THUA",
            ind_j.get("structure", "?"), vr_txt,
            ",".join(right_ag) or "—", ",".join(wrong_ag) or "—"))
    return {"wins": wins, "losses": losses, "win_rate": win_rate,
            "loss_streak": loss_streak, "win_streak": win_streak, "text": "\n".join(lines)}


def agent_scorecard(force=False):
    with SCORE_LOCK:
        if not force and SCORE_CACHE["data"] and time.time() - SCORE_CACHE["ts"] < 60:
            return SCORE_CACHE["data"]
        with HIST_LOCK:
            r = HIST_REQ["cur"]
            trades = r["result"]["trades"] if r and r["status"] == "done" and r.get("result") else None
        if trades:
            outcomes_from_history(trades)
        known = db_outcomes()
        sigs = executed_signals()
        stats = {aid: {"votes": 0, "correct": 0} for aid in VOTERS}
        recent, pending, wins = [], 0, 0
        for s in sigs:
            oc = known.get(s["signal_id"])
            outcome = oc["outcome"] if oc else None
            source = oc["source"] if oc else ""
            detail = oc["detail"] if oc else ""
            exit_reason = oc.get("exit_reason", "") if oc else ""
            close_price = oc.get("close_price", 0.0) if oc else 0.0
            close_time = oc.get("close_time", "") if oc else ""
            net_profit = oc.get("net_profit", 0.0) if oc else 0.0
            if not outcome:
                try:
                    outcome, detail, full_oc = evaluate_by_candles(s)
                except Exception as e:
                    outcome, detail, full_oc = None, "lỗi đánh giá: %s" % str(e)[:80], None
                if outcome and full_oc:
                    source = full_oc.get("source", "candles")
                    exit_reason = full_oc.get("exit_reason", "")
                    close_price = full_oc.get("close_price", 0.0)
                    close_time = full_oc.get("close_time", "")
                    net_profit = full_oc.get("net_profit", 0.0)
                    db_set_outcome(s["signal_id"], outcome, source, detail,
                                   exit_reason=exit_reason, close_price=close_price,
                                   close_time=close_time, net_profit=net_profit)
            recent.append({"signal_id": s["signal_id"], "asset": s["asset"], "action": s["action"], "ticket": s["ticket"],
                           "outcome": outcome or "pending", "exit_reason": exit_reason or ("OPEN" if not outcome else ""),
                           "close_price": close_price, "close_time": close_time, "net_profit": net_profit,
                           "source": source, "detail": detail, "votes": s["votes"]})
            if not outcome:
                pending += 1
                continue
            wins += outcome == "win"
            for aid in VOTERS:
                v = s["votes"].get(aid)
                if v not in ("BUY", "SELL"):
                    continue                             # WAIT / kèo cũ chưa có agent này: không tính
                stats[aid]["votes"] += 1
                stats[aid]["correct"] += (v == s["action"]) == (outcome == "win")
        auto = bool(CONFIG.get("agent_auto_weight", True))
        agents = []
        for aid in VOTERS:
            st = stats[aid]
            acc = st["correct"] * 100.0 / st["votes"] if st["votes"] else None
            factor = max(0.5, min(1.5, acc / 50.0)) if acc is not None and st["votes"] >= SCORE_MIN_VOTES else 1.0
            agents.append({"id": aid, "name": AGENTS[aid]["name"], "label": VOTE_LABELS[aid], "votes": st["votes"],
                           "correct": st["correct"], "accuracy": round(acc, 1) if acc is not None else None,
                           "base_weight": BASE_WEIGHTS[aid], "factor": round(factor, 3),
                           "applied": auto and st["votes"] >= SCORE_MIN_VOTES,
                           "weight": round(BASE_WEIGHTS[aid] * (factor if auto else 1.0), 3)})
        done = len(sigs) - pending
        data = {"generated_at": now_iso(), "auto_weight": auto, "min_votes": SCORE_MIN_VOTES,
                "consensus_threshold": float(CONFIG.get("quant_consensus") or 0.4),
                "signals": {"executed": len(sigs), "evaluated": done, "pending": pending, "wins": wins,
                            "losses": done - wins, "win_rate": round(wins * 100.0 / done, 1) if done else None},
                "agents": agents, "regime_multipliers": REGIME_MULT, "recent": recent[-30:][::-1]}
        SCORE_CACHE["ts"], SCORE_CACHE["data"] = time.time(), data
        return data


def agent_weight_factors():
    try:
        return {a["id"]: a["factor"] for a in agent_scorecard()["agents"]}
    except Exception as e:
        print("scorecard:", e)
        return {}


# ============================================================================
# 5. MULTI-LLM ROUTER + FALLBACK
# ============================================================================
def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("Không tìm thấy JSON trong phản hồi LLM")
    return json.loads(text[s:e + 1])


# ---------------------------------------------------------------------------
# GEMINI MODEL POOL: xoay vòng nhiều model free, đếm request theo ngày (giờ Pacific),
# tự né model đã hết hạn mức (429), quá tải (503) hoặc không còn mở (404).
# ---------------------------------------------------------------------------
# (model, rpm, rpd, bật) — số liệu free tier tham khảo, sửa được trên web
GEMINI_DEFAULT_MODELS = [
    ("gemini-3.8-flash", 5, 20, True),
    ("gemini-3.7-flash", 5, 20, True),
    ("gemini-3.6-flash", 5, 20, True),
    ("gemini-3.5-flash", 5, 20, True),
    ("gemini-3-flash-preview", 5, 20, True),
    ("gemini-flash-latest", 5, 20, True),
    ("gemini-3.5-flash-lite", 15, 500, True),
    ("gemini-3.1-flash-lite", 15, 500, True),
    ("gemini-3.1-flash-lite-preview", 15, 500, True),
    ("gemini-flash-lite-latest", 15, 500, True),
    ("gemma-4-31b-it", 30, 14400, True),
    ("gemma-4-26b-a4b-it", 30, 14400, True),
    ("gemini-3.1-pro-preview", 0, 0, False),
    ("gemini-4-argon", 0, 0, False),
]
GEMINI_SKIP_WORDS = ("tts", "image", "embedding", "live", "transcribe", "audio", "banana", "robotics",
                     "computer-use", "veo", "imagen", "aqa", "customtools", "native", "lyria", "antigravity", "deep-research")
LLM_USAGE_LOCK = threading.Lock()
GEMINI_RPM_WINDOW = {}     # model -> deque[timestamps]
GEMINI_RR = {"i": 0}


def pacific_offset_hours(utc_dt):
    """Giờ Pacific (reset hạn mức Gemini): PDT -7 từ CN thứ 2 tháng 3, PST -8 từ CN đầu tháng 11."""
    y = utc_dt.year

    def nth_sunday(month, n):
        d = datetime(y, month, 1)
        first = d.replace(day=1 + (6 - d.weekday()) % 7)
        return first.replace(day=first.day + 7 * (n - 1))
    dst_start = nth_sunday(3, 2).replace(hour=10)    # 02:00 PST = 10:00 UTC
    dst_end = nth_sunday(11, 1).replace(hour=9)      # 02:00 PDT = 09:00 UTC
    naive = utc_dt.replace(tzinfo=None)
    return -7 if dst_start <= naive < dst_end else -8


def pacific_day_and_reset():
    from datetime import timedelta
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    off = pacific_offset_hours(utc)
    pt = utc + timedelta(hours=off)
    next_mid = (pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_epoch = time.time() + (next_mid - pt).total_seconds()
    return pt.strftime("%Y-%m-%d"), reset_epoch


def gemini_models_cfg(cfg=None):
    cfg = cfg or CONFIG
    lst = cfg.get("gemini_models") or []
    if not lst:
        lst = [{"model": m, "rpm": r, "rpd": d, "enabled": e} for m, r, d, e in GEMINI_DEFAULT_MODELS]
    out = []
    for it in lst:
        m = str(it.get("model", "")).strip()
        if m:
            out.append({"model": m, "rpm": int(it.get("rpm") or 0), "rpd": int(it.get("rpd") or 0),
                        "enabled": bool(it.get("enabled", True))})
    return out


def usage_get(day, model):
    with DB_LOCK:
        conn = db_conn()
        r = conn.execute("SELECT * FROM llm_usage WHERE day=? AND model=?", (day, model)).fetchone()
        conn.close()
    return dict(r) if r else {"day": day, "model": model, "ok": 0, "fail": 0, "last_status": "", "last_error": "",
                               "cooldown_until": 0.0, "last_used": ""}


def usage_update(model, ok, status, error="", cooldown_until=None):
    day, _ = pacific_day_and_reset()
    with LLM_USAGE_LOCK:
        u = usage_get(day, model)
        u["ok"] += 1 if ok else 0
        u["fail"] += 0 if ok else 1
        u["last_status"] = status
        u["last_error"] = (error or "")[:300]
        if cooldown_until is not None:
            u["cooldown_until"] = cooldown_until
        u["last_used"] = now_iso()
        with DB_LOCK:
            conn = db_conn()
            conn.execute("""INSERT OR REPLACE INTO llm_usage (day, model, ok, fail, last_status, last_error, cooldown_until, last_used)
                            VALUES (?,?,?,?,?,?,?,?)""", (day, model, u["ok"], u["fail"], u["last_status"], u["last_error"],
                                                         u["cooldown_until"], u["last_used"]))
            conn.commit()
            conn.close()


def gemini_status(cfg=None):
    day, reset = pacific_day_and_reset()
    now = time.time()
    out = []
    for it in gemini_models_cfg(cfg):
        u = usage_get(day, it["model"])
        win = GEMINI_RPM_WINDOW.get(it["model"]) or []
        rpm_used = sum(1 for t in win if now - t < 60)
        cd = max(0, int(u["cooldown_until"] - now))
        if not it["enabled"]:
            st = "off"
        elif cd > 0:
            st = "cooldown"
        elif it["rpd"] and u["ok"] >= it["rpd"]:
            st = "exhausted"
        elif it["rpm"] and rpm_used >= it["rpm"]:
            st = "rpm"
        else:
            st = "ready"
        out.append(dict(it, used=u["ok"], fail=u["fail"], rpm_used=rpm_used, cooldown_sec=cd, state=st,
                        last_status=u["last_status"], last_error=u["last_error"], last_used=u["last_used"]))
    return {"day_pt": day, "reset_in_sec": int(reset - now), "strategy": (cfg or CONFIG).get("gemini_strategy", "priority"),
            "models": out}


def gemini_call_model(model, prompt, key, timeout=30):
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, key)
    for json_mode in (True, False):
        gen = {"temperature": 0.4}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        try:
            data = http_post_json(url, {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 400 and json_mode:
                continue                       # model không hỗ trợ JSON mode -> thử lại thường
            raise
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))
    raise RuntimeError("không có phản hồi")


def gemini_pick_order(cfg):
    st = gemini_status(cfg)["models"]
    ready = [m for m in st if m["state"] == "ready"]
    if cfg.get("gemini_strategy") == "round_robin" and ready:
        i = GEMINI_RR["i"] % len(ready)
        GEMINI_RR["i"] += 1
        ready = ready[i:] + ready[:i]
    return [m["model"] for m in ready]


def llm_gemini(prompt, cfg, errors=None):
    """Thử lần lượt các model sẵn sàng. Trả về (text, model). Ghi lỗi từng model vào errors."""
    key = cfg.get("gemini_api_key")
    order = gemini_pick_order(cfg)
    if not order:
        raise RuntimeError("tất cả model Gemini đã hết hạn mức / đang nghỉ")
    _, reset_epoch = pacific_day_and_reset()
    for model in order[:max(1, int(cfg.get("gemini_max_attempts") or 5))]:
        GEMINI_RPM_WINDOW.setdefault(model, deque(maxlen=200)).append(time.time())
        try:
            text = gemini_call_model(model, prompt, key)
            extract_json(text)                                 # phải parse được mới tính thành công
            usage_update(model, True, "ok")
            return text, model
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                body = ""
            if e.code == 429:
                if "PerDay" in body or "per day" in body.lower():
                    cd, why = reset_epoch, "hết hạn mức ngày"
                else:
                    import re
                    m = re.search(r'"retryDelay":\s*"(\d+)', body)
                    cd, why = time.time() + (int(m.group(1)) + 2 if m else 60), "vượt giới hạn/phút"
            elif e.code == 404:
                cd, why = time.time() + 86400, "model không còn mở"
            elif e.code in (500, 502, 503, 504):
                cd, why = time.time() + 120, "quá tải tạm thời"
            elif e.code in (401, 403):
                cd, why = time.time() + 600, "API key bị từ chối"
            else:
                cd, why = time.time() + 300, "lỗi HTTP %d" % e.code
            usage_update(model, False, "http_%d" % e.code, why + ": " + body[:200], cd)
            if errors is not None:
                errors.append("gemini/%s %d (%s)" % (model, e.code, why))
        except Exception as e:
            usage_update(model, False, "error", str(e)[:200], time.time() + 120)
            if errors is not None:
                errors.append("gemini/%s: %s" % (model, str(e)[:120]))
    raise RuntimeError("đã thử %d model Gemini đều lỗi" % min(len(order), int(cfg.get("gemini_max_attempts") or 5)))


def gemini_discover(cfg):
    """Lấy danh sách model văn bản từ API, thêm model mới vào cuối danh sách (tắt sẵn để bạn tự bật)."""
    key = cfg.get("gemini_api_key")
    d = http_get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key=" + key)
    found = []
    for m in d.get("models", []):
        name = m["name"].split("/")[-1]
        if "generateContent" in m.get("supportedGenerationMethods", []) and not any(w in name.lower() for w in GEMINI_SKIP_WORDS):
            found.append(name)
    cur = gemini_models_cfg(cfg)
    have = {m["model"] for m in cur}
    added = [n for n in found if n not in have]
    for n in added:
        cur.append({"model": n, "rpm": 5, "rpd": 20, "enabled": False})
    return cur, added, found


def llm_openai_compat(url, key, model, prompt, json_mode=True):
    payload = {"model": model, "temperature": 0.4,
               "messages": [{"role": "system", "content": "Bạn là Trưởng nhóm chiến lược giao dịch. Chỉ trả về JSON hợp lệ."},
                            {"role": "user", "content": prompt}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": "Bearer %s" % key} if key else {}
    try:
        data = http_post_json(url, payload, headers)
    except urllib.error.HTTPError as e:
        if json_mode and e.code in (400, 422):
            payload.pop("response_format", None)
            data = http_post_json(url, payload, headers)
        else:
            raise
    return data["choices"][0]["message"]["content"]


def llm_groq(prompt, cfg):
    return llm_openai_compat("https://api.groq.com/openai/v1/chat/completions", cfg["groq_api_key"],
                             cfg.get("groq_model") or "openai/gpt-oss-120b", prompt)


def llm_openrouter(prompt, cfg):
    return llm_openai_compat("https://openrouter.ai/api/v1/chat/completions", cfg["openrouter_api_key"],
                             cfg.get("openrouter_model") or "deepseek/deepseek-chat:free", prompt)


def llm_custom(prompt, cfg):
    url = cfg["custom_api_url"].rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")
    return llm_openai_compat(url, cfg.get("custom_api_key", ""), cfg.get("custom_model") or "llama3", prompt)


def llm_provider_available(name, cfg):
    """Nhà cung cấp đã đủ cấu hình để gọi chưa (có key / có endpoint)."""
    if name == "gemini":
        return bool(cfg.get("gemini_api_key"))
    if name == "groq":
        return bool(cfg.get("groq_api_key"))
    if name == "openrouter":
        return bool(cfg.get("openrouter_api_key"))
    if name == "custom":
        return bool(cfg.get("custom_api_url"))
    return False


def llm_provider_order(cfg):
    """Thứ tự gọi nhà cung cấp do người dùng xếp (kéo thả). Bỏ tên lạ, khử trùng, và tự thêm
    các nhà cung cấp còn thiếu vào cuối để danh sách luôn đầy đủ 4 mục."""
    raw = cfg.get("llm_provider_order") or []
    out, seen = [], set()
    for name in raw:
        name = str(name)
        if name in LLM_PROVIDERS and name not in seen:
            seen.add(name)
            out.append(name)
    for name in LLM_PROVIDERS:
        if name not in seen:
            out.append(name)
    return out


def call_free_llm(prompt, cfg):
    """Gọi LLM theo thứ tự nhà cung cấp đã cấu hình trong Cài đặt (kéo thả).
    Mặc định: Gemini -> Groq -> OpenRouter -> Custom/Ollama. Trả về (dict|None, provider, errors);
    hết chuỗi thì rơi xuống Built-in Quant AI."""
    fns = {"gemini": llm_gemini, "groq": llm_groq, "openrouter": llm_openrouter, "custom": llm_custom}
    providers = [(name, fns[name]) for name in llm_provider_order(cfg) if llm_provider_available(name, cfg)]
    errors = []
    for name, fn in providers:
        try:
            if name == "gemini":
                raw, model = llm_gemini(prompt, cfg, errors)
                name = "gemini/" + model
            else:
                raw = fn(prompt, cfg)
            obj = extract_json(raw)
            act = str(obj.get("action", "WAIT")).upper()
            if act not in ("BUY", "SELL", "WAIT"):
                act = "WAIT"
            conf = int(float(obj.get("confidence", 60)))
            obj = {"action": act, "confidence": max(50, min(95, conf)),
                   "bull_argument": str(obj.get("bull_argument", "")).strip(),
                   "bear_argument": str(obj.get("bear_argument", "")).strip(),
                   "summary": str(obj.get("summary", "")).strip(),
                   "lesson_learned": str(obj.get("lesson_learned", "")).strip()}
            return obj, name, errors
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")[:200]
            except Exception:
                body = ""
            errors.append("%s HTTP %s %s" % (name, e.code, body))
        except Exception as e:
            if not (name == "gemini" and str(e).startswith("đã thử")):
                errors.append("%s: %s" % (name, str(e)[:200]))
    return None, "builtin-quant", errors


def ta_prompt_block(asset, ta, votes):
    """Số liệu 4 agent mở rộng (Khung lớn, Nhịp, Mốc giá, Volume VSA) + trọng số đồng thuận cho LLM."""
    d = ASSETS[asset]["decimals"]
    lines = []
    htf = ta.get("htf") or {}
    for key in ("h1", "h4"):
        h = htf.get(key)
        if h:
            lines.append("- %s: xu hướng %s | giá %.*f | EMA50 %.*f | EMA200 %.*f | cấu trúc đỉnh đáy %s" % (
                key.upper(), h["bias"], d, h["price"], d, h["ema50"], d, h["ema200"], h["structure"]))
        else:
            lines.append("- %s: không có dữ liệu" % key.upper())
    lines.append("- Veto khung lớn: %s" % ("CẤM " + htf["veto"] if htf.get("veto") else "không"))
    reg = ta.get("regime") or {}
    if reg:
        lines.append("- Trạng thái thị trường: %s | ADX %.1f (DI+ %.1f / DI- %.1f) | độ rộng Bollinger percentile %.0f | ATR/TB %.2f | spread %s (median %s)" % (
            reg.get("regime"), reg.get("adx14", 0), reg.get("plus_di", 0), reg.get("minus_di", 0), reg.get("bb_width_pct", 0),
            reg.get("atr_ratio", 1), reg.get("spread"), reg.get("spread_median")))
        lines.append("- Cờ chặn: %s" % ("; ".join(reg["block_reasons"]) if reg.get("blocked") else "không"))
    lv = ta.get("levels") or {}
    if lv:
        near = sorted(lv.get("levels") or [], key=lambda l: abs(l["dist_atr"]))[:6]
        lines.append("- Phiên hiện tại: %s (%02dh UTC) | hỗ trợ gần: %s %s | kháng cự gần: %s %s | phản ứng: %s" % (
            lv.get("session"), lv.get("utc_hour", 0), lv.get("support_name"), lv.get("support"),
            lv.get("resistance_name"), lv.get("resistance"), lv.get("reaction")))
        lines.append("- Các mức gần nhất (khoảng cách theo ATR, âm = dưới giá): " +
                     "; ".join("%s %s (%+.1f)" % (l["name"], l["price"], l["dist_atr"]) for l in near))
    vol = ta.get("volume") or {}
    if vol:
        lines.append("- Khối lượng & VSA (Cá Voi Volume): RVOL hiện tại %.2f× TB20 (3 nến %.2f×) | Volume Delta 10 nến %+.0f%% | Tín hiệu VSA: %s%s" % (
            float(vol.get("vol_ratio") or 1.0), float(vol.get("vol_ratio_3") or 1.0),
            float(vol.get("vol_delta_ratio") or 0.0) * 100, vol.get("vsa_signal", "NORMAL"),
            " (⚠️ CẢNH BÁO FAKEOUT CẠN VOLUME)" if vol.get("fakeout_warning") else ""))
    cs = ta.get("consensus") or {}
    if cs:
        lines.append("- Trọng số agent theo trạng thái %s (đã nhân hệ số tự học): %s" % (cs.get("regime"), ", ".join(
            "%s %.2f" % (VOTE_LABELS.get(a, a), w) for a, w in cs["weights"].items())))
        lines.append("- Điểm đồng thuận có trọng số: %+.2f / %.2f = %+.0f%% (ngưỡng ±%.0f%%) → %s" % (
            cs["score"], cs["total_weight"], cs["ratio"] * 100, cs["threshold"] * 100, cs["action"]))
    return "\n".join(lines)


def build_prompt(asset, tf, ind, ticker, votes, news, skill_text, ta=None):
    ta = ta or {}
    mem = ta.get("memory") or sl_tp_memory_block(asset)
    news_txt = "\n".join("- %s%s (%s, %s)" % ("🔥 " if n.get("relevant") else "", n["title"], n.get("source", ""), n.get("published", ""))
                         for n in news[:10])
    votes_txt = "\n".join("- %s (%s): %s — %s" % (AGENTS[a]["name"], a, v, m) for a, (v, m) in votes.items())
    return """Bạn là Trưởng Nhóm Chiến Lược của một văn phòng đầu tư. Hãy chủ trì cuộc họp Bull vs Bear cho %s khung %s.

## SỐ LIỆU THỰC TẾ (GIÁ, CHỈ BÁO & VOLUME VSA)
- Giá hiện tại: %.2f | Thay đổi 24h: %.2f%% | Cao/Thấp 24h: %.2f / %.2f
- Session VWAP: %.2f | Biên trên +1.5σ: %.2f | Biên dưới -1.5σ: %.2f | Vùng: %s
- EMA20: %.2f | EMA50: %.2f | EMA200: %.2f | Cấu trúc: %s
- RSI(14): %.1f | ATR(14): %.2f
- Swing High(20): %.2f | Swing Low(20): %.2f | Sweep: %s | BOS: %s
- Khối lượng (Volume): Hiện tại %.2f / TB20 %.2f (RVOL %.2f×, TB 3 nến %.2f×) | Delta Mua-Bán 10 nến: %+.0f%% | Tín hiệu VSA: %s

## KHUNG LỚN, TRẠNG THÁI THỊ TRƯỜNG, MỨC GIÁ, PHIÊN & DÒNG TIỀN VOLUME
%s

## PHIẾU BẦU CỦA %d CHUYÊN VIÊN
%s

## HỒ SƠ THỰC CHIẾN & LỊCH SỬ CHẠM SL/TP GẦN NHẤT (BỘ NÃO TỰ HỌC)
%s

## TIN VĨ MÔ MỚI NHẤT (tin bắt đầu bằng "Telegram:" là từ kênh tin realtime, 🔥 = liên quan trực tiếp; hãy cân nhắc tác động tới kèo)
%s

## QUY TẮC KỶ LUẬT & BÀI HỌC HẬU KIỂM (trích SKILL.md)
%s

## YÊU CẦU
Trả về DUY NHẤT một JSON (tiếng Việt), không thêm chữ nào khác:
{"action": "BUY|SELL|WAIT", "confidence": 50-95, "bull_argument": "lập luận phe mua 2-3 câu (nêu rõ cấu trúc, VWAP và Volume/VSA)", "bear_argument": "lập luận phe bán 2-3 câu (nêu rõ rủi ro, kháng cự và áp lực Volume)", "summary": "kết luận trưởng nhóm 2-4 câu có số liệu giá, RVOL và rút kinh nghiệm từ lịch sử SL/TP", "lesson_learned": "1 bài học kỷ luật ngắn gọn rút ra từ kèo này"}
Chỉ chọn BUY/SELL khi điểm đồng thuận có trọng số đạt ngưỡng, có sự ủng hộ của dòng tiền Volume (tránh phá vỡ giả khi RVOL thấp) và không lặp lại sai lầm của các lệnh vừa dính SL gần đây. Nếu mâu thuẫn, chọn WAIT.
Bắt buộc WAIT khi kèo bị veto khung lớn, có cờ chặn biến động/spread, hoặc bị Cá Voi Volume cảnh báo Fakeout cạn thanh khoản.""" % (
        ASSETS[asset]["label"], tf, ind["price"], ticker["change_pct"], ticker["high24"], ticker["low24"],
        ind["vwap"], ind["vwap_upper"], ind["vwap_lower"], ind["vwap_zone"],
        ind["ema20"], ind["ema50"], ind["ema200"], ind["structure"], ind["rsi14"], ind["atr14"],
        ind["swing_high"], ind["swing_low"], ind["sweep"], ind["bos"],
        float(ind.get("vol_current") or 0), float(ind.get("vol_ma20") or 0),
        float(ind.get("vol_ratio") or 1.0), float(ind.get("vol_ratio_3") or 1.0),
        float(ind.get("vol_delta_ratio") or 0.0) * 100, ind.get("vsa_signal", "NORMAL"),
        ta_prompt_block(asset, ta, votes) or "- (không có)",
        len(votes), votes_txt, mem.get("text", "- (chưa có)"),
        news_txt or "- (không có)", skill_text[:2800])


# ============================================================================
# 6. HERMES SKILL.md LOOP (Thư viện chiến lược & Tự học hậu kiểm SL/TP)
# ============================================================================
SKILL_FILES = {"XAUUSD": "xauusd-vwap-playbook.md", "BTCUSDT": "btcusdt-momentum-playbook.md"}
JOURNAL_HEADER = "## Nhật ký Tự Học (Hermes Loop)"
SKILL_LOCK = threading.Lock()


def safe_skill_path(name):
    name = os.path.basename(name)
    if not name.endswith(".md"):
        raise ValueError("Chỉ hỗ trợ file .md")
    return os.path.join(SKILLS_DIR, name)


def read_skill(asset):
    path = safe_skill_path(SKILL_FILES[asset])
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "# (Chưa có SKILL.md cho %s)" % asset


def skill_rules_excerpt(text):
    """Lấy phần quy tắc (trước mục Nhật ký) + ưu tiên các bài học [HẬU KIỂM THỰC CHIẾN] từ SL/TP + các bài học gần nhất."""
    if JOURNAL_HEADER in text:
        rules, journal = text.split(JOURNAL_HEADER, 1)
        all_lines = [l for l in journal.strip().splitlines() if l.strip().startswith("-")]
        post_mortems = [l for l in all_lines if "[HẬU KIỂM" in l][-5:]
        recent_regular = [l for l in all_lines if "[HẬU KIỂM" not in l][-4:]
        combined = post_mortems + [l for l in recent_regular if l not in post_mortems]
        return rules.strip() + "\n\n" + JOURNAL_HEADER + " (Ưu tiên bài học hậu kiểm chạm SL/TP)\n" + "\n".join(combined[-8:])
    return text


def append_lesson(asset, lesson, action, confidence):
    path = safe_skill_path(SKILL_FILES[asset])
    line = "- [%s] (%s %d%%) %s" % (now_iso(), action, confidence, lesson.replace("\n", " ").strip())
    with SKILL_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            content = "# %s Playbook\n" % asset
        if JOURNAL_HEADER not in content:
            content = content.rstrip() + "\n\n" + JOURNAL_HEADER + "\n"
        content = content.rstrip("\n") + "\n" + line + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return line


def append_outcome_lesson(sig, oc):
    """Ghi bài học hậu kiểm thực chiến vào SKILL.md ngay khi lệnh chạm SL hoặc TP."""
    asset = sig.get("asset", "XAUUSD")
    if asset not in SKILL_FILES:
        return None
    outcome = oc.get("outcome", "loss")
    rsn = oc.get("exit_reason") or ("TP" if outcome == "win" else "SL")
    ind = sig.get("indicators") or {}
    votes = sig.get("votes") or {}
    right_ag, wrong_ag = [], []
    for aid, v_raw in votes.items():
        v = v_raw[0] if isinstance(v_raw, (list, tuple)) else v_raw
        if v not in ("BUY", "SELL"):
            continue
        is_right = (v == sig.get("action")) == (outcome == "win")
        (right_ag if is_right else wrong_ag).append("%s(%s)" % (VOTE_LABELS.get(aid, aid), v))
    vr = float(ind.get("vol_ratio") or 1.0)
    vsa = str(ind.get("vsa_signal") or "NORMAL")
    struct = str(ind.get("structure") or "?")
    vzone = str(ind.get("vwap_zone") or "?")
    net = float(oc.get("net_profit") or 0.0)
    pnl_str = " (%+.2f USD)" % net if net != 0 else ""
    if outcome == "loss":
        advice = ("RÚT KINH NGHIỆM THUA (SL): Tránh vào %s khi cấu trúc %s / vùng %s (RVOL %.2f×, VSA=%s). "
                  "Cần lưu ý phản biện của %s." % (
                      sig.get("action"), struct, vzone, vr, vsa,
                      ", ".join(right_ag) if right_ag else "các chỉ báo ngược chiều"))
    else:
        advice = ("MẪU KÈO THẮNG (%s): Tiếp tục phát huy setup %s khi cấu trúc %s / vùng %s có RVOL %.2f× (%s), "
                  "đồng thuận bởi %s." % (
                      rsn, sig.get("action"), struct, vzone, vr, vsa,
                      ", ".join(right_ag) if right_ag else "nhóm chuyên viên"))
    lesson_txt = ("[HẬU KIỂM THỰC CHIẾN Kèo #%s · Chạm %s @%s%s] Đúng: %s | Sai: %s → %s" % (
        sig.get("id"), rsn, "{:g}".format(float(oc.get("close_price") or sig.get("entry") or 0)),
        pnl_str, ", ".join(right_ag) or "—", ", ".join(wrong_ag) or "—", advice))
    return append_lesson(asset, lesson_txt, sig.get("action", "WAIT"), int(sig.get("confidence") or 50))


def list_skills():
    out = []
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if fn.endswith(".md"):
            p = os.path.join(SKILLS_DIR, fn)
            out.append({"name": fn, "size": os.path.getsize(p),
                        "modified": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")})
    return out


# ============================================================================
# 6b. BỘ VẼ BIỂU ĐỒ KÈO PNG (100% Python Standard Library: zlib + struct)
# ============================================================================
import unicodedata

_FONT_5X7 = {
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    '!': (0x04, 0x04, 0x04, 0x04, 0x00, 0x04, 0x00),
    '"': (0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00),
    '#': (0x0A, 0x1F, 0x0A, 0x0A, 0x1F, 0x0A, 0x00),
    '$': (0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04),
    '%': (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),
    '&': (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),
    "'": (0x04, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00),
    '(': (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ')': (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    '*': (0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00),
    '+': (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    ',': (0x00, 0x00, 0x00, 0x00, 0x04, 0x04, 0x08),
    '-': (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    '.': (0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x06),
    '/': (0x01, 0x02, 0x04, 0x04, 0x08, 0x10, 0x00),
    '0': (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    '1': (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    '2': (0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F),
    '3': (0x1F, 0x02, 0x04, 0x06, 0x01, 0x11, 0x0E),
    '4': (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    '5': (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    '6': (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    '7': (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    '8': (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    '9': (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ':': (0x00, 0x06, 0x06, 0x00, 0x06, 0x06, 0x00),
    ';': (0x00, 0x06, 0x06, 0x00, 0x06, 0x04, 0x08),
    '<': (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    '=': (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    '>': (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    '?': (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    '@': (0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E),
    'A': (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    'B': (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    'C': (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    'D': (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    'E': (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    'F': (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    'G': (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    'H': (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    'I': (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    'J': (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    'K': (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    'L': (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    'M': (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    'N': (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    'O': (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    'P': (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    'Q': (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    'R': (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    'S': (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    'T': (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    'U': (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    'V': (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    'W': (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    'X': (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    'Y': (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    'Z': (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    '[': (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),
    ']': (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),
    '_': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    '|': (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
}


def _ascii_clean(s):
    s = str(s or "").replace("đ", "d").replace("Đ", "D").replace("±", "+/-").replace("σ", "sd").replace("×", "x")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c) and 32 <= ord(c) < 127)


class SimplePngCanvas(object):
    def __init__(self, width, height, bg=(11, 15, 26)):
        self.w = int(width)
        self.h = int(height)
        self.buf = bytearray(bytes(bg) * (self.w * self.h))

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.w, int(x + w))
        y1 = min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        span = bytes(color) * (x1 - x0)
        stride = self.w * 3
        b = self.buf
        for py in range(y0, y1):
            off = py * stride + x0 * 3
            b[off:off + (x1 - x0) * 3] = span

    def fill_rect_alpha(self, x, y, w, h, color, alpha=0.22):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.w, int(x + w))
        y1 = min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        r, g, bl = color
        a = max(0.0, min(1.0, float(alpha)))
        ia = 1.0 - a
        ar, ag, ab = int(r * a), int(g * a), int(bl * a)
        stride = self.w * 3
        b = self.buf
        for py in range(y0, y1):
            row = py * stride
            for px in range(x0, x1):
                i = row + px * 3
                b[i] = min(255, int(b[i] * ia) + ar)
                b[i + 1] = min(255, int(b[i + 1] * ia) + ag)
                b[i + 2] = min(255, int(b[i + 2] * ia) + ab)

    def stroke_rect(self, x, y, w, h, color, thickness=1):
        t = max(1, int(thickness))
        self.fill_rect(x, y, w, t, color)
        self.fill_rect(x, y + h - t, w, t, color)
        self.fill_rect(x, y, t, h, color)
        self.fill_rect(x + w - t, y, t, h, color)

    def draw_hline(self, x0, x1, y, color, dashed=False, thickness=1):
        py = int(round(y))
        if py < 0 or py >= self.h:
            return
        xa, xb = max(0, min(int(x0), int(x1))), min(self.w - 1, max(int(x0), int(x1)))
        if xb <= xa:
            return
        if not dashed:
            self.fill_rect(xa, py - thickness // 2, xb - xa + 1, thickness, color)
            return
        for sx in range(xa, xb + 1, 10):
            ex = min(xb + 1, sx + 6)
            self.fill_rect(sx, py - thickness // 2, ex - sx, thickness, color)

    def draw_line(self, x0, y0, x1, y1, color, thickness=1):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        w, h, b = self.w, self.h, self.buf
        cb = bytes(color)
        r = max(0, int(thickness) - 1)
        while True:
            if 0 <= x0 < w and 0 <= y0 < h:
                if r == 0:
                    idx = (y0 * w + x0) * 3
                    b[idx:idx + 3] = cb
                else:
                    self.fill_rect(x0 - r, y0 - r, r * 2 + 1, r * 2 + 1, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def draw_text(self, x, y, text, color=(230, 235, 245), scale=2):
        s = _ascii_clean(text).upper()
        cx = int(x)
        cy = int(y)
        sc = max(1, int(scale))
        for ch in s:
            glyph = _FONT_5X7.get(ch, _FONT_5X7[' '])
            for row_i, mask in enumerate(glyph):
                if not mask:
                    continue
                for col_i in range(5):
                    if mask & (1 << (4 - col_i)):
                        self.fill_rect(cx + col_i * sc, cy + row_i * sc, sc, sc, color)
            cx += 6 * sc
        return cx

    def text_width(self, text, scale=2):
        s = _ascii_clean(text)
        return max(0, len(s) * 6 * max(1, int(scale)) - max(1, int(scale)))

    def to_png(self):
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw.extend(self.buf[y * stride:(y + 1) * stride])

        def _chunk(tag, data):
            return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack("!IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        idat = zlib.compress(bytes(raw), 6)
        return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def render_signal_chart_png(sig, candles=None):
    """Vẽ ảnh chụp biểu đồ kèo (960x560 PNG): nến OHLC, cột Volume VSA, dải VWAP ±1.5σ, EMA 20/50/200, vùng Entry/SL/TP1/TP2 và phiếu 7 Agent."""
    asset = sig.get("asset", "XAUUSD")
    tf = sig.get("timeframe") or CONFIG.get("timeframe") or "15m"
    if not candles:
        try:
            _, all_c = market_full(asset, tf, publish=False)
            candles = all_c[-65:]
        except Exception:
            candles = []
    else:
        candles = list(candles)[-65:]

    W, H = 960, 560
    cv = SimplePngCanvas(W, H, bg=(11, 15, 26))
    C_PANEL = (18, 24, 41)
    C_PANEL2 = (23, 31, 51)
    C_LINE = (38, 48, 73)
    C_TEXT = (230, 235, 245)
    C_MUTED = (138, 148, 173)
    C_GREEN = (46, 204, 113)
    C_RED = (255, 92, 92)
    C_AMBER = (245, 182, 60)
    C_BLUE = (77, 163, 255)
    C_PURPLE = (166, 108, 255)
    C_CYAN = (56, 217, 245)

    act = str(sig.get("action") or "WAIT").upper()
    act_col = C_GREEN if act == "BUY" else (C_RED if act == "SELL" else C_AMBER)
    conf = int(sig.get("confidence") or 50)
    d = ASSETS.get(asset, {}).get("decimals", 2)
    ind = sig.get("indicators") or {}

    # 1. HEADER BAR (0..58)
    cv.fill_rect(0, 0, W, 58, C_PANEL)
    cv.fill_rect(0, 0, W, 3, act_col)
    cv.fill_rect(14, 11, 118, 36, act_col)
    cv.draw_text(24, 19, "%s %d%%" % (act, conf), (11, 15, 26), scale=3)

    sid_txt = "#%s " % sig["id"] if sig.get("id") else ""
    title_str = "%s%s  [%s]  %s" % (sid_txt, asset, tf.upper(), str(sig.get("symbol") or "").upper())
    cv.draw_text(146, 12, title_str, C_TEXT, scale=2)
    sub_str = "GIA: %.*f  VWAP: %.*f  RSI: %.1f  ATR: %.*f  RVOL: %.2fX (%s)  %s" % (
        d, float(ind.get("price") or sig.get("entry") or 0),
        d, float(ind.get("vwap") or 0),
        float(ind.get("rsi14") or 50),
        d, float(ind.get("atr14") or 0),
        float(ind.get("vol_ratio") or 1.0),
        str(ind.get("vsa_signal") or "NORMAL"),
        str(ind.get("structure") or "SIDEWAY"))
    cv.draw_text(146, 35, sub_str[:125], C_MUTED, scale=1)
    ts_str = str(sig.get("created_at") or now_iso())
    tw = cv.text_width(ts_str, scale=1)
    cv.draw_text(W - tw - 16, 14, ts_str, C_MUTED, scale=1)

    # 2. KHUNG BIỂU ĐỒ NẾN, VOLUME & SETUP (y: 68..432)
    cx, cy, cw, ch = 14, 68, W - 28, 364
    cv.fill_rect(cx, cy, cw, ch, C_PANEL)
    cv.stroke_rect(cx, cy, cw, ch, C_LINE, 1)

    plot_x0 = cx + 14
    plot_x1 = cx + cw - 118
    plot_y0 = cy + 16
    plot_y1 = cy + ch - 62   # dành 48px đáy khung cho biểu đồ cột Volume VSA
    vol_y0 = plot_y1 + 6
    vol_y1 = cy + ch - 10
    vol_h = max(16, vol_y1 - vol_y0)
    plot_w = plot_x1 - plot_x0
    plot_h = plot_y1 - plot_y0

    entry = float(sig.get("entry") or ind.get("price") or 0)
    sl = float(sig.get("stop_loss") or 0)
    tp1 = float(sig.get("take_profit_1") or 0)
    tp2 = float(sig.get("take_profit_2") or 0)
    vwap_v = float(ind.get("vwap") or 0)
    vwap_up = float(ind.get("vwap_upper") or 0)
    vwap_lo = float(ind.get("vwap_lower") or 0)
    close_mark = float(sig.get("_close_price") or 0)

    if candles and len(candles) >= 5:
        closes = [c["c"] for c in candles]
        e20_s = ema(closes, 20)
        e50_s = ema(closes, 50)
        e200_s = ema(closes, min(len(closes), 200))
        p_vals = [c["h"] for c in candles] + [c["l"] for c in candles]
        for lv in (entry, sl, tp1, tp2, vwap_v, vwap_up, vwap_lo, close_mark):
            if lv and lv > 0:
                p_vals.append(lv)
        p_min, p_max = min(p_vals), max(p_vals)
        pad = (p_max - p_min) * 0.08 or 1.0
        p_lo, p_hi = p_min - pad, p_max + pad

        def py_of(p):
            return int(round(plot_y1 - (p - p_lo) / (p_hi - p_lo) * plot_h))

        for gi in range(6):
            gv = p_lo + (p_hi - p_lo) * gi / 5.0
            gy = py_of(gv)
            cv.draw_hline(plot_x0, plot_x1, gy, (27, 36, 58), dashed=False, thickness=1)
            cv.draw_text(plot_x1 + 8, gy - 4, "%.*f" % (d, gv), C_MUTED, scale=1)

        if vwap_up > 0 and vwap_lo > 0:
            y_up, y_lo, y_vm = py_of(vwap_up), py_of(vwap_lo), py_of(vwap_v)
            cv.fill_rect_alpha(plot_x0, min(y_up, y_lo), plot_w, abs(y_lo - y_up), C_AMBER, alpha=0.07)
            cv.draw_hline(plot_x0, plot_x1, y_up, (140, 110, 45), dashed=True, thickness=1)
            cv.draw_hline(plot_x0, plot_x1, y_lo, (140, 110, 45), dashed=True, thickness=1)
            cv.draw_hline(plot_x0, plot_x1, y_vm, C_AMBER, dashed=False, thickness=1)

        candle_area_w = int(plot_w * 0.76)
        proj_x0 = plot_x0 + candle_area_w + 6
        proj_w = plot_x1 - proj_x0 - 2
        n_c = len(candles)
        step_x = float(candle_area_w) / max(1, n_c)
        bar_w = max(3, min(11, int(step_x * 0.68)))

        if entry > 0 and sl > 0 and tp1 > 0:
            y_en = py_of(entry)
            y_sl = py_of(sl)
            y_tp1 = py_of(tp1)
            y_tp2 = py_of(tp2) if tp2 > 0 else y_tp1
            cv.fill_rect_alpha(proj_x0, min(y_en, y_sl), proj_w, max(2, abs(y_sl - y_en)), C_RED, alpha=0.22)
            cv.fill_rect_alpha(proj_x0, min(y_en, y_tp2), proj_w, max(2, abs(y_tp2 - y_en)), C_GREEN, alpha=0.18)
            cv.draw_hline(proj_x0 - 20, plot_x1, y_sl, C_RED, dashed=True, thickness=2)
            cv.draw_hline(proj_x0 - 20, plot_x1, y_tp1, C_GREEN, dashed=True, thickness=2)
            if tp2 > 0:
                cv.draw_hline(proj_x0 - 20, plot_x1, y_tp2, C_CYAN, dashed=True, thickness=2)
            cv.draw_hline(proj_x0 - 30, plot_x1, y_en, C_BLUE, dashed=False, thickness=2)

            def _price_tag(y_pos, label_txt, bg_col, fg_col=(11, 15, 26)):
                ty = max(plot_y0, min(plot_y1 - 13, y_pos - 6))
                cv.fill_rect(plot_x1 + 4, ty, 108, 13, bg_col)
                cv.draw_text(plot_x1 + 8, ty + 3, label_txt, fg_col, scale=1)

            if tp2 > 0:
                _price_tag(y_tp2, "TP2 %.*f" % (d, tp2), C_CYAN)
            _price_tag(y_tp1, "TP1 %.*f" % (d, tp1), C_GREEN)
            _price_tag(y_sl, "SL  %.*f" % (d, sl), C_RED, (255, 255, 255))
            _price_tag(y_en, "EN  %.*f" % (d, entry), C_BLUE, (255, 255, 255))
            if close_mark > 0:
                y_cm = py_of(close_mark)
                cm_lbl = str(sig.get("_exit_reason") or "HIT")[:4]
                cm_col = C_GREEN if "TP" in cm_lbl else (C_RED if "SL" in cm_lbl else C_AMBER)
                cv.draw_hline(plot_x0, plot_x1, y_cm, cm_col, dashed=False, thickness=2)
                _price_tag(y_cm, "%s %.*f" % (cm_lbl, d, close_mark), cm_col, (11, 15, 26))

        for series, col in ((e200_s, C_PURPLE), (e50_s, C_BLUE), (e20_s, C_CYAN)):
            pts = [(int(plot_x0 + (i + 0.5) * step_x), py_of(v)) for i, v in enumerate(series)]
            for i in range(1, len(pts)):
                cv.draw_line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], col, thickness=2)

        for i, c in enumerate(candles):
            cx_i = int(plot_x0 + (i + 0.5) * step_x)
            yh = py_of(c["h"])
            yl = py_of(c["l"])
            yo = py_of(c["o"])
            yc = py_of(c["c"])
            bull = c["c"] >= c["o"]
            col = C_GREEN if bull else C_RED
            cv.draw_line(cx_i, yh, cx_i, yl, col, thickness=1)
            top = min(yo, yc)
            bh = max(2, abs(yc - yo))
            cv.fill_rect(cx_i - bar_w // 2, top, bar_w, bh, col)

        # Vẽ biểu đồ cột Volume & đường MA20 Volume ở chân biểu đồ
        cv.draw_hline(plot_x0, plot_x1, vol_y0 - 2, C_LINE, dashed=False, thickness=1)
        vols = [max(float(c.get("v") or 0.0), 0.0) for c in candles]
        v_max = max(vols) if vols and max(vols) > 0 else 1.0
        v_ma = sum(vols[-20:]) / min(20, len(vols)) if vols else 1.0
        for i, c in enumerate(candles):
            cx_i = int(plot_x0 + (i + 0.5) * step_x)
            v_val = max(float(c.get("v") or 0.0), 0.0)
            vh = max(1, int(round((v_val / v_max) * vol_h)))
            bull = c["c"] >= c["o"]
            is_spike = v_ma > 0 and v_val >= 1.5 * v_ma
            v_col = (C_CYAN if bull else C_AMBER) if is_spike else ((36, 145, 86) if bull else (180, 65, 65))
            cv.fill_rect(cx_i - bar_w // 2, vol_y1 - vh, bar_w, vh, v_col)
        if v_ma > 0 and v_max > 0:
            y_vma = vol_y1 - int(round((v_ma / v_max) * vol_h))
            cv.draw_hline(plot_x0, plot_x0 + candle_area_w, max(vol_y0, min(vol_y1, y_vma)), C_AMBER, dashed=True, thickness=1)
        cv.draw_text(plot_x1 + 8, vol_y0 + 6, "VOL %.2fX" % float(ind.get("vol_ratio") or 1.0), C_CYAN, scale=1)

        cv.draw_text(plot_x0 + 6, plot_y0 + 4, "EMA20", C_CYAN, scale=1)
        cv.draw_text(plot_x0 + 48, plot_y0 + 4, "EMA50", C_BLUE, scale=1)
        cv.draw_text(plot_x0 + 90, plot_y0 + 4, "EMA200", C_PURPLE, scale=1)
        cv.draw_text(plot_x0 + 140, plot_y0 + 4, "VWAP +/-1.5SD", C_AMBER, scale=1)
        cv.draw_text(plot_x0 + 236, plot_y0 + 4, "VOL MA20", C_CYAN, scale=1)
    else:
        cv.draw_text(cx + 40, cy + ch // 2, "CHUA CO DU LIEU NEN DE VE BIEU DO", C_MUTED, scale=2)

    # 3. DẢI PHIẾU BẦU 7 AGENT & QUẢN TRỊ VỐN (y: 442..548)
    by = 442
    votes = sig.get("votes") or {}
    n_voters = len(VOTERS)
    gap = 6
    card_w = (W - 28 - (n_voters - 1) * gap) // n_voters
    for idx, aid in enumerate(VOTERS):
        vx = 14 + idx * (card_w + gap)
        v_raw = votes.get(aid, "WAIT")
        v_str = str(v_raw[0] if isinstance(v_raw, (list, tuple)) else v_raw).upper()
        v_col = C_GREEN if v_str == "BUY" else (C_RED if v_str == "SELL" else C_AMBER)
        cv.fill_rect(vx, by, card_w, 52, C_PANEL2)
        cv.stroke_rect(vx, by, card_w, 52, v_col, 1)
        cv.fill_rect(vx, by, 5, 52, v_col)
        lbl = VOTE_LABELS.get(aid, aid)
        cv.draw_text(vx + 10, by + 8, lbl, C_MUTED, scale=1)
        cv.draw_text(vx + 10, by + 24, v_str, v_col, scale=2)

    fy = 504
    cv.fill_rect(14, fy, W - 28, 42, C_PANEL)
    cv.stroke_rect(14, fy, W - 28, 42, C_LINE, 1)
    ta_info = (ind.get("ta") or {})
    cs = ta_info.get("consensus") or {}
    cs_txt = "%+.0f%% (NGUONG %.0f%%)" % (float(cs.get("ratio") or 0) * 100, float(cs.get("threshold") or 0.4) * 100) if cs else "N/A"
    foot_left = "LOT: %.3f  |  RUI RO: $%.2f  |  RR: 1:%.1f / 1:%.1f  |  RVOL: %.2fX  |  DONG THUAN: %s" % (
        float(sig.get("lot_size") or 0), float(sig.get("risk_amount") or 0),
        float(sig.get("rr1") or 1.8), float(sig.get("rr2") or 2.6), float(ind.get("vol_ratio") or 1.0), cs_txt)
    cv.draw_text(26, fy + 10, foot_left[:125], C_TEXT, scale=1)
    summary_clean = _ascii_clean(sig.get("summary") or "")[:115]
    cv.draw_text(26, fy + 25, "LY DO: " + summary_clean, C_AMBER, scale=1)

    return cv.to_png()


# ============================================================================
# 7. TELEGRAM
# ============================================================================
def _html_esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram(cfg, text, reply_to_message_id=None):
    token, chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not token or not chat:
        return False, "chưa cấu hình"
    try:
        payload = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        tg_api(cfg, "sendMessage", payload, timeout=15)
        return True, "ok"
    except Exception as e:
        return False, str(e)[:200]


def format_telegram(sig):
    icon = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}.get(sig["action"], "🟡")
    sid_str = "#%s · " % sig["id"] if sig.get("id") else ""
    votes = sig.get("votes") or {}
    ind = sig.get("indicators") or {}
    vote_str = " · ".join("%s:<b>%s</b>" % (VOTE_LABELS.get(a, a), votes[a][0] if isinstance(votes[a], (list, tuple)) else votes[a])
                          for a in VOTERS if a in votes)
    vol_line = "🐳 Volume VSA: RVOL <b>%.2f×</b> TB20 | Delta <b>%+.0f%%</b> | <code>%s</code>\n" % (
        float(ind.get("vol_ratio") or 1.0), float(ind.get("vol_delta_ratio") or 0.0) * 100,
        _html_esc(ind.get("vsa_signal") or "NORMAL"))
    return ("%s <b>%s%s %s</b> (%s) — Tự tin <b>%d%%</b>\n"
            "🎯 Entry: <code>%s</code> | 🛑 SL: <code>%s</code>\n"
            "💰 TP1: <code>%s</code> (1:%s) | 🏆 TP2: <code>%s</code> (1:%s)\n"
            "📦 Lot: <code>%s</code> | Rủi ro: <b>$%s</b>\n"
            "%s"
            "🗳️ Phiếu bầu: %s\n"
            "💹 Nguồn giá: <b>%s</b>\n\n"
            "📋 <b>Lý do vào lệnh (Trưởng nhóm):</b>\n%s\n\n"
            "🟢 <b>Luận điểm Phe Mua:</b>\n%s\n\n"
            "🔴 <b>Luận điểm Phe Bán:</b>\n%s\n\n"
            "🛡️ <b>Quản trị rủi ro:</b>\n%s\n\n"
            "<i>%s · Nguồn AI: %s</i>" % (
                icon, sid_str, sig["action"], sig["asset"], sig["timeframe"], sig["confidence"],
                sig["entry"], sig["stop_loss"],
                sig["take_profit_1"], sig.get("rr1", 1.8), sig["take_profit_2"], sig.get("rr2", 2.6),
                sig["lot_size"], sig["risk_amount"],
                vol_line,
                vote_str or "—",
                _html_esc(sig.get("symbol", "").replace("mt5:", "MT5 ").replace("binance:", "Binance ").replace("yahoo:", "Yahoo ")),
                _html_esc(sig.get("summary", "")),
                _html_esc(sig.get("bull_argument", "")),
                _html_esc(sig.get("bear_argument", "")),
                _html_esc(sig.get("risk_note", "")),
                sig["created_at"], _html_esc(sig.get("llm_provider", ""))))


def send_telegram_signal(cfg, sig, candles=None):
    """Chụp màn hình biểu đồ kèo PNG kèm lý do vào lệnh gửi sang Telegram."""
    token, chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not token or not chat:
        return False, "chưa cấu hình"
    full_text = format_telegram(sig)
    if not cfg.get("telegram_send_photo", True):
        return send_telegram(cfg, full_text)
    try:
        png_bytes = render_signal_chart_png(sig, candles=candles)
        fname = "keo_%s_%s.png" % (sig.get("asset", "XAU"), sig.get("id") or "live")
        if len(full_text) <= 1024:
            tg_api(cfg, "sendPhoto", {"chat_id": chat, "parse_mode": "HTML", "caption": full_text},
                   timeout=25, file_tuple=("photo", fname, png_bytes))
            return True, "đã gửi ảnh + lý do"
        icon = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}.get(sig["action"], "🟡")
        sid_str = "#%s · " % sig["id"] if sig.get("id") else ""
        votes = sig.get("votes") or {}
        ind = sig.get("indicators") or {}
        vote_str = " · ".join("%s:<b>%s</b>" % (VOTE_LABELS.get(a, a), votes[a][0] if isinstance(votes[a], (list, tuple)) else votes[a])
                              for a in VOTERS if a in votes)
        short_caption = (
            "%s <b>%s%s %s</b> (%s) — Tự tin <b>%d%%</b>\n"
            "🎯 Entry: <code>%s</code> | 🛑 SL: <code>%s</code>\n"
            "💰 TP1: <code>%s</code> (1:%s) | 🏆 TP2: <code>%s</code> (1:%s)\n"
            "📦 Lot: <code>%s</code> ($%s) | 🐳 RVOL: <b>%.2f×</b> (<code>%s</code>)\n"
            "🗳️ Phiếu: %s\n\n"
            "📋 <b>Lý do vào lệnh:</b>\n%s\n\n"
            "🟢 <b>Bull:</b> %s\n"
            "🔴 <b>Bear:</b> %s\n"
            "<i>%s · AI: %s</i>" % (
                icon, sid_str, sig["action"], sig["asset"], sig["timeframe"], sig["confidence"],
                sig["entry"], sig["stop_loss"], sig["take_profit_1"], sig.get("rr1", 1.8),
                sig["take_profit_2"], sig.get("rr2", 2.6), sig["lot_size"], sig["risk_amount"],
                float(ind.get("vol_ratio") or 1.0), _html_esc(ind.get("vsa_signal") or "NORMAL"),
                vote_str or "—",
                _html_esc(sig.get("summary", ""))[:280],
                _html_esc(sig.get("bull_argument", ""))[:170],
                _html_esc(sig.get("bear_argument", ""))[:170],
                sig["created_at"], _html_esc(sig.get("llm_provider", ""))
            )
        )[:1020]
        res = tg_api(cfg, "sendPhoto", {"chat_id": chat, "parse_mode": "HTML", "caption": short_caption},
                     timeout=25, file_tuple=("photo", fname, png_bytes))
        msg_id = (res.get("result") or {}).get("message_id") if isinstance(res, dict) else None
        detail_reply = (
            "📝 <b>Chi tiết biên bản họp kèo %s%s (%s):</b>\n\n"
            "📋 <b>Kết luận Trưởng nhóm:</b>\n%s\n\n"
            "🟢 <b>Phe Mua:</b>\n%s\n\n"
            "🔴 <b>Phe Bán:</b>\n%s\n\n"
            "🛡️ <b>Quản trị vốn:</b>\n%s\n\n"
            "📕 <b>Bài học kỷ luật:</b>\n%s" % (
                sid_str, sig["asset"], sig["action"],
                _html_esc(sig.get("summary", "")),
                _html_esc(sig.get("bull_argument", "")),
                _html_esc(sig.get("bear_argument", "")),
                _html_esc(sig.get("risk_note", "")),
                _html_esc(sig.get("lesson_learned", "")),
            )
        )
        send_telegram(cfg, detail_reply, reply_to_message_id=msg_id)
        return True, "đã gửi ảnh + lý do"
    except Exception as e:
        print("send_telegram_signal fallback:", e)
        return send_telegram(cfg, full_text)


def send_telegram_sl_tp_alert(cfg, sig, oc):
    """Tự động bắn thông báo kèm ảnh chụp biểu đồ cập nhật sang Telegram khi kèo chạm SL, TP1, TP2 hoặc BE."""
    token, chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not token or not chat:
        return False, "chưa cấu hình Telegram"
    outcome = oc.get("outcome", "loss")
    rsn = str(oc.get("exit_reason") or ("TP" if outcome == "win" else "SL"))
    cp = float(oc.get("close_price") or sig.get("entry") or 0.0)
    net = float(oc.get("net_profit") or 0.0)
    src_lbl = "Khớp thật MT5" if oc.get("source") == "mt5_deal" else "Theo dõi nến"
    if "TP" in rsn:
        head_icon, title_tag = "🏆", "CHẠM TAKE PROFIT (%s)" % rsn
    elif rsn == "BE":
        head_icon, title_tag = "🛡️", "ĐÓNG HOÀ VỐN (BREAKEVEN)"
    else:
        head_icon, title_tag = "🛑", "DÍNH STOP LOSS (%s)" % rsn

    votes = sig.get("votes") or {}
    right_ag, wrong_ag = [], []
    for aid in VOTERS:
        v_raw = votes.get(aid)
        v = v_raw[0] if isinstance(v_raw, (list, tuple)) else v_raw
        if v not in ("BUY", "SELL"):
            continue
        is_right = (v == sig.get("action")) == (outcome == "win")
        (right_ag if is_right else wrong_ag).append("%s:<b>%s</b>" % (VOTE_LABELS.get(aid, aid), v))

    pnl_line = "💵 Lãi/Lỗ ròng: <b>%+.2f USD</b> (%s)\n" % (net, src_lbl) if net != 0 else "📡 Nguồn xác nhận: <b>%s</b>\n" % src_lbl
    caption = (
        "%s <b>%s · KÈO #%s %s %s</b> (%s)\n"
        "🎯 Entry: <code>%s</code> → 🏁 Giá chạm: <code>%s</code>\n"
        "🛑 SL: <code>%s</code> | 💰 TP1: <code>%s</code> | 🏆 TP2: <code>%s</code>\n"
        "%s"
        "📋 Chi tiết: %s\n\n"
        "🧠 <b>Hậu kiểm & Tự học (Hermes SKILL.md):</b>\n"
        "✅ Agent bầu đúng: %s\n"
        "❌ Agent bầu sai: %s\n"
        "<i>Hệ thống đã tự động ghi nhận vào bộ não tự học và cập nhật trọng số các chuyên viên cho phiên họp tiếp theo.</i>" % (
            head_icon, title_tag, sig.get("id"), sig.get("action"), sig.get("asset"), sig.get("timeframe", "15m"),
            sig.get("entry"), "{:g}".format(cp),
            sig.get("stop_loss"), sig.get("take_profit_1"), sig.get("take_profit_2"),
            pnl_line,
            _html_esc(oc.get("detail") or ""),
            ", ".join(right_ag) if right_ag else "—",
            ", ".join(wrong_ag) if wrong_ag else "—",
        )
    )
    if not cfg.get("telegram_send_photo", True):
        return send_telegram(cfg, caption)
    try:
        sig_chart = dict(sig, _close_price=cp, _exit_reason=rsn)
        png_bytes = render_signal_chart_png(sig_chart)
        fname = "ketqua_%s_%s_%s.png" % (sig.get("asset", "XAU"), sig.get("id") or "0", rsn.replace("+", "_"))
        tg_api(cfg, "sendPhoto", {"chat_id": chat, "parse_mode": "HTML", "caption": caption[:1020]},
               timeout=25, file_tuple=("photo", fname, png_bytes))
        return True, "đã gửi ảnh kết quả " + rsn
    except Exception as e:
        print("send_telegram_sl_tp_alert fallback:", e)
        return send_telegram(cfg, caption)


# ============================================================================
# 7b. TELEGRAM LISTENER — lắng nghe tin từ kênh/nhóm (bot là admin) hoặc tin forward tới bot
# ============================================================================
TG_NEWS = deque(maxlen=120)
TG_OFFSET = {"v": 0}
NEWS_KEYWORDS = ("gold", "xau", "vàng", "btc", "bitcoin", "crypto", "fed", "fomc", "cpi", "nfp", "pce", "dxy",
                 "powell", "lãi suất", "rate", "etf", "treasury", "yield", "inflation", "lạm phát", "usd", "sec", "war", "tariff")
BULL_WORDS = ("tăng", "bull", "rally", "surge", "soar", "jump", "gain", "record", "cut rate", "hạ lãi", "inflow", "breakout", "mua")
BEAR_WORDS = ("giảm", "bear", "drop", "fall", "plunge", "crash", "slump", "sell-off", "hike", "tăng lãi", "outflow", "breakdown", "bán")


def tg_api(cfg, method, params=None, timeout=35, file_tuple=None):
    url = "https://api.telegram.org/bot%s/%s" % (cfg.get("telegram_bot_token"), method)
    if file_tuple:
        field_name, filename, raw_bytes = file_tuple
        return http_post_form_file(url, params or {}, field_name, filename, raw_bytes, timeout=timeout)
    return http_post_json(url, params or {}, timeout=timeout)


def tg_owner_id(cfg):
    return str(cfg.get("telegram_chat_id") or "").strip()


def tg_allowed_chat(cfg, chat):
    """Chỉ nhận chat có id trùng telegram_chat_id hoặc nằm trong telegram_news_chats (id / @username).
    Danh sách trống -> không nhận gì. Không so theo title vì ai cũng đặt được title trùng."""
    allow = set(x.strip().lstrip("@").lower() for x in (cfg.get("telegram_news_chats") or "").split(",") if x.strip())
    owner = tg_owner_id(cfg)
    if owner:
        allow.add(owner.lstrip("@").lower())
    if not allow or not isinstance(chat, dict):
        return False
    cid = str(chat.get("id", "")).strip()
    uname = str(chat.get("username") or "").strip().lower()
    return bool((cid and cid in allow) or (uname and uname in allow))


def tg_forwarded_by_owner(cfg, msg):
    """Tin forward chỉ được nhận khi người forward là telegram_chat_id (hoặc forward vào đúng chat đó)."""
    owner = tg_owner_id(cfg)
    if not owner:
        return False
    sender = str((msg.get("from") or {}).get("id", "")).strip()
    chat_id = str((msg.get("chat") or {}).get("id", "")).strip()
    return owner in (sender, chat_id)


def tg_handle_update(cfg, upd):
    msg = upd.get("channel_post") or upd.get("message") or upd.get("edited_channel_post")
    if not msg:
        return None
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return None
    chat = msg.get("chat", {})
    origin = msg.get("forward_origin") or {}
    is_fwd = bool(origin or msg.get("forward_from_chat") or msg.get("forward_from") or
                  msg.get("forward_sender_name") or msg.get("forward_date"))
    fwd = msg.get("forward_from_chat") or origin.get("chat") or origin.get("sender_chat")
    if is_fwd:
        if not tg_forwarded_by_owner(cfg, msg):
            return None
    elif not tg_allowed_chat(cfg, chat):
        return None
    src_chat = fwd or chat
    # Bỏ qua tin do chính bot gửi (kèo) và lệnh /start
    if text.startswith("/") or text.startswith(("🟢 <b>", "🔴 <b>", "🟡 <b>")) or "Entry:" in text and "SL:" in text:
        return None
    low = text.lower()
    relevant = any(k in low for k in NEWS_KEYWORDS)
    bull = sum(low.count(w) for w in BULL_WORDS)
    bear = sum(low.count(w) for w in BEAR_WORDS)
    item = {"title": text[:220].replace("\n", " "), "source": "Telegram:" + str(src_chat.get("title") or src_chat.get("username") or src_chat.get("id")),
            "url": "", "published": datetime.fromtimestamp(msg.get("date", time.time())).strftime("%H:%M %d/%m"),
            "ts": msg.get("date", time.time()), "relevant": relevant, "sentiment": bull - bear, "forwarded": is_fwd}
    TG_NEWS.append(item)
    return item


def telegram_listener_loop():
    time.sleep(5)
    backoff = 5
    while True:
        cfg = CONFIG
        if not (cfg.get("telegram_listen") and cfg.get("telegram_bot_token")):
            time.sleep(5)
            continue
        try:
            res = tg_api(cfg, "getUpdates", {"offset": TG_OFFSET["v"], "timeout": 25,
                                             "allowed_updates": ["message", "channel_post", "edited_channel_post"]})
            backoff = 5
            for upd in res.get("result", []):
                TG_OFFSET["v"] = upd["update_id"] + 1
                item = tg_handle_update(cfg, upd)
                if item:
                    tag = "🔥" if item["relevant"] else "💬"
                    log("macro_owl", "%s Telegram [%s]: %s" % (tag, item["source"][9:40], item["title"][:120]))
                    if item["relevant"] and not STATE["running"]:
                        set_agent("macro_owl", bubble="📨 " + item["title"][:50])
                    NEWS_CACHE["ts"] = 0  # buộc trộn lại tin
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")[:160]
            except Exception:
                pass
            print("telegram listener HTTP %s: %s" % (e.code, body))
            if e.code == 409:  # webhook đang bật hoặc 1 instance khác đang getUpdates
                try:
                    tg_api(cfg, "deleteWebhook", {"drop_pending_updates": False}, timeout=10)
                except Exception:
                    pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
        except Exception as e:
            print("telegram listener:", str(e)[:120])
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)


def telegram_news(limit=8, max_age_h=12):
    cutoff = time.time() - max_age_h * 3600
    items = [i for i in TG_NEWS if i["ts"] >= cutoff]
    items.sort(key=lambda i: (i["relevant"], i["ts"]), reverse=True)
    return items[:limit]


def news_sentiment(news):
    """Điểm cảm tính -N..+N từ tin Telegram liên quan (dùng cho Built-in Quant AI)."""
    return sum(i.get("sentiment", 0) for i in news if i.get("relevant"))


# ============================================================================
# 8. WORKFLOW 5 BƯỚC
# ============================================================================
WORKFLOW_LOCK = threading.Lock()
STEP_DELAY = float(os.environ.get("OFFICE_STEP_DELAY", "2.5"))


def pause(sec=None):
    time.sleep(STEP_DELAY if sec is None else sec)


def run_meeting(asset):
    cfg = dict(CONFIG)
    tf = cfg.get("timeframe") or "15m"
    if tf not in TF_SECONDS:
        tf = "15m"
    with STATE_LOCK:
        STATE["running"] = True
        STATE["current_asset"] = asset
        STATE["last_error"] = ""
    try:
        label = ASSETS[asset]["label"]
        log("chief_strategist", "📣 Triệu tập họp kèo %s (khung %s)." % (label, tf))
        # ---- BƯỚC 1: Cú Mèo kéo nến & tin (kéo song song cả H1/H4 vào cache) ----
        set_step(1, "Bước 1/5 · Cú Mèo kéo nến & tin tức")
        set_agent("macro_owl", status="working", bubble="Đang kéo nến %s/H1/H4 & tin nóng..." % tf, tasks=2)
        prefetch_timeframes(asset, (tf, "1h", "4h"), main_tf=tf)
        market = fetch_market(asset, tf)
        news = fetch_news()
        tk, ind = market["ticker"], market["indicators"]
        log("macro_owl", "📰 %s: giá %.2f (%+.2f%% 24h) · nguồn %s · %d nến %s." % (
            label, tk["price"], tk["change_pct"], market["source"], market["candles_count"], tf))
        log("macro_owl", "🗞️ Tin nóng: %s" % news[0]["title"][:100])
        set_agent("macro_owl", status="working", bubble="%s %.2f (%+.2f%%)" % (asset, tk["price"], tk["change_pct"]), tasks=1)
        pause()
        # ---- BƯỚC 2: 7 chuyên viên tính chỉ báo & bỏ phiếu (kèm Volume VSA) ----
        set_step(2, "Bước 2/5 · Phòng Kỹ Thuật & Cá Voi Volume tính chỉ báo")
        set_agent("vwap_hunter", status="working", bubble="Soi VWAP & dải ±1.5σ...", tasks=1)
        set_agent("smc_sniper", status="working", bubble="Soi Swing High/Low & BOS...", tasks=1)
        set_agent("trend_radar", status="working", bubble="Soi EMA 20/50/200 & RSI...", tasks=1)
        set_agent("htf_scout", status="working", bubble="Soi H1/H4: EMA50/200 & đỉnh đáy...", tasks=2)
        set_agent("regime_meter", status="working", bubble="Đo ADX, độ rộng Bollinger, ATR, spread...", tasks=1)
        set_agent("level_mapper", status="working", bubble="Dò đỉnh đáy ngày trước, phiên Á, số tròn...", tasks=1)
        set_agent("volume_whale", status="working", bubble="Đo RVOL, Volume Delta & tín hiệu VSA...", tasks=1)
        set_agent("chief_strategist", status="working", bubble="Chờ báo cáo 7 chuyên viên", tasks=len(VOTERS))
        pause(STEP_DELAY * 0.6)
        votes = {"vwap_hunter": vote_vwap(ind), "smc_sniper": vote_smc(ind), "trend_radar": vote_trend(ind)}
        v, m, htf_info = safe_vote("htf_scout", vote_htf, asset)
        votes["htf_scout"] = (v, m)
        v, m, reg_info = safe_vote("regime_meter", vote_regime, asset, ind)
        votes["regime_meter"] = (v, m)
        v, m, lv_info = safe_vote("level_mapper", vote_levels, asset, ind, market["candles"])
        votes["level_mapper"] = (v, m)
        v, m, vol_info = safe_vote("volume_whale", vote_volume, ind, market["candles"])
        votes["volume_whale"] = (v, m)
        # Quét nhanh các kèo trước đó xem có kèo nào vừa chạm SL/TP trên nến không để cập nhật bộ nhớ ngay trước khi họp
        try:
            check_open_signals_sl_tp()
        except Exception:
            pass
        mem_info = sl_tp_memory_block(asset)
        ta = {"htf": htf_info, "regime": reg_info, "levels": lv_info, "volume": vol_info, "memory": mem_info}
        ta["consensus"] = consensus(votes, reg_info.get("regime"), loss_streak=int(mem_info.get("loss_streak") or 0))
        extra = {"htf_scout": " · veto %s" % htf_info["veto"] if htf_info.get("veto") else "",
                 "regime_meter": " · %s%s" % (reg_info.get("regime", "?"), " ⛔" if reg_info.get("blocked") else ""),
                 "level_mapper": " · phiên %s" % lv_info.get("session", "?"),
                 "volume_whale": " · RVOL %.2f× (%s)" % (float(vol_info.get("vol_ratio") or 1.0), vol_info.get("vsa_signal", "NORMAL"))}
        for aid, (v, msg) in votes.items():
            set_agent(aid, status="working", bubble="Đề xuất: %s%s" % (v, extra.get(aid, "")), tasks=1)
            log(aid, "%s → %s" % (v, msg))
        cs = ta["consensus"]
        log("chief_strategist", "🧮 Điểm đồng thuận có trọng số %+.2f/%.2f (%+.0f%%, ngưỡng ±%.0f%%, trạng thái %s) → %s." % (
            cs["score"], cs["total_weight"], cs["ratio"] * 100, cs["threshold"] * 100, cs["regime"], cs["action"]))
        pause()
        # ---- BƯỚC 3: Hermes nạp SKILL.md & Hồ sơ thực chiến SL/TP ----
        set_step(3, "Bước 3/5 · Hermes nạp SKILL.md & Hồ sơ tự học SL/TP")
        set_agent("hermes_scribe", status="working", bubble="Đọc %s & lịch sử SL/TP..." % SKILL_FILES[asset], tasks=1)
        skill_full = read_skill(asset)
        skill_text = skill_rules_excerpt(skill_full)
        log("hermes_scribe", "📚 Nạp %s (%d ký tự) + Bộ nhớ thực chiến (%d Thắng / %d Thua)." % (
            SKILL_FILES[asset], len(skill_full), mem_info.get("wins", 0), mem_info.get("losses", 0)))
        pause(STEP_DELAY * 0.7)
        # ---- BƯỚC 4: Họp Bull vs Bear ----
        set_step(4, "Bước 4/5 · Họp Bull vs Bear tại Phòng Họp")
        move_all("meeting_room", status="walking", bubble="")
        log("chief_strategist", "🚶 Toàn bộ nhân sự di chuyển sang Phòng Họp Đầu Tư.", room="meeting_room")
        pause(STEP_DELAY * 1.6)
        for aid in AGENTS:
            set_agent(aid, status="meeting", tasks=1)
        set_agent("chief_strategist", bubble="Bull vs Bear, bắt đầu!")
        for aid, (v, _) in votes.items():
            set_agent(aid, bubble="Tôi bầu %s%s" % (v, extra.get(aid, "")))
        set_agent("macro_owl", bubble="Tin: %s" % news[0]["title"][:40])
        set_agent("hermes_scribe", bubble="Kiểm tra kỷ luật & SL/TP...")
        prompt = build_prompt(asset, tf, ind, tk, votes, news, skill_text, ta)
        decision, provider, errors = call_free_llm(prompt, cfg)
        for e in errors:
            log("chief_strategist", "⚠️ LLM lỗi: %s" % e, room="meeting_room")
        if decision is None:
            decision = quant_decision(asset, ind, votes, [n["title"] for n in news], skill_text, news_sentiment(news), ta)
            log("chief_strategist", "🧮 Dùng Built-in Quant AI (chưa có API key hoặc LLM lỗi).", room="meeting_room")
        else:
            log("chief_strategist", "🧠 Phản hồi từ LLM %s." % provider, room="meeting_room")
            decision = enforce_guards(decision, ta)
        if decision.get("guards"):
            log("chief_strategist", "⛔ Ép WAIT: %s" % " | ".join(decision["guards"]), room="meeting_room")
            guard_agent = "htf_scout" if (ta["htf"] or {}).get("veto") else ("volume_whale" if (ta.get("volume") or {}).get("fakeout_warning") else "regime_meter")
            set_agent(guard_agent, bubble="⛔ Không vào lệnh!")
        pause()
        log("chief_strategist", "🟢 Phe Mua: %s" % decision["bull_argument"], room="meeting_room")
        log("chief_strategist", "🔴 Phe Bán: %s" % decision["bear_argument"], room="meeting_room")
        log("chief_strategist", "⚖️ Kết luận: %s → %s (%d%%)" % (decision["summary"][:160], decision["action"],
                                                                 decision["confidence"]), room="meeting_room")
        set_agent("chief_strategist", bubble="Chốt: %s %d%%" % (decision["action"], decision["confidence"]))
        pause()
        # ---- BƯỚC 5: Rủi ro -> Hermes ghi -> Heo lưu/Telegram (kèm ảnh biểu đồ) -> Party ----
        set_step(5, "Bước 5/5 · Duyệt rủi ro, ghi bài học, lưu kèo & chụp ảnh gửi Telegram")
        live_tk, drift_note = refresh_ticker_for_plan(asset, ind, tk)
        plan = risk_plan(asset, decision["action"], ind, cfg, live_tk)
        if drift_note:
            plan["risk_note"] = drift_note + " " + plan["risk_note"]
            log("risk_guard", drift_note, room="meeting_room")
        set_agent("risk_guard", bubble="SL %s · TP1 %s · Lot %s" % (plan["stop_loss"], plan["take_profit_1"], plan["lot_size"]))
        log("risk_guard", "🛡️ Entry %s | SL %s | TP1 %s | TP2 %s | Lot %.3f | %s" % (
            plan["entry"], plan["stop_loss"], plan["take_profit_1"], plan["take_profit_2"], plan["lot_size"], plan["risk_note"][:120]),
            room="meeting_room")
        pause(STEP_DELAY * 0.7)
        line = append_lesson(asset, decision["lesson_learned"], decision["action"], decision["confidence"])
        set_agent("hermes_scribe", bubble="Ghi bài học vào SKILL.md ✍️")
        log("hermes_scribe", "✍️ Append vào %s: %s" % (SKILL_FILES[asset], line[:140]), room="meeting_room")
        pause(STEP_DELAY * 0.6)
        sig = {"created_at": now_iso(), "asset": asset, "symbol": market["source"], "timeframe": tf,
               "action": decision["action"], "confidence": decision["confidence"],
               "summary": decision["summary"], "bull_argument": decision["bull_argument"],
               "bear_argument": decision["bear_argument"], "lesson_learned": decision["lesson_learned"],
               "llm_provider": provider, "indicators": dict(ind, ta=ta), "votes": {k: v[0] for k, v in votes.items()},
               "telegram_sent": False}
        sig.update(plan)
        sig["id"] = db_insert_signal(sig)
        min_conf = int(cfg.get("telegram_min_confidence") or 0)
        if decision["action"] == "WAIT" and not cfg.get("telegram_send_wait"):
            ok, msg = False, "lọc: kèo WAIT không gửi"
        elif decision["confidence"] < min_conf:
            ok, msg = False, "lọc: tự tin %d%% < ngưỡng %d%%" % (decision["confidence"], min_conf)
        else:
            ok, msg = send_telegram_signal(cfg, sig, candles=market.get("candles"))
            if ok:
                with DB_LOCK:
                    conn = db_conn()
                    conn.execute("UPDATE signals SET telegram_sent=1 WHERE id=?", (sig["id"],))
                    conn.commit()
                    conn.close()
        sig["telegram_sent"] = ok
        set_agent("vault_piggy", bubble="Đã lưu kèo #%d %s" % (sig["id"], "📸📨" if ok else "🔒"))
        log("vault_piggy", "💾 Lưu kèo #%d vào SQLite. Telegram: %s." % (sig["id"], ("đã gửi kèm ảnh & lý do ✅ (%s)" % msg) if ok else msg), room="meeting_room")
        with STATE_LOCK:
            STATE["last_signal"] = sig
        pause(STEP_DELAY * 0.6)
        if decision["action"] in ("BUY", "SELL") and decision["confidence"] >= 75:
            move_all("party_room", status="walking")
            log("chief_strategist", "🎉 Kèo %s %d%% ≥ 75%% → cả văn phòng sang Phòng Party ăn mừng!" % (
                decision["action"], decision["confidence"]), room="party_room")
            pause(STEP_DELAY * 1.6)
            for aid in AGENTS:
                set_agent(aid, status="party", bubble="🎉 %s!" % decision["action"])
            pause(STEP_DELAY * 1.5)
        else:
            log("chief_strategist", "🧘 Kèo %s %d%% < 75%% → không ăn mừng, về bàn trực chiến." % (
                decision["action"], decision["confidence"]), room="meeting_room")
        send_home("walking")
        pause(STEP_DELAY * 1.5)
        send_home("idle")
        set_step(0, "Hoàn tất · %s %s %d%%" % (asset, decision["action"], decision["confidence"]))
        log("chief_strategist", "✅ Kết thúc phiên họp %s." % label)
        return sig
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:300])
        traceback.print_exc()
        log("chief_strategist", "❌ Lỗi phiên họp: %s" % err, room="office")
        with STATE_LOCK:
            STATE["last_error"] = err
        send_home("idle")
        set_step(0, "Lỗi: " + err[:60])
        return None
    finally:
        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_asset"] = None


def start_meeting(asset):
    if asset not in ASSETS:
        return False, "Tài sản không hợp lệ"
    if not WORKFLOW_LOCK.acquire(blocking=False):
        return False, "Đang có phiên họp khác chạy"

    def worker():
        try:
            run_meeting(asset)
        finally:
            WORKFLOW_LOCK.release()
    threading.Thread(target=worker, daemon=True, name="meeting-" + asset).start()
    return True, "Đã triệu tập họp " + asset


# ============================================================================
# 9. AUTO-PILOT 24/7 & MARKET REFRESH
# ============================================================================
def autopilot_loop():
    while True:
        try:
            if STATE["auto_pilot"]:
                interval = max(5, int(CONFIG.get("auto_interval_min") or 30)) * 60
                for asset in ("XAUUSD", "BTCUSDT"):
                    if not STATE["auto_pilot"]:
                        break
                    ok, _ = start_meeting(asset)
                    if ok:
                        time.sleep(3)
                        WORKFLOW_LOCK.acquire()
                        WORKFLOW_LOCK.release()
                    time.sleep(5)
                nxt = time.time() + interval
                with STATE_LOCK:
                    STATE["next_auto_run"] = datetime.fromtimestamp(nxt).strftime("%H:%M:%S")
                while time.time() < nxt and STATE["auto_pilot"]:
                    time.sleep(2)
            else:
                with STATE_LOCK:
                    STATE["next_auto_run"] = None
                time.sleep(3)
        except Exception as e:
            print("autopilot error:", e)
            time.sleep(10)


def market_refresh_loop():
    time.sleep(2)
    while True:
        tf = CONFIG.get("timeframe") or "15m"
        for asset in ASSETS:
            try:
                fetch_market(asset, tf, max_age=40)
            except Exception as e:
                with STATE_LOCK:
                    STATE["last_error"] = "market %s: %s" % (asset, str(e)[:120])
        try:
            fetch_news()
        except Exception:
            pass
        try:
            check_open_signals_sl_tp()
        except Exception:
            pass
        for _ in range(30):
            time.sleep(2)
            for asset in ASSETS:
                with MT5_LOCK:
                    live = any(a == asset for (a, _tf) in MT5_FEED)
                if live:
                    try:
                        fetch_market(asset, tf, max_age=1)
                    except Exception:
                        pass


# ============================================================================
# 10. HTTP SERVER
# ============================================================================
def qs_int(qs, key, default, lo=1, hi=200):
    """Lấy tham số số nguyên từ query string, kẹp trong [lo, hi]; sai định dạng -> default."""
    try:
        v = int(float((qs.get(key) or [default])[0]))
    except Exception:
        v = default
    return max(lo, min(hi, v))


class Handler(BaseHTTPRequestHandler):
    server_version = "AITradingOffice/1.0"
    timeout = 20          # timeout socket mỗi kết nối: chặn client treo giữ luồng mãi

    def log_message(self, fmt, *args):
        if os.environ.get("OFFICE_HTTP_LOG") == "1":
            super().log_message(fmt, *args)

    # --- helpers ---
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            return self.send_json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # --- auth ---
    def is_authorized(self, path):
        if not ADMIN_PASSWORD or path.startswith("/api/health"):
            return True
        token = CONFIG.get("bridge_token") or ""
        if token and path in EA_PATHS:
            got = self.headers.get("X-Bridge-Token") or ""
            if hmac.compare_digest(got.encode(), token.encode()):
                return True
        hdr = self.headers.get("Authorization") or ""
        if hdr.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(hdr[6:]).decode("utf-8").partition(":")
                return hmac.compare_digest(user.encode(), ADMIN_USER.encode()) and \
                    hmac.compare_digest(pwd.encode(), ADMIN_PASSWORD.encode())
            except Exception:
                return False
        return False

    def csrf_error(self, path):
        """Chống CSRF cho POST của dashboard (không áp dụng EA_PATHS):
        bắt buộc Content-Type application/json (form/text-plain cross-site bị chặn) và
        Origin/Referer (nếu có) phải trùng Host. Trả (code, message) nếu vi phạm, None nếu hợp lệ."""
        if path in EA_PATHS:
            return None
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return 415, "Content-Type phải là application/json"
        hosts = set(h.strip().lower() for h in ((self.headers.get("Host") or ""),
                                                 (self.headers.get("X-Forwarded-Host") or "").split(",")[0]) if h.strip())
        for hname in ("Origin", "Referer"):
            val = (self.headers.get(hname) or "").strip()
            if not val:
                continue
            netloc = urllib.parse.urlparse(val).netloc.lower() if val.lower() != "null" else ""
            if not netloc or netloc not in hosts:
                return 403, "%s không trùng Host" % hname
        return None

    def deny(self):
        body = b'{"error": "unauthorized"}'
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AI Trading Office", charset="UTF-8"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- GET ---
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path, qs = u.path, urllib.parse.parse_qs(u.query)
        if not self.is_authorized(path):
            return self.deny()
        try:
            if path in ("/", "/index.html"):
                return self.send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                fn = os.path.basename(path)
                ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css",
                         "png": "image/png", "svg": "image/svg+xml"}.get(fn.rsplit(".", 1)[-1], "application/octet-stream")
                return self.send_file(os.path.join(STATIC_DIR, fn), ctype + "; charset=utf-8")
            if path == "/api/state":
                with STATE_LOCK:
                    snap = json.loads(json.dumps(STATE, default=str))
                snap["logs"] = list(LOGS)[-80:]
                snap["config"] = {k: CONFIG.get(k) for k in ("account_balance", "risk_per_trade_pct", "timeframe", "auto_interval_min")}
                snap["llm_ready"] = any(CONFIG.get(k) for k in ("gemini_api_key", "groq_api_key", "openrouter_api_key", "custom_api_url"))
                snap["telegram_ready"] = bool(CONFIG.get("telegram_bot_token") and CONFIG.get("telegram_chat_id"))
                snap["bridge"] = mt5_status()
                snap["account"] = account_snapshot()
                snap["ea_last_config_fetch"] = STATE.get("ea_last_config_fetch")
                snap["telegram_news"] = telegram_news(10)
                snap["config"]["telegram_min_confidence"] = CONFIG.get("telegram_min_confidence")
                snap["server_time"] = now_iso()
                body = json.dumps(snap, ensure_ascii=False, default=str).encode("utf-8")
                etag = hashlib.md5(body).hexdigest()
                inm = self.headers.get("If-None-Match")
                if inm == etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("ETag", etag)
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/market":
                asset = (qs.get("symbol") or qs.get("asset") or ["XAUUSD"])[0].upper()
                tf = (qs.get("tf") or [CONFIG.get("timeframe") or "15m"])[0]
                if asset not in ASSETS:
                    return self.send_json({"error": "symbol phải là XAUUSD hoặc BTCUSDT"}, 400)
                if tf not in TF_SECONDS:
                    return self.send_json({"error": "tf phải là 5m/15m/1h/4h"}, 400)
                return self.send_json(fetch_market(asset, tf))
            if path == "/api/markets":
                tf = CONFIG.get("timeframe") or "15m"
                out = {}
                for a in ASSETS:
                    try:
                        d = fetch_market(a, tf)
                        out[a] = {k: v for k, v in d.items() if k != "candles"}
                    except Exception as e:
                        out[a] = {"error": str(e)[:200]}
                return self.send_json(out)
            if path == "/api/news":
                return self.send_json(fetch_news())
            if path == "/api/signals":
                return self.send_json(db_list_signals(qs_int(qs, "limit", 30)))
            if path == "/api/logs":
                return self.send_json(list(LOGS))
            if path == "/api/config":
                return self.send_json(masked_config())
            if path == "/api/skills":
                return self.send_json(list_skills())
            if path.startswith("/api/skills/"):
                name = urllib.parse.unquote(path[len("/api/skills/"):])
                p = safe_skill_path(name)
                if not os.path.isfile(p):
                    return self.send_json({"error": "không có file"}, 404)
                with open(p, "r", encoding="utf-8") as f:
                    return self.send_json({"name": os.path.basename(p), "content": f.read()})
            if path == "/api/stats/result":
                return self.send_json(stats_status(int((qs.get("id") or ["0"])[0])))
            if path == "/api/llm/models":
                return self.send_json(gemini_status())
            if path == "/api/ea/config":
                token = CONFIG.get("bridge_token") or ""
                if token and self.headers.get("X-Bridge-Token") != token:
                    return self.send_json({"error": "sai bridge_token"}, 403)
                with STATE_LOCK:
                    STATE["ea_last_config_fetch"] = now_iso()
                return self.send_json(ea_config())
            if path == "/api/bridge/status":
                return self.send_json(mt5_status())
            if path == "/api/executions":
                limit = qs_int(qs, "limit", 50)
                sid = qs_int(qs, "signal_id", 0, lo=0, hi=2 ** 62)
                only_ent = (qs.get("entered") or ["0"])[0] == "1"
                return self.send_json(db_list_executions(limit, sid or None, only_entered=only_ent))
            if path == "/api/sl_tp_history":
                return self.send_json(sl_tp_history(qs_int(qs, "limit", 100)))
            if path == "/api/chart.png":
                sid = int((qs.get("signal_id") or ["0"])[0])
                sig = db_get_signal(sid) if sid > 0 else None
                if not sig:
                    sigs = db_list_signals(1)
                    sig = sigs[0] if sigs else None
                if not sig:
                    return self.send_json({"error": "chưa có kèo để vẽ biểu đồ"}, 404)
                png = render_signal_chart_png(sig)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(png)
                return
            if path == "/api/agents/scorecard":
                return self.send_json(agent_scorecard(force=(qs.get("refresh") or ["0"])[0] == "1"))
            if path == "/api/health":
                return self.send_json({"ok": True, "time": now_iso(), "running": STATE["running"]})
            return self.send_json({"error": "not found"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": "%s: %s" % (type(e).__name__, e)}, 500)

    # --- POST ---
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        if not self.is_authorized(path):
            return self.deny()
        bad = self.csrf_error(path)
        if bad:
            return self.send_json({"error": bad[1]}, bad[0])
        body = self.read_body()
        if not isinstance(body, dict):
            body = {}
        try:
            if path == "/api/meeting":
                asset = str(body.get("asset", "XAUUSD")).upper()
                ok, msg = start_meeting(asset)
                return self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)
            if path == "/api/autopilot":
                enabled = bool(body.get("enabled"))
                with STATE_LOCK:
                    STATE["auto_pilot"] = enabled
                CONFIG["auto_pilot"] = enabled
                save_config(CONFIG)
                log("chief_strategist", "🤖 Auto-Pilot 24/7: %s" % ("BẬT" if enabled else "TẮT"), room="office")
                return self.send_json({"ok": True, "auto_pilot": enabled})
            if path == "/api/config":
                changed = []
                for k in DEFAULT_CONFIG:
                    if k not in body:
                        continue
                    v = body[k]
                    if k in SECRET_KEYS and (v == "" or (isinstance(v, str) and v.startswith("••"))):
                        continue  # giữ nguyên key cũ nếu để trống/masked
                    if k in ("account_balance", "risk_per_trade_pct"):
                        try:
                            v = float(v)
                        except Exception:
                            continue
                    if k in EA_INT_KEYS:
                        try:
                            v = int(float(v))
                        except Exception:
                            continue
                    if k in EA_FLOAT_KEYS:
                        try:
                            v = float(v)
                        except Exception:
                            continue
                    if k in EA_BOOL_KEYS:
                        v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                    if k == "bridge_stale_sec":
                        try:
                            v = max(10, int(v))
                        except Exception:
                            continue
                    if k == "auto_interval_min":
                        try:
                            v = max(5, int(v))
                        except Exception:
                            continue
                    if k == "timeframe" and v not in TF_SECONDS:
                        continue
                    if k == "gemini_models":
                        if not isinstance(v, list):
                            continue
                        v = [{"model": str(i.get("model", "")).strip(), "rpm": max(0, int(float(i.get("rpm") or 0))),
                              "rpd": max(0, int(float(i.get("rpd") or 0))), "enabled": bool(i.get("enabled", True))}
                             for i in v if isinstance(i, dict) and str(i.get("model", "")).strip()]
                    if k == "price_source" and v not in ("mt5_only", "auto"):
                        continue
                    if k == "gemini_strategy" and v not in ("priority", "round_robin"):
                        continue
                    if k == "llm_provider_order":
                        if not isinstance(v, list):
                            continue
                        v = [str(x) for x in v if str(x) in LLM_PROVIDERS]
                    if k == "gemini_max_attempts":
                        try:
                            v = max(1, min(15, int(v)))
                        except Exception:
                            continue
                    if k == "telegram_min_confidence":
                        try:
                            v = max(0, min(95, int(v)))
                        except Exception:
                            continue
                    if k in ("telegram_send_wait", "telegram_send_photo", "telegram_listen", "agent_auto_weight", "use_mt5_balance",
                             "telegram_alert_sl_tp", "btc_binance_fallback"):
                        v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                    if k == "quant_consensus":
                        try:
                            v = max(0.2, min(0.9, float(v)))
                        except Exception:
                            continue
                    if k == "auto_pilot":
                        v = bool(v)
                        with STATE_LOCK:
                            STATE["auto_pilot"] = v
                    if isinstance(v, str):
                        v = v.strip()
                    CONFIG[k] = v
                    changed.append(k)
                for k in body.get("clear_keys", []) or []:
                    if k in SECRET_KEYS:
                        CONFIG[k] = ""
                        changed.append(k)
                save_config(CONFIG)
                MARKET_CACHE.clear()
                SCORE_CACHE["ts"] = 0
                log("vault_piggy", "⚙️ Cập nhật cấu hình: %s" % ", ".join(changed), room="office")
                return self.send_json({"ok": True, "changed": changed, "config": masked_config()})
            if path == "/api/push_account":
                token = CONFIG.get("bridge_token") or ""
                if token and (self.headers.get("X-Bridge-Token") or body.get("token")) != token:
                    return self.send_json({"error": "sai bridge_token"}, 403)
                res = account_push(body)
                hr = stats_pending_for_ea()
                if hr:
                    res["history_request"] = hr
                return self.send_json(res)
            if path == "/api/push_history":
                token = CONFIG.get("bridge_token") or ""
                if token and self.headers.get("X-Bridge-Token") != token:
                    return self.send_json({"error": "sai bridge_token"}, 403)
                if not body:
                    n = int(self.headers.get("Content-Length") or 0)
                    with HIST_LOCK:
                        r = HIST_REQ["cur"]
                        if r and r["status"] == "pending":
                            r["last_ea_error"] = "server không đọc được JSON (%d byte)" % n
                    log("vault_piggy", "⚠️ Gói lịch sử từ EA không phải JSON hợp lệ (%d byte)" % n, room="vault_room")
                    return self.send_json({"ok": False, "error": "JSON không hợp lệ"}, 400)
                return self.send_json(stats_receive(body))
            if path == "/api/stats/request":
                magic = int(body.get("magic") or 0)
                dfrom, dto = str(body.get("from") or ""), str(body.get("to") or "")
                import re as _re
                if not _re.match(r"^\d{4}\.\d{2}\.\d{2}( \d{2}:\d{2}(:\d{2})?)?$", dfrom) or \
                   not _re.match(r"^\d{4}\.\d{2}\.\d{2}( \d{2}:\d{2}(:\d{2})?)?$", dto):
                    return self.send_json({"error": "from/to phải dạng YYYY.MM.DD hoặc YYYY.MM.DD HH:MM"}, 400)
                acc = account_snapshot()
                return self.send_json({"ok": True, "id": stats_request(magic, dfrom, dto),
                                       "ea_online": bool(acc and acc.get("online")),
                                       "ea_version": (acc or {}).get("ea_version", "")})
            if path == "/api/push_price":
                token = CONFIG.get("bridge_token") or ""
                if token and (self.headers.get("X-Bridge-Token") or body.get("token")) != token:
                    return self.send_json({"error": "sai bridge_token"}, 403)
                res = mt5_push(body)
                if res.get("tf"):
                    with MARKET_CACHE_LOCK:
                        MARKET_CACHE.pop((res["asset"], res.get("tf")), None)
                if res.get("need_full"):
                    return self.send_json(res, 409)  # Báo HTTP 409 để EA tự bật g_needFull=true và đẩy lại đủ 300 nến ngay
                return self.send_json(res)
            if path == "/api/execution":
                token = CONFIG.get("bridge_token") or ""
                if token and (self.headers.get("X-Bridge-Token") or body.get("token")) != token:
                    return self.send_json({"error": "sai bridge_token"}, 403)
                if not isinstance(body, dict) or "signal_id" not in body:
                    return self.send_json({"error": "thiếu signal_id"}, 400)
                row = db_insert_execution(body)
                if row["error"] == "dry_run":
                    msg = "🧪 EA (DryRun) mô phỏng %s %s %.3f lot @%s cho kèo #%d." % (
                        row["action"], row["symbol"], row["volume"], "{:g}".format(row["price"]), row["signal_id"])
                elif row["ticket"] and not row["error"]:
                    msg = "🤖 EA đã khớp %s %s %.3f lot @%s · ticket %d · SL %s · TP %s (kèo #%d, tài khoản %d)." % (
                        row["action"], row["symbol"], row["volume"], "{:g}".format(row["price"]), row["ticket"],
                        "{:g}".format(row["sl"]), "{:g}".format(row["tp"]), row["signal_id"], row["account"])
                else:
                    msg = "⚠️ EA không vào lệnh kèo #%d %s %s: %s" % (
                        row["signal_id"], row["action"], row["symbol"], row["error"] or "retcode %d" % row["retcode"])
                log("vault_piggy", msg, room="vault_room")
                return self.send_json({"ok": True, "id": row["id"]})
            if path == "/api/gemini/discover":
                if not CONFIG.get("gemini_api_key"):
                    return self.send_json({"error": "chưa nhập Gemini API key"}, 400)
                models, added, found = gemini_discover(CONFIG)
                CONFIG["gemini_models"] = models
                save_config(CONFIG)
                log("hermes_scribe", "🔍 Dò được %d model Gemini, thêm mới %d: %s" % (len(found), len(added), ", ".join(added)[:150]), room="office")
                return self.send_json({"ok": True, "added": added, "found": found, "status": gemini_status()})
            if path == "/api/gemini/test":
                model = str(body.get("model", "")).strip()
                if not model or not CONFIG.get("gemini_api_key"):
                    return self.send_json({"error": "thiếu model hoặc API key"}, 400)
                GEMINI_RPM_WINDOW.setdefault(model, deque(maxlen=200)).append(time.time())
                t0 = time.time()
                try:
                    text = gemini_call_model(model, 'Trả về JSON: {"action":"WAIT","confidence":50,"summary":"OK"}', CONFIG["gemini_api_key"])
                    extract_json(text)
                    usage_update(model, True, "ok", cooldown_until=0)          # test thành công -> bỏ trạng thái nghỉ
                    return self.send_json({"ok": True, "model": model, "ms": int((time.time() - t0) * 1000)})
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", "ignore")
                    usage_update(model, False, "http_%d" % e.code, body[:200])
                    msg = json.loads(body).get("error", {}).get("message", "") if body.startswith("{") else body
                    return self.send_json({"ok": False, "model": model, "error": "HTTP %d: %s" % (e.code, msg[:160])})
                except Exception as e:
                    return self.send_json({"ok": False, "model": model, "error": str(e)[:160]})
            if path == "/api/gemini/reset_cooldown":
                day, _ = pacific_day_and_reset()
                with DB_LOCK:
                    conn = db_conn()
                    conn.execute("UPDATE llm_usage SET cooldown_until=0 WHERE day=?", (day,))
                    conn.commit()
                    conn.close()
                return self.send_json({"ok": True, "status": gemini_status()})
            if path == "/api/telegram/test":
                sigs = db_list_signals(1)
                if CONFIG.get("telegram_send_photo", True) and sigs:
                    ok, msg = send_telegram_signal(CONFIG, sigs[0])
                else:
                    ok, msg = send_telegram(CONFIG, "✅ Văn Phòng AI Trading: kết nối Telegram thành công!")
                return self.send_json({"ok": ok, "message": msg})
            if path == "/api/llm/test":
                obj, provider, errors = call_free_llm(
                    'Trả về JSON: {"action":"WAIT","confidence":50,"bull_argument":"test","bear_argument":"test","summary":"Kết nối OK","lesson_learned":"test"}',
                    CONFIG)
                return self.send_json({"ok": obj is not None, "provider": provider, "errors": errors, "result": obj})
            return self.send_json({"error": "not found"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": "%s: %s" % (type(e).__name__, e)}, 500)


def main():
    db_init()
    load_mt5_cache()
    load_mt5_cache()
    log("chief_strategist", "🏢 Văn phòng mở cửa. Khung %s · Quỹ $%s · Rủi ro %s%%/lệnh." % (
        CONFIG.get("timeframe"), "{:,.0f}".format(float(CONFIG.get("account_balance") or 0)),
        CONFIG.get("risk_per_trade_pct")), room="office")
    account_load_history()
    threading.Thread(target=market_refresh_loop, daemon=True, name="market").start()
    threading.Thread(target=autopilot_loop, daemon=True, name="autopilot").start()
    threading.Thread(target=telegram_listener_loop, daemon=True, name="tg-listener").start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    if not ADMIN_PASSWORD:
        if HOST in ("0.0.0.0", "", "::"):
            print("\033[1;31m" + "!" * 78 + "\n"
                  "!!  CẢNH BÁO: server bind %s:%d mà KHÔNG có OFFICE_ADMIN_PASSWORD.\n"
                  "!!  Ai vào được cổng này đều xem/sửa cấu hình, API key, bật Auto-Pilot.\n"
                  "!!  Đặt OFFICE_ADMIN_PASSWORD trong biến môi trường hoặc file .env cạnh server.py.\n"
                  % (HOST or "*", PORT) + "!" * 78 + "\033[0m", flush=True)
        else:
            print("⚠️  Chưa đặt OFFICE_ADMIN_PASSWORD: dashboard KHÔNG có mật khẩu, đừng mở cổng ra Internet.", flush=True)
    print("🏢 AI Trading Office chạy tại http://%s:%d  (Ctrl+C để dừng)" % (HOST if HOST != "0.0.0.0" else "localhost", PORT), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nĐóng cửa văn phòng.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
