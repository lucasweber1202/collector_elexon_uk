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

## Canonical catalogue versus the active set

The source catalogue is **196 series**: 100 APXMIDP and 96 N2EXMIDP, each a
price and a volume series per settlement period. That figure describes what the
source has ever published and does not change with a run.

What is stored after the 5.1 usable-series filter is smaller, and the two
numbers must not be conflated. Measured against the live source on 2026-09-25:

| Family | Catalogue | Active after filter |
| --- | ---: | ---: |
| APXMIDP | 100 | 100 |
| N2EXMIDP | 96 | 16 |
| **Total** | **196** | **116** |

APX reports every settlement period every day: 366 report-days in the last
twelve months. N2EX does not. It reports only when N2EX trades occur in a given
settlement period, and it did so on 26 days in the same twelve months; several
of its settlement periods were last reported in 2021 or 2023. Those series are
dropped on recency, which is the filter working as intended rather than a
collection defect. The catalogue still records all 96.

### Settlement periods 49 and 50

The long clock-change day — the last Sunday of October, when BST ends — runs to
50 half-hour settlement periods instead of 48, so SP49 and SP50 exist on
exactly one day a year. Each holds ten observations, one per clock change from
2016-10-30 to 2025-10-26, against roughly 3,600 for SP46 to SP48.

Judged by the strict two-month staleness rule they read as discontinued for ten
months of every twelve, so they were admitted each October and dropped again
each January. They are judged on a fourteen-month allowance instead — two
months past the clock change that should have refreshed them — so a genuinely
retired long-day period still ages out while a live one stops flickering.
`tests/test_clock_change_periods.py` holds both directions.
