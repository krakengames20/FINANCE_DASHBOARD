"""Headless Trends transport with a separate, persistent browser profile.

Only the requested timeline is collected. Google challenges and refusals stop
the fetch; this transport never solves CAPTCHAs or cycles browser identities.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from src.data import google_trends as gt

BROWSER_DIR = gt.CACHE_DIR / "browser"
BLOCK_COOLDOWN = 30 * 60
MIN_INTERVAL = 30
PAGE_TIMEOUT = 45_000
_local_lock = threading.Lock()


@contextmanager
def request_lock():
    """One network fetch across all threads and local dashboard processes."""
    with _local_lock:
        try:
            BROWSER_DIR.mkdir(parents=True, exist_ok=True)
            handle = (BROWSER_DIR / "request.lock").open("a+b")
        except OSError as exc:
            raise gt.TrendsError("The browser needs a writable .cache/google_trends/browser directory.") from exc
        acquired = False
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 90
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise gt.TrendsError("Another Trends fetch is still running. Please try again later.")
                    time.sleep(0.2)
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _state() -> dict:
    try:
        state = json.loads((BROWSER_DIR / "pacing.json").read_text(encoding="utf-8"))
        return {key: float(state.get(key, 0)) for key in ("last_request", "blocked_until")}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"last_request": 0, "blocked_until": 0}


def _save_state(state: dict) -> None:
    target = BROWSER_DIR / "pacing.json"
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        raise gt.TrendsError("Could not save the shared Google Trends cooldown.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _check_pacing() -> dict:
    state = _state()
    now = time.time()
    remaining = state["blocked_until"] - now
    if remaining > 0:
        minutes = max(1, int(remaining / 60) + 1)
        raise gt.TrendsRateLimitError(
            f"Google refused the timeline request. Browser fetching is paused for another {minutes} minutes "
            "across the sidecar and dashboard. Google's block may last longer; the previous chart is retained."
        )
    delay = MIN_INTERVAL - (now - state["last_request"])
    if delay > 0:
        time.sleep(min(delay, MIN_INTERVAL))
    state["last_request"] = time.time()
    _save_state(state)
    return state


def _launch_context(playwright):
    """Use installed Chrome/Edge, or Playwright's installed Chromium on servers."""
    profile = str((BROWSER_DIR.parent / "browser_profile").resolve())
    from playwright.sync_api import Error
    for channel in ("chrome", "msedge", "chromium"):
        try:
            return playwright.chromium.launch_persistent_context(
                profile, channel=channel, headless=True, locale="en-US",
                timezone_id="UTC", timeout=20_000, accept_downloads=False,
            )
        except Error:
            continue
    raise gt.TrendsError(
        "Could not start the Trends browser. Install Chrome or Edge, or run "
        "the project's Python with -m playwright install chromium."
    )


def _collect(page, query: gt.TrendsQuery) -> dict:
    """Capture the same JSON used by the page; avoid scraping chart pixels."""
    from playwright.sync_api import Error, TimeoutError
    outcome: dict = {}
    sent_timeline = False
    deadline = time.monotonic() + PAGE_TIMEOUT / 1000

    def remaining_ms():
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise gt.TrendsError("The browser reached Google, but no timeline arrived within 45 seconds.")
        return remaining

    def route_widget(route):
        nonlocal sent_timeline
        path = urlparse(route.request.url).path
        if path == "/trends/api/widgetdata/multiline" and not sent_timeline:
            sent_timeline = True
            route.continue_()
        else:
            route.abort()  # related charts and automatic timeline retries are unnecessary

    def response_received(response):
        path = urlparse(response.url).path
        if path not in ("/trends/api/explore", "/trends/api/widgetdata/multiline"):
            return
        if response.status in (401, 403, 429):
            outcome["error"] = gt.TrendsRateLimitError(
                f"Google refused the browser timeline request (HTTP {response.status}). "
                "Fetching is paused for 30 minutes; Google's restriction may last longer."
            )
        elif response.status >= 400:
            outcome["error"] = gt.TrendsError(f"Google Trends is unavailable (HTTP {response.status}).")
        elif path.endswith("/multiline"):
            try:
                outcome["payload"] = gt.decode_payload(response.text())
            except (gt.TrendsError, Error):
                outcome["error"] = gt.TrendsError("Google returned an unreadable timeline; no chart was updated.")

    page.route("**/trends/api/widgetdata/**", route_widget)
    page.on("response", response_received)
    try:
        warmup = page.goto(f"{gt.BASE_URL}/?hl=en-US", wait_until="domcontentloaded", timeout=remaining_ms())
        if warmup and warmup.status in (401, 403, 429):
            raise gt.TrendsRateLimitError("Google refused the browser connection. Fetching is paused for 30 minutes.")
        if warmup and warmup.status >= 400:
            raise gt.TrendsError(f"Google Trends is unavailable (HTTP {warmup.status}).")
        document = page.goto(query.explore_url, wait_until="domcontentloaded", timeout=remaining_ms())
        if document and document.status in (401, 403, 429):
            raise gt.TrendsRateLimitError("Google blocked the Explore page. Fetching is paused for 30 minutes.")
        if document and document.status >= 400:
            raise gt.TrendsError(f"Google Trends is unavailable (HTTP {document.status}).")
        while not outcome:
            if "/sorry/" in page.url or page.locator('form[action*="Captcha"], #captcha-form').count():
                raise gt.TrendsRateLimitError(
                    "Google requires a browser verification. Automated fetching has stopped for 30 minutes. "
                    "Open this query in Google Trends to check the connection."
                )
            if time.monotonic() >= deadline:
                raise gt.TrendsError("The browser reached Google, but no timeline arrived within 45 seconds.")
            page.wait_for_timeout(200)
        if "error" in outcome:
            raise outcome["error"]
        return outcome["payload"]
    except TimeoutError as exc:
        raise gt.TrendsError("Google Trends timed out in the browser. Try again later.") from exc


class BrowserTrendsClient:
    """The caller holds request_lock for cache, profile, and cooldown access."""

    def fetch(self, query: gt.TrendsQuery) -> gt.TrendsResult:
        query = gt.build_query(query.terms, query.window, query.geo)
        state = _check_pacing()
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError as exc:
            raise gt.TrendsError("Install the project requirements to enable the Google Trends browser.") from exc
        try:
            with sync_playwright() as playwright:
                context = _launch_context(playwright)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    payload = _collect(page, query)
                finally:
                    context.close()  # flush persistent cookies and release the profile on every exit
            values, partial = gt.parse_timeline(payload, query)
            return gt.TrendsResult(query, values, partial, gt.dt.datetime.now(gt.dt.timezone.utc), "browser")
        except gt.TrendsRateLimitError:
            state["blocked_until"] = time.time() + BLOCK_COOLDOWN
            _save_state(state)
            raise
        except Error as exc:
            # Browser errors can contain URLs and proxy credentials; keep them out of the UI.
            raise gt.TrendsError("Could not collect Google Trends in the browser. Check the connection and try later.") from exc
