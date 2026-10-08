"""AI-bubble watchlist: the stocks, signal tickers and dated events the
AI Bubble tab tracks.

Hand-maintained research config, kept in Python (not YAML) so it is typed,
importable without extra dependencies, and checked by tests. Edit this file to
add a stock, change a risk score or move an event date.

Sources for groups, risk scores and events: the FINANCE project's AI-bubble
risk map and bear playbook (Oct 2026). Risk score = expected damage in a "lab
shock" (one frontier lab cuts compute commitments 30–50% or its valuation
halves), 1 = barely affected, 10 = could lose most of its value.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    group: str
    risk: int | None  # 1–10 from the risk map; None = not scored
    why: str
    listed: str | None = None  # ISO date for listings after the ChatGPT launch


@dataclass(frozen=True)
class Event:
    date: dt.date
    label: str
    status: str  # "confirmed" | "reported" | "estimated"


# Groups, in display order.
GROUPS: tuple[str, ...] = (
    "Levered builders",
    "Chips & hardware",
    "Power & grid",
    "Platforms & labs",
    "Reference",
)

# The 20 AI-exposed names, plus reference rows (indices and the two least
# exposed hyperscalers) for context.
STOCKS: tuple[Stock, ...] = (
    # Levered builders: borrowed money against one or two customers.
    Stock(
        "CRWV",
        "CoreWeave",
        "Levered builders",
        9,
        "Debt ≈ 3.4× revenue; Microsoft 67% of 2025 revenue",
        listed="2025-03-28",
    ),
    Stock(
        "ORCL",
        "Oracle",
        "Levered builders",
        9,
        "~50% of $664B backlog is OpenAI; negative free cash flow",
    ),
    Stock("NBIS", "Nebius", "Levered builders", 8, "Debt-funded GPU cloud", listed="2024-10-21"),
    Stock("APLD", "Applied Digital", "Levered builders", 8, "Neocloud / data-centre developer"),
    Stock("IREN", "IREN", "Levered builders", 8, "Ex-bitcoin miner turned AI cloud"),
    Stock(
        "CIFR", "Cipher Digital", "Levered builders", 8, "Ex-miner; leases backstopped by Google"
    ),
    Stock("WULF", "TeraWulf", "Levered builders", 8, "Ex-miner; leases backstopped by Google"),
    # Chips & hardware: capex-stall beta; some now finance their own buyers.
    Stock(
        "NVDA",
        "Nvidia",
        "Chips & hardware",
        7,
        "5 customers = 70% of receivables; guarantees ≤ $108.5B",
    ),
    Stock(
        "AVGO",
        "Broadcom",
        "Chips & hardware",
        8,
        "$161B leases, $42B loan, ≤ $29B backstop to Anthropic",
    ),
    Stock("AMD", "AMD", "Chips & hardware", 7, "OpenAI 6 GW deal paid partly in warrants"),
    Stock("MU", "Micron", "Chips & hardware", 7, "Memory cycle: low P/E at peak earnings"),
    Stock("SMCI", "Super Micro", "Chips & hardware", None, "AI servers; thin margins"),
    Stock("ANET", "Arista", "Chips & hardware", 6, "AI networking; Microsoft and Meta heavy"),
    # Power & grid: priced for a multi-year data-centre backlog.
    Stock("VRT", "Vertiv", "Power & grid", 6, "Data-centre power and cooling"),
    Stock(
        "GEV",
        "GE Vernova",
        "Power & grid",
        6,
        "Turbines and grid; multi-year backlog",
        listed="2024-04-02",
    ),
    Stock("CEG", "Constellation Energy", "Power & grid", 5, "Contracted hyperscaler power"),
    Stock("VST", "Vistra", "Power & grid", 5, "Contracted hyperscaler power"),
    # Platforms & labs: valuation and earnings tied to the labs.
    Stock("PLTR", "Palantir", "Platforms & labs", 7, "AI-premium valuation"),
    Stock(
        "SPCX",
        "SpaceX (incl. xAI)",
        "Platforms & labs",
        7,
        "xAI 17% of 2025 revenue, most of the loss",
        listed="2026-06-12",
    ),
    Stock("AMZN", "Amazon", "Platforms & labs", 7, "Earnings flattered by Anthropic re-mark gains"),
    # Reference rows.
    Stock("^GSPC", "S&P 500", "Reference", 6, "Top 10 ≈ 41% of the index"),
    Stock("^NDX", "Nasdaq-100", "Reference", None, "Cap-weighted tech benchmark"),
    Stock("MSFT", "Microsoft", "Reference", 6, "OpenAI ≈ 32% of commercial backlog"),
    Stock("GOOGL", "Alphabet", "Reference", 5, "Owns ~14% of Anthropic; earnings include gains"),
    Stock("META", "Meta", "Reference", 6, "Self-funded capex; $279B uncommenced leases"),
)

# Baskets used by the signals.
BUILDERS: tuple[str, ...] = ("CRWV", "ORCL", "NBIS", "APLD", "IREN", "CIFR", "WULF")
LEADERS: tuple[str, ...] = ("NVDA", "AVGO", "AMD")
PRIVATE_CREDIT: tuple[str, ...] = ("OWL", "APO", "BIZD", "9984.T")

# Tickers needed only by the signals (not shown in the stock table).
SIGNAL_TICKERS: dict[str, str] = {
    "SPY": "S&P 500 ETF (cap-weighted)",
    "RSP": "S&P 500 equal-weight ETF",
    "QQQ": "Nasdaq-100 ETF (cap-weighted)",
    "QQEW": "Nasdaq-100 equal-weight ETF",
    "SMH": "Semiconductor ETF",
    "ACWI": "MSCI All-Country World ETF",
    "^VIX": "VIX (S&P 500 30-day implied vol)",
    "^VIX3M": "VIX 3-month",
    "^VXN": "Nasdaq-100 implied vol",
    "OWL": "Blue Owl (private credit)",
    "APO": "Apollo (private credit, insurance)",
    "BIZD": "BDC ETF (listed private-credit lenders)",
    "9984.T": "SoftBank Group (Tokyo)",
}

# FRED series the tab reads (already used elsewhere in the dashboard).
FRED_CREDIT: dict[str, str] = {
    "BAMLH0A0HYM2": "High-yield OAS",
    "BAMLC0A0CM": "Investment-grade OAS",
    "BAA10Y": "Baa–10y spread",
    "DGS10": "10-year Treasury yield",
}

# Dated catalysts. "estimated" dates are best guesses; move them as dates firm up.
EVENTS: tuple[Event, ...] = (
    Event(dt.date(2026, 10, 14), "ASML Q3 results · Anthropic investor event", "reported"),
    Event(dt.date(2026, 10, 15), "TSMC Q3 results", "confirmed"),
    Event(dt.date(2026, 10, 26), "Anthropic public S-1 (≥15 days before roadshow)", "estimated"),
    Event(dt.date(2026, 10, 28), "FOMC · Microsoft, Alphabet, Meta Q3", "estimated"),
    Event(dt.date(2026, 10, 29), "US Q3 GDP · Amazon Q3", "estimated"),
    Event(dt.date(2026, 11, 3), "US midterms · AMD and Palantir Q3", "estimated"),
    Event(dt.date(2026, 11, 9), "Anthropic roadshow (week of)", "reported"),
    Event(dt.date(2026, 11, 10), "CoreWeave Q3 · SoftBank results", "estimated"),
    Event(dt.date(2026, 11, 18), "Nvidia Q3 FY27", "estimated"),
    Event(dt.date(2026, 11, 25), "Anthropic listing (target: by this date)", "reported"),
    Event(dt.date(2026, 12, 9), "FOMC · Oracle Q2 FY27", "estimated"),
    Event(dt.date(2026, 12, 10), "Broadcom Q4 FY26", "estimated"),
    Event(dt.date(2026, 12, 16), "Micron Q1 FY27", "estimated"),
    Event(dt.date(2027, 1, 27), "Big Tech Q4: 2027 capex guidance", "estimated"),
    Event(dt.date(2027, 5, 24), "Anthropic lock-up expiry (~180 days after listing)", "estimated"),
)


def table_tickers() -> list[str]:
    return [s.ticker for s in STOCKS]


def all_tickers() -> list[str]:
    """Every Yahoo ticker the tab needs, de-duplicated, in a stable order."""
    seen: dict[str, None] = {}
    for t in table_tickers() + list(SIGNAL_TICKERS):
        seen.setdefault(t, None)
    return list(seen)


def ai_basket() -> list[str]:
    """The 20 AI-exposed names (everything except the reference rows)."""
    return [s.ticker for s in STOCKS if s.group != "Reference"]


def upcoming_events(today: dt.date, limit: int | None = None) -> list[Event]:
    events = sorted((e for e in EVENTS if e.date >= today), key=lambda e: e.date)
    return events[:limit] if limit else events
