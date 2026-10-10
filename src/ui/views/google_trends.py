"""On-demand Google search-interest panel, shared with the standalone sidecar."""

from __future__ import annotations

import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from src.data.google_trends import CACHE_TTL, REGIONS, WINDOWS, TrendsError, TrendsQuery, TrendsResult
from src.data.google_trends import build_query, fetch_interest
from src.ui.components import apply_template
from src.ui.glossary import chart_help
from src.ui.theme import PALETTE

COOLDOWN = 30


def _load(query: TrendsQuery) -> TrendsResult:
    # The shared disk cache checks age against the original fetch time. A second
    # cache here could extend the effective lifetime of an almost-expired result.
    return fetch_interest(query)


def interest_chart(result: TrendsResult) -> go.Figure:
    colors = [PALETTE["accent"], PALETTE["risk_low"], PALETTE["risk_high"],
              PALETTE["submodel"]["sentiment"], PALETTE["text_primary"]]
    fig = go.Figure()
    for term, color in zip(result.query.terms, colors):
        values = result.values[term]
        status = ["Partial period" if p else "Complete period" for p in result.partial]
        fig.add_trace(go.Scatter(
            x=values.index, y=values, name=term, mode="lines",
            line=dict(color=color, width=2), connectgaps=False, customdata=status,
            hovertemplate="%{x|%d %b %Y %H:%M UTC}<br>Interest: %{y:.0f}<br>%{customdata}<extra>%{fullData.name}</extra>",
        ))
        partial_values = values[result.partial & values.notna()]
        if not partial_values.empty:
            fig.add_trace(go.Scatter(
                x=partial_values.index, y=partial_values, mode="markers", name=term,
                marker=dict(color=color, size=8, symbol="circle-open"), showlegend=False,
                hovertemplate="%{x|%d %b %Y %H:%M UTC}<br>Interest: %{y:.0f}<br>Partial period<extra>%{fullData.name}</extra>",
            ))
    apply_template(fig, height=370)
    fig.update_layout(legend=dict(orientation="h", y=1.12, x=0), hovermode="x unified")
    fig.update_yaxes(title="Search interest (0–100)", range=[0, 105])
    fig.update_xaxes(title=None)
    return fig


@st.fragment
def render() -> None:
    """Only explicit submission fetches data; editing controls keeps the last chart."""
    st.markdown("#### Google Trends · search attention")
    st.caption("Compare search interest in AI companies, products, or phrases.")
    with st.form("ai_trends_form"):
        terms = st.text_input(
            "Search terms", value="ChatGPT, Claude, Gemini", max_chars=510,
            placeholder="ChatGPT, Claude, Gemini, AI bubble",
            help="Up to five terms, separated by commas. Phrases are searched as terms, not Google Topics.",
            key="ai_trends_terms",
        )
        left, right = st.columns([2, 1])
        with left:
            window = st.segmented_control("Rolling window", list(WINDOWS), default="1 year", key="ai_trends_window")
        with right:
            region = st.selectbox("Region", list(REGIONS), key="ai_trends_region")
        submitted = st.form_submit_button("Fetch trends", type="primary")

    if submitted:
        try:
            query = build_query(terms, window or "1 year", REGIONS[region])
        except ValueError as exc:
            st.session_state["ai_trends_error"] = str(exc)
        else:
            now = dt.datetime.now(dt.timezone.utc)
            attempts = st.session_state.get("ai_trends_attempts", {})
            last_attempt = attempts.get(query)
            if last_attempt and (now - last_attempt).total_seconds() < COOLDOWN:
                st.session_state["ai_trends_error"] = "Please wait 30 seconds between fetches."
            else:
                st.session_state["ai_trends_requested"] = query
                try:
                    with st.spinner("Fetching Google search interest…"):
                        result = _load(query)
                except TrendsError as exc:
                    attempts[query] = now
                    st.session_state["ai_trends_attempts"] = attempts
                    st.session_state["ai_trends_error"] = str(exc)
                else:
                    attempts.pop(query, None)
                    st.session_state["ai_trends_attempts"] = attempts
                    st.session_state["ai_trends_result"] = result
                    st.session_state.pop("ai_trends_error", None)

    error = st.session_state.get("ai_trends_error")
    if error:
        st.warning(error)
        if st.session_state.get("ai_trends_result") is not None:
            st.caption("The previous successful result remains below; it has not been updated.")
    result = st.session_state.get("ai_trends_result")
    if result is None:
        st.info("Enter terms and choose a window, then fetch to draw the graph.")
        query = st.session_state.get("ai_trends_requested")
        if query is not None:
            st.link_button("Open this query in Google Trends", query.explore_url)
        return

    if result.warning:
        st.warning(result.warning)
    region_name = next((k for k, v in REGIONS.items() if v == result.query.geo), result.query.geo)
    st.markdown(f"**{result.query.window} · {region_name}** — " + ", ".join(result.query.terms))
    st.plotly_chart(interest_chart(result), width="stretch", key="ai_trends_chart")
    chart_help("ai.search_attention")
    # Date range is the actual returned coverage, not a promise of daily data.
    start, end = result.values.index.min(), result.values.index.max()
    resolution = ""
    if len(result.values) > 1:
        step = result.values.index.to_series().diff().median()
        resolution = "hourly" if step < dt.timedelta(days=1) else "daily" if step < dt.timedelta(days=7) else "weekly"
    stamp = result.fetched_at.strftime("%d %b %Y %H:%M UTC")
    age = dt.datetime.now(dt.timezone.utc) - result.fetched_at
    if age.total_seconds() > CACHE_TTL:
        st.caption("This retained result is over an hour old. Fetch again to update it.")
    st.caption(
        f"Google Trends · {len(result.values)} {resolution} observations · {start:%d %b %Y} to {end:%d %b %Y} "
        f"· fetched {stamp} · repeated queries cached for 1 hour."
    )
    st.caption(
        "100 is the peak relative search interest within this query; these are not search counts. "
        "Terms are scaled together. Changing the terms, region, or window rescales the scores, "
        "so separate queries are not directly comparable. Zero can mean too little search volume. "
        "Open circles mark unfinished periods; gaps mean unavailable data."
    )
    left, right = st.columns(2)
    with left:
        st.download_button(
            "Download CSV", result.csv_bytes(),
            file_name="google_trends.csv", mime="text/csv", key="ai_trends_download",
        )
    with right:
        st.link_button("Open in Google Trends", result.query.explore_url)
