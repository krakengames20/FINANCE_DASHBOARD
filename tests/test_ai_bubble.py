"""Offline tests for the AI Bubble tab: Yahoo parsing, watchlist integrity,
price maths and signal thresholds. No network calls."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import ai_watchlist as wl
from src.data.market_prices import parse_chart, parse_quote
from src.models import ai_bubble as ab

FIX = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------------ helpers


def _bdays(n: int, end: str = "2026-10-07") -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=n)


def _walk(n: int, seed: int, drift: float = 0.0005, vol: float = 0.02, start: float = 100.0):
    r = np.random.default_rng(seed).normal(drift, vol, n)
    return start * np.cumprod(1 + r)


@pytest.fixture
def closes() -> pd.DataFrame:
    idx = _bdays(520)
    df = pd.DataFrame({t: _walk(len(idx), i) for i, t in enumerate(wl.all_tickers())}, index=idx)
    df["^VIX"] = 15.0
    df["^VIX3M"] = 18.0
    df["^VXN"] = 21.0
    # A late listing: no data before June 2026.
    df.loc[df.index < "2026-06-12", "SPCX"] = np.nan
    return df


# ------------------------------------------------------------- Yahoo parsing


def test_parse_chart_real_fixture():
    payload = json.loads((FIX / "yahoo_chart_nvda_1mo.json").read_text())
    s, meta = parse_chart(payload)
    assert meta["symbol"] == "NVDA"
    assert len(s) == 22 and s.index.is_monotonic_increasing
    # gmtoffset shifts the 13:30 UTC stamps onto the New York trading date
    assert s.index[-1] == pd.Timestamp("2026-10-07")
    assert s.iloc[-1] == pytest.approx(237.47, abs=1e-3)
    assert s.index.tz is None


def test_parse_chart_not_found_raises():
    payload = json.loads((FIX / "yahoo_chart_not_found.json").read_text())
    with pytest.raises(ValueError, match="Not Found"):
        parse_chart(payload)


@pytest.mark.parametrize("payload", [{}, {"chart": {"result": []}}, None])
def test_parse_chart_empty_raises(payload):
    with pytest.raises(ValueError):
        parse_chart(payload)


def test_parse_chart_drops_null_closes():
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "X", "gmtoffset": 0},
                    "timestamp": [1_790_000_000, 1_790_086_400, 1_790_172_800],
                    "indicators": {"quote": [{"close": [1.0, None, 3.0]}]},
                }
            ],
            "error": None,
        }
    }
    s, _ = parse_chart(payload)
    assert list(s.values) == [1.0, 3.0]


def test_parse_quote_real_fixture():
    payload = json.loads((FIX / "yahoo_quote_nvda_crwv.json").read_text())
    q = parse_quote(payload)
    assert q["NVDA"]["pe_trailing"] == pytest.approx(30.25, abs=0.01)
    assert q["NVDA"]["pe_forward"] == pytest.approx(14.92, abs=0.01)
    assert q["CRWV"]["pe_trailing"] is None  # loss-making: Yahoo omits it


# ---------------------------------------------------------- watchlist sanity


def test_watchlist_has_20_ai_names_and_unique_tickers():
    assert len(wl.ai_basket()) == 20
    tickers = wl.table_tickers()
    assert len(tickers) == len(set(tickers))


def test_watchlist_groups_and_risk_scores_valid():
    for s in wl.STOCKS:
        assert s.group in wl.GROUPS, s
        assert s.risk is None or 1 <= s.risk <= 10, s
        assert s.why
        if s.listed:
            dt.date.fromisoformat(s.listed)


def test_baskets_are_in_the_universe():
    universe = set(wl.all_tickers())
    for basket in (wl.BUILDERS, wl.LEADERS, wl.PRIVATE_CREDIT):
        assert set(basket) <= universe


def test_events_valid_and_upcoming_sorted():
    assert all(e.status in {"confirmed", "reported", "estimated"} for e in wl.EVENTS)
    up = wl.upcoming_events(dt.date(2026, 10, 8))
    assert [e.date for e in up] == sorted(e.date for e in up)
    assert all(e.date >= dt.date(2026, 10, 8) for e in up)
    assert len(wl.upcoming_events(dt.date(2026, 10, 8), limit=3)) == 3


# ------------------------------------------------------------- price maths


def test_change_windows_use_calendar_offsets():
    idx = pd.bdate_range("2026-08-01", "2026-10-07")
    s = pd.Series(np.arange(1, len(idx) + 1, dtype=float), index=idx)
    # 7 calendar days before Wed 7 Oct is Wed 30 Sep
    assert ab.change_since(s, days=7) == pytest.approx((s.iloc[-1] / s.loc["2026-09-30"] - 1) * 100)
    assert ab.change_since(s, months=1) == pytest.approx(
        (s.iloc[-1] / s.loc["2026-09-07"] - 1) * 100
    )
    assert ab.change_1d(s) == pytest.approx((s.iloc[-1] / s.iloc[-2] - 1) * 100)


def test_change_since_not_enough_history_is_nan():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-10-06", "2026-10-07"]))
    assert np.isnan(ab.change_since(s, months=1))


def test_from_high():
    s = pd.Series(
        [100.0, 200.0, 150.0], index=pd.to_datetime(["2026-01-02", "2026-06-01", "2026-10-07"])
    )
    assert ab.from_high(s) == pytest.approx(-25.0)


def test_stock_table_shape_and_missing_ticker(closes):
    closes = closes.drop(columns=["WULF"])
    fund = {"NVDA": {"pe_trailing": 30.0, "pe_forward": 15.0}, "CRWV": {"pe_trailing": -5.0}}
    t = ab.stock_table(closes, fund)
    assert len(t) == len(wl.STOCKS)
    wulf = t.set_index("Ticker").loc["WULF"]
    assert np.isnan(wulf["Price"]) and wulf["Data date"] is None
    nvda = t.set_index("Ticker").loc["NVDA"]
    assert nvda["P/E trailing"] == 30.0 and nvda["P/E forward"] == 15.0
    assert np.isnan(t.set_index("Ticker").loc["CRWV", "P/E trailing"])  # negative → blank


def test_equal_weight_index_handles_late_listing(closes):
    idx = ab.equal_weight_index(closes, ["NVDA", "SPCX"])
    assert idx.iloc[0] == pytest.approx(100.0 * (1 + 0.0), rel=0.05)
    assert idx.notna().all()


def test_equal_weight_index_math():
    idx = pd.bdate_range("2026-01-01", periods=3)
    df = pd.DataFrame({"A": [100, 110, 121], "B": [100, 90, 81]}, index=idx, dtype=float)
    ew = ab.equal_weight_index(df, ["A", "B"])
    # day 2: mean(+10%, -10%) = 0 ; day 3: same
    assert list(ew.round(6)) == [100.0, 100.0, 100.0]


def test_breadth_counts_only_names_with_full_window():
    idx = pd.bdate_range("2026-01-01", periods=60)
    up = pd.Series(np.linspace(1, 2, 60), index=idx)
    df = pd.DataFrame({"UP": up, "DOWN": up[::-1].values, "NEW": np.nan}, index=idx)
    b = ab.breadth(df, ["UP", "DOWN", "NEW"], 50)
    assert b.iloc[-1] == pytest.approx(50.0)


def test_builders_vs_leaders_detects_divergence():
    idx = _bdays(300)
    df = pd.DataFrame(index=idx)
    for t in wl.BUILDERS:
        df[t] = np.linspace(100, 50, len(idx))  # builders halve
    for t in wl.LEADERS:
        df[t] = np.linspace(100, 120, len(idx))  # leaders rise
    r = ab.builders_vs_leaders(df)
    assert r.iloc[0] == pytest.approx(100.0)
    assert r.iloc[-1] < 50


# ------------------------------------------------------------------ signals


def _status_of(signals, key):
    return {s.key: s for s in signals}[key].status


def test_signals_complete_without_fred(closes):
    sigs = ab.evaluate_signals(closes, fred=None)
    keys = [s.key for s in sigs]
    assert len(keys) == len(set(keys)) == 9
    assert _status_of(sigs, "hy_credit") == ab.NA
    assert _status_of(sigs, "ten_year") == ab.NA
    assert _status_of(sigs, "volatility") == ab.CALM  # VIX 15, ratio 0.83
    assert all(s.status in {ab.CALM, ab.WATCH, ab.ALERT, ab.NA} for s in sigs)


def test_signals_never_raise_on_empty_inputs():
    sigs = ab.evaluate_signals(pd.DataFrame(), fred={})
    assert len(sigs) == 9
    assert all(s.status == ab.NA for s in sigs)
    assert all("—" in s.value for s in sigs)


def test_volatility_backwardation_is_alert(closes):
    closes = closes.copy()
    closes["^VIX"] = 25.0
    closes["^VIX3M"] = 22.0
    assert _status_of(ab.evaluate_signals(closes), "volatility") == ab.ALERT


def test_credit_and_rates_thresholds(closes):
    idx = pd.date_range("2026-08-01", "2026-10-07", freq="B")
    hy_wide = pd.Series(np.linspace(3.0, 4.2, len(idx)), index=idx)  # ~+80bp in a month
    tens = pd.Series(5.27, index=idx)
    sigs = ab.evaluate_signals(closes, fred={"BAMLH0A0HYM2": hy_wide, "DGS10": tens})
    assert _status_of(sigs, "hy_credit") == ab.WATCH
    assert _status_of(sigs, "ten_year") == ab.WATCH
    tens_hi = pd.Series(5.6, index=idx)
    assert _status_of(ab.evaluate_signals(closes, fred={"DGS10": tens_hi}), "ten_year") == ab.ALERT


def test_global_equities_drawdown_triggers(closes):
    closes = closes.copy()
    n = len(closes)
    closes["ACWI"] = np.r_[np.full(n - 20, 100.0), np.full(20, 78.0)]
    assert _status_of(ab.evaluate_signals(closes), "global_equities") == ab.ALERT


def test_summarize_counts(closes):
    sigs = ab.evaluate_signals(closes)
    c = ab.summarize(sigs)
    assert sum(c.values()) == len(sigs)


def test_group_indices(closes):
    g = ab.group_indices(closes, start="2025-10-07")
    assert set(g.columns) == {
        "Levered builders",
        "Chips & hardware",
        "Power & grid",
        "Platforms & labs",
    }
    assert g.iloc[0].round(6).eq(100.0).all()
