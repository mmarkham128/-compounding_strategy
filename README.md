# Compounding Strategy

An automated crypto trading system built for sustainable, compounding gains on Blofin. A spot grid core gated by a regime classifier, wrapped in an always on risk overlay, validated by backtesting before any capital is at risk.

The goal is a curve that never resets to zero. Headline monthly returns stay modest on purpose, because survival across every market regime is what lets a fractional, risk sized stake compound over time.

## Why this exists

A bot amplifies an edge, it does not create one. So the whole project is structured to prove positive expectancy after fees, funding, and slippage on cheap, offline data first, then forward test on a demo venue, then go live small, then scale only once the live record holds. Every phase has a gate that must clear before the next begins.

## Status

Phase 0, foundations. The backtest harness, regime classifier, spot grid simulator, risk overlay, persistence, and test suite are in place. Next step is running the harness on one year of real data across the top ten assets to produce the first comparison matrix.

## Quick start

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest                       # validate the core logic, runs offline
python scripts/run_phase0_backtest.py  # downloads data and prints the comparison
```

The test suite runs fully offline on synthetic markets. The backtest script reaches Binance through ccxt to download one year of hourly candles, caches them locally, then runs the grid plus regime analysis on each asset.

## Layout

```
config/config.yaml                 all tunable parameters, no values hard coded
scripts/run_phase0_backtest.py     Phase 0 entry point
src/compounding_strategy/
  config.py                        config loader with environment secret overlay
  data/loader.py                   ccxt OHLCV download with CSV cache
  regime/indicators.py             EMA, ATR, ADX, Bollinger width
  regime/classifier.py             labels each candle ranging, trend up, trend down, chop
  backtest/grid_simulator.py       deterministic spot grid fill model
  backtest/metrics.py              return, drawdown, Sharpe
  backtest/runner.py               multi asset comparison matrix
  risk/overlay.py                  circuit breaker, kill switch, fractional sizing
  persistence/                     SQLite schema and helpers
tests/                             pytest suite, synthetic markets
docs/SPEC.md                       full spec, phase gates, decisions, open items
.claude/agents/test-runner.md      testing subagent prompt for Claude Code
```

## Conventions

* Ask before building. Research and confirm assumptions before each new piece, every time.
* All parameters live in config, never hard coded in modules.
* The risk overlay is always on, in every phase.
* No hyphens anywhere in docs or comments, per project style.

See `docs/SPEC.md` for the complete plan.
