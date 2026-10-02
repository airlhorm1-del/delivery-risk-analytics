# Delivery Promise Analytics: revenue at risk from late e-commerce deliveries

An end-to-end analytics pipeline on 99,441 real orders from Olist, a Brazilian e-commerce platform
that connects small sellers to the big online marketplaces. It brings in public holidays, weather and ECB exchange rates from public APIs, models everything in a
cloud warehouse with tested SQL (dbt), and finds out where late deliveries come from and how much
revenue they put at risk.

![Headline](docs/images/00_headline.png)

## Results (orders Jan 2017 - Aug 2018)

- **6.8% of delivered orders arrive after the promised date**, even though Olist promises about twice
  the actual delivery time (24.3 vs. 12.5 days on average).
- **EUR 264k of revenue is at risk (6.6% of GMV):** late orders rated 1-2 stars (EUR 183k) plus orders
  never delivered after their promised date (EUR 81k).
- **Lateness destroys satisfaction.** Late orders average 2.3 stars (on time: 4.3), and 62% are rated 1-2 stars.
  Even 1-2 days late nearly triples the share of 1-2 star reviews.
- **72% of late orders were handed to the carrier on time.** The delay happened in transit, on specific routes.
- **When a seller misses its hand-over deadline, the order is late 4 times as often** (21% vs. 5%). The
  seller's delay adds 7.3 days, but the customer's promise does not move.
- **One route, Sao Paulo -> Rio de Janeiro, carries 17% of the revenue at risk** with 8.5% of delivered
  orders (14% late). The Northeast is late 12.8% of the time, the Southeast 6.1%.
- **Paying by boleto (bank slip) adds about a day** for payment clearing, and the customer's promise
  ignores it. Olist's own seller deadline starts when payment clears (79% of deadlines are exactly
  N days after approval), but the customer's promise starts at purchase.
- **Rain and holidays matter much less than they first appear.** Rain looks like +5 points of lateness,
  but it is +1.2 once you compare orders to the same state in the same week. Holidays add 0.3 days,
  and the promise already allows 1.3.

![Why orders are late](docs/images/03_late_drivers.png)

### Recommendations

1. **Enforce the seller hand-over deadline** (8.9% of orders miss it), starting with the 54 watchlist
   sellers. They handle 4.4% of revenue but 9.2% of revenue at risk. When a deadline is missed, update the
   customer's delivery date straight away.
2. **Fix Sao Paulo -> Rio de Janeiro first**, then the Sao Paulo -> Northeast routes: the top 10 routes
   hold 60% of the revenue at risk.
3. **Start the delivery promise when payment clears**, so boleto customers are not promised a day
   the process cannot deliver.
4. **Add a buffer for peak periods.** Late rates reached 12-19% in Nov 2017 and Feb-Mar 2018, which no
   fixed formula absorbs.
5. **Investigate the 1,699 orders that never arrived** (EUR 81k): lost parcels or missing delivery
   scans. 76% of those customers left 1-2 stars.

Not recommended: replacing the promise formula. Back-tested on 2018 orders, promises based on each
route's past delivery times performed about the same as Olist's own
([decision 014](docs/decisions.md)).

Full numbers: [docs/results/02_findings.md](docs/results/02_findings.md). Every design choice and why:
[docs/decisions.md](docs/decisions.md).

## Simulated live orders (SYNTHETIC DATA)

> **The orders dated 2026 are simulated, not real.** They exist to show the pipeline running as a live
> system (new data every day, orders changing status, missed days caught up). All results above use the
> real 2017-2018 Olist orders only.

A simulator (`simulator/`) learns what a normal Olist day looked like (orders per weekday and season,
purchase hours, Black Friday, payment clearing, outcomes, reviews) and acts as a live shop. Every morning
at 07:00 a scheduled run:

- adds the orders "placed" since the last run (about 210 a day), dated today in Sao Paulo time, and fills in
  any days missed while the laptop was off;
- moves earlier orders on: payment approved, shipped, delivered on time or late, reviewed;
- uses today's real data: the ECB exchange rate, recent weather at the 27 state capitals, 2026-27
  holidays for the bank calendar, and Brazil's official inflation index (IPCA) to bring 2017-18 prices
  to today's reais;
- rebuilds and tests everything, then refreshes BigQuery.

Each simulated order copies one real order's basket and journey shape, then gets a new date, IDs, prices,
payment clearing on today's calendar, an outcome and a review. A validation compares 14 measures of four
simulated months with the real data (late rate, delivery days, weekday and hour patterns, reviews and
more): all are within tolerance ([docs/results/04_simulator_validation.md](docs/results/04_simulator_validation.md)).

![Simulator validation](docs/images/06_simulator_validation.png)

Labelled everywhere: `sim-` order IDs, separate `raw.sim_*` tables, and `data_source = 'simulated'` /
`is_synthetic = true` on every row. dbt tests fail if a synthetic row ever reaches the headline KPIs.

## Architecture

```mermaid
flowchart LR
    subgraph Sources
        K[Olist CSVs<br/>Kaggle]
        H[Nager.Date API<br/>holidays]
        W[Open-Meteo API<br/>weather]
        F[Frankfurter API<br/>ECB EUR/BRL]
        B[Banco Central API<br/>inflation]
    end
    SIM[Simulator<br/>SYNTHETIC live orders]
    subgraph Python["Python (ingestion/)"]
        E[extract, validate,<br/>stamp lineage]
    end
    subgraph Warehouse["Warehouse: BigQuery (prod) / DuckDB (dev)"]
        R[(raw)] --> S[(staging)] --> I[(intermediate)] --> M[(marts<br/>star schema)]
    end
    K & H & W & F & B --> E --> R
    K -. patterns .-> SIM
    B -. prices .-> SIM
    SIM --> R
    M --> P[Power BI data model + DAX]
    M --> A[analysis + independent check]
```

| Layer | What happens | Where |
|---|---|---|
| Extract | Download Olist; call 4 public APIs with retries, validation and lineage fields | `ingestion/` |
| Simulate | Simulated live orders (SYNTHETIC) in the Olist format, re-created up to "now" on every run | `simulator/` |
| Load | Land files unchanged in the `raw` schema, all CSV columns as text, row counts checked | `ingestion/load_*.py` |
| Staging | Types, clear names, one model per source table | `dbt/models/staging/` |
| Intermediate | Business rules: delivery outcome, stage timings, latest review, EUR rates, holidays and rain per order | `dbt/models/intermediate/` |
| Marts | Star schema (`fct_orders`, `fct_order_items`, 4 dimensions) plus route, seller, monthly and driver tables | `dbt/models/marts/` |
| Analysis | Findings, charts, promise back-test, independent recomputation in pandas | `analysis/` |
| Power BI | Data model, relationships and 18 DAX measures on the marts | `powerbi/` |

SQL techniques used: CTEs throughout, window functions (`row_number` for de-duplication,
`last_value ... ignore nulls` to carry exchange rates over weekends, rolling 3-month rates, `lag`,
`rank` and `percent_rank`, cumulative Pareto shares), range joins, Jinja-generated SQL and
warehouse-specific macros.

## Quality checks

- **129 dbt data tests:** keys unique and not null, relationships between tables, accepted values and
  ranges, reconciliations (e.g. GMV in the fact table equals the raw files to the cent), and the fence
  between real and synthetic data (no simulated order may reach the headline KPIs; no simulated event
  may lie in the future).
- **4 dbt unit tests** pin down the business rules with hand-made examples: delivered on the promised
  day = on time; weekend exchange rate = Friday's; latest review wins; a simulated order is overdue only
  once its promise has passed at its snapshot time.
- **34 Python unit tests** for the extractors, loaders and simulator (offline), e.g. the same day always
  gives the same simulated orders, and boleto payments clear only on bank days.
- **Simulator validation:** 14 measures of simulated orders compared with the real data, all within tolerance.
- **Independent verification:** `analysis/verify.py` recomputes 10 headline numbers from the raw files
  with pandas, without any SQL. All 10 match the warehouse exactly.
- **Two warehouses, one answer:** the same dbt project runs on DuckDB and on BigQuery (EU). Headline
  numbers, driver effects and route rankings are identical on both.
- **CI:** every push runs lint, tests and the whole pipeline from scratch on GitHub Actions.

Every data issue found and how it was resolved: [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md).
What each code file does: [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md).

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                   # Python 3.12 + exact library versions from uv.lock
uv run python run_pipeline.py             # download, APIs, simulator, load, dbt build + tests, analysis, checks (~3 min)
uv run python run_pipeline.py --daily     # the daily run: today's API data + simulated live orders (~1.5 min)
```

Daily at 07:00 on Windows: `scripts/register_daily_task.ps1` (remove with `scripts/unregister_daily_task.ps1`).

Cloud warehouse: log in once with `gcloud auth application-default login`, set `GCP_PROJECT_ID`,
then run `uv run python run_pipeline.py --bigquery`. Power BI data model and measures:
[powerbi/DASHBOARD_GUIDE.md](powerbi/DASHBOARD_GUIDE.md).

## Limitations

- Brazilian data from 2016-2018. The methods transfer to any marketplace; the numbers do not.
- Olist records one delivery date per order, so multi-seller orders share one outcome.
- Weather is measured at each state capital, not the customer's city.
- Driver effects compare like with like (same state, same week). They are not a causal model.
- The public holiday API lists only one state-level holiday for Brazil, so holidays are mostly national.
- The 2026 orders are simulated. They copy real 2017-18 orders, so they show the same patterns and add no new
  evidence about the real world.

## Data sources and attribution

- Olist, [Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), CC BY-NC-SA 4.0
- [Nager.Date](https://date.nager.at): public holidays
- [Open-Meteo](https://open-meteo.com): historical weather, CC BY 4.0
- [Frankfurter](https://frankfurter.dev): European Central Bank reference rates

## How this was built

Built with Claude Code, an AI coding assistant, which wrote the Python, the SQL and first drafts of
the write-ups. I chose the business problem and the direction, drawing on my background in banking
and logistics, and reviewed the findings, the design decisions and the numbers.
