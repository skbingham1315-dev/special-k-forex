# Special K Forex

A forex ETF swing trader built on the same engine as Special K Trading v2.
Uses Alpaca (same API keys) to trade currency ETFs: FXE, FXB, FXY, FXC, FXA, UUP.

## What it does
- Same trend-pullback strategy as Special K equity bot
- Trades forex ETFs instead of stocks (works with your existing Alpaca keys)
- Deploys buying power until the configured minimum is reached, then pauses
- Resumes automatically when positions close and cash recovers
- Server-side bracket orders handle stops and take-profits even when the script isn't running

## Currency ETF reference
| ETF | Tracks |
|-----|--------|
| FXE | Euro (EUR/USD) |
| FXB | British Pound (GBP/USD) |
| FXY | Japanese Yen (USD/JPY inverse) |
| FXC | Canadian Dollar (USD/CAD inverse) |
| FXA | Australian Dollar (AUD/USD) |
| UUP | US Dollar Index bullish |

## Setup

```bash
cd /Users/mymac/Downloads/special_k_forex
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
open .env   # paste your Alpaca keys
```

## Run

Dry run (no orders placed):
```bash
python -m special_k_forex.cli --dry-run
```

Paper trading live:
```bash
python -m special_k_forex.cli
```

## Buying power pause
Set `MIN_BUYING_POWER` in `.env` (default $500).
When available buying power drops below that, the bot skips new entries
and logs "Waiting for buying power to recover".
It will resume the next time it runs and buying power is above the threshold.

## Cron (run once per weekday near market open)
```bash
crontab -e
```
```
35 6 * * 1-5 cd /Users/mymac/Downloads/special_k_forex && source venv/bin/activate && python -m special_k_forex.cli >> trading.log 2>&1
```
Arizona is UTC-7, so 6:35 AM local ≈ 13:35 UTC. Adjust as needed.
