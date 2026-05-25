"""Blofin copy trading API feasibility check.

Determines whether an authenticated read-only API key returns real per-trade
history for arbitrary leaderboard traders and how far back the history goes.

Run this script twice:
  1. Without a key (no .env or BLOFIN_API_KEY set) to document what public
     endpoints return and what error structure auth-required endpoints produce.
  2. With a read-only key set in .env or as environment variables to see what
     additional data is unlocked and measure history depth.

The script never writes, transfers, or trades. It only reads.

Setup for authenticated run:
  Copy .env.example to .env and fill in:
    BLOFIN_API_KEY=your_read_only_key
    BLOFIN_API_SECRET=your_secret
    BLOFIN_PASSPHRASE=your_passphrase

The passphrase is required by Blofin for all signed requests.

Usage:
    python scripts/check_blofin_api_auth.py
"""

import sys
import os
import json
import time
import hmac
import hashlib
import base64
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

# Load .env if present (python-dotenv optional)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

BASE = "https://blofin.com"
OPENAPI_BASE = "https://openapi.blofin.com"
HEADERS_PUBLIC = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://blofin.com",
    "Referer": "https://blofin.com/en/copy-trade",
}

API_KEY = os.environ.get("BLOFIN_API_KEY", "")
API_SECRET = os.environ.get("BLOFIN_API_SECRET", "")
PASSPHRASE = os.environ.get("BLOFIN_PASSPHRASE", "")

AUTHENTICATED = bool(API_KEY and API_SECRET and PASSPHRASE)


# -- Blofin REST auth (HMAC-SHA256) --------------------------------------------

def _sign(method: str, path: str, body: str = "") -> dict:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    nonce = str(int(time.time() * 1000))
    prehash = f"{ts}{nonce}{method.upper()}{path}{body}"
    sig = base64.b64encode(
        hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-NONCE": nonce,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }


def _post(url: str, body: dict, auth: bool = False) -> dict:
    body_str = json.dumps(body)
    headers = _sign("POST", url.replace(BASE, "").replace(OPENAPI_BASE, ""), body_str) if auth else HEADERS_PUBLIC
    try:
        r = requests.post(url, data=body_str, headers=headers, timeout=20)
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


def _get(url: str, auth: bool = False) -> dict:
    path = url.replace(BASE, "").replace(OPENAPI_BASE, "")
    headers = _sign("GET", path) if auth else {k: v for k, v in HEADERS_PUBLIC.items() if k != "Content-Type"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}


# -- Helpers ------------------------------------------------------------------─

def status(d: dict) -> str:
    code = d.get("code")
    msg = d.get("msg", d.get("message", ""))
    if "error" in d:
        return f"NETWORK_ERR: {d['error']}"
    if code == 200 or code == 0:
        return "OK"
    if code == 400:
        return f"AUTH_REQUIRED (code=400, msg={msg!r})"
    if code == 401:
        return f"UNAUTHORIZED (code=401, msg={msg!r})"
    if code == 403:
        return f"FORBIDDEN (code=403, msg={msg!r})"
    return f"code={code} msg={msg!r}"


def fetch_sample_uids(n: int = 5) -> list[int]:
    d = _post(f"{BASE}/uapi/v1/copy/trader/rank", {"rank_type": 2, "limit": n, "nick_name": ""})
    uids = []
    for key, lst in d.get("data", {}).items():
        if isinstance(lst, list):
            uids.extend(t.get("uid") for t in lst if t.get("uid"))
    return list(set(uids))[:n]


# -- Main ----------------------------------------------------------------------

def main() -> None:
    print("=== Blofin Copy Trading API Feasibility Check ===\n")
    print(f"Auth mode: {'AUTHENTICATED (key present)' if AUTHENTICATED else 'PUBLIC (no key)'}")
    if not AUTHENTICATED:
        print("  Set BLOFIN_API_KEY, BLOFIN_API_SECRET, BLOFIN_PASSPHRASE in .env to test auth endpoints.\n")
    else:
        print(f"  Key: {API_KEY[:8]}...  Passphrase: {'set' if PASSPHRASE else 'MISSING'}\n")

    # -- 1. Public instruments available for copy trading ----------------------
    print("-- 1. Copy trading instruments (public) --")
    d = _get(f"{OPENAPI_BASE}/api/v1/copytrading/instruments")
    insts = d.get("instIdList", [])
    print(f"  {len(insts)} instruments available for copy trading")
    print(f"  Sample: {insts[:8]}")

    # -- 2. Sample UIDs from leaderboard --------------------------------------
    print("\n-- 2. Sample trader UIDs from leaderboard --")
    sample_uids = fetch_sample_uids(5)
    print(f"  Fetched {len(sample_uids)} UIDs: {sample_uids}")

    if not sample_uids:
        print("  WARNING: could not fetch UIDs, leaderboard may be down")
        sample_uids = [52128006135]  # Warriors (known from test session)

    uid = sample_uids[0]
    print(f"  Using UID {uid} for auth endpoint tests\n")

    # -- 3. Auth-required endpoints: public attempt (expected fail) ------------
    print("-- 3. Auth-required endpoints (public attempt, expected failure) --")

    auth_endpoints_post = [
        (f"{BASE}/uapi/v1/copy_trading/order/history",
         {"page": 1, "page_size": 20},
         "trader order history (own trades)"),
        (f"{BASE}/uapi/v1/copy_trading/order/all_history",
         {"page": 1, "page_size": 20},
         "all order history (followers' trades)"),
        (f"{BASE}/uapi/v1/copy_trading/user/info",
         {"uid": uid},
         "trader user info"),
        (f"{BASE}/uapi/v1/copy/trader/stat/performance",
         {"uid": uid},
         "trader performance stats (long history)"),
        (f"{BASE}/uapi/v1/copy/trader/stat/symbol_performance",
         {"uid": uid},
         "trader per-symbol performance"),
        (f"{BASE}/uapi/v1/copy_trading/user/self_introduction/query",
         {"uid": uid},
         "trader self introduction (public?)"),
    ]

    for url, body, label in auth_endpoints_post:
        d = _post(url, body, auth=False)
        print(f"  PUBLIC  {label}")
        print(f"          {url.replace(BASE, '')}")
        print(f"          -> {status(d)}")
        time.sleep(0.3)

    # -- 4. Authenticated attempts --------------------------------------------─
    if AUTHENTICATED:
        print("\n-- 4. Auth-required endpoints (signed request) --")

        for url, body, label in auth_endpoints_post:
            d = _post(url, body, auth=True)
            st = status(d)
            print(f"\n  AUTH  {label}")
            print(f"        {url.replace(BASE, '')}")
            print(f"        -> {st}")
            if st == "OK":
                data = d.get("data", {})
                if isinstance(data, dict):
                    print(f"        keys: {list(data.keys())}")
                elif isinstance(data, list) and data:
                    print(f"        list of {len(data)} records")
                    print(f"        first record keys: {list(data[0].keys()) if data else 'empty'}")
                    if label == "trader order history (own trades)" and data:
                        rec = data[0]
                        print(f"        sample fields: {json.dumps(rec, default=str)[:300]}")
                    # Estimate history depth
                    if label in ("trader order history (own trades)", "all order history (followers' trades)"):
                        times = [r.get("create_time", r.get("createTime", r.get("ts"))) for r in data if r]
                        times = [t for t in times if t]
                        if times:
                            oldest = min(int(t) for t in times if str(t).isdigit())
                            newest = max(int(t) for t in times if str(t).isdigit())
                            unit = "ms" if oldest > 1e12 else "s"
                            if unit == "ms":
                                oldest_dt = datetime.datetime.fromtimestamp(oldest / 1000)
                                newest_dt = datetime.datetime.fromtimestamp(newest / 1000)
                            else:
                                oldest_dt = datetime.datetime.fromtimestamp(oldest)
                                newest_dt = datetime.datetime.fromtimestamp(newest)
                            print(f"        time range: {oldest_dt.date()} to {newest_dt.date()}")
                            print(f"        NOTE: this is page 1 only. Paginate to measure full depth.")
            time.sleep(0.4)

        # Specific test: trader stat performance endpoint, try to get full chart history
        print("\n-- 5. Trader performance stats (full history check) --")
        perf_url = f"{BASE}/uapi/v1/copy/trader/stat/performance"
        for test_uid in sample_uids[:3]:
            d = _post(perf_url, {"uid": test_uid}, auth=True)
            st = status(d)
            print(f"\n  uid={test_uid} -> {st}")
            if st == "OK":
                data = d.get("data", {})
                print(f"  keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                if isinstance(data, dict):
                    # Look for any time-series fields that indicate history depth
                    for k, v in data.items():
                        if isinstance(v, list) and v:
                            first = v[0]
                            print(f"  field '{k}': list of {len(v)}, first item type {type(first).__name__}")
                            if isinstance(first, dict) and ("time" in first or "ts" in first or "date" in first):
                                times = [
                                    first.get("time", first.get("ts", first.get("date")))
                                ]
                                print(f"  '{k}' appears to be a time series, first point: {first}")
                        elif isinstance(v, (int, float, str)):
                            print(f"  {k}: {v}")
            time.sleep(0.4)

        # Check if there is a pagination parameter to get full trade history
        print("\n-- 6. Paginate trade history to measure full depth --")
        history_url = f"{BASE}/uapi/v1/copy_trading/order/history"
        all_records = []
        page = 1
        while page <= 5:  # cap at 5 pages to avoid hammering the API
            d = _post(history_url, {"page": page, "page_size": 50}, auth=True)
            if status(d) != "OK":
                print(f"  page {page}: {status(d)}")
                break
            data = d.get("data", {})
            records = data if isinstance(data, list) else data.get("list", data.get("orders", []))
            if not records:
                print(f"  page {page}: empty, stopping")
                break
            all_records.extend(records)
            print(f"  page {page}: {len(records)} records (total so far: {len(all_records)})")
            if len(records) < 50:
                print(f"  last page reached at page {page}")
                break
            page += 1
            time.sleep(0.3)

        if all_records:
            times = []
            for r in all_records:
                for tk in ("create_time", "createTime", "ts", "time", "cTime"):
                    v = r.get(tk)
                    if v:
                        try:
                            times.append(int(v))
                        except (TypeError, ValueError):
                            pass
                        break
            if times:
                unit = "ms" if max(times) > 1e12 else "s"
                div = 1000 if unit == "ms" else 1
                oldest = datetime.datetime.fromtimestamp(min(times) / div)
                newest = datetime.datetime.fromtimestamp(max(times) / div)
                print(f"\n  History range ({len(all_records)} records): {oldest.date()} to {newest.date()}")
                print(f"  Months of history: ~{(newest - oldest).days / 30:.1f}")
                print(f"  Sample record keys: {list(all_records[0].keys())}")
                if len(all_records[0].keys()) < 20:
                    print(f"  Sample record: {json.dumps(all_records[0], default=str)[:500]}")

    else:
        print("\n-- 4-6. Skipped (no API key). --")
        print("  To run authenticated checks:")
        print("  1. Create a read-only API key on Blofin (no Trade/Transfer/Withdraw permissions)")
        print("  2. Copy .env.example to .env and fill BLOFIN_API_KEY / _SECRET / _PASSPHRASE")
        print("  3. Re-run this script")

    # -- Summary --------------------------------------------------------------─
    print("\n-- Summary --")
    print("Public data:")
    print("  - Leaderboard: uid, name, ROI, MDD, Sharpe, AUM, chart_data.roi (30d)")
    print("  - chart_data.roi: 30-day daily cumulative ROI only, not full history")
    print("  - Copy trading instruments list (via openapi)")
    print("  - Self introduction fields (appears partially public)")
    print()
    print("Auth-required (expected, from prior testing):")
    print("  - /uapi/v1/copy_trading/order/history     own trade history")
    print("  - /uapi/v1/copy_trading/order/all_history  all trades (own + followers)")
    print("  - /uapi/v1/copy/trader/stat/performance    full performance chart")
    print("  - /uapi/v1/copy/trader/stat/symbol_performance  per-symbol breakdown")
    print()
    print("Open question: does a read-only key return ANY trader's history (not just")
    print("the key holder's), or only the history of the account that owns the key?")
    print("Copy trading platforms typically allow authenticated followers to query")
    print("the traders they follow. Whether you can query ARBITRARY leaderboard")
    print("traders without following them first is the key unknown.")
    print()
    print("For a proper 10-month OOS backtest of copy traders you need:")
    print("  - Either per-trade history going back to at least 2025-05")
    print("  - Or daily equity curve data going back at least 6 months")
    print("  The 30-day public chart_data is insufficient for this.")


if __name__ == "__main__":
    main()
