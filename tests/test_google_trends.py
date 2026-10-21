"""Offline contract tests for the local collector and standalone Trends panel."""

import datetime as dt
import json
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from src.data import google_trends as gt
from src.ui.views import google_trends as view


def timeline(values=None):
    return {"default": {"timelineData": [
        {"time": "1791244800", "value": values or [50, 0], "hasData": [True, False]},
        {"time": "1791331200", "value": [100, 20], "hasData": [True, True], "isPartial": True},
    ]}}


def result(terms=("ChatGPT", "Claude"), window="1 year", geo="US"):
    query = gt.build_query(terms, window, geo)
    values, partial = gt.parse_timeline(timeline(), query)
    return gt.TrendsResult(query, values, partial, dt.datetime.now(dt.timezone.utc))


@pytest.mark.parametrize("window,timeframe", list(gt.WINDOWS.items()))
def test_rolling_windows_and_encoded_query(window, timeframe):
    query = gt.build_query('  AI bubble, ChatGPT, chatgpt, C++ & AI  ', window, "us")
    assert query.terms == ("AI bubble", "ChatGPT", "C++ & AI")
    assert query.timeframe == timeframe
    params = parse_qs(urlparse(query.explore_url).query)
    assert params["q"] == ["AI bubble,ChatGPT,C++ & AI"]
    assert params["date"] == [timeframe]


@pytest.mark.parametrize("terms", ["", " , ", "a,b,c,d,e,f", "a" * 101, "line\nbreak"])
def test_bad_terms_rejected(terms):
    with pytest.raises(ValueError):
        gt.build_query(terms, "1 week")


def test_quoted_phrase_and_worldwide():
    query = gt.build_query('"AI, bubble", Nvidia', "1 month", "")
    assert query.terms == ("AI, bubble", "Nvidia")
    assert query.geo == ""
    with pytest.raises(ValueError):
        gt.build_query("AI", "forever")
    with pytest.raises(ValueError):
        gt.build_query("AI", "1 year", "bad&region")


@pytest.mark.parametrize("prefix", ["", ")]}'\n", ")]}'\r\n", ")]}' ,\n", "\ufeff )]}'\n"])
def test_xssi_variants(prefix):
    assert gt.decode_payload(prefix + '{"widgets": []}') == {"widgets": []}


@pytest.mark.parametrize("body", ["<html>blocked</html>", "[]", "", "null"])
def test_unexpected_response(body):
    with pytest.raises(gt.TrendsError):
        gt.decode_payload(body)


def test_missing_data_and_partial_period_preserved():
    data = result()
    assert pd.isna(data.values.iloc[0, 1])
    assert data.values.iloc[1, 0] == 100
    assert data.partial.tolist() == [False, True]
    assert str(data.values.index.tz) == "UTC"
    fig = view.interest_chart(data)
    assert fig.layout.yaxis.range == (0, 105)
    assert fig.data[0].connectgaps is False
    assert fig.data[1].marker.symbol == "circle-open"


def test_arbitrary_term_names_and_duplicate_timestamps():
    query = gt.build_query("time,_partial", "1 year")
    payload = timeline()
    payload["default"]["timelineData"].append(payload["default"]["timelineData"][0] | {"value": [12, 34], "hasData": [True, True]})
    values, flags = gt.parse_timeline(payload, query)
    assert list(values.columns) == ["time", "_partial"]
    assert values.iloc[0].tolist() == [12, 34]
    assert len(flags) == 2


@pytest.mark.parametrize("payload", [{}, {"default": {"timelineData": []}}, timeline([101, 0]), timeline([5])])
def test_empty_or_malformed_timeline(payload):
    with pytest.raises(gt.TrendsError):
        gt.parse_timeline(payload, gt.build_query("ChatGPT,Claude", "1 year"))


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response(payload=None, status=200):
    return SimpleNamespace(status_code=status, text=")]}'\n" + json.dumps(payload or {}))


def widget():
    return response({"widgets": [{"id": "TIMESERIES", "request": {"time": "test"}, "token": "test-token"}]})


def test_cookie_reused_and_comparison_terms_sent_together(monkeypatch):
    session = FakeSession([response(), widget(), response(timeline()), widget(), response(timeline())])
    monkeypatch.setattr(gt.requests, "Session", lambda: session)
    client = gt.TrendsClient()
    first = client.fetch(gt.build_query("ChatGPT,Claude", "1 week", ""))
    second = client.fetch(gt.build_query("ChatGPT,Claude", "1 month", "US"))
    assert first.query.geo == "" and second.query.geo == "US"
    assert len(session.calls) == 5  # warmup only once, then two requests per query
    sent = json.loads(session.calls[1][1]["params"]["req"])
    assert sent["comparisonItem"] == [
        {"keyword": "ChatGPT", "geo": "", "time": "now 7-d"},
        {"keyword": "Claude", "geo": "", "time": "now 7-d"},
    ]
    assert all(call[1]["timeout"] == gt.TIMEOUT for call in session.calls)


@pytest.mark.parametrize("status", [403, 429])
def test_refusal_pauses_future_requests_without_retries(monkeypatch, status):
    session = FakeSession([response(), widget(), response(status=status)])
    monkeypatch.setattr(gt.requests, "Session", lambda: session)
    client = gt.TrendsClient()
    query = gt.build_query("ChatGPT,Claude", "1 year")
    with pytest.raises(gt.TrendsError):
        client.fetch(query)
    with pytest.raises(gt.TrendsError, match="paused"):
        client.fetch(query)
    assert len(session.calls) == 3


@pytest.mark.parametrize("failure,match", [(requests.Timeout(), "timed out"), (requests.ConnectionError("https://user:secret@proxy"), "Could not connect")])
def test_network_errors_are_safe_and_bounded(monkeypatch, failure, match):
    session = FakeSession([failure])
    monkeypatch.setattr(gt.requests, "Session", lambda: session)
    with pytest.raises(gt.TrendsError, match=match) as exc:
        gt.TrendsClient().fetch(gt.build_query("AI", "1 year"))
    assert "secret" not in str(exc.value)
    assert len(session.calls) == 1


@pytest.mark.parametrize("widgets", [None, {}, [None], [{"id": "TIMESERIES", "token": "x", "request": "wrong"}]])
def test_changed_widgets_fail_cleanly(monkeypatch, widgets):
    session = FakeSession([response(), response({"widgets": widgets})])
    monkeypatch.setattr(gt.requests, "Session", lambda: session)
    with pytest.raises(gt.TrendsError):
        gt.TrendsClient().fetch(gt.build_query("AI", "1 year"))


def app():
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "trends_sidecar.py", default_timeout=10).run()


def test_sidecar_does_not_fetch_on_load_or_input_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(view, "_load", lambda query: calls.append(query))
    at = app()
    assert not at.exception
    at.text_input[0].set_value("Nvidia, AI bubble").run()
    assert calls == []
    assert "fetch" in at.info[0].value


def test_sidecar_success_then_provider_failure_retains_labeled_chart(monkeypatch):
    monkeypatch.setattr(view, "_load", lambda query: result())
    at = app()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 1
    assert at.session_state["ai_trends_result"].query.window == "1 year"
    def fail(query):
        raise gt.TrendsError("Google is rate-limiting this connection.")
    monkeypatch.setattr(view, "_load", fail)
    at.text_input[0].set_value("Nvidia")
    at.button[0].click().run()
    assert not at.exception
    assert "rate-limiting" in at.warning[0].value
    assert len(at.get("plotly_chart")) == 1
    assert any("previous successful" in c.value for c in at.caption)
    assert at.session_state["ai_trends_result"].query.terms == ("ChatGPT", "Claude")


def test_invalid_input_never_reaches_provider(monkeypatch):
    def unexpected(query):
        pytest.fail("invalid query reached the provider")
    monkeypatch.setattr(view, "_load", unexpected)
    at = app()
    at.text_input[0].set_value(" , ")
    at.button[0].click().run()
    assert not at.exception
    assert "one and five" in at.warning[0].value


@pytest.mark.parametrize("fred_down", [False, True])
def test_google_trends_tab_routes_with_and_without_fred(monkeypatch, fred_down):
    calls = []
    monkeypatch.setattr(view, "_load", lambda query: calls.append(query) or result())
    model_patch = "side_effect=RuntimeError('FRED offline')" if fred_down else "return_value={}"
    script = f"""
import app as dashboard_app
from unittest.mock import patch
import pandas as pd
with patch.object(dashboard_app, '_build_models', {model_patch}), \\
     patch.object(dashboard_app, '_load_probit_report', return_value={{}}), \\
     patch.object(dashboard_app, '_load_market_prob', return_value=pd.DataFrame()), \\
     patch.object(dashboard_app, '_header'), \\
     patch.object(dashboard_app, '_data_status_bar'), \\
     patch.object(dashboard_app, '_nav', return_value='Google Trends'):
    dashboard_app.main()
"""
    at = AppTest.from_string(script, default_timeout=10).run()
    assert not at.exception
    assert at.text_input[0].label == "Search terms"
    assert not calls
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 1
    assert len(calls) == 1


def test_disk_cache_shared_and_preserves_original_timestamp(monkeypatch, tmp_path):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)
    data = result()
    calls = []
    monkeypatch.setattr(gt, "_client", lambda: SimpleNamespace(fetch=lambda q: calls.append(q) or data))
    first = gt.fetch_interest(data.query)
    second = gt.fetch_interest(data.query)
    assert calls == [data.query]
    assert second.fetched_at == first.fetched_at
    pd.testing.assert_frame_equal(first.values, second.values)
    pd.testing.assert_series_equal(first.partial, second.partial)
    gt.fetch_interest(data.query, refresh=True)
    assert len(calls) == 2


@pytest.mark.parametrize("age", [dt.timedelta(hours=2), dt.timedelta(hours=-1)])
def test_expired_or_future_disk_cache_is_replaced(monkeypatch, tmp_path, age):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)
    old = result()
    old.fetched_at -= age
    gt._write_cache(old)
    fresh = result()
    calls = []
    monkeypatch.setattr(gt, "_client", lambda: SimpleNamespace(fetch=lambda q: calls.append(q) or fresh))
    assert gt.fetch_interest(fresh.query).fetched_at == fresh.fetched_at
    assert calls == [fresh.query]


def test_corrupt_cache_and_readonly_cache_do_not_break_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path)
    data = result()
    gt._cache_path(data.query).write_text("broken", encoding="utf-8")
    monkeypatch.setattr(gt, "_client", lambda: SimpleNamespace(fetch=lambda q: data))
    assert gt.fetch_interest(data.query) is data
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file", encoding="utf-8")
    monkeypatch.setattr(gt, "CACHE_DIR", blocked)
    assert gt.fetch_interest(data.query) is data


def test_csv_keeps_terms_matching_metadata_names():
    data = result(("time_utc", "is_partial"))
    header = data.csv_bytes().decode("utf-8").splitlines()[0]
    assert header == "_time_utc,time_utc,is_partial,_is_partial"
