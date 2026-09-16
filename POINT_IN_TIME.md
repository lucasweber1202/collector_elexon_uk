# Point-in-time contract

This collector stores predictor data for forecasting. A historical backtest must never see information that was unavailable at the simulated forecast instant.

## Stored dates

- `reference_date`: period the observation describes.
- `vintage_date`: UTC date on which this collector stored that version.
- `release_date`: source publication date when explicitly supported.
- `available_at`: earliest defensible instant at which this stored vintage could have been known.
- `collected_at`: timestamp of this pipeline run.

`availability_basis` is one of `official_timestamp`, `official_date`, `archived_release`, `first_seen`, `inferred`, `unknown`.

By default `get_series_as_of()` accepts only `official_timestamp`, `official_date`, `archived_release`, and `first_seen`. `inferred` and `unknown` require explicit opt-in.

## Historical revisions

A revised value for an already stored `(series_id, reference_date)` must not reuse the original publication timestamp. Unless the source exposes explicit evidence for the revision release, the revised vintage is stamped:

- `available_at = collected_at`
- `availability_basis = first_seen`
- `release_date = NULL`

This prevents a 2026 revision of a 2024 observation from appearing in a 2024 backtest.

## Same-day revisions

The fleet schema uses `vintage_date DATE`. Two different intraday revisions therefore cannot be represented without overwriting one information set. Predictor collectors fail closed when an already stored vintage changes again on the same UTC date. Retry after the UTC date changes rather than rewriting history.

## As-of guarantee

`get_series_as_of(series_id, as_of)` filters on `available_at <= as_of` before ranking vintages. A later revision therefore cannot mask the vintage that was actually current at the historical instant.

## Elexon MID availability

### There is no publication timestamp

The BMRS API returns settlement data with no field describing when that data was
published, and the endpoint has no change history or release feed. There is
therefore **nothing to attribute an `official_timestamp` to**, and this
collector does not invent one.

`SourceData.releases` is empty for this source. That is a deliberate statement
of ignorance, not an oversight.

### What each vintage actually carries

| Situation | `availability_basis` | `available_at` |
| --- | --- | --- |
| Historical backfill | `inferred` | reference date + 1 day, midday UTC |
| A period first seen between two runs | `first_seen` | this run's `collected_at` |
| A revised value for a stored period | `first_seen` | this run's `collected_at` |

The `inferred` instant comes from the documented behaviour that MID is
published shortly after each settlement period. That is a *reconstruction from
a release rule*, which is exactly what `inferred` means in the fleet
vocabulary, and `get_series_as_of()` excludes it by default.

The practical consequence is stated plainly because it constrains research: a
backtest that accepts only genuine point-in-time evidence sees **only the
periods this collector has itself witnessed appearing**, not the ten-year
backfill. The backfill is usable for exploratory work provided the result is
labelled as resting on reconstructed availability.

Availability is never back-dated from the settlement date, and
`available_at = settlementDate 00:00` is never used: a settlement period cannot
have been knowable before it ended.
