# Data audit — collector_elexon_uk

- Audit seed: `20260918`
- Source version: live capture on 2026-09-18
- Test result: **64 passed**
- Execution: **PASS**
- Overall: **PASS** — Amostra live cobre início, meio, últimos meses e ponta; valores, zero-pair filter, unidades e PIT conservador foram validados.
- Output: 4,398 observations, 126 series, 2016-09-12 to 2026-09-18.
- Sample: 20; values matched: 20; failures: 0; not verifiable: 0.

## Observation evidence

| # | Series | Period | Collector | Official source | Unit/frequency evidence | Result |
|---:|---|---|---:|---:|---|---|
| 1 | `ELEXON_MID_APXMIDP_VOLUME_SP34` | 2016-09-12 | 537.35 | 537.35 | MWh; daily per settlement period; JSON data[606].volume | **PASS** |
| 2 | `ELEXON_MID_APXMIDP_PRICE_SP20` | 2026-09-18 | 89.19 | 89.19 | GBP/MWh; daily per settlement period; JSON data[35].price | **PASS** |
| 3 | `ELEXON_MID_APXMIDP_VOLUME_SP22` | 2016-09-13 | 370.25 | 370.25 | MWh; daily per settlement period; JSON data[534].volume | **PASS** |
| 4 | `ELEXON_MID_APXMIDP_VOLUME_SP40` | 2016-09-21 | 910.9 | 910.9 | MWh; daily per settlement period; JSON data[350].volume | **PASS** |
| 5 | `ELEXON_MID_APXMIDP_PRICE_SP20` | 2016-09-20 | 40.08 | 40.08 | GBP/MWh; daily per settlement period; JSON data[485].price | **PASS** |
| 6 | `ELEXON_MID_APXMIDP_VOLUME_SP13` | 2016-09-19 | 992.5 | 992.5 | MWh; daily per settlement period; JSON data[589].volume | **PASS** |
| 7 | `ELEXON_MID_APXMIDP_PRICE_SP31` | 2026-02-04 | 102.34 | 102.34 | GBP/MWh; daily per settlement period; JSON data[418].price | **PASS** |
| 8 | `ELEXON_MID_APXMIDP_VOLUME_SP27` | 2021-09-18 | 591.5 | 591.5 | MWh; daily per settlement period; JSON data[142].volume | **PASS** |
| 9 | `ELEXON_MID_APXMIDP_PRICE_SP04` | 2025-11-27 | 56.13 | 56.13 | GBP/MWh; daily per settlement period; JSON data[375].price | **PASS** |
| 10 | `ELEXON_MID_APXMIDP_VOLUME_SP27` | 2021-09-17 | 1709.7 | 1709.7 | MWh; daily per settlement period; JSON data[238].volume | **PASS** |
| 11 | `ELEXON_MID_APXMIDP_PRICE_SP25` | 2026-09-16 | 138.76 | 138.76 | GBP/MWh; daily per settlement period; JSON data[217].price | **PASS** |
| 12 | `ELEXON_MID_APXMIDP_VOLUME_SP48` | 2026-09-17 | 2649.9 | 2649.9 | MWh; daily per settlement period; JSON data[75].volume | **PASS** |
| 13 | `ELEXON_MID_APXMIDP_VOLUME_SP14` | 2026-09-08 | 2889.95 | 2889.95 | MWh; daily per settlement period; JSON data[552].volume | **PASS** |
| 14 | `ELEXON_MID_APXMIDP_PRICE_SP32` | 2025-11-29 | 68.59 | 68.59 | GBP/MWh; daily per settlement period; JSON data[127].price | **PASS** |
| 15 | `ELEXON_MID_APXMIDP_PRICE_SP37` | 2025-11-25 | 152.0 | 152.0 | GBP/MWh; daily per settlement period; JSON data[501].price | **PASS** |
| 16 | `ELEXON_MID_N2EXMIDP_VOLUME_SP02` | 2025-11-29 | 207.4 | 207.4 | MWh; daily per settlement period; JSON data[188].volume | **PASS** |
| 17 | `ELEXON_MID_APXMIDP_VOLUME_SP11` | 2016-09-20 | 291.8 | 291.8 | MWh; daily per settlement period; JSON data[503].volume | **PASS** |
| 18 | `ELEXON_MID_APXMIDP_VOLUME_SP20` | 2016-09-17 | 646.5 | 646.5 | MWh; daily per settlement period; JSON data[156].volume | **PASS** |
| 19 | `ELEXON_MID_N2EXMIDP_VOLUME_SP45` | 2021-09-14 | 25.0 | 25.0 | MWh; daily per settlement period; JSON data[491].volume | **PASS** |
| 20 | `ELEXON_MID_APXMIDP_PRICE_SP02` | 2026-09-10 | 163.8 | 163.8 | GBP/MWh; daily per settlement period; JSON data[384].price | **PASS** |

## Filtering and metadata

- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2016-09-12T00:00Z&to=2016-09-18T23:59Z&format=json","raw_rows":614,"zero_pairs_removed":309}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2016-09-19T00:00Z&to=2016-09-25T23:59Z&format=json","raw_rows":611,"zero_pairs_removed":302}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2021-09-13T00:00Z&to=2021-09-19T23:59Z&format=json","raw_rows":672,"zero_pairs_removed":332}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2025-11-24T00:00Z&to=2025-11-30T23:59Z&format=json","raw_rows":671,"zero_pairs_removed":328}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2026-02-02T00:00Z&to=2026-02-08T23:59Z&format=json","raw_rows":672,"zero_pairs_removed":335}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2026-09-07T00:00Z&to=2026-09-13T23:59Z&format=json","raw_rows":672,"zero_pairs_removed":334}`
- `{"file":"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?from=2026-09-14T00:00Z&to=2026-09-18T23:59Z&format=json","raw_rows":452,"zero_pairs_removed":225}`

The audit read the captured official artifact independently of the collector parser. It checked identifier linkage, published labels, units, frequency and first/latest boundaries. Source artifacts are identified by SHA-256 in the audit evidence.

## Point-in-time and revisions

Predictor as-of queries filter availability before ranking vintages. `inferred` and `unknown` remain excluded by default. Current mutable-file backfills are recorded at `first_seen`; later observed revisions create later vintages and do not inherit an original release timestamp. Actual pre-collection historical editions remain `NOT_VERIFIABLE` unless an archived source file exists.

## Corrections

- Volume passou de other para megawatt_hours.
- Settlement date deixou de preencher last_publish_date, pois a API não fornece publication timestamp.

## Result

**PASS** — Amostra live cobre início, meio, últimos meses e ponta; valores, zero-pair filter, unidades e PIT conservador foram validados.
