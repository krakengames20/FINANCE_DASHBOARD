"""Interpretation checks: growth vs speed, price levels, gaps and dates."""
import numpy as np
import pandas as pd
import pytest
from src.models.business_cycle import GDP_ID, GDI_ID, business_cycle_overview


def inputs():
    quarters = pd.date_range('2026-01-01', periods=2, freq='QS')
    headline = {GDP_ID: pd.Series([3.4, 2.2], index=quarters), GDI_ID: pd.Series([2.8, 2.0], index=quarters)}
    months = pd.date_range('2025-08-01', '2026-08-01', freq='MS')
    panel = pd.DataFrame({'CFNAIMA3': np.linspace(-.4, .2, len(months)), 'CFNAIDIFF': np.linspace(-.4, .1, len(months))}, index=months)
    prices = pd.Series(100 * np.cumprod([1.] + [1.003] * 9 + [1.001] * 3), index=months)
    return panel, headline, prices


def report(panel=None, headline=None, prices=None, today='2026-10-09'):
    p, h, c = inputs()
    return business_cycle_overview(p if panel is None else panel, h if headline is None else headline, c if prices is None else prices, today=today)


def cards(result):
    return {c['key']: c for c in result['cards']}


def test_growth_can_slow_without_contracting_and_monthly_evidence_can_disagree():
    result = report()
    c = cards(result)
    assert c['activity']['answer'] == 'Expanding'
    assert c['momentum']['answer'] == 'Slowing'
    assert c['activity']['date'] == 'Q2 2026'
    assert c['breadth']['date'] == 'Aug 2026'
    assert any('does not mean' in note for note in result['notes'])
    assert any('other way' in note for note in result['notes'])


def test_rising_price_index_can_mean_easing_inflation():
    _, _, prices = inputs()
    assert prices.diff().dropna().gt(0).all()
    c = cards(report(prices=prices))['inflation']
    assert c['answer'] == 'Easing'
    assert '1.2% annual pace' in c['explanation']
    assert '3.66%' in c['evidence'][0]
    assert any('does not mean prices are falling' in line for line in c['evidence'])


def test_negative_activity_index_does_not_override_positive_gdp():
    panel, _, _ = inputs()
    panel['CFNAIMA3'] = -.5
    assert cards(report(panel=panel))['activity']['answer'] == 'Expanding'


def test_income_confirmation_uses_same_quarter_and_surfaces_disagreement():
    _, headline, _ = inputs()
    headline[GDI_ID].iloc[-1] = -1
    assert any('opposite directions' in n for n in report(headline=headline)['notes'])
    headline[GDI_ID].iloc[-1] = np.nan
    c = cards(report(headline=headline))['activity']
    assert 'No income-side estimate' in c['evidence'][1] and 'Q2 2026' in c['evidence'][1]


def test_missing_gdp_quarter_is_not_skipped_for_speed_comparison():
    _, headline, _ = inputs()
    headline[GDP_ID] = pd.Series([3., np.nan, 2.], index=pd.date_range('2025-10-01', periods=3, freq='QS'))
    c = cards(report(headline=headline))
    assert c['activity']['available'] and not c['momentum']['available']


@pytest.mark.parametrize('column,key', [('CFNAIDIFF', 'breadth'), ('prices', 'inflation')])
def test_missing_month_prevents_a_false_comparison(column, key):
    panel, _, prices = inputs()
    if column == 'prices':
        prices.loc['2026-04-01'] = np.nan
    else:
        panel.loc['2026-05-01', column] = np.nan
    c = cards(report(panel=panel, prices=prices))[key]
    assert not c['available'] and c['answer'] == 'Not enough data'


def test_stale_and_missing_data_do_not_produce_a_positive_cycle_label():
    old = report(today='2028-10-09')
    assert all(c['answer'] == 'Out of date' for c in old['cards'])
    assert not any(c['available'] for c in old['cards'])
    empty = business_cycle_overview(pd.DataFrame(), {}, None, today='2026-10-09')
    assert not any(c['available'] for c in empty['cards'])
    assert 'not enough current evidence' in empty['summary']


def test_future_or_incomplete_period_is_not_a_reported_observation():
    panel, headline, prices = inputs()
    headline[GDP_ID].loc[pd.Timestamp('2026-10-01')] = -30
    panel.loc[pd.Timestamp('2026-10-01')] = -5
    prices.loc[pd.Timestamp('2026-10-01')] = 999
    c = cards(report(panel=panel, headline=headline, prices=prices))
    assert c['activity']['date'] == 'Q2 2026'
    assert c['breadth']['date'] == c['inflation']['date'] == 'Aug 2026'


def test_invalid_price_levels_withhold_inflation_comparison():
    _, _, prices = inputs()
    prices.loc['2026-06-01'] = -10
    assert not cards(report(prices=prices))['inflation']['available']


def test_flat_growth_and_steady_inflation_are_not_called_acceleration():
    panel, headline, prices = inputs()
    headline[GDP_ID].iloc[:] = [2., 2.1]
    prices.iloc[:] = 100 * 1.002 ** np.arange(len(prices))
    c = cards(report(panel=panel, headline=headline, prices=prices))
    assert c['momentum']['answer'] == c['inflation']['answer'] == 'Little change'


def test_partial_inputs_leave_other_answers_usable():
    c = cards(report(headline={}))
    assert not c['activity']['available']
    assert c['breadth']['available'] and c['inflation']['available']


def test_overview_renders_and_evidence_buttons_navigate_offline():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from src.ui.business_cycle import render_report
from src.models.business_cycle import business_cycle_overview
import pandas as pd
render_report(business_cycle_overview(pd.DataFrame(), {}, None, today="2026-10-09"))
st.text(st.session_state.get("pending_nav", ""))
''').run()
    assert not app.exception
    assert len([m for m in app.markdown if 'class="panel"' in m.value]) == 4
    app.button(key='cycle_growth').click().run()
    assert not app.exception and app.text[-1].value == 'Growth'
    app.button(key='cycle_breadth').click().run()
    assert app.text[-1].value == 'Pulse'
