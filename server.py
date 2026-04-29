"""
Special K Forex - Full Dashboard Server
Mirrors the equity dashboard with forex-specific adaptations.
"""
import os, logging, threading, datetime
from functools import wraps
from flask import Flask, jsonify, render_template_string, request, session, redirect
from dotenv import load_dotenv
import pytz

load_dotenv()

import collections as _collections
_LOG_BUFFER = _collections.deque(maxlen=200)

class _BufferHandler(logging.Handler):
    def emit(self, record):
        _LOG_BUFFER.append({"t": datetime.datetime.utcnow().strftime("%H:%M:%S"), "lvl": record.levelname, "msg": self.format(record)})

_buf_handler = _BufferHandler()
_buf_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO)
logging.getLogger().addHandler(_buf_handler)
log = logging.getLogger("server")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "specialk-forex-2026")
DASH_PASSWORD  = os.environ.get("DASHBOARD_PASSWORD", "changeme")

RISK_LEVEL   = {"value": 5}
_ENGINE_LOCK = threading.Lock()  # prevents concurrent engine runs
_alpaca_key  = os.environ.get("ALPACA_API_KEY", "")
LIVE_MODE    = {"value": (
    os.environ.get("ALPACA_PAPER", "true").strip().lower() == "false"
    or _alpaca_key.startswith("AK")
)}

# ── Budget persistence ─────────────────────────────────────────────────────────
import json as _json
_SETTINGS_FILE = "logs/settings.json"

def _load_settings():
    try:
        os.makedirs("logs", exist_ok=True)
        with open(_SETTINGS_FILE) as _f:
            return _json.load(_f)
    except Exception:
        return {}

def _save_settings(data: dict):
    try:
        os.makedirs("logs", exist_ok=True)
        existing = _load_settings()
        existing.update(data)
        with open(_SETTINGS_FILE, "w") as _f:
            _json.dump(existing, _f)
    except Exception as _e:
        log.warning(f"Could not save settings: {_e}")

_saved = _load_settings()
TRADE_BUDGET = {"value": _saved.get("trade_budget", float(os.environ.get("TRADE_BUDGET", "0")))}  # 0 = unlimited
TRADE_LOG  = []
_SERVER_START    = datetime.datetime.utcnow()
_LAST_ENGINE_RUN = {"time": None, "result": "not run yet"}
_periods_cache   = {"data": None, "at": 0.0}
_PERIODS_TTL     = 900
_scan_cache      = {"data": None, "at": 0.0}
_SCAN_TTL        = 600   # 10 minutes — scan is expensive (16 Claude calls)
_prev_close_cache = {}

# ── Currency ETF reference ────────────────────────────────────────────────────
FOREX_PAIRS = {
    "FXE": "EUR/USD", "FXB": "GBP/USD", "FXY": "USD/JPY (inv)",
    "FXC": "USD/CAD (inv)", "FXA": "AUD/USD", "UUP": "USD Index",
}

# ── Auto-seed on startup ──────────────────────────────────────────────────────
def _auto_seed():
    import time; time.sleep(8)
    try:
        trades = _alpaca_orders_as_trades()
        TRADE_LOG.clear(); TRADE_LOG.extend(trades)
        _periods_cache["data"] = None
        log.info(f"Auto-seed complete: {len(trades)} trades loaded")
    except Exception as e:
        log.warning(f"Auto-seed failed: {e}")
    # Kick off trend memory build after seed
    threading.Thread(target=_refresh_trend_memory, daemon=True).start()

threading.Thread(target=_auto_seed, daemon=True).start()

# ── Trend memory (AI learns market trends daily) ───────────────────────────────
def _refresh_trend_memory():
    try:
        from special_k_forex.trend_memory import refresh_memory, needs_refresh
        if not needs_refresh():
            log.info("Trend memory: still fresh, skipping refresh")
            return
        from special_k_forex.config import settings
        from special_k_forex.data import MarketDataClient
        from special_k_forex.indicators import compute_indicators
        client = MarketDataClient()
        refresh_memory(settings.symbols, FOREX_PAIRS, client, compute_indicators)
    except Exception as e:
        log.warning(f"Trend memory refresh error: {e}")

def _trend_memory_daily_loop():
    """Re-run trend memory analysis once per day."""
    import time
    while True:
        time.sleep(86400)  # 24 hours
        threading.Thread(target=_refresh_trend_memory, daemon=True).start()

# ── Risk params ───────────────────────────────────────────────────────────────
def get_risk_params():
    r = RISK_LEVEL["value"]
    # Stop gets tighter as risk increases (more aggressive entries)
    stop_mult = round(1.8 - (r - 1) * 0.06, 2)   # r=1→1.80, r=10→1.26
    # TP is always 2.5x the stop multiplier — guarantees ≥2.5 R:R at every risk level
    tp_mult   = round(stop_mult * 2.6, 2)
    # min_signal_score: higher risk allows more positions but requires SAME quality
    # floor at 5 so we never allow garbage signals regardless of risk setting
    min_score = max(5, 8 - r // 2)               # r=1→8, r=5→6, r=10→5
    return {
        "risk_per_trade_pct":           round(0.25 + (r - 1) * 0.2, 2),
        "stop_atr_multiplier":          stop_mult,
        "take_profit_atr_multiplier":   tp_mult,
        "min_signal_score":             min_score,
        "max_positions":                min(2 + r // 3, 6),
    }

def is_market_open():
    et = pytz.timezone("America/New_York")
    now = datetime.datetime.now(et)
    if now.weekday() >= 5: return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close

def get_broker():
    from special_k_forex.broker import Broker
    return Broker()

# ETFs associated with each world market session
_MARKET_ETFS = {
    "tokyo":     ["FXY", "EWJ"],
    "hong_kong": ["EWH", "EEM"],
    "mumbai":    ["EEM"],
    "frankfurt": ["FXE", "FXF", "EWG"],
    "london":    ["FXB", "FXS", "EWU"],
    "sydney":    ["FXA", "EWA"],
}

def _prioritise_symbols(symbols: list) -> list:
    try:
        from special_k_forex.market_hours import get_market_status
        open_markets = {m["id"] for m in get_market_status() if m["open"]}
        priority = []
        for mid, etfs in _MARKET_ETFS.items():
            if mid in open_markets:
                priority.extend(e for e in etfs if e in symbols and e not in priority)
        rest = [s for s in symbols if s not in priority]
        if priority:
            log.info(f"[MARKET] Prioritising {priority} (open: {open_markets & set(_MARKET_ETFS)})")
        return priority + rest
    except Exception:
        return symbols

def run_engine(dry=None):
    if os.environ.get("DISABLE_TRADING", "").strip().lower() == "true":
        log.info("DISABLE_TRADING=true — engine skipped.")
        return
    if not _ENGINE_LOCK.acquire(blocking=False):
        log.info("Engine already running — skipping concurrent run.")
        return
    try:
        dry = dry if dry is not None else not LIVE_MODE["value"]
        log.info(f"Running crypto engine | live={LIVE_MODE['value']}")
        from special_k_forex.crypto_engine import CryptoEngine
        from special_k_forex.config import Settings
        cfg = Settings()
        if TRADE_BUDGET["value"] > 0:
            cfg.trade_budget = TRADE_BUDGET["value"]
        CryptoEngine(cfg, dry_run=dry).run()
        _LAST_ENGINE_RUN["time"]   = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _LAST_ENGINE_RUN["result"] = "ok"
        # Refresh trade log
        fresh = _alpaca_orders_as_trades()
        if len(fresh) > len(TRADE_LOG):
            TRADE_LOG.clear(); TRADE_LOG.extend(fresh)
            _periods_cache["data"] = None
    except Exception as e:
        log.error(f"Engine error: {e}")
        _LAST_ENGINE_RUN["result"] = str(e)
    finally:
        _ENGINE_LOCK.release()

def scheduler_loop():
    import time as _time
    _last_crypto_run = 0.0
    while True:
        try:
            if os.environ.get("DISABLE_TRADING", "").strip().lower() != "true":
                if _time.monotonic() - _last_crypto_run >= 900:  # every 15 min, 24/7
                    if not _ENGINE_LOCK.acquire(blocking=False):
                        log.info("Scheduler: engine already running — skipping this cycle.")
                    else:
                        try:
                            from special_k_forex.crypto_engine import CryptoEngine
                            from special_k_forex.config import Settings
                            cfg = Settings()
                            if TRADE_BUDGET["value"] > 0:
                                cfg.trade_budget = TRADE_BUDGET["value"]
                            CryptoEngine(cfg, dry_run=not LIVE_MODE["value"]).run()
                        finally:
                            _ENGINE_LOCK.release()
                    _last_crypto_run = _time.monotonic()
        except Exception as e:
            log.error(f"Scheduler error: {e}")
        _time.sleep(300)

threading.Thread(target=scheduler_loop, daemon=True).start()
threading.Thread(target=_trend_memory_daily_loop, daemon=True).start()
log.info("Crypto-only scheduler started — runs every 15 min 24/7")

# ── Auth ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"): return redirect("/login")
        return f(*args, **kwargs)
    return decorated

# ── Trade history helpers ──────────────────────────────────────────────────────
def _alpaca_orders_as_trades():
    try:
        broker = get_broker()
        orders = broker.get_closed_orders(limit=500) if hasattr(broker, "get_closed_orders") else []
        def _ts(o):
            t = getattr(o,"filled_at",None) or getattr(o,"created_at",None)
            return str(t) if t else ""
        def _fl(v):
            try: return float(v or 0)
            except: return 0.0
        def _oval(o, attr):
            v = getattr(o, attr, None)
            return str(getattr(v, "value", v) or "").lower()
        buys  = [o for o in orders if _oval(o,"side")=="buy"  and _oval(o,"status")=="filled"]
        sells = [o for o in orders if _oval(o,"side")=="sell" and _oval(o,"status")=="filled"]
        sells_by_sym = {}
        for s in sells: sells_by_sym.setdefault(getattr(s,"symbol",""), []).append(s)
        for sym in sells_by_sym: sells_by_sym[sym].sort(key=_ts)
        trades = []; used = set()
        for buy in sorted(buys, key=_ts):
            sym   = getattr(buy,"symbol","")
            entry = _fl(getattr(buy,"filled_avg_price",0))
            qty   = int(_fl(getattr(buy,"filled_qty",0)))
            bt    = _ts(buy)
            if not entry or not qty: continue
            matched = None
            for s in sells_by_sym.get(sym, []):
                sid = str(getattr(s,"id",id(s)))
                if sid not in used and _ts(s) >= bt:
                    matched = s; used.add(sid); break
            exit_p  = _fl(getattr(matched,"filled_avg_price",0)) if matched else None
            pnl     = round((exit_p - entry) * qty, 2) if exit_p else None
            pnl_pct = round((exit_p - entry) / entry * 100, 2) if exit_p and entry else None
            trades.append({
                "time": bt[:16].replace("T"," "), "symbol": sym,
                "pair": FOREX_PAIRS.get(sym, sym),
                "side": "long", "qty": qty, "entry": entry, "exit": exit_p,
                "pnl": pnl, "pnl_pct": pnl_pct, "score": None,
                "exit_reason": "bracket_fill" if matched else None,
                "status": "closed" if exit_p else "open",
                "entry_time_iso": bt, "duration_min": None, "notes": [],
            })
        log.info(f"Trade pull: {len(trades)} trades ({sum(1 for t in trades if t['status']=='closed')} closed)")
        return trades
    except Exception as e:
        log.error(f"Trade pull failed: {e}"); return []

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == DASH_PASSWORD:
            session["logged_in"] = True; return redirect("/")
        error = "Wrong password"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear(); return redirect("/login")

@app.route("/")
@login_required
def index():
    return render_template_string(HTML)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/account")
@login_required
def api_account():
    try:
        b = get_broker(); a = b.get_account()
        pos = b.get_positions(); orders = b.get_open_orders()
        up = sum(float(p.unrealized_pl or 0) for p in pos)

        def _is_crypto_sym(sym: str) -> bool:
            s = sym.upper()
            # Crypto Alpaca symbols: BTCUSD, ETHUSD, SOLUSDT etc (6+ chars ending USD/USDT)
            return (len(s) >= 6 and (s.endswith("USD") or s.endswith("USDT"))) or "/" in s

        crypto_deployed = sum(abs(float(p.market_value or 0)) for p in pos if _is_crypto_sym(p.symbol))
        stock_deployed  = sum(abs(float(p.market_value or 0)) for p in pos if not _is_crypto_sym(p.symbol))
        crypto_pnl      = sum(float(p.unrealized_pl or 0) for p in pos if _is_crypto_sym(p.symbol))
        stock_pnl       = sum(float(p.unrealized_pl or 0) for p in pos if not _is_crypto_sym(p.symbol))

        pos_list = [{
            "symbol": p.symbol,
            "pair": FOREX_PAIRS.get(p.symbol, p.symbol),
            "qty": float(p.qty or 0),
            "side": str(getattr(p.side, "value", p.side) or "long"),
            "avg_entry_price": float(p.avg_entry_price or 0),
            "current_price":   float(p.current_price or 0),
            "market_value":    float(p.market_value or 0),
            "unrealized_pl":   float(p.unrealized_pl or 0),
            "unrealized_plpc": float(p.unrealized_plpc or 0),
            "is_crypto":       _is_crypto_sym(p.symbol),
        } for p in pos]
        ord_list = [{
            "id":          str(o.id),
            "symbol":      o.symbol,
            "side":        str(getattr(o.side, "value", o.side) or ""),
            "qty":         float(o.qty or 0),
            "filled_qty":  float(o.filled_qty or 0),
            "type":        str(getattr(o.type, "value", o.type) or ""),
            "limit_price": float(o.limit_price or 0) if o.limit_price else None,
            "status":      str(getattr(o.status, "value", o.status) or ""),
            "created_at":  str(o.created_at)[:19] if o.created_at else "",
        } for o in orders]
        return jsonify({
            "account": {"equity": float(a.equity or 0), "cash": float(a.cash or 0),
                        "buying_power": float(a.buying_power or 0), "last_equity": float(a.last_equity or 0)},
            "unrealized_pnl": up, "position_count": len(pos), "order_count": len(orders),
            "positions": pos_list, "orders": ord_list,
            "crypto_deployed": round(crypto_deployed, 2),
            "stock_deployed":  round(stock_deployed, 2),
            "crypto_pnl":      round(crypto_pnl, 2),
            "stock_pnl":       round(stock_pnl, 2),
        })
    except Exception as e:
        log.error(f"/api/account error: {e}")
        return jsonify({"error": str(e), "account": {}, "unrealized_pnl": 0, "position_count": 0, "order_count": 0, "positions": [], "orders": []})

@app.route("/api/positions")
@login_required
def api_positions():
    try:
        pos = get_broker().get_positions()
        return jsonify({"positions": [{
            "symbol": p.symbol, "pair": FOREX_PAIRS.get(p.symbol, p.symbol),
            "qty": float(p.qty or 0), "side": str(getattr(p.side,"value",p.side) or "long"),
            "avg_entry_price": float(p.avg_entry_price or 0),
            "current_price":   float(p.current_price or 0),
            "market_value":    float(p.market_value or 0),
            "unrealized_pl":   float(p.unrealized_pl or 0),
            "unrealized_plpc": float(p.unrealized_plpc or 0),
        } for p in pos]})
    except Exception as e:
        return jsonify({"error": str(e), "positions": []})

@app.route("/api/quotes")
@login_required
def api_quotes():
    try:
        import time
        from special_k_forex.config import settings
        from special_k_forex.data import MarketDataClient
        client = MarketDataClient()
        out = {}
        for sym in settings.symbols:
            q = client.get_latest_quote(sym)
            if not q: continue
            price = float(q.get("ask") or q.get("bid") or 0)
            cached = _prev_close_cache.get(sym)
            if not cached or (time.time() - cached[1]) > 300:
                bars = client.get_daily_bars(sym, days=5)
                prev = float(bars.iloc[-2]["close"]) if bars is not None and len(bars) >= 2 else None
                if prev: _prev_close_cache[sym] = (prev, time.time())
            else:
                prev = cached[0]
            chg = round((price - prev) / prev * 100, 2) if prev and price else None
            out[sym] = {"price": price, "bid": q.get("bid",0), "ask": q.get("ask",0),
                        "change_pct": chg, "prev_close": prev, "pair": FOREX_PAIRS.get(sym,sym)}
        return jsonify({"quotes": out})
    except Exception as e:
        return jsonify({"error": str(e), "quotes": {}})

def _run_scan_background():
    """Run the full crypto scan in background and populate the scan cache."""
    try:
        from special_k_forex.crypto_data import CryptoDataClient, CRYPTO_SYMBOLS
        from special_k_forex.crypto_engine import CryptoStrategy
        from special_k_forex.indicators import compute_crypto_indicators, classify_regime
        from special_k_forex.ai_analyst import analyse_crypto_signal
        from special_k_forex.crypto_signals import get_market_context
        import pandas as _pd
        import time as _time

        client = CryptoDataClient()
        strat  = CryptoStrategy()
        results = []

        def _safe(val, rnd=4):
            try: return round(float(val), rnd) if not _pd.isna(val) else None
            except: return None

        # Fetch market-wide context once for the whole scan
        try:
            mkt = get_market_context("BTC/USD")
            on_chain_score = mkt.get("total_on_chain_score", 0)
        except Exception:
            mkt = {}
            on_chain_score = 0

        for sym in CRYPTO_SYMBOLS:
            bars = client.get_daily_bars(sym)
            if bars is None or len(bars) < 60:
                results.append({
                    "symbol": sym, "pair": sym, "signal": None, "score": 0,
                    "notes": [], "regime": "normal", "last_close": None,
                    "rsi": None, "ema20": None, "ema50": None, "atr": None,
                    "trend_up": False, "direction": None,
                })
                continue

            df   = compute_crypto_indicators(bars)
            last = df.iloc[-1]
            regime = classify_regime(df)

            long_sig     = strat.evaluate(sym, bars)
            breakout_sig = strat.evaluate_breakout(sym, bars)
            bounce_sig   = strat.evaluate_bounce(sym, bars)
            all_sigs     = [s for s in [long_sig, breakout_sig, bounce_sig] if s is not None]
            sig = max(all_sigs, key=lambda s: s.score) if all_sigs else None

            ai_data = {}
            if sig:
                try:
                    sym_ctx = get_market_context(sym)
                    ai_data = analyse_crypto_signal(
                        symbol=sym, regime=regime,
                        score=sig.score + on_chain_score,
                        rsi=_safe(last.get("rsi"), 1) or 50,
                        adx=_safe(last.get("adx"), 1) or 20,
                        atr=_safe(last.get("atr14")) or 0,
                        price=_safe(last["close"]) or 0,
                        sma50=_safe(last.get("ema50")) or 0,
                        sma200=_safe(last.get("ema200")) or 0,
                        macd_hist=_safe(last.get("macd_hist"), 5) or 0,
                        pullback_10d_pct=_safe(last.get("pullback_from_high"), 2) or 0,
                        notes=sig.notes,
                        direction=sig.direction,
                        on_chain_context=sym_ctx,
                    )
                except Exception:
                    ai_data = {}

            results.append({
                "symbol": sym, "pair": sym,
                "signal": sig.action if sig else None,
                "direction": sig.direction if sig else None,
                "score": (sig.score + on_chain_score) if sig else 0,
                "notes": sig.notes if sig else [],
                "long_score":     long_sig.score     if long_sig     else 0,
                "breakout_score": breakout_sig.score if breakout_sig else 0,
                "bounce_score":   bounce_sig.score   if bounce_sig   else 0,
                "regime": regime,
                "last_close": _safe(last["close"]),
                "rsi":   _safe(last.get("rsi"), 1),
                "ema20": _safe(last.get("ema20")),
                "ema50": _safe(last.get("ema50")),
                "atr":   _safe(last.get("atr14")),
                "macd_hist": _safe(last.get("macd_hist"), 5),
                "vol_ratio": _safe(last.get("vol_ratio"), 2),
                "trend_up": bool(
                    _safe(last.get("ema20")) and _safe(last.get("ema50"))
                    and float(last["close"]) > float(last.get("ema20", 0)) > float(last.get("ema50", 0))
                ),
                "ai_confidence": ai_data.get("confidence"),
                "ai_action":     ai_data.get("action"),
                "ai_reason":     ai_data.get("reason"),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        _scan_cache["data"] = {"results": results, "ai_overview": "", "scanned_at": _time.time()}
        _scan_cache["at"] = _time.time()
        log.info(f"Background crypto scan complete: {len(results)} symbols")
    except Exception as e:
        log.error(f"Background scan error: {e}")


# Pre-warm scan cache on startup (defined after the function)
threading.Thread(target=_run_scan_background, daemon=True).start()


@app.route("/api/scan")
@login_required
def api_scan():
    """Score all watchlist symbols and return signals — forex research tab."""
    # Return cached results immediately if fresh (< 10 min old)
    if _scan_cache["data"] and (_time.time() - _scan_cache["at"]) < _SCAN_TTL:
        return jsonify(_scan_cache["data"])
    # No fresh cache — kick off background scan and return skeleton immediately
    threading.Thread(target=_run_scan_background, daemon=True).start()
    return jsonify({"results": [], "ai_overview": "", "scanning": True, "message": "Scan started — refresh in 30 seconds"})

# ── Scan trigger: also exposed as POST to force a fresh scan ─────────────────
@app.route("/api/scan/refresh", methods=["POST"])
@login_required
def api_scan_refresh():
    _scan_cache["data"] = None  # invalidate cache
    threading.Thread(target=_run_scan_background, daemon=True).start()
    return jsonify({"status": "scan started"})


@app.route("/api/trade_log")
@login_required
def api_trade_log():
    try:
        fresh = _alpaca_orders_as_trades()
        TRADE_LOG.clear(); TRADE_LOG.extend(fresh)
        _periods_cache["data"] = None
        return jsonify({"trades": TRADE_LOG, "count": len(TRADE_LOG)})
    except Exception as e:
        return jsonify({"trades": TRADE_LOG, "error": str(e), "count": len(TRADE_LOG)})

@app.route("/api/performance")
@login_required
def api_performance():
    try:
        trades = TRADE_LOG or _alpaca_orders_as_trades()
        closed = [t for t in trades if t.get("status")=="closed" and t.get("pnl") is not None]
        wins   = [t for t in closed if (t.get("pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl") or 0) <= 0]
        total_pnl = sum(t.get("pnl") or 0 for t in closed)
        gw = sum(t.get("pnl",0) for t in wins)
        gl = abs(sum(t.get("pnl",0) for t in losses))
        return jsonify({"summary": {
            "total_trades": len(closed), "open_trades": len(trades) - len(closed),
            "win_rate":     round(len(wins)/len(closed)*100,1) if closed else 0,
            "total_pnl":    round(total_pnl,2),
            "avg_pnl":      round(total_pnl/len(closed),2) if closed else 0,
            "best_trade":   round(max((t.get("pnl",0) for t in closed),default=0),2),
            "worst_trade":  round(min((t.get("pnl",0) for t in closed),default=0),2),
            "profit_factor": round(gw/gl,2) if gl > 0 else None,
            "avg_win":      round(gw/len(wins),2) if wins else 0,
            "avg_loss":     round(gl/len(losses),2) if losses else 0,
        }})
    except Exception as e:
        return jsonify({"error": str(e), "summary": {}})

@app.route("/api/periods")
@login_required
def api_periods():
    import time as _time
    from datetime import datetime as _dt, timezone as _tz, date as _date, timedelta as _td
    if _periods_cache["data"] and (_time.time() - _periods_cache["at"]) < _PERIODS_TTL:
        return jsonify(_periods_cache["data"])
    try:
        broker = get_broker()
        current_equity = float(broker.get_account().equity or 0)
        eq_history = []
        try:
            h = broker.get_portfolio_history(period="1A", timeframe="1D")
            for ts, eq in zip(getattr(h,"timestamp",None) or [], getattr(h,"equity",None) or []):
                if not eq: continue
                try:
                    d = _dt.fromtimestamp(float(ts), tz=_tz.utc).strftime("%Y-%m-%d")
                    eq_history.append({"date": d, "equity": round(float(eq),2)})
                except: pass
        except Exception as eh:
            log.warning(f"Portfolio history unavailable: {eh}")

        today       = _date.today()
        week_start  = today - _td(days=today.weekday())
        month_start = today.replace(day=1)
        year_start  = today.replace(month=1, day=1)

        def equity_at(start):
            s = start.isoformat(); baseline = None
            for e in eq_history:
                if e["date"] <= s: baseline = e["equity"]
            return baseline

        trades = TRADE_LOG or _alpaca_orders_as_trades()
        closed = [t for t in trades if t.get("status")=="closed" and t.get("pnl") is not None]

        def parse_date(t):
            ts = t.get("entry_time_iso") or t.get("time") or ""
            try:
                return _dt.fromisoformat(ts).date() if "T" in ts else _dt.strptime(ts[:10],"%Y-%m-%d").date()
            except: return None

        def build_period(start):
            pts = [t for t in closed if (parse_date(t) or _date.min) >= start]
            # Always use sum of actual closed trade P&Ls — never equity delta.
            # Equity delta includes deposits/withdrawals which are NOT trading income.
            pnl = round(sum(float(t.get("pnl") or 0) for t in pts), 2)
            wins = sum(1 for t in pts if float(t.get("pnl") or 0) > 0)
            count = len(pts)
            return {"pnl": pnl, "pnl_pct": round(pnl/current_equity*100,2) if current_equity else 0,
                    "trades": count, "wins": wins, "win_rate": round(wins/count*100,1) if count else 0}

        # Daily average P&L from closed trades only (excludes deposits/withdrawals)
        daily_avg = 0.0
        if closed:
            all_days = sorted({parse_date(t) for t in closed if parse_date(t)})
            if all_days:
                total_trade_pnl = sum(float(t.get("pnl") or 0) for t in closed)
                trading_days = max(len(all_days), 1)
                daily_avg = round(total_trade_pnl / trading_days, 2)

        # ── Cumulative trade P&L chart (deposits excluded) ──────────────────
        # Group closed trades by date, accumulate P&L day by day.
        # This replaces the raw equity chart which was inflated by deposits.
        pnl_by_date: dict = {}
        for t in closed:
            d = parse_date(t)
            if d:
                pnl_by_date[d] = pnl_by_date.get(d, 0.0) + float(t.get("pnl") or 0)

        cumulative_pnl = []
        running = 0.0
        for d in sorted(pnl_by_date):
            running += pnl_by_date[d]
            cumulative_pnl.append({"date": d.isoformat(), "pnl": round(running, 2)})

        # Keep equity_history for reference (account value) but primary chart is cumulative P&L
        result = {
            "week":  build_period(week_start),
            "month": build_period(month_start),
            "year":  build_period(year_start),
            "projections": {
                "daily_avg_pnl":    daily_avg,
                "projected_week":   round(daily_avg*5,2),
                "projected_month":  round(daily_avg*21,2),
                "projected_year":   round(daily_avg*252,2),
                "annualized_return_pct": round(daily_avg*252/current_equity*100,2) if current_equity else 0,
            },
            "equity_history": eq_history[-90:],
            "cumulative_pnl": cumulative_pnl,
        }
        _periods_cache["data"] = result; _periods_cache["at"] = _time.time()
        return jsonify(result)
    except Exception as e:
        log.error(f"/api/periods error: {e}")
        return jsonify({"error": str(e), "week":{}, "month":{}, "year":{}, "projections":{}, "equity_history":[]})

@app.route("/api/status")
@login_required
def api_status():
    up = datetime.datetime.utcnow() - _SERVER_START
    h, rem = divmod(int(up.total_seconds()), 3600); m = rem // 60
    open_t  = sum(1 for t in TRADE_LOG if t.get("status")=="open")
    closed_t = sum(1 for t in TRADE_LOG if t.get("status")=="closed")

    # AI connection health check
    import os as _os
    _anthr_key = _os.getenv("ANTHROPIC_API_KEY", "").strip()
    ai_connected = bool(_anthr_key)
    ai_model = "claude-haiku-4-5-20251001"

    # Trend memory status
    try:
        from special_k_forex.trend_memory import get_all_memory, needs_refresh as _needs_refresh
        _mem = get_all_memory()
        trend_symbols_loaded = len(_mem.get("symbols", {}))
        trend_memory_stale   = _needs_refresh()
        trend_last_updated   = _mem.get("last_updated") or "never"
    except Exception:
        trend_symbols_loaded = 0
        trend_memory_stale   = True
        trend_last_updated   = "unavailable"

    return jsonify({
        "server_start": _SERVER_START.strftime("%Y-%m-%d %H:%M UTC"),
        "uptime": f"{h}h {m}m",
        "last_engine_run": _LAST_ENGINE_RUN["time"] or "not yet",
        "last_engine_result": _LAST_ENGINE_RUN["result"],
        "open_trades": open_t, "closed_trades": closed_t,
        "risk_level": RISK_LEVEL["value"],
        "mode": "LIVE" if LIVE_MODE["value"] else "PAPER",
        "market_open": is_market_open(),
        "buying_power": None,
        "ai_connected": ai_connected,
        "ai_model": ai_model,
        "trend_symbols_loaded": trend_symbols_loaded,
        "trend_memory_stale": trend_memory_stale,
        "trend_last_updated": trend_last_updated,
    })

@app.route("/api/market_intelligence")
@login_required
def api_market_intelligence():
    """Claude's learned trend analysis for each symbol + macro overview."""
    try:
        from special_k_forex.trend_memory import get_all_memory, needs_refresh
        mem = get_all_memory()
        return jsonify({
            "symbols": mem.get("symbols", {}),
            "macro_overview": mem.get("macro_overview", ""),
            "last_updated": mem.get("last_updated"),
            "stale": needs_refresh(),
        })
    except Exception as e:
        return jsonify({"error": str(e), "symbols": {}, "macro_overview": ""})

@app.route("/api/market_intelligence/refresh", methods=["POST"])
@login_required
def api_refresh_intelligence():
    """Manually trigger a trend memory refresh."""
    threading.Thread(target=_refresh_trend_memory, daemon=True).start()
    return jsonify({"status": "refresh started"})

@app.route("/api/risk", methods=["GET"])
@login_required
def api_get_risk():
    return jsonify({"level": RISK_LEVEL["value"], "params": get_risk_params()})

@app.route("/api/risk", methods=["POST"])
@login_required
def api_set_risk():
    level = max(1, min(10, int(request.get_json().get("level", 5))))
    RISK_LEVEL["value"] = level
    return jsonify({"level": level, "params": get_risk_params()})

@app.route("/api/run_dry", methods=["POST"])
@login_required
def api_run_dry():
    def _run_crypto_dry():
        try:
            from special_k_forex.crypto_engine import CryptoEngine
            from special_k_forex.config import Settings
            cfg = Settings()
            if TRADE_BUDGET["value"] > 0:
                cfg.trade_budget = TRADE_BUDGET["value"]
            CryptoEngine(cfg, dry_run=True).run()
        except Exception as e:
            log.error(f"Dry run error: {e}")
    threading.Thread(target=_run_crypto_dry, daemon=True).start()
    return jsonify({"message": "Dry run started — check logs"})

@app.route("/api/run_live", methods=["POST"])
@login_required
def api_run_live():
    def _run_crypto_live():
        try:
            from special_k_forex.crypto_engine import CryptoEngine
            from special_k_forex.config import Settings
            cfg = Settings()
            if TRADE_BUDGET["value"] > 0:
                cfg.trade_budget = TRADE_BUDGET["value"]
            CryptoEngine(cfg, dry_run=False).run()
            _LAST_ENGINE_RUN["time"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            _LAST_ENGINE_RUN["result"] = "ok"
        except Exception as e:
            log.error(f"Manual crypto run error: {e}")
            _LAST_ENGINE_RUN["result"] = str(e)
    threading.Thread(target=_run_crypto_live, daemon=True).start()
    return jsonify({"message": "Crypto engine live run started"})

@app.route("/api/seed_history", methods=["POST"])
@login_required
def api_seed_history():
    try:
        fresh = _alpaca_orders_as_trades()
        TRADE_LOG.clear(); TRADE_LOG.extend(fresh)
        _periods_cache["data"] = None
        return jsonify({"message": f"Synced {len(fresh)} trades from Alpaca", "count": len(fresh)})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/cancel_all", methods=["POST"])
@login_required
def api_cancel_all():
    try:
        b = get_broker()
        for p in b.get_positions(): b.cancel_orders_for_symbol(p.symbol)
        return jsonify({"message": "All orders cancelled"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/close/<symbol>", methods=["POST"])
@login_required
def api_close(symbol):
    try:
        get_broker().close_position(symbol)
        return jsonify({"message": f"Closed {symbol}"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/mode", methods=["GET"])
@login_required
def api_get_mode():
    return jsonify({"live": LIVE_MODE["value"]})

@app.route("/api/mode", methods=["POST"])
@login_required
def api_set_mode():
    LIVE_MODE["value"] = bool(request.get_json().get("live", False))
    return jsonify({"live": LIVE_MODE["value"], "mode": "LIVE" if LIVE_MODE["value"] else "PAPER"})

@app.route("/api/logs")
@login_required
def api_logs():
    return jsonify({"logs": list(_LOG_BUFFER)[-100:]})

@app.route("/api/run_now", methods=["POST"])
@login_required
def api_run_now():
    try:
        _LOG_BUFFER.clear()
        run_engine()
        return jsonify({"ok": True, "logs": list(_LOG_BUFFER)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "logs": list(_LOG_BUFFER)})

@app.route("/api/budget", methods=["GET"])
@login_required
def api_get_budget():
    try:
        from special_k_forex.broker import Broker
        acct = Broker().get_account()
        buying_power = float(acct.buying_power)
        equity       = float(acct.equity)
    except Exception:
        buying_power = equity = 0.0
    budget = TRADE_BUDGET["value"]
    return jsonify({
        "budget":         budget,
        "unlimited":      budget == 0,
        "buying_power":   buying_power,
        "equity":         equity,
        "budget_pct":     round(budget / equity * 100, 1) if equity > 0 and budget > 0 else 0,
        "live":           LIVE_MODE["value"],
    })

@app.route("/api/budget", methods=["POST"])
@login_required
def api_set_budget():
    data   = request.get_json() or {}
    amount = float(data.get("budget", 0))
    if amount < 0:
        return jsonify({"error": "Budget cannot be negative"}), 400
    TRADE_BUDGET["value"] = amount
    _save_settings({"trade_budget": amount})
    log.info(f"Trade budget set to: {'unlimited' if amount == 0 else f'${amount:,.2f}'}")
    return jsonify({"budget": amount, "unlimited": amount == 0})

@app.route("/api/crypto")
@login_required
def api_crypto_scan():
    """Quick crypto market overview for the dashboard."""
    try:
        from special_k_forex.crypto_data import CryptoDataClient, CRYPTO_SYMBOLS
        from special_k_forex.indicators import compute_indicators
        from special_k_forex.strategy import ForexETFStrategy
        client   = CryptoDataClient()
        strategy = ForexETFStrategy()
        results  = []
        for sym in CRYPTO_SYMBOLS:
            bars = client.get_daily_bars(sym, lookback_days=100)
            if bars is None or len(bars) < 60:
                continue
            df   = compute_indicators(bars)
            last = df.iloc[-1]
            bounce = strategy.evaluate_bounce(sym, bars)
            results.append({
                "symbol":  sym,
                "price":   round(float(last["close"]), 4),
                "rsi":     round(float(last.get("rsi", 50) or 50), 1),
                "adx":     round(float(last.get("adx", 20) or 20), 1),
                "signal":  bounce.direction if bounce else None,
                "score":   bounce.score if bounce else 0,
                "change_pct": round(float(last.get("pullback_10d_pct", 0) or 0), 2),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return jsonify({"crypto": results})
    except Exception as e:
        return jsonify({"crypto": [], "error": str(e)})

@app.route("/api/crypto_chart")
@login_required
def api_crypto_chart():
    """Price history + trade markers + P&L for crypto chart tab."""
    sym = request.args.get("symbol", "BTC/USD")
    try:
        from special_k_forex.data import MarketDataClient, is_crypto, normalise_crypto
        from special_k_forex.indicators import compute_indicators
        fetcher = MarketDataClient()
        bars = fetcher.get_daily_bars(sym, days=180)
        price_labels, price_data, entry_points, exit_points = [], [], [], []
        if bars is not None and not bars.empty:
            df = compute_indicators(bars)
            for _, row in df.tail(90).iterrows():
                d = str(row.get("date", ""))[:10]
                price_labels.append(d)
                price_data.append(round(float(row["close"]), 4))

        # Pull trade entries/exits for this symbol from trade log
        trades = _alpaca_orders_as_trades()
        sym_clean = sym.replace("/", "")
        crypto_trades = [t for t in trades if t.get("symbol","").replace("/","") == sym_clean]
        for t in crypto_trades:
            d = str(t.get("entry_time","") or t.get("date",""))[:10]
            if d and d in price_labels:
                idx = price_labels.index(d)
                if t.get("entry_price"):
                    entry_points.append({"x": idx, "y": float(t["entry_price"]), "label": f"BUY {t.get('qty','')} @ ${t['entry_price']}"})
                if t.get("exit_price") and t.get("status") == "closed":
                    exit_d = str(t.get("exit_time",""))[:10]
                    if exit_d and exit_d in price_labels:
                        eidx = price_labels.index(exit_d)
                        exit_points.append({"x": eidx, "y": float(t["exit_price"]), "label": f"SELL @ ${t['exit_price']} P&L:{t.get('pnl','?')}"})

        # Crypto cumulative P&L
        closed_crypto = [t for t in crypto_trades if t.get("status")=="closed" and t.get("pnl") is not None]
        pnl_by_date = {}
        for t in closed_crypto:
            d = str(t.get("exit_time","") or t.get("date",""))[:10]
            if d:
                pnl_by_date[d] = pnl_by_date.get(d, 0.0) + float(t.get("pnl") or 0)
        cum_pnl, running = [], 0.0
        for d in sorted(pnl_by_date):
            running += pnl_by_date[d]
            cum_pnl.append({"date": d, "pnl": round(running, 4)})

        wins = sum(1 for t in closed_crypto if float(t.get("pnl",0)) > 0)
        losses = sum(1 for t in closed_crypto if float(t.get("pnl",0)) <= 0)

        # Fear & Greed index
        fg = {"value": 50, "classification": "Neutral"}
        try:
            import urllib.request as _ur, json as _j
            with _ur.urlopen("https://api.alternative.me/fng/?limit=1", timeout=5) as _r:
                _d = _j.loads(_r.read().decode())
                if _d.get("data"):
                    fg = {"value": int(_d["data"][0]["value"]), "classification": _d["data"][0]["value_classification"]}
        except Exception:
            pass

        return jsonify({
            "symbol": sym,
            "price_labels": price_labels,
            "price_data": price_data,
            "entry_points": entry_points,
            "exit_points": exit_points,
            "cum_pnl": cum_pnl,
            "wins": wins,
            "losses": losses,
            "trades": [{"time": t.get("entry_time","")[:16] if t.get("entry_time") else "", "symbol": t.get("symbol",""), "qty": t.get("qty",""), "entry": t.get("entry_price",""), "exit": t.get("exit_price",""), "pnl": t.get("pnl",""), "pnl_pct": t.get("pnl_pct",""), "status": t.get("status","")} for t in crypto_trades[-50:]],
            "fear_greed": fg,
        })
    except Exception as e:
        return jsonify({"error": str(e), "price_labels": [], "price_data": [], "entry_points": [], "exit_points": [], "cum_pnl": [], "wins": 0, "losses": 0, "trades": [], "fear_greed": {"value": 50, "classification": "Neutral"}})


@app.route("/api/markets")
@login_required
def api_markets():
    try:
        from special_k_forex.market_hours import get_market_status
        return jsonify({"markets": get_market_status()})
    except Exception as e:
        return jsonify({"markets": [], "error": str(e)})

HEDGE_CONFIG = {
    "enabled":          True,
    "trigger_pct":      1.5,
    "ratio":            0.5,
    "recovery_buffer":  0.5,
}

@app.route("/api/hedge", methods=["GET"])
@login_required
def api_get_hedge():
    try:
        from special_k_forex.broker import Broker
        from special_k_forex.hedge import HedgeManager, HEDGE_INSTRUMENTS
        from special_k_forex.config import Settings
        cfg = Settings()
        cfg.hedge_enabled          = HEDGE_CONFIG["enabled"]
        cfg.hedge_trigger_pct      = HEDGE_CONFIG["trigger_pct"]
        cfg.hedge_ratio            = HEDGE_CONFIG["ratio"]
        cfg.hedge_recovery_buffer  = HEDGE_CONFIG["recovery_buffer"]
        broker  = Broker()
        hedger  = HedgeManager(cfg)
        acct    = broker.get_account()
        equity  = float(acct.equity)
        positions = {p.symbol: p for p in broker.get_positions()}
        status  = hedger.status(broker, positions, equity)
        return jsonify(status)
    except Exception as e:
        return jsonify({"enabled": HEDGE_CONFIG["enabled"], "error": str(e), "open_hedges": [], "hedged": False, "pnl_pct": 0})

@app.route("/api/hedge", methods=["POST"])
@login_required
def api_set_hedge():
    data = request.get_json() or {}
    if "enabled" in data:
        HEDGE_CONFIG["enabled"] = bool(data["enabled"])
    if "trigger_pct" in data:
        HEDGE_CONFIG["trigger_pct"] = float(data["trigger_pct"])
    if "ratio" in data:
        HEDGE_CONFIG["ratio"] = float(data["ratio"])
    log.info(f"Hedge config updated: {HEDGE_CONFIG}")
    return jsonify({"ok": True, **HEDGE_CONFIG})

@app.route("/api/hedge/open", methods=["POST"])
@login_required
def api_hedge_open():
    """Manually trigger hedge open."""
    try:
        from special_k_forex.broker import Broker
        from special_k_forex.data import MarketDataClient
        from special_k_forex.hedge import HedgeManager
        from special_k_forex.indicators import compute_indicators
        from special_k_forex.config import Settings
        cfg = Settings()
        cfg.hedge_enabled     = True
        cfg.hedge_trigger_pct = 0.0   # force-open regardless of drawdown
        cfg.hedge_ratio       = HEDGE_CONFIG["ratio"]
        broker  = Broker()
        fetcher = MarketDataClient()
        hedger  = HedgeManager(cfg)
        positions = {p.symbol: p for p in broker.get_positions()}
        # attach indicators so hedge_qty can get ATR
        enriched = {}
        for sym, pos in positions.items():
            bars = fetcher.get_daily_bars(sym)
            if bars is not None and len(bars) >= 14:
                bars = compute_indicators(bars)
                pos._bars = bars
            enriched[sym] = pos
        opened = hedger.open_hedges(broker, fetcher, enriched, dry_run=False)
        return jsonify({"opened": opened})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/hedge/close", methods=["POST"])
@login_required
def api_hedge_close():
    """Manually close all hedge positions."""
    try:
        from special_k_forex.broker import Broker
        from special_k_forex.hedge import HedgeManager
        from special_k_forex.config import Settings
        cfg    = Settings()
        broker = Broker()
        hedger = HedgeManager(cfg)
        closed = hedger.close_hedges(broker, dry_run=False)
        return jsonify({"closed": closed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── HTML ──────────────────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Special K Forex Login</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080c10;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:'Share Tech Mono',monospace}
.box{background:#0d1117;border:1px solid #1e2d3d;border-radius:8px;padding:40px;width:100%;max-width:360px;text-align:center}
.logo{font-size:22px;color:#00e5ff;letter-spacing:3px;margin-bottom:6px}
.logo span{color:#00ff88}
.sub{font-size:11px;color:#4a6278;letter-spacing:2px;margin-bottom:32px}
input{width:100%;background:#080c10;border:1px solid #1e2d3d;color:#c9d8e8;font-family:'Share Tech Mono',monospace;font-size:14px;padding:12px 14px;border-radius:4px;margin-bottom:14px;outline:none}
input:focus{border-color:#00e5ff}
button{width:100%;background:rgba(0,229,255,.08);border:1px solid #00e5ff;color:#00e5ff;font-family:'Share Tech Mono',monospace;font-size:13px;letter-spacing:2px;padding:12px;border-radius:4px;cursor:pointer}
button:hover{background:rgba(0,229,255,.18)}
.error{color:#ff4466;font-size:12px;margin-bottom:14px}
</style></head>
<body><div class="box">
<div class="logo">SPECIAL<span>K</span> CRYPTO</div>
<div class="sub">CURRENCY TERMINAL</div>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="POST" action="/login">
<input type="password" name="password" placeholder="Enter password" autofocus>
<button type="submit">ACCESS TERMINAL</button>
</form>
</div></body></html>"""

HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Special K Forex</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#080c10;--surface:#0d1117;--card:#111820;--border:#1e2d3d;--accent:#00e5ff;--green:#00ff88;--red:#ff4466;--yellow:#ffc107;--dim:#4a6278;--text:#c9d8e8;--mono:'Share Tech Mono',monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;font-size:14px}
header{display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:52px;border-bottom:1px solid var(--border);background:var(--surface);flex-wrap:wrap;gap:8px}
.logo{font-family:var(--mono);font-size:16px;color:var(--accent);letter-spacing:2px}
.logo span{color:var(--green)}
.sdot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;display:inline-block;margin-right:6px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.hr{display:flex;align-items:center;gap:14px;font-family:var(--mono);font-size:11px;color:var(--dim)}
#clock{color:var(--accent)}
.lbtn{font-family:var(--mono);font-size:10px;color:var(--dim);background:none;border:1px solid var(--border);padding:4px 10px;border-radius:3px;cursor:pointer;text-decoration:none}
.lbtn:hover{color:var(--red);border-color:var(--red)}
nav{display:flex;padding:0 16px;overflow-x:auto;background:var(--surface);border-bottom:1px solid var(--border);scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{background:none;border:none;color:var(--dim);cursor:pointer;font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;padding:12px 14px;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}
nav button:hover{color:var(--text)}
nav button.active{color:var(--accent);border-bottom-color:var(--accent)}
.tape-wrap{overflow:hidden;background:#060a0e;border-bottom:1px solid var(--border);height:32px}
.tape{display:flex;gap:40px;padding:8px 0;white-space:nowrap;animation:scroll 30s linear infinite}
@keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.ti{font-family:var(--mono);font-size:12px}
.ti .sym{color:var(--accent);margin-right:4px}
.ti .pair{color:var(--dim);font-size:10px;margin-right:6px}
.ti .pos{color:var(--green)}.ti .neg{color:var(--red)}
.page{display:none;padding:16px}
.page.active{display:block}
.sr{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:16px}
.sc{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px 14px}
.sc .lb{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:5px}
.sc .val{font-family:var(--mono);font-size:18px;color:var(--text)}
.sc .val.green{color:var(--green)}.sc .val.red{color:var(--red)}.sc .val.accent{color:var(--accent)}
.sc .sub{font-size:11px;color:var(--dim);margin-top:4px;font-family:var(--mono)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:700px){.g2,.g3{grid-template-columns:1fr}}
.cp{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px}
.cp h3{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:12px;font-family:var(--mono)}
.cp canvas{width:100%!important;display:block}
.tw{background:var(--card);border:1px solid var(--border);border-radius:6px;overflow:auto}
.tw h3{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);padding:12px 14px 0;font-family:var(--mono)}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px;min-width:500px}
th{text-align:left;padding:8px 12px;font-size:10px;letter-spacing:1px;color:var(--dim);border-bottom:1px solid var(--border);text-transform:uppercase}
td{padding:9px 12px;border-bottom:1px solid #0f1a24}
tr:last-child td{border-bottom:none}
tr:hover td{background:#0f1a24}
.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px}
.badge.long{background:rgba(0,255,136,.1);color:var(--green);border:1px solid rgba(0,255,136,.3)}
.badge.open{background:rgba(0,229,255,.1);color:var(--accent);border:1px solid rgba(0,229,255,.3)}
.badge.closed{background:rgba(74,98,120,.1);color:var(--dim);border:1px solid var(--border)}
.badge.signal{background:rgba(0,255,136,.15);color:var(--green);border:1px solid rgba(0,255,136,.4)}
.badge.nosig{background:rgba(74,98,120,.1);color:var(--dim);border:1px solid var(--border)}
.badge.trend{background:rgba(0,229,255,.1);color:var(--accent);border:1px solid rgba(0,229,255,.3)}
.lw{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;max-height:220px;overflow-y:auto}
.lw h3{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:8px;font-family:var(--mono)}
.ll{font-family:var(--mono);font-size:11px;padding:3px 0;border-bottom:1px solid #0d1520}
.ll .ts{color:var(--dim);margin-right:8px}
.ll.buy .msg{color:var(--green)}.ll.sell .msg{color:var(--red)}.ll.warn .msg{color:var(--yellow)}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;padding:8px 14px;border-radius:4px;border:1px solid;cursor:pointer;transition:all .2s}
.ba{border-color:var(--accent);color:var(--accent);background:rgba(0,229,255,.05)}
.ba:hover{background:rgba(0,229,255,.15)}
.bd{border-color:var(--red);color:var(--red);background:rgba(255,68,102,.05)}
.bd:hover{background:rgba(255,68,102,.15)}
.bg{border-color:var(--green);color:var(--green);background:rgba(0,255,136,.05)}
.bg:hover{background:rgba(0,255,136,.15)}
.acts{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.gap{margin-bottom:16px}
.ph{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.pt{font-family:var(--mono);font-size:12px;color:var(--accent);letter-spacing:2px;text-transform:uppercase}
.rb{font-family:var(--mono);font-size:10px;color:var(--dim);background:none;border:1px solid var(--border);padding:4px 10px;border-radius:3px;cursor:pointer}
.rb:hover{color:var(--accent);border-color:var(--accent)}
.risk-box{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:16px;margin-bottom:16px}
.risk-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.risk-label{font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px;text-transform:uppercase}
.risk-val{font-family:var(--mono);font-size:22px;color:var(--accent)}
.risk-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
input[type=range]{flex:1;accent-color:var(--accent);height:4px;cursor:pointer}
.risk-params{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-top:4px}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.ptab{font-family:var(--mono);font-size:10px;letter-spacing:1px;padding:4px 12px;border-radius:3px;border:1px solid var(--border);color:var(--dim);background:none;cursor:pointer}
.ptab.active{color:var(--accent);border-color:var(--accent);background:rgba(0,229,255,.08)}
.proj-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-top:8px}
.scan-card{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;margin-bottom:10px}
.scan-sym{font-family:var(--mono);font-size:18px;color:var(--accent);margin-bottom:2px}
.scan-pair{font-family:var(--mono);font-size:11px;color:var(--dim);margin-bottom:10px}
.ind-row{display:flex;align-items:center;gap:8px;margin-bottom:5px;font-family:var(--mono);font-size:11px}
.ind-lbl{width:80px;color:var(--dim)}
.ind-bar{flex:1;height:5px;background:var(--border);border-radius:3px;overflow:hidden}
.ind-fill{height:100%;border-radius:3px}
.ind-val{width:60px;text-align:right;color:var(--text)}
</style></head>
<body>
<header>
<div class="logo">SPECIAL<span>K</span> CRYPTO</div>
<div class="hr">
<span><span class="sdot"></span><span id="market-status">CHECKING</span></span>
<span id="clock">--:--:--</span>
<span id="countdown" style="color:var(--yellow);font-size:11px"></span>
<span id="hedge-header-badge" style="font-family:var(--mono);font-size:10px;padding:3px 8px;border-radius:3px;background:rgba(74,98,120,.3);color:var(--dim)">HEDGE</span>
<span id="conn-badge" style="display:none;font-family:var(--mono);font-size:10px;padding:3px 8px;border-radius:3px;background:rgba(255,68,102,.15);color:var(--red);border:1px solid rgba(255,68,102,.3)">⚠ OFFLINE</span>
<button id="mode-btn" onclick="toggleMode()" style="font-family:var(--mono);font-size:10px;padding:4px 10px;border-radius:3px;border:1px solid var(--green);color:var(--green);background:rgba(0,255,136,.05);cursor:pointer">PAPER</button>
<a href="/logout" class="lbtn">LOGOUT</a>
</div>
</header>
<nav>
<button class="active" onclick="showTab('overview',this)">Overview</button>
<button onclick="showTab('positions',this)">Positions</button>
<button onclick="showTab('performance',this)">Performance</button>
<button onclick="showTab('research',this)">Research</button>
<button onclick="showTab('crypto',this)">&#8383; Crypto</button>
<button onclick="showTab('tradelog',this)">Trade Log</button>
<button onclick="showTab('control',this)">Controls</button>
</nav>
<div class="tape-wrap"><div class="tape" id="tape">Loading FX data...</div></div>
<div id="market-clock" style="background:#060c12;border-bottom:1px solid var(--border);padding:5px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center">
<span style="font-family:var(--mono);font-size:9px;color:var(--dim);letter-spacing:1px;margin-right:4px">MARKETS</span>
<div id="market-clock-items" style="display:flex;gap:10px;flex-wrap:wrap"></div>
</div>

<!-- OVERVIEW -->
<div id="page-overview" class="page active">
<div class="ph"><span class="pt">Portfolio Overview</span><button class="rb" onclick="loadOverview()">Refresh</button><button class="rb" onclick="runEngineNow()" style="margin-left:8px;background:rgba(0,229,255,.1);color:var(--accent);border-color:var(--accent)">▶ Run Engine Now</button></div>
<div id="engine-log-panel" style="margin-bottom:12px;display:none">
  <div style="background:#060c12;border:1px solid var(--border);border-radius:6px;padding:12px">
    <div style="font-family:var(--mono);font-size:10px;letter-spacing:2px;color:var(--dim);margin-bottom:8px">ENGINE LOG</div>
    <div id="engine-log-lines" style="font-family:var(--mono);font-size:10px;color:var(--dim);max-height:300px;overflow-y:auto;white-space:pre-wrap;line-height:1.6"></div>
  </div>
</div>
<div class="sr">
<div class="sc"><div class="lb">Equity</div><div class="val accent" id="s-equity">--</div></div>
<div class="sc"><div class="lb">Cash</div><div class="val" id="s-cash">--</div></div>
<div class="sc"><div class="lb">Buying Power</div><div class="val" id="s-bp">--</div></div>
<div class="sc"><div class="lb">Daily P&L</div><div class="val" id="s-dpnl">--</div></div>
<div class="sc"><div class="lb">Unrealized P&L</div><div class="val" id="s-upnl">--</div></div>
<div class="sc"><div class="lb">Positions</div><div class="val accent" id="s-pos">--</div></div>
<div class="sc"><div class="lb">Exposure</div><div class="val" id="s-exp">--</div></div>
<div class="sc"><div class="lb">Open Orders</div><div class="val" id="s-orders">--</div></div>
<div class="sc" style="border-left:2px solid #f7931a"><div class="lb" style="color:#f7931a">&#8383; Crypto</div><div class="val" id="s-crypto">--</div><div style="font-size:9px;color:var(--dim);margin-top:2px" id="s-crypto-pnl"></div></div>
<div class="sc" style="border-left:2px solid var(--accent)"><div class="lb">Stocks / FX</div><div class="val" id="s-stocks">--</div><div style="font-size:9px;color:var(--dim);margin-top:2px" id="s-stocks-pnl"></div></div>
</div>

<div class="cp gap" id="period-box">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
  <span style="font-family:var(--mono);font-size:10px;letter-spacing:2px;color:var(--dim);text-transform:uppercase">Period P&amp;L Overview</span>
  <div style="display:flex;gap:6px">
    <button class="ptab active" onclick="showPeriod('week',this)">WEEK</button>
    <button class="ptab" onclick="showPeriod('month',this)">MONTH</button>
    <button class="ptab" onclick="showPeriod('year',this)">YEAR</button>
  </div>
</div>
<div class="sr" style="margin-bottom:14px">
  <div class="sc"><div class="lb">P&amp;L</div><div class="val" id="pd-pnl">--</div></div>
  <div class="sc"><div class="lb">Return %</div><div class="val" id="pd-pct">--</div></div>
  <div class="sc"><div class="lb">Trades</div><div class="val accent" id="pd-trades">--</div></div>
  <div class="sc"><div class="lb">Win Rate</div><div class="val" id="pd-wr">--</div></div>
  <div class="sc"><div class="lb">Wins</div><div class="val green" id="pd-wins">--</div></div>
  <div class="sc"><div class="lb">Losses</div><div class="val red" id="pd-losses">--</div></div>
</div>
<div style="font-family:var(--mono);font-size:10px;letter-spacing:1px;color:var(--dim);text-transform:uppercase;margin-bottom:8px">Projections</div>
<div class="proj-grid">
  <div class="sc"><div class="lb">Daily Avg</div><div class="val" id="pj-day">--</div></div>
  <div class="sc"><div class="lb">Proj Week</div><div class="val" id="pj-wk">--</div></div>
  <div class="sc"><div class="lb">Proj Month</div><div class="val" id="pj-mo">--</div></div>
  <div class="sc"><div class="lb">Proj Year</div><div class="val" id="pj-yr">--</div></div>
  <div class="sc"><div class="lb">Ann. Return</div><div class="val" id="pj-ann">--</div></div>
</div>
<div style="font-family:var(--mono);font-size:10px;letter-spacing:1px;color:var(--dim);text-transform:uppercase;margin:14px 0 8px">Cumulative Trading P&amp;L (deposits excluded)</div>
<canvas id="equityHistChart" height="100"></canvas>
</div>

<div class="g2 gap">
<div class="cp"><h3>Equity Curve (live)</h3><canvas id="equityChart" height="160"></canvas></div>
<div class="cp"><h3>P&L Distribution</h3><canvas id="pnlDistChart" height="160"></canvas></div>
</div>
<div class="g2 gap">
<div class="cp"><h3>Exposure by ETF</h3><canvas id="exposureChart" height="170"></canvas></div>
<div class="cp"><h3>Cash vs Invested</h3><canvas id="allocationChart" height="170"></canvas></div>
</div>
<div class="cp gap">
<div class="ph"><span class="pt">Open Positions</span><span id="ov-pos-count" style="font-family:var(--mono);font-size:11px;color:var(--dim)"></span></div>
<div id="ov-positions" style="font-family:var(--mono);font-size:11px;color:var(--dim)">Loading...</div>
</div>
<div class="cp gap">
<div class="ph"><span class="pt">Open Orders</span><span id="ov-ord-count" style="font-family:var(--mono);font-size:11px;color:var(--dim)"></span></div>
<div id="ov-orders" style="font-family:var(--mono);font-size:11px;color:var(--dim)">Loading...</div>
</div>
<div class="acts">
<button class="btn ba" onclick="runDry()">DRY RUN SCAN</button>
<button class="btn bg" onclick="runLive()">RUN ENGINE</button>
<button class="btn ba" onclick="seedHistory()">SYNC HISTORY</button>
<button class="btn bd" onclick="if(confirm('Cancel ALL orders?'))cancelAll()">CANCEL ALL</button>
</div>
<div class="g2 gap">
<div class="lw"><h3>Activity Log</h3><div id="activity-log"></div></div>
<div class="cp"><h3>System Status</h3><div id="sys-status" style="font-family:var(--mono);font-size:12px;padding:4px 0"></div></div>
</div>
</div>

<!-- POSITIONS -->
<div id="page-positions" class="page">
<div class="ph"><span class="pt">Open Positions</span><button class="rb" onclick="loadPositions()">Refresh</button></div>
<div class="g3 gap" id="pos-cards"></div>
<div class="g2 gap">
<div class="cp"><h3>Unrealized P&L</h3><canvas id="positionPnlChart" height="200"></canvas></div>
<div class="cp"><h3>Market Value</h3><canvas id="positionSizeChart" height="200"></canvas></div>
</div>
<div class="tw gap">
<h3 style="padding:12px 14px 8px">Positions Detail</h3>
<table><thead><tr><th>ETF</th><th>Pair</th><th>Qty</th><th>Entry</th><th>Current</th><th>Mkt Val</th><th>Unreal P&L</th><th>P&L %</th><th>Action</th></tr></thead>
<tbody id="pos-tbody"></tbody></table>
</div>
</div>

<!-- PERFORMANCE -->
<div id="page-performance" class="page">
<div class="ph"><span class="pt">Performance Analytics</span><button class="rb" onclick="loadPerformance()">Refresh</button></div>
<div class="sr">
<div class="sc"><div class="lb">Total Trades</div><div class="val accent" id="p-total">--</div></div>
<div class="sc"><div class="lb">Win Rate</div><div class="val" id="p-winrate">--</div></div>
<div class="sc"><div class="lb">Avg Win</div><div class="val green" id="p-avgwin">--</div></div>
<div class="sc"><div class="lb">Avg Loss</div><div class="val red" id="p-avgloss">--</div></div>
<div class="sc"><div class="lb">Profit Factor</div><div class="val" id="p-pf">--</div></div>
<div class="sc"><div class="lb">Best Trade</div><div class="val green" id="p-best">--</div></div>
<div class="sc"><div class="lb">Worst Trade</div><div class="val red" id="p-worst">--</div></div>
<div class="sc"><div class="lb">Max Drawdown</div><div class="val red" id="p-dd">--</div></div>
</div>
<div class="g2 gap">
<div class="cp"><h3>Cumulative P&L</h3><canvas id="cumulPnlChart" height="180"></canvas></div>
<div class="cp"><h3>Win / Loss</h3><canvas id="winLossChart" height="180"></canvas></div>
</div>
<div class="g2 gap">
<div class="cp"><h3>P&L per ETF</h3><canvas id="symPnlChart" height="180"></canvas></div>
<div class="cp"><h3>Trade Duration</h3><canvas id="durationChart" height="180"></canvas></div>
</div>
<div class="cp gap"><h3>Drawdown Over Time</h3><canvas id="drawdownChart" height="120"></canvas></div>
<div id="perf-empty" style="display:none;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:32px;text-align:center;margin-bottom:16px">
  <span style="font-family:var(--mono);font-size:12px;color:var(--dim)">NO TRADE HISTORY YET</span>
</div>
</div>

<!-- FX RESEARCH -->
<div id="page-research" class="page">
<div class="ph"><span class="pt">Crypto Research — Signal Scanner</span>
  <div style="display:flex;gap:8px">
    <button class="rb" onclick="loadIntelligence()" style="background:rgba(255,180,0,.12);color:#ffb400;border-color:rgba(255,180,0,.3)">AI Intelligence</button>
    <button class="rb" onclick="forceScan()">Scan Now</button>
  </div>
</div>
<div id="ai-overview" style="display:none;font-family:var(--mono);font-size:12px;color:var(--accent);background:rgba(0,229,255,.05);border:1px solid rgba(0,229,255,.15);border-radius:5px;padding:10px 14px;margin-bottom:12px;line-height:1.6"></div>
<div id="intelligence-panel" style="display:none;margin-bottom:16px"></div>
<div class="g2 gap">
<div class="cp"><h3>Signal Scores</h3><canvas id="scoreChart" height="220"></canvas></div>
<div class="cp"><h3>RSI by ETF</h3><canvas id="rsiChart" height="220"></canvas></div>
</div>
<div id="scan-cards" style="margin-top:16px"></div>
<div style="font-family:var(--mono);font-size:10px;color:var(--dim);padding:8px 0">
  Signal fires at score &ge; 4 &middot; Trend gate: Close &gt; SMA50 &gt; SMA200 &middot; Entry: RSI pullback + Bollinger proximity
</div>
<div class="ph" style="margin-top:16px"><span class="pt" style="color:#f7931a">&#8383; CRYPTO MARKETS — 24/7</span><button class="rb" onclick="loadCrypto()">Refresh</button></div>
<div id="crypto-cards" class="g3 gap"></div>
</div>

<!-- CRYPTO -->
<div id="page-crypto" class="page">
<div class="ph">
  <span class="pt" style="color:#f7931a">&#8383; Crypto Trading — 24/7</span>
  <div style="display:flex;gap:8px;align-items:center">
    <select id="crypto-sym-select" style="background:#0d1117;border:1px solid var(--border);color:var(--fg);font-family:var(--mono);font-size:11px;padding:4px 8px;border-radius:3px">
      <option value="BTC/USD">BTC/USD</option>
      <option value="ETH/USD">ETH/USD</option>
      <option value="SOL/USD">SOL/USD</option>
      <option value="DOGE/USD">DOGE/USD</option>
    </select>
    <button class="rb" onclick="loadCryptoChart()">Load Chart</button>
    <button class="rb" onclick="loadCryptoTab()" style="background:rgba(247,147,26,.12);color:#f7931a;border-color:rgba(247,147,26,.3)">Refresh All</button>
  </div>
</div>

<!-- Fear & Greed + Market Stats row -->
<div id="crypto-stats-row" class="g3 gap" style="margin-bottom:16px"></div>

<!-- Price chart with trade markers -->
<div class="cp" style="margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <h3 id="crypto-chart-title" style="color:#f7931a">BTC/USD — Price Chart</h3>
    <div style="font-family:var(--mono);font-size:10px;color:var(--dim)">&#9650; = Entry &nbsp; &#9660; = Exit</div>
  </div>
  <div style="position:relative;height:280px"><canvas id="cryptoPriceChart"></canvas></div>
</div>

<!-- Crypto P&L chart -->
<div class="g2 gap" style="margin-bottom:16px">
  <div class="cp"><h3>Crypto Cumulative P&L</h3><div style="position:relative;height:180px"><canvas id="cryptoPnlChart"></canvas></div></div>
  <div class="cp"><h3>Crypto Win / Loss</h3><div style="position:relative;height:180px"><canvas id="cryptoWinLossChart"></canvas></div></div>
</div>

<!-- Live crypto cards -->
<div class="ph" style="margin-top:4px"><span class="pt" style="font-size:12px">Live Signals</span></div>
<div id="crypto-tab-cards" class="g3 gap" style="margin-bottom:16px"></div>

<!-- Crypto trade log -->
<div class="tw">
<h3 style="padding:12px 14px 8px">Crypto Trades</h3>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L $</th><th>P&L %</th><th>Status</th></tr></thead>
<tbody id="crypto-log-tbody"><tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px">Loading...</td></tr></tbody></table>
</div>
</div>

<!-- TRADE LOG -->
<div id="page-tradelog" class="page">
<div class="ph"><span class="pt">Trade Log</span><button class="rb" onclick="loadTradeLog()">Refresh</button></div>
<div class="g2 gap">
<div class="cp"><h3>Trade P&L Over Time</h3><canvas id="tradeTimeChart" height="180"></canvas></div>
<div class="cp"><h3>P&L by ETF</h3><canvas id="etfPnlChart" height="180"></canvas></div>
</div>
<div class="tw">
<h3 style="padding:12px 14px 8px">All Trades</h3>
<table><thead><tr><th>Time</th><th>ETF</th><th>Pair</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L $</th><th>P&L %</th><th>Reason</th><th>Status</th></tr></thead>
<tbody id="log-tbody"></tbody></table>
</div>
</div>

<!-- CONTROLS -->
<div id="page-control" class="page">
<div class="ph"><span class="pt">Bot Controls</span></div>

<div style="background:linear-gradient(135deg,rgba(0,255,136,.06),rgba(0,229,255,.04));border:1px solid rgba(0,255,136,.25);border-radius:8px;padding:20px;margin-bottom:16px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px">
    <div>
      <div style="font-family:var(--mono);font-size:13px;color:var(--green);letter-spacing:1px;margin-bottom:3px">TRADE BUDGET</div>
      <div style="font-family:var(--mono);font-size:11px;color:var(--dim)">Hard cap on total capital deployed. Set to 0 for unlimited.</div>
    </div>
    <div id="budget-status" style="font-family:var(--mono);font-size:11px;color:var(--dim);text-align:right"></div>
  </div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <div style="display:flex;align-items:center;gap:8px;background:#0a0f15;border:1px solid var(--border);border-radius:5px;padding:6px 12px;flex:1;min-width:180px">
      <span style="font-family:var(--mono);font-size:16px;color:var(--green)">$</span>
      <input id="budget-input" type="number" min="0" step="10" placeholder="e.g. 50"
        style="background:none;border:none;outline:none;color:var(--text);font-family:var(--mono);font-size:18px;width:100%;max-width:160px">
      <span style="font-family:var(--mono);font-size:11px;color:var(--dim)">USD</span>
    </div>
    <button onclick="setBudget()" style="background:rgba(0,255,136,.15);color:var(--green);border:1px solid rgba(0,255,136,.4);border-radius:5px;padding:10px 20px;font-family:var(--mono);font-size:12px;cursor:pointer;letter-spacing:1px">SET BUDGET</button>
    <button onclick="setBudget(0)" style="background:rgba(74,98,120,.2);color:var(--dim);border:1px solid var(--border);border-radius:5px;padding:10px 16px;font-family:var(--mono);font-size:11px;cursor:pointer">UNLIMITED</button>
  </div>
  <div style="margin-top:12px" id="budget-bar-wrap" style="display:none">
    <div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;color:var(--dim);margin-bottom:4px">
      <span>Deployed</span><span id="budget-bar-label"></span>
    </div>
    <div style="height:6px;background:#0f1a24;border-radius:3px"><div id="budget-bar" style="height:6px;border-radius:3px;background:var(--green);transition:width .5s;width:0%"></div></div>
  </div>
</div>

<div class="risk-box" id="hedge-box">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <div>
      <div style="font-family:var(--mono);font-size:13px;color:#ffb400;letter-spacing:1px;margin-bottom:3px">HEDGE PROTECTION</div>
      <div style="font-family:var(--mono);font-size:11px;color:var(--dim)">Auto-opens UUP hedge when portfolio drops below trigger threshold.</div>
    </div>
    <div id="hedge-status-badge" style="font-family:var(--mono);font-size:11px;padding:4px 10px;border-radius:4px;background:rgba(74,98,120,.3);color:var(--dim)">LOADING</div>
  </div>
  <div id="hedge-pnl-row" style="font-family:var(--mono);font-size:12px;color:var(--dim);margin-bottom:10px"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
    <div>
      <div style="font-family:var(--mono);font-size:10px;color:var(--dim);margin-bottom:3px">TRIGGER DRAWDOWN %</div>
      <input id="hedge-trigger" type="number" min="0.5" max="10" step="0.5" value="1.5"
        style="background:#0a0f15;border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:14px;padding:5px 8px;border-radius:4px;width:80px">
    </div>
    <div>
      <div style="font-family:var(--mono);font-size:10px;color:var(--dim);margin-bottom:3px">HEDGE RATIO (0–1)</div>
      <input id="hedge-ratio" type="number" min="0.1" max="1" step="0.1" value="0.5"
        style="background:#0a0f15;border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:14px;padding:5px 8px;border-radius:4px;width:80px">
    </div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button onclick="toggleHedge()" id="hedge-toggle-btn"
      style="background:rgba(0,255,136,.15);color:var(--green);border:1px solid rgba(0,255,136,.4);border-radius:5px;padding:8px 16px;font-family:var(--mono);font-size:11px;cursor:pointer;letter-spacing:1px">DISABLE</button>
    <button onclick="saveHedgeConfig()"
      style="background:rgba(255,180,0,.1);color:#ffb400;border:1px solid rgba(255,180,0,.3);border-radius:5px;padding:8px 16px;font-family:var(--mono);font-size:11px;cursor:pointer">SAVE CONFIG</button>
    <button onclick="manualHedge()"
      style="background:rgba(255,68,100,.1);color:var(--red);border:1px solid rgba(255,68,100,.3);border-radius:5px;padding:8px 16px;font-family:var(--mono);font-size:11px;cursor:pointer">HEDGE NOW</button>
    <button onclick="closeHedges()"
      style="background:rgba(74,98,120,.2);color:var(--dim);border:1px solid var(--border);border-radius:5px;padding:8px 16px;font-family:var(--mono);font-size:11px;cursor:pointer">CLOSE HEDGES</button>
  </div>
  <div id="hedge-open-list" style="margin-top:8px;font-family:var(--mono);font-size:11px;color:var(--dim)"></div>
</div>

<div class="risk-box">
<div class="risk-header">
<span class="risk-label">Risk Level</span>
<span class="risk-val" id="risk-display">5 / 10</span>
</div>
<div class="risk-row">
<span style="font-family:var(--mono);font-size:10px;color:var(--green)">SAFE</span>
<input type="range" min="1" max="10" value="5" id="risk-slider"
  oninput="updateRiskDisplay(this.value)"
  onchange="setRisk(this.value)">
<span style="font-family:var(--mono);font-size:10px;color:var(--red)">MAX</span>
</div>
<div class="risk-params" id="risk-params"></div>
</div>

<div class="cp gap">
<h3>Watchlist — Currency ETF Reference</h3>
<table><thead><tr><th>ETF</th><th>Tracks</th><th>Current Price</th><th>Change</th></tr></thead>
<tbody id="watchlist-tbody"></tbody></table>
</div>

<div class="acts">
<button class="btn ba" onclick="runDry()">DRY RUN SCAN</button>
<button class="btn bg" onclick="runLive()">RUN ENGINE NOW</button>
<button class="btn ba" onclick="seedHistory()">SYNC HISTORY</button>
<button class="btn bd" onclick="if(confirm('Cancel ALL orders?'))cancelAll()">CANCEL ALL ORDERS</button>
</div>

<div class="cp gap">
<h3>System Status</h3>
<div id="ctrl-status" style="font-family:var(--mono);font-size:12px;padding:4px 0"></div>
</div>
<div class="lw"><h3>Activity Log</h3><div id="ctrl-log"></div></div>
</div>

<script>
Chart.defaults.color='#4a6278';
Chart.defaults.borderColor='#1e2d3d';
Chart.defaults.font.family="'Share Tech Mono',monospace";
Chart.defaults.font.size=11;
const AC='#00e5ff',GR='#00ff88',RE='#ff4466',YE='#ffc107',DI='#4a6278';
const CH={};
document.querySelectorAll('.cp canvas').forEach(c=>{const h=parseInt(c.getAttribute('height')||160);const w=document.createElement('div');w.style.cssText=`position:relative;height:${h}px;overflow:hidden`;c.parentNode.insertBefore(w,c);w.appendChild(c);c.removeAttribute('height');});
function mk(id,cfg){if(CH[id])CH[id].destroy();const c=document.getElementById(id);if(!c)return;CH[id]=new Chart(c,cfg);}
function cc(type,labels,datasets,opts={}){return{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:opts.legend??false,labels:{color:'#4a6278',boxWidth:10,font:{size:10}}}},scales:opts.ns?{}:{x:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278'}},y:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278'}}}}};}
function tick(){document.getElementById('clock').textContent=new Date().toLocaleTimeString('en-US',{hour12:false});}
setInterval(tick,1000);tick();
function showTab(id,btn){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+id).classList.add('active');
  if(btn)btn.classList.add('active');
  setTimeout(()=>Object.values(CH).forEach(c=>{try{c.resize();}catch(e){}}),50);
  ({overview:loadOverview,positions:loadPositions,performance:loadPerformance,research:()=>{loadResearch();loadCrypto();},crypto:loadCryptoTab,tradelog:loadTradeLog,control:loadControl})[id]?.();
}
const f$=v=>v==null?'--':'$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const f4=v=>v==null?'--':parseFloat(v).toFixed(4);
const fp=v=>v==null?'--':(v>=0?'+':'')+parseFloat(v).toFixed(2)+'%';
const fc=v=>parseFloat(v)>=0?'green':'red';
function lg(msg,t=''){
  ['activity-log','ctrl-log'].forEach(id=>{const d=document.getElementById(id);if(!d)return;const ts=new Date().toLocaleTimeString('en-US',{hour12:false});d.innerHTML=`<div class="ll ${t}"><span class="ts">${ts}</span><span class="msg">${msg}</span></div>`+d.innerHTML;});
}

// ── Period ─────────────────────────────────────────────────────────────────
window._periods=null;window._activePeriod='week';
async function loadPeriods(){
  try{
    const r=await fetch('/api/periods');const d=await r.json();
    window._periods=d;showPeriod(window._activePeriod);
    const proj=d.projections||{};
    const pv=(id,v)=>{const el=document.getElementById(id);if(!el)return;el.textContent=v==null?'--':v;};
    const pc=(id,v)=>{const el=document.getElementById(id);if(!el)return;el.className='val '+(parseFloat(v||0)>=0?'green':'red');};
    pv('pj-day',f$(proj.daily_avg_pnl));pc('pj-day',proj.daily_avg_pnl);
    pv('pj-wk',f$(proj.projected_week));pc('pj-wk',proj.projected_week);
    pv('pj-mo',f$(proj.projected_month));pc('pj-mo',proj.projected_month);
    pv('pj-yr',f$(proj.projected_year));pc('pj-yr',proj.projected_year);
    const ann=proj.annualized_return_pct;
    pv('pj-ann',ann!=null?(ann>=0?'+':'')+ann.toFixed(2)+'%':'--');pc('pj-ann',ann);
    const cpnl=d.cumulative_pnl||[];
    if(cpnl.length>=1){
      const color=cpnl.length&&cpnl[cpnl.length-1].pnl>=0?'rgba(0,255,136,1)':'rgba(255,68,102,1)';
      const bgColor=cpnl.length&&cpnl[cpnl.length-1].pnl>=0?'rgba(0,255,136,.07)':'rgba(255,68,102,.07)';
      mk('equityHistChart',cc('line',cpnl.map(e=>e.date.slice(5)),[{data:cpnl.map(e=>e.pnl),borderColor:color,backgroundColor:bgColor,fill:true,tension:.3,pointRadius:cpnl.length<=30?3:1,borderWidth:1.5}]));
    } else {
      const eq=d.equity_history||[];
      if(eq.length>=2)mk('equityHistChart',cc('line',eq.map(e=>e.date.slice(5)),[{data:eq.map(e=>e.equity),borderColor:AC,backgroundColor:'rgba(0,229,255,.05)',fill:true,tension:.3,pointRadius:eq.length<=30?3:1,borderWidth:1.5}]));
    }
  }catch(e){console.error('Periods error:',e);}
}
function showPeriod(period,btn){
  window._activePeriod=period;
  if(!window._periods)return;
  const data=window._periods[period]||{};
  const pv=(id,v,cls)=>{const el=document.getElementById(id);if(!el)return;el.textContent=v;if(cls!==undefined)el.className='val '+cls;};
  const pnl=data.pnl??null;const pct=data.pnl_pct??null;const wr=data.win_rate??null;
  pv('pd-pnl',pnl!=null?f$(pnl):'--',pnl!=null?(pnl>=0?'green':'red'):'');
  pv('pd-pct',pct!=null?(pct>=0?'+':'')+pct.toFixed(2)+'%':'--',pct!=null?(pct>=0?'green':'red'):'');
  pv('pd-trades',data.trades??'--','accent');
  pv('pd-wr',wr!=null&&data.trades?wr.toFixed(1)+'%':'--',wr!=null?(wr>=50?'green':'red'):'');
  pv('pd-wins',data.wins??'--','green');
  pv('pd-losses',data.trades!=null&&data.wins!=null?(data.trades-data.wins):'--','red');
  document.querySelectorAll('.ptab').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
}

// ── Tape ──────────────────────────────────────────────────────────────────
async function loadTape(){
  try{
    const r=await fetch('/api/quotes');const d=await r.json();
    if(!d.quotes||!Object.keys(d.quotes).length)return;
    const items=Object.entries(d.quotes).map(([s,q])=>{
      const c=q.change_pct??0;
      return `<span class="ti"><span class="sym">${s}</span><span class="pair">${q.pair||''}</span>${f4(q.price)} <span class="${c>=0?'pos':'neg'}">${fp(c)}</span></span>`;
    });
    document.getElementById('tape').innerHTML=[...items,...items].join('');
  }catch(e){}
}

// ── Overview ──────────────────────────────────────────────────────────────
async function loadOverview(){
  try{
    const r=await fetch('/api/account');const d=await r.json();
    if(d.error){lg('Account error: '+d.error,'warn');}
    document.getElementById('conn-badge').style.display='none';
    const a=d.account||{};
    document.getElementById('s-equity').textContent=f$(a.equity);
    document.getElementById('s-cash').textContent=f$(a.cash);
    document.getElementById('s-bp').textContent=f$(a.buying_power);
    const dp=parseFloat(a.equity||0)-parseFloat(a.last_equity||0);
    const el=document.getElementById('s-dpnl');if(el){el.textContent=f$(dp);el.className='val '+fc(dp);}
    const up=document.getElementById('s-upnl');if(up){up.textContent=f$(d.unrealized_pnl??0);up.className='val '+fc(d.unrealized_pnl??0);}
    document.getElementById('s-pos').textContent=d.position_count??0;
    document.getElementById('s-orders').textContent=d.order_count??0;
    const eq=parseFloat(a.equity||0),ca=parseFloat(a.cash||0);
    const expEl=document.getElementById('s-exp');if(expEl)expEl.textContent=eq>0?((eq-ca)/eq*100).toFixed(1)+'%':'--';

    // ── Crypto vs Stocks/FX capital breakdown ─────────────────────────────
    const cDep=parseFloat(d.crypto_deployed||0),sDep=parseFloat(d.stock_deployed||0);
    const cPnl=parseFloat(d.crypto_pnl||0),sPnl=parseFloat(d.stock_pnl||0);
    const cEl=document.getElementById('s-crypto');
    if(cEl)cEl.textContent=f$(cDep);
    const cPnlEl=document.getElementById('s-crypto-pnl');
    if(cPnlEl){cPnlEl.textContent=cDep>0?(cPnl>=0?'+':'')+f$(cPnl)+' P&L':'no positions';cPnlEl.style.color=cPnl>=0?'var(--green)':'var(--red)';}
    const sEl=document.getElementById('s-stocks');
    if(sEl)sEl.textContent=f$(sDep);
    const sPnlEl=document.getElementById('s-stocks-pnl');
    if(sPnlEl){sPnlEl.textContent=sDep>0?(sPnl>=0?'+':'')+f$(sPnl)+' P&L':'no positions';sPnlEl.style.color=sPnl>=0?'var(--green)':'var(--red)';}

    if(eq){
      if(!window._eq)window._eq=[];
      window._eq.push({t:new Date().toLocaleTimeString('en-US',{hour12:false}),v:eq});
      if(window._eq.length>200)window._eq.shift();
      mk('equityChart',cc('line',window._eq.map(x=>x.t),[{data:window._eq.map(x=>x.v),borderColor:AC,backgroundColor:'rgba(0,229,255,.06)',fill:true,tension:.3,pointRadius:0,borderWidth:1.5}]));
    }
    const iv=Math.max(0,eq-ca);
    mk('allocationChart',{type:'doughnut',data:{labels:['Cash','Invested'],datasets:[{data:[ca,iv],backgroundColor:[DI,AC],borderColor:'#080c10',borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,labels:{color:'#4a6278',boxWidth:10}}}}});
    // ── Positions mini-table ──────────────────────────────────────────────
    const pos=d.positions||[];
    const posEl=document.getElementById('ov-positions');
    const posCt=document.getElementById('ov-pos-count');
    if(posCt)posCt.textContent=pos.length?`${pos.length} open`:'';
    if(posEl){
      posEl.innerHTML=pos.length?`<table style="width:100%;border-collapse:collapse"><thead><tr style="color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1px"><th style="text-align:left;padding:4px 6px">Symbol</th><th style="text-align:left;padding:4px 6px">Pair</th><th style="text-align:right;padding:4px 6px">Qty</th><th style="text-align:right;padding:4px 6px">Entry</th><th style="text-align:right;padding:4px 6px">Price</th><th style="text-align:right;padding:4px 6px">Value</th><th style="text-align:right;padding:4px 6px">P&L</th><th style="text-align:right;padding:4px 6px">%</th><th style="text-align:right;padding:4px 6px"></th></tr></thead><tbody>`+
        pos.map(p=>{const pl=parseFloat(p.unrealized_pl||0);const plpc=(parseFloat(p.unrealized_plpc||0)*100).toFixed(2);const col=pl>=0?'var(--green)':'var(--red)';
          return `<tr style="border-top:1px solid #0d1520"><td style="padding:5px 6px;color:var(--accent)">${p.symbol}</td><td style="padding:5px 6px;color:var(--dim);font-size:10px">${p.pair||''}</td><td style="padding:5px 6px;text-align:right">${p.qty}</td><td style="padding:5px 6px;text-align:right">${f4(p.avg_entry_price)}</td><td style="padding:5px 6px;text-align:right">${f4(p.current_price)}</td><td style="padding:5px 6px;text-align:right">${f$(p.market_value)}</td><td style="padding:5px 6px;text-align:right;color:${col}">${f$(pl)}</td><td style="padding:5px 6px;text-align:right;color:${col}">${plpc}%</td><td style="padding:5px 6px;text-align:right"><button class="btn bd" style="padding:2px 8px;font-size:10px" onclick="closePos('${p.symbol}')">X</button></td></tr>`;
        }).join('')+`</tbody></table>`
        :'<div style="color:var(--dim);padding:6px 0">No open positions</div>';
    }
    // ── Open orders mini-table ────────────────────────────────────────────
    const ords=d.orders||[];
    const ordEl=document.getElementById('ov-orders');
    const ordCt=document.getElementById('ov-ord-count');
    if(ordCt)ordCt.textContent=ords.length?`${ords.length} pending`:'';
    if(ordEl){
      ordEl.innerHTML=ords.length?`<table style="width:100%;border-collapse:collapse"><thead><tr style="color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:1px"><th style="text-align:left;padding:4px 6px">Symbol</th><th style="text-align:left;padding:4px 6px">Side</th><th style="text-align:right;padding:4px 6px">Qty</th><th style="text-align:right;padding:4px 6px">Filled</th><th style="text-align:right;padding:4px 6px">Limit</th><th style="text-align:left;padding:4px 6px">Status</th><th style="text-align:left;padding:4px 6px">Type</th><th style="text-align:left;padding:4px 6px">Created</th></tr></thead><tbody>`+
        ords.map(o=>{const col=o.side==='buy'?'var(--green)':'var(--red)';
          return `<tr style="border-top:1px solid #0d1520"><td style="padding:5px 6px;color:var(--accent)">${o.symbol}</td><td style="padding:5px 6px;color:${col};text-transform:uppercase">${o.side}</td><td style="padding:5px 6px;text-align:right">${o.qty}</td><td style="padding:5px 6px;text-align:right;color:var(--dim)">${o.filled_qty||0}</td><td style="padding:5px 6px;text-align:right">${o.limit_price?f4(o.limit_price):'MKT'}</td><td style="padding:5px 6px;color:var(--accent)">${o.status}</td><td style="padding:5px 6px;color:var(--dim)">${o.type}</td><td style="padding:5px 6px;color:var(--dim);font-size:10px">${o.created_at.slice(0,16)}</td></tr>`;
        }).join('')+`</tbody></table>`
        :'<div style="color:var(--dim);padding:6px 0">No open orders</div>';
    }
    if(pos.length)mk('exposureChart',cc('bar',pos.map(p=>p.symbol),[{data:pos.map(p=>Math.abs(parseFloat(p.market_value||0))),backgroundColor:pos.map(p=>parseFloat(p.unrealized_pl||0)>=0?'rgba(0,255,136,.4)':'rgba(255,68,102,.4)'),borderColor:pos.map(p=>parseFloat(p.unrealized_pl||0)>=0?GR:RE),borderWidth:1}]));
    const l=window._tl||[];const b={};
    l.forEach(t=>{const k=Math.round((t.pnl||0)/50)*50;b[k]=(b[k]||0)+1;});
    const ks=Object.keys(b).sort((a,b)=>+a-+b);
    if(ks.length)mk('pnlDistChart',cc('bar',ks.map(k=>'$'+k),[{data:ks.map(k=>b[k]),backgroundColor:ks.map(k=>+k>=0?'rgba(0,255,136,.5)':'rgba(255,68,102,.5)'),borderColor:ks.map(k=>+k>=0?GR:RE),borderWidth:1}]));
    loadPeriods();
  }catch(e){
    const cb=document.getElementById('conn-badge');
    if(e.message&&e.message.toLowerCase().includes('fetch')){
      if(cb)cb.style.display='inline';
    }else{
      lg('Account error: '+e.message,'warn');
    }
  }
  try{
    const sr=await fetch('/api/status');const sd=await sr.json();
    const ss=document.getElementById('sys-status');
    if(ss){
      const moc=sd.market_open?'<span style="color:var(--green)">● OPEN</span>':'<span style="color:var(--red)">● CLOSED</span>';
      ss.innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;padding:4px 0">`+
        `<div style="color:var(--dim)">Mode</div><div style="color:var(--accent)">${sd.mode}</div>`+
        `<div style="color:var(--dim)">Market</div><div>${moc}</div>`+
        `<div style="color:var(--dim)">Risk Level</div><div style="color:var(--accent)">${sd.risk_level}/10</div>`+
        `<div style="color:var(--dim)">Uptime</div><div>${sd.uptime}</div>`+
        `<div style="color:var(--dim)">Last Run</div><div style="color:var(--dim)">${sd.last_engine_run}</div>`+
        `<div style="color:var(--dim)">Open Trades</div><div style="color:var(--accent)">${sd.open_trades}</div>`+
        `<div style="color:var(--dim)">Closed Trades</div><div>${sd.closed_trades}</div>`+
        `<div style="color:var(--dim)">AI Brain</div><div>${sd.ai_connected?'<span style="color:var(--green)">● CONNECTED</span>':'<span style="color:var(--red)">● NO KEY</span>'}</div>`+
        `<div style="color:var(--dim)">Trend Memory</div><div style="${sd.trend_memory_stale?'color:var(--dim)':'color:var(--green)'}">${sd.trend_symbols_loaded} symbols${sd.trend_memory_stale?' (stale)':' ✓'}</div>`+
        `</div>`;
    }
  }catch(e){}
}

// ── Positions ──────────────────────────────────────────────────────────────
async function loadPositions(){
  try{
    const r=await fetch('/api/positions');const d=await r.json();const pos=d.positions||[];
    document.getElementById('pos-cards').innerHTML=pos.length?pos.map(p=>{
      const pl=parseFloat(p.unrealized_pl||0);const plpc=parseFloat(p.unrealized_plpc||0)*100;
      return `<div class="sc"><div class="lb">${p.symbol} <span style="color:var(--dim);font-size:10px">${p.pair||''}</span></div><div class="val ${pl>=0?'green':'red'}">${f$(pl)}</div><div class="sub">${f4(p.current_price)} &middot; ${plpc.toFixed(2)}%</div></div>`;
    }).join(''):'<div style="color:var(--dim);font-family:var(--mono);font-size:12px;padding:10px">No open positions</div>';
    if(pos.length){
      mk('positionPnlChart',cc('bar',pos.map(p=>p.symbol),[{data:pos.map(p=>parseFloat(p.unrealized_pl||0)),backgroundColor:pos.map(p=>parseFloat(p.unrealized_pl||0)>=0?'rgba(0,255,136,.4)':'rgba(255,68,102,.4)'),borderColor:pos.map(p=>parseFloat(p.unrealized_pl||0)>=0?GR:RE),borderWidth:1}]));
      mk('positionSizeChart',cc('bar',pos.map(p=>p.symbol),[{data:pos.map(p=>Math.abs(parseFloat(p.market_value||0))),backgroundColor:'rgba(0,229,255,.3)',borderColor:AC,borderWidth:1}]));
    }
    document.getElementById('pos-tbody').innerHTML=pos.length?pos.map(p=>{
      const pl=parseFloat(p.unrealized_pl||0);const plpc=(parseFloat(p.unrealized_plpc||0)*100).toFixed(2);
      return `<tr><td style="color:var(--accent)">${p.symbol}</td><td style="color:var(--dim)">${p.pair||''}</td><td>${Math.round(p.qty)}</td><td>${f4(p.avg_entry_price)}</td><td>${f4(p.current_price)}</td><td>${f$(p.market_value)}</td><td style="color:${pl>=0?'var(--green)':'var(--red)'}">${f$(pl)}</td><td style="color:${pl>=0?'var(--green)':'var(--red)'}">${plpc}%</td><td><button class="btn bd" style="padding:4px 8px;font-size:10px" onclick="closePos('${p.symbol}')">CLOSE</button></td></tr>`;
    }).join(''):'<tr><td colspan="9" style="color:var(--dim);text-align:center;padding:20px">No positions</td></tr>';
  }catch(e){console.error(e);}
}

// ── Performance ────────────────────────────────────────────────────────────
async function loadPerformance(){
  try{
    const [tlRes,perfRes]=await Promise.all([fetch('/api/trade_log'),fetch('/api/performance')]);
    const tlData=await tlRes.json();const perfData=await perfRes.json();
    window._tl=tlData.trades||[];
    const l=window._tl;const cl=l.filter(t=>t.status==='closed');
    const wi=cl.filter(t=>(t.pnl||0)>0);const lo=cl.filter(t=>(t.pnl||0)<=0);
    const gw=wi.reduce((s,t)=>s+(t.pnl||0),0);const gl=Math.abs(lo.reduce((s,t)=>s+(t.pnl||0),0));
    const pf=gl>0?(gw/gl).toFixed(2):'N/A';const wr=cl.length>0?(wi.length/cl.length*100).toFixed(1)+'%':'--';
    const isEmpty=cl.length===0;
    document.getElementById('perf-empty').style.display=isEmpty?'block':'none';
    document.getElementById('p-total').textContent=cl.length||0;
    document.getElementById('p-winrate').textContent=wr;document.getElementById('p-winrate').className='val '+(parseFloat(wr)>=50?'green':'red');
    document.getElementById('p-avgwin').textContent=wi.length?f$(gw/wi.length):'--';
    document.getElementById('p-avgloss').textContent=lo.length?f$(-gl/lo.length):'--';
    document.getElementById('p-pf').textContent=pf;document.getElementById('p-pf').className='val '+(+pf>=1&&pf!='N/A'?'green':'red');
    const ps=cl.map(t=>t.pnl||0);
    document.getElementById('p-best').textContent=ps.length?f$(Math.max(...ps)):'--';
    document.getElementById('p-worst').textContent=ps.length?f$(Math.min(...ps)):'--';
    if(!isEmpty){
      let cu=0;const cd=cl.map(t=>{cu+=t.pnl||0;return cu;});
      mk('cumulPnlChart',cc('line',cl.map((_,i)=>'T'+(i+1)),[{data:cd,borderColor:cu>=0?GR:RE,backgroundColor:cu>=0?'rgba(0,255,136,.07)':'rgba(255,68,102,.07)',fill:true,tension:.3,pointRadius:2,borderWidth:2}]));
      mk('winLossChart',{type:'doughnut',data:{labels:['Wins','Losses','Open'],datasets:[{data:[wi.length,lo.length,l.length-cl.length],backgroundColor:['rgba(0,255,136,.6)','rgba(255,68,102,.6)','rgba(0,229,255,.4)'],borderColor:'#080c10',borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,labels:{color:'#4a6278',boxWidth:10}}}}});
      const sm={};cl.forEach(t=>{sm[t.symbol]=(sm[t.symbol]||0)+(t.pnl||0);});const sy=Object.keys(sm);
      if(sy.length)mk('symPnlChart',cc('bar',sy,[{data:sy.map(s=>sm[s]),backgroundColor:sy.map(s=>sm[s]>=0?'rgba(0,255,136,.4)':'rgba(255,68,102,.4)'),borderColor:sy.map(s=>sm[s]>=0?GR:RE),borderWidth:1}]));
      const du=cl.filter(t=>t.duration_min).map(t=>Math.round(t.duration_min/60));
      const db={},lb=['<1h','1-4h','4-8h','8-24h','1-3d','3d+'];
      du.forEach(h=>{const bk=h<1?'<1h':h<4?'1-4h':h<8?'4-8h':h<24?'8-24h':h<72?'1-3d':'3d+';db[bk]=(db[bk]||0)+1;});
      mk('durationChart',cc('bar',lb,[{data:lb.map(l=>db[l]||0),backgroundColor:'rgba(0,229,255,.3)',borderColor:AC,borderWidth:1}]));
      let pk=0;cu=0;
      const dd=cl.map(t=>{cu+=t.pnl||0;pk=Math.max(pk,cu);return pk>0?((cu-pk)/pk*100):0;});
      document.getElementById('p-dd').textContent=dd.length?fp(Math.min(...dd)):'--';
      mk('drawdownChart',cc('line',cl.map((_,i)=>'T'+(i+1)),[{data:dd,borderColor:RE,backgroundColor:'rgba(255,68,102,.07)',fill:true,tension:.3,pointRadius:0,borderWidth:1.5}]));
    }
  }catch(e){console.error('Performance error:',e);}
}

// ── Market Intelligence (AI Trend Memory) ──────────────────────────────────
async function loadIntelligence(){
  const panel=document.getElementById('intelligence-panel');
  panel.style.display='block';
  panel.innerHTML='<div style="font-family:var(--mono);color:var(--dim);padding:16px">Loading AI market intelligence...</div>';
  try{
    const r=await fetch('/api/market_intelligence');const d=await r.json();
    const syms=d.symbols||{};const macro=d.macro_overview||'';const stale=d.stale;
    const staleNote=stale?'<span style="color:#ffb400;font-size:10px;margin-left:8px">STALE — refresh recommended</span>':'';
    const ts=d.last_updated?new Date(d.last_updated).toLocaleString():'never';
    let html=`<div class="cp" style="margin-bottom:12px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <span style="font-family:var(--mono);font-size:13px;color:var(--accent)">AI Macro Overview</span>
        <span style="font-family:var(--mono);font-size:10px;color:var(--dim)">Updated: ${ts}${staleNote}</span>
        <button class="rb" onclick="refreshIntelligence()" style="font-size:11px;padding:4px 10px">Refresh</button>
      </div>
      <div style="font-family:var(--mono);font-size:12px;color:var(--text);line-height:1.7;font-style:italic">${macro||'No macro analysis yet. Click Refresh to generate.'}</div>
    </div>
    <div class="g2 gap">`;
    for(const[sym,mem] of Object.entries(syms)){
      const dir=mem.trend_direction||'?';const str=mem.trend_strength||'?';
      const dirColor=dir==='bullish'?'var(--green)':dir==='bearish'?'var(--red)':'var(--dim)';
      html+=`<div class="cp">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span style="font-family:var(--mono);font-size:16px;color:var(--accent)">${sym}</span>
          <span style="font-family:var(--mono);font-size:11px;color:${dirColor};text-transform:uppercase">${dir} / ${str}</span>
        </div>
        <div style="font-size:11px;color:var(--dim);margin-bottom:6px;font-style:italic">${mem.pattern_notes||''}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-family:var(--mono);font-size:10px">
          <div><span style="color:var(--dim)">Support</span><br><span style="color:var(--green)">${mem.key_support||'--'}</span></div>
          <div><span style="color:var(--dim)">Resistance</span><br><span style="color:var(--red)">${mem.key_resistance||'--'}</span></div>
        </div>
        <div style="margin-top:8px;font-size:10px;color:var(--dim)"><span style="color:#ffb400">Macro:</span> ${mem.macro_context||'--'}</div>
        <div style="margin-top:4px;font-size:10px;color:var(--dim)"><span style="color:var(--accent)">Watch for:</span> ${mem.watch_for||'--'}</div>
        <div style="margin-top:4px;font-size:10px;color:var(--red)"><span style="color:var(--dim)">Risk:</span> ${mem.risk_notes||'--'}</div>
      </div>`;
    }
    html+='</div>';
    if(!Object.keys(syms).length) html+='<div style="font-family:var(--mono);color:var(--dim);padding:20px;text-align:center">No intelligence data yet. Click Refresh to run AI analysis on all symbols.</div>';
    panel.innerHTML=html;
  }catch(e){panel.innerHTML='<div style="color:var(--red);font-family:var(--mono);padding:16px">Intelligence error: '+e.message+'</div>';}
}
async function refreshIntelligence(){
  try{
    await fetch('/api/market_intelligence/refresh',{method:'POST'});
    setTimeout(loadIntelligence,3000);
  }catch(e){console.error(e);}
}

// ── FX Research ────────────────────────────────────────────────────────────
async function forceScan(){
  await fetch('/api/scan/refresh',{method:'POST'});
  const cards=document.getElementById('scan-cards');
  cards.innerHTML='<div style="font-family:var(--mono);color:var(--accent);padding:20px">⟳ Scan running — AI analyzing 16 symbols... refresh in ~45 seconds</div>';
  setTimeout(loadResearch, 45000);
}
async function loadResearch(){
  const cards=document.getElementById('scan-cards');
  try{
    const r=await fetch('/api/scan');const d=await r.json();
    if(d.scanning){
      cards.innerHTML='<div style="font-family:var(--mono);color:var(--accent);padding:20px">⟳ AI scan running — analyzing all symbols... <button class="rb" style="margin-left:12px" onclick="setTimeout(loadResearch,30000);this.disabled=true;this.textContent=\'Waiting...\'">Check Again in 30s</button></div>';
      return;
    }
    const res=d.results||[];
    const syms=res.map(r=>r.symbol);
    const scores=res.map(r=>r.score||0);
    const rsis=res.map(r=>r.rsi||0);
    mk('scoreChart',cc('bar',syms,[{data:scores,backgroundColor:scores.map(s=>s>=4?'rgba(0,255,136,.5)':'rgba(74,98,120,.3)'),borderColor:scores.map(s=>s>=4?GR:DI),borderWidth:1}]));
    mk('rsiChart',cc('bar',syms,[{data:rsis,backgroundColor:rsis.map(r=>r<=38?'rgba(0,255,136,.5)':r>=70?'rgba(255,68,102,.5)':'rgba(0,229,255,.3)'),borderColor:rsis.map(r=>r<=38?GR:r>=70?RE:AC),borderWidth:1}]));
    // AI market overview banner
    const ovEl=document.getElementById('ai-overview');
    if(ovEl&&d.ai_overview){ovEl.textContent='AI: '+d.ai_overview;ovEl.style.display='block';}
    cards.innerHTML=res.map(s=>{
      const hasSig=s.signal!=null;const trendUp=s.trend_up;
      const dir=s.direction||'long';
      const rsiColor=s.rsi<=38?'var(--green)':s.rsi>=70?'var(--red)':'var(--text)';
      const macdColor=s.macd_hist>0?'var(--green)':'var(--red)';
      const rsiPct=s.rsi?(s.rsi/100*100):50;
      const regime=s.regime||'normal';
      const regimeBadge=regime==='slow'?`<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:3px;background:rgba(255,180,0,.12);color:#ffb400;border:1px solid rgba(255,180,0,.3)">SLOW</span>`:regime==='active'?`<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:3px;background:rgba(0,255,136,.1);color:var(--green);border:1px solid rgba(0,255,136,.3)">ACTIVE</span>`:'';
      const dirBadge=hasSig?(dir==='short'?`<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:3px;background:rgba(255,68,102,.12);color:var(--red);border:1px solid rgba(255,68,102,.3)">SHORT ↓</span>`:dir==='bounce'?`<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:3px;background:rgba(255,180,0,.12);color:#ffb400;border:1px solid rgba(255,180,0,.3)">BOUNCE ↑</span>`:`<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:3px;background:rgba(0,255,136,.12);color:var(--green);border:1px solid rgba(0,255,136,.3)">LONG ↑</span>`):'';
      const scoreRow=`<div style="display:flex;gap:8px;margin-bottom:10px;font-family:var(--mono);font-size:10px"><span style="color:var(--green)">L:${s.long_score||0}</span><span style="color:var(--red)">S:${s.short_score||0}</span><span style="color:#ffb400">B:${s.bounce_score||0}</span></div>`;
      const notes=(s.notes||[]).map(n=>`<span style="font-family:var(--mono);font-size:10px;padding:2px 6px;border-radius:3px;background:rgba(0,229,255,.08);color:var(--dim);border:1px solid var(--border)">${n.replace(/_/g,' ')}</span>`).join(' ');
      const aiConf=s.ai_confidence;const aiAction=s.ai_action||'';const aiReason=s.ai_reason||'';
      const aiColor=aiConf>=8?'var(--green)':aiConf>=5?'var(--accent)':'var(--red)';
      const aiBlock=aiConf!=null?`<div style="margin-top:10px;padding:8px 10px;border-radius:4px;background:rgba(0,229,255,.04);border:1px solid rgba(0,229,255,.12)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <span style="font-family:var(--mono);font-size:10px;color:var(--dim)">AI ANALYST</span>
          <div style="flex:1;height:4px;background:#0f1a24;border-radius:2px"><div style="width:${aiConf*10}%;height:100%;background:${aiColor};border-radius:2px"></div></div>
          <span style="font-family:var(--mono);font-size:11px;color:${aiColor}">${aiConf}/10</span>
          <span style="font-family:var(--mono);font-size:10px;padding:1px 6px;border-radius:3px;background:${aiAction==='enter'?'rgba(0,255,136,.12)':aiAction==='reduce'?'rgba(255,180,0,.12)':'rgba(255,68,102,.12)'};color:${aiAction==='enter'?'var(--green)':aiAction==='reduce'?'#ffb400':'var(--red)'}">${aiAction.toUpperCase()}</span>
        </div>
        <div style="font-size:11px;color:var(--dim);font-style:italic">${aiReason}</div>
      </div>`:'';
      const pol=s.political||{};
      const polBlock=(pol.buys||pol.sells)?`<div style="margin-top:6px;font-family:var(--mono);font-size:10px;color:var(--dim);padding:5px 8px;border-radius:3px;background:rgba(255,255,255,.02);border:1px solid var(--border)"><span style="color:#ffb400">CONGRESS</span> — ${pol.summary||''}</div>`:'';
      return `<div class="scan-card">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:2px">
          <div><span class="scan-sym">${s.symbol}</span></div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            ${regimeBadge}${dirBadge}
            ${hasSig?`<span class="badge signal">SCORE ${s.score}</span>`:trendUp?`<span class="badge trend">TREND ↑</span>`:`<span class="badge nosig">NO SIGNAL</span>`}
          </div>
        </div>
        <div class="scan-pair">${s.pair||''}</div>
        ${scoreRow}
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-bottom:12px">
          <div class="sc"><div class="lb">Price</div><div class="val" style="font-size:14px">${s.last_close!=null?s.last_close.toFixed(4):'--'}</div></div>
          <div class="sc"><div class="lb">RSI</div><div class="val" style="font-size:14px;color:${rsiColor}">${s.rsi!=null?s.rsi.toFixed(1):'--'}</div></div>
          <div class="sc"><div class="lb">ATR</div><div class="val" style="font-size:14px">${s.atr!=null?s.atr.toFixed(4):'--'}</div></div>
          <div class="sc"><div class="lb">ADX</div><div class="val" style="font-size:14px">${s.adx!=null?s.adx.toFixed(1):'--'}</div></div>
          <div class="sc"><div class="lb">MACD Hist</div><div class="val" style="font-size:14px;color:${macdColor}">${s.macd_hist!=null?s.macd_hist.toFixed(5):'--'}</div></div>
          <div class="sc"><div class="lb">10d Pull%</div><div class="val" style="font-size:14px;color:${(s.pullback_10d_pct||0)<0?'var(--red)':'var(--green)'}">${s.pullback_10d_pct!=null?s.pullback_10d_pct.toFixed(2)+'%':'--'}</div></div>
        </div>
        <div class="ind-row"><span class="ind-lbl">RSI</span><div class="ind-bar"><div class="ind-fill" style="width:${rsiPct}%;background:${rsiColor}"></div></div><span class="ind-val" style="color:${rsiColor}">${s.rsi!=null?s.rsi.toFixed(1):'--'}</span></div>
        <div class="ind-row"><span class="ind-lbl">SMA50</span><div class="ind-bar"><div class="ind-fill" style="width:${s.sma50&&s.last_close?Math.min(s.last_close/s.sma50*100,110)-10:0}%;background:var(--accent)"></div></div><span class="ind-val">${s.sma50!=null?s.sma50.toFixed(4):'--'}</span></div>
        <div class="ind-row"><span class="ind-lbl">SMA150</span><div class="ind-bar"><div class="ind-fill" style="width:${s.sma150&&s.last_close?Math.min(s.last_close/s.sma150*100,110)-10:0}%;background:#7788ff"></div></div><span class="ind-val">${s.sma150!=null?s.sma150.toFixed(4):'--'}</span></div>
        <div class="ind-row"><span class="ind-lbl">SMA200</span><div class="ind-bar"><div class="ind-fill" style="width:${s.sma200&&s.last_close?Math.min(s.last_close/s.sma200*100,110)-10:0}%;background:var(--yellow)"></div></div><span class="ind-val">${s.sma200!=null?s.sma200.toFixed(4):'--'}</span></div>
        ${notes?`<div style="margin-top:10px;display:flex;gap:5px;flex-wrap:wrap">${notes}</div>`:''}
        ${s.legendary_score!=null?`<div style="margin-top:8px;padding:8px 10px;border-radius:4px;background:rgba(255,180,0,.04);border:1px solid rgba(255,180,0,.15)">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px">LEGENDARY SCORE</span>
            <div style="flex:1;height:4px;background:#0f1a24;border-radius:2px"><div style="width:${Math.round(s.legendary_score/s.legendary_max*100)}%;height:100%;background:${s.legendary_recommend?'#ffc107':'var(--dim)'};border-radius:2px"></div></div>
            <span style="font-family:var(--mono);font-size:12px;color:${s.legendary_recommend?'#ffc107':'var(--dim)'};font-weight:bold">${s.legendary_score}/${s.legendary_max}</span>
            <span style="font-family:var(--mono);font-size:10px;padding:1px 7px;border-radius:3px;background:${s.legendary_recommend?'rgba(255,193,7,.15)':'rgba(74,98,120,.15)'};color:${s.legendary_recommend?'#ffc107':'var(--dim)';border:1px solid ${s.legendary_recommend?'rgba(255,193,7,.3)':'var(--border)'}">${s.legendary_recommend?'✓ APPROVED':'✗ VETOED'}</span>
          </div>
        </div>`:''}
        ${aiBlock}${polBlock}
      </div>`;
    }).join('');
  }catch(e){cards.innerHTML='<div style="color:var(--red);font-family:var(--mono);padding:20px">Scan error: '+e.message+'</div>';}
}

// ── Trade Log ──────────────────────────────────────────────────────────────
async function loadTradeLog(){
  try{
    const r=await fetch('/api/trade_log');const d=await r.json();window._tl=d.trades||[];const tr=window._tl;
    const cl=tr.filter(t=>t.status==='closed');
    mk('tradeTimeChart',{type:'scatter',data:{datasets:[{data:cl.map((t,i)=>({x:i+1,y:t.pnl||0})),backgroundColor:cl.map(t=>(t.pnl||0)>=0?'rgba(0,255,136,.7)':'rgba(255,68,102,.7)'),pointRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278'}},y:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278'}}}}});
    const sm={};cl.forEach(t=>{sm[t.symbol]=(sm[t.symbol]||0)+(t.pnl||0);});const sy=Object.keys(sm);
    if(sy.length)mk('etfPnlChart',cc('bar',sy,[{data:sy.map(s=>sm[s]),backgroundColor:sy.map(s=>sm[s]>=0?'rgba(0,255,136,.4)':'rgba(255,68,102,.4)'),borderColor:sy.map(s=>sm[s]>=0?GR:RE),borderWidth:1}]));
    document.getElementById('log-tbody').innerHTML=tr.slice().reverse().map(t=>{
      const pl=t.pnl||0;
      return `<tr><td style="color:var(--dim)">${t.time||'--'}</td><td style="color:var(--accent)">${t.symbol||'--'}</td><td style="color:var(--dim)">${t.pair||'--'}</td><td>${t.qty||'--'}</td><td>${f4(t.entry)}</td><td>${f4(t.exit)}</td><td style="color:${pl>=0?'var(--green)':'var(--red)'}">${f$(pl)}</td><td style="color:${pl>=0?'var(--green)':'var(--red)'}">${fp(t.pnl_pct)}</td><td style="color:var(--dim)">${t.exit_reason||'--'}</td><td><span class="badge ${t.status==='open'?'open':'closed'}">${t.status||'--'}</span></td></tr>`;
    }).join('')||'<tr><td colspan="10" style="color:var(--dim);text-align:center;padding:20px">No trades yet</td></tr>';
  }catch(e){console.error(e);}
}

// ── Controls ───────────────────────────────────────────────────────────────
async function loadControl(){
  loadRisk();
  loadBudget();
  loadHedge();
  try{
    const r=await fetch('/api/quotes');const d=await r.json();const q=d.quotes||{};
    document.getElementById('watchlist-tbody').innerHTML=Object.entries(q).map(([sym,v])=>{
      const chg=v.change_pct??0;
      return `<tr><td style="color:var(--accent)">${sym}</td><td style="color:var(--dim)">${v.pair||''}</td><td>${(v.price||0).toFixed(4)}</td><td style="color:${chg>=0?'var(--green)':'var(--red)'}">${fp(chg)}</td></tr>`;
    }).join('');
  }catch(e){}
  try{
    const sr=await fetch('/api/status');const sd=await sr.json();
    const ss=document.getElementById('ctrl-status');
    if(ss){
      const moc=sd.market_open?'<span style="color:var(--green)">● OPEN</span>':'<span style="color:var(--red)">● CLOSED</span>';
      ss.innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;padding:4px 0">`+
        `<div style="color:var(--dim)">Mode</div><div style="color:var(--accent)">${sd.mode}</div>`+
        `<div style="color:var(--dim)">Market</div><div>${moc}</div>`+
        `<div style="color:var(--dim)">Risk Level</div><div style="color:var(--accent)">${sd.risk_level}/10</div>`+
        `<div style="color:var(--dim)">Uptime</div><div>${sd.uptime}</div>`+
        `<div style="color:var(--dim)">Last Run</div><div style="color:var(--dim)">${sd.last_engine_run}</div>`+
        `<div style="color:var(--dim)">Last Result</div><div style="color:var(--dim)">${sd.last_engine_result}</div>`+
        `<div style="color:var(--dim)">Open Trades</div><div style="color:var(--accent)">${sd.open_trades}</div>`+
        `<div style="color:var(--dim)">Closed Trades</div><div>${sd.closed_trades}</div>`+
        `<div style="color:var(--dim)">AI Brain</div><div>${sd.ai_connected?'<span style="color:var(--green)">● CONNECTED</span>':'<span style="color:var(--red)">● NO KEY</span>'}</div>`+
        `<div style="color:var(--dim)">Trend Memory</div><div style="${sd.trend_memory_stale?'color:var(--dim)':'color:var(--green)'}">${sd.trend_symbols_loaded} symbols${sd.trend_memory_stale?' (stale)':' ✓'}</div>`+
        `</div>`;
    }
  }catch(e){}
}

// ── Crypto ────────────────────────────────────────────────────────────────────
async function loadCrypto(){
  try{
    const r=await fetch('/api/crypto');const d=await r.json();
    const el=document.getElementById('crypto-cards');
    if(!el||!d.crypto)return;
    if(!d.crypto.length){el.innerHTML='<div style="color:var(--dim);font-family:var(--mono);padding:16px">No crypto data yet.</div>';return;}
    el.innerHTML=d.crypto.map(c=>{
      const sigCol=c.signal?'#f7931a':'var(--dim)';
      const rsiCol=c.rsi<25?'var(--red)':c.rsi<40?'#ffb400':'var(--green)';
      const chgCol=c.change_pct>=0?'var(--green)':'var(--red)';
      return `<div class="cp">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span style="font-family:var(--mono);font-size:14px;color:#f7931a;font-weight:bold">${c.symbol}</span>
          <span style="font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:3px;background:rgba(247,147,26,.15);color:${sigCol}">${c.signal?c.signal.toUpperCase()+' '+c.score:'NO SIGNAL'}</span>
        </div>
        <div style="font-size:20px;font-weight:bold;margin-bottom:6px">$${c.price.toLocaleString()}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;font-family:var(--mono);font-size:11px">
          <div><div style="color:var(--dim)">RSI</div><div style="color:${rsiCol}">${c.rsi}</div></div>
          <div><div style="color:var(--dim)">ADX</div><div>${c.adx}</div></div>
          <div><div style="color:var(--dim)">10D</div><div style="color:${chgCol}">${c.change_pct>=0?'+':''}${c.change_pct}%</div></div>
        </div>
      </div>`;
    }).join('');
  }catch(e){}
}
// ── Crypto Tab ────────────────────────────────────────────────────────────────
async function loadCryptoChart(){
  const sym = document.getElementById('crypto-sym-select')?.value || 'BTC/USD';
  document.getElementById('crypto-chart-title').textContent = sym + ' — Price Chart (90 days)';
  try {
    const r = await fetch('/api/crypto_chart?symbol='+encodeURIComponent(sym));
    const d = await r.json();
    if(d.error){console.error('Crypto chart error:',d.error);return;}

    // Price line chart with entry/exit scatter points
    const priceDs = [{
      label: sym, data: d.price_data,
      borderColor:'#f7931a', backgroundColor:'rgba(247,147,26,.08)',
      fill:true, tension:.2, pointRadius:0, borderWidth:1.5, order:2
    }];
    if(d.entry_points.length){
      priceDs.push({label:'Entry', data: d.price_labels.map((_,i)=>{const p=d.entry_points.find(e=>e.x===i);return p?p.y:null;}),
        type:'scatter', pointStyle:'triangle', pointRadius:10, pointBackgroundColor:'#00ff88',
        pointBorderColor:'#00ff88', showLine:false, order:1});
    }
    if(d.exit_points.length){
      priceDs.push({label:'Exit', data: d.price_labels.map((_,i)=>{const p=d.exit_points.find(e=>e.x===i);return p?p.y:null;}),
        type:'scatter', pointStyle:'triangle', rotation:180, pointRadius:10, pointBackgroundColor:'#ff4466',
        pointBorderColor:'#ff4466', showLine:false, order:1});
    }
    mk('cryptoPriceChart',{type:'line',data:{labels:d.price_labels,datasets:priceDs},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:d.entry_points.length>0||d.exit_points.length>0,labels:{color:'#4a6278',boxWidth:10,font:{size:10}}}},scales:{x:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278',maxTicksLimit:12}},y:{grid:{color:'#0f1a24'},ticks:{color:'#4a6278'}}}}});

    // Cumulative P&L chart
    const cpnl = d.cum_pnl || [];
    if(cpnl.length){
      const lastVal = cpnl[cpnl.length-1]?.pnl || 0;
      const pnlColor = lastVal >= 0 ? '#00ff88' : '#ff4466';
      mk('cryptoPnlChart', cc('line', cpnl.map(e=>e.date.slice(5)), [{data:cpnl.map(e=>e.pnl), borderColor:pnlColor, backgroundColor:lastVal>=0?'rgba(0,255,136,.08)':'rgba(255,68,102,.08)', fill:true, tension:.3, pointRadius:cpnl.length<=20?3:1, borderWidth:1.5}]));
    } else {
      const el=document.getElementById('cryptoPnlChart');if(el){const ctx=el.getContext('2d');ctx.font='11px monospace';ctx.fillStyle='#4a6278';ctx.textAlign='center';ctx.fillText('No closed crypto trades yet',el.width/2,el.height/2);}
    }

    // Win/Loss donut
    if(d.wins+d.losses>0){
      mk('cryptoWinLossChart',{type:'doughnut',data:{labels:['Wins','Losses'],datasets:[{data:[d.wins,d.losses],backgroundColor:['rgba(0,255,136,.7)','rgba(255,68,102,.7)'],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,labels:{color:'#4a6278',boxWidth:10,font:{size:10}}}}}});
    }

    // Crypto trade log
    const tbody=document.getElementById('crypto-log-tbody');
    if(tbody){
      tbody.innerHTML = d.trades.length ? d.trades.slice().reverse().map(t=>{
        const pc=parseFloat(t.pnl||0)>=0?'var(--green)':'var(--red)';
        return `<tr><td>${(t.time||'').slice(5,16)}</td><td style="color:#f7931a">${t.symbol}</td><td>${t.qty}</td><td>${t.entry?'$'+parseFloat(t.entry).toFixed(4):'--'}</td><td>${t.exit?'$'+parseFloat(t.exit).toFixed(4):'--'}</td><td style="color:${pc}">${t.pnl!=null?'$'+parseFloat(t.pnl).toFixed(4):'--'}</td><td style="color:${pc}">${t.pnl_pct!=null?(t.pnl_pct>=0?'+':'')+parseFloat(t.pnl_pct).toFixed(2)+'%':'--'}</td><td>${t.status||''}</td></tr>`;
      }).join('') : '<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px">No crypto trades yet — bot is scanning 24/7</td></tr>';
    }
  } catch(e){console.error('loadCryptoChart',e);}
}

async function loadCryptoTab(){
  // Load stats row: Fear & Greed + crypto cards
  try {
    const r = await fetch('/api/crypto_chart?symbol=BTC%2FUSD');
    const d = await r.json();
    const fg = d.fear_greed || {value:50, classification:'Neutral'};
    const fgColor = fg.value<=25?'#ff4466':fg.value<=45?'#ffb400':fg.value<=55?'#4a6278':fg.value<=75?'#00cfff':'#00ff88';
    const statsEl = document.getElementById('crypto-stats-row');
    if(statsEl){
      statsEl.innerHTML = `
        <div class="cp" style="text-align:center">
          <div style="font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:6px">FEAR & GREED INDEX</div>
          <div style="font-size:48px;font-weight:bold;color:${fgColor};line-height:1">${fg.value}</div>
          <div style="font-family:var(--mono);font-size:13px;color:${fgColor};margin-top:4px">${fg.classification.toUpperCase()}</div>
          <div style="margin-top:10px;background:#0d1a26;border-radius:4px;height:8px;overflow:hidden">
            <div style="height:100%;width:${fg.value}%;background:linear-gradient(90deg,#ff4466,#ffb400,#00ff88);border-radius:4px"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:9px;color:var(--dim);margin-top:2px"><span>FEAR</span><span>GREED</span></div>
        </div>
        <div class="cp">
          <div style="font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:8px">CRYPTO ENGINE</div>
          <div style="font-family:var(--mono);font-size:12px;color:var(--fg);line-height:2">
            <div>&#9679; Runs every <span style="color:#f7931a">15 min</span> 24/7</div>
            <div>&#9679; Scanning <span style="color:#f7931a">15 pairs: BTC · ETH · SOL · AVAX · DOGE · LINK · LTC · BCH · AAVE · UNI · XRP · DOT · MATIC · SHIB · ADA</span></div>
            <div>&#9679; Strategy: Long + Bounce signals</div>
            <div>&#9679; No PDT restrictions on crypto</div>
          </div>
        </div>
        <div class="cp">
          <div style="font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:8px">SIGNAL GUIDE</div>
          <div style="font-family:var(--mono);font-size:11px;line-height:2">
            <div><span style="color:#00ff88">▲ LONG</span> — RSI pullback in uptrend</div>
            <div><span style="color:#f7931a">▲ BOUNCE</span> — RSI &lt; 22, extreme oversold</div>
            <div style="color:var(--dim);font-size:10px;margin-top:4px">Fear &amp; Greed &lt; 25 = buy opportunity</div>
            <div style="color:var(--dim);font-size:10px">Fear &amp; Greed &gt; 75 = reduce exposure</div>
          </div>
        </div>`;
    }
  } catch(e){}

  // Load live signal cards
  try {
    const r2 = await fetch('/api/crypto'); const d2 = await r2.json();
    const el = document.getElementById('crypto-tab-cards');
    if(el && d2.crypto){
      if(!d2.crypto.length){el.innerHTML='<div style="color:var(--dim);font-family:var(--mono);padding:16px">Scanning... no signals yet.</div>';return;}
      el.innerHTML = d2.crypto.map(c=>{
        const sigCol=c.signal?'#f7931a':'var(--dim)';
        const rsiCol=c.rsi<25?'var(--red)':c.rsi<40?'#ffb400':'var(--green)';
        const chgCol=c.change_pct>=0?'var(--green)':'var(--red)';
        return `<div class="cp" style="cursor:pointer" onclick="document.getElementById('crypto-sym-select').value='${c.symbol}';loadCryptoChart()">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-family:var(--mono);font-size:14px;color:#f7931a;font-weight:bold">${c.symbol}</span>
            <span style="font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:3px;background:rgba(247,147,26,.15);color:${sigCol}">${c.signal?c.signal.toUpperCase()+' '+c.score:'WATCHING'}</span>
          </div>
          <div style="font-size:20px;font-weight:bold;margin-bottom:6px">$${c.price.toLocaleString()}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;font-family:var(--mono);font-size:11px">
            <div><div style="color:var(--dim)">RSI</div><div style="color:${rsiCol}">${c.rsi}</div></div>
            <div><div style="color:var(--dim)">ADX</div><div>${c.adx}</div></div>
            <div><div style="color:var(--dim)">10D</div><div style="color:${chgCol}">${c.change_pct>=0?'+':''}${c.change_pct}%</div></div>
          </div>
          <div style="font-family:var(--mono);font-size:9px;color:var(--dim);margin-top:6px">Click to view chart</div>
        </div>`;
      }).join('');
    }
  } catch(e){}

  // Auto-load BTC chart
  loadCryptoChart();
}

// ── Market Clock ──────────────────────────────────────────────────────────────
async function loadMarketClock(){
  try{
    const r=await fetch('/api/markets');const d=await r.json();
    const el=document.getElementById('market-clock-items');
    if(!el||!d.markets)return;
    el.innerHTML=d.markets.map(m=>{
      const col=m.open?(m.id==='crypto'?'#f7931a':m.id.startsWith('nyc')?'var(--green)':'#00cfff'):'var(--dim)';
      const dot=m.open?'●':'○';
      return `<span style="font-family:var(--mono);font-size:10px;color:${col};white-space:nowrap" title="${m.name} ${m.local_day} ${m.local_time}">${dot} ${m.flag} ${m.name} <span style="font-size:9px;opacity:0.7">${m.local_time}</span></span>`;
    }).join('');
  }catch(e){}
}
setInterval(loadMarketClock, 60000);
loadMarketClock();

// ── Hedge ──────────────────────────────────────────────────────────────────
async function loadHedge(){
  try{
    const r=await fetch('/api/hedge');const d=await r.json();
    const badge=document.getElementById('hedge-status-badge');
    const hdr=document.getElementById('hedge-header-badge');
    const pnlRow=document.getElementById('hedge-pnl-row');
    const openList=document.getElementById('hedge-open-list');
    const toggleBtn=document.getElementById('hedge-toggle-btn');
    let badgeText,badgeBg,badgeColor;
    if(!d.enabled){badgeText='HEDGE OFF';badgeBg='rgba(74,98,120,.3)';badgeColor='var(--dim)';}
    else if(d.hedged){badgeText='HEDGED ✓';badgeBg='rgba(255,180,0,.2)';badgeColor='#ffb400';}
    else if(d.needs_hedge){badgeText='HEDGE!';badgeBg='rgba(255,68,100,.25)';badgeColor='var(--red)';}
    else{const pct=(d.pnl_pct||0).toFixed(1);badgeText=`HEDGE ON ${pct}%`;badgeBg='rgba(0,255,136,.1)';badgeColor='var(--green)';}
    if(badge){badge.textContent=badgeText;badge.style.background=badgeBg;badge.style.color=badgeColor;}
    if(hdr){hdr.textContent=badgeText;hdr.style.background=badgeBg;hdr.style.color=badgeColor;}
    if(pnlRow){
      const pct=d.pnl_pct||0;const col=pct>=0?'var(--green)':'var(--red)';
      pnlRow.innerHTML=`Portfolio P&L: <span style="color:${col}">${pct>=0?'+':''}${pct.toFixed(2)}%</span>`+
        ` &nbsp;|&nbsp; Trigger: <span style="color:#ffb400">-${d.trigger_pct||1.5}%</span>`;
    }
    if(openList){
      openList.innerHTML=d.open_hedges&&d.open_hedges.length?
        'Open hedges: '+d.open_hedges.map(s=>`<span style="color:#ffb400">${s}</span>`).join(', '):
        'No hedges open';
    }
    if(toggleBtn) toggleBtn.textContent=d.enabled?'DISABLE':'ENABLE';
    if(d.trigger_pct) document.getElementById('hedge-trigger').value=d.trigger_pct;
    if(d.ratio) document.getElementById('hedge-ratio').value=d.ratio;
  }catch(e){}
}
async function toggleHedge(){
  try{
    const r=await fetch('/api/hedge');const d=await r.json();
    await fetch('/api/hedge',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({enabled:!d.enabled})});
    loadHedge();
  }catch(e){}
}
async function saveHedgeConfig(){
  const trigger=parseFloat(document.getElementById('hedge-trigger').value)||1.5;
  const ratio=parseFloat(document.getElementById('hedge-ratio').value)||0.5;
  try{
    await fetch('/api/hedge',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({trigger_pct:trigger,ratio})});
    lg(`Hedge config saved: trigger=-${trigger}% ratio=${ratio}`,'');
    loadHedge();
  }catch(e){}
}
async function manualHedge(){
  if(!confirm('Open hedge positions NOW against current losing trades?'))return;
  try{
    const r=await fetch('/api/hedge/open',{method:'POST'});const d=await r.json();
    lg(d.opened&&d.opened.length?`Hedges opened: ${d.opened.join(', ')}`:'No hedges to open','');
    loadHedge();
  }catch(e){lg('Hedge error: '+e.message,'warn');}
}
async function closeHedges(){
  if(!confirm('Close ALL hedge positions?'))return;
  try{
    const r=await fetch('/api/hedge/close',{method:'POST'});const d=await r.json();
    lg(d.closed&&d.closed.length?`Hedges closed: ${d.closed.join(', ')}`:'No hedges to close','');
    loadHedge();
  }catch(e){lg('Hedge close error: '+e.message,'warn');}
}

// ── Budget ─────────────────────────────────────────────────────────────────
async function loadBudget(){
  try{
    const r=await fetch('/api/budget');const d=await r.json();
    const inp=document.getElementById('budget-input');
    if(inp&&d.budget>0) inp.value=d.budget;
    const st=document.getElementById('budget-status');
    const bar=document.getElementById('budget-bar');
    const barLabel=document.getElementById('budget-bar-label');
    const live=d.live;const modeColor=live?'var(--green)':'var(--accent)';
    if(st){
      const budgetTxt=d.unlimited?'<span style="color:var(--dim)">No limit set</span>':`<span style="color:var(--green)">$${d.budget.toFixed(2)}</span> budget`;
      st.innerHTML=`Mode: <span style="color:${modeColor}">${live?'LIVE':'PAPER'}</span> &nbsp;|&nbsp; ${budgetTxt}<br>`+
        `Equity: <span style="color:var(--accent)">$${(d.equity||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span> &nbsp;|&nbsp; `+
        `Buying Power: <span style="color:var(--text)">$${(d.buying_power||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`;
    }
    if(bar&&!d.unlimited&&d.budget>0){
      const pct=Math.min(d.budget_pct,100);
      bar.style.width=pct+'%';
      bar.style.background=pct>80?'var(--red)':pct>50?'#ffb400':'var(--green)';
      if(barLabel) barLabel.textContent=`$${d.budget.toFixed(2)} of $${(d.equity||0).toFixed(2)} equity (${d.budget_pct}%)`;
    }
  }catch(e){}
}
async function setBudget(val){
  const amount=val!==undefined?val:parseFloat(document.getElementById('budget-input').value||'0');
  try{
    const r=await fetch('/api/budget',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({budget:amount})});
    const d=await r.json();
    lg(d.unlimited?'Budget set to UNLIMITED':`Budget set to $${d.budget.toFixed(2)}`,'');
    loadBudget();
  }catch(e){lg('Budget error: '+e.message,'warn');}
}

// ── Risk ───────────────────────────────────────────────────────────────────
async function loadRisk(){
  try{const r=await fetch('/api/risk');const d=await r.json();document.getElementById('risk-slider').value=d.level;updateRiskDisplay(d.level);showRiskParams(d.params);}catch(e){}
}
function updateRiskDisplay(v){
  document.getElementById('risk-display').textContent=v+' / 10';
  const colors={1:'#00ff88',2:'#00ff88',3:'#7dff88',4:'#b8ff44',5:'#ffc107',6:'#ffaa00',7:'#ff8844',8:'#ff6633',9:'#ff4466',10:'#ff0044'};
  document.getElementById('risk-display').style.color=colors[v]||'var(--accent)';
}
function showRiskParams(p){
  if(!p)return;
  document.getElementById('risk-params').innerHTML=
    `<div class="sc"><div class="lb">Risk/Trade</div><div class="val" style="font-size:14px">${p.risk_per_trade_pct}%</div></div>`+
    `<div class="sc"><div class="lb">Stop ATR</div><div class="val" style="font-size:14px">${p.stop_atr_multiplier}x</div></div>`+
    `<div class="sc"><div class="lb">TP ATR</div><div class="val" style="font-size:14px">${p.take_profit_atr_multiplier}x</div></div>`+
    `<div class="sc"><div class="lb">Min Score</div><div class="val" style="font-size:14px">${p.min_signal_score}</div></div>`+
    `<div class="sc"><div class="lb">Max Pos</div><div class="val" style="font-size:14px">${p.max_positions}</div></div>`;
}
async function setRisk(v){
  try{const r=await fetch('/api/risk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({level:parseInt(v)})});const d=await r.json();showRiskParams(d.params);lg('Risk set to '+v+'/10');}catch(e){lg('Risk error: '+e.message,'warn');}
}

// ── Actions ────────────────────────────────────────────────────────────────
async function runDry(){lg('Starting dry run scan...','');try{const r=await fetch('/api/run_dry',{method:'POST'});const d=await r.json();lg(d.message||'Done','');setTimeout(loadOverview,3000);}catch(e){lg('Error: '+e.message,'warn');}}
async function runLive(){if(!confirm('Run engine live now?'))return;lg('Starting live engine run...','buy');try{const r=await fetch('/api/run_live',{method:'POST'});const d=await r.json();lg(d.message||'Done','buy');setTimeout(()=>{loadOverview();loadPositions();},5000);}catch(e){lg('Error: '+e.message,'warn');}}
async function seedHistory(){lg('Syncing trade history from Alpaca...','');try{const r=await fetch('/api/seed_history',{method:'POST'});const d=await r.json();lg(d.message||d.error||'Done','');setTimeout(()=>{loadPeriods();loadTradeLog();_periods_cache_client=null;},1000);}catch(e){lg('Seed error: '+e.message,'warn');}}
async function cancelAll(){try{const r=await fetch('/api/cancel_all',{method:'POST'});const d=await r.json();lg(d.message||'Cancelled','warn');}catch(e){lg('Error: '+e.message,'warn');}}
async function closePos(sym){if(!confirm('Close '+sym+'?'))return;try{const r=await fetch('/api/close/'+sym,{method:'POST'});const d=await r.json();lg(d.message||sym+' closed','sell');setTimeout(loadPositions,1500);}catch(e){lg('Error: '+e.message,'warn');}}

async function toggleMode(){
  try{const r=await fetch('/api/mode');const d=await r.json();const live=!d.live;const r2=await fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({live})});const d2=await r2.json();document.getElementById('mode-btn').textContent=d2.live?'LIVE':'PAPER';document.getElementById('mode-btn').style.borderColor=d2.live?'var(--red)':'var(--green)';document.getElementById('mode-btn').style.color=d2.live?'var(--red)':'var(--green)';lg('Mode: '+d2.mode,'');}catch(e){}
}

// ── Market Status ──────────────────────────────────────────────────────────
function updateMarketStatus(){
  const now=new Date();const et=new Date(now.toLocaleString("en-US",{timeZone:"America/New_York"}));
  const day=et.getDay();const h=et.getHours(),m=et.getMinutes(),s=et.getSeconds();
  const totalSec=h*3600+m*60+s;
  const preSec=4*3600;const openSec=9*3600+30*60;const closeSec=16*3600;const afterSec=20*3600;
  const isWeekday=day>=1&&day<=5;
  const statusEl=document.getElementById("market-status");const countEl=document.getElementById("countdown");
  if(!isWeekday){
    statusEl.textContent="WEEKEND";statusEl.style.color="var(--dim)";
    const monday=new Date(et);monday.setDate(et.getDate()+(day===6?2:1));monday.setHours(4,0,0,0);
    const diff=Math.floor((monday-et)/1000);countEl.textContent=`Pre-market opens in ${Math.floor(diff/3600)}h ${Math.floor((diff%3600)/60)}m`;
    return;
  }
  if(totalSec>=openSec&&totalSec<closeSec){
    statusEl.textContent="MARKET OPEN";statusEl.style.color="var(--green)";
    const rem=closeSec-totalSec;countEl.textContent=`Closes in ${Math.floor(rem/3600)}h ${String(Math.floor((rem%3600)/60)).padStart(2,"0")}m`;
  }else if(totalSec>=preSec&&totalSec<openSec){
    statusEl.textContent="PRE-MARKET";statusEl.style.color="#ffb400";
    const rem=openSec-totalSec;countEl.textContent=`Regular opens in ${Math.floor(rem/3600)}h ${String(Math.floor((rem%3600)/60)).padStart(2,"0")}m`;
  }else if(totalSec>=closeSec&&totalSec<afterSec){
    statusEl.textContent="AFTER HOURS";statusEl.style.color="#ffb400";
    const rem=afterSec-totalSec;countEl.textContent=`After-hours close in ${Math.floor(rem/3600)}h ${String(Math.floor((rem%3600)/60)).padStart(2,"0")}m`;
  }else{
    statusEl.textContent="MARKET CLOSED";statusEl.style.color="var(--red)";
    const tomorrow=new Date(et);if(totalSec>=afterSec){tomorrow.setDate(et.getDate()+1);}
    tomorrow.setHours(4,0,0,0);
    const diff=Math.floor((tomorrow-et)/1000);countEl.textContent=`Pre-market opens in ${Math.floor(diff/3600)}h ${Math.floor((diff%3600)/60)}m`;
  }
}
setInterval(updateMarketStatus,1000);updateMarketStatus();

// ── Engine Log ────────────────────────────────────────────────────────────────
async function loadLogs(){
  try{
    const r=await fetch('/api/logs');const d=await r.json();
    const el=document.getElementById('engine-log-lines');if(!el)return;
    const lvlCol={INFO:'var(--dim)',WARNING:'#ffb400',ERROR:'var(--red)'};
    el.innerHTML=d.logs.slice().reverse().map(l=>`<span style="color:${lvlCol[l.lvl]||'var(--dim)'}">[${l.t}] ${l.msg}</span>`).join('\n');
  }catch(e){}
}
async function runEngineNow(){
  const btn=event.target;btn.disabled=true;btn.textContent='Running...';
  const logPanel=document.getElementById('engine-log-panel');
  const logEl=document.getElementById('engine-log-lines');
  if(logPanel)logPanel.style.display='block';
  if(logEl)logEl.textContent='Running engine...';
  try{
    const r=await fetch('/api/run_now',{method:'POST'});const d=await r.json();
    const lvlCol={INFO:'var(--dim)',WARNING:'#ffb400',ERROR:'var(--red)'};
    if(logEl)logEl.innerHTML=d.logs.slice().reverse().map(l=>`<span style="color:${lvlCol[l.lvl]||'var(--dim)'}">[${l.t}] ${l.msg}</span>`).join('\n');
    lg(d.ok?'Engine run complete':'Engine error: '+(d.error||''),'');
    setTimeout(loadOverview,1000);
  }catch(e){if(logEl)logEl.textContent='Error: '+e.message;}
  finally{btn.disabled=false;btn.textContent='▶ Run Engine Now';}
}
setInterval(loadLogs,30000);

// ── Init ───────────────────────────────────────────────────────────────────
loadOverview();loadTape();loadHedge();loadBudget();loadCrypto();loadLogs();
setInterval(loadTape, 15000);
setInterval(loadOverview, 15000);
setInterval(loadHedge, 30000);
setInterval(loadBudget, 60000);
setInterval(()=>{
  const active = document.querySelector('.page.active');
  if(!active) return;
  const id = active.id.replace('page-','');
  if(id === 'positions') loadPositions();
  if(id === 'research'){ loadResearch(); loadCrypto(); }
  if(id === 'control') loadControl();
}, 300000);
// Load mode state
fetch('/api/mode').then(r=>r.json()).then(d=>{const btn=document.getElementById('mode-btn');btn.textContent=d.live?'LIVE':'PAPER';btn.style.borderColor=d.live?'var(--red)':'var(--green)';btn.style.color=d.live?'var(--red)':'var(--green)';}).catch(()=>{});
</script>
</body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
