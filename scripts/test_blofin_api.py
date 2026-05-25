"""
Blofin copy trading API research script.
Tests discovered endpoints for leaderboard and trader data.
"""
import urllib.request
import ssl
import json
import sys

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE = "https://blofin.com"
OPENAPI_BASE = "https://openapi.blofin.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://blofin.com",
    "Referer": "https://blofin.com/en/copy-trade",
}

SAMPLE_UID = 52128006135  # Warriors trader


def post(url, body):
    payload = json.dumps(body).encode()
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def get(url):
    req = urllib.request.Request(url, headers={k: v for k, v in HEADERS.items() if k != "Content-Type"})
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# 1. Public instruments list
print("=== 1. Public instruments (openapi) ===")
d = get(f"{OPENAPI_BASE}/api/v1/copytrading/instruments")
insts = d.get("instIdList", [])
print(f"  {len(insts)} copy trading instruments available")
print(f"  sample: {insts[:5]}")

# 2. Leaderboard (rank_type=2 = top ROI)
print("\n=== 2. Leaderboard rank_type=2 ===")
d = post(f"{BASE}/uapi/v1/copy/trader/rank", {"rank_type": 2, "limit": 15, "nick_name": ""})
top_roi = d.get("data", {}).get("top_roi_list", [])
print(f"  {len(top_roi)} traders returned")
if top_roi:
    t = top_roi[0]
    print(f"  Fields: {[k for k in t.keys() if k != 'chart_data']}")
    print(f"  Top trader: uid={t['uid']} nick={t['nick_name']}")
    print(f"    roi={t['roi']}, pnl={t['pnl']}, mdd={t['mdd']}")
    print(f"    sharpe_ratio={t['sharpe_ratio']}, aum={t['aum']}, followers={t['followers']}")
    cd = t.get("chart_data", {})
    if cd and "roi" in cd:
        roi_pts = cd["roi"]
        import datetime
        oldest = datetime.datetime.fromtimestamp(roi_pts[-1]["time"] / 1000).strftime("%Y-%m-%d")
        newest = datetime.datetime.fromtimestamp(roi_pts[0]["time"] / 1000).strftime("%Y-%m-%d")
        print(f"    chart_data.roi: {len(roi_pts)} daily points, {oldest} to {newest}")

# 3. Rank type categories
print("\n=== 3. Rank type categories ===")
rank_type_desc = {2: "top_roi", 3: "top_predunt (consistent)", 4: "highest_copier_pnl", 5: "top_new_talent"}
for rt, desc in rank_type_desc.items():
    d = post(f"{BASE}/uapi/v1/copy/trader/rank", {"rank_type": rt, "limit": 5, "nick_name": ""})
    data = d.get("data", {})
    for key, val in data.items():
        if val:
            print(f"  rank_type={rt} ({desc}): key={key}, {len(val)} traders")

# 4. Trader search by name
print("\n=== 4. Name search ===")
d = post(f"{BASE}/uapi/v1/copy/trader/rank", {"rank_type": 2, "limit": 5, "nick_name": "Warriors"})
found = d.get("data", {}).get("top_roi_list", [])
print(f"  Search 'Warriors': {len(found)} results")

# 5. Trader self-introduction (public without auth)
print("\n=== 5. Trader self-introduction/query ===")
d = post(f"{BASE}/uapi/v1/copy_trading/user/self_introduction/query", {"uid": SAMPLE_UID})
if d.get("code") == 200:
    info = d.get("data", {})
    print(f"  SUCCESS - fields: {list(info.keys())}")
    print(f"  hidden: {info.get('hidden')}")
    print(f"  symbols count: {len(info.get('symbols', []))}")
    print(f"  sample symbols: {info.get('symbols', [])[:5]}")
else:
    print(f"  FAIL: code={d.get('code')} msg={d.get('msg')}")

# 6. Auth-required endpoints check
print("\n=== 6. Auth-required endpoints (expected 400 = session cookie needed) ===")
auth_tests = [
    (f"{BASE}/uapi/v1/copy_trading/order/history", {"page": 1, "page_size": 20}),
    (f"{BASE}/uapi/v1/copy_trading/order/all_history", {"page": 1, "page_size": 20}),
    (f"{BASE}/uapi/v1/copy_trading/user/info", {"uid": SAMPLE_UID}),
    (f"{BASE}/uapi/v1/copy/trader/stat/performance", {"uid": SAMPLE_UID}),
    (f"{BASE}/uapi/v1/copy/trader/stat/symbol_performance", {"uid": SAMPLE_UID}),
]
for url, body in auth_tests:
    d = post(url, body)
    ep = url.replace(BASE, "")
    code = d.get("code")
    msg = d.get("msg", "")
    status = "AUTH_REQUIRED" if code == 400 else f"code={code}"
    print(f"  {ep}: {status} ({msg})")

# 7. Rate limit on public rank endpoint (measure response times)
import time
print("\n=== 7. Rate limit test on /uapi/v1/copy/trader/rank ===")
times = []
for i in range(5):
    start = time.time()
    post(f"{BASE}/uapi/v1/copy/trader/rank", {"rank_type": 2, "limit": 3, "nick_name": ""})
    elapsed = time.time() - start
    times.append(elapsed)
print(f"  5 requests: avg={sum(times)/len(times):.3f}s min={min(times):.3f}s max={max(times):.3f}s")
print(f"  No rate limit errors encountered")

print("\n=== DONE ===")
