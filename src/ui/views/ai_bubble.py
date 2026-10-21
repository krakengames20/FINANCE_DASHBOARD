"""AI Bubble tab: daily monitor for the AI trade, built from the FINANCE
project's dot-com comparison.

Sections: signal tiles (CALM / WATCH / ALERT), the 20-stock watchlist table,
four market charts (builders vs leaders, group performance, 1-month moves, breadth),
and the catalyst countdown. Prices come from Yahoo Finance (delayed); credit
and rates from FRED via the existing client. Each section is isolated, so a
failure in one shows a note instead of breaking the page.
"""

from __future__ import annotations

import datetime as dt
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data import ai_watchlist as wl
from src.data.market_prices import fetch_fundamentals, fetch_market_data
from src.models import ai_bubble as ab
from src.ui.components import apply_template, line_chart, signed_bar
from src.ui.glossary import chart_help, info_icon_html
from src.ui.theme import PALETTE

STATUS_COLOR = {
    ab.CALM: PALETTE["risk_low"],
    ab.WATCH: PALETTE["risk_elevated"],
    ab.ALERT: PALETTE["risk_critical"],
    ab.NA: PALETTE["text_muted"],
}
GROUP_COLOR = {
    "Levered builders": PALETTE["risk_critical"],
    "Chips & hardware": PALETTE["accent"],
    "Power & grid": PALETTE["risk_low"],
    "Platforms & labs": PALETTE["submodel"]["sentiment"],
}
_EVENT_STATUS = {"confirmed": "CONFIRMED", "reported": "REPORTED", "estimated": "EST."}


# ------------------------------------------------------------------ loading


def _load_fred() -> dict[str, pd.Series]:
    """Credit and rate series through the shared FRED client. Missing key or
    network = empty dict; the dependent signals then show N/A."""
    from src.data.fred_client import fetch_series

    out: dict[str, pd.Series] = {}
    for sid in wl.FRED_CREDIT:
        try:
            out[sid] = fetch_series(sid)
        except Exception:  # noqa: BLE001 - per-series failure is in the fetch log
            continue
    return out


def render() -> None:
    with st.spinner("Loading market prices…"):
        try:
            market = fetch_market_data(tuple(wl.all_tickers()))
        except Exception as exc:  # noqa: BLE001
            _unavailable(f"Price download failed: {type(exc).__name__}: {exc}")
            return
    if market.closes.empty:
        first = market.failed[0][1].split("(")[0].strip() if market.failed else "no response"
        _unavailable(f"No prices returned for {len(market.failed)} tickers. First error: {first}.")
        return
    try:
        fundamentals, fund_status = fetch_fundamentals(tuple(s.ticker for s in wl.STOCKS))
    except Exception as exc:  # noqa: BLE001
        fundamentals, fund_status = {}, f"P/E unavailable ({type(exc).__name__})"
    fred = _load_fred()

    closes = market.closes
    _section(_row_header, market, fred)
    signals = _section(ab.evaluate_signals, closes, fred) or []
    _section(_row_signals, signals)
    _section(_row_table, closes, fundamentals, fund_status)
    _section(_row_charts_top, closes)
    _section(_row_charts_bottom, closes)
    _section(_row_events)
    _section(_row_feed_status, market, fund_status, fred)
    _footnote()


def _section(fn, *args):
    """Run one section; on error show a muted note and keep rendering."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        _note(f"This section could not be drawn ({type(exc).__name__}: {escape(str(exc))[:160]}).")
        return None


# ------------------------------------------------------------------- header


def _row_header(market, fred) -> None:
    # Most common last-trading date across tickers: Tokyo closes a day ahead of
    # New York, so the overall max date would overstate how fresh US prices are.
    last_dates = market.closes.apply(lambda c: c.last_valid_index()).dropna()
    last = (
        pd.Timestamp(last_dates.mode().iloc[0])
        if not last_dates.empty
        else market.closes.index.max()
    )
    fetched = market.fetched_at.strftime("%H:%M") if market.fetched_at else "—"
    credit = "credit &amp; rates: FRED" if fred else "credit &amp; rates: FRED unavailable"
    st.markdown(
        '<div class="label-small" style="margin-top:8px;">'
        f"AI bubble monitor · prices to {last:%d %b %Y} · Yahoo Finance (delayed ~15 min) · "
        f"fetched {fetched} · {credit}</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ signals


def _row_signals(signals: list[ab.Signal]) -> None:
    counts = ab.summarize(signals)
    if counts[ab.ALERT]:
        worst = ab.ALERT
    elif counts[ab.WATCH]:
        worst = ab.WATCH
    elif counts[ab.CALM]:
        worst = ab.CALM
    else:
        worst = ab.NA
    color = STATUS_COLOR[worst]
    parts = " · ".join(
        f'<span style="color:{STATUS_COLOR[k]};">{counts[k]} {k}</span>'
        for k in (ab.ALERT, ab.WATCH, ab.CALM)
        if counts[k]
    )
    na = (
        f' · <span style="color:{PALETTE["text_muted"]};">{counts[ab.NA]} N/A</span>'
        if counts[ab.NA]
        else ""
    )
    st.markdown(
        f'<div class="panel" style="margin-top:8px;"><div class="panel-header">'
        f"<span>AI bubble signals{info_icon_html('AI bubble signals')}</span>"
        f'<span class="risk-badge" style="color:{color};">{worst}</span>'
        f'</div><div class="panel-body"><div class="data-font" style="font-size:20px;">{parts}{na}</div>'
        f'<div class="metric-sub" style="text-transform:none;letter-spacing:0.02em;">'
        "Read top-left to bottom-right: the 2000 sequence ran builders → breadth → leadership → "
        "suppliers → volatility → credit → rates → lenders → the whole market.</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    for i in range(0, len(signals), 3):
        cols = st.columns(3)
        for col, sig in zip(cols, signals[i : i + 3]):
            with col:
                st.markdown(_signal_tile(sig), unsafe_allow_html=True)


def _signal_tile(sig: ab.Signal) -> str:
    c = STATUS_COLOR[sig.status]
    # Single line: Streamlit treats indented HTML lines as code blocks.
    return (
        f'<div class="panel" style="height:100%;">'
        f'<div class="panel-header"><span>{escape(sig.name)}{info_icon_html(sig.name)}</span>'
        f'<span class="risk-badge" style="color:{c};">{sig.status}</span></div>'
        f'<div class="panel-body"><div class="data-font" style="font-size:22px;color:{c};">'
        f"{escape(sig.value)}</div>"
        f'<div class="metric-sub" style="text-transform:none;letter-spacing:0.02em;line-height:1.5;">'
        f"{escape(sig.detail)}</div></div></div>"
    )


# -------------------------------------------------------------------- table

_SORTS = {
    "Watchlist order": None,
    "Trailing P/E (high first)": ("P/E trailing", False),
    "Today %": ("Today %", True),
    "1m % (worst first)": ("1m %", True),
    "From 52w high (worst first)": ("From 52w high %", True),
    "Risk (high first)": ("Risk", False),
}
_PCT_COLS = ["Today %", "7d %", "1m %"]


def _row_table(closes: pd.DataFrame, fundamentals: dict, fund_status: str) -> None:
    table = ab.stock_table(closes, fundamentals)
    table["Risk"] = pd.to_numeric(table["Risk"], errors="coerce")

    st.markdown(
        f'<div class="label-small" style="margin-top:16px;">AI stocks{info_icon_html("AI stocks")}'
        f" · {len(wl.ai_basket())} names + reference rows</div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns([3, 1])
    with left:
        group = (
            st.segmented_control(
                "Group",
                ["All", *wl.GROUPS],
                default="All",
                key="ai_group",
                label_visibility="collapsed",
            )
            or "All"
        )
    with right:
        sort = st.selectbox("Sort", list(_SORTS), key="ai_sort", label_visibility="collapsed")

    view = table if group == "All" else table[table["Group"] == group]
    spec = _SORTS[sort]
    if spec is not None:
        col, asc = spec
        # Loss-makers (no P/E) first when sorting by P/E: they carry the most valuation risk.
        if col == "P/E trailing":
            view = (
                view.assign(_loss=view[col].isna())
                .sort_values(
                    ["_loss", col],
                    ascending=[False, asc],
                    na_position="first",
                )
                .drop(columns="_loss")
            )
        else:
            view = view.sort_values(col, ascending=asc, na_position="last")

    show = view.drop(columns=["Group"]) if group != "All" else view
    st.dataframe(
        _style(show),
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(show), 980),
        column_config={
            "Why exposed": st.column_config.TextColumn(width="large"),
            "Name": st.column_config.TextColumn(width="medium"),
            "Price": st.column_config.TextColumn(width=95),
            "From 52w high %": st.column_config.TextColumn("vs 52w high", width=115),
        },
    )
    st.caption(
        "Today % = vs previous close · 7d and 1m = calendar days · From 52w high = vs highest close "
        f"in the last 365 days · P/E: {fund_status}; — = loss-making or not meaningful · "
        "Risk = damage in a lab shock, 1–10 (risk map)."
    )


def _style(df: pd.DataFrame):
    pos, neg = PALETTE["risk_low"], PALETTE["risk_high"]

    def pct_color(v):
        if pd.isna(v) or v == 0:
            return ""
        return f"color: {pos}" if v > 0 else f"color: {neg}"

    def high_color(v):
        if pd.isna(v):
            return ""
        if v <= -30:
            return f"color: {PALETTE['risk_critical']}"
        if v <= -15:
            return f"color: {PALETTE['risk_elevated']}"
        return f"color: {PALETTE['text_muted']}"

    def risk_color(v):
        if pd.isna(v):
            return ""
        if v >= 9:
            return f"color: {PALETTE['risk_critical']}; font-weight: 600"
        if v >= 8:
            return f"color: {PALETTE['risk_high']}"
        if v >= 7:
            return f"color: {PALETTE['risk_elevated']}"
        return f"color: {PALETTE['text_muted']}"

    fmt = {
        "Price": "{:,.2f}",
        "Today %": "{:+.2f}%",
        "7d %": "{:+.1f}%",
        "1m %": "{:+.1f}%",
        "From 52w high %": "{:+.1f}%",
        "P/E trailing": "{:.0f}×",
        "P/E forward": "{:.0f}×",
        "Risk": "{:.0f}",
    }
    # Pre-format to strings: st.dataframe shows nulls as "None" and ignores the
    # Styler's na_rep. Rows are already sorted numerically before this point.
    disp = df.copy()
    for col, spec in fmt.items():
        if col in disp.columns:
            disp[col] = [spec.format(v) if pd.notna(v) else "—" for v in df[col]]
    if "Data date" in disp.columns:
        disp["Data date"] = [
            d.strftime("%d %b") if d is not None and not pd.isna(d) else "—"
            for d in df["Data date"]
        ]

    def colored(fn):
        return lambda col: [fn(v) for v in df[col.name]]

    sty = disp.style
    pct = [c for c in _PCT_COLS if c in disp.columns]
    if pct:
        sty = sty.apply(colored(pct_color), subset=pct)
    if "From 52w high %" in disp.columns:
        sty = sty.apply(colored(high_color), subset=["From 52w high %"])
    if "Risk" in disp.columns:
        sty = sty.apply(colored(risk_color), subset=["Risk"])
    return sty


# ------------------------------------------------------------------- charts


def _one_year(s: pd.Series | pd.DataFrame):
    if s is None or len(s) == 0:
        return s
    return s.loc[s.index.max() - pd.DateOffset(years=1) :]


def _row_charts_top(closes: pd.DataFrame) -> None:
    left, right = st.columns(2)
    with left:
        st.markdown(
            '<div class="label-small" style="margin-top:16px;">Builders vs leaders · 12 months</div>',
            unsafe_allow_html=True,
        )
        r = ab.builders_vs_leaders(closes)
        r = _one_year(r)
        if r is None or r.dropna().empty:
            _note("Not enough price history for the builders/leaders ratio.")
        else:
            r = 100.0 * r / r.iloc[0]
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=r.index,
                    y=r.values,
                    mode="lines",
                    name="Builders ÷ leaders",
                    line=dict(color=PALETTE["risk_critical"], width=1.6),
                    hovertemplate="%{x|%d %b %Y}<br>%{y:.1f}<extra></extra>",
                )
            )
            ma = r.rolling(50).mean()
            fig.add_trace(
                go.Scatter(
                    x=ma.index,
                    y=ma.values,
                    mode="lines",
                    name="50-day average",
                    line=dict(color=PALETTE["text_muted"], width=1, dash="dot"),
                    hovertemplate="%{x|%d %b %Y}<br>%{y:.1f}<extra></extra>",
                )
            )
            fig.add_hline(y=100, line=dict(color="#3d4754", width=1, dash="dot"))
            fig.update_yaxes(title="rebased to 100")
            apply_template(fig, height=300)
            fig.update_layout(legend=dict(orientation="h", y=1.08, x=0))
            st.plotly_chart(fig, use_container_width=True)
            chart_help("ai.builders_leaders")
    with right:
        st.markdown(
            '<div class="label-small" style="margin-top:16px;">Groups · equal-weight · 12 months</div>',
            unsafe_allow_html=True,
        )
        start = closes.index.max() - pd.DateOffset(years=1)
        g = ab.group_indices(closes, start=start)
        if g.empty:
            _note("Not enough price history for the group indices.")
        else:
            fig = line_chart(g, color=GROUP_COLOR, height=300, yaxis_title="rebased to 100")
            fig.update_traces(hovertemplate="%{x|%d %b %Y}<br>%{y:.1f}<extra></extra>")
            fig.add_hline(y=100, line=dict(color="#3d4754", width=1, dash="dot"))
            fig.update_layout(legend=dict(orientation="h", y=1.08, x=0))
            st.plotly_chart(fig, use_container_width=True)
            chart_help("ai.groups")


def _row_charts_bottom(closes: pd.DataFrame) -> None:
    left, right = st.columns(2)
    names = {s.ticker: s.name for s in wl.STOCKS}
    with left:
        st.markdown(
            '<div class="label-small" style="margin-top:16px;">1-month change · 20 AI names</div>',
            unsafe_allow_html=True,
        )
        moves = (
            pd.Series(
                {
                    f"{t} · {names[t]}": ab.change_since(closes[t], months=1)
                    for t in wl.ai_basket()
                    if t in closes.columns
                }
            )
            .dropna()
            .sort_values()
        )
        if moves.empty:
            _note("No 1-month changes available.")
        else:
            fig = signed_bar(moves, height=520, xaxis_title="% change over 1 month")
            fig.update_traces(hovertemplate="%{y}: %{x:+.1f}%<extra></extra>")
            st.plotly_chart(fig, use_container_width=True)
            chart_help("ai.month_moves")
    with right:
        st.markdown(
            '<div class="label-small" style="margin-top:16px;">AI breadth · 12 months</div>',
            unsafe_allow_html=True,
        )
        basket = wl.ai_basket()
        b = pd.concat(
            {
                "Above 200-day": ab.breadth(closes, basket, 200),
                "Above 50-day": ab.breadth(closes, basket, 50),
            },
            axis=1,
            sort=True,
        )
        b = _one_year(b.dropna(how="all"))
        if b is None or b.empty:
            _note("Not enough price history for breadth.")
        else:
            fig = line_chart(
                b,
                color={"Above 200-day": PALETTE["accent"], "Above 50-day": PALETTE["text_muted"]},
                height=520,
                yaxis_title="% of the 20 AI names",
            )
            fig.update_traces(hovertemplate="%{x|%d %b %Y}<br>%{y:.0f}%<extra></extra>")
            th = ab.THRESHOLDS["ai_breadth"]
            for y, c in (
                (th["watch"], PALETTE["risk_elevated"]),
                (th["alert"], PALETTE["risk_critical"]),
            ):
                fig.add_hline(y=y, line=dict(color=c, width=1, dash="dash"))
            fig.update_yaxes(range=[0, 100])
            fig.update_layout(legend=dict(orientation="h", y=1.04, x=0))
            st.plotly_chart(fig, use_container_width=True)
            chart_help("ai.breadth")


# ------------------------------------------------------------------- events


def _row_events() -> None:
    today = dt.date.today()
    events = wl.upcoming_events(today, limit=10)
    st.markdown(
        f'<div class="label-small" style="margin-top:16px;">'
        f"Upcoming catalysts{info_icon_html('Upcoming catalysts')}</div>",
        unsafe_allow_html=True,
    )
    if not events:
        _note("No upcoming events in the watchlist. Add dates in src/data/ai_watchlist.py.")
        return
    rows = []
    for e in events:
        days = (e.date - today).days
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        hot = "anthropic" in e.label.lower()
        color = PALETTE["accent"] if hot else PALETTE["text_primary"]
        status_c = PALETTE["risk_low"] if e.status == "confirmed" else PALETTE["text_muted"]
        rows.append(
            f'<div class="submodel-row"><span class="name" style="min-width:110px;">{e.date:%a %d %b}</span>'
            f'<span class="value" style="min-width:90px;color:{PALETTE["text_muted"]};">{when}</span>'
            f'<span class="value" style="flex:1;color:{color};padding:0 12px;">{escape(e.label)}</span>'
            f'<span class="name" style="color:{status_c};">{_EVENT_STATUS.get(e.status, e.status)}</span></div>'
        )
    st.markdown(
        f'<div class="panel"><div class="panel-body">{"".join(rows)}</div></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Estimated dates are best guesses and move as companies confirm. "
        "Edit them in src/data/ai_watchlist.py. An Anthropic price tracker switches on at listing."
    )


# --------------------------------------------------------------- feed status


def _row_feed_status(market, fund_status: str, fred: dict) -> None:
    failed = market.failed
    label = (
        f"Price feed · {len(market.ok)} of {len(market.log)} tickers loaded"
        + (f" · {len(failed)} failed" if failed else "")
        + f" · {fund_status}"
        + f" · FRED {len(fred)}/{len(wl.FRED_CREDIT)}"
    )
    with st.expander(("⚠ " if failed else "") + label):
        st.caption(
            "Prices are cached for 1 hour and P/E for 6 hours; ↻ Refresh data at the top clears both. "
            "Yahoo Finance is an unofficial, delayed source: fine for monitoring, not for trading."
        )
        st.dataframe(
            pd.DataFrame(market.log, columns=["Ticker", "Status", "Detail"]),
            hide_index=True,
            width="stretch",
        )


# ------------------------------------------------------------------- helpers


def _footnote() -> None:
    st.markdown(
        f'<div class="panel" style="margin-top:16px;"><div class="panel-body" '
        f'style="font-size:12px;color:{PALETTE["text_muted"]};line-height:1.6;">'
        "<p><b>What this tab is.</b> A daily check on whether the AI trade is following the "
        "2000–02 pattern: the debt-funded builders break first, breadth and leadership narrow, the "
        "suppliers reset, then stress spreads to volatility, credit, rates and the lenders behind "
        "the data centres.</p>"
        "<p><b>Honest scope.</b> Thresholds are judgement calls, kept in one place "
        "(<code>THRESHOLDS</code> in src/models/ai_bubble.py). Private-credit marks, CDS and GPU "
        "rental prices have no free daily feed, so listed proxies stand in. The scenario odds and "
        "rulebook lights come in the next phase.</p>"
        "<p>Performance uses daily closing-price returns, excluding dividends. The private-credit "
        "proxy blends local-currency returns (including SoftBank in JPY), rather than a USD "
        "portfolio return. Risk scores and exposure notes are manually maintained research; "
        "reported and estimated event dates require confirmation.</p>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _note(text: str) -> None:
    st.markdown(
        f'<div class="panel"><div class="panel-body" '
        f'style="font-size:12px;color:{PALETTE["text_muted"]};">{text}</div></div>',
        unsafe_allow_html=True,
    )


def _unavailable(reason: str) -> None:
    st.markdown(
        '<div class="label-small" style="margin-top:8px;">AI bubble monitor</div>',
        unsafe_allow_html=True,
    )
    _note(
        "Market prices could not be loaded, so this tab is empty. The rest of the dashboard is "
        f"unaffected. Check your internet connection, then use ↻ Refresh data.<br><br>{escape(reason)}"
    )
