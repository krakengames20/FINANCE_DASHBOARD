"""Offline tests: every on-screen card label and chart has an explanation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ui import glossary

VIEWS = Path(__file__).resolve().parents[1] / "src" / "ui" / "views"

# Card / panel labels as rendered (captured from a full render of every tab).
RENDERED_LABELS = [
    "Composite Risk",
    "Probability a new recession starts within 12 months",
    "Probability a new recession starts within 12 months · 4-model ensemble",
    "Labor Composite", "10Y − 3M Spread", "10Y − 3M", "10Y − 2Y", "5Y − 2Y",
    "Financial Conditions", "Adjusted Financial Conditions", "Financial Stress",
    "Economic Activity (3-mo)", "Shiller CAPE", "Implied 10y real return",
    "GDPNow nowcast", "Credit-stress composite", "Activity Diffusion (CFNAI)",
    "Labor breadth · below trend", "Labor momentum · deteriorating", "Sahm Rule",
    "Wage growth (median)", "SOFR", "Fed Funds (EFFR)", "1M T-Bill (DGS1MO)",
    "4-model ensemble", "NY Fed", "Wright", "BIC-selected", "Estrella-Mishkin",
    "Chauvet-Piger", "BIC model · this scenario",
    # early-warning ladder rungs
    "Yield-curve inversion (10y–3m)", "Bank lending standards (SLOOS)",
    "Housing permits (YoY)", "Labor: Sahm rule", "Recession-start ensemble (12-mo)",
    "Labor breadth below trend", "Financial conditions (NFCI)", "Acute stress: VIX",
    # AI Bubble tab
    "AI bubble signals", "AI stocks", "Upcoming catalysts",
]


def test_every_ai_signal_has_help():
    import pandas as pd

    from src.models.ai_bubble import evaluate_signals

    for sig in evaluate_signals(pd.DataFrame()):
        h = glossary.indicator_help(sig.name)
        assert h is not None, sig.name
        assert h["what"] and h["high"] and h["low"]


@pytest.mark.parametrize("label", RENDERED_LABELS)
def test_every_rendered_label_has_help(label):
    h = glossary.indicator_help(label)
    assert h is not None, label
    assert h["what"] and h["high"] and h["low"]


def test_market_implied_rows_have_help():
    from src.models.market_implied import MARKET_IMPLIED_SIGNALS

    for _sid, label, _unit, _fmt in MARKET_IMPLIED_SIGNALS:
        assert glossary.indicator_help(label) is not None, label


def test_dash_variants_match():
    assert glossary.indicator_help("10Y - 3M") is glossary.indicator_help("10Y − 3M")
    assert glossary.indicator_help("Estrella–Mishkin") is not None


def test_treasury_cards_fall_back_to_generic():
    assert glossary.indicator_help("10Y Treasury") is not None


def test_unknown_label_has_no_icon():
    assert glossary.indicator_help("Not a real indicator") is None
    assert glossary.info_icon_html("Not a real indicator") == ""


def test_icon_html_escapes_and_aligns():
    html = glossary.info_icon_html("Sahm Rule")
    assert 'class="info-tip"' in html and "▲ High" in html
    assert "tip-left" in glossary.info_icon_html("Sahm Rule", align="left")
    assert "<script" not in html


def test_every_chart_help_id_exists():
    used = set()
    for path in VIEWS.glob("*.py"):
        used |= set(re.findall(r'chart_help\("([^"]+)"\)', path.read_text(encoding="utf-8")))
    assert used, "no chart_help calls found"
    missing = used - set(glossary.CHARTS)
    assert not missing, missing


def test_every_chart_has_a_note():
    """Each st.plotly_chart in the views is followed by a chart_help call.
    The Methodology tab is itself the long-form explanation, so it's exempt."""
    for path in VIEWS.glob("*.py"):
        if path.name == "methodology.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "st.plotly_chart(" in line:
                assert i + 1 < len(lines) and "chart_help(" in lines[i + 1], f"{path.name}:{i + 1}"
