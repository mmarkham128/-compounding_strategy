"""Tests for the regime classifier."""

from compounding_strategy.regime.classifier import Regime, classify


def test_uptrend_detected(uptrend_market):
    labels = classify(uptrend_market)
    tail = labels.iloc[200:]  # skip indicator warmup
    assert (tail == Regime.TREND_UP.value).mean() > 0.3


def test_downtrend_detected(downtrend_market):
    labels = classify(downtrend_market)
    tail = labels.iloc[200:]
    assert (tail == Regime.TREND_DOWN.value).mean() > 0.3


def test_ranging_detected(ranging_market):
    labels = classify(ranging_market)
    tail = labels.iloc[200:]
    assert (tail == Regime.RANGING.value).mean() > 0.3


def test_labels_are_valid(ranging_market):
    labels = classify(ranging_market)
    valid = {r.value for r in Regime}
    assert set(labels.unique()).issubset(valid)
    assert len(labels) == len(ranging_market)
