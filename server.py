"""
Special K Forex - Dashboard Server
"""
import os, logging, threading
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, render_template_string, request, session, redirect
from dotenv import load_dotenv
import pytz

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "specialk-forex-2026")
DASH_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")

AZ = pytz.timezone("America/Phoenix")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == DASH_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        error = "Wrong password"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------------------------------------------------------------------
# Alpaca helpers
# ---------------------------------------------------------------------------
def get_broker():
    from special_k_forex.broker import Broker
    return Broker()

def get_account_data():
    try:
        broker = get_broker()
        acct = broker.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "error": None,
        }
    except Exception as e:
        return {"equity": 0, "cash": 0, "buying_power": 0, "error": str(e)}

def get_positions_data():
    try:
        broker = get_broker()
        positions = broker.get_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": round(float(p.unrealized_plpc) * 100, 2),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
            }
            for p in positions
        ]
    except Exception as e:
        log.error(f"Positions error: {e}")
        return []

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    acct = get_account_data()
    positions = get_positions_data()
    now_az = datetime.now(AZ).strftime("%Y-%m-%d %I:%M %p AZ")
    return render_template_string(
        DASHBOARD_HTML,
        acct=acct,
        positions=positions,
        now=now_az,
        paper=os.environ.get("ALPACA_PAPER", "true").lower() == "true",
    )

@app.route("/api/account")
@login_required
def api_account():
    return jsonify(get_account_data())

@app.route("/api/positions")
@login_required
def api_positions():
    return jsonify(get_positions_data())

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    dry = request.json.get("dry_run", True) if request.json else True
    def _run():
        try:
            from special_k_forex.config import settings
            from special_k_forex.engine import ForexEngine
            engine = ForexEngine(config=settings, dry_run=dry)
            engine.run()
        except Exception as e:
            log.error(f"Engine run error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "dry_run": dry})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>Special K Forex — Login</title>
<style>
  body { font-family: monospace; background: #0d1117; color: #c9d1d9;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .box { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
         padding: 40px; width: 300px; text-align: center; }
  h2 { color: #58a6ff; margin-bottom: 24px; }
  input { width: 100%; padding: 10px; margin: 8px 0; background: #0d1117;
          border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; box-sizing: border-box; }
  button { width: 100%; padding: 10px; background: #238636; color: white;
           border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin-top: 8px; }
  .error { color: #f85149; margin-top: 8px; }
</style></head>
<body>
<div class="box">
  <h2>Special K Forex</h2>
  <form method="POST">
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Login</button>
  </form>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
</div>
</body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head><title>Special K Forex Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 24px; }
  h1 { color: #58a6ff; margin-bottom: 4px; }
  .subtitle { color: #8b949e; font-size: 13px; margin-bottom: 24px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
           background: {% if paper %}#3d1f00{% else %}#0d4429{% endif %};
           color: {% if paper %}#e3b341{% else %}#56d364{% endif %};
           border: 1px solid {% if paper %}#e3b341{% else %}#56d364{% endif %}; }
  .cards { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 20px; flex: 1; min-width: 180px; }
  .card-label { color: #8b949e; font-size: 12px; margin-bottom: 6px; }
  .card-value { color: #c9d1d9; font-size: 22px; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; background: #161b22;
          border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
  th { background: #21262d; color: #8b949e; font-size: 12px; padding: 10px 14px;
       text-align: left; border-bottom: 1px solid #30363d; }
  td { padding: 10px 14px; border-bottom: 1px solid #21262d; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  .pos { color: #56d364; } .neg { color: #f85149; }
  .actions { margin-bottom: 24px; display: flex; gap: 10px; }
  button { padding: 8px 18px; border: none; border-radius: 4px; cursor: pointer;
           font-family: monospace; font-size: 13px; }
  .btn-dry { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
  .btn-live { background: #238636; color: white; }
  .btn-refresh { background: #1f6feb; color: white; }
  .msg { margin-top: 10px; font-size: 12px; color: #8b949e; }
  .logout { float: right; color: #8b949e; font-size: 12px; text-decoration: none; }
  .empty { color: #8b949e; padding: 20px; text-align: center; }
</style></head>
<body>
<a href="/logout" class="logout">logout</a>
<h1>Special K Forex</h1>
<p class="subtitle">{{ now }} &nbsp; <span class="badge">{% if paper %}PAPER{% else %}LIVE{% endif %}</span></p>

{% if acct.error %}
<p style="color:#f85149; margin-bottom:16px;">Alpaca error: {{ acct.error }}</p>
{% else %}
<div class="cards">
  <div class="card"><div class="card-label">Equity</div><div class="card-value">${{ "{:,.2f}".format(acct.equity) }}</div></div>
  <div class="card"><div class="card-label">Cash</div><div class="card-value">${{ "{:,.2f}".format(acct.cash) }}</div></div>
  <div class="card"><div class="card-label">Buying Power</div><div class="card-value">${{ "{:,.2f}".format(acct.buying_power) }}</div></div>
  <div class="card"><div class="card-label">Open Positions</div><div class="card-value">{{ positions|length }}</div></div>
</div>
{% endif %}

<div class="actions">
  <button class="btn-dry" onclick="runBot(true)">Dry Run Scan</button>
  <button class="btn-live" onclick="runBot(false)">Live Run</button>
  <button class="btn-refresh" onclick="location.reload()">Refresh</button>
</div>
<div id="msg" class="msg"></div>

<h3 style="margin-bottom:12px; color:#8b949e; font-size:13px;">OPEN POSITIONS</h3>
{% if positions %}
<table>
  <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>Value</th><th>P&L</th><th>P&L %</th></tr>
  {% for p in positions %}
  <tr>
    <td><b>{{ p.symbol }}</b></td>
    <td>{{ p.qty|int }}</td>
    <td>${{ "%.4f"|format(p.avg_entry_price) }}</td>
    <td>${{ "%.4f"|format(p.current_price) }}</td>
    <td>${{ "{:,.2f}".format(p.market_value) }}</td>
    <td class="{{ 'pos' if p.unrealized_pl >= 0 else 'neg' }}">${{ "{:,.2f}".format(p.unrealized_pl) }}</td>
    <td class="{{ 'pos' if p.unrealized_plpc >= 0 else 'neg' }}">{{ p.unrealized_plpc }}%</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<table><tr><td class="empty">No open positions</td></tr></table>
{% endif %}

<script>
function runBot(dryRun) {
  document.getElementById('msg').textContent = dryRun ? 'Dry run started — check logs...' : 'Live run started...';
  fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({dry_run: dryRun})
  }).then(r => r.json()).then(d => {
    document.getElementById('msg').textContent = 'Run started. Refresh in a few seconds to see results.';
  });
}
</script>
</body></html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
