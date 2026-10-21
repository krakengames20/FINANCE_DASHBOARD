"""Opt-in financial data audit. Reads live FRED and bundled inputs; never refreshes source files.

python scripts/audit_financial_data.py [--cached]
Results go under .cache/financial_audit. API keys are never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.fred_client import _get_client
from src.data.series_registry import fred_ids
from src.data import credit, gdp, market_probability as mp
from src.models import recession_probit as rp

DESTINATION = ROOT / ".cache" / "financial_audit"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--backtest", action="store_true", help="Also run revised-data walk-forward calibration")
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(fred_ids() + rp.all_series_ids() +
        [sid for sid, _ in gdp.HEADLINE_SERIES + gdp.CONTRIBUTION_SERIES + gdp.HIGHFREQ_SERIES + gdp.COINCIDENT_INPUTS] +
        [sid for sid, _, _ in credit.STRESS_SERIES] +
        [sid for sid, _ in credit.LIQUIDITY_SERIES + credit.CLO_SERIES + credit.HOUSEHOLD_SERIES] +
        ["A007RY2Q224SBEA", "IC4WSA", "SAHMCURRENT", "PCECC96", "TB3MS"]))
    path = DESTINATION / "fred_observations.parquet"
    if args.cached and path.exists():
        panel = pd.read_parquet(path)
        metadata = pd.read_csv(DESTINATION / "fred_metadata.csv").to_dict("records")
    else:
        fred = _get_client()
        frames, metadata = {}, []
        for i, sid in enumerate(ids, 1):
            try:
                s = pd.Series(fred.get_series(sid, observation_start="1950-01-01"), name=sid).sort_index()
                frames[sid] = s
                info = fred.get_series_info(sid)
                clean = s.dropna()
                metadata.append({
                    "series": sid, "title": info.get("title"), "units": info.get("units"),
                    "frequency": info.get("frequency_short"), "seasonal_adjustment": info.get("seasonal_adjustment_short"),
                    "first_obs": str(clean.index.min().date()) if len(clean) else None,
                    "last_obs": str(clean.index.max().date()) if len(clean) else None,
                    "observations": len(clean), "missing": int(s.isna().sum()),
                    "duplicates": int(s.index.duplicated().sum()),
                    "nonfinite": int((~np.isfinite(clean)).sum()),
                })
            except Exception as exc:
                metadata.append({"series": sid, "error": type(exc).__name__})
            if i % 10 == 0 or i == len(ids):
                print(f"FRED checked {i}/{len(ids)}", flush=True)
        panel = pd.DataFrame(frames).sort_index()
        panel.to_parquet(path)
        pd.DataFrame(metadata).to_csv(DESTINATION / "fred_metadata.csv", index=False)
    checks = {"checked_at": pd.Timestamp.now().isoformat(), "fred_series": len(metadata),
              "failed_series": [m['series'] for m in metadata if m.get('error') and pd.notna(m.get('error'))]}
    clean_metadata = pd.DataFrame(metadata)
    checks['data_integrity'] = {
        'duplicate_dates': int(clean_metadata.duplicates.fillna(0).sum()),
        'nonfinite_observations': int(clean_metadata.nonfinite.fillna(0).sum()),
        'frequency_mismatches': [sid for sid, cfg in rp.SERIES_CONFIG.items()
            if cfg.get('freq', 'M') != clean_metadata.set_index('series').loc[sid, 'frequency']],
        'unemployment_missing_months': [str(d.date()) for d in panel.UNRATE.dropna().resample('MS').last().loc[lambda s: s.isna()].index],
    }
    contrib_ids = [sid for sid, _ in gdp.CONTRIBUTION_SERIES]
    for label, columns in (("configured", contrib_ids),
                           ("fixed_investment", ["A007RY2Q224SBEA" if sid == "A006RY2Q224SBEA" else sid for sid in contrib_ids])):
        if set(columns + ["A191RL1Q225SBEA"]).issubset(panel.columns):
            joint = panel[columns + ["A191RL1Q225SBEA"]].dropna()
            residual = joint[columns].sum(axis=1) - joint["A191RL1Q225SBEA"]
            checks[f"gdp_{label}"] = {"quarters": len(joint), "latest_date": str(joint.index[-1].date()),
                "sum_pp": float(joint[columns].iloc[-1].sum()), "gdp_percent_saar": float(joint['A191RL1Q225SBEA'].iloc[-1]),
                "max_abs_residual_pp": float(residual.abs().max()), "latest_residual_pp": float(residual.iloc[-1])}
    df = mp.load_market_probabilities()
    buckets = mp.probability_buckets(df)
    totals = buckets.groupby(["snapshot_date", "meeting_date"])["probability"].sum()
    rates = df[df['field'].str.startswith('Rate:')].pivot_table(index=['snapshot_date','meeting_date'], columns='field', values='value', aggfunc='last')
    checks["market_probability"] = {"rows": len(df), "snapshots": df.snapshot_date.nunique(),
        "last_snapshot": str(df.snapshot_date.max().date()),
        "duplicate_keys": int(df.duplicated(['snapshot_date', 'meeting_date', 'field']).sum()),
        "bucket_groups": len(totals), "bucket_sums_outside_99_9_to_100_1": int(((totals < 99.9) | (totals > 100.1)).sum()),
        "bucket_sum_min_percent": float(totals.min()), "bucket_sum_median_percent": float(totals.median()),
        "bucket_sums_over_100_1": int((totals > 100.1).sum()),
        "bucket_min": float(buckets.probability.min()), "bucket_max": float(buckets.probability.max()),
        "reversed_quantiles": int((rates['Rate: 25th percentile'] > rates['Rate: 75th percentile']).sum())}
    cape = pd.read_csv(ROOT / 'data/cape.csv')
    checks['cape'] = {"rows": len(cape), "duplicates": int(cape.date.duplicated().sum()),
                     "latest": str(cape.date.max()), "nonpositive_cape": int((cape.cape <= 0).sum())}
    if {'real_tr_price', 'cape'}.issubset(cape):
        checks['cape']['nonpositive_real_tr_price'] = int((cape.real_tr_price.dropna() <= 0).sum())
    target_data = pd.DataFrame()
    for sid, info in {**rp.SERIES_CONFIG, **rp.TARGET_SERIES}.items():
        if sid not in panel:
            continue
        s = panel[sid].dropna().loc[rp.OBS_START:]
        frequency = info.get('freq', 'M')
        monthly = s.resample('MS').mean() if frequency == 'W' else s.resample('MS').asfreq() if frequency == 'Q' else s.resample('MS').last()
        target_data[sid] = monthly.reindex(pd.date_range(rp.OBS_START, panel.index.max(), freq='MS')) if target_data.empty else monthly
    # DataFrame construction above must retain the full monthly calendar.
    for sid, cfg in rp.SERIES_CONFIG.items():
        if cfg.get('freq') == 'Q' and sid in target_data:
            target_data[sid] = target_data[sid].groupby(target_data.index.to_period('Q')).ffill()
    if 'USREC' in target_data:
        report = rp.build_report(target_data, bootstrap=0)
        checks['probit'] = {key: report[key] for key in ('ensemble_probability', 'model_probabilities', 'benchmark_probabilities', 'model_as_of', 'bic_selected_features', 'data_through', 'model_metadata')}
        if args.backtest:
            print('Running walk-forward calibration on saved revised observations...', flush=True)
            target = rp.target_series(target_data)
            oos = rp.walk_forward(target_data)
            oos.to_csv(DESTINATION / 'walk_forward.csv')
            checks['walk_forward'] = rp.calibration_stats(oos, target)
            checks['walk_forward']['reliability_curve'] = checks['walk_forward']['reliability_curve'].to_dict('records')
            checks['walk_forward']['cycle_peaks'] = [str(d.date()) for d, _ in rp.nber_turning_points(target_data.USREC)
                if d is not None and oos.index.min() <= d <= oos.index.max()]
            joined = pd.concat([oos.rename('prediction'), target.rename('target')], axis=1).dropna()
            high = joined[joined.prediction >= 90.]
            checks['walk_forward']['predictions_above_90_percent'] = len(high)
            checks['walk_forward']['false_alarms_above_90_percent'] = int((high.target == 0).sum())
    (DESTINATION / 'checks.json').write_text(json.dumps(checks, indent=2, default=str), encoding='utf-8')
    print(json.dumps(checks, indent=2, default=str), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
