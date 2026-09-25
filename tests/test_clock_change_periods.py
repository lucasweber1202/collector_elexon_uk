"""Settlement periods 49 and 50 publish annually, not daily.

The long clock-change day -- the last Sunday of October, when BST ends -- runs
to 50 half-hour settlement periods instead of 48. SP49 and SP50 therefore exist
on exactly one day a year. Judged by the strict two-month staleness rule they
read as discontinued for ten months of every twelve, so they would be admitted
each October and dropped again each January, flickering in and out of the
database forever while nothing about them had changed.

Measured against the live source on 2026-09-25: SP49 and SP50 each hold exactly
ten observations, one on every clock-change Sunday from 2016-10-30 to
2025-10-26, while SP46 to SP48 hold about 3,600 each.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.config import CLOCK_CHANGE_MAX_STALE_MONTHS, MAX_STALE_MONTHS
from scripts.extract import assess_series, filter_usable_series, settlement_period

# The real clock-change Sundays this source has published.
CLOCK_CHANGE_DAYS = [
    date(2016, 10, 30),
    date(2017, 10, 29),
    date(2018, 10, 28),
    date(2019, 10, 27),
    date(2020, 10, 25),
    date(2021, 10, 31),
    date(2022, 10, 30),
    date(2023, 10, 29),
    date(2024, 10, 27),
    date(2025, 10, 26),
]
# Eleven months after the last clock change, and the worst case for the rule:
# the next one has not happened yet.
TODAY = date(2026, 9, 25)


class _Observation:
    def __init__(self, series_id: str, reference_date: date, value: float) -> None:
        self.series_id = series_id
        self.reference_date = reference_date
        self.value = value


def _daily(count: int, end: date) -> list[date]:
    return [date.fromordinal(end.toordinal() - offset) for offset in range(count)]


@pytest.mark.parametrize("period", ["SP49", "SP50"])
def test_a_live_clock_change_period_is_kept(period: str) -> None:
    series_id = f"ELEXON_MID_APXMIDP_PRICE_{period}"
    assert assess_series(CLOCK_CHANGE_DAYS, TODAY, series_id=series_id) == "keep"


@pytest.mark.parametrize("period", ["SP49", "SP50"])
def test_the_strict_rule_would_have_dropped_it(period: str) -> None:
    """Proves the allowance is load-bearing, not decoration."""
    series_id = f"ELEXON_MID_APXMIDP_PRICE_{period}"
    assert assess_series(CLOCK_CHANGE_DAYS, TODAY) == "stale"
    assert assess_series(CLOCK_CHANGE_DAYS, TODAY, series_id=series_id) == "keep"


def test_a_retired_clock_change_period_still_ages_out() -> None:
    """One clock change has passed without refreshing it, so it is dead."""
    series_id = "ELEXON_MID_APXMIDP_PRICE_SP49"
    stale_today = date(2027, 2, 1)
    assert assess_series(CLOCK_CHANGE_DAYS, stale_today, series_id=series_id) == "stale"


def test_an_ordinary_period_keeps_the_strict_rule() -> None:
    """SP48 publishes daily; a three-month gap in it is a real outage."""
    series_id = "ELEXON_MID_APXMIDP_PRICE_SP48"
    dates = _daily(1200, date(2026, 6, 1))
    assert assess_series(dates, TODAY, series_id=series_id) == "stale"
    assert assess_series(_daily(1200, date(2026, 9, 24)), TODAY, series_id=series_id) == "keep"


def test_the_allowance_is_wider_than_the_strict_rule() -> None:
    assert CLOCK_CHANGE_MAX_STALE_MONTHS > MAX_STALE_MONTHS


@pytest.mark.parametrize(
    ("series_id", "expected"),
    [
        ("ELEXON_MID_APXMIDP_PRICE_SP49", "SP49"),
        ("ELEXON_MID_N2EXMIDP_VOLUME_SP01", "SP01"),
        ("ELEXON_MID_APXMIDP_PRICE", None),
        ("SOMETHING_SPQR", None),
    ],
)
def test_settlement_period_is_read_from_the_identifier(
    series_id: str, expected: str | None
) -> None:
    assert settlement_period(series_id) == expected


def test_the_filter_keeps_clock_change_periods_end_to_end() -> None:
    """The path main.py takes: both long-day periods survive a September run."""
    observations: list[_Observation] = []
    catalog: dict[str, dict[str, object]] = {}
    for period in ("SP48", "SP49", "SP50"):
        series_id = f"ELEXON_MID_APXMIDP_PRICE_{period}"
        catalog[series_id] = {}
        days = _daily(1200, date(2026, 9, 24)) if period == "SP48" else CLOCK_CHANGE_DAYS
        observations += [_Observation(series_id, day, 50.0) for day in days]

    _, kept_catalog, report = filter_usable_series(observations, catalog, TODAY)
    assert report.stale == ()
    assert set(kept_catalog) == set(catalog)
