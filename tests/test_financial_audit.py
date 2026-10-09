"""Independent accounting, calendar, target and missing-data regression checks."""
import numpy as np
import pandas as pd
import pytest

from src.data import gdp
from src.data.nber import load_nber_recessions
from src.data.series_registry import transform_series
from src.models.composite import composite_risk
from src.models.external import sahm_rule
from src.models.lame import LAME
from src.models.yield_curve import YieldCurve, _nber_peaks
from src.models import recession_probit as rp


def test_claims_average_is_four_weeks_not_four_months():
    idx = pd.date_range('2024-01-06', periods=8, freq='W-SAT')
    values = pd.DataFrame({'ICSA': np.arange(1., 9.) * 1000}, index=idx)
    actual = LAME()._prepare_monthly_values(values).icsa
    assert actual.loc['2024-02-29'] == 6500  # last four weeks: 5, 6, 7, 8


def test_yoy_keeps_missing_month_and_does_not_fill_it():
    idx = pd.date_range('2023-01-31', periods=25, freq='ME')
    values = pd.Series(np.arange(100., 125.), index=idx)
    values.iloc[5] = np.nan
    actual = transform_series(values, 'yoy')
    assert actual.loc['2024-01-31'] == pytest.approx(12.)
    assert np.isnan(actual.loc['2024-06-30'])


def test_daily_three_month_average_is_not_one_month_average():
    idx = pd.date_range('2024-01-01', '2024-03-31', freq='D')
    values = pd.Series(idx.month * 10., index=idx)
    assert transform_series(values, 'ma_3m').iloc[-1] == 20.


def test_sahm_uses_previous_three_month_average_minimum():
    idx = pd.date_range('2023-01-01', periods=16, freq='MS')
    # Monthly outlier changes raw unemployment's min, not the smoothed min.
    u = pd.Series([4., 3., 5.] + [4.] * 12 + [3.7], index=idx)
    panel = pd.DataFrame({'UNRATE': u, 'SAHMREALTIME': np.nan})
    assert sahm_rule(panel).iloc[-1] == pytest.approx(-.1)


def test_missing_components_are_unavailable_not_low_risk():
    result = composite_risk(np.nan, np.nan, np.nan)
    assert np.isnan(result['composite'])
    assert result['band'] == 'UNAVAILABLE'


def test_custom_weights_renormalize_only_available_components():
    result = composite_risk(80., np.nan, 0., weights={'ensemble': 50, 'lame': 25, 'curve': 25})
    assert result['composite'] == 70  # 2/3 * 80 + 1/3 * 50
    assert composite_risk(80., 0., 0., weights={'ensemble': 0, 'lame': 0, 'curve': 0})['band'] == 'UNAVAILABLE'


def test_gdp_inventory_is_not_already_inside_investment_component():
    ids = dict(gdp.CONTRIBUTION_SERIES)
    assert 'A007RY2Q224SBEA' in ids  # fixed investment excludes inventory
    assert 'A006RY2Q224SBEA' not in ids


def test_nber_fallback_matches_fred_peak_excluded_convention():
    flags = load_nber_recessions(start='2007-01-01', end='2010-01-01')
    assert not flags.loc['2007-12-01']
    assert flags.loc['2008-01-01']
    assert flags.loc['2009-06-01']
    assert _nber_peaks(flags) == [pd.Timestamp('2007-12-01')]


def test_recent_inversion_is_pending_not_a_false_positive():
    idx = pd.date_range('2024-01-01', '2024-12-31', freq='D')
    panel = pd.DataFrame({'DGS10': 3., 'DGS3MO': 4.}, index=idx)
    flags = pd.Series(False, index=pd.date_range('2023-01-01', '2024-12-01', freq='MS'))
    stats = YieldCurve(panel).inversion_stats(flags)
    assert stats['hit_rate'] == (0, 0)
    assert stats['pending_episodes'] == 1


def test_missing_spread_cannot_be_relabelled_as_yield_curve_model():
    idx = pd.date_range('1970-01-01', periods=360, freq='MS')
    raw = pd.DataFrame({'FEDFUNDS': np.linspace(1., 10., len(idx)), 'USREC': 0.}, index=idx)
    with pytest.raises(RuntimeError, match='SPREAD'):
        rp._prepare(raw)


def test_frozen_benchmark_uses_bond_equivalent_bill_yield():
    raw = pd.DataFrame({'GS10': [5.], 'TB3MS': [4.]}, index=[pd.Timestamp('2024-01-01')])
    # Published bill conversion: 365*d / (360 - 0.91*d).
    spread = 5. - 365. * 4. / (360. - .91 * 4.)
    from scipy.stats import norm
    assert rp.estrella_mishkin_history(raw).iloc[0] == pytest.approx(norm.cdf(-.6045 - .7374 * spread) * 100.)


def test_other_exchange_holidays_do_not_shorten_breadth_window():
    from src.models.ai_bubble import breadth
    dates = pd.date_range('2024-01-01', periods=5, freq='D')
    prices = pd.DataFrame({'US': [10., np.nan, 12., np.nan, 9.], 'JP': 100.}, index=dates)
    result = breadth(prices, ['US'], 3)
    assert result.index.tolist() == [dates[-1]]
    assert result.iloc[0] == 0.


def test_invalid_prices_cannot_create_returns():
    from src.data.market_prices import parse_chart
    payload = {'chart': {'result': [{'timestamp': [1704067200, 1704153600, 1704240000, 1704326400],
                'meta': {'symbol': 'X'}, 'indicators': {'quote': [{'close': [100., 0., -1., np.inf]}]}}]}}
    prices, _ = parse_chart(payload)
    assert prices.tolist() == [100.]


def test_nonconverged_fit_is_not_a_valid_probability(monkeypatch):
    from types import SimpleNamespace
    model = SimpleNamespace(fit=lambda **kwargs: SimpleNamespace(mle_retvals={'converged': False}, params=np.array([1., 1.])))
    monkeypatch.setattr(rp.sm, 'Probit', lambda *args, **kwargs: model)
    with pytest.raises(RuntimeError, match='converge'):
        rp._fit_probit(pd.Series([0., 1.]), pd.DataFrame({'X': [0., 1.]}))


def test_quarterly_resampling_fills_only_its_reference_quarter(monkeypatch):
    from src.data import fred_client
    def fetch(sid, start):
        if sid == 'PCECC96':
            return pd.Series([100.], index=[pd.Timestamp('2024-01-01')])
        if sid == 'GS10':
            return pd.Series([4.] * 6, index=pd.date_range('2024-01-01', periods=6, freq='MS'))
        raise RuntimeError('unavailable')
    monkeypatch.setattr(fred_client, 'fetch_series', fetch)
    result = rp.fetch_probit_panel('2024-01-01')
    assert result.PCECC96.iloc[:3].tolist() == [100.] * 3
    assert result.PCECC96.iloc[3:].isna().all()


def test_credit_yoy_uses_calendar_year_despite_missing_quarter():
    from src.data.credit import yoy
    idx = pd.date_range('2022-01-01', periods=12, freq='QS')
    data = pd.Series(np.arange(100., 112.), index=idx).drop(idx[5])
    result = yoy(data)
    assert result.loc[idx[8]] == pytest.approx((108. / 104. - 1.) * 100.)
    assert idx[9] not in result.index  # comparator quarter is missing


@pytest.mark.parametrize('score,band,shown', [(23, 'ELEVATED', '23'), (np.nan, 'UNAVAILABLE', '—')])
def test_header_keeps_available_and_unavailable_composite_visible(monkeypatch, score, band, shown):
    import app
    captured = []
    monkeypatch.setattr(app, '_composite_now', lambda models: {'composite': score, 'band': band})
    monkeypatch.setattr(app.st, 'markdown', lambda html, **kwargs: captured.append(html))
    app._header({})
    html = ''.join(captured)
    assert 'composite-number' in html
    assert f'>{shown}</div>' in html
    assert band in html
