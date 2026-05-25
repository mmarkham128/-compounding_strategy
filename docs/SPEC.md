# Compounding Strategy Specification

The complete plan: what we are building, the decisions locked so far, the phase gates, and the open items we close deliberately as we go.

## 1. Objective

A trading system that survives every market regime, earns in the conditions it is designed for, sits patiently in the conditions it is not, and compounds a fractional, risk sized stake over months. Sustainability over headline return.

Realistic target if the edge proves out: 1 to 3 percent net per month in favorable conditions, with flat and occasionally negative months built into the average. Compounded, that is roughly 13 to 43 percent annually, with the realistic center in the lower half. Nothing is guaranteed.

## 2. Core design

A spot grid core, gated by a regime classifier, wrapped in an always on risk overlay, with realized profit reinvested under fractional position sizing.

* **Regime classifier.** A compact, robust indicator set: ADX for trend strength, fast versus slow EMA for direction, ATR as a fraction of price for volatility. Output is one label per candle: ranging, trend up, trend down, chop.
* **Strategy selector.** Ranging runs the grid. Trend up holds or trend follows. Trend down goes flat or accumulates. Chop tightens the grid band.
* **Risk overlay.** Per strategy drawdown circuit breaker, account level kill switch, equity based fractional sizing, leverage cap.
* **Compounding.** Reinvest realized profit, sized as a fraction of current equity so the curve grows on the way up and exposure shrinks automatically in a drawdown.

## 3. Decisions locked

* Standalone repository on the personal GitHub account, separate from Nexgent and Polymythic. Kept apart from Nexgent because that foundation is not clean enough to build on.
* Spot grid is the core engine. No leverage until the edge is proven.
* Leverage is decoupled from any dollar threshold. Once Phase 1 shadow mode proves the edge on demo, leverage turns on in Phase 2 paper trading, always reversible to spot.
* Working leverage cap is 10 to 15, with the final number set by per asset drawdown data from the backtest.
* Asset scope starts with the top ten by market cap, SOL as the baseline. Narrow to the three to five winners after Phase 0. Edge case coins wait until Phase 4.
* Backtest window is one year, enough to span multiple regimes without heavy compute.
* Data source for backtesting is Binance through ccxt. Execution happens on Blofin. Price history is effectively identical across venues, so the two do not need to match.

## 4. Backtest engine note

Phase 0 uses a purpose built grid simulator rather than Freqtrade. Freqtrade is excellent for entry and exit signal strategies, but a grid rests a ladder of orders, which does not map cleanly onto its signal model. The custom simulator gives exact control over grid fills, fee accounting on every fill, and the held inventory on a breakout. Freqtrade stays available in the stack for the directional and trend following pieces in later phases, and for its data download and parameter search utilities.

## 5. Backtest hygiene, non negotiable

* Charge real fees on every fill plus a slippage fraction. Dense grids generate huge fill counts, so undercharging fees is the fastest route to a fake profit. The first synthetic run already showed fee drag turning a ranging market negative, which is the harness working as intended.
* Add funding cost on any futures variant.
* Test across a window holding bull, bear, and long sideways stretches.
* Split in sample and out of sample. Tune on in sample only, then run untouched on out of sample. Walk forward across rolling windows to confirm parameters are not curve fit.
* Treat backtest results as an upper bound. Live fills are not guaranteed and latency is real.

## 6. Phase gates

**Phase 0, foundations.** Repo structure, config, persistence, test suite, the backtest harness, regime classifier, grid simulator, and risk overlay. Gate to advance: positive net expectancy after costs across multiple regimes on real one year data, not one lucky window.

**Phase 1, valuation and shadow mode.** Wire the Blofin adapter to the demo environment with read access. Run the full signal and selection logic in shadow mode, logging and scoring the trades it would make, with no orders sent. Gate: live regime calls match what the classifier expected, and shadow scoring is consistent with the backtest.

**Phase 2, paper trading.** Full order path against the Blofin demo environment with simulated funds. Leverage turns on here once shadow mode has proven the edge. Calibration and realized edge tracked against the gates. Gate: paper results stay within range of the backtest across at least one full regime change.

**Phase 3, small live.** Real positions at minimum size starting with the 50 dollar stake, spot first, risk overlay fully active. Gate: live performance tracks paper across a real regime change.

**Phase 4, learning loop and expansion.** Self adjustment within bounds. Expand the asset set to edge case coins. Add the capped low leverage futures amplifier only if it improves risk adjusted return in testing.

## 7. Tooling discipline

* Python 3.11 or later.
* A dedicated testing subagent owns writing and running tests, defined at `.claude/agents/test-runner.md`, so the main coding context stays focused on building.
* Ask before building is a repeated theme. Confirm assumptions at every new piece.

## 8. Open items to close deliberately

* Confirm the exact top ten symbol list against current market cap at run time, and that each has clean one year history on the data source.
* Tune grid density against fee drag. The first run showed tight auto ranges over trade. Candidate levers: fewer grids, wider band, maker only fills, geometric spacing.
* Refine the win rate definition to net both legs of a round trip, since the current count flatters dense fee heavy grids.
* Decide the regime aware grid range logic, since a fixed annual percentile band is a placeholder.
* Confirm Blofin demo environment access and API behavior for Phase 1.
* Settle the compounding cadence: reinvest continuously, or sweep a portion to a reserve so a good run cannot be fully given back.
* Decide the asset focus for live: SOL only, or a small basket, once the comparison matrix is in.

## 9. What I need from you

* Create the empty repo on your GitHub and push this scaffold, or tell me the remote and I will prepare the exact commands.
* For Phase 1 onward, Blofin API keys with read and trade permissions and withdrawal permission off, placed in a local .env.
* Confirmation to proceed asset by asset once the first real comparison matrix is in front of us.
