"""Macro Dashboard — Streamlit entry point."""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

from src.data.fred_client import fetch_panel
from src.data.nber import load_recession_flags
from src.data.series_registry import fred_ids
from src.models.composite import composite_risk
from src.models.lame import LAME
from src.models.recession_probit import compute_probit_report
from src.models.yield_curve import YieldCurve
from src.ui.glossary import info_icon_html
from src.ui.theme import PALETTE, inject_theme, risk_color
from src.ui.views import ai_bubble, credit, curve, dashboard, early_warning, growth, methodology, pulse, rate_path, recession
from src.ui.views import lame as lame_view


st.set_page_config(
    page_title="U.S. Macro Dashboard",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

NAV_OPTIONS = ["Macro Dashboard", "Early Warning", "Recession", "Yield Curve", "Credit", "Labor", "Growth", "Pulse", "Policy Path", "AI Bubble", "Methodology"]

inject_theme()


# --------------------------------------------------------------------- caching


@st.cache_data(ttl=21600, show_spinner=False)
def _load_panel(cache_version: str) -> pd.DataFrame:
    # cache_version participates in the key so adding a series to the registry
    # (e.g. CFNAIDIFF) forces a refetch instead of serving a stale panel.
    return fetch_panel(fred_ids(), start="1959-01-01")


@st.cache_data(ttl=21600, show_spinner=False)
def _load_nber() -> pd.Series:
    # Prefer FRED USREC (live, auto-updating); falls back to the bundled CSV.
    return load_recession_flags()


@st.cache_data(ttl=21600, show_spinner=False)
def _load_market_prob() -> pd.DataFrame:
    # Atlanta Fed Market Probability Tracker — a bundled CSV export (the source
    # blocks automated fetching). Returns empty on any error so the rest of the
    # dashboard still renders.
    from src.data.market_probability import load_market_probabilities

    try:
        return load_market_probabilities()
    except Exception:
        return pd.DataFrame()


def _warm_secondary_loaders() -> None:
    """Fetch the Credit and Growth tab series up front so the data-status line
    covers every FRED series, not just the ones behind tabs already opened.
    Same default arguments as the views, so they share the cache entries."""
    from src.data import credit, gdp

    for fn in (credit.credit_stress, credit.fetch_liquidity, credit.fetch_clo,
               credit.fetch_household, gdp.fetch_gdp_bundle, gdp.coincident_factor):
        try:
            fn()
        except Exception:  # noqa: BLE001 - per-series failures are in the fetch log
            pass


# ttl matches the data caches: without it the fitted models (and the panel they
# hold) were kept until the server restarted, so the headline never refreshed.
@st.cache_resource(ttl=21600, show_spinner=False)
def _build_models(cache_version: str) -> dict:
    """Build the labor and yield-curve models independently of the probit report.

    ``cache_version`` participates in Streamlit's resource cache key — bump
    it whenever model or class code changes, otherwise the *old* instance
    keeps being served (cache_resource hashes function source, not its
    imported dependencies). The argument deliberately has no underscore
    prefix: Streamlit skips underscore-prefixed args when computing the
    cache key, which silently neutralises any value you pass.
    """
    panel = _load_panel(cache_version)
    nber = _load_nber()

    lame = LAME()
    lame.compute(panel)

    yc = YieldCurve(panel)

    _warm_secondary_loaders()

    return {
        "lame": lame,
        "yield_curve": yc,
        "panel": panel,
        "nber": nber,
    }


@st.cache_resource(ttl=21600, show_spinner=False)
def _load_probit_report(cache_version: str) -> dict:
    """Cache successful reports only; a failed calculation is retried on rerun."""
    report = compute_probit_report()
    if "error" in report:
        raise RuntimeError(report["error"])
    probability = report.get("ensemble_probability")
    if probability is None or not math.isfinite(float(probability)):
        raise RuntimeError("The recession model returned a non-finite probability.")
    return report


# ------------------------------------------------------------------------- run


def _probit_ensemble_now(models: dict) -> float:
    """Headline probability (from the four-model probit ensemble) that a new
    recession starts within 12 months."""
    probit = models.get("probit") or {}
    if not probit or "error" in probit:
        return float("nan")
    return float(probit.get("ensemble_probability", float("nan")))


def _recession_view(models: dict) -> tuple[dict, pd.DataFrame]:
    """Adapt the probit report into the ``current`` / ``history`` shape the
    dashboard cards expect (ensemble + per-model 'submodels' + history)."""
    probit = models.get("probit") or {}
    if not probit or "error" in probit:
        return {
            "ensemble": float("nan"), "submodels": {}, "drivers": {},
            "report_like": {"error": probit.get("error", "No recession report is available.")},
        }, pd.DataFrame()
    current = {
        "ensemble": probit["ensemble_probability"],
        "submodels": probit.get("model_probabilities", {}),
        "drivers": {},
        # Minimal report view for the headline-state logic + nowcast panel.
        "report_like": {
            "ensemble_probability": probit["ensemble_probability"],
            "recession_state": probit.get("recession_state", "expansion"),
            "nowcast": probit.get("nowcast") or {},
        },
    }
    history = pd.DataFrame({"ensemble": probit["ensemble_history"]})
    return current, history


def _composite_now(models: dict) -> dict:
    panel = models["panel"]
    ensemble_now = _probit_ensemble_now(models)
    lame_hist = models["lame"].history()
    lame_now = float(lame_hist.iloc[-1]) if not lame_hist.empty else float("nan")
    spreads = models["yield_curve"].spreads_history()
    curve_now = (
        float(spreads["spread_10y3m"].dropna().iloc[-1])
        if "spread_10y3m" in spreads.columns and not spreads["spread_10y3m"].dropna().empty
        else float("nan")
    )
    return composite_risk(ensemble_now, lame_now, curve_now)


def _header(models: dict | None) -> None:
    from src.data import freshness

    info = freshness.summary(freshness.status_table(freshness.fetch_log()))
    if info["fetched_at"] is not None:
        pulled = info["fetched_at"].strftime("%d %b %Y %H:%M")
        daily = info["latest_daily"].strftime("%d %b") if info["latest_daily"] else "—"
        monthly = info["latest_monthly"].strftime("%b %Y") if info["latest_monthly"] else "—"
        timestamp = (
            f"data pulled {pulled} · daily series through {daily} · "
            f"monthly series through {monthly} · auto-refresh every 6h"
        )
    else:
        timestamp = "data not loaded"
    composite_html = ""
    if models is not None:
        try:
            comp = _composite_now(models)
            color = risk_color(comp["band"])
            composite_html = (
                f'<div class="composite-readout">'
                f'<div class="label-tiny">Composite Risk{info_icon_html("Composite Risk", align="left")}</div>'
                f'<div class="composite-number" style="color:{color};">{comp["composite"]}</div>'
                f'<div class="risk-badge" style="color:{color};margin-top:6px;">{comp["band"]}</div>'
                f"</div>"
            )
        except Exception:
            composite_html = ""

    st.markdown(
        (
            '<div class="dashboard-header">'
            '<div>'
            '<div class="dashboard-title">U.S. Macro Dashboard</div>'
            f'<div class="dashboard-subtitle">U.S. recession risk · {timestamp}</div>'
            '</div>'
            f'{composite_html}'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


_REFRESH_SCRIPTS = (
    ("Policy path (Atlanta Fed)", "scripts.refresh_market_probability"),
    ("CAPE (Shiller)", "scripts.refresh_cape"),
)


def _refresh_all() -> list[str]:
    """Re-download the bundled CSVs, then drop every cache so the next run
    refetches FRED and refits the models. Returns one line per script."""
    import subprocess
    import sys
    from pathlib import Path

    from src.data import freshness

    results = []
    root = Path(__file__).resolve().parent
    for label, module in _REFRESH_SCRIPTS:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", module], cwd=root,
                capture_output=True, text=True, timeout=180,
            )
            ok = proc.returncode == 0
            results.append(f"{label}: {'updated' if ok else 'FAILED (exit ' + str(proc.returncode) + ')'}")
        except Exception as exc:  # noqa: BLE001
            results.append(f"{label}: FAILED ({type(exc).__name__})")
    st.cache_data.clear()
    st.cache_resource.clear()
    freshness.clear_log()
    return results


def _data_status_bar() -> None:
    """Series-status expander plus a manual refresh button."""
    from src.data import freshness

    table = freshness.status_table(freshness.fetch_log())
    info = freshness.summary(table)
    left, right = st.columns([5, 1])
    with right:
        if st.button("↻ Refresh data", key="refresh_data", help=(
            "Re-downloads all FRED series, the Atlanta Fed policy-path file and "
            "Shiller CAPE, then refits the models (about a minute). Data also "
            "refreshes on its own every 6 hours when the page is loaded."
        )):
            with st.spinner("Refreshing all sources…"):
                st.session_state.refresh_results = _refresh_all()
            st.rerun()
    with left:
        problems = info["late"] + info["failed"] + info["discontinued"]
        label = (
            f"Data status · {info['n']} FRED series · {info['ok']} current"
            + (f" · {info['late']} late" if info["late"] else "")
            + (f" · {info['failed']} failed" if info["failed"] else "")
            + (f" · {info['discontinued']} discontinued" if info["discontinued"] else "")
        )
        with st.expander(("⚠ " if problems else "") + label):
            for line in st.session_state.pop("refresh_results", []):
                st.caption(line)
            st.caption(
                "‘late’ = the newest observation is older than that series normally runs "
                "(monthly data is dated the 1st and published 1–2 months later). "
                "Policy path and CAPE come from bundled files; their dates are shown on their cards."
            )
            order = {"failed": 0, "discontinued": 1, "late": 2, "ok": 3}
            st.dataframe(
                table.sort_values("status", key=lambda s: s.map(order)).drop(columns=["fetched_at"]),
                hide_index=True, width="stretch",
            )


def _nav() -> str:
    """Top navigation. Drill-down buttons set ``pending_nav`` then rerun; we
    consume it here via ``manual_select`` so streamlit-option-menu actually
    moves its selection (its internal session state otherwise sticks)."""
    if "view" not in st.session_state:
        st.session_state.view = NAV_OPTIONS[0]

    manual_select = None
    if "pending_nav" in st.session_state:
        target = st.session_state.pop("pending_nav")
        if target in NAV_OPTIONS:
            manual_select = NAV_OPTIONS.index(target)
            st.session_state.view = target

    default_index = NAV_OPTIONS.index(st.session_state.view) if st.session_state.view in NAV_OPTIONS else 0

    selected = option_menu(
        menu_title=None,
        options=NAV_OPTIONS,
        icons=["grid", "exclamation-triangle", "graph-down", "activity", "bank", "people", "graph-up", "reception-4", "signpost-split", "cpu", "book"],
        orientation="horizontal",
        default_index=default_index,
        manual_select=manual_select,
        key="nav",
        styles={
            "container": {"background-color": "#0a0d12", "padding": "0"},
            "nav-link": {
                "font-size": "11px",
                "letter-spacing": "0.15em",
                "text-transform": "uppercase",
                "color": "#6b7280",
                "background-color": "transparent",
                "padding": "10px 18px",
            },
            "nav-link-selected": {
                "color": "#d4a574",
                "background-color": "transparent",
                "border-bottom": "2px solid #d4a574",
            },
            "icon": {"display": "none"},
        },
    )
    st.session_state.view = selected
    return selected


def main() -> None:
    try:
        with st.spinner("Loading FRED data…"):
            # Bump this version string whenever model code changes — Streamlit's
            # cache_resource doesn't track imported modules, so a code edit to
            # e.g. src/models/lame.py won't otherwise invalidate the cached fit.
            cache_version = "v18-recession-recovery"
            models = dict(_build_models(cache_version))
    except Exception as exc:
        _header(None)
        # The AI Bubble tab runs on Yahoo prices, not the FRED models, so it
        # stays usable when FRED is down or the key is missing.
        if _nav() == "AI Bubble":
            ai_bubble.render()
            return
        st.error(
            f"Failed to initialise the dashboard: {exc}. "
            "Make sure FRED_API_KEY is set in `.env` or `.streamlit/secrets.toml`."
        )
        return

    # Catch outside the cache so transient failures aren't stored for six hours.
    try:
        with st.spinner("Calculating recession risk…"):
            models["probit"] = _load_probit_report(cache_version)
    except Exception as exc:  # noqa: BLE001
        models["probit"] = {"error": str(exc)}

    market_prob = _load_market_prob()

    _header(models)
    _data_status_bar()
    selected = _nav()

    if selected == "Macro Dashboard":
        rec_current, rec_history = _recession_view(models)
        dashboard.render(
            rec_current, rec_history, models["lame"], models["panel"], models["nber"],
            market_prob=market_prob,
        )
    elif selected == "Early Warning":
        early_warning.render(models["panel"], models.get("probit"), models["lame"])
    elif selected == "Recession":
        recession.render(models.get("probit"), models["nber"])
    elif selected == "Growth":
        growth.render(models["nber"], models.get("probit"))
    elif selected == "Credit":
        credit.render(models["nber"], models.get("probit"))
    elif selected == "Pulse":
        pulse.render(models["panel"], models["nber"], models["lame"])
    elif selected == "Labor":
        lame_view.render(models["panel"], models["nber"], models["lame"])
    elif selected == "Yield Curve":
        curve.render(models["panel"], models["nber"])
    elif selected == "Policy Path":
        rate_path.render(market_prob, models["nber"])
    elif selected == "AI Bubble":
        ai_bubble.render()
    elif selected == "Methodology":
        methodology.render(models.get("probit"))

    st.markdown(
        f'<div style="margin-top:48px;padding-top:16px;border-top:1px solid {PALETTE["panel_border"]};'
        f'color:{PALETTE["text_tiny"]};font-size:10px;letter-spacing:0.2em;text-transform:uppercase;">'
        "Data · FRED  ·  Recession dates · NBER  ·  Policy path · Atlanta Fed  ·  AI Bubble prices · Yahoo Finance  ·  This is research, not investment advice."
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
