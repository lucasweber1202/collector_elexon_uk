# Predictor collector methodology

This repository belongs to the UK inflation predictor fleet. It collects raw explanatory variables (X) only. Official forecast targets (Y), CPI weights and bottom-up reconciliation remain owned by `collector_ons_cpi` / `collector_ons_ex_cpi`.

## Collector contract

Each repository owns one publisher/source family and writes five tables in a schema whose name equals the repository name:

1. `metadata`
2. `time_series`
3. `availability`
4. `source_snapshots`
5. `logs`

Only raw published levels are stored. MoM, YoY, MTD, rolling averages, monthly aggregation, diffusion and model features are downstream research transformations.

## Source isolation

Source-specific download, parsing and validation live in `scripts/extract.py` or source-forced helper modules. There are no imports from other collector repositories, no shared Python package, no `BaseCollector`, ORM layer or migration framework. Template code is copied into each repository so every collector remains independently deployable and auditable.

## Validation

Before persistence the source module should validate at least source schema, duplicate keys, units, frequency/cadence, plausible values, expected history boundaries where defensible and non-empty output. Source changes that undermine an invariant fail loudly.

## Idempotency and revisions

An unchanged rerun writes no `time_series`, `availability`, `source_snapshots` or `metadata` rows. A later-day historical change creates a new vintage and keeps the old vintage. Point-in-time revision handling follows `POINT_IN_TIME.md`.

## Raw snapshots

Every parsed artifact is hashed with SHA-256. A changed upstream file becomes a new `source_snapshots` row rather than replacing the previous snapshot. Raw bytes stay outside Git in a gitignored location.

## Elexon BMRS Market Index Data

MID is the market index price and volume each market index data provider
reports per settlement period. It is the highest-frequency series in this
fleet and sits upstream of retail energy prices.

### Representing a half-hourly series in a DATE-keyed schema

The fleet keys observations by `(series_id, reference_date, vintage_date)` with
`reference_date` a `DATE`. Rather than change the schema for one source, the
settlement date is the reference date and the settlement period is part of the
identifier (`…_SP01` to `…_SP50`). Two consequences are deliberate:

- every half-hour is an independent series, so a research query asks for the
  periods it wants rather than filtering a wide table;
- the collector performs no aggregation at all — daily, monthly and
  month-to-date views are the research layer's to build.

### Windows and snapshots

The API rejects a window wider than seven days, so the history is walked in
seven-day windows. For a JSON API the question "what is a raw snapshot" has to
be answered explicitly: here **one window's response body is one snapshot**,
hashed with SHA-256 exactly like a downloaded file. The bodies are byte-stable
across identical requests, so an unchanged rerun produces the same digests and
writes no new snapshot rows.

Settlement dates follow local midnight while the window is in UTC, so the last
hour of one window belongs to the next settlement date. Consecutive windows
turn out to be complementary rather than overlapping, but that depends on
contiguity and on the clock, so the collector deduplicates defensively: an
identical repeat of a `(series_id, reference_date)` is dropped and a genuine
disagreement between windows stops collection.

### Distinguishing a placeholder from an observation

Both providers are collected. A row whose price and volume are *both* exactly
zero is skipped as a non-reporting placeholder.

Getting to that rule took two passes, and the second one matters. The first
reading sampled eleven days spanning ten years, found `N2EXMIDP` zero in every
one, and excluded the provider — with a guard that re-proved the exclusion on
every run. The first full-history run tripped that guard: `N2EXMIDP` reports in
501 of 172,666 periods, on 168 distinct dates, with entirely real values. The
provider exclusion was wrong and the guard is the only reason it did not ship.

The replacement rule is the conjunction, not the provider, and the conjunction
is load-bearing: six rows in the history carry a zero price with a real volume,
which are genuine zero-price trades and are stored.

The general lesson is recorded here because it will recur: a sample that agrees
with a hypothesis is not evidence for it when the population is cheap to check.
The full history was 523 requests away the whole time.
