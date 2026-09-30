# Decision log

Short records of design choices: what was decided, what else was considered, and why.

## 001: Olist as the primary dataset

**Decision:** Use the Olist Brazilian e-commerce dataset (99,441 orders, Sep 2016 - Oct 2018).
**Alternatives:** DataCo Smart Supply Chain (one flat, partly synthetic file); UCI Online Retail II (no delivery data); public fraud datasets (anonymised features, unusable for a business dashboard).
**Why:** Olist is real, anonymised commercial data in 9 related tables, so it needs genuine data modelling. It has both the *promised* and the *actual* delivery date, which is the core of the question, and it has payment methods, which link payment clearing to delivery delays.

## 002: BigQuery for the cloud warehouse, DuckDB as its local stand-in

**Decision:** The dbt project has two targets: `dev` = DuckDB (a database in one file, no account) and `prod` = Google BigQuery in the EU region. The same SQL runs on both.
**Alternatives:** Snowflake (the trial ends after 30 days, so the project would stop working); BigQuery only (every test run would need a login and network).
**Why:** Development, tests and CI run anywhere in two minutes with no credentials. BigQuery is where Power BI reads from. The BigQuery sandbox needs no credit card; its limits (tables expire after 60 days, no INSERT/UPDATE/MERGE) don't matter, because every run rebuilds the tables from source with `CREATE OR REPLACE`.
**How the SQL stays portable:** dbt's cross-database macros (`dbt.datediff`, `dbt.dateadd`, `dbt.listagg`, type macros) plus four small macros of our own (`array_contains`, `percentile`, `type_double`, `iso_day_of_week`) that dbt switches per warehouse. First live BigQuery run (30 Sep 2026): all 131 dbt steps passed, and the headline numbers, the driver table and the route table are identical to DuckDB to the cent. That run found two differences the offline checks could not: one Olist file starts with an invisible byte-order mark that DuckDB ignores but BigQuery rejected (fixed in the loader, with a test), and the route percentile interpolated on DuckDB but not on BigQuery (both now return an actual observed value).

## 003: ELT, with raw data landed unchanged

**Decision:** Python only extracts, validates and stamps lineage. All cleaning and business logic lives in SQL (dbt).
**Why:** The raw layer is an audit trail: any dashboard number can be traced back to the file or API response it came from. The logic is version-controlled and tested, and can be re-run without calling the APIs again.

## 004: Raw CSV columns loaded as text

**Decision:** Every Olist column lands as text; the staging models convert types.
**Why:** 23,995 customers have zip prefixes with a leading zero (e.g. 01001, Sao Paulo). Loaded as numbers they would become 1001 and no longer join to the geolocation table. A failed conversion in staging is visible and tested instead of silently guessed at load time.

## 005: NDJSON as the landing format for API data

**Decision:** API responses are written one record per line (NDJSON) with `_source_url` and `_ingested_at` added.
**Why:** It is BigQuery's native JSON load format and keeps nested lists (the states a regional holiday applies to) as arrays, which are unpacked in SQL.

## 006: "Late" is judged on dates, not timestamps

**Decision:** An order is late when the delivery *date* is after the promised *date*.
**Why:** The promised date is stored as midnight. Comparing timestamps would count 1,292 orders delivered during the promised day as late, and inflate the late count from 6,534 to 7,826 (+20%).

## 007: KPI window of 20 complete months

**Decision:** Headline numbers use orders purchased 1 Jan 2017 - 31 Aug 2018. All orders stay in the tables, flagged with `is_in_kpi_window`.
**Why:** Sep-Dec 2016 has 329 orders (Nov 2016 has none) and Sep-Oct 2018 has 20. Monthly trends and averages over those months would be noise.

## 008: Revenue at risk definition

**Decision:** Revenue at risk = GMV of orders where the promise was broken **and** there is evidence of damage: (a) delivered late and rated 1-2 stars, or (b) never delivered although the promised date passed before the data cut-off (17 Oct 2018).
**Alternatives:** all late GMV (EUR 291k: includes customers who did not mind); a lifetime-value model of lost future purchases (only 3% of customers ever order twice, so it would be guesswork).
**Why:** Each order counted has a concrete reason to expect a refund, a complaint or a lost customer, and the number is easy to explain and check.

## 009: Money in EUR at the ECB rate of the purchase date

**Decision:** GMV = item prices + freight (BRL), divided by the ECB EUR/BRL reference rate of the purchase date. Weekends and holidays use the last published rate. Money stays an exact decimal in BRL; only the EUR figure is floating point.
**Why:** The audience is German, and the ECB rate is the official reference. Using each day's rate (not one average) keeps each order's value as it was when it happened.

## 010: One seller per order for routes

**Decision:** Each order is placed on one route (seller state -> customer state) using its "primary" seller, the one with the highest item value. Seller-level analysis uses item rows, so every seller gets its own items.
**Why:** 1,278 orders (1.3%) have several sellers but only one delivery date. A route needs one origin.

## 011: Weather at the state capital

**Decision:** Daily rain at each of the 27 state capitals stands in for the whole state.
**Alternatives:** weather per customer city (about 4,000 cities, i.e. about 4,000 API calls).
**Why:** 27 calls instead of thousands. The capitals' coordinates were checked against Olist's own geolocation data: all 27 within 0.1 degrees (about 11 km). The limitation is stated wherever rain results are shown.

## 012: Fixed-length windows for holidays and rain

**Decision:** Holidays are counted in the first 10 days after purchase, and heavy rain in the first 7 days after hand-over, for every order.
**What went wrong first:** the first version counted holidays and rain up to the promised date. Orders with longer promises collected more rainy days and holidays *and* were rarely late (they had more time), so rain appeared to *reduce* lateness by 8 percentage points. That was a measurement artefact, not a finding. Equal windows for all orders removed it.

## 013: Compare like with like (same state, same week)

**Decision:** Each driver's effect is measured by comparing exposed and unexposed orders going to the same state in the same week, then averaging those differences, weighted by exposed orders. Rain is compared within the same *shipping* week, because it is measured from hand-over.
**Why:** Raw comparisons mix in geography and season. Rain looked like +5.0 points raw but is +1.2 within the same state and shipping week, because the rainy season overlaps the Black Friday and Feb-Mar peaks. Holidays looked like -4.0 points within the same month, because Black Friday and Feb-Mar late orders fell in holiday-free parts of those months; within the same week the effect is -0.9. This is a standardised difference: simple enough to explain, and it removes the biggest distortions. It is not a causal model, and it is not presented as one.

## 014: Test the promise formula before recommending a new one

**Decision:** Route-based promises (a percentile of each route's 2017 delivery times) were back-tested on Jan-Aug 2018 against Olist's actual promises before being recommended.
**Result:** At the same average promise length, the route rule performs about the same as Olist's own (Olist: 23.4 days, 7.7% late; route P95: 25.6 days, 5.4% late; route P90: 20.6 days, 10.2% late). So the recommendation is *not* "replace the promise formula" but "fix the specific failures" (seller hand-over, a few routes, peaks, boleto). Testing a hypothesis and reporting that it failed is part of the result.

## 015: Simulated live orders: copy real orders, re-time them on today's calendar

**Decision:** A simulator (`simulator/`) acts as a live shop. Each simulated order copies one real delivered Olist order from the normal months (its basket and the shape of its journey: promise, seller deadline, hand-over and transit times) and gives it a new date, new IDs, prices raised by official Brazilian inflation (IPCA), a payment that clears on today's bank calendar, a Christmas-season slowdown, an outcome and a review. Daily volume, purchase hours, payment clearing, outcome rates and review behaviour are learned from the real data into `simulator/model/sim_model.json`.
**What went wrong first:** the first version drew promise, hand-over and transit times separately from per-route distributions. The validation (`simulator/validate.py`) showed 9.3% late orders against 4.2% in reality, and too many missed seller deadlines. Drawing the timings separately broke the links between them (a bulky order to a remote town gets a long promise *and* a long journey). Copying each real order's whole journey fixed it: all 14 validation measures are now within tolerance.
**Why copy rather than invent:** the simulated data has to look like Olist's, so the pipeline, tests and dashboard can treat it as one more feed. Copying real combinations is the simplest way to be realistic, and the validation proves it.

## 016: The simulated shop is re-created on every run (no stored state)

**Decision:** Each day of the simulated shop has a fixed random seed. Every run re-creates every day from 2 Jul 2026 up to "now" (Sao Paulo time) and reveals only the events that have happened by then.
**Why:** No state file can get lost or corrupted. Missed days (laptop off) fill in automatically. Running twice gives identical data. A fresh GitHub machine (Option B) can rebuild the whole simulated history from the model file alone. Trade-off: refitting the model rewrites the simulated history, which is acceptable for synthetic data and is why the model file is committed.

## 017: Synthetic data is labelled everywhere and fenced out of the findings

**Decision:** Simulated rows have `sim-` IDs, their own raw tables (`raw.sim_*`) and staging models (`stg_simulated__*`), and `data_source = 'simulated'`, `is_synthetic = true` and `sim_as_of` on every row. They join the real data only in the `int_*_unioned` models. `is_in_kpi_window`, which every finding and headline KPI uses, is only ever true for real Olist orders.
**How it is enforced:** dbt tests fail if a synthetic row is in the KPI window, if a simulated ID does not start with `sim-`, if a simulated event lies after its snapshot time, or if events are out of order. The independent verification still matches 10 of 10 numbers, and the findings file is unchanged.

## 018: Daily schedule: Windows Task Scheduler now (Option A), GitHub Actions + BigQuery later (Option B)

**Decision (Option A):** A Windows scheduled task runs `scripts/run_daily.ps1` at 07:00 under the owner's account: today's API data, the simulator, DuckDB build and tests, the independent verification, the Parquet export, then BigQuery. If the laptop is off at 07:00, it runs at the next opportunity. It uses the Google login already saved on the laptop, so no credentials are stored in the project.
**Sandbox expiry:** sandbox tables expire 60 days after they are *created*, so the loader drops and re-creates every raw table, and dbt runs with `--full-refresh` to re-create the seeds. The daily run therefore keeps everything fresh.
**Option B (planned, not built):** see `docs/OPTION_B_PLAN.md`.
