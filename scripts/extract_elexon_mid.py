"""Elexon BMRS Market Index Data (MID): half-hourly wholesale electricity prices.

Official endpoint:
https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index

MID is the market index price and volume reported per settlement period by each
market index data provider. It sits upstream of retail energy prices and is the
highest-frequency predictor in this fleet.

Settlement periods live in the identifier
-----------------------------------------
`time_series.reference_date` is a `DATE`, and the fleet schema is not changed to
accommodate one source. So ``reference_date`` is the settlement date and the
settlement period is encoded in the series identifier:

    ELEXON_MID_APXMIDP_PRICE_SP01 ... ELEXON_MID_APXMIDP_PRICE_SP50

That keeps the primary key ``(series_id, reference_date, vintage_date)`` intact
and makes every half-hour its own series. A clock-change day has 46 or 50
periods rather than 48, which is why the identifier space runs to SP50.

Aggregation to daily, monthly or month-to-date belongs to
`uk_inflation_predictors`, not here.

Both providers are collected; the zero pair is a placeholder
-----------------------------------------------------------
The API returns two providers, ``APXMIDP`` and ``N2EXMIDP``. Both are
collected, but a row whose price *and* volume are both exactly zero is not
stored, because it is the API's way of saying the provider did not report that
settlement period rather than an economic observation.

That rule was established against the full published history (523 windows,
345,379 rows, 2016-09 to 2026-09):

===============  ==========  =======================  =====================
Provider         Rows        Both price and volume 0  Genuinely reporting
===============  ==========  =======================  =====================
``APXMIDP``      172,713     221                      172,492
``N2EXMIDP``     172,666     172,165                  501
===============  ==========  =======================  =====================

``N2EXMIDP`` reports rarely — 501 periods on 168 distinct dates across ten
years — but when it does the values are real, spanning -65.8 to 450.23 GBP/MWh
on volumes of 25 to 519 MWh. Dropping the provider would therefore discard
genuine data, and storing its 172,165 zero rows would corrupt any average
across providers. Skipping only the zero *pair* keeps both correct.

The rule is deliberately the conjunction. Six rows in the full history carry a
zero price with a non-zero volume — three for each provider — and those are
genuine zero-price trades, not placeholders, so they are stored. No row anywhere
in the history carries a non-zero price with zero volume.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, date, datetime
from typing import Any

import httpx

from scripts.elexon import (
    ATTRIBUTION,
    LICENCE_URL,
    MAX_WINDOW_DAYS,
    SourceData,
    fetch_window,
    utc_today,
    windows,
)
from scripts.snapshots import build_snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)

SOURCE_ID = "elexon_market_index_prices"
API_BASE = "https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index"
DOC_URL = "https://bmrs.elexon.co.uk/api-documentation"

# The first settlement date the API serves any MID row, established by
# bisection against the live API on 2026-09-16. 2016-09-12 is a partial day
# (40 rows); 2016-09-13 is the first full day (96 rows).
HISTORY_START = date(2016, 9, 12)

# Collection can be bounded for a development run without editing code. The
# default is the full published history.
START_OVERRIDE_ENV = "COLLECTOR_ELEXON_START"

# Both providers publish real data; see the module docstring. A provider not
# listed here has never been assessed, so it stops collection rather than being
# collected blind or dropped silently.
PRIMARY_PROVIDER = "APXMIDP"
SPARSE_PROVIDER = "N2EXMIDP"
KNOWN_PROVIDERS = frozenset({PRIMARY_PROVIDER, SPARSE_PROVIDER})

# measure token -> (payload field, fleet unit, published unit)
MEASURES: dict[str, tuple[str, str, str]] = {
    "PRICE": ("price", "currency", "GBP per MWh"),
    "VOLUME": ("volume", "megawatt_hours", "MWh"),
}

# A settlement day has 48 periods, 46 on the spring clock change and 50 on the
# autumn one.
MIN_SETTLEMENT_PERIOD = 1
MAX_SETTLEMENT_PERIOD = 50

REQUIRED_FIELDS = ("dataProvider", "settlementDate", "settlementPeriod", "price", "volume")

# The API exposes no publication timestamp, so there are no official releases
# to attribute to. See POINT_IN_TIME.md: the backfill is `inferred` from the
# documented near-real-time publication rule, and periods that appear between
# two runs are witnessed as `first_seen`.
MIN_LAG_DAYS = 0
MAX_LAG_DAYS = 0
INFERRED_LAG_DAYS = 1

# Plausibility envelope. GB wholesale prices have been negative in oversupply
# and have spiked above £2,000/MWh, so the band is wide and exists to catch a
# unit change or a decimal shift, not to express a market view.
MIN_PLAUSIBLE_PRICE = -1_000.0
MAX_PLAUSIBLE_PRICE = 10_000.0
MAX_PLAUSIBLE_VOLUME = 1_000_000.0

MIN_EXPECTED_SERIES = 90


def make_series_id(provider: str, measure: str, settlement_period: int) -> str:
    """Build ``ELEXON_MID_{PROVIDER}_{MEASURE}_SP{NN}``."""
    if not MIN_SETTLEMENT_PERIOD <= settlement_period <= MAX_SETTLEMENT_PERIOD:
        raise ValueError(
            f"Settlement period {settlement_period} is outside "
            f"{MIN_SETTLEMENT_PERIOD}-{MAX_SETTLEMENT_PERIOD}"
        )
    if measure not in MEASURES:
        raise ValueError(f"Unknown Elexon measure {measure!r}")
    series_id = f"ELEXON_MID_{provider}_{measure}_SP{settlement_period:02d}"
    if len(series_id) > 200:
        raise ValueError(f"series_id exceeds 200 characters: {series_id}")
    return series_id


def parse_series_id(series_id: str) -> tuple[str, str, str, str, int]:
    """Decode ``ELEXON_MID_{PROVIDER}_{MEASURE}_SP{NN}`` into its five parts."""
    parts = series_id.split("_")
    if len(parts) != 5 or parts[0] != "ELEXON" or parts[1] != "MID":
        raise ValueError(f"Invalid Elexon MID series_id: {series_id}")
    source, dataset, provider, measure, period = parts
    if measure not in MEASURES:
        raise ValueError(f"Unknown measure in Elexon MID series_id: {series_id}")
    match = re.fullmatch(r"SP(\d{2})", period)
    if not match:
        raise ValueError(f"Elexon MID series_id carries no settlement period: {series_id}")
    settlement_period = int(match.group(1))
    if not MIN_SETTLEMENT_PERIOD <= settlement_period <= MAX_SETTLEMENT_PERIOD:
        raise ValueError(f"Elexon MID series_id has an out-of-range period: {series_id}")
    return source, dataset, provider, measure, settlement_period


def resolve_start() -> date:
    """Return the first settlement date to collect."""
    raw = os.getenv(START_OVERRIDE_ENV, "").strip()
    if not raw:
        return HISTORY_START
    override = date.fromisoformat(raw)
    if override < HISTORY_START:
        raise ValueError(
            f"{START_OVERRIDE_ENV}={override} precedes the published history start {HISTORY_START}"
        )
    logger.warning(
        "%s is set: collecting from %s rather than the full history from %s",
        START_OVERRIDE_ENV,
        override,
        HISTORY_START,
    )
    return override


def is_placeholder(price: object, volume: object) -> bool:
    """Is this row the API's "did not report" placeholder?

    Only the conjunction counts. A zero price with a real volume is a genuine
    zero-price trade and must be stored; the full history contains six of them.
    """
    return (price or 0) == 0 and (volume or 0) == 0


def parse_window(
    body: bytes, url: str, snapshot_id: str
) -> tuple[list[Observation], dict[str, dict[str, str]], int]:
    """Parse one window payload.

    Returns the observations, their native labels, and how many rows were the
    non-reporting placeholder, so `validate` can refuse a window that is
    entirely placeholder.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Elexon response for {url} is not JSON") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError(
            f"Elexon response for {url} has no 'data' key; the API contract changed and must "
            "be re-verified against the official documentation"
        )

    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    placeholders = 0
    for row in payload["data"]:
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            raise ValueError(
                f"Elexon row from {url} is missing field(s) {missing}; the API contract changed "
                "and must be re-verified"
            )
        provider = str(row["dataProvider"]).strip()
        if provider not in KNOWN_PROVIDERS:
            raise ValueError(
                f"Elexon published unknown data provider {provider!r} in {url}; known providers "
                f"are {sorted(KNOWN_PROVIDERS)}. A new provider must be assessed before it is "
                "collected or ignored."
            )
        if is_placeholder(row["price"], row["volume"]):
            # The provider did not report this settlement period.
            placeholders += 1
            continue

        settlement_period = int(row["settlementPeriod"])
        if not MIN_SETTLEMENT_PERIOD <= settlement_period <= MAX_SETTLEMENT_PERIOD:
            raise ValueError(
                f"Elexon published settlement period {settlement_period} in {url}, outside "
                f"{MIN_SETTLEMENT_PERIOD}-{MAX_SETTLEMENT_PERIOD}"
            )
        reference_date = date.fromisoformat(str(row["settlementDate"])[:10])
        for measure, (field, _fleet_unit, _published_unit) in MEASURES.items():
            value = row[field]
            if value is None:
                continue
            series_id = make_series_id(provider, measure, settlement_period)
            natives.setdefault(
                series_id,
                {
                    "provider": provider,
                    "measure": measure,
                    "settlement_period": str(settlement_period),
                },
            )
            observations.append(
                Observation(
                    series_id=series_id,
                    reference_date=reference_date,
                    value=float(value),
                    snapshot_id=snapshot_id,
                )
            )
    return observations, natives, placeholders


def _build_catalog(
    natives: dict[str, dict[str, str]], last_publish_date: date | None
) -> dict[str, dict[str, Any]]:
    """Describe every collected series from its verified native labels."""
    catalog: dict[str, dict[str, Any]] = {}
    for series_id, fields in natives.items():
        measure = fields["measure"]
        _field, fleet_unit, published_unit = MEASURES[measure]
        period = int(fields["settlement_period"])
        what = "price" if measure == "PRICE" else "traded volume"
        catalog[series_id] = {
            "source_id": SOURCE_ID,
            "name": (
                f"GB market index {what}, {fields['provider']}, settlement period {period:02d} "
                f"({published_unit})"
            ),
            "description": (
                f"Half-hourly GB wholesale electricity market index {what} reported by "
                f"{fields['provider']} for settlement period {period:02d}, in {published_unit}, "
                "from the Elexon BMRS Market Index Data set. The settlement date is the "
                "reference date and the settlement period is carried in the identifier, because "
                "the fleet schema keys observations by DATE. Stored exactly as published; "
                "aggregation to daily, monthly or month-to-date belongs to the research layer. "
                f"{ATTRIBUTION} Licence: {LICENCE_URL}"
            ),
            "frequency": "daily",
            "unit": fleet_unit,
            "eco_group": "financial_markets",
            "source_url": DOC_URL,
            "last_publish_date": None,  # MID exposes settlement time, not publication time.
        }
    return catalog


def validate(
    observations: list[Observation],
    natives: dict[str, dict[str, str]],
    placeholders: int,
) -> None:
    """Gate the parsed panel before anything reaches the database."""
    # The specific diagnosis first: the API answered, but nothing was reported.
    if placeholders and not observations:
        raise ValueError(
            f"Elexon MID returned {placeholders} rows and every one was the non-reporting "
            "placeholder; no provider published anything for the collected range"
        )
    if not observations:
        raise ValueError("Elexon MID collection produced no observations")
    if len(natives) < MIN_EXPECTED_SERIES:
        raise ValueError(
            f"Elexon MID returned only {len(natives)} series, below the {MIN_EXPECTED_SERIES} "
            "floor; settlement periods or a measure are missing"
        )

    present = {fields["measure"] for fields in natives.values()}
    if present != set(MEASURES):
        raise ValueError(
            f"Elexon MID returned measures {sorted(present)}, expected {sorted(MEASURES)}"
        )

    keys = [(observation.series_id, observation.reference_date) for observation in observations]
    if len(keys) != len(set(keys)):
        counts: dict[tuple[str, date], int] = {}
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        duplicates = sorted(key for key, count in counts.items() if count > 1)[:5]
        raise ValueError(
            f"Elexon MID produced duplicate observations, for example {duplicates}; overlapping "
            "windows would do this"
        )

    dates = sorted({observation.reference_date for observation in observations})
    if dates[-1] > utc_today():
        raise ValueError(f"Elexon MID published a future settlement date {dates[-1]}")
    if dates[0] < HISTORY_START:
        raise ValueError(
            f"Elexon MID returned settlement date {dates[0]}, before the established history "
            f"start {HISTORY_START}"
        )

    for observation in observations:
        measure = natives[observation.series_id]["measure"]
        if measure == "PRICE":
            if not MIN_PLAUSIBLE_PRICE <= observation.value <= MAX_PLAUSIBLE_PRICE:
                raise ValueError(
                    f"Elexon MID published price {observation.value} for "
                    f"{observation.series_id} at {observation.reference_date}, outside the "
                    f"plausible [{MIN_PLAUSIBLE_PRICE}, {MAX_PLAUSIBLE_PRICE}] GBP/MWh envelope"
                )
        elif not 0.0 <= observation.value <= MAX_PLAUSIBLE_VOLUME:
            raise ValueError(
                f"Elexon MID published volume {observation.value} for {observation.series_id} "
                f"at {observation.reference_date}, outside the plausible "
                f"[0, {MAX_PLAUSIBLE_VOLUME}] MWh envelope"
            )

    logger.info(
        "Elexon MID validation passed: %d series, %d settlement dates, %s to %s",
        len(natives),
        len(dates),
        dates[0],
        dates[-1],
    )


def collect(client: httpx.Client) -> SourceData:
    """Walk the published history in seven-day windows and validate the result."""
    start, end = resolve_start(), utc_today()
    all_windows = list(windows(start, end, MAX_WINDOW_DAYS))
    logger.info(
        "Elexon MID: collecting %s to %s in %d seven-day window(s)", start, end, len(all_windows)
    )

    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    placeholders = 0
    snapshots: list[Any] = []
    fetched_at = datetime.now(UTC)
    # Settlement dates follow local (BST/GMT) midnight while the API window is
    # in UTC, so the last hour of one window belongs to the next settlement
    # date. Consecutive windows are complementary rather than overlapping, but
    # that is a property of contiguous windows and a clock change, so the same
    # key is deduplicated defensively: an identical repeat is dropped and a
    # genuine disagreement stops collection instead of silently picking one.
    seen: dict[tuple[str, date], float] = {}

    for index, (first, last) in enumerate(all_windows, start=1):
        url, body, digest = fetch_window(client, API_BASE, first, last)
        window_observations, window_natives, window_placeholders = parse_window(body, url, digest)
        if not window_observations and not window_placeholders:
            # A window before MID began, or a genuine publication gap. Neither
            # is an error; an empty whole history is, and `validate` catches it.
            logger.debug("Elexon MID window %s to %s returned no rows", first, last)
            continue
        snapshots.append(
            build_snapshot(
                source_id=SOURCE_ID,
                source_url=url,
                filename=f"mid-{first.isoformat()}-{last.isoformat()}.json",
                body=body,
                digest=digest,
                etag=None,
                last_modified=None,
                fetched_at=fetched_at,
                source_published_date=None,
            )
        )
        for observation in window_observations:
            key = (observation.series_id, observation.reference_date)
            previous = seen.get(key)
            if previous is not None:
                if previous != observation.value:
                    raise ValueError(
                        f"Elexon MID windows disagree for {observation.series_id} at "
                        f"{observation.reference_date}: {previous} then {observation.value}. "
                        "Overlapping windows must report the same published value."
                    )
                continue
            seen[key] = observation.value
            observations.append(observation)
        for series_id, fields in window_natives.items():
            natives.setdefault(series_id, fields)
        placeholders += window_placeholders
        if index % 25 == 0:
            logger.info("Elexon MID: %d/%d windows fetched", index, len(all_windows))

    validate(observations, natives, placeholders)
    return SourceData(
        source_id=SOURCE_ID,
        source_url=DOC_URL,
        catalog=_build_catalog(natives, None),
        observations=observations,
        # The BMRS API exposes no publication timestamp, so there is nothing to
        # attribute to. See POINT_IN_TIME.md.
        releases=[],
        snapshots=snapshots,
        min_lag_days=MIN_LAG_DAYS,
        max_lag_days=MAX_LAG_DAYS,
        inferred_lag_days=INFERRED_LAG_DAYS,
        last_publish_date=None,
    )
