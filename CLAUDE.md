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

## Current phase

Phase 0, foundations. The harness is built and the test suite passes offline. Next action is running `scripts/run_phase0_backtest.py` on one year of real data across the top ten assets, then reading the comparison matrix together before narrowing the traded set.

## Phase 0 done criteria

Positive net expectancy after fees and slippage across multiple regimes on real one year data, demonstrated on out of sample windows, not a single lucky period. Only then does Phase 1 begin.

## Known tuning levers

Grid density against fee drag is the first one. The opening synthetic run showed a tight auto range over trading into a loss once fees were charged on every fill. Candidate fixes: fewer grids, a wider band, maker only fills, or geometric spacing. The win rate metric also needs to net both legs of a round trip.
