#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MT5 Bridge — đẩy giá realtime (bid/ask) và nến từ MetaTrader 5 lên Văn Phòng AI Trading.

Chạy trên máy Windows đã cài MetaTrader 5 và đăng nhập tài khoản:
    pip install MetaTrader5
    python mt5_bridge.py --server http://IP_SERVER:8080 --gold XAUUSD --btc BTCUSD

Chỉ cần thư viện MetaTrader5 (của MetaQuotes); phần còn lại là Python stdlib.
Server sẽ ưu tiên nguồn MT5 trước Binance khi dữ liệu còn tươi (< bridge_stale_sec, mặc định 90s).
"""
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

try:
    import MetaTrader5 as mt5
except ImportError:
    print("Thiếu thư viện MetaTrader5. Cài bằng:  pip install MetaTrader5  (chỉ hỗ trợ Windows)")
    sys.exit(1)

TF_MAP = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4}


def post(url, payload, token, timeout=8):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Bridge-Token"] = token
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rates_to_candles(rates):
    out = []
    for r in rates:
        out.append({"t": int(r["time"]), "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                    "c": float(r["close"]), "v": float(r["real_volume"] or r["tick_volume"])})
    return out


def build_tick(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    bid, ask = float(tick.bid), float(tick.ask)
    last = float(tick.last) if tick.last else (bid + ask) / 2.0
    # Biến động 24h từ 24 nến H1 gần nhất
    h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 25)
    change_pct, high24, low24, vol24 = 0.0, bid, bid, 0.0
    if h1 is not None and len(h1) > 1:
        base = float(h1[0]["close"])
        change_pct = (last - base) / base * 100 if base else 0.0
        high24 = max(float(x["high"]) for x in h1[1:])
        low24 = min(float(x["low"]) for x in h1[1:])
        vol24 = sum(float(x["tick_volume"]) for x in h1[1:])
    return {"bid": bid, "ask": ask, "last": last, "change_pct": change_pct,
            "high24": max(high24, last), "low24": min(low24, last), "volume24": vol24}


def main():
    ap = argparse.ArgumentParser(description="Đẩy giá MT5 lên AI Trading Office")
    ap.add_argument("--server", default="http://localhost:8080", help="URL server văn phòng")
    ap.add_argument("--gold", default="XAUUSD", help="Tên symbol vàng trên broker (XAUUSD, GOLD, XAUUSDm...)")
    ap.add_argument("--btc", default="BTCUSD", help="Tên symbol Bitcoin trên broker (BTCUSD, BTCUSDT, để trống nếu không có)")
    ap.add_argument("--tfs", default="5m,15m,1h,4h", help="Các khung nến cần đẩy")
    ap.add_argument("--bars", type=int, default=300, help="Số nến mỗi khung")
    ap.add_argument("--tick-interval", type=float, default=1.0, help="Giây giữa 2 lần đẩy tick")
    ap.add_argument("--candle-interval", type=float, default=15.0, help="Giây giữa 2 lần đẩy nến")
    ap.add_argument("--token", default="", help="bridge_token trùng với cấu hình server (nếu đặt)")
    ap.add_argument("--login", type=int, default=0, help="Số tài khoản MT5 (tuỳ chọn, mặc định dùng terminal đang mở)")
    ap.add_argument("--password", default="")
    ap.add_argument("--mt5-server", default="", help="Tên server broker (tuỳ chọn)")
    ap.add_argument("--path", default="", help="Đường dẫn terminal64.exe (tuỳ chọn)")
    args = ap.parse_args()

    kw = {}
    if args.path:
        kw["path"] = args.path
    if args.login:
        kw.update(login=args.login, password=args.password, server=args.mt5_server)
    if not mt5.initialize(**kw):
        print("Không khởi tạo được MT5:", mt5.last_error())
        sys.exit(1)
    info = mt5.account_info()
    print("MT5 kết nối: %s | tài khoản %s | %s" % (mt5.version(), info.login if info else "?", info.server if info else ""))

    symbols = {"XAUUSD": args.gold}
    if args.btc:
        symbols["BTCUSDT"] = args.btc
    for asset, sym in list(symbols.items()):
        if not mt5.symbol_select(sym, True):
            print("⚠️ Không chọn được symbol %s cho %s (bỏ qua). Kiểm tra tên symbol trong Market Watch." % (sym, asset))
            symbols.pop(asset)
    if not symbols:
        print("Không có symbol nào hợp lệ.")
        sys.exit(1)
    tfs = [t.strip() for t in args.tfs.split(",") if t.strip() in TF_MAP]
    url = args.server.rstrip("/") + "/api/push_price"
    print("Đẩy %s khung %s lên %s" % (symbols, tfs, url))

    last_candle_push = 0.0
    errors = 0
    while True:
        t0 = time.time()
        push_candles = t0 - last_candle_push >= args.candle_interval
        for asset, sym in symbols.items():
            try:
                tick = build_tick(sym)
                if tick is None:
                    continue
                if push_candles:
                    for tf in tfs:
                        rates = mt5.copy_rates_from_pos(sym, TF_MAP[tf], 0, args.bars)
                        if rates is None or len(rates) < 30:
                            continue
                        post(url, {"asset": asset, "symbol": sym, "tick": tick, "tf": tf,
                                   "candles": rates_to_candles(rates)}, args.token)
                else:
                    post(url, {"asset": asset, "symbol": sym, "tick": tick}, args.token)
                errors = 0
                print("\r%s  %s %s bid %.2f ask %.2f %s" % (datetime.now().strftime("%H:%M:%S"), asset, sym, tick["bid"], tick["ask"],
                                                            "(+nến)" if push_candles else "      "), end="", flush=True)
            except urllib.error.HTTPError as e:
                errors += 1
                print("\nLỗi server %s: %s" % (e.code, e.read()[:120]))
            except Exception as e:
                errors += 1
                print("\nLỗi:", str(e)[:150])
        if push_candles:
            last_candle_push = t0
        if errors > 20:
            print("\nQuá nhiều lỗi liên tiếp, chờ 30s...")
            time.sleep(30)
            errors = 0
        time.sleep(max(0.2, args.tick_interval - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDừng bridge.")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
