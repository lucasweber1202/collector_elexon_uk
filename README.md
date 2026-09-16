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
| `elexon_market_index_prices` | [Market Index Data (MID)](https://bmrs.elexon.co.uk/api-documentation) | half-hourly settlement periods | 2016-09-12 → | 96 |

Endpoint: `https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index`
(no authentication required).

### Settlement periods live in the identifier

`time_series.reference_date` is a `DATE` and the fleet schema is not changed for
one source. So the settlement date is the reference date and the settlement
period is encoded in the series identifier:

```
ELEXON_MID_APXMIDP_PRICE_SP01 … ELEXON_MID_APXMIDP_PRICE_SP50
ELEXON_MID_APXMIDP_VOLUME_SP01 … ELEXON_MID_APXMIDP_VOLUME_SP50
```

The primary key `(series_id, reference_date, vintage_date)` is untouched and
every half-hour is its own series. A clock-change day has 46 or 50 periods, not
48, which is why the space runs to SP50; both cases are covered by tests.

Aggregation to daily, monthly or month-to-date belongs to the research layer.

### N2EXMIDP is not collected

The API returns two providers. Verified on 2026-09-16 across eleven sampled days
spanning 2016-09 to 2026-09 plus an exhaustive scan of January 2024,
**`N2EXMIDP` publishes `price = 0.00` and `volume = 0.000` in every settlement
period without exception.**

A market index price of zero with zero traded volume, sustained for ten years,
is a non-reporting placeholder, not an economic price. Storing it would put
~175,000 synthetic zeros into the research layer, where averaging across
providers would halve every price.

It is excluded — but not silently. `validate` re-checks on every run that the
excluded provider is still entirely zero and **fails** if it ever starts
reporting, so the exclusion cannot outlive its evidence.

### Seven-day windows

Verified against the live API: a request spanning more than seven days is
rejected with HTTP 400. Collection walks the history in seven-day windows, and
**each window's response body is one raw snapshot**. The body is byte-stable —
the same window requested twice returns identical bytes and the same SHA-256 —
which is what makes an unchanged rerun a no-op in `source_snapshots`.

A full backfill from 2016-09-12 is roughly 520 requests. Set
`COLLECTOR_ELEXON_START=YYYY-MM-DD` to bound a development run; the default is
the full published history.

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
