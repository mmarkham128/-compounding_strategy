"""Fetch Blofin copy trading leaderboard from all four public rank categories."""

import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

RANK_URL = "https://blofin.com/uapi/v1/copy/trader/rank"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
CATEGORIES = [(2, "top_roi"), (3, "consistent"), (4, "copier_pnl"), (5, "new_talent")]


def fetch_leaderboard() -> list[dict]:
    all_traders: dict[int, dict] = {}
    for rank_type, label in CATEGORIES:
        try:
            r = requests.post(
                RANK_URL,
                json={"rank_type": rank_type, "limit": 15, "nick_name": ""},
                headers=HEADERS,
                timeout=20,
            )
            data = r.json()
            for key, lst in data.get("data", {}).items():
                for t in lst:
                    uid = t.get("uid")
                    if uid and uid not in all_traders:
                        all_traders[uid] = {
                            "name": t.get("nick_name", "")[:28],
                            "uid": uid,
                            "roi_pct": round(float(t.get("roi", 0)) * 100, 1),
                            "mdd_pct": round(float(t.get("mdd", 0)) * 100, 1),
                            "sharpe": round(float(t.get("sharpe_ratio", 0)), 2),
                            "aum_usdt": int(t.get("aum", 0)),
                            "followers": int(t.get("followers", 0)),
                            "category": label,
                        }
            print(f"  {label}: ok ({len(all_traders)} unique so far)")
        except Exception as exc:
            print(f"  {label}: failed - {exc}")
        time.sleep(0.4)
    return list(all_traders.values())


def main():
    print("Fetching Blofin copy trading leaderboard...")
    traders = fetch_leaderboard()
    print(f"\n{len(traders)} unique traders across all categories\n")

    header = f"{'Name':<28}  {'ROI%':>8}  {'MDD%':>6}  {'Sharpe':>7}  {'AUM':>10}  {'Followers':>9}  Category"
    print("Sorted by Sharpe ratio (top 25):")
    print(header)
    print("-" * 100)
    by_sharpe = sorted(traders, key=lambda x: x["sharpe"], reverse=True)
    for t in by_sharpe[:25]:
        line = (
            f"{t['name']:<28}  {t['roi_pct']:>8.1f}  {t['mdd_pct']:>6.1f}"
            f"  {t['sharpe']:>7.2f}  {t['aum_usdt']:>10,}  {t['followers']:>9}"
            f"  {t['category']}"
        )
        print(line)

    print("\nFiltered: Sharpe > 1, MDD < 30%, ROI > 0")
    print(header)
    print("-" * 100)
    qualified = [t for t in traders if t["sharpe"] > 1.0 and t["mdd_pct"] < 30.0 and t["roi_pct"] > 0]
    qualified.sort(key=lambda x: x["sharpe"], reverse=True)
    for t in qualified:
        line = (
            f"{t['name']:<28}  {t['roi_pct']:>8.1f}  {t['mdd_pct']:>6.1f}"
            f"  {t['sharpe']:>7.2f}  {t['aum_usdt']:>10,}  {t['followers']:>9}"
            f"  {t['category']}"
        )
        print(line)
    print(f"\n{len(qualified)} traders pass the filter.")


if __name__ == "__main__":
    main()
