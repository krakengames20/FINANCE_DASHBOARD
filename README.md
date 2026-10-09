# U.S. Macro Dashboard

> A unified view of U.S. recession risk through three complementary macro lenses.

![status](https://img.shields.io/badge/status-live-5ba3a3)
![python](https://img.shields.io/badge/python-3.11+-d4a574)
![license](https://img.shields.io/badge/license-MIT-6b7280)

[Methodology notebook](notebooks/methodology.ipynb)

## What this is

A single-indicator recession model gives you a precise number and the false comfort of a precise number. The 10-year/3-month yield curve has the best track record of any single signal in the post-war U.S. sample, and it has nonetheless run hot for stretches when the rest of the economy was demonstrably fine. Street estimates routinely disagree by twenty or thirty percentage points without disclosing what is driving the spread.

The dashboard presents three complementary lenses. A three-model recession-start ensemble (local term-spread, Wright-style, and BIC-selected probits) estimates the probability of an NBER peak within 12 months, with the frozen Estrella–Mishkin point-horizon model and Chauvet–Piger coincident nowcast shown separately. A 10-indicator labor composite (LAME) summarizes labor conditions in an inverse-volatility-weighted z-score. The yield-curve module exposes Treasury yields and inversion statistics. The 0–100 headline composite is a judgmental 50/25/25 index, not a calibrated probability.

What's novel — for a public dashboard — is the transparent decomposition. Every cell of the headline can be opened: each model reports its probability, the watchlist reports the exact indicator value that would trip a higher reading, and the LAME breakdown shows the z-score, weight, and contribution of each of its ten indicators. When the models disagree, the disagreement is auditable.

## The three modules

**Recession ensemble.** Three locally re-estimated start-target probits (term spread; spread plus fed funds; sign-constrained BIC model) over a 38-series FRED universe. Members are scored at one common month and averaged equally. Estrella–Mishkin predicts recession in month 12 using frozen 2006 coefficients and a bond-equivalent bill yield; it is excluded from the ensemble and backtest. Chauvet–Piger is a separate coincident nowcast. Brier scores and AUC describe in-sample fits and a walk-forward exercise on revised data with approximate publication lags; this is not a real-time vintage backtest.

**LAME — Labor Aggregate Market Engine.** Ten labor indicators (`UNRATE`, `ICSA`, `CCSA`, `JTSJOL`, `JTSQUR`, `AWHAETP`, `TEMPHELPS`, `PAYEMS`, `U6RATE`, `CIVPART`) are transformed per the registry, signed so that positive means expansionary, z-scored against their own expanding-window history, and combined with inverse-volatility weights computed from a rolling 5-year window.

**Yield curve.** Daily term structure with 11 maturities, three benchmark spreads (10Y−3M, 10Y−2Y, 5Y−2Y), and inversion statistics that condition on inversions lasting more than three months to avoid noise.

## Methodology

The BIC-selected model is built by forward-stepwise selection over the full FRED universe: a candidate feature is accepted only if it improves BIC, does not induce quasi-complete separation, and keeps every coefficient on the economically correct side (lower spread → higher risk; rising unemployment → higher risk; weaker sentiment and contracting credit → higher risk). The NY Fed and Wright models are re-estimated probits on fixed feature sets; Estrella–Mishkin uses frozen 2006 coefficients; Chauvet–Piger is FRED's published `RECPROUSM156N`.

The dependent variable is start-dated: `y_t = 1` if an NBER peak falls in `t+1` through `t+12`. Peak-through-trough months and unobserved future windows are excluded. Estimation starts in 1967. At each walk-forward refit, labels must be at least 12 months old and BIC selection is repeated using that fold's training data. Revised FRED vintages and NBER announcement delays remain sources of look-ahead. The BIC 90% pairs-bootstrap interval is indicative: overlapping labels, serial dependence and selection uncertainty are not captured.

LAME's expanding-window z-scoring requires a minimum of 60 monthly observations. Inverse-volatility weights are computed from the rolling 5-year volatility of each signed z-score; weights are normalised to sum to 1 at every date, with indicators with missing readings dropping out of the basket for that month.

A full **Methodology** tab is built into the dashboard itself — it auto-generates the data sources table from the registry and shows the feature set retained by the live fit, so it cannot drift from the code. See also [`notebooks/methodology.ipynb`](notebooks/methodology.ipynb) for a step-by-step walkthrough including a side-by-side comparison against a naive base-rate baseline.

## Calibration

Brier score and AUC are reported on the Methodology page, both in-sample (section 9) and out-of-sample via the walk-forward backtest (section 10), each with a decile reliability diagram and a base-rate skill score. The Recession page's *Under the Hood* tab shows the per-model comparison and indicator percentiles.

## Quick start

```bash
git clone https://github.com/krakengames20/FINANCE_DASHBOARD.git
cd FINANCE_DASHBOARD
pip install -r requirements.txt
cp .env.example .env
# Add your FRED_API_KEY to .env — free key at https://fred.stlouisfed.org/docs/api/api_key.html
streamlit run app.py
```

On Windows, after installing dependencies into `.venv`, run `./run-dashboard.cmd`.
The launcher uses the project's Python directly, so PowerShell activation is not required.

The first load fetches the FRED panel, fits the three-model ensemble, and runs the walk-forward backtest (tens of seconds); subsequent loads come from Streamlit's cache for six hours. Tests run with `pytest` and do not require network access.

## Recession page — three-model probit ensemble + benchmark

The Recession page shows the three-model start-target ensemble and separate point-horizon and coincident benchmarks. It includes an indicative BIC bootstrap interval, trigger levels, a 24-calendar-month attribution, and an interactive scenario tool. Models labeled NY Fed and Wright are local adaptations, not official institutional forecasts. Signals are research outputs with judgmental bands.

## AI Bubble tab

A daily monitor for the AI trade, built from a dot-com (2000–02) comparison: in 2000 the
debt-funded firms broke first, leadership narrowed, the suppliers reset, and only then did
stress reach credit and the wider market. The tab checks each step.

- **Nine signals**, each CALM / WATCH / ALERT: builders vs leaders, AI breadth, equal-weight
  vs cap-weight, semis trend, volatility (VIX and its term structure), high-yield credit,
  10-year yield, private-credit proxies, and global equities from peak (the rulebook's
  −20% / −30% buying triggers). Thresholds live in `THRESHOLDS` in `src/models/ai_bubble.py`.
- **20 AI-exposed stocks** plus reference rows: price, today / 7-day / 1-month change,
  distance from the 52-week high, trailing and forward P/E, and a 1–10 risk score.
- **Charts**: builders ÷ leaders, group performance, 1-month moves, breadth.
- **Catalyst countdown**: Anthropic S-1, roadshow, listing and lock-up; Big Tech earnings; FOMC.

Edit the stock list, risk scores and event dates in `src/data/ai_watchlist.py`.

Prices and P/E come from Yahoo Finance's public endpoints via `requests` (no extra
dependency; unofficial and delayed ~15 minutes, so for monitoring, not trading). Prices are
cached for 1 hour and P/E for 6 hours; **↻ Refresh data** clears both. If `yfinance` is
installed it is used as a fallback for P/E. Credit and rates reuse the FRED client. The tab
works even if FRED is unavailable.

## Google Trends tab

Type up to five terms and fetch a comparison over a rolling 1 year, 1 month,
or 1 week, with a region selector and CSV download. This independent tab remains
available when FRED or the market-price feed is unavailable.

The Google Trends panel uses a headless browser to load the website's
Explore page and capture its timeline JSON. Install `requirements.txt` and
Chrome or Edge; on a server without either browser, run
`python -m playwright install chromium`. No API key is needed. The
[official API still requires alpha access](https://developers.google.com/search/apis/trends).
Data is fetched only when **Fetch trends** is pressed and successful queries
are cached for 1 hour, including a local cache shared with the sidecar under
`.cache/google_trends/`. A dedicated browser profile under
`.cache/google_trends/browser_profile/` saves cookies across restarts; it does
not use your personal Chrome profile. Browser processes close after each fetch.
The sidecar and dashboard share a process lock and allow at most one fresh
fetch every 30 seconds. Only the timeline is requested: related widgets and
automatic retries are suppressed. Google refusals pause browser fetching for
30 minutes across processes; this is a local pause, not a guaranteed Google
reset time. Browser fetching can still receive an IP-level 429 or a verification
challenge, in which case it stops. Failed updates retain the previous chart
and can use the same query's cached result for up to seven days, with a visible
warning and the original terms, window, region, and fetch time.

The original direct HTTP collector remains available for diagnostic checks
with `--provider http`; it honors `HTTPS_PROXY` / `HTTP_PROXY`. The browser
uses Chrome/Edge's normal network configuration.

Scores are relative search interest, jointly normalized to 0–100 for the
selected query, not search counts. Different windows or term sets are not
directly comparable. Google chooses the sampling interval (normally weekly
for a year, daily for a month, hourly for a week); unfinished periods are
marked with open circles, and missing readings appear as gaps.

The standalone sidecar remains available for independent testing:

```powershell
.\.venv\Scripts\python.exe -m streamlit run trends_sidecar.py --server.port 8511
# Optional live check of all three windows; saves CSVs under .cache/google_trends
.\.venv\Scripts\python.exe scripts/check_google_trends.py
# Compare the original HTTP transport explicitly (also contacts Google)
.\.venv\Scripts\python.exe scripts/check_google_trends.py --provider http --window "1 year"
# Offline collector, chart, and interaction tests
.\.venv\Scripts\python.exe -m pytest tests/test_google_trends.py tests/test_google_trends_browser.py
# Real headless browser against local fixture data; does not contact Google
.\.venv\Scripts\python.exe scripts/check_google_trends_browser.py
```

## Data notes

- Recession dates are sourced live from FRED's `USREC` (NBER-based recession indicator), falling back to the bundled `data/nber_recessions.csv` if the fetch is unavailable.
- The probit model drops any candidate feature covering less than 80% of the target window, so short-history series (e.g. JOLTS from 2000) don't shrink the estimation sample.
- Non-monthly series are resampled to month-start (weekly→mean, daily→last, quarterly→forward-fill) before being aligned into the monthly panel the probit ensemble consumes.
- The **Policy Path** tab reads a bundled CSV (`data/market_probability_tracker.csv`) built from the [Atlanta Fed Market Probability Tracker](https://www.atlantafed.org/cenfis/market-probability-tracker)'s *MPT Historical Data* (`.xlsx`) export — the market-implied distribution of the FOMC policy rate from CME SOFR options. A scheduled GitHub Action (`.github/workflows/refresh-market-probability.yml`) refreshes it daily: it downloads the `.xlsx`, validates it through the parser, and commits a new CSV only when the data changes (which redeploys the app). If the source blocks automated access, the last committed snapshot is served and can be refreshed manually by replacing the file; the tab and dashboard card show the snapshot **as-of date** so staleness is visible. Enabling it requires *Settings → Actions → General → Workflow permissions → Read and write*.

## Disclaimer

This is a research project. Not investment advice. No warranty.

## License

MIT — see [LICENSE](LICENSE).

Financial verification completed on 9 October 2026. See `docs/financial_model_audit_2026-10-09.html` for findings, remaining limitations, and the source checks. Reproduce live data checks with `.venv\Scripts\python.exe scripts/audit_financial_data.py`; add `--cached` to reuse the saved audit snapshot without network calls.
