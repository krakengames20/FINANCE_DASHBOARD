"""Offline tests for the per-series fetch log and staleness check."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.data import freshness


@pytest.fixture(autouse=True)
def _clean_log():
    freshness.clear_log()
    yield
    freshness.clear_log()


def _series(end: str, freq: str, n: int = 40) -> pd.Series:
    idx = pd.date_range(end=end, periods=n, freq=freq)
    return pd.Series(range(n), index=idx, dtype=float)


@pytest.mark.parametrize(
    "freq, expected",
    [("B", "D"), ("W-FRI", "W"), ("MS", "M"), ("QS", "Q"), ("YS", "A")],
)
def test_infer_freq(freq, expected):
    assert freshness.infer_freq(_series("2026-09-01", freq).index) == expected


def test_infer_freq_too_short():
    assert freshness.infer_freq(pd.DatetimeIndex(["2026-01-01"])) == "?"


def test_status_ok_late_failed_discontinued():
    today = dt.date(2026, 10, 5)
    freshness.record_fetch("DGS10", _series("2026-10-02", "B"))       # 3 days old → ok
    freshness.record_fetch("UNRATE", _series("2026-09-01", "MS"))     # 34 days → ok
    freshness.record_fetch("HOUST", _series("2026-05-01", "MS"))      # 157 days → late
    freshness.record_fetch("USSLIND", _series("2020-02-01", "MS"))    # known discontinued
    freshness.record_fetch("BADID", error="ValueError: Bad Request")

    table = freshness.status_table(freshness.fetch_log(), today=today).set_index("series")
    assert table.loc["DGS10", "status"] == "ok"
    assert table.loc["UNRATE", "status"] == "ok"
    assert table.loc["HOUST", "status"] == "late"
    assert table.loc["USSLIND", "status"] == "discontinued"
    assert table.loc["BADID", "status"] == "failed"
    assert "Bad Request" in table.loc["BADID", "note"]

    s = freshness.summary(table.reset_index())
    assert (s["n"], s["ok"], s["late"], s["failed"], s["discontinued"]) == (5, 2, 1, 1, 1)
    assert s["latest_daily"] == dt.date(2026, 10, 2)  # the only daily series here
    assert s["latest_monthly"] == dt.date(2026, 9, 1)


def test_latest_daily_ignores_single_early_poster():
    freshness.record_fetch("DGS10", _series("2026-10-02", "B"))
    freshness.record_fetch("DGS2", _series("2026-10-02", "B"))
    freshness.record_fetch("IORB", _series("2026-10-05", "B"))  # posted ahead of time
    s = freshness.summary(freshness.status_table(freshness.fetch_log(), today=dt.date(2026, 10, 5)))
    assert s["latest_daily"] == dt.date(2026, 10, 2)


def test_override_extends_allowed_lag():
    # Case-Shiller is dated the 1st and published ~2 months later: 96 days is normal.
    freshness.record_fetch("CSUSHPISA", _series("2026-07-01", "MS"))
    table = freshness.status_table(freshness.fetch_log(), today=dt.date(2026, 10, 5))
    assert table.iloc[0]["status"] == "ok"


def test_history_limited_note_kept():
    freshness.record_fetch("BAMLH0A0HYM2", _series("2026-10-01", "B"))
    row = freshness.status_table(freshness.fetch_log(), today=dt.date(2026, 10, 5)).iloc[0]
    assert row["status"] == "ok"
    assert "3 years" in row["note"]


def test_failure_after_success_keeps_last_obs():
    freshness.record_fetch("DGS10", _series("2026-10-02", "B"))
    freshness.record_fetch("DGS10", error="HTTPError: 500")
    row = freshness.status_table(freshness.fetch_log(), today=dt.date(2026, 10, 5)).iloc[0]
    assert row["status"] == "failed"
    assert row["last_obs"] == dt.date(2026, 10, 2)


def test_error_text_scrubs_api_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "abc123secret")
    freshness.record_fetch("X", error="GET ...?api_key=abc123secret failed")
    assert "abc123secret" not in freshness.fetch_log()["X"]["error"]


def test_empty_summary():
    s = freshness.summary(freshness.status_table({}))
    assert s["n"] == 0 and s["fetched_at"] is None


def test_fetch_series_records_success_and_failure(monkeypatch):
    from src.data import fred_client

    class FakeFred:
        def get_series(self, series_id, observation_start=None):
            if series_id == "BAD":
                raise ValueError("Bad Request. The series does not exist.")
            return _series("2026-09-01", "MS")

    monkeypatch.setattr(fred_client, "_get_client", lambda: FakeFred())
    fred_client.fetch_series.clear()

    fred_client.fetch_series("GOOD")
    with pytest.raises(RuntimeError):
        fred_client.fetch_series("BAD")

    log = freshness.fetch_log()
    assert log["GOOD"]["error"] is None and log["GOOD"]["freq"] == "M"
    assert "does not exist" in log["BAD"]["error"]
    fred_client.fetch_series.clear()
