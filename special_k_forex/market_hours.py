"""
Global market hours tracker.
Returns open/closed status for all major world markets.
"""
from __future__ import annotations
from datetime import datetime, time
import pytz

MARKETS = [
    {"id": "sydney",    "name": "Sydney",    "tz": "Australia/Sydney",    "open": time(10, 0),  "close": time(16, 0),  "flag": "🇦🇺"},
    {"id": "tokyo",     "name": "Tokyo",     "tz": "Asia/Tokyo",          "open": time(9,  0),  "close": time(15, 30), "flag": "🇯🇵"},
    {"id": "hong_kong", "name": "Hong Kong", "tz": "Asia/Hong_Kong",      "open": time(9, 30),  "close": time(16, 0),  "flag": "🇭🇰"},
    {"id": "mumbai",    "name": "Mumbai",    "tz": "Asia/Kolkata",        "open": time(9, 15),  "close": time(15, 30), "flag": "🇮🇳"},
    {"id": "frankfurt", "name": "Frankfurt", "tz": "Europe/Berlin",       "open": time(9,  0),  "close": time(17, 30), "flag": "🇩🇪"},
    {"id": "london",    "name": "London",    "tz": "Europe/London",       "open": time(8,  0),  "close": time(16, 30), "flag": "🇬🇧"},
    {"id": "nyc_pre",   "name": "US Pre",    "tz": "America/New_York",    "open": time(4,  0),  "close": time(9, 30),  "flag": "🇺🇸"},
    {"id": "nyc",       "name": "US Market", "tz": "America/New_York",    "open": time(9, 30),  "close": time(16, 0),  "flag": "🇺🇸"},
    {"id": "nyc_after", "name": "US After",  "tz": "America/New_York",    "open": time(16, 0),  "close": time(20, 0),  "flag": "🇺🇸"},
    {"id": "crypto",    "name": "Crypto",    "tz": "UTC",                 "open": time(0,  0),  "close": time(23, 59), "flag": "₿"},
]

def get_market_status() -> list[dict]:
    """Return list of all markets with their current open/closed status and local time."""
    utc_now = datetime.now(pytz.utc)
    result = []
    for m in MARKETS:
        tz = pytz.timezone(m["tz"])
        local_now = utc_now.astimezone(tz)
        local_time = local_now.time()
        is_weekday = local_now.weekday() < 5
        if m["id"] == "crypto":
            is_open = True
        else:
            is_open = is_weekday and m["open"] <= local_time <= m["close"]
        result.append({
            "id":         m["id"],
            "name":       m["name"],
            "flag":       m["flag"],
            "open":       is_open,
            "local_time": local_now.strftime("%H:%M"),
            "local_day":  local_now.strftime("%a"),
        })
    return result

def is_us_regular() -> bool:
    now = datetime.now(pytz.timezone("America/New_York"))
    t = now.time()
    return now.weekday() < 5 and time(9, 30) <= t <= time(16, 0)

def is_us_extended() -> bool:
    now = datetime.now(pytz.timezone("America/New_York"))
    t = now.time()
    return now.weekday() < 5 and (time(4, 0) <= t < time(9, 30) or time(16, 0) < t <= time(20, 0))

def is_any_market_open() -> bool:
    return is_us_regular() or is_us_extended()
