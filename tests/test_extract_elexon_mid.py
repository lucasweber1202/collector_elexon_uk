"""Elexon MID parsing, settlement-period identifiers, provider exclusion, gates."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest

from scripts.elexon import MAX_WINDOW_DAYS, windows
from scripts.extract_elexon_mid import (
    HISTORY_START,
    MAX_SETTLEMENT_PERIOD,
    MEASURES,
    PRIMARY_PROVIDER,
    SPARSE_PROVIDER,
    _build_catalog,
    is_placeholder,
    make_series_id,
    parse_series_id,
    parse_window,
    validate,
)
from scripts.metadata import validate_catalog
from scripts.time_series import Observation


def _row(
    provider: str, day: str, period: int, price: float | None, volume: float | None
) -> dict[str, object]:
    return {
        "startTime": f"{day}T00:00:00Z",
        "dataProvider": provider,
        "settlementDate": day,
        "settlementPeriod": period,
        "price": price,
        "volume": volume,
    }


def _payload(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"metadata": {"datasets": ["MID"]}, "data": rows}).encode()


def _panel(days: int = 3, periods: int = 48) -> tuple[list[Observation], dict[str, dict[str, str]]]:
    observations: list[Observation] = []
    natives: dict[str, dict[str, str]] = {}
    for measure in MEASURES:
        for period in range(1, periods + 1):
            series_id = make_series_id(PRIMARY_PROVIDER, measure, period)
            natives[series_id] = {
                "provider": PRIMARY_PROVIDER,
                "measure": measure,
                "settlement_period": str(period),
            }
            for offset in range(days):
                observations.append(
                    Observation(
                        series_id,
                        HISTORY_START + timedelta(days=offset),
                        50.0,
                        "snapshot",
                    )
                )
    return observations, natives


# --- parsing -------------------------------------------------------------


def test_parses_price_and_volume_per_settlement_period() -> None:
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 1, 61.5, 400.0)])
    observations, natives, placeholders = parse_window(body, "t://e", "snap")
    assert len(natives) == 2
    values = {o.series_id: o.value for o in observations}
    assert values[make_series_id(PRIMARY_PROVIDER, "PRICE", 1)] == pytest.approx(61.5)
    assert values[make_series_id(PRIMARY_PROVIDER, "VOLUME", 1)] == pytest.approx(400.0)
    assert all(o.reference_date == date(2026, 9, 1) for o in observations)
    assert placeholders == 0


def test_the_settlement_date_is_the_reference_date() -> None:
    """The schema keys by DATE; the period lives in the identifier."""
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 30, 10.0, 1.0)])
    observations, _natives, _excluded = parse_window(body, "t://e", "snap")
    assert {o.reference_date for o in observations} == {date(2026, 9, 1)}
    assert all("_SP30" in o.series_id for o in observations)


def test_both_providers_are_collected() -> None:
    """N2EXMIDP reports rarely but genuinely; dropping it would lose real data."""
    body = _payload(
        [
            _row(PRIMARY_PROVIDER, "2026-09-01", 1, 61.5, 400.0),
            _row(SPARSE_PROVIDER, "2026-09-01", 1, 44.0, 50.0),
        ]
    )
    observations, natives, placeholders = parse_window(body, "t://e", "snap")
    providers = {n["provider"] for n in natives.values()}
    assert providers == {PRIMARY_PROVIDER, SPARSE_PROVIDER}
    assert placeholders == 0
    assert len(observations) == 4


def test_the_zero_pair_is_a_placeholder_not_an_observation() -> None:
    """price == 0 and volume == 0 means the provider did not report."""
    body = _payload(
        [
            _row(PRIMARY_PROVIDER, "2026-09-01", 1, 61.5, 400.0),
            _row(SPARSE_PROVIDER, "2026-09-01", 1, 0.0, 0.0),
        ]
    )
    observations, natives, placeholders = parse_window(body, "t://e", "snap")
    assert placeholders == 1
    assert all(PRIMARY_PROVIDER in o.series_id for o in observations)
    assert all(SPARSE_PROVIDER not in sid for sid in natives)


def test_a_zero_price_with_real_volume_is_a_genuine_trade() -> None:
    """Six such rows exist in the full history; they are not placeholders."""
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 1, 0.0, 120.0)])
    observations, _natives, placeholders = parse_window(body, "t://e", "snap")
    assert placeholders == 0
    values = {o.series_id: o.value for o in observations}
    assert values[make_series_id(PRIMARY_PROVIDER, "PRICE", 1)] == 0.0
    assert values[make_series_id(PRIMARY_PROVIDER, "VOLUME", 1)] == pytest.approx(120.0)


@pytest.mark.parametrize(
    ("price", "volume", "expected"),
    [(0.0, 0.0, True), (0.0, 120.0, False), (61.5, 400.0, False), (None, None, True)],
)
def test_the_placeholder_rule_is_the_conjunction(
    price: float | None, volume: float | None, expected: bool
) -> None:
    assert is_placeholder(price, volume) is expected


def test_an_unknown_provider_fails_loudly() -> None:
    body = _payload([_row("NEWMIDP", "2026-09-01", 1, 50.0, 100.0)])
    with pytest.raises(ValueError, match="unknown data provider"):
        parse_window(body, "t://e", "snap")


def test_a_missing_field_fails_loudly() -> None:
    row = _row(PRIMARY_PROVIDER, "2026-09-01", 1, 50.0, 100.0)
    del row["volume"]
    with pytest.raises(ValueError, match="missing field"):
        parse_window(_payload([row]), "t://e", "snap")


def test_a_payload_without_a_data_key_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no 'data' key"):
        parse_window(json.dumps({"metadata": {}}).encode(), "t://e", "snap")


def test_a_non_json_payload_fails_loudly() -> None:
    with pytest.raises(ValueError, match="not JSON"):
        parse_window(b"<html>error</html>", "t://e", "snap")


def test_an_out_of_range_settlement_period_fails_loudly() -> None:
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 51, 50.0, 100.0)])
    with pytest.raises(ValueError, match="outside"):
        parse_window(body, "t://e", "snap")


def test_a_null_value_is_skipped_not_zeroed() -> None:
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 1, None, 400.0)])
    observations, natives, _excluded = parse_window(body, "t://e", "snap")
    assert set(natives) == {make_series_id(PRIMARY_PROVIDER, "VOLUME", 1)}
    assert len(observations) == 1


# --- clock changes -------------------------------------------------------


@pytest.mark.parametrize("period", [46, 48, 49, 50])
def test_clock_change_days_are_representable(period: int) -> None:
    """A short day has 46 periods and a long one 50."""
    body = _payload([_row(PRIMARY_PROVIDER, "2026-10-25", period, 40.0, 300.0)])
    observations, _natives, _excluded = parse_window(body, "t://e", "snap")
    assert any(f"_SP{period:02d}" in o.series_id for o in observations)


def test_the_identifier_space_covers_fifty_periods() -> None:
    assert make_series_id(PRIMARY_PROVIDER, "PRICE", MAX_SETTLEMENT_PERIOD).endswith("_SP50")
    with pytest.raises(ValueError, match="outside"):
        make_series_id(PRIMARY_PROVIDER, "PRICE", 51)


# --- identifiers ---------------------------------------------------------


def test_series_ids_round_trip() -> None:
    for measure in MEASURES:
        for period in (1, 9, 10, 46, 48, 50):
            series_id = make_series_id(PRIMARY_PROVIDER, measure, period)
            _s, _d, provider, parsed_measure, parsed_period = parse_series_id(series_id)
            assert make_series_id(provider, parsed_measure, parsed_period) == series_id
            assert parsed_period == period


def test_the_period_is_zero_padded_so_ids_sort() -> None:
    assert make_series_id(PRIMARY_PROVIDER, "PRICE", 1).endswith("_SP01")
    ids = [make_series_id(PRIMARY_PROVIDER, "PRICE", p) for p in (1, 2, 10, 48)]
    assert ids == sorted(ids)


@pytest.mark.parametrize(
    "series_id",
    [
        "ELEXON_MID_APXMIDP_PRICE",
        "ELEXON_MID_APXMIDP_PRICE_SP99",
        "ELEXON_MID_APXMIDP_COST_SP01",
        "ELEXON_MID_APXMIDP_PRICE_1",
    ],
)
def test_a_malformed_series_id_is_refused(series_id: str) -> None:
    with pytest.raises(ValueError):
        parse_series_id(series_id)


# --- windowing -----------------------------------------------------------


def test_windows_never_exceed_the_api_limit() -> None:
    spans = list(windows(date(2024, 1, 1), date(2024, 3, 1)))
    assert all((last - first).days + 1 <= MAX_WINDOW_DAYS for first, last in spans)


def test_windows_are_contiguous_and_cover_the_range() -> None:
    spans = list(windows(date(2024, 1, 1), date(2024, 1, 20)))
    assert spans[0][0] == date(2024, 1, 1)
    assert spans[-1][1] == date(2024, 1, 20)
    for (_a, end), (start, _b) in pairwise(spans):
        assert start == end + timedelta(days=1)


def test_an_oversized_window_is_refused() -> None:
    with pytest.raises(ValueError, match="1 to 7 days"):
        list(windows(date(2024, 1, 1), date(2024, 1, 31), 31))


def test_a_reversed_range_is_refused() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        list(windows(date(2024, 2, 1), date(2024, 1, 1)))


# --- validation gates ----------------------------------------------------


def test_validation_accepts_a_well_formed_panel() -> None:
    observations, natives = _panel()
    validate(observations, natives, 0)


def test_an_all_placeholder_history_is_refused() -> None:
    """The API answering with nothing but placeholders is a source failure."""
    with pytest.raises(ValueError, match="every one was the non-reporting placeholder"):
        validate([], {}, 500)


def test_too_few_series_is_refused() -> None:
    observations, natives = _panel(periods=10)
    with pytest.raises(ValueError, match="below the .* floor"):
        validate(observations, natives, 0)


def test_losing_a_measure_is_refused() -> None:
    observations, natives = _panel()
    kept = {s for s, f in natives.items() if f["measure"] == "PRICE"}
    with pytest.raises(ValueError, match="returned measures|below the .* floor"):
        validate(
            [o for o in observations if o.series_id in kept],
            {s: f for s, f in natives.items() if s in kept},
            0,
        )


def test_a_duplicate_observation_is_refused() -> None:
    observations, natives = _panel()
    with pytest.raises(ValueError, match="duplicate observations"):
        validate([*observations, observations[0]], natives, 0)


def test_a_future_settlement_date_is_refused() -> None:
    observations, natives = _panel()
    future = Observation(
        observations[0].series_id,
        datetime.now(UTC).date() + timedelta(days=30),
        50.0,
        "snapshot",
    )
    with pytest.raises(ValueError, match="future settlement date"):
        validate([*observations, future], natives, 0)


def test_a_date_before_the_established_history_is_refused() -> None:
    observations, natives = _panel()
    early = Observation(
        observations[0].series_id, HISTORY_START - timedelta(days=1), 50.0, "snapshot"
    )
    with pytest.raises(ValueError, match="before the established history start"):
        validate([*observations, early], natives, 0)


def test_a_negative_price_is_accepted_as_published() -> None:
    """GB wholesale prices go negative in oversupply; that is real."""
    observations, natives = _panel()
    sid = make_series_id(PRIMARY_PROVIDER, "PRICE", 1)
    negative = Observation(sid, HISTORY_START, -85.0, "snapshot")
    kept = [o for o in observations if (o.series_id, o.reference_date) != (sid, HISTORY_START)]
    validate([negative, *kept], natives, 0)


def test_a_negative_volume_is_refused() -> None:
    observations, natives = _panel()
    sid = make_series_id(PRIMARY_PROVIDER, "VOLUME", 1)
    broken = Observation(sid, HISTORY_START, -1.0, "snapshot")
    kept = [o for o in observations if (o.series_id, o.reference_date) != (sid, HISTORY_START)]
    with pytest.raises(ValueError, match="plausible"):
        validate([broken, *kept], natives, 0)


@pytest.mark.parametrize("price", [-5000.0, 50000.0])
def test_an_implausible_price_is_refused(price: float) -> None:
    observations, natives = _panel()
    sid = make_series_id(PRIMARY_PROVIDER, "PRICE", 1)
    broken = Observation(sid, HISTORY_START, price, "snapshot")
    kept = [o for o in observations if (o.series_id, o.reference_date) != (sid, HISTORY_START)]
    with pytest.raises(ValueError, match="plausible"):
        validate([broken, *kept], natives, 0)


def test_an_empty_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="no observations"):
        validate([], {}, 0)


def test_the_catalog_satisfies_the_metadata_vocabularies() -> None:
    body = _payload([_row(PRIMARY_PROVIDER, "2026-09-01", 1, 61.5, 400.0)])
    _observations, natives, _excluded = parse_window(body, "t://e", "snap")
    catalog = _build_catalog(natives, date(2026, 9, 1))
    validate_catalog(catalog)
    price = catalog[make_series_id(PRIMARY_PROVIDER, "PRICE", 1)]
    volume = catalog[make_series_id(PRIMARY_PROVIDER, "VOLUME", 1)]
    assert price["unit"] == "currency"
    assert volume["unit"] == "megawatt_hours"
    # The Elexon licence requires attribution to travel with the data.
    assert "Contains BMRS data" in price["description"]
    assert "settlement period 01" in price["name"]
