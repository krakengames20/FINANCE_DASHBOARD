"""Small, bounded collector for Google Trends' public website data endpoints.

This is not the application-gated official API. Keep the transport separate
from the UI so it can be replaced when official access becomes available.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pandas as pd
import requests

BASE_URL = "https://trends.google.com/trends"
WINDOWS = {"1 year": "today 12-m", "1 month": "today 1-m", "1 week": "now 7-d"}
REGIONS = {
    "United States": "US", "Worldwide": "", "United Kingdom": "GB",
    "France": "FR", "Germany": "DE", "Canada": "CA", "Australia": "AU",
    "India": "IN", "Japan": "JP", "China": "CN",
}
TIMEOUT = (5, 15)
CACHE_TTL = 3600
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "google_trends"


class TrendsError(RuntimeError):
    """A provider failure that can be shown without breaking the dashboard."""


class TrendsRateLimitError(TrendsError):
    """The connection should be left idle after Google's refusal."""


@dataclass(frozen=True)
class TrendsQuery:
    terms: tuple[str, ...]
    window: str
    geo: str

    @property
    def timeframe(self) -> str:
        return WINDOWS[self.window]

    @property
    def explore_url(self) -> str:
        return f"{BASE_URL}/explore?" + urlencode(
            {"date": self.timeframe, "geo": self.geo, "q": ",".join(self.terms), "hl": "en-US"}
        )


@dataclass
class TrendsResult:
    query: TrendsQuery
    values: pd.DataFrame
    partial: pd.Series
    fetched_at: dt.datetime
    source: str = "http"
    warning: str | None = None

    def csv_bytes(self) -> bytes:
        """Keep arbitrary user terms even if they match metadata column names."""
        flag, stamp = "is_partial", "time_utc"
        while flag in self.values.columns:
            flag = "_" + flag
        while stamp in self.values.columns or stamp == flag:
            stamp = "_" + stamp
        return self.values.assign(**{flag: self.partial}).to_csv(index_label=stamp).encode("utf-8")


def build_query(terms: str | tuple[str, ...], window: str, geo: str = "US") -> TrendsQuery:
    if window not in WINDOWS:
        raise ValueError("Choose 1 year, 1 month, or 1 week.")
    geo = geo.strip().upper()
    if geo and not re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]{1,3})?", geo):
        raise ValueError("Use a country or subdivision code, or leave the region empty for Worldwide.")
    try:
        items = next(csv.reader([terms], strict=True)) if isinstance(terms, str) else terms
    except csv.Error as exc:
        raise ValueError("Separate terms with commas; quote a phrase that contains a comma.") from exc
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        term = item.strip()
        if not term:
            continue
        if len(term) > 100 or any(ord(c) < 32 for c in term):
            raise ValueError("Each term must be at most 100 characters, on one line.")
        if term.casefold() not in seen:
            cleaned.append(term)
            seen.add(term.casefold())
    if not 1 <= len(cleaned) <= 5:
        raise ValueError("Enter between one and five terms, separated by commas.")
    return TrendsQuery(tuple(cleaned), window, geo)


def decode_payload(text: str) -> dict:
    """Google prefixes JSON with an anti-XSSI guard, with variable whitespace."""
    body = text.lstrip("\ufeff \r\n\t")
    if body.startswith(")]}'"):
        body = body[4:].lstrip(", \r\n\t")
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise TrendsError("Google returned an unexpected response. Open Google Trends or try later.") from exc
    if not isinstance(payload, dict):
        raise TrendsError("Google returned an unexpected data format.")
    return payload


def parse_timeline(payload: dict, query: TrendsQuery) -> tuple[pd.DataFrame, pd.Series]:
    """Preserve missing/low-volume readings and Google's unfinished-period flag."""
    try:
        rows = payload["default"]["timelineData"]
        if not isinstance(rows, list):
            raise TypeError("timelineData is not a list")
        parsed, stamps, flags = [], [], []
        for row in rows:
            values = row["value"]
            has_data = row.get("hasData", [True] * len(query.terms))
            if len(values) != len(query.terms) or len(has_data) != len(query.terms):
                raise ValueError("term count changed")
            point = []
            for term, value, available in zip(query.terms, values, has_data):
                if not available:
                    point.append(float("nan"))
                    continue
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= 100:
                    raise ValueError("score outside 0–100")
                point.append(number)
            stamps.append(pd.to_datetime(int(row["time"]), unit="s", utc=True))
            flags.append(bool(row.get("isPartial", False)))
            parsed.append(point)
        if not parsed:
            raise TrendsError("Google has no search-interest data for these terms and this region.")
        frame = pd.DataFrame(parsed, index=pd.DatetimeIndex(stamps, name="time"), columns=query.terms, dtype=float)
        partial = pd.Series(flags, index=frame.index, dtype=bool, name="is_partial")
        keep = ~frame.index.duplicated(keep="last")
        frame, partial = frame.loc[keep].sort_index(), partial.loc[keep].sort_index()
        if frame.isna().all().all():
            raise TrendsError("Google has insufficient search volume for this query. Try broader terms or Worldwide.")
        return frame, partial
    except TrendsError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise TrendsError("Google's timeline format changed; no chart was updated.") from exc


def _get(session: requests.Session, path: str, params: dict | None = None) -> dict:
    response = session.get(f"{BASE_URL}{path}", params=params, timeout=TIMEOUT)
    if response.status_code == 429:
        raise TrendsRateLimitError("Google is rate-limiting this connection. Wait 5 minutes before fetching again.")
    if response.status_code in (401, 403):
        raise TrendsRateLimitError("Google blocked this connection. You can still open the same query in Google Trends.")
    if response.status_code >= 400:
        raise TrendsError(f"Google Trends is unavailable (HTTP {response.status_code}). Try again later.")
    return decode_payload(response.text)


class TrendsClient:
    """Retain Google's session cookie; serialize requests from dashboard users."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{BASE_URL}/explore/",
        })
        self.lock = threading.Lock()
        self.warmed = False
        self.paused_until = 0.0

    def fetch(self, query: TrendsQuery) -> TrendsResult:
        query = build_query(query.terms, query.window, query.geo)
        request = {
            "comparisonItem": [
                {"keyword": term, "geo": query.geo, "time": query.timeframe}
                for term in query.terms
            ], "category": 0, "property": "",
        }
        with self.lock:
            if time.monotonic() < self.paused_until:
                raise TrendsError("Google recently refused a request. Fetching is paused for 5 minutes; the previous chart is retained.")
            try:
                if not self.warmed:
                    warmup = self.session.get(f"{BASE_URL}/", timeout=TIMEOUT)
                    if warmup.status_code >= 400:
                        if warmup.status_code in (403, 429):
                            raise TrendsRateLimitError("Google refused this connection. Wait 5 minutes or open Google Trends.")
                        raise TrendsError(f"Google Trends is unavailable (HTTP {warmup.status_code}). Try again later.")
                    self.warmed = True
                explore = _get(self.session, "/api/explore", {
                    "hl": "en-US", "tz": 0, "req": json.dumps(request, ensure_ascii=False),
                })
                widgets = explore.get("widgets", [])
                if not isinstance(widgets, list):
                    raise TrendsError("Google returned an unexpected widget format.")
                widget = next((w for w in widgets if isinstance(w, dict) and w.get("id") == "TIMESERIES"), None)
                if not widget or not widget.get("token") or not isinstance(widget.get("request"), dict):
                    raise TrendsError("Google did not return a timeline for this query. Try broader search terms.")
                payload = _get(self.session, "/api/widgetdata/multiline", {
                    "hl": "en-US", "tz": 0, "token": widget["token"],
                    "req": json.dumps(widget["request"], ensure_ascii=False),
                })
            except TrendsRateLimitError:
                self.paused_until = time.monotonic() + 300
                raise
            except requests.Timeout as exc:
                raise TrendsError("Google Trends timed out. Try again later.") from exc
            except requests.RequestException as exc:
                # Avoid echoing connection URLs, which may contain proxy credentials.
                raise TrendsError("Could not connect to Google Trends. Check your connection or proxy settings.") from exc
        values, partial = parse_timeline(payload, query)
        return TrendsResult(query, values, partial, dt.datetime.now(dt.timezone.utc))


@lru_cache(maxsize=1)
def _http_client() -> TrendsClient:
    return TrendsClient()


@lru_cache(maxsize=1)
def _client():
    from src.data.google_trends_browser import BrowserTrendsClient
    return BrowserTrendsClient()


def _cache_path(query: TrendsQuery) -> Path:
    key = json.dumps([1, query.terms, query.window, query.geo], ensure_ascii=False).encode("utf-8")
    return CACHE_DIR / (hashlib.sha256(key).hexdigest() + ".json")


def _read_cache(query: TrendsQuery, *, allow_stale: bool = False) -> TrendsResult | None:
    try:
        document = json.loads(_cache_path(query).read_text(encoding="utf-8"))
        stamp = dt.datetime.fromisoformat(document["fetched_at"])
        age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
        if not 0 <= age < (7 * 86400 if allow_stale else CACHE_TTL):
            return None
        if document["query"] != [list(query.terms), query.window, query.geo]:
            return None
        values, flags = parse_timeline(document["timeline"], query)
        return TrendsResult(query, values, flags, stamp, document.get("source", "http"))
    except (OSError, ValueError, KeyError, TypeError, TrendsError):
        return None  # corrupt/expired/unwritable caches never prevent a live fetch


def _write_cache(result: TrendsResult) -> None:
    rows = []
    for stamp, values in result.values.iterrows():
        rows.append({
            "time": str(int(stamp.timestamp())),
            "value": [float(v) if pd.notna(v) else 0 for v in values],
            "hasData": [bool(pd.notna(v)) for v in values],
            "isPartial": bool(result.partial.loc[stamp]),
        })
    document = {
        "query": [list(result.query.terms), result.query.window, result.query.geo],
        "fetched_at": result.fetched_at.isoformat(),
        "source": result.source,
        "timeline": {"default": {"timelineData": rows}},
    }
    target = _cache_path(result.query)
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        pass  # cache is optional, e.g. on a read-only deployment
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def fetch_interest(query: TrendsQuery, *, refresh: bool = False, provider: str = "browser") -> TrendsResult:
    """Fetch with a saved browser profile; reuse cache across local processes.

    ``refresh`` bypasses the result cache, never the shared browser cooldown.
    The HTTP collector remains available for explicit diagnostic comparisons.
    Failed updates can return the same query's last successful cached result,
    with its original timestamp and a warning, for up to seven days.
    """
    if provider not in ("browser", "http"):
        raise ValueError("Choose the browser or http provider.")
    query = build_query(query.terms, query.window, query.geo)
    if not refresh:
        cached = _read_cache(query)
        if cached is not None:
            return cached
    from src.data.google_trends_browser import request_lock
    with request_lock():
        # Another process may have populated the cache while we waited.
        if not refresh:
            cached = _read_cache(query)
            if cached is not None:
                return cached
        try:
            result = (_client() if provider == "browser" else _http_client()).fetch(query)
        except TrendsError as exc:
            retained = _read_cache(query, allow_stale=True) if not refresh else None
            if retained is None:
                raise
            return replace(retained, warning=f"{exc} Showing the cached result for this query; it has not been updated.")
        _write_cache(result)
        return result
