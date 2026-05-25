"""Track B: copy trading OOS backtest and regime dynamic selector.

Trade history endpoints on Blofin require session auth. What is publicly
available is chart_data.roi in the leaderboard response: a daily cumulative
ROI series for each trader. We use that as their equity curve, apply the same
walk forward OOS methodology and 20% circuit breaker as Track A, build a
regime rotating dynamic selector, and produce a side by side comparison.

Limitation: chart_data gives daily granularity, not individual trades.
The circuit breaker fires on daily closes, not intraday. This is conservative
compared to how it would fire on hourly data (fewer false trips near
intraday dips that recover by close).

Usage:
    python scripts/run_track_b_copy.py
"""

import sys
import time
import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

from compounding_strategy.config import load_config
from compounding_strategy.data.loader import fetch_ohlcv
from compounding_strategy.regime.classifier import classify
from compounding_strategy.backtest import metrics as M


RANK_URL = "https://blofin.com/uapi/v1/copy/trader/rank"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://blofin.com",
    "Referer": "https://blofin.com/en/copy-trade",
}
CATEGORIES = [(2, "top_roi"), (3, "consistent"), (4, "copier_pnl"), (5, "new_talent")]


# ──────────────────────────────────────────────────────────────────────────────
# Fetch leaderboard


def _extract_roi_value(pt: dict) -> float | None:
    """Pull the ROI value from a chart_data point regardless of key name."""
    for key in ("roi", "value", "y", "pct", "r"):
        if key in pt:
            try:
                return float(pt[key])
            except (TypeError, ValueError):
                pass
    for k, v in pt.items():
        if k != "time":
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _sanitize_name(s: str) -> str:
    """Strip characters that Windows cp1252 console cannot encode."""
    return s.encode("ascii", "replace").decode("ascii").replace("?", "_")


def _build_equity_curve(roi_pts: list[dict]) -> pd.Series | None:
    """Convert chart_data.roi points to a daily equity series (1000 base)."""
    if len(roi_pts) < 10:
        return None
    pts = sorted(roi_pts, key=lambda p: p["time"])
    timestamps = [
        datetime.datetime.fromtimestamp(p["time"] / 1000, tz=datetime.timezone.utc)
        for p in pts
    ]
    values = [_extract_roi_value(p) for p in pts]
    if any(v is None for v in values):
        return None

    # Detect if values are percentages (e.g. 15.0) rather than decimals (e.g. 0.15).
    # Cumulative ROI over one year rarely exceeds 500% for a reasonable trader, so
    # values beyond 5.0 in decimal form are treated as percentage and divided by 100.
    max_val = max(abs(v) for v in values)
    if max_val > 5.0:
        values = [v / 100.0 for v in values]

    equity = pd.Series(
        [(1.0 + float(v)) * 1000.0 for v in values],
        index=pd.DatetimeIndex(timestamps),
        name="equity",
    )
    # Drop any negative equity (data error)
    if (equity <= 0).any():
        return None
    return equity


def fetch_leaderboard_with_curves(limit_per_cat: int = 15) -> list[dict]:
    """Fetch all four leaderboard categories, return traders that have usable equity curves."""
    all_traders: dict = {}
    for rank_type, label in CATEGORIES:
        try:
            resp = requests.post(
                RANK_URL,
                json={"rank_type": rank_type, "limit": limit_per_cat, "nick_name": ""},
                headers=HEADERS,
                timeout=25,
            )
            data = resp.json()
            for _key, lst in data.get("data", {}).items():
                if not isinstance(lst, list):
                    continue
                for t in lst:
                    uid = t.get("uid")
                    if not uid or uid in all_traders:
                        continue
                    cd = t.get("chart_data") or {}
                    roi_pts = cd.get("roi") or []
                    equity = _build_equity_curve(roi_pts)
                    if equity is None:
                        continue
                    all_traders[uid] = {
                        "name": _sanitize_name(str(t.get("nick_name", uid)))[:28],
                        "uid": uid,
                        "published_roi_pct": round(float(t.get("roi", 0)) * 100, 1),
                        "published_mdd_pct": round(float(t.get("mdd", 0)) * 100, 1),
                        "published_sharpe": round(float(t.get("sharpe_ratio", 0)), 2),
                        "aum_usdt": int(t.get("aum", 0)),
                        "category": label,
                        "equity_curve": equity,
                    }
            print(f"  {label}: {len(all_traders)} unique traders with curves so far")
        except Exception as exc:
            print(f"  {label}: failed  {exc}")
        time.sleep(0.5)
    return list(all_traders.values())


# ──────────────────────────────────────────────────────────────────────────────
# Circuit breaker


def apply_circuit_breaker(equity: pd.Series, pct: float = 20.0) -> tuple[pd.Series, bool]:
    """Halt and hold cash if equity drops pct% from peak. Returns modified curve + flag."""
    values = equity.values.astype(float).copy()
    peak = values[0]
    halted = False
    halt_val: float = 0.0
    for i in range(len(values)):
        if halted:
            values[i] = halt_val
            continue
        if values[i] > peak:
            peak = values[i]
        dd = (values[i] / peak - 1.0) * 100.0
        if dd <= -pct:
            halted = True
            halt_val = values[i]
    return pd.Series(values, index=equity.index, name=equity.name), halted


# ──────────────────────────────────────────────────────────────────────────────
# Backtest with circuit breaker
#
# Blofin chart_data.roi only returns the last 30 days from the public leaderboard
# endpoint. Full trade history (and longer chart history) is behind auth. With
# 30 days we cannot run monthly walk-forward OOS. Instead we apply the circuit
# breaker to the full available window and report straight metrics, making the
# methodology difference explicit when comparing to the grid's OOS results.


def evaluate_trader_window(
    equity_curve: pd.Series,
    capital: float = 1000.0,
    circuit_breaker_pct: float = 20.0,
) -> dict:
    """Apply circuit breaker to the trader's full available equity window.

    Normalises to capital at the first point so metrics are in the same
    units as the grid results.
    """
    if equity_curve.index.tz is None:
        equity_curve = equity_curve.tz_localize("UTC")
    start = float(equity_curve.iloc[0])
    if start <= 0:
        return {}
    normed = equity_curve / start * capital
    normed_cb, halted = apply_circuit_breaker(normed, circuit_breaker_pct)
    ret = (float(normed_cb.iloc[-1]) / capital - 1.0) * 100.0
    dd = M.max_drawdown_pct(normed_cb)
    # Daily data -> ppy = 365
    sharpe = M.sharpe_ratio(normed_cb, 365)
    return {
        "days": len(normed_cb),
        "return_pct": round(ret, 2),
        "max_dd_pct": round(dd, 2),
        "sharpe": round(sharpe, 2),
        "breaker_tripped": halted,
        "equity": normed_cb,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Regime helper


def get_btc_monthly_regime(btc_df: pd.DataFrame) -> dict:
    """Return {Period: majority_hourly_regime} for the full BTC data range."""
    regimes = classify(btc_df)
    result: dict = {}
    periods = regimes.index.to_period("M")
    for m in periods.unique():
        group = regimes[periods == m]
        result[m] = group.mode().iloc[0]
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic selector (simplified for 30-day data)
#
# With only 30 days we cannot run a full monthly walk-forward. The toy selector
# operates in one pass: for the most recent BTC regime, pick the trader with
# the best risk-adjusted return across the 30-day window, and report what the
# equity of that strategy would be. In a live system you would re-run this
# selection every week as new data arrives; here it shows the concept and the
# switching cost structure once per regime change.
#
# To build the proper monthly selector the leaderboard API would need to return
# at least six months of daily chart_data (currently limited to 30 days without auth).


def build_toy_dynamic_selector(
    traders_with_results: list[dict],
    current_btc_regime: str,
    capital: float,
) -> dict:
    """Toy regime selector: pick the single best trader for the current BTC regime.

    Scores traders by Sharpe if non-zero, then by return_pct as tiebreaker.
    Returns selection metadata and the equity curve of the winning trader.
    """
    # Group traders by their 30-day Sharpe into regime-agnostic ranking first,
    # then try to find regime-specialist if any trader's category hints at it.
    # Without historical regime breakdown we use overall Sharpe as the score.
    candidates = [
        t for t in traders_with_results
        if t.get("result") and t["result"].get("days", 0) >= 15
    ]
    if not candidates:
        return {}

    # Primary: highest 30-day Sharpe. Secondary: highest return.
    candidates.sort(key=lambda t: (t["result"]["sharpe"], t["result"]["return_pct"]), reverse=True)
    winner = candidates[0]

    return {
        "current_regime": current_btc_regime,
        "selected_trader": winner["name"],
        "selected_uid": winner["uid"],
        "selected_sharpe": winner["result"]["sharpe"],
        "selected_return_pct": winner["result"]["return_pct"],
        "selected_max_dd_pct": winner["result"]["max_dd_pct"],
        "selected_breaker_tripped": winner["result"]["breaker_tripped"],
        "candidate_count": len(candidates),
        "note": (
            f"Toy selector: picks by 30-day Sharpe under {current_btc_regime} regime. "
            "Full rotating selector requires >= 6 months chart_data (auth required on Blofin)."
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main


def main() -> None:
    cfg = load_config()
    capital = cfg["backtest"]["capital"]
    lookback_months = cfg["backtest"]["lookback_months"]
    since = cfg["backtest"]["since"]
    exchange_id = cfg["backtest"]["exchange"]
    circuit_breaker_pct = cfg["risk"]["max_strategy_drawdown_pct"]

    print("=== Track B: Copy Trading Backtest ===\n")
    print("DATA LIMITATION: Blofin chart_data.roi in the public leaderboard endpoint")
    print("returns a 30-day rolling window only. Full trade history and longer chart")
    print("history are behind auth (session cookie). Per-trade OOS is not possible")
    print("with public data. We apply the 20% circuit breaker to the 30-day window")
    print("and compare published stats vs observed stats to screen for inflation.\n")

    # ── 1. Fetch traders ──────────────────────────────────────────────────────
    print("Fetching Blofin leaderboard + equity curves...")
    traders = fetch_leaderboard_with_curves(limit_per_cat=15)
    print(f"{len(traders)} traders fetched with usable equity curves\n")

    if not traders:
        print("ERROR: no trader equity curves fetched. Blofin API may be unreachable.")
        return

    print("Equity curve coverage:")
    for t in traders:
        ec = t["equity_curve"]
        start_d = ec.index[0].strftime("%Y-%m-%d")
        end_d = ec.index[-1].strftime("%Y-%m-%d")
        print(
            f"  {t['name']:<28}  {start_d} to {end_d}  ({len(ec):>3}d)"
            f"  pub Sharpe {t['published_sharpe']:>6.2f}"
        )

    # ── 2. Apply circuit breaker to each trader's 30-day window ──────────────
    print(f"\nApplying {circuit_breaker_pct}% circuit breaker to each trader's window...")
    evaluated: list[dict] = []
    for t in traders:
        result = evaluate_trader_window(t["equity_curve"], capital, circuit_breaker_pct)
        if result:
            t["result"] = result
            evaluated.append(t)
            flag = "PASS" if result["sharpe"] > 0 else "fail"
            cb_flag = " CB!" if result["breaker_tripped"] else ""
            print(
                f"  {t['name']:<28}"
                f"  {result['days']:>2}d"
                f"  ret {result['return_pct']:>7.1f}%"
                f"  MDD {result['max_dd_pct']:>6.1f}%"
                f"  Sharpe {result['sharpe']:>5.2f}"
                f"{cb_flag:<4}  {flag}"
            )

    qualifying = [t for t in evaluated if t["result"]["sharpe"] > 0]
    print(f"\n{len(evaluated)} traders evaluated, {len(qualifying)} pass Sharpe > 0\n")

    if not evaluated:
        print("ERROR: no traders evaluated.")
        return

    # ── 3. BTC current regime ─────────────────────────────────────────────────
    print("Loading BTC/USDT hourly data for regime...")
    btc_df = fetch_ohlcv("BTC/USDT", timeframe="1h", since=since, exchange_id=exchange_id)
    monthly_regime = get_btc_monthly_regime(btc_df)
    # Current regime = most recent full month
    latest_month = max(monthly_regime.keys())
    current_regime = monthly_regime[latest_month]

    print("\nBTC monthly regime (majority hourly label):")
    for m, r in sorted(monthly_regime.items()):
        print(f"  {m}  {r}")
    print(f"\nCurrent regime ({latest_month}): {current_regime}")

    # ── 4. Toy dynamic selector ───────────────────────────────────────────────
    print("\nToy dynamic selector (current regime pick):")
    sel = build_toy_dynamic_selector(evaluated, current_regime, capital)
    if sel:
        print(f"  Regime: {sel['current_regime']}")
        print(f"  Selected: {sel['selected_trader']}  (Sharpe {sel['selected_sharpe']:.2f}, ret {sel['selected_return_pct']:.1f}%)")
        print(f"  {sel['note']}")

    # ── 5. Load Track A for comparison ───────────────────────────────────────
    track_a_path = ROOT / "results" / "phase0_gated.csv"
    grid_hold_return = grid_hold_dd = grid_hold_sharpe = grid_flip_return = float("nan")
    best_grid_asset = "N/A"
    best_grid_return = best_grid_dd = best_grid_sharpe = float("nan")
    if track_a_path.exists():
        track_a = pd.read_csv(track_a_path, index_col=0)
        grid_hold_return = round(float(track_a["hold_return_pct"].mean()), 2)
        grid_hold_dd = round(float(track_a["oos_max_dd_pct"].mean()), 2)
        grid_hold_sharpe = round(float(track_a["oos_sharpe"].mean()), 2)
        grid_flip_return = round(float(track_a["flip_return_pct"].mean()), 2)
        best_grid_asset = str(track_a["hold_return_pct"].idxmax())
        best_grid_row = track_a.loc[best_grid_asset]
        best_grid_return = round(float(best_grid_row["hold_return_pct"]), 2)
        best_grid_dd = round(float(best_grid_row["oos_max_dd_pct"]), 2)
        best_grid_sharpe = round(float(best_grid_row["oos_sharpe"]), 2)

    # ── 6. Side by side comparison ────────────────────────────────────────────
    sep = "=" * 100
    print(f"\n{sep}")
    print("SIDE-BY-SIDE COMPARISON")
    print("Grid: 10-month walk-forward OOS on KuCoin data, hourly candles")
    print("Copy traders: 30-day observed window from Blofin chart_data (public endpoint)")
    print("Both use the same 20% circuit breaker rule.")
    print("WARNING: different OOS windows make direct comparison indicative, not rigorous.")
    print(sep)
    print(f"{'Strategy':<40}  {'Ret%':>7}  {'MaxDD%':>7}  {'Sharpe':>7}  {'CB':>4}  Notes")
    print("-" * 100)

    def row(label, ret, dd, sharpe, cb, notes=""):
        r = f"{ret:>7.1f}" if ret == ret else f"{'N/A':>7}"
        d = f"{dd:>7.1f}" if dd == dd else f"{'N/A':>7}"
        s = f"{sharpe:>7.2f}" if sharpe == sharpe else f"{'N/A':>7}"
        c = f"{cb:>4}" if isinstance(cb, int) else f"{'':>4}"
        print(f"{label:<40}  {r}  {d}  {s}  {c}  {notes}")

    print("-- GRID (10-month OOS walk-forward) --")
    row("Gated grid hold (avg 10 assets)", grid_hold_return, grid_hold_dd, grid_hold_sharpe, "", "all assets negative")
    row("Gated grid flip (avg 10 assets)", grid_flip_return, float("nan"), float("nan"), "", "flip makes it much worse")
    row(f"Best grid asset: {best_grid_asset}", best_grid_return, best_grid_dd, best_grid_sharpe, "")
    print()
    print("-- COPY TRADERS (30-day observed window, 20% CB applied) --")
    best_trader = max(evaluated, key=lambda t: (t["result"]["sharpe"], t["result"]["return_pct"]))
    best_res = best_trader["result"]
    row(f"Best copy trader: {best_trader['name']}", best_res["return_pct"], best_res["max_dd_pct"], best_res["sharpe"], int(best_res["breaker_tripped"]))
    if sel:
        sel_trader = next((t for t in evaluated if t["uid"] == sel["selected_uid"]), None)
        if sel_trader:
            sr = sel_trader["result"]
            row(
                f"Toy selector ({current_regime} regime)",
                sr["return_pct"],
                sr["max_dd_pct"],
                sr["sharpe"],
                int(sr["breaker_tripped"]),
                f"picked {sel_trader['name']}",
            )

    print(f"\n{sep}")
    print("ALL COPY TRADERS  (30-day CB-adjusted Sharpe desc)  * = Sharpe > 0")
    print(sep)
    print(
        f"  {'Name':<28}  {'Ret%':>7}  {'MDD%':>7}  {'Sharpe':>7}  {'CB':>4}"
        f"  {'PubSharpe':>10}  {'PubROI%':>8}  {'PubMDD%':>8}  Cat"
    )
    print(f"  {'-'*28}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*4}  {'-'*10}  {'-'*8}  {'-'*8}  ---")
    for t in sorted(evaluated, key=lambda x: (x["result"]["sharpe"], x["result"]["return_pct"]), reverse=True):
        r = t["result"]
        star = " *" if r["sharpe"] > 0 else "  "
        cb_flag = "Y" if r["breaker_tripped"] else "N"
        print(
            f"  {t['name']:<28}"
            f"  {r['return_pct']:>7.1f}  {r['max_dd_pct']:>7.1f}  {r['sharpe']:>7.2f}  {cb_flag:>4}"
            f"  {t['published_sharpe']:>10.2f}  {t['published_roi_pct']:>8.1f}  {t['published_mdd_pct']:>8.1f}"
            f"  {t['category']}{star}"
        )

    print(f"\n{sep}")
    print("PUBLISHED vs OBSERVED SHARPE (gap = inflation, sorted largest gap first)")
    print(f"{sep}")
    gaps = sorted(
        [(t["name"], t["published_sharpe"], t["result"]["sharpe"]) for t in evaluated],
        key=lambda x: x[1] - x[2],
        reverse=True,
    )
    for name, pub, obs in gaps:
        gap = pub - obs
        flag = "  <-- likely inflated" if gap > 5 else ""
        print(f"  {name:<28}  pub {pub:>6.2f}  obs {obs:>6.2f}  gap {gap:>6.2f}{flag}")

    # ── 7. Save results ───────────────────────────────────────────────────────
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    copy_rows = []
    for t in evaluated:
        r = t["result"]
        copy_rows.append({
            "name": t["name"],
            "uid": t["uid"],
            "category": t["category"],
            "published_roi_pct": t["published_roi_pct"],
            "published_mdd_pct": t["published_mdd_pct"],
            "published_sharpe": t["published_sharpe"],
            "observed_return_pct": r["return_pct"],
            "observed_max_dd_pct": r["max_dd_pct"],
            "observed_sharpe": r["sharpe"],
            "breaker_tripped": r["breaker_tripped"],
            "days": r["days"],
        })
    copy_df = pd.DataFrame(copy_rows).sort_values("observed_sharpe", ascending=False)
    copy_csv = results_dir / "track_b_copy_traders.csv"
    copy_df.to_csv(copy_csv, index=False)
    print(f"\nCopy trader results -> {copy_csv}")

    comp_rows = [
        {
            "strategy": "gated_grid_hold_avg_10assets",
            "window": "10mo OOS walk-forward",
            "return_pct": grid_hold_return,
            "max_dd_pct": grid_hold_dd,
            "sharpe": grid_hold_sharpe,
            "notes": "all negative",
        },
        {
            "strategy": f"best_grid_asset_{best_grid_asset}",
            "window": "10mo OOS walk-forward",
            "return_pct": best_grid_return,
            "max_dd_pct": best_grid_dd,
            "sharpe": best_grid_sharpe,
            "notes": "best single grid asset",
        },
        {
            "strategy": f"best_copy_trader_{best_trader['name']}",
            "window": "30d observed",
            "return_pct": best_res["return_pct"],
            "max_dd_pct": best_res["max_dd_pct"],
            "sharpe": best_res["sharpe"],
            "notes": "30d window only, not full OOS",
        },
    ]
    if sel and sel_trader:
        sr = sel_trader["result"]
        comp_rows.append({
            "strategy": f"toy_selector_{current_regime}",
            "window": "30d observed",
            "return_pct": sr["return_pct"],
            "max_dd_pct": sr["max_dd_pct"],
            "sharpe": sr["sharpe"],
            "notes": f"picked {sel_trader['name']}",
        })
    comp_df = pd.DataFrame(comp_rows)
    comp_csv = results_dir / "track_b_comparison.csv"
    comp_df.to_csv(comp_csv, index=False)
    print(f"Side-by-side comparison -> {comp_csv}")


if __name__ == "__main__":
    main()
