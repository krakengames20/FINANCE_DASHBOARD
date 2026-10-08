"""AI-bubble monitor: price changes, basket indices and red/amber/green signals.

Pure functions over a closes DataFrame (one column per ticker, daily, local
trading dates) and optional FRED series, so everything is testable offline.

The signals encode the FINANCE project's dot-com comparison:
- in 2000 the weakest-funded firms broke first, months before the leaders
  (builders vs leaders, AI breadth);
- leadership narrowed before the top (equal-weight vs cap-weight);
- the supplier reset showed in semis (semis trend);
- stress then spread through credit (HY spreads, private-credit proxies) and
  rates (10-year yield);
- the rulebook deploys dry powder at −20% / −30% on global equities.
Thresholds are judgement calls, kept in one place (``THRESHOLDS``) so they can
be tuned.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.ai_watchlist import BUILDERS, LEADERS, PRIVATE_CREDIT, STOCKS, Stock

CALM, WATCH, ALERT, NA = "CALM", "WATCH", "ALERT", "N/A"

THRESHOLDS: dict[str, dict[str, float]] = {
    # 3-month change in builders ÷ leaders (%). Builders falling behind = red.
    "builders_vs_leaders": {"watch": -10.0, "alert": -20.0},
    # Share of the 20 AI names above their 200-day average (%).
    "ai_breadth": {"watch": 60.0, "alert": 40.0},
    # 3-month change in equal-weight ÷ cap-weight S&P 500 (%). Falling = narrowing.
    "equal_vs_cap": {"watch": -3.0, "alert": -6.0},
    # VIX level and VIX ÷ VIX3M (above 1 = near-term fear exceeds 3-month).
    "vix_level": {"watch": 20.0, "alert": 30.0},
    "vix_term": {"watch": 0.95, "alert": 1.0},
    # High-yield spread: 1-month change (bp) and level (%).
    "hy_change_bp": {"watch": 50.0, "alert": 100.0},
    "hy_level": {"watch": 4.5, "alert": 6.0},
    # 10-year Treasury yield (%).
    "ten_year": {"watch": 5.0, "alert": 5.5},
    # Private-credit proxy basket, % from 52-week high.
    "private_credit": {"watch": -15.0, "alert": -30.0},
    # Global equities (ACWI), % from 52-week high: the rulebook's −20% / −30% triggers.
    "global_equities": {"watch": -10.0, "alert": -20.0},
}


@dataclass(frozen=True)
class Signal:
    key: str
    name: str
    value: str
    status: str  # CALM | WATCH | ALERT | N/A
    detail: str


# --------------------------------------------------------------- price maths


def _clean(s: pd.Series) -> pd.Series:
    return s.dropna().sort_index()


def change_since(s: pd.Series, *, days: int = 0, months: int = 0) -> float:
    """% change from the close on or before (last date − offset) to the last close."""
    s = _clean(s)
    if len(s) < 2:
        return float("nan")
    end = s.index[-1]
    start = end - pd.DateOffset(days=days, months=months)
    base = s.loc[:start]
    if base.empty:
        return float("nan")
    return float((s.iloc[-1] / base.iloc[-1] - 1.0) * 100.0)


def change_1d(s: pd.Series) -> float:
    s = _clean(s)
    if len(s) < 2:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[-2] - 1.0) * 100.0)


def from_high(s: pd.Series, *, window_days: int = 365) -> float:
    """% below the highest close in the last ``window_days`` calendar days."""
    s = _clean(s)
    if s.empty:
        return float("nan")
    recent = s.loc[s.index[-1] - pd.Timedelta(days=window_days) :]
    return float((s.iloc[-1] / recent.max() - 1.0) * 100.0)


def stock_table(
    closes: pd.DataFrame,
    fundamentals: dict[str, dict] | None = None,
    stocks: tuple[Stock, ...] = STOCKS,
) -> pd.DataFrame:
    """One row per watchlist stock with price, 1d / 7d / 1m change, distance
    from the 52-week high, P/E and the risk-map score. Missing tickers keep
    their row with NaNs, so a failed download is visible rather than silent."""
    fundamentals = fundamentals or {}
    rows = []
    for st in stocks:
        s = closes[st.ticker] if st.ticker in closes.columns else pd.Series(dtype=float)
        s = _clean(s)
        f = fundamentals.get(st.ticker, {})
        rows.append(
            {
                "Group": st.group,
                "Ticker": st.ticker,
                "Name": st.name,
                "Price": float(s.iloc[-1]) if not s.empty else np.nan,
                "Today %": change_1d(s),
                "7d %": change_since(s, days=7),
                "1m %": change_since(s, months=1),
                "From 52w high %": from_high(s),
                "P/E trailing": _pe(f.get("pe_trailing")),
                "P/E forward": _pe(f.get("pe_forward")),
                "Risk": st.risk,
                "Why exposed": st.why,
                "Data date": s.index[-1].date() if not s.empty else None,
            }
        )
    return pd.DataFrame(rows)


def _pe(x) -> float:
    """Negative or absurd P/Es are not meaningful; show them as blank."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if 0 < v < 2000 else np.nan


def equal_weight_index(closes: pd.DataFrame, tickers, *, start=None) -> pd.Series:
    """Equal-weight basket rebalanced daily (mean of available daily returns),
    rebased to 100. Names that list later join on their first day."""
    cols = [t for t in tickers if t in closes.columns]
    if not cols:
        return pd.Series(dtype=float)
    px = closes[cols]
    if start is not None:
        px = px.loc[pd.Timestamp(start) :]
    # Bridge short gaps (holidays on one exchange); leading NaNs before a
    # listing stay NaN, so late listings simply join when they start trading.
    px = px.ffill(limit=5)
    rets = px.pct_change(fill_method=None)
    ew = rets.mean(axis=1, skipna=True).fillna(0.0)
    idx = 100.0 * (1.0 + ew).cumprod()
    first = px.dropna(how="all").index.min()
    return idx.loc[first:]


def ratio(closes: pd.DataFrame, num: str, den: str) -> pd.Series:
    if num not in closes.columns or den not in closes.columns:
        return pd.Series(dtype=float)
    df = closes[[num, den]].ffill(limit=3).dropna()
    return (df[num] / df[den]).rename(f"{num}/{den}")


def builders_vs_leaders(closes: pd.DataFrame) -> pd.Series:
    b = equal_weight_index(closes, BUILDERS)
    lead = equal_weight_index(closes, LEADERS)
    df = pd.concat([b, lead], axis=1, keys=["b", "l"]).dropna()
    if df.empty:
        return pd.Series(dtype=float)
    r = df["b"] / df["l"]
    return (100.0 * r / r.iloc[0]).rename("Builders ÷ leaders")


def breadth(closes: pd.DataFrame, tickers, window: int) -> pd.Series:
    """% of ``tickers`` closing above their ``window``-day moving average,
    counting only names with a full window of history on that day."""
    cols = [t for t in tickers if t in closes.columns]
    if not cols:
        return pd.Series(dtype=float)
    px = closes[cols].ffill(limit=3)
    ma = px.rolling(window, min_periods=window).mean()
    valid = ma.notna() & px.notna()
    above = (px > ma) & valid
    n = valid.sum(axis=1)
    out = (above.sum(axis=1) / n.replace(0, np.nan)) * 100.0
    return out.dropna().rename(f"% above {window}-day average")


def _status(value: float, watch: float, alert: float, *, higher_is_worse: bool) -> str:
    if not np.isfinite(value):
        return NA
    if higher_is_worse:
        return ALERT if value >= alert else WATCH if value >= watch else CALM
    return ALERT if value <= alert else WATCH if value <= watch else CALM


def _worst(*statuses: str) -> str:
    order = {ALERT: 3, WATCH: 2, CALM: 1, NA: 0}
    return max(statuses, key=lambda s: order[s])


def _last(s: pd.Series) -> float:
    s = _clean(s) if s is not None else pd.Series(dtype=float)
    return float(s.iloc[-1]) if not s.empty else float("nan")


def _fmt(v: float, spec: str, suffix: str = "") -> str:
    return f"{v:{spec}}{suffix}" if np.isfinite(v) else "—"


# ------------------------------------------------------------------- signals


def evaluate_signals(
    closes: pd.DataFrame,
    fred: dict[str, pd.Series] | None = None,
    ai_names: list[str] | None = None,
) -> list[Signal]:
    """Compute every signal. Missing inputs give an N/A signal, never an error."""
    fred = fred or {}
    ai_names = ai_names or [s.ticker for s in STOCKS if s.group != "Reference"]
    th = THRESHOLDS
    out: list[Signal] = []

    # 1. Builders vs leaders
    bl = builders_vs_leaders(closes)
    c3 = change_since(bl, months=3)
    c1 = change_since(bl, months=1)
    t = th["builders_vs_leaders"]
    out.append(
        Signal(
            "builders_vs_leaders",
            "Builders vs leaders",
            _fmt(c3, "+.1f", "% (3m)"),
            _status(c3, t["watch"], t["alert"], higher_is_worse=False),
            f"Levered builders ÷ Nvidia, Broadcom, AMD · 1m {_fmt(c1, '+.1f', '%')}",
        )
    )

    # 2. AI breadth
    b200 = _last(breadth(closes, ai_names, 200))
    b50 = _last(breadth(closes, ai_names, 50))
    t = th["ai_breadth"]
    out.append(
        Signal(
            "ai_breadth",
            "AI breadth",
            _fmt(b200, ".0f", "% > 200d"),
            _status(b200, t["watch"], t["alert"], higher_is_worse=False),
            f"Share of the 20 AI names above their 200-day average · above 50-day: {_fmt(b50, '.0f', '%')}",
        )
    )

    # 3. Equal-weight vs cap-weight
    ew_cap = ratio(closes, "RSP", "SPY")
    c3 = change_since(ew_cap, months=3)
    nd = change_since(ratio(closes, "QQEW", "QQQ"), months=3)
    t = th["equal_vs_cap"]
    out.append(
        Signal(
            "equal_vs_cap",
            "Equal-weight vs cap-weight",
            _fmt(c3, "+.1f", "% (3m)"),
            _status(c3, t["watch"], t["alert"], higher_is_worse=False),
            f"RSP ÷ SPY; falling = leadership narrowing · Nasdaq-100 version {_fmt(nd, '+.1f', '%')}",
        )
    )

    # 4. Semis trend
    semis = ratio(closes, "SMH", "SPY")
    if len(semis.dropna()) >= 200:
        now, ma50, ma200 = (
            semis.iloc[-1],
            semis.rolling(50).mean().iloc[-1],
            semis.rolling(200).mean().iloc[-1],
        )
        if now > ma50 and ma50 > ma200:
            st_semis, desc = CALM, "above 50-day, 50-day above 200-day"
        elif now < ma200 and ma50 < ma200:
            st_semis, desc = ALERT, "below 200-day, 50-day below 200-day"
        else:
            st_semis, desc = WATCH, "mixed: trend weakening"
        val = f"{(now / ma200 - 1) * 100:+.1f}% vs 200d"
    else:
        st_semis, desc, val = NA, "not enough history", "—"
    out.append(Signal("semis_trend", "Semis trend", val, st_semis, f"SMH ÷ SPY {desc}"))

    # 5. Volatility
    vix = _last(closes["^VIX"]) if "^VIX" in closes.columns else float("nan")
    vix3m = _last(closes["^VIX3M"]) if "^VIX3M" in closes.columns else float("nan")
    vxn = _last(closes["^VXN"]) if "^VXN" in closes.columns else float("nan")
    term = vix / vix3m if np.isfinite(vix) and np.isfinite(vix3m) and vix3m else float("nan")
    st_vol = _worst(
        _status(vix, th["vix_level"]["watch"], th["vix_level"]["alert"], higher_is_worse=True),
        _status(term, th["vix_term"]["watch"], th["vix_term"]["alert"], higher_is_worse=True),
    )
    out.append(
        Signal(
            "volatility",
            "Volatility",
            f"VIX {_fmt(vix, '.1f')}",
            st_vol,
            f"VIX ÷ VIX3M {_fmt(term, '.2f')} (above 1 = stress) · VXN {_fmt(vxn, '.1f')}",
        )
    )

    # 6. High-yield credit (FRED)
    hy = fred.get("BAMLH0A0HYM2")
    if hy is not None and not _clean(hy).empty:
        lvl = _last(hy)
        chg_bp = _abs_change_since(hy, months=1) * 100.0
        st_hy = _worst(
            _status(
                chg_bp,
                th["hy_change_bp"]["watch"],
                th["hy_change_bp"]["alert"],
                higher_is_worse=True,
            ),
            _status(lvl, th["hy_level"]["watch"], th["hy_level"]["alert"], higher_is_worse=True),
        )
        ig = fred.get("BAMLC0A0CM")
        ig_txt = f" · IG {_last(ig):.2f}%" if ig is not None and not _clean(ig).empty else ""
        out.append(
            Signal(
                "hy_credit",
                "High-yield credit",
                f"{lvl:.2f}%",
                st_hy,
                f"HY spread over Treasuries · 1m {chg_bp:+.0f} bp{ig_txt}",
            )
        )
    else:
        out.append(
            Signal(
                "hy_credit", "High-yield credit", "—", NA, "FRED unavailable (needs FRED_API_KEY)"
            )
        )

    # 7. 10-year yield (FRED)
    tens = fred.get("DGS10")
    if tens is not None and not _clean(tens).empty:
        lvl = _last(tens)
        chg = _abs_change_since(tens, months=1) * 100.0
        t = th["ten_year"]
        out.append(
            Signal(
                "ten_year",
                "10-year yield",
                f"{lvl:.2f}%",
                _status(lvl, t["watch"], t["alert"], higher_is_worse=True),
                f"Raises the cost of every lease and SPV · 1m {chg:+.0f} bp",
            )
        )
    else:
        out.append(
            Signal("ten_year", "10-year yield", "—", NA, "FRED unavailable (needs FRED_API_KEY)")
        )

    # 8. Private-credit proxies
    pc = equal_weight_index(closes, PRIVATE_CREDIT)
    pc_dd = from_high(pc)
    t = th["private_credit"]
    names = [x for x in PRIVATE_CREDIT if x in closes.columns]
    out.append(
        Signal(
            "private_credit",
            "Private-credit proxies",
            _fmt(pc_dd, "+.1f", "% from high"),
            _status(pc_dd, t["watch"], t["alert"], higher_is_worse=False),
            f"Equal-weight {', '.join(names) or 'n/a'} · 1m {_fmt(change_since(pc, months=1), '+.1f', '%')}",
        )
    )

    # 9. Global equities from peak (rulebook deployment trigger)
    acwi = closes["ACWI"] if "ACWI" in closes.columns else pd.Series(dtype=float)
    dd = from_high(acwi)
    t = th["global_equities"]
    out.append(
        Signal(
            "global_equities",
            "Global equities from peak",
            _fmt(dd, "+.1f", "%"),
            _status(dd, t["watch"], t["alert"], higher_is_worse=False),
            "ACWI vs 52-week high · rulebook: deploy ⅓ of dry powder at −20%, another ⅓ at −30%",
        )
    )
    return out


def _abs_change_since(s: pd.Series, *, months: int) -> float:
    """Absolute (not %) change, for rates and spreads quoted in %."""
    s = _clean(s)
    if len(s) < 2:
        return float("nan")
    base = s.loc[: s.index[-1] - pd.DateOffset(months=months)]
    return float(s.iloc[-1] - base.iloc[-1]) if not base.empty else float("nan")


def summarize(signals: list[Signal]) -> dict[str, int]:
    counts = {ALERT: 0, WATCH: 0, CALM: 0, NA: 0}
    for s in signals:
        counts[s.status] += 1
    return counts


def group_indices(closes: pd.DataFrame, *, start=None) -> pd.DataFrame:
    """Equal-weight index per watchlist group (excluding Reference), rebased to 100."""
    groups: dict[str, list[str]] = {}
    for st in STOCKS:
        if st.group != "Reference":
            groups.setdefault(st.group, []).append(st.ticker)
    frames = {g: equal_weight_index(closes, tick, start=start) for g, tick in groups.items()}
    df = pd.DataFrame({g: s for g, s in frames.items() if not s.empty})
    if df.empty:
        return df
    df = df.dropna()
    return 100.0 * df / df.iloc[0]
