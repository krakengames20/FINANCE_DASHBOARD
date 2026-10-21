"""Plain-English explanations for every indicator card and chart.

``INDICATORS`` is keyed by the card label as it appears on screen (matching is
case- and dash-insensitive). Each entry says what the number is and what a high
or low reading implies for the economy. ``CHARTS`` holds a "how to read this
chart" note per chart id; views call :func:`chart_help` right under the chart.
Band thresholds quoted here mirror the ones in the model/view code.
"""

from __future__ import annotations

import re
from html import escape

INDICATORS: dict[str, dict[str, str]] = {
    # ---- headline ---------------------------------------------------------
    "Composite Risk": {
        "what": "A heuristic 0–100 risk index, not a calibrated probability: 50% the 12-month recession "
                "probability, 25% the labor composite, 25% the 10y–3m yield spread.",
        "high": "Higher = more recession risk. Bands: <20 LOW, 20–40 ELEVATED, 40–60 HIGH, 60+ CRITICAL.",
        "low": "Low = the three lenses agree the expansion looks intact.",
    },
    "Probability a new recession starts within 12 months": {
        "what": "Average of three locally re-estimated models (NY Fed, Wright, BIC-selected) "
                "that estimate the chance a recession begins in the next 12 months.",
        "high": "Above 30% is the dashboard warning band; above 50% is elevated. These are judgmental thresholds.",
        "low": "Below 20% is the normal range during an expansion.",
    },
    "3-model ensemble": {
        "what": "Simple average of the three forward-looking recession models.",
        "high": "Above 30% warning, above 50% elevated.",
        "low": "Below 20% is typical of an expansion.",
    },
    "NY Fed": {
        "what": "Local adaptation of a term-spread probit: recession-start odds from the 10y–3m Treasury spread alone.",
        "high": "Rises when the curve flattens or inverts (short rates above long rates).",
        "low": "Falls when the curve is steep (long rates well above short rates).",
    },
    "Wright": {
        "what": "Local adaptation of Wright's specification: the yield spread plus the level of the fed funds rate.",
        "high": "Rises with an inverted curve combined with high policy rates (tight money).",
        "low": "Falls with a steep curve and/or low policy rates.",
    },
    "BIC-selected": {
        "what": "A model that picks the best mix of up to 4 indicators (always including the yield "
                "spread) from ~35 FRED series, keeping only economically sensible signs.",
        "high": "Rises when the selected drivers (shown in Under the Hood) deteriorate.",
        "low": "Falls when they improve.",
    },
    "Estrella-Mishkin": {
        "what": "Separate benchmark: frozen 2006 coefficients predict recession in month 12, not a new recession within a year.",
        "high": "Rises as the 10y–3m spread falls toward or below zero.",
        "low": "Falls as the spread steepens.",
    },
    "Chauvet-Piger": {
        "what": "Benchmark, not part of the average: probability the U.S. is in recession *now* "
                "(a nowcast from payrolls, production, income and sales).",
        "high": "Above ~80% has historically meant a recession was under way.",
        "low": "Near 0% means current activity data look like an expansion.",
    },
    "BIC model · this scenario": {
        "what": "Recession probability from the BIC-selected model if the drivers moved to the "
                "values you set in the scenario sliders.",
        "high": "Higher than baseline = your scenario adds risk.",
        "low": "Lower than baseline = your scenario reduces risk.",
    },
    # ---- labor ------------------------------------------------------------
    "Labor Composite": {
        "what": "LAME: 10 labor-market indicators (unemployment, claims, openings, quits, hours, "
                "temp help, payrolls, U-6, participation), each scored against its own history "
                "and blended into one z-score. 0 = average conditions.",
        "high": "Positive = labor market stronger than usual (>+1 HOT, +0.5 to +1 FIRM).",
        "low": "Negative = weakening (−0.5 to −1 SOFTENING, below −1 CONTRACTIONARY, "
               "which usually coincides with recession).",
    },
    "Sahm Rule": {
        "what": "3-month average unemployment rate minus its lowest level of the prior 12 months.",
        "high": "0.5 pp or more has signalled the start of every U.S. recession since 1970.",
        "low": "Below 0.2 pp = unemployment not rising meaningfully.",
    },
    "Wage growth (median)": {
        "what": "Atlanta Fed Wage Growth Tracker: median year-on-year wage growth of the same "
                "workers, 12-month average. Long-run average ≈ 3.5–4%.",
        "high": "Above ~4.5% = hot labor market and inflation pressure; often met by Fed tightening.",
        "low": "Below ~2.5% = soft labor market, weak bargaining power.",
    },
    "Labor breadth · below trend": {
        "what": "Share of the 10 labor indicators currently below their long-run average.",
        "high": "Above 70% = broad weakness (typical near recessions).",
        "low": "Below 40% = broad strength.",
    },
    "Labor momentum · deteriorating": {
        "what": "Share of the 10 labor indicators that have worsened over the last 3 months.",
        "high": "High = weakness is spreading, even if levels still look fine.",
        "low": "Low = most indicators stable or improving.",
    },
    "Activity Diffusion (CFNAI)": {
        "what": "How broadly the ~85 monthly activity series in the Chicago Fed index are "
                "improving vs. worsening.",
        "high": "At or above 0 = broad-based growth.",
        "low": "Below −0.35 = broad weakness, a recession-like pattern.",
    },
    # ---- curve & rates -------------------------------------------------------
    "10Y − 3M Spread": {
        "what": "10-year Treasury yield minus 3-month bill yield, in percentage points.",
        "high": "Positive and rising = normal, upward-sloping curve; the market expects growth.",
        "low": "Below 0 (inverted) has preceded every U.S. recession since the 1960s, "
               "typically by 6–18 months. The recession often starts after it re-steepens.",
    },
    "10Y − 3M": {
        "what": "10-year Treasury yield minus 3-month bill yield, in percentage points. The "
                "best single recession predictor in the U.S. record.",
        "high": "Positive = normal curve.",
        "low": "Negative (inverted) has preceded every recession since the 1960s.",
    },
    "10Y − 2Y": {
        "what": "10-year minus 2-year Treasury yield. The most-quoted curve measure in markets.",
        "high": "Positive = normal curve; steepening out of an inversion often happens as the Fed cuts.",
        "low": "Negative = inverted; the market expects rate cuts / slower growth ahead.",
    },
    "5Y − 2Y": {
        "what": "5-year minus 2-year Treasury yield: the slope of the front end of the curve.",
        "high": "Positive = market expects the policy rate to drift up or stay put.",
        "low": "Negative = market prices Fed cuts within the next few years.",
    },
    "SOFR": {
        "what": "Secured Overnight Financing Rate: the cost of borrowing cash overnight against "
                "Treasury collateral. The main U.S. benchmark rate.",
        "high": "Spikes above the fed funds rate signal funding strain (scarce reserves/cash).",
        "low": "Trading near or below fed funds = ample liquidity.",
    },
    "Fed Funds (EFFR)": {
        "what": "Effective federal funds rate: the overnight rate banks charge each other, kept by "
                "the Fed inside its target range.",
        "high": "Higher = tighter monetary policy.",
        "low": "Lower = easier monetary policy.",
    },
    "1M T-Bill (DGS1MO)": {
        "what": "1-month Treasury bill yield: the market's near-term view of policy rates.",
        "high": "Above fed funds = market pricing hikes (or bill supply pressure).",
        "low": "Below fed funds = market pricing cuts, or a flight to safety.",
    },
    # ---- financial conditions ---------------------------------------------
    "Financial Conditions": {
        "what": "Chicago Fed NFCI: 105 measures of risk, credit and leverage. 0 = average; "
                "units are standard deviations.",
        "high": "Positive = tighter than average (0.5–1 TIGHTENING, 1–2 STRESSED, 2+ CRISIS).",
        "low": "Negative = easier than average (below −0.5 EASY).",
    },
    "Adjusted Financial Conditions": {
        "what": "ANFCI: the NFCI with the effect of the economic cycle and inflation removed, "
                "so it shows conditions relative to what the economy normally implies.",
        "high": "Positive = conditions tighter than the current economy would justify.",
        "low": "Negative = looser than the economy would justify (risk-taking is easy).",
    },
    "Financial Stress": {
        "what": "St. Louis Fed Financial Stress Index (STLFSI4): 18 weekly market series "
                "(rates, spreads, volatility). 0 = normal.",
        "high": "Above 0 = above-normal stress; above 1 = significant stress.",
        "low": "Below 0 = below-normal stress.",
    },
    "Economic Activity (3-mo)": {
        "what": "Chicago Fed National Activity Index, 3-month average (CFNAIMA3): 85 monthly "
                "activity series. 0 = the economy is growing at trend.",
        "high": "Above +0.7 = growth well above trend (possible inflation pressure).",
        "low": "Below −0.7 has historically marked the start of recessions; below −1.5 = deep recession.",
    },
    "Credit-stress composite": {
        "what": "Average of six standardized credit measures (high-yield and investment-grade "
                "spreads, Baa–10y spread, NFCI, St. Louis stress, bank lending standards). "
                "Note: the ICE spread inputs only have 3 years of history on FRED.",
        "high": "Higher = credit getting harder/more expensive to obtain, which usually "
                "leads slowdowns (70th+ pct ELEVATED, 90th+ STRESSED).",
        "low": "Lower = credit is easy and cheap (below 40th pct CALM).",
    },
    # ---- growth ------------------------------------------------------------
    "GDPNow nowcast": {
        "what": "Atlanta Fed's running estimate of real GDP growth for the current quarter, "
                "annualized, updated after each data release.",
        "high": "Above ~2% = growth at or above the economy's long-run trend.",
        "low": "Below 0 = the economy is estimated to be shrinking this quarter.",
    },
    # ---- valuation -------------------------------------------------------------
    "Shiller CAPE": {
        "what": "S&P 500 price divided by 10-year average inflation-adjusted earnings. "
                "A valuation measure, not a timing signal.",
        "high": "High (85th+ pct EXTREME) = stocks expensive; lower long-run returns and bigger "
                "drawdowns if a recession hits.",
        "low": "Low (below 25th pct CHEAP) = stocks cheap; historically higher 10-year returns.",
    },
    "Implied 10y real return": {
        "what": "Annualized after-inflation S&P 500 return over the next 10 years implied by "
                "today's CAPE, from a regression on history.",
        "high": "Higher = valuations leave room for good long-run returns.",
        "low": "Low or negative = today's price already discounts a lot of future growth.",
    },
    # ---- market-implied (Pulse) -------------------------------------------------
    "5y5y forward inflation": {
        "what": "Market-implied average inflation for the 5 years starting 5 years from now. "
                "The Fed's favoured gauge of long-run inflation expectations.",
        "high": "Above ~2.5–3% = markets doubt the Fed will hold inflation at 2%.",
        "low": "Below ~2% = markets expect low inflation, often a sign of weak growth expectations.",
    },
    "10y breakeven inflation": {
        "what": "10-year Treasury yield minus 10-year TIPS yield: average inflation priced for "
                "the next 10 years.",
        "high": "Rising = markets price more inflation.",
        "low": "Falling sharply = markets price disinflation or a slowdown.",
    },
    "10y real yield (TIPS)": {
        "what": "10-year inflation-protected Treasury yield: the real (after-inflation) cost of money.",
        "high": "High real yields = tight financial conditions; pressure on stocks and housing.",
        "low": "Low or negative = very easy conditions.",
    },
    "10y–3m term spread": {
        "what": "10-year minus 3-month Treasury yield.",
        "high": "Positive = normal upward-sloping curve.",
        "low": "Negative (inverted) has preceded every recession since the 1960s.",
    },
    "High-yield credit spread": {
        "what": "Extra yield investors demand on junk-rated corporate bonds over Treasuries "
                "(ICE BofA HY OAS).",
        "high": "Above ~5–6 pp = credit stress; above 8 pp is typical of recessions.",
        "low": "Below ~3.5 pp = investors very relaxed about default risk.",
    },
    "Financial stress index": {
        "what": "St. Louis Fed Financial Stress Index. 0 = normal.",
        "high": "Above 0 = above-normal stress.",
        "low": "Below 0 = calm markets.",
    },
    # ---- early-warning ladder ------------------------------------------------
    "Yield-curve inversion (10y–3m)": {
        "what": "Whether the 10y–3m spread is inverted. Earliest and slowest signal.",
        "high": "Lit = curve inverted; recessions have historically followed within 6–18 months.",
        "low": "Unlit = normal curve.",
    },
    "Bank lending standards (SLOOS)": {
        "what": "Net share of banks tightening standards on business loans (Fed loan officer survey).",
        "high": "High positive = banks pulling back credit; tends to lead recessions by 6–12 months.",
        "low": "Near zero or negative = banks easing.",
    },
    "Housing permits (YoY)": {
        "what": "Year-on-year change in new building permits. Housing turns early in the cycle.",
        "high": "Rising = construction pipeline growing.",
        "low": "Falling sharply (e.g. −20% YoY) has led most recessions.",
    },
    "Labor: Sahm rule": {
        "what": "3-month average unemployment minus its 12-month low.",
        "high": "≥ 0.5 pp = recession signal.",
        "low": "Below 0.2 pp = no signal.",
    },
    "Recession-start ensemble (12-mo)": {
        "what": "The 3-model recession probability.",
        "high": "Above 30% warning, above 50% elevated.",
        "low": "Below 20% normal.",
    },
    "Labor breadth below trend": {
        "what": "Share of the 10 labor indicators below their long-run average.",
        "high": "Above 70% = broad weakness.",
        "low": "Below 40% = broad strength.",
    },
    "Financial conditions (NFCI)": {
        "what": "Chicago Fed National Financial Conditions Index. 0 = average.",
        "high": "Positive = tighter than average; above 1 = stress.",
        "low": "Negative = easy conditions.",
    },
    "Acute stress: VIX": {
        "what": "VIX: the market's expected S&P 500 volatility over the next 30 days.",
        "high": "Above 30 = acute fear/stress; above 40 is crisis territory.",
        "low": "Below 15 = calm (sometimes complacent) markets.",
    },
    # ---- AI Bubble tab ----------------------------------------------------
    "AI bubble signals": {
        "what": "Nine daily checks built from the dot-com comparison: is the weakest part of the AI "
                "build-out cracking, and is stress spreading to credit and the wider market? "
                "Each is CALM, WATCH or ALERT.",
        "high": "More ALERTs = more of the 2000 sequence is showing: weak firms break first, "
                "leadership narrows, then credit and rates tighten.",
        "low": "Mostly CALM = trend intact. Booms can run long; CALM is not a forecast.",
    },
    "Builders vs leaders": {
        "what": "Equal-weight basket of the levered builders (CoreWeave, Oracle, Nebius, Applied "
                "Digital, IREN, Cipher, TeraWulf) divided by Nvidia, Broadcom and AMD. Shown as the "
                "3-month change. WATCH below −10%, ALERT below −20%.",
        "high": "Rising = the borrowers are keeping up with the suppliers; financing is still easy.",
        "low": "Falling = the debt-funded part of the chain is breaking first, as CLECs and dot-coms "
               "did months before Cisco peaked in 2000.",
    },
    "AI breadth": {
        "what": "Share of the 20 AI names trading above their 200-day average. "
                "WATCH below 60%, ALERT below 40%.",
        "high": "Most names in uptrends = broad participation.",
        "low": "A few leaders hold the index up while most AI names are in downtrends: a classic "
               "late-cycle pattern.",
    },
    "Equal-weight vs cap-weight": {
        "what": "Equal-weight S&P 500 (RSP) divided by the cap-weighted S&P 500 (SPY), as a "
                "3-month change. WATCH below −3%, ALERT below −6%.",
        "high": "Rising = the average stock is keeping up; leadership is broadening.",
        "low": "Falling = gains concentrated in a few mega-caps; leadership is narrowing, "
               "as it did into the 2000 top.",
    },
    "Semis trend": {
        "what": "Semiconductor ETF (SMH) relative to the S&P 500, compared with its 50- and 200-day "
                "averages. The value shows the gap to the 200-day average.",
        "high": "Above both averages, 50-day above 200-day = suppliers still leading (CALM).",
        "low": "Below the 200-day with the 50-day under it = supplier reset under way (ALERT), "
               "as with chip stocks in 2000–01.",
    },
    "Volatility": {
        "what": "VIX level, plus VIX ÷ VIX3M: near-term vs 3-month implied volatility. "
                "WATCH at VIX 20 or ratio 0.95; ALERT at VIX 30 or ratio above 1.",
        "high": "High VIX or ratio above 1 = acute fear; protection is expensive.",
        "low": "Low VIX = calm markets, and cheap protection (puts) for anyone hedging.",
    },
    "High-yield credit": {
        "what": "ICE BofA US high-yield option-adjusted spread (FRED), with its 1-month change. "
                "WATCH at +50 bp in a month or 4.5%; ALERT at +100 bp or 6%.",
        "high": "Widening = lenders demanding more to fund risky borrowers; the refinancing route "
                "for neoclouds and SPVs is closing.",
        "low": "Tight spreads = easy credit; little stress priced in.",
    },
    "10-year yield": {
        "what": "10-year Treasury yield (FRED). WATCH at 5.0%, ALERT at 5.5%.",
        "high": "High long rates raise the cost of every data-centre lease, SPV bond and "
                "GPU-backed loan, and lower what future AI profits are worth today.",
        "low": "Lower long rates ease financing for the build-out.",
    },
    "Private-credit proxies": {
        "what": "Equal-weight basket of listed stand-ins for private credit: Blue Owl, Apollo, the "
                "BDC ETF (BIZD) and SoftBank. Shown as % below its 52-week high. "
                "WATCH below −15%, ALERT below −30%.",
        "high": "Near highs = lenders to the build-out still trusted.",
        "low": "Deep drawdown = markets doubt the loans and SPV equity behind the data centres.",
    },
    "Global equities from peak": {
        "what": "MSCI All-Country World ETF (ACWI) vs its 52-week high. Ties to the rulebook: "
                "deploy a third of dry powder at −20%, another third at −30%.",
        "high": "Near 0% = no broad sell-off.",
        "low": "−20% or worse = ALERT: the rulebook's first buying trigger.",
    },
    "AI stocks": {
        "what": "The 20 AI-exposed names from the risk map plus reference rows. Today % is vs the "
                "previous close; 7d and 1m use calendar days. Risk = expected damage in a lab "
                "shock (1–10).",
        "high": "Large gains concentrated in high-risk names = speculative phase.",
        "low": "High-risk names deep below their highs while leaders hold up = early cracking.",
    },
    "Upcoming catalysts": {
        "what": "Dated events that could reprice the AI trade: Anthropic S-1, roadshow and listing, "
                "Big Tech earnings and capex guidance, FOMC, and the lock-up expiry.",
        "high": "Several events close together = higher odds of a sharp move.",
        "low": "Quiet calendar = fewer forced repricings.",
    },
}

_ALIASES = {
    "probability a new recession starts within 12 months · 3-model ensemble":
        "probability a new recession starts within 12 months",
}

_GENERIC_TREASURY = {
    "what": "Treasury yield at this maturity: what the U.S. government pays to borrow for that long.",
    "high": "Higher yields = tighter financing conditions for households and companies.",
    "low": "Lower yields = easier conditions; sharp falls often reflect growth fears or expected Fed cuts.",
}


def _norm(label: str) -> str:
    s = label.strip().lower()
    s = re.sub(r"[−–—]", "-", s)      # minus / en / em dash → hyphen
    return re.sub(r"\s+", " ", s)


_INDEX = {_norm(k): v for k, v in INDICATORS.items()}


def indicator_help(label: str) -> dict[str, str] | None:
    """Explanation dict for a card label, or None if there isn't one."""
    key = _norm(label)
    key = _ALIASES.get(key, key)
    if key in _INDEX:
        return _INDEX[key]
    if key.endswith(" treasury"):
        return _GENERIC_TREASURY
    return None


def help_text(label: str) -> str | None:
    """Plain-text tooltip: what / high / low on separate lines."""
    h = indicator_help(label)
    if not h:
        return None
    return f"{h['what']}\n\n▲ High: {h['high']}\n▼ Low: {h['low']}"


def info_icon_html(label: str, *, align: str = "right") -> str:
    """A small ⓘ with a hover tooltip, or '' when the label has no entry.

    ``align="left"`` opens the tooltip leftwards (for icons near the right edge).
    """
    text = help_text(label)
    if not text:
        return ""
    body = escape(text).replace("\n", "<br>")
    cls = "info-tip tip-left" if align == "left" else "info-tip"
    return f'<span class="{cls}" tabindex="0">ⓘ<span class="info-tip-body">{body}</span></span>'


# ---------------------------------------------------------------- charts

CHARTS: dict[str, str] = {
    # Macro Dashboard
    "dash.policy_path": (
        "Each point starts a SOFR reference quarter; the line is the three-month average rate markets "
        "price for that quarter, and the band is the 25th–75th percentile range. A line sloping "
        "down = markets price rate cuts; up = hikes. Wider bands = more uncertainty."
    ),
    "dash.three_lenses": (
        "The three inputs of the composite over 30 years, with recessions shaded grey. Watch for "
        "the recession probability rising, the labor line (σ) falling below 0, and the 10y–3m "
        "spread dropping below 0. Recessions usually follow when all three turn together."
    ),
    "dash.cape": (
        "CAPE since 1950 with its median (dotted) and famous peaks. The level says little about "
        "when a downturn comes, but readings far above the median have been followed by weak "
        "10-year returns and larger falls in recessions (shaded)."
    ),
    "dash.cape_return": (
        "Each dot is a past month: CAPE then (x-axis) vs. the real S&P 500 return over the next "
        "10 years (y-axis). The fitted curve shows the historical relationship; the highlighted "
        "point is where today's CAPE puts the implied return. Scatter around the line = uncertainty."
    ),
    "dash.fin_conditions": (
        "Left axis: three financial-stress indices (0 = average, above the dashed line at 1 = "
        "stress). Right axis: Chicago Fed activity, 3-month average (below −0.7 = recession zone). "
        "Danger pattern: stress lines rising while activity falls."
    ),
    # Recession
    "rec.history": (
        "Recession-start probability over time for the 3-model ensemble and the BIC model, with "
        "NBER recessions shaded. Good models rise *before* the grey bars. Readings above 30% "
        "are a warning, above 50% elevated."
    ),
    "rec.model_compare": (
        "Today's probability from each model side by side. If the bars cluster, the models agree "
        "and the headline is more trustworthy; a wide spread means the signal depends on which "
        "indicators you believe."
    ),
    "rec.percentiles": (
        "Where each driver of the BIC model sits versus its own history (0 = lowest ever, "
        "100 = highest). Extremes in the risk-raising direction explain a high probability."
    ),
    # Growth
    "growth.headline": (
        "Quarterly real GDP growth (line, annualized %) with the Atlanta Fed GDPNow estimate for "
        "the current quarter as a separate marker. Below 0 = the economy shrank that quarter; two "
        "negative quarters is the popular (not official) recession rule."
    ),
    "growth.contributions": (
        "How much each part of the economy added to (right) or subtracted from (left) the latest "
        "quarter's GDP growth, in percentage points. Consumption is ~70% of GDP, so it usually "
        "dominates; inventories and net exports are volatile and often reverse next quarter."
    ),
    "growth.contrib_history": (
        "Stacked contributions over the last 16 quarters. Shows which engine is driving growth "
        "and whether it is rotating (e.g. from consumers to government)."
    ),
    "growth.wei": (
        "Dallas Fed Weekly Economic Index, scaled to read like year-on-year GDP growth. Gives a "
        "weekly read long before GDP is published; a fast drop toward 0 is an early warning."
    ),
    "growth.factor": (
        "Coincident growth factor: payrolls, industrial production, retail sales and real "
        "consumption (year-on-year), standardized and averaged. 0 = trend growth; below −1.5 "
        "has been typical of recessions (shaded)."
    ),
    "growth.factor_validation": (
        "Each dot is a quarter: the coincident factor (x) vs. actual GDP growth (y). A tight upward "
        "pattern shows historical co-movement, not validated real-time forecasting skill."
    ),
    "growth.vs_risk": (
        "Coincident factor (left axis, today's growth) vs. recession probability (right axis, "
        "next 12 months). Danger: growth falling while the probability rises."
    ),
    # Credit
    "credit.composite": (
        "Credit-stress composite over time (0 = average, in standard deviations) with recessions "
        "shaded. Credit stress typically rises before and during recessions."
    ),
    "credit.drivers": (
        "Today's reading of each credit input in standard deviations from its average. Bars to "
        "the right add stress; bars to the left reduce it. Shows what is driving the composite."
    ),
    "credit.liquidity": (
        "Fed overnight reverse repo (ON RRP) balance in $ trillions: spare cash parked at the Fed. "
        "A falling balance drains the cushion; near zero, further Fed balance-sheet shrinkage "
        "starts to pull reserves from banks, raising the risk of funding strain."
    ),
    "credit.clo": (
        "Year-on-year change in CLOs outstanding (packaged leveraged loans), Fed Z.1 data, "
        "quarterly with ~10-week lag. Growth = credit to riskier companies expanding; "
        "contraction = that credit channel shrinking."
    ),
    "credit.vs_risk": (
        "Credit stress (left) vs. recession probability (right). When both rise together, the "
        "financial and macro signals confirm each other."
    ),
    # Pulse
    "pulse.breadth": (
        "Share of the 10 labor indicators below trend (level) and deteriorating over 3 months "
        "(momentum). Momentum usually turns first; when both climb above ~60–70%, labor "
        "weakness is broad, as in past recessions (shaded)."
    ),
    # Labor
    "labor.composite": (
        "The labor composite (z-score) over time with regime bands. Above 0 = stronger than "
        "usual; dips below −1 have lined up with recessions (shaded)."
    ),
    "labor.breakdown": (
        "Each indicator's current contribution, signed so right = strong labor market and "
        "left = weak. Shows which parts of the labor market drive the composite."
    ),
    "labor.sahm": (
        "Sahm Rule over time. Crossing the dashed 0.5 pp line has marked the start of every "
        "recession since 1970, usually within a few months."
    ),
    "labor.wages": (
        "Median wage growth (12-month average) vs. its long-run average. Well above it = tight "
        "labor market and inflation pressure; falling fast = labor demand cooling."
    ),
    "labor.diffusion": (
        "Share of labor indicators with a positive (stronger-than-average) reading. Falling below "
        "~30% has accompanied recessions; above 70% = broad strength."
    ),
    "labor.small_multiples": (
        "One mini chart per labor indicator, all as z-scores (0 = average, signed so up = stronger). "
        "Lets you see which indicators are leading a turn."
    ),
    "labor.beveridge": (
        "Job openings (y) vs. unemployment rate (x). Moving down and to the right = labor demand "
        "falling and unemployment rising (recession path). Down and left = 'soft landing': "
        "openings fall without job losses."
    ),
    # Yield curve
    "curve.funding": (
        "Overnight rates: SOFR, effective fed funds, 1-month T-bill, with interest on reserves "
        "(IORB) as the Fed's floor. They should move together; SOFR jumping above the others = "
        "cash shortage in money markets."
    ),
    "curve.sofr_effr": (
        "SOFR minus fed funds in basis points. Normally a few bp. Spikes past the dashed "
        "95th-percentile line signal repo-market strain (as in Sept 2019)."
    ),
    "curve.term_structure": (
        "Treasury yields by maturity today vs. 3 and 12 months ago. Upward-sloping = normal. "
        "A downward slope (short above long) = inverted, a classic recession warning. Compare "
        "lines to see whether short or long rates are moving."
    ),
    "curve.maturity_history": (
        "Full history of the selected Treasury yield. Use it to put today's level in context."
    ),
    "curve.maturity_distribution": (
        "How often each yield level has occurred in history; the marker shows today. "
        "Near the right tail = yields high by historical standards."
    ),
    "curve.spreads": (
        "The three curve spreads over time with recessions shaded. Dips below 0 (inversions) "
        "preceded every recession; the recession often starts once the spread re-steepens."
    ),
    "curve.spread_distribution": (
        "How often each spread level has occurred; the marker shows today. Readings in the "
        "negative tail are historically rare and have been recession warnings."
    ),
    "curve.inversions": (
        "10y–3m spread with inversion episodes highlighted. The table below lists each episode "
        "and whether a recession followed."
    ),
    "curve.heatmap": (
        "Yields by maturity (rows) over time (columns); brighter = higher. Horizontal bands of "
        "colour = parallel moves; when short maturities (top) are brighter than long ones, the "
        "curve is inverted."
    ),
    "curve.pca_loadings": (
        "Principal components of the curve. PC1 (flat line) = level, all yields moving together. "
        "PC2 (sloped) = slope, short vs. long. PC3 (humped) = curvature. Percentages = share of "
        "all yield moves each explains."
    ),
    "curve.pca_scores": (
        "Cumulative level / slope / curvature moves over time. A falling slope score = curve "
        "flattening or inverting."
    ),
    # Policy path
    "rate.fan": (
        "Option-implied three-month average SOFR for each reference quarter (mean and mode) "
        "with the 25th–75th percentile band, from SOFR options. Downward slope = cuts priced."
    ),
    "rate.path_shift": (
        "Today's implied path vs. earlier snapshots. A path that has shifted down = markets now "
        "expect more or earlier cuts than before (often after weak data)."
    ),
    "rate.heatmap": (
        "Exported probability (colour) of each rate range (rows) for each reference quarter "
        "(columns). Unshown tails mean each column may total less than 100%."
    ),
    # AI Bubble
    "ai.builders_leaders": (
        "Levered builders ÷ chip leaders, rebased to 100, with a 50-day average. A falling line = "
        "the debt-funded builders are losing ground to the suppliers. In 2000 this kind of split "
        "(CLECs and dot-coms falling while Cisco held up) came months before the leaders broke."
    ),
    "ai.groups": (
        "Equal-weight performance of each watchlist group over the last 12 months, rebased to 100. "
        "Shows which part of the AI chain is leading or cracking. Late listings join on their "
        "first trading day."
    ),
    "ai.month_moves": (
        "1-month price change for each of the 20 AI names. Red bars = falling. A wall of red in "
        "the levered builders with green in the chip leaders = the 2000 pattern."
    ),
    "ai.breadth": (
        "Share of the 20 AI names above their 50-day (short trend) and 200-day (long trend) "
        "averages. The dashed lines mark the 60% WATCH and 40% ALERT levels for the 200-day line. "
        "Breadth falling while the indices make new highs = narrowing leadership."
    ),
    "ai.search_attention": (
        "Google search attention for the typed terms in the selected region and rolling window. "
        "Look for attention surges and compare terms within one query. Google jointly scales "
        "the series so the peak is 100; a different query is scaled again. These are relative "
        "search-interest scores, not search counts or an investment signal. Open circles "
        "mark incomplete periods and gaps mark unavailable readings."
    ),
}


def chart_help(chart_id: str) -> None:
    """Render a small 'How to read this chart' line with a hover explanation."""
    import streamlit as st

    text = CHARTS.get(chart_id)
    if not text:
        return
    st.markdown(
        '<div class="label-tiny" style="margin:-8px 0 12px 0;">How to read this chart</div>',
        help=text,
        unsafe_allow_html=True,
    )
