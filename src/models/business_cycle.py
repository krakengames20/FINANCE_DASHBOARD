"""Descriptive cycle overview from existing data; no forecast or new score."""

from __future__ import annotations

import numpy as np
import pandas as pd


GDP_ID = "A191RL1Q225SBEA"
GDI_ID = "A261RL1Q225SBEA"
GDP_CHANGE_BAND = 0.5  # annualized percentage points
ACTIVITY_CHANGE_BAND = 0.1  # index points over three months
DIFFUSION_CHANGE_BAND = 0.05  # index points over three months
INFLATION_CHANGE_BAND = 0.25  # annualized percentage points

QUESTIONS = {
    "activity": "Is economic activity growing?",
    "momentum": "Is it gaining or losing speed?",
    "breadth": "Is weakness spreading?",
    "inflation": "Is inflation easing?",
}


def _calendar(series, freq: str, today: pd.Timestamp) -> pd.Series:
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    s = pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan)
    s.index = pd.DatetimeIndex(s.index)
    s = s.sort_index().resample(freq).last()
    period = "Q" if freq == "QS" else "M"
    # Reference periods must be complete; current-quarter nowcasts are not GDP.
    return s.loc[s.index.to_period(period).end_time.normalize() <= today]


def _date(ts: pd.Timestamp, quarterly: bool = False) -> str:
    return f"Q{ts.quarter} {ts.year}" if quarterly else ts.strftime("%b %Y")


def _card(key: str, answer: str, explanation: str, date=None, *, severity="neutral", evidence=None):
    return {"key": key, "question": QUESTIONS[key], "answer": answer,
            "explanation": explanation, "date": date, "severity": severity,
            "evidence": evidence or [], "available": date is not None}


def _unavailable(key: str, reason: str, date=None):
    card = _card(key, "Out of date" if date else "Not enough data", reason, date)
    card["available"] = False
    return card


def _direction(change: float, band: float) -> str:
    return "up" if change > band else "down" if change < -band else "steady"


def business_cycle_overview(
    panel: pd.DataFrame,
    headline: dict[str, pd.Series],
    core_prices: pd.Series | None,
    *,
    today=None,
) -> dict:
    """Four dated answers. Calendar gaps and stale inputs withhold conclusions.

    GDP describes the latest reported quarter. Monthly CFNAI momentum and
    diffusion provide newer context. Core PCE uses consecutive, non-overlapping
    three-month annualized rates, not the price-index level. Labels are
    descriptive conventions, not statistical significance or recession calls.
    """
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    panel = panel if panel is not None else pd.DataFrame()
    cards = {}
    notes = []

    gdp = _calendar(headline.get(GDP_ID), "QS", today)
    valid = gdp.dropna()
    quarterly_direction = None
    if valid.empty:
        cards["activity"] = _unavailable("activity", "The reported GDP estimate is unavailable.")
        cards["momentum"] = _unavailable("momentum", "Two consecutive GDP quarters are needed.")
    else:
        ts, value = valid.index[-1], float(valid.iloc[-1])
        stamp = _date(ts, True)
        age = (today - ts.to_period("Q").end_time.normalize()).days
        if age > 140:
            reason = f"The latest GDP estimate is for {stamp}; it is too old for a current reading."
            cards["activity"] = _unavailable("activity", reason, stamp)
            cards["momentum"] = _unavailable("momentum", reason, stamp)
        else:
            answer = "Expanding" if value > 0 else "Contracting" if value < 0 else "Unchanged"
            cards["activity"] = _card(
                "activity", answer,
                f"Inflation-adjusted economic output {'grew' if value > 0 else 'fell' if value < 0 else 'was unchanged'} "
                f"in {stamp}: {value:+.1f}% at an annual rate.", stamp,
                severity="positive" if value > 0 else "caution" if value < 0 else "neutral",
                evidence=[f"BEA real GDP growth: {value:+.1f}% annualized ({stamp})."],
            )
            # Same-quarter income-side confirmation; never silently use an older GDI quarter.
            gdi = _calendar(headline.get(GDI_ID), "QS", today)
            income = gdi.get(ts, np.nan)
            if np.isfinite(income):
                cards["activity"]["evidence"].append(
                    f"BEA real GDI growth: {income:+.1f}% annualized ({stamp}); measures output through income."
                )
                if value * income < 0:
                    notes.append(f"The two official views disagree in {stamp}: output and income moved in opposite directions.")
            else:
                cards["activity"]["evidence"].append(f"No income-side estimate is available for {stamp}.")

            prev_ts = ts - pd.DateOffset(months=3)
            previous = gdp.get(prev_ts, np.nan)
            if not np.isfinite(previous):
                cards["momentum"] = _unavailable("momentum", "The preceding GDP quarter is missing; no speed comparison is shown.")
            else:
                change = value - float(previous)
                quarterly_direction = _direction(change, GDP_CHANGE_BAND)
                answer = {"up": "Accelerating", "down": "Slowing", "steady": "Little change"}[quarterly_direction]
                cards["momentum"] = _card(
                    "momentum", answer,
                    f"GDP growth moved from {previous:+.1f}% in {_date(prev_ts, True)} to {value:+.1f}% in {stamp}.",
                    stamp, severity="positive" if quarterly_direction == "up" else "caution" if quarterly_direction == "down" else "neutral",
                    evidence=[f"Change in annualized GDP growth: {change:+.1f} percentage points."],
                )
                if value > 0 and quarterly_direction == "down":
                    notes.append("Output is still growing, but more slowly. Slower growth does not mean the economy is shrinking.")
                if value < 0 and quarterly_direction == "up":
                    notes.append("Output is still shrinking, but the decline is becoming less severe.")

    activity = _calendar(panel.get("CFNAIMA3"), "MS", today)
    av = activity.dropna()
    if not av.empty:
        at = av.index[-1]
        a = float(av.iloc[-1])
        if (today - at.to_period("M").end_time.normalize()).days <= 90:
            context = f"The monthly activity average is {a:+.2f} in {_date(at)}; zero means growth near its historical trend."
            cards["activity"]["evidence"].append(context)
            earlier = activity.get(at - pd.DateOffset(months=3), np.nan)
            if np.isfinite(earlier):
                direction = _direction(a - earlier, ACTIVITY_CHANGE_BAND)
                cards["momentum"]["evidence"].append(
                    f"Monthly activity average: {earlier:+.2f} in {_date(at - pd.DateOffset(months=3))}, "
                    f"{a:+.2f} in {_date(at)}."
                )
                if quarterly_direction and direction != "steady" and quarterly_direction != "steady" and direction != quarterly_direction:
                    notes.append(f"The monthly activity reading through {_date(at)} points the other way from GDP's quarterly speed comparison.")
                elif quarterly_direction and direction == "steady" and quarterly_direction != "steady":
                    notes.append(f"Monthly activity through {_date(at)} shows little change, so it does not clearly confirm GDP's change in speed.")

    diffusion = _calendar(panel.get("CFNAIDIFF"), "MS", today)
    dv = diffusion.dropna()
    if dv.empty:
        cards["breadth"] = _unavailable("breadth", "The broad activity reading is unavailable.")
    else:
        ts, value = dv.index[-1], float(dv.iloc[-1])
        stamp = _date(ts)
        earlier = diffusion.get(ts - pd.DateOffset(months=3), np.nan)
        if (today - ts.to_period("M").end_time.normalize()).days > 90:
            cards["breadth"] = _unavailable("breadth", f"The broad activity reading stops at {stamp}.", stamp)
        elif not np.isfinite(earlier):
            cards["breadth"] = _unavailable("breadth", "The reading three months earlier is missing; we cannot tell whether weakness is spreading.")
        else:
            direction = _direction(value - earlier, DIFFUSION_CHANGE_BAND)
            if direction == "down":
                answer = "Spreading" if value < 0 else "Support narrowing"
                text = "The broad mix of activity measures shows increasing weakness relative to normal growth." if value < 0 else "Support for growth has narrowed, but the balance is still positive."
                severity = "caution"
            elif direction == "up":
                answer = "Narrowing" if value < 0 else "Support broadening"
                text = "Weakness is easing, although the balance of readings remains below trend." if value < 0 else "The broad mix of activity measures provides increasing support for growth."
                severity = "positive"
            else:
                answer = "Little change"
                text = "The balance of below-trend activity readings has changed little." if value < 0 else "Broad support for growth has changed little."
                severity = "neutral"
            if value <= -0.35:
                text += " Weakness remains widespread."
            cards["breadth"] = _card(
                "breadth", answer, text, stamp, severity=severity,
                evidence=[f"Chicago Fed activity diffusion (about 85 measures): {earlier:+.2f} in "
                          f"{_date(ts - pd.DateOffset(months=3))}, {value:+.2f} in {stamp}.",
                          "Below trend is weaker than usual growth; it does not necessarily mean outright contraction."],
            )

    prices = _calendar(core_prices, "MS", today)
    prices = prices.where(prices > 0)
    pv = prices.dropna()
    if pv.empty:
        cards["inflation"] = _unavailable("inflation", "The underlying consumer-price reading is unavailable.")
    else:
        ts = pv.index[-1]
        stamp = _date(ts)
        levels = [prices.get(ts - pd.DateOffset(months=n), np.nan) for n in (0, 3, 6)]
        if (today - ts.to_period("M").end_time.normalize()).days > 90:
            cards["inflation"] = _unavailable("inflation", f"The price reading stops at {stamp}.", stamp)
        elif not np.isfinite(levels).all() or prices.reindex(pd.date_range(ts - pd.DateOffset(months=6), ts, freq="MS")).isna().any():
            cards["inflation"] = _unavailable("inflation", "Six consecutive months of price changes are needed to compare inflation's pace.")
        else:
            recent = ((levels[0] / levels[1]) ** 4 - 1) * 100
            prior = ((levels[1] / levels[2]) ** 4 - 1) * 100
            direction = _direction(recent - prior, INFLATION_CHANGE_BAND)
            answer = {"down": "Easing", "up": "Intensifying", "steady": "Little change"}[direction]
            text = f"Underlying prices rose at a {recent:.1f}% annual pace over the latest three months, versus {prior:.1f}% in the preceding three."
            if recent < 0:
                text = f"Underlying prices fell at a {abs(recent):.1f}% annual pace over the latest three months; the preceding pace was {prior:+.1f}%."
            cards["inflation"] = _card(
                "inflation", answer, text, stamp,
                severity="positive" if direction == "down" else "caution" if direction == "up" else "neutral",
                evidence=[f"Core consumer inflation (PCE, excluding food and energy): {recent:.2f}% annualized over three months, "
                          f"versus {prior:.2f}% in the previous three.",
                          "Easing means prices are rising more slowly; it usually does not mean prices are falling."],
            )
            year_ago = prices.get(ts - pd.DateOffset(months=12), np.nan)
            if np.isfinite(year_ago):
                cards["inflation"]["evidence"].append(f"Prices are {(levels[0] / year_ago - 1) * 100:.1f}% higher than a year earlier.")

    activity_card = cards["activity"]
    momentum_card = cards["momentum"]
    if activity_card["available"] and momentum_card["available"]:
        movement = {"Expanding": "increased", "Contracting": "decreased", "Unchanged": "was unchanged"}[activity_card["answer"]]
        speed = {"Accelerating": "The growth rate increased from the preceding quarter.",
                 "Slowing": "The growth rate decreased from the preceding quarter.",
                 "Little change": "The growth rate changed little from the preceding quarter."}[momentum_card["answer"]]
        lead = f"Economic output {movement} in {activity_card['date']}. {speed}"
    elif activity_card["available"]:
        lead = f"The latest reported quarter is {activity_card['answer'].lower()}; its change in speed is unclear."
    else:
        lead = "There is not enough current evidence to describe the latest quarter."
    if not all(card["available"] for card in cards.values()):
        notes.append("Some answers are unavailable. Read the dated evidence before drawing a complete cycle conclusion.")
    return {"cards": list(cards.values()), "summary": lead, "notes": notes}
