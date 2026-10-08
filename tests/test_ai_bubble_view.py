"""Render the AI Bubble tab headlessly with Streamlit's AppTest, using
synthetic prices (no network). Guards against the tab breaking the app."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _script_ok():
    import numpy as np
    import pandas as pd

    import src.ui.views.ai_bubble as view
    from src.data import ai_watchlist as wl
    from src.data.market_prices import MarketData

    idx = pd.bdate_range(end="2026-10-07", periods=520)
    rng = np.random.default_rng(0)
    closes = pd.DataFrame(
        {t: 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, len(idx))) for t in wl.all_tickers()},
        index=idx,
    )
    closes.loc[closes.index < "2026-06-12", "SPCX"] = np.nan
    closes = closes.drop(columns=["WULF"])  # one failed download
    log = [(t, "ok", "") for t in closes.columns] + [("WULF", "failed", "HTTP 429")]
    fred_idx = pd.bdate_range(end="2026-10-07", periods=80)
    view.fetch_market_data = lambda tickers: MarketData(closes=closes, meta={}, log=log)
    view.fetch_fundamentals = lambda tickers: (
        {"NVDA": {"pe_trailing": 30.0, "pe_forward": 15.0}},
        "test",
    )
    view._load_fred = lambda: {
        "BAMLH0A0HYM2": pd.Series(3.0, index=fred_idx),
        "DGS10": pd.Series(5.27, index=fred_idx),
    }
    view.render()


def _script_empty():
    import pandas as pd

    import src.ui.views.ai_bubble as view
    from src.data.market_prices import MarketData

    view.fetch_market_data = lambda tickers: MarketData(
        closes=pd.DataFrame(), log=[("NVDA", "failed", "timeout")]
    )
    view.render()


def _script_raises():
    import src.ui.views.ai_bubble as view

    def boom(tickers):
        raise ConnectionError("offline")

    view.fetch_market_data = boom
    view.render()


def _all_markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_tab_renders_with_data():
    at = AppTest.from_function(_script_ok, default_timeout=60).run()
    assert not at.exception, at.exception
    text = _all_markdown(at)
    assert "AI bubble signals" in text
    assert "Builders vs leaders" in text and "Global equities from peak" in text
    assert "Upcoming catalysts" in text or "No upcoming events" in text
    assert len(at.dataframe) >= 1  # the stock table (and feed status)
    # No section fell back to the error note.
    assert "could not be drawn" not in text


def test_tab_controls_work():
    at = AppTest.from_function(_script_ok, default_timeout=60).run()
    at.selectbox(key="ai_sort").select("Trailing P/E (high first)").run()
    assert not at.exception, at.exception


def test_tab_handles_no_prices():
    at = AppTest.from_function(_script_empty, default_timeout=60).run()
    assert not at.exception, at.exception
    assert "could not be loaded" in _all_markdown(at)


def test_tab_handles_download_error():
    at = AppTest.from_function(_script_raises, default_timeout=60).run()
    assert not at.exception, at.exception
    assert "offline" in _all_markdown(at)
