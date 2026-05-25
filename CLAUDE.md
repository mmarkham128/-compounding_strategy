# CLAUDE.md

Project context for Claude Code. Read this first, every session.

## What this is

Compounding Strategy is an automated crypto trading system for sustainable, compounding gains on Blofin. A spot grid core gated by a regime classifier, wrapped in an always on risk overlay, proven by backtesting before any capital is at risk. Full detail in `docs/SPEC.md`.

## Working rules

* Ask before building. Research and confirm assumptions before each new piece. This is a repeated theme, not a one time step.
* The risk overlay is always on, in every phase. Nothing bypasses it.
* All parameters live in `config/config.yaml`. Never hard code values in modules.
* No hyphens anywhere in prose, comments, or docs. Use spaces or rephrase.
* Tests are owned by the testing subagent at `.claude/agents/test-runner.md`. Delegate validation to it and keep the main context on building.

## Architecture

* `data/loader.py` downloads OHLCV through ccxt from Binance, caches to CSV. Runs on the local machine, not in a restricted sandbox.
* `regime/` computes indicators and labels each candle ranging, trend up, trend down, or chop.
* `backtest/grid_simulator.py` is the deterministic spot grid fill model. `runner.py` builds the multi asset comparison matrix. `metrics.py` holds return, drawdown, and Sharpe.
* `risk/overlay.py` is the circuit breaker, kill switch, and fractional sizer.
* `persistence/` is SQLite for bot state, trades, backtest runs, and equity curves.

## Current state

Phase 0, validation. The harness is hardened: walk forward OOS, circuit breaker
applied in the backtest, win rate netting fixed. Two backtest runs are complete.
The naive always on grid is negative out of sample on all ten assets, so the
Phase 0 gate is NOT cleared and no strategy is selected yet.

Next action: the two track pass below. Track A is a regime gated grid rerun.
Track B is copy trading research and comparison. Stop for human review before
selecting a strategy or starting Phase 1.

## Phase 0 done criteria

Positive net expectancy after fees and slippage across multiple regimes on real
out of sample data, shown on walk forward windows, not a single lucky period.
Currently NOT met.

## Progress log (newest at bottom)

2026-05-25, consolidation after a mid session reboot. Reconstructed because only
the scaffold commit existed in git. History to date:

- Scaffold built and committed: grid simulator, regime classifier, risk overlay,
  backtest harness, persistence, tests passing.
- Binance is geo blocked from the US. Data source moved off Binance. Confirm the
  exact venue in config. KuCoin and OKX are also US blocked, Blofin public
  endpoints are the preferred source, Kraken without TRX is the fallback.
- First real run showed 8 to 19 percent returns. Hindsight illusion: grid bounds
  were set from the same year's percentiles (lookahead) and the breaker was not
  applied. Discarded.
- Hardening run: walk forward OOS, 3 month lookback, 10 OOS months, breaker wired
  in, win rate netting fixed. Result: every asset negative OOS. Gate not cleared.
  The harness worked, it killed a false positive. Findings: win rate reads 100
  percent and is a vanity metric for grids, since every round trip is profitable
  by construction. Realized and unrealized percent columns have an aggregation
  artifact (summed across 10 windows over one window's base capital), so their
  magnitudes are not yet interpretable. TRX alone had zero breaker trips and
  positive realized at plus 5.56 percent but a depreciating held bag, which shows
  the spread capture engine works and the killer is directional inventory risk,
  not the grid math.

Open insight to test: a 20 percent equity drawdown breaker may be the wrong risk
primitive for a grid, since a grid expects to hold through dips while the breaker
crystallizes losses near the bottom. Range breakout invalidation, exit if price
breaks decisively below the grid floor, is the cleaner primitive to test.

Fix order, one lever at a time, each validated OOS, to avoid curve fitting back
to a fake positive:
1. Regime gating (this pass).
2. Range breakout invalidation versus the equity breaker.
3. Partial capital deployment with a cash reserve.

Kill criterion: if a regime gated, range invalidated grid still cannot clear
positive OOS expectancy after these mechanism justified fixes, stop rescuing the
grid and let the other strategies compete on equal footing.

## Phase 0 done criteria

Positive net expectancy after fees and slippage across multiple regimes on real one year data, demonstrated on out of sample windows, not a single lucky period. Only then does Phase 1 begin.

## Known tuning levers

Grid density against fee drag is the first one. The opening synthetic run showed a tight auto range over trading into a loss once fees were charged on every fill. Candidate fixes: fewer grids, a wider band, maker only fills, or geometric spacing. The win rate metric also needs to net both legs of a round trip.
