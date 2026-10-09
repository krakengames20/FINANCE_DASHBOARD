"""Daily prices and valuation ratios from Yahoo Finance, for the AI Bubble tab.

No new dependency: prices come from Yahoo's public v8 chart endpoint via
``requests`` (already required). P/E ratios come from the v7 quote endpoint,
which needs a cookie + "crumb" handshake; if that fails and ``yfinance`` happens
to be installed, it is used as a fallback, otherwise P/E shows as "—".

Everything degrades per ticker: a bad symbol, a timeout or a throttled request
is logged and skipped, never raised, so one failure cannot take the tab down.
Yahoo data is unofficial and delayed (~15 min); this is a monitoring feed, not
a trading feed.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np

CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
QUOTE_URL = "https://query2.finance.yahoo.com/v7/finance/quote"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
_TIMEOUT = 12
_WORKERS = 8
PRICE_TTL = 3600  # prices: 1 hour
FUNDAMENTALS_TTL = 21600  # P/E: 6 hours, it barely moves intraday


def _cache_data(*args, **kwargs):
    """``st.cache_data`` inside Streamlit; a no-op decorator elsewhere (tests)."""
    try:
        import streamlit as st

        return st.cache_data(*args, **kwargs)
    except Exception:  # pragma: no cover - streamlit always present in the app

        def _passthrough(fn):
            return fn

        return _passthrough


@dataclass
class MarketData:
    """Closes (one column per ticker, tz-naive local trading dates) plus metadata."""

    closes: pd.DataFrame
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    log: list[tuple[str, str, str]] = field(default_factory=list)  # (ticker, status, detail)
    fetched_at: dt.datetime | None = None

    @property
    def ok(self) -> list[str]:
        return [t for t, status, _ in self.log if status == "ok"]

    @property
    def failed(self) -> list[tuple[str, str]]:
        return [(t, detail) for t, status, detail in self.log if status != "ok"]


# ------------------------------------------------------------------ parsing


def parse_chart(payload: dict) -> tuple[pd.Series, dict[str, Any]]:
    """Turn a v8 chart response into (daily closes, meta).

    Bars are stamped in UTC; shifting by the exchange's ``gmtoffset`` gives the
    local trading date, so Tokyo and New York closes line up by calendar date.
    Raises ``ValueError`` when Yahoo reports an error or returns no prices.
    """
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        raise ValueError(f"{err.get('code', 'error')}: {err.get('description', '')}".strip())
    results = chart.get("result") or []
    if not results:
        raise ValueError("empty result")
    res = results[0]
    meta = dict(res.get("meta") or {})
    stamps = res.get("timestamp") or []
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    if not stamps or not closes:
        raise ValueError("no price history")
    offset = int(meta.get("gmtoffset") or 0)
    dates = pd.to_datetime([int(t) + offset for t in stamps], unit="s").normalize()
    s = pd.Series(
        pd.to_numeric(pd.Series(closes), errors="coerce").values, index=dates, dtype=float
    )
    s = s[~s.index.duplicated(keep="last")].dropna().sort_index()
    s = s[np.isfinite(s) & (s > 0)]
    if s.empty:
        raise ValueError("no valid closes")
    s.name = meta.get("symbol")
    return s, meta


def parse_quote(payload: dict) -> dict[str, dict[str, float | None]]:
    """Valuation fields per ticker from a v7 quote response."""
    out: dict[str, dict[str, float | None]] = {}
    for row in ((payload or {}).get("quoteResponse") or {}).get("result") or []:
        sym = row.get("symbol")
        if not sym:
            continue
        out[sym] = {
            "pe_trailing": _num(row.get("trailingPE")),
            "pe_forward": _num(row.get("forwardPE")),
            "eps_trailing": _num(row.get("epsTrailingTwelveMonths")),
            "eps_forward": _num(row.get("epsForward")),
            "market_cap": _num(row.get("marketCap")),
        }
    return out


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if pd.notna(v) else None


# ------------------------------------------------------------------ fetching


def _session():
    import requests

    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _fetch_one(session, ticker: str, range_: str) -> tuple[str, pd.Series | None, dict, str]:
    url = CHART_URL.format(ticker=ticker)
    params = {"range": range_, "interval": "1d", "includePrePost": "false"}
    last_err = ""
    for _attempt in range(2):
        try:
            r = session.get(url, params=params, timeout=_TIMEOUT)
            payload = r.json() if r.content else {}
            if r.status_code >= 400 and not (payload.get("chart") or {}).get("error"):
                raise ValueError(f"HTTP {r.status_code}")
            s, meta = parse_chart(payload)
            return ticker, s, meta, ""
        except Exception as exc:  # noqa: BLE001 - any failure is logged per ticker
            last_err = f"{type(exc).__name__}: {exc}"[:160]
            if "Not Found" in last_err:
                break
    return ticker, None, {}, last_err


@_cache_data(ttl=PRICE_TTL, show_spinner=False)
def fetch_market_data(tickers: tuple[str, ...], range_: str = "2y") -> MarketData:
    """Daily closes for ``tickers`` (parallel, cached 1 h)."""
    session = _session()
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda t: _fetch_one(session, t, range_), tickers))
    series, meta, log = {}, {}, []
    for ticker, s, m, err in results:
        if s is None:
            log.append((ticker, "failed", err or "no data"))
            continue
        series[ticker] = s
        meta[ticker] = m
        log.append((ticker, "ok", f"{len(s)} days to {s.index.max():%d %b %Y}"))
    closes = pd.DataFrame(series).sort_index() if series else pd.DataFrame()
    if not closes.empty:
        closes = closes[[t for t in tickers if t in closes.columns]]
    return MarketData(closes=closes, meta=meta, log=log, fetched_at=dt.datetime.now())


@_cache_data(ttl=FUNDAMENTALS_TTL, show_spinner=False)
def fetch_fundamentals(tickers: tuple[str, ...]) -> tuple[dict[str, dict[str, float | None]], str]:
    """Trailing/forward P/E per ticker, plus a one-line status for the UI."""
    try:
        session = _session()
        session.get(COOKIE_URL, timeout=_TIMEOUT)  # sets the consent cookie; 404 is normal
        crumb = session.get(CRUMB_URL, timeout=_TIMEOUT).text.strip()
        if not crumb or "<" in crumb or len(crumb) > 64:
            raise ValueError("no crumb")
        r = session.get(
            QUOTE_URL, params={"symbols": ",".join(tickers), "crumb": crumb}, timeout=_TIMEOUT
        )
        data = parse_quote(r.json())
        if data:
            return data, f"Yahoo quote · {len(data)} tickers"
        raise ValueError("empty quote response")
    except Exception as exc:  # noqa: BLE001
        primary_error = f"{type(exc).__name__}: {exc}"[:120]

    try:  # optional fallback, only if the user has yfinance installed
        import yfinance as yf  # type: ignore

        out = {}
        for t in tickers:
            info = yf.Ticker(t).info or {}
            out[t] = {
                "pe_trailing": _num(info.get("trailingPE")),
                "pe_forward": _num(info.get("forwardPE")),
                "eps_trailing": _num(info.get("trailingEps")),
                "eps_forward": _num(info.get("forwardEps")),
                "market_cap": _num(info.get("marketCap")),
            }
        return out, f"yfinance fallback · {len(out)} tickers"
    except Exception:  # noqa: BLE001
        return {}, f"P/E unavailable ({primary_error})"
