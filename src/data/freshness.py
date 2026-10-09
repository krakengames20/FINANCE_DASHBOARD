"""Per-series fetch log and staleness check.

``fred_client.fetch_series`` records every fetch here (success or failure), so
the header can show when data was last pulled and flag any series that is late,
discontinued or failing — nothing is dropped silently.
"""

from __future__ import annotations

import datetime as dt
import os
import threading

import pandas as pd

# Series FRED still serves but no longer updates (verified 2026-10-05 audit).
KNOWN_DISCONTINUED: dict[str, str] = {
    "USSLIND": "Philadelphia Fed stopped updating it; last observation Feb 2020",
}

# FRED keeps only a rolling window for these (licensing), so history is short.
HISTORY_LIMITED: dict[str, str] = {
    "BAMLH0A0HYM2": "ICE BofA data: FRED keeps only the last 3 years",
    "BAMLC0A0CM": "ICE BofA data: FRED keeps only the last 3 years",
    "SP500": "S&P licence: FRED keeps only the last 10 years",
}

# Days an observation may age before it counts as late, by inferred frequency.
# Monthly data is dated the 1st of the month and published 1–2 months later.
MAX_AGE_DAYS: dict[str, int] = {"D": 7, "W": 14, "M": 75, "Q": 200, "A": 500}

# Series with a normal publication lag longer than their frequency default.
MAX_AGE_OVERRIDES: dict[str, int] = {
    "CCSA": 21,             # continued claims: published a week after initial claims
    "CSUSHPISA": 120,       # Case-Shiller: ~2-month lag on top of month-start dating
    "JTSJOL": 100,          # JOLTS: ~2-month lag
    "JTSQUR": 100,
    "TERMCBCCALLNS": 200,   # G.19 credit-card/auto rates: quarterly-month releases
    "TERMCBAUTO48NS": 200,
    "DRALACBS": 230,        # bank delinquency: ~5-month lag
    "GDPNOW": 200,          # quarterly target date; the nowcast itself updates weekly
}

_lock = threading.Lock()
_LOG: dict[str, dict] = {}


def record_fetch(series_id: str, series: pd.Series | None = None, error: str | None = None) -> None:
    """Record the outcome of one fetch. Called by ``fred_client.fetch_series``."""
    key = os.getenv("FRED_API_KEY")
    if error and key:
        error = error.replace(key, "***")  # error text is shown in the UI
    entry: dict = {"fetched_at": dt.datetime.now(), "error": error}
    if series is not None and error is None:
        s = pd.Series(series).dropna()
        entry.update(
            first_obs=s.index.min() if len(s) else None,
            last_obs=s.index.max() if len(s) else None,
            n_obs=len(s),
            freq=infer_freq(s.index),
        )
    with _lock:
        prev = _LOG.get(series_id, {})
        # A failure after a success keeps the last good observation dates visible.
        if error is not None and prev.get("last_obs") is not None:
            entry = {**prev, "fetched_at": entry["fetched_at"], "error": error}
        _LOG[series_id] = entry


def fetch_log() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _LOG.items()}


def restore_fetch_log(entries: dict[str, dict]) -> None:
    """Restore metadata carried with cached readings without changing fetch times.

    A module reload can reset the in-memory log while Streamlit retains model
    resources. Never replace a newer fetch or failure with an older cache entry.
    """
    with _lock:
        for sid, entry in entries.items():
            previous = _LOG.get(sid)
            if previous is None or entry["fetched_at"] > previous["fetched_at"]:
                _LOG[sid] = dict(entry)


def clear_log() -> None:
    with _lock:
        _LOG.clear()


def infer_freq(index: pd.Index) -> str:
    """D / W / M / Q / A from the median spacing of the last ~30 observations."""
    idx = pd.DatetimeIndex(index).sort_values()
    if len(idx) < 3:
        return "?"
    gap = pd.Series(idx[-30:]).diff().dropna().median().days
    if gap <= 4:
        return "D"
    if gap <= 10:
        return "W"
    if gap <= 45:
        return "M"
    if gap <= 120:
        return "Q"
    return "A"


def status_table(log: dict[str, dict], today: dt.date | None = None) -> pd.DataFrame:
    """One row per series: last observation, age, and a status label.

    Status is one of ``failed``, ``discontinued``, ``late`` or ``ok``.
    History-limited series get a note but keep their status.
    """
    today = pd.Timestamp(today or dt.date.today())
    rows = []
    for sid, e in sorted(log.items()):
        last = e.get("last_obs")
        freq = e.get("freq", "?")
        age = int((today - pd.Timestamp(last)).days) if last is not None else None
        limit = MAX_AGE_OVERRIDES.get(sid, MAX_AGE_DAYS.get(freq, 120))
        note = KNOWN_DISCONTINUED.get(sid) or HISTORY_LIMITED.get(sid, "")
        if e.get("error"):
            status = "failed"
            note = e["error"] if not note else f"{e['error']} · {note}"
        elif sid in KNOWN_DISCONTINUED:
            status = "discontinued"
        elif age is not None and age > limit:
            status = "late"
        else:
            status = "ok"
        rows.append({
            "series": sid,
            "status": status,
            "freq": freq,
            "last_obs": pd.Timestamp(last).date() if last is not None else None,
            "age_days": age,
            "first_obs": pd.Timestamp(e["first_obs"]).date() if e.get("first_obs") is not None else None,
            "fetched_at": e["fetched_at"],
            "note": note,
        })
    cols = ["series", "status", "freq", "last_obs", "age_days", "first_obs", "fetched_at", "note"]
    return pd.DataFrame(rows, columns=cols)


def summary(table: pd.DataFrame) -> dict:
    """Counts by status, latest fetch time and latest daily observation."""
    if table.empty:
        return {"n": 0, "ok": 0, "late": 0, "failed": 0, "discontinued": 0,
                "fetched_at": None, "latest_daily": None, "latest_monthly": None}
    counts = table["status"].value_counts().to_dict()
    daily = table.loc[table["freq"] == "D", "last_obs"].dropna()
    monthly = table.loc[table["freq"] == "M", "last_obs"].dropna()
    return {
        "n": len(table),
        "ok": counts.get("ok", 0),
        "late": counts.get("late", 0),
        "failed": counts.get("failed", 0),
        "discontinued": counts.get("discontinued", 0),
        "fetched_at": table["fetched_at"].max(),
        # Most common last date, not the max: IORB is posted ahead of time and
        # would otherwise make the whole panel look a few days fresher than it is.
        "latest_daily": daily.mode().max() if not daily.empty else None,
        "latest_monthly": monthly.mode().max() if not monthly.empty else None,
    }
