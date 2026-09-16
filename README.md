# collector_elexon_uk

Standalone collector for Elexon BMRS datasets relevant to UK inflation.

The repository owns Elexon extraction and raw point-in-time persistence. It does
not map predictors to CPI targets or calculate modelling features; those tasks
belong to [`uk_inflation_predictors`](https://github.com/lucasweber1202/uk_inflation_predictors).

Schema: `collector_elexon_uk`.

## Attribution and licence

> Contains BMRS data © Elexon Limited copyright and database right.

BMRS open data is published under Elexon's
[Licence to use BMRS open data](https://www.elexon.co.uk/bsc/operations-settlement/bsc-central-services/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/),
a worldwide, royalty-free, perpetual, non-exclusive licence to copy, adapt and
exploit the data, including commercially, subject to attribution. Automated
access and historical storage are permitted. The attribution is carried in every
series description so it travels with the data into the research layer.

## Current coverage

| `source_id` | Dataset | Frequency | History | Series |
| --- | --- | --- | --- | --- |
| `elexon_market_index_prices` | [Market Index Data (MID)](https://bmrs.elexon.co.uk/api-documentation) | half-hourly settlement periods | 2016-09-12 → | 196 |

The verified full-history build contains **196 series and 345,986 stored
observations across 523 source snapshots**: 100 APXMIDP series and 96 N2EXMIDP
series. The provider totals differ because APXMIDP reports the clock-change
settlement periods SP49/SP50 while the sparse N2EXMIDP history does not.

Endpoint: `https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index`
(no authentication required).

### Settlement periods live in the identifier

`time_series.reference_date` is a `DATE` and the fleet schema is not changed for
one source. So the settlement date is the reference date and the settlement
period is encoded in the series identifier:

```
ELEXON_MID_APXMIDP_PRICE_SP01 … ELEXON_MID_APXMIDP_PRICE_SP50
ELEXON_MID_APXMIDP_VOLUME_SP01 … ELEXON_MID_APXMIDP_VOLUME_SP50
ELEXON_MID_N2EXMIDP_PRICE_SP01 … ELEXON_MID_N2EXMIDP_PRICE_SP48
ELEXON_MID_N2EXMIDP_VOLUME_SP01 … ELEXON_MID_N2EXMIDP_VOLUME_SP48
```

The primary key `(series_id, reference_date, vintage_date)` is untouched and
every half-hour is its own series. A clock-change day has 46 or 50 periods, not
48, which is why the space runs to SP50; both cases are covered by tests.

Aggregation to daily, monthly or month-to-date belongs to the research layer.

### Both providers are collected; the zero pair is a placeholder

The API returns two providers. A row whose price **and** volume are both exactly
zero is not stored: it is the API's way of saying the provider did not report
that settlement period, not an economic observation.

That rule was established against the **full** published history — 523 windows,
345,379 rows, 2016-09 to 2026-09:

| Provider | Rows | Both zero | Genuinely reporting |
| --- | --- | --- | --- |
| `APXMIDP` | 172,713 | 221 | 172,492 |
| `N2EXMIDP` | 172,666 | 172,165 | **501** |

`N2EXMIDP` reports rarely — 501 periods on 168 distinct dates across ten years —
but when it does, the values are real: −65.8 to 450.23 GBP/MWh on volumes of 25
to 519 MWh. Dropping the provider would discard genuine data; storing its
172,165 zero rows would corrupt any average across providers. Skipping only the
zero *pair* keeps both correct.

The rule is deliberately the **conjunction**. Six rows in the full history carry
a zero price with a non-zero volume — three per provider — and those are genuine
zero-price trades, so they are stored. No row anywhere carries a non-zero price
with zero volume.

> An earlier reading of this source, based on eleven sampled days, concluded
> that `N2EXMIDP` was entirely silent and excluded the provider. The full
> history disproved it. The exclusion was caught by a guard written to re-prove
> it on every run, which is why the rule shipped here is the placeholder rule
> rather than a provider exclusion.

### Seven-day windows

Verified against the live API: a request spanning more than seven days is
rejected with HTTP 400. Collection walks the history in seven-day windows, and
**each window's response body is one raw snapshot**. The body is byte-stable —
the same window requested twice returns identical bytes and the same SHA-256 —
which is what makes an unchanged rerun a no-op in `source_snapshots`.

A full backfill from 2016-09-12 is 523 requests and takes roughly 15 minutes.
Set `COLLECTOR_ELEXON_START=YYYY-MM-DD` to bound a development run; the default
is the full published history.

**The trailing window is live.** The last window covers today, and today is
still being published, so a rerun minutes later legitimately sees different
bytes and records a *new snapshot* for that window alone. That is the snapshot
contract working — changed content, new row — not churn. Verified over two full
back-to-back runs: 522 of 523 windows re-hashed identically and wrote nothing;
only the trailing window changed (35,801 → 35,944 bytes). The data tables were
untouched: 0 new `time_series`, `availability` or `metadata` rows.

Collecting today is deliberate. It is what lets a period first seen between two
runs be recorded as `first_seen`, which is the only genuine point-in-time
evidence this source can produce.

## Limitations

The BMRS API exposes **no publication timestamp**, so no observation can carry
`official_timestamp`. See `POINT_IN_TIME.md`: the backfill is `inferred` and
periods that appear between two runs are witnessed as `first_seen`. A
point-in-time backtest that refuses reconstructed availability will therefore
only see data this collector has itself witnessed appearing.

## Run

```bash
python -m pip install -r requirements.txt
cp .env.example .env
COLLECTOR_ELEXON_START=2026-01-01 python main.py   # bounded run
python main.py                                     # full history
```
