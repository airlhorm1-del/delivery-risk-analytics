# Data quality report

Every problem found in the data, how big it was, what was done about it, and what now guards
against it. The raw files are never edited: they are loaded unchanged, and every cleaning rule lives
in SQL (dbt), where it is versioned, tested and documented.

## 1. Sources and the checks on arrival

| Source | What arrives | Checked on arrival |
|---|---|---|
| Olist (Kaggle) | 9 CSV files: 99,441 orders with items, payments, reviews, customers, sellers, products, geolocation | Row count in the warehouse = row count in the file, counted with a real CSV reader (review comments contain line breaks, so counting lines would be wrong) |
| Nager.Date | Brazilian public holidays per year | Required fields present; every holiday dated inside the requested year; no holiday without a date |
| Open-Meteo | Daily weather for the 27 state capitals | Every day of the window present for every capital; one row per capital and day; rainfall never negative |
| Frankfurter (European Central Bank) | Daily EUR/BRL reference rates | Rate between 2 and 8 BRL per EUR; no gap of more than 5 days between rates; one rate per date |
| Banco Central do Brasil (IBGE as backup) | Monthly consumer price inflation (IPCA) | Every monthly change between -3% and +5%; no missing months; latest month at most 3 months old. If both sources are down, the saved series is kept only if it passes the same age check |

Bad data stops the run at this point instead of reaching the reports.

## 2. Issues found in the data, and how they were resolved

| # | Issue | Size | Resolution | Guarded by |
|---|---|---|---|---|
| 1 | Zip-code prefixes start with 0 (e.g. Sao Paulo `01001`); loaded as numbers they become `1001` and stop matching the location table | 23,995 customers | Every CSV column is loaded as text; types are set in SQL | Relationship tests: every customer and seller state exists |
| 2 | One file starts with an invisible byte-order mark; one database ignored it, the other refused the file | 1 file | The header is read with an encoding that drops the mark | Python test with a file that has the mark |
| 3 | Incomplete months at the edges of the data | Sep-Dec 2016: 329 orders (none in Nov 2016); Sep-Oct 2018: 20 | KPIs use the 20 complete months, Jan 2017 to Aug 2018; all orders are kept and flagged | Test: the KPI window holds exactly 20 months |
| 4 | "Late" depends on how dates are compared: the promised date is always midnight, so comparing timestamps makes orders delivered *on* the promised day late | 1,292 orders (7,826 late instead of 6,534) | Dates are compared, not times | Unit test: delivered on the promised day = on time |
| 5 | Timestamps out of order | 1,350 orders handed to the carrier before payment approval, 165 before purchase, 23 delivered before hand-over | Flagged (`has_timestamp_anomaly`), not deleted; left out only of the stage-timing averages; a late order whose cause cannot be told apart is labelled "Unclear (timestamp issue)" | Accepted values for `late_cause` |
| 6 | Orders that never arrive | 1,107 "shipped" plus 622 stuck earlier, all past their promised date | New outcome "Overdue, not delivered", counted in revenue at risk | Accepted values for `delivery_outcome`; unit test of the delivery rules |
| 7 | Several reviews for one order | 547 orders | The most recent answer is kept | Unit test: latest review wins; one review per order (uniqueness test) |
| 8 | Do payments add up? | 98,362 of 98,665 orders match item prices + freight to the cent | Revenue = item prices + freight (what each seller sold) | Test: GMV equals the raw files to the cent |
| 9 | Orders with several sellers | 1,278 orders | A "primary seller" (highest item value) is used for routes; item-level tables keep every seller | Test: each order's items add up to the order value; primary seller never missing |
| 10 | Products without a category, and categories missing from the translation list | 610 products; 2 categories | Labelled "unknown"; the 2 translations added as a small seed file | Not-null test on the English category name |
| 11 | Locations outside Brazil (bad geocoding) | 42 of about 1 million points | Flagged (`is_inside_brazil`) and left out of the zip-code centre points | One centre point per zip prefix (uniqueness test) |
| 12 | Misspelled source columns | `product_name_lenght`, `product_description_lenght` | Renamed in staging | - |
| 13 | Blank product measurements loaded as empty text | 610 products | Converted to missing values | - |
| 14 | No exchange rate on weekends and holidays (the ECB publishes on working days only) | All non-working days | The last published rate carries forward (Friday's rate on Saturday and Sunday) | Unit test: weekend rate = Friday's |

Full numbers: [results/01_data_profile.md](results/01_data_profile.md).

## 3. Issues found while running the pipeline every day

| # | Issue | Resolution |
|---|---|---|
| 15 | The first version of the order simulator was 9.3% late instead of about 4.2% | Each simulated order now copies a real order's whole journey instead of drawing each timing separately; all 14 validation measures pass |
| 16 | The weather archive refused "today" shortly after midnight | Live weather ends yesterday and steps back a day if the archive is not ready |
| 17 | BigQuery sandbox tables expire 60 days after creation, even when overwritten | After each load, the table's expiry date is pushed forward |
| 18 | The first scheduled 07:00 run failed: the laptop slept in the middle of an upload and one table went missing | The daily script keeps Windows awake while it works, uploads retry three times, and tables are replaced in one step so a failed upload leaves the old data in place |

## 4. Real and simulated data are kept apart

Simulated live orders are labelled `is_synthetic = true` and `data_source = 'simulated'` on every row.
Tests make sure no simulated order reaches the headline KPIs and no simulated event lies in the
future. The findings and the independent verification below are identical with or without the
simulated orders.

## 5. Automated checks

| Check | What it covers | Result |
|---|---|---|
| 129 dbt data tests | Unique and non-missing keys, relationships between tables, accepted values and ranges, reconciliations to the raw files, the real/simulated fence | All pass |
| 4 dbt unit tests | The business rules on hand-made examples (issues 4, 7, 14 and the simulated-order rule) | All pass |
| 39 Python tests | Extractors, loaders and the simulator, offline | All pass |
| Simulator validation | 14 measures of simulated orders against the real data | All within tolerance ([results/04_simulator_validation.md](results/04_simulator_validation.md)) |
| Independent verification | 10 headline numbers recomputed from the raw files with pandas, no SQL | 10 of 10 match exactly ([results/03_verification.md](results/03_verification.md)) |
| Two warehouses | The same dbt project on DuckDB and on BigQuery | Identical results |
| Continuous integration | Every push to GitHub runs lint, tests and the whole pipeline from scratch | Passing |
