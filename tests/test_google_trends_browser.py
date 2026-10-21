"""Browser contracts, shared pacing, cleanup, and stale-data behavior offline."""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright import sync_api

from src.data import google_trends as gt
from src.data import google_trends_browser as browser


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(browser, "BROWSER_DIR", tmp_path / "browser")
    monkeypatch.setattr(browser, "MIN_INTERVAL", 0)
    monkeypatch.setattr(gt, "CACHE_DIR", tmp_path / "cache")
    browser.BROWSER_DIR.mkdir()


def payload():
    return {"default": {"timelineData": [
        {"time": "1791244800", "value": [50, 10], "hasData": [True, True]},
        {"time": "1791331200", "value": [100, 20], "isPartial": True},
    ]}}


class FakePage:
    def __init__(self, status=200, data=None, challenge=False):
        self.status = status
        self.data = payload() if data is None else data
        self.challenge = challenge
        self.url = "about:blank"
        self.visits = []
        self.events = {}
        self.route_handler = None

    def route(self, pattern, handler):
        self.route_handler = handler

    def on(self, name, handler):
        self.events[name] = handler

    def goto(self, url, **kwargs):
        self.url = url
        self.visits.append(url)
        if "/explore?" in url and not self.challenge:
            self.events["response"](SimpleNamespace(
                url=gt.BASE_URL + "/api/widgetdata/multiline", status=self.status,
                text=lambda: ")]}'\n" + json.dumps(self.data),
            ))
        return SimpleNamespace(status=200)

    def locator(self, selector):
        return SimpleNamespace(count=lambda: int(self.challenge))

    def wait_for_timeout(self, ms):
        pytest.fail("An immediately completed/blocked fetch should not keep waiting")


def setup_browser(monkeypatch, page):
    context = SimpleNamespace(pages=[page], close=Mock())
    launcher = Mock(return_value=context)
    monkeypatch.setattr(browser, "_launch_context", launcher)
    class Runtime:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(sync_api, "sync_playwright", Runtime)
    return context, launcher


@pytest.mark.parametrize("window", list(gt.WINDOWS))
def test_browser_returns_valid_comparison_and_closes_context(monkeypatch, window):
    page = FakePage()
    context, _ = setup_browser(monkeypatch, page)
    query = gt.build_query("ChatGPT,Claude", window)
    with browser.request_lock():
        data = browser.BrowserTrendsClient().fetch(query)
    assert data.query == query
    assert data.source == "browser"
    assert data.values.iloc[1].tolist() == [100, 20]
    assert data.partial.tolist() == [False, True]
    assert page.visits[-1] == query.explore_url
    context.close.assert_called_once()


def test_only_one_timeline_request_is_allowed(monkeypatch):
    page = FakePage()
    browser._collect(page, gt.build_query("ChatGPT,Claude", "1 year"))
    timeline_route = SimpleNamespace(
        request=SimpleNamespace(url=gt.BASE_URL + "/api/widgetdata/multiline"),
        continue_=Mock(), abort=Mock(),
    )
    related_route = SimpleNamespace(
        request=SimpleNamespace(url=gt.BASE_URL + "/api/widgetdata/relatedsearches"),
        continue_=Mock(), abort=Mock(),
    )
    page.route_handler(timeline_route)
    page.route_handler(timeline_route)  # Google's automatic retry must be suppressed
    page.route_handler(related_route)
    timeline_route.continue_.assert_called_once()
    timeline_route.abort.assert_called_once()
    related_route.abort.assert_called_once()


@pytest.mark.parametrize("status,challenge", [(429, False), (403, False), (200, True)])
def test_block_persists_across_new_clients_without_launching_again(monkeypatch, status, challenge):
    page = FakePage(status=status, challenge=challenge)
    context, launcher = setup_browser(monkeypatch, page)
    query = gt.build_query("ChatGPT,Claude", "1 year")
    with browser.request_lock():
        with pytest.raises(gt.TrendsRateLimitError):
            browser.BrowserTrendsClient().fetch(query)
    assert browser._state()["blocked_until"] > time.time() + 1700
    with browser.request_lock():
        with pytest.raises(gt.TrendsRateLimitError, match="paused"):
            browser.BrowserTrendsClient().fetch(query)
    launcher.assert_called_once()
    context.close.assert_called_once()


def test_changed_timeline_closes_browser_without_poisoning_cooldown(monkeypatch):
    context, _ = setup_browser(monkeypatch, FakePage(data={"unexpected": []}))
    with browser.request_lock():
        with pytest.raises(gt.TrendsError, match="format changed"):
            browser.BrowserTrendsClient().fetch(gt.build_query("ChatGPT,Claude", "1 year"))
    context.close.assert_called_once()
    assert browser._state()["blocked_until"] == 0


def test_fetch_uses_browser_by_default_and_cache_survives_block(monkeypatch):
    context, launcher = setup_browser(monkeypatch, FakePage())
    gt._client.cache_clear()
    query = gt.build_query("ChatGPT,Claude", "1 year")
    first = gt.fetch_interest(query)
    second = gt.fetch_interest(query)
    assert first.source == second.source == "browser"
    assert first.fetched_at == second.fetched_at
    launcher.assert_called_once()
    context.close.assert_called_once()
    first.fetched_at -= dt.timedelta(hours=2)
    gt._write_cache(first)
    browser._save_state({"last_request": 0, "blocked_until": time.time() + 1800})
    stale = gt.fetch_interest(query)
    assert stale.fetched_at == first.fetched_at
    assert "cached result" in stale.warning
    launcher.assert_called_once()
    # A different query must never inherit this query's cached scores.
    with pytest.raises(gt.TrendsRateLimitError):
        gt.fetch_interest(gt.build_query("Nvidia", "1 year"))
    # A live check bypasses cache, but never bypasses the provider's cooldown.
    with pytest.raises(gt.TrendsRateLimitError):
        gt.fetch_interest(query, refresh=True)


def test_browser_start_failure_is_actionable_and_does_not_leak_details():
    chromium = SimpleNamespace(launch_persistent_context=Mock(side_effect=sync_api.Error("secret proxy URL")))
    with pytest.raises(gt.TrendsError, match="Install Chrome or Edge") as failure:
        browser._launch_context(SimpleNamespace(chromium=chromium))
    assert "secret" not in str(failure.value)
    assert chromium.launch_persistent_context.call_count == 3


def test_process_lock_prevents_sidecar_and_dashboard_overlap():
    script = '''
import sys
from pathlib import Path
from src.data import google_trends_browser as b
b.BROWSER_DIR = Path(sys.argv[1])
with b.request_lock():
    print('acquired', flush=True)
'''
    with browser.request_lock():
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(browser.BROWSER_DIR)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=2)
        except BaseException:
            process.kill()
            process.communicate()
            raise
    output, errors = process.communicate(timeout=15)
    assert process.returncode == 0, errors
    assert output.strip() == "acquired"


def test_sidecar_labels_stale_cache_as_stale(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src.ui.views import google_trends as view
    query = gt.build_query("ChatGPT,Claude", "1 year")
    values, partial = gt.parse_timeline(payload(), query)
    retained = gt.TrendsResult(query, values, partial, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
                              "browser", "Google refused this connection. Showing the cached result.")
    monkeypatch.setattr(view, "_load", lambda query: retained)
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "trends_sidecar.py", default_timeout=10).run()
    at.button[0].click().run()
    assert not at.exception
    assert "cached result" in at.warning[0].value
    assert any("over an hour old" in caption.value for caption in at.caption)
    assert len(at.get("plotly_chart")) == 1
