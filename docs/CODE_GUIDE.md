# Code guide

What every file does, in the order the pipeline runs it, in plain language. Each file also explains
itself at the top.

## How a run works

```
run_pipeline.py
  1. Extract    ingestion/*.py      download Olist, call the 4 APIs        -> data/raw/
  2. Simulate   simulator/run.py    simulated live orders up to "now"      -> data/raw/sim/  (SYNTHETIC)
  3. Load       ingestion/load_*.py raw files, unchanged                   -> warehouse schema "raw"
  4. Transform  dbt build           staging -> intermediate -> marts, with all tests
  5. Analyse    analysis/*.py       profile, findings, charts, independent check
  6. Export     analysis/export_powerbi.py  the marts as Parquet           -> powerbi/data/
```

The warehouse is DuckDB on the laptop (`data/warehouse/delivery_risk.duckdb`) or Google BigQuery in the
cloud (`--bigquery`); the same code runs on both. `run_pipeline.py` stops at the first failure.

## Top level

| File | What it does |
|---|---|
| `run_pipeline.py` | Runs the whole pipeline end to end and stops at the first failure. Flags: `--skip-extract` (reuse downloaded files), `--bigquery` (also load and build in BigQuery), `--daily` (the 07:00 run) |
| `pyproject.toml`, `uv.lock` | The Python version and the exact package versions, so every machine installs the same thing |
| `.github/workflows/ci.yml` | On every push to GitHub: lint, all tests and the whole pipeline from scratch |

## 1. Extract: `ingestion/`

| File | What it does |
|---|---|
| `config.py` | Settings in one place: folders, API addresses, the analysis window, simulator settings |
| `http_client.py` | One web connection for every extractor: timeouts, automatic retries, a polite user agent |
| `landing.py` | Saves every download into `data/raw` the same way, with when and where it came from |
| `olist.py` | Downloads the Olist dataset from Kaggle and unpacks the 9 CSV files |
| `holidays.py` | Brazilian public holidays from the Nager.Date API; checks the fields and the year of each holiday |
| `weather.py` | Daily weather for the 27 state capitals from the Open-Meteo archive; checks no day is missing |
| `fx.py` | Daily EUR/BRL rates (European Central Bank) from the Frankfurter API; rejects impossible rates and gaps |
| `ipca.py` | Brazil's monthly inflation (IPCA) from the Banco Central do Brasil API, used to put simulated prices in today's money |
| `sources.py` | The single list of which landed file becomes which raw table, used by both loaders so they cannot drift apart |

## 2. Simulate: `simulator/` (SYNTHETIC DATA)

| File | What it does |
|---|---|
| `fit.py` | Learns the patterns of the real 2017-2018 orders (volumes per weekday and season, purchase hours, routes, payment types, timings) and saves them as `model/sim_model.json` |
| `distributions.py` | How the learned patterns are stored and drawn from |
| `templates.py` | Picks real Olist orders as templates, so each simulated order copies a real basket and journey |
| `bank_calendar.py` | Brazilian bank days and Black Friday: bank-slip payments only clear on bank days |
| `engine.py` | Creates the simulated orders of a day and decides each order's whole journey (approval, hand-over, delivery, review) when it is placed |
| `run.py` | Runs the simulated shop up to "now" (Sao Paulo time) and writes it in the Olist file format; missed days are filled in |
| `validate.py` | Simulates four normal months and compares 14 measures with the real data |

## 3. Load: `ingestion/load_*.py`

| File | What it does |
|---|---|
| `load_duckdb.py` | Loads every landed file, unchanged and as text, into the local DuckDB warehouse; checks row counts against the files |
| `load_bigquery.py` | The same into Google BigQuery: replaces each table in one step, retries failed uploads, keeps sandbox tables from expiring |

## 4. Transform: `dbt/`

dbt turns the raw tables into clean, tested tables with SQL. The models run in three layers.

| Folder or file | What it does |
|---|---|
| `dbt_project.yml`, `profiles.yml`, `packages.yml` | The project settings, the two warehouse connections (DuckDB and BigQuery) and the dbt_utils package |
| `seeds/brazil_states.csv` | The 27 states with region and capital |
| `seeds/category_translation_additions.csv` | The 2 product categories missing from Olist's translation list |
| `macros/` | Small SQL helpers that work the same on both warehouses: calendar days, weekday numbers, days between dates, distance in km, percentiles, number types, schema names |
| `tests/` | 4 custom tests: GMV equals the raw files to the cent; the KPI window has 20 months; the monthly table matches the order table; each order's items add up to the order |

**Staging** (`models/staging/`): one model per source table. Types, clear names, nothing removed.

| Model | What it does |
|---|---|
| `stg_olist__orders` | One row per order with typed timestamps and clearer names |
| `stg_olist__order_items` | One row per item; money stays in reais (BRL) |
| `stg_olist__order_payments` | One row per payment method used on an order |
| `stg_olist__order_reviews` | Review rows as received (an order can have several) |
| `stg_olist__customers` | Customers; `customer_unique_id` is the actual person |
| `stg_olist__sellers` | Sellers and their location |
| `stg_olist__products` | Products; fixes the misspelled "lenght" columns and blank measurements |
| `stg_olist__category_translation` | Portuguese to English category names, plus the 2 missing ones |
| `stg_olist__geolocation` | About 1 million location points; flags the few outside Brazil |
| `stg_external__holidays` | One row per holiday, nationwide or for specific states |
| `stg_external__weather` | One row per state capital per day |
| `stg_external__fx_rates` | The ECB rate as published (working days only) |
| `stg_external__ipca` | Monthly inflation |
| `stg_simulated__*` (5 models) | The simulated orders, items, payments, reviews and customers, typed exactly like the real ones and labelled synthetic |

**Intermediate** (`models/intermediate/`): the business rules.

| Model | What it does |
|---|---|
| `int_orders_unioned`, `int_order_items_unioned`, `int_order_payments_unioned`, `int_order_reviews_unioned`, `int_customers_unioned` | Real and simulated rows in one table each; `data_source` and `is_synthetic` say which feed a row came from |
| `int_fx_rates_daily` | One exchange rate for every calendar day; weekends and holidays carry the last published rate |
| `int_state_holidays` | One row per state per holiday date |
| `int_zip_centroids` | One location point per zip prefix (the average of its points inside Brazil) |
| `int_order_items_summary` | Per order: item totals, the seller's hand-over deadline and the primary seller |
| `int_order_payments_summary` | Per order: how it was paid (the method that paid most) |
| `int_order_reviews_latest` | One review per order: the most recent answer |
| `int_order_timeline` | The delivery rules: how long each stage took, whether the promise was kept and, for late orders, whose stage it was. Unit-tested |
| `int_order_context` | Outside conditions per order over fixed windows: holidays in the first 10 days, heavy rain in the first 7 days of transit, distance |

**Marts** (`models/marts/`): the tables the analysis and Power BI use.

| Model | What it does |
|---|---|
| `fct_orders` | The central table: one row per order with route, timings, outcome, money in BRL and EUR, review and outside conditions |
| `fct_order_items` | One row per item, so sellers and categories get their share of each order |
| `dim_date` | One row per calendar day with holidays and the exchange rate |
| `dim_states`, `dim_sellers`, `dim_products` | States, sellers and products for slicing |
| `mart_monthly_kpis` | Headline KPIs per month, with a 3-month rolling late rate |
| `mart_route_performance` | One row per route, ranked by revenue at risk (Pareto) |
| `mart_seller_performance` | One row per seller; the watchlist holds sellers late at least twice as often as the platform |
| `mart_late_drivers` | Late rate with and without each condition, raw and compared fairly (same state, same week) |
| `mart_live_daily` | SYNTHETIC: the simulated live shop, one row per day |

Each layer's `.yml` file lists the tests on its models.

## 5. Analyse: `analysis/`

| File | What it does |
|---|---|
| `common.py` | Shared folders, the warehouse connection and number formatting |
| `profile.py` | Looks at the raw data before anything is changed; writes `docs/results/01_data_profile.md` |
| `findings.py` | Answers the business questions from the marts; writes `docs/results/02_findings.md` and the charts in `docs/images/` |
| `verify.py` | Recomputes 10 headline numbers straight from the raw files with pandas (no SQL) and fails if any differs; writes `docs/results/03_verification.md` |
| `export_powerbi.py` | Writes the mart tables as Parquet files to `powerbi/data/` |

## 6. Schedule: `scripts/`

| File | What it does |
|---|---|
| `run_daily.ps1` | The daily run: today's API data, the simulator, the DuckDB build and tests, the verification, the Parquet export, then BigQuery. Keeps Windows awake while it works and logs everything |
| `register_daily_task.ps1`, `unregister_daily_task.ps1` | Create or remove the Windows scheduled task that runs `run_daily.ps1` at 07:00 |

## Tests: `tests/`

| File | What it does |
|---|---|
| `test_holidays.py` | The holiday extractor, with a saved example answer (runs offline) |
| `test_extractors.py` | The exchange-rate and weather extractors and the loaders' shared parts, e.g. a file with a byte-order mark |
| `test_simulator.py` | The simulator: the same day always gives the same orders, bank-slip payments clear only on bank days |

## Power BI: `powerbi/`

| File | What it does |
|---|---|
| `DASHBOARD_GUIDE.md` | The data model, relationships, DAX measures and report pages |
| `theme.json` | The colours, matching the charts in `docs/images/` |
