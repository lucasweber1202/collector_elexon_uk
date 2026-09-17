"""Bounded HTTP access to the Elexon BMRS open-data API.

This module holds the host allowlist, retry budget, download ceiling and the
API's seven-day window constraint in one place. It owns no parsing and no
series identifiers; those stay in the `extract_*.py` modules.

Licence
-------
BMRS open data is published under Elexon's "Licence to use BMRS open data",
which grants a worldwide, royalty-free, perpetual, non-exclusive licence to
copy, adapt and exploit the data, including commercially, provided the source
is attributed. Automated access and historical storage are therefore permitted.
The required attribution is reproduced in `ATTRIBUTION` and is carried into
every series description so it travels with the data.

https://www.elexon.co.uk/bsc/operations-settlement/bsc-central-services/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/

Window constraint
-----------------
Verified against the live API on 2026-09-16: a request spanning more than seven
days is rejected with HTTP 400. Collection therefore walks the history in
seven-day windows, and each window's response body is one raw snapshot. The
body is byte-stable — the same window requested twice returns identical bytes
and therefore the same SHA-256 — which is what makes an unchanged rerun a no-op
in `source_snapshots`.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from scripts.config import (
    BACKOFF_FACTOR,
    MAX_DOWNLOAD_BYTES,
    MAX_RETRIES,
    MAX_RETRY_DELAY,
    RATE_LIMIT_BACKOFF,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from scripts.snapshots import Snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)

API_HOST = "data.elexon.co.uk"
ALLOWED_HOSTS = frozenset({API_HOST})

ATTRIBUTION = "Contains BMRS data © Elexon Limited copyright and database right."
LICENCE_URL = (
    "https://www.elexon.co.uk/bsc/operations-settlement/bsc-central-services/"
    "balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/"
)

# The API rejects a window wider than this with HTTP 400.
MAX_WINDOW_DAYS = 7

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RATE_LIMITED_STATUS = 429
_TRANSFER_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})

# A courtesy pause between windows. A full backfill is several hundred
# requests, and this keeps the walk well inside any reasonable rate limit.
INTER_REQUEST_DELAY = 0.4


def build_client() -> httpx.Client:
    """Build the single managed HTTP client used by one collection call."""
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        trust_env=True,
        follow_redirects=False,
    )


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Return the bounded wait before the next attempt, honouring Retry-After."""
    delay = float(BACKOFF_FACTOR**attempt)
    if response is not None and response.status_code == RATE_LIMITED_STATUS:
        delay = max(delay, RATE_LIMIT_BACKOFF * (attempt + 1))
        header = response.headers.get("retry-after", "").strip()
        if header.isdigit():
            delay = max(delay, float(header))
    return min(delay, MAX_RETRY_DELAY)


def _bounded_body(response: httpx.Response, url: str) -> bytes:
    """Read a streamed body, refusing an implausibly large download."""
    declared = response.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"Elexon declared {declared} bytes for {url}, above the download limit")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Response for {url} exceeded the {MAX_DOWNLOAD_BYTES} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def http_get(client: httpx.Client, url: str) -> bytes:
    """Request an allowlisted Elexon URL with bounded exponential-backoff retries."""
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing non-Elexon URL: {url}")
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        response = None
        try:
            with client.stream("GET", url) as streamed:
                response = streamed
                if streamed.status_code not in RETRYABLE_STATUSES:
                    streamed.raise_for_status()
                    return _bounded_body(streamed, url)
                streamed.read()
                last_error = httpx.HTTPStatusError(
                    f"retryable status {streamed.status_code}",
                    request=streamed.request,
                    response=streamed,
                )
        except httpx.TransportError as exc:
            response = None
            last_error = exc
        if attempt < MAX_RETRIES:
            delay = _retry_delay(attempt, response)
            logger.warning(
                "Elexon request failed; retrying in %.1fs (%d/%d)", delay, attempt + 1, MAX_RETRIES
            )
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def windows(
    start: date, end: date, size_days: int = MAX_WINDOW_DAYS
) -> Iterator[tuple[date, date]]:
    """Split ``[start, end]`` into inclusive windows the API will accept."""
    if size_days < 1 or size_days > MAX_WINDOW_DAYS:
        raise ValueError(
            f"Elexon accepts a window of 1 to {MAX_WINDOW_DAYS} days; {size_days} was requested"
        )
    if end < start:
        raise ValueError(f"Elexon window end {end} precedes start {start}")
    cursor = start
    while cursor <= end:
        last = min(cursor + timedelta(days=size_days - 1), end)
        yield cursor, last
        cursor = last + timedelta(days=1)


def window_url(base: str, first: date, last: date) -> str:
    """Build the API URL for one inclusive day window."""
    return f"{base}?from={first.isoformat()}T00:00Z&to={last.isoformat()}T23:59Z&format=json"


def fetch_window(
    client: httpx.Client, base: str, first: date, last: date
) -> tuple[str, bytes, str]:
    """Fetch one window, returning ``(url, body, sha256)``.

    The body is the raw bytes the API returned, which is what gets hashed and
    stored as the snapshot: re-requesting an unchanged window yields identical
    bytes and therefore the same digest.
    """
    url = window_url(base, first, last)
    body = http_get(client, url)
    digest = hashlib.sha256(body).hexdigest()
    logger.debug("Elexon %s to %s: %d bytes (sha256 %s)", first, last, len(body), digest[:12])
    time.sleep(INTER_REQUEST_DELAY)
    return url, body, digest


@dataclass(frozen=True)
class SourceData:
    """Everything one Elexon source yielded in a single collection call.

    Mirrors the fleet contract used by the GOV.UK collectors: a plain data
    carrier that `main.py` consumes, not a base class.
    """

    source_id: str
    source_url: str
    catalog: dict[str, dict[str, Any]]
    observations: list[Observation]
    # Official publication timestamps. The BMRS API exposes none, so this is
    # empty for every Elexon source and availability falls back as documented
    # in POINT_IN_TIME.md.
    releases: list[datetime]
    snapshots: list[Snapshot]
    min_lag_days: int
    max_lag_days: int
    inferred_lag_days: int | None
    last_publish_date: date | None


def utc_today() -> date:
    """Return today's UTC date, isolated here so tests can reason about it."""
    return datetime.now(UTC).date()
