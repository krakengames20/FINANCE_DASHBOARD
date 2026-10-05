# Architecture

Sources on the left, what they're computed into on the right. Every FRED call goes through
`src/data/fred_client.py` (`fetch_series` → `fredapi.Fred.get_series`), cached in memory for 6 h.
Full per-series inventory: [`docs/fred_series_audit.csv`](docs/fred_series_audit.csv) (89 series).

```mermaid
flowchart LR
  subgraph SRC[Sources]
    FRED[(FRED API<br/>89 series)]
    ALFRED[(ALFRED vintages<br/>PAYEMS, GDPC1, RSAFS)]
    SHILLER[(Shiller ie_data / GitHub mirror)]
    ATL[(Atlanta Fed MPT xlsx)]
    CSV[(bundled data/*.csv<br/>nber, cape, mpt)]
  end

  subgraph LOAD[Loaders - src/data]
    PANEL[fetch_panel<br/>series_registry: 47 ids<br/>daily/weekly/monthly panel]
    PROBITP[fetch_probit_panel<br/>38 ids incl. USREC<br/>monthly, 1967+]
    CRED[credit.py<br/>stress, liquidity, CLO, household]
    GDP[gdp.py<br/>GDP, GDPNow, GDI, contributions, WEI]
    REV[revisions.py<br/>first vs latest release]
    NBER[nber.py<br/>USREC flags]
    CAPE[cape.py]
    MPT[market_probability.py]
  end

  subgraph MODEL[Models - src/models]
    PROBIT[recession_probit<br/>4 probits -> 12m recession %]
    LAME[LAME<br/>10 labor z-scores -> inv-vol weighted z]
    YC[YieldCurve<br/>term structure, spreads, inversions]
    COMP[composite_risk<br/>50% probit + 25% LAME + 25% curve -> 0-100]
    EW[early_warning ladder]
    MISC[conditions, breadth, external Sahm, market_implied]
    CSTRESS[credit stress z-composite]
    GFAC[coincident growth factor]
  end

  subgraph UI[Tabs - src/ui/views]
    T1[Macro Dashboard]
    T2[Early Warning]
    T3[Recession]
    T4[Yield Curve]
    T5[Credit]
    T6[Labor]
    T7[Growth]
    T8[Pulse]
    T9[Policy Path]
    T10[Methodology]
  end

  FRED --> PANEL & PROBITP & CRED & GDP & NBER
  ALFRED --> REV
  SHILLER --> CAPE
  CSV --> NBER & CAPE & MPT
  ATL -.->|manual refresh script| CSV

  PROBITP --> PROBIT
  NBER --> PROBIT
  PANEL --> LAME & YC & EW & MISC
  PROBIT & LAME & YC --> COMP
  PROBIT & LAME --> EW
  CRED --> CSTRESS
  GDP --> GFAC

  COMP --> T1
  CAPE & MPT & MISC --> T1
  EW --> T2
  PROBIT --> T3
  YC --> T4
  CSTRESS --> T5
  LAME & MISC --> T6
  GFAC & REV --> T7
  MISC & LAME --> T8
  MPT --> T9
  PROBIT & REV --> T10
```

## Persistence and refresh

No database. FRED data lives in Streamlit's in-memory cache and is re-downloaded in full on
each refresh, so FRED itself is the store. The exception is series FRED trims (ICE BofA OAS
keeps 3 years), whose older history is not kept here.

- **Automatic:** all caches, including the fitted models, expire after 6 h; the next page
  load refetches and refits.
- **Manual:** the *Refresh data* button (`app._refresh_all`) re-runs
  `scripts/refresh_market_probability.py` and `scripts/refresh_cape.py`, then clears every cache.
- **Status:** `fred_client.fetch_series` → `src/data/freshness.py` logs each fetch; the header
  shows when data was pulled, and the *Data status* panel lists every series as
  ok / late / failed / discontinued.

## Explanations

`src/ui/glossary.py` holds what-it-is / high / low text per indicator (shown as ⓘ hover
tooltips on cards) and a "how to read this chart" note per chart (`chart_help(id)` under each
chart). Tests fail if a chart is added without a note.

## Recession probit (why it matters here)

It produces the headline 12-month recession probability, which is 50% of the composite score and
drives the Recession, Early Warning and Methodology tabs. Coefficients are estimated live from FRED
data (except Estrella–Mishkin, which is frozen); the composite's 50/25/25 weights and its linear
anchors in `src/models/composite.py` are hand-set.
