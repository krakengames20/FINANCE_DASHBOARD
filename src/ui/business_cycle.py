"""Plain-language overview, placed before the detailed dashboard metrics."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.models.business_cycle import business_cycle_overview
from src.ui.theme import PALETTE


def render(panel: pd.DataFrame) -> None:
    from src.data.fred_client import fetch_series
    from src.data.gdp import fetch_gdp_bundle
    from src.models.recession_probit import OBS_START

    # These exact series/arguments are already used by Growth and the probit
    # loader. Reuse their caches rather than add a feed or change a model.
    try:
        headline = fetch_gdp_bundle().get("headline", {})
    except Exception:
        headline = {}
    try:
        core_prices = fetch_series("PCEPILFE", OBS_START)
    except Exception:
        core_prices = None
    report = business_cycle_overview(panel, headline, core_prices)
    render_report(report)


def render_report(report: dict) -> None:
    st.markdown("### Business cycle at a glance")
    st.write(report["summary"])
    st.caption("Start here: the state of activity, its speed, how widely weakness is spreading, and the pace of price rises. Each answer uses the date shown.")
    colors = {"positive": PALETTE["risk_low"], "caution": PALETTE["risk_elevated"], "neutral": PALETTE["text_primary"]}
    for col, card in zip(st.columns(4), report["cards"]):
        with col:
            date = f"Evidence through {card['date']}" if card["date"] else "Current comparison unavailable"
            st.markdown(
                '<div class="panel"><div class="panel-body">'
                f'<div style="font-size:13px;min-height:40px;">{escape(card["question"])}</div>'
                f'<div class="display-font" style="font-size:25px;margin:12px 0;color:{colors[card["severity"]]};">{escape(card["answer"])}</div>'
                f'<div style="font-size:12px;line-height:1.7;">{escape(card["explanation"])}</div>'
                f'<div style="font-size:11px;margin-top:14px;color:{PALETTE["text_muted"]};">{escape(date)}</div>'
                '</div></div>', unsafe_allow_html=True,
            )
    for note in report["notes"]:
        st.write(note)
    st.caption("This describes published evidence. It is not an official recession declaration or a forecast; the recession-risk model appears separately below.")
    with st.expander("Why these answers? See the evidence and reading guide"):
        for card in report["cards"]:
            st.markdown(f"**{card['question']} — {card['answer']}**")
            for line in card["evidence"] or [card["explanation"]]:
                st.write(line)
        st.markdown(
            "**How to read this**\n\n"
            "Growing means output increased; accelerating means its growth rate increased. "
            "Below-trend activity can still be growing. Inflation easing usually means prices rise more slowly.\n\n"
            "An annual rate shows what the pace would look like if it lasted a year; it is not a prediction. "
            "The GDP comparison uses consecutive reported quarters. The monthly activity and breadth comparisons use three months. "
            "The inflation comparison uses two consecutive three-month periods. Different dates can explain disagreements.\n\n"
            "**Label conventions:** changes within 0.5 percentage points for annualized GDP growth, 0.10 points for the monthly activity average, "
            "0.05 points for activity diffusion, and 0.25 percentage points for annualized core inflation are called little change. "
            "These are descriptive choices, not tests of statistical significance. Activity diffusion at or below −0.35 is described as widespread weakness. "
            "Monthly readings older than 90 days after their month ends, or GDP older than 140 days after its quarter ends, are withheld. "
            "Missing comparison periods are not filled. Published data can be revised.\n\n"
            "Sources: [BEA quarterly growth](https://www.bea.gov/help/faq/122), "
            "[Chicago Fed activity and diffusion](https://www.chicagofed.org/research/data/cfnai/current-data), "
            "[core consumer prices via FRED](https://fred.stlouisfed.org/series/PCEPILFE)."
        )
        growth, breadth = st.columns(2)
        with growth:
            if st.button("Explore growth evidence", key="cycle_growth"):
                st.session_state.pending_nav = "Growth"
                st.rerun()
        with breadth:
            if st.button("Explore breadth evidence", key="cycle_breadth"):
                st.session_state.pending_nav = "Pulse"
                st.rerun()
