# Power BI dashboard: build guide

The dashboard reads the **marts** from the warehouse: a star schema (two fact tables, four dimension
tables) plus five small analysis tables. The fact tables hold the real Olist orders **and** the
simulated live orders (SYNTHETIC DATA, `is_synthetic = true`); every page filters to one or the other. All business logic already lives in SQL, so the DAX below
only adds things up. That means every number on the dashboard can be traced to a tested dbt model.

## 1. Connect to the data

**Option A: BigQuery (the real setup).** Do the BigQuery steps in `docs/WALKTHROUGH.md` ("What you
still need to do") first.

1. Power BI Desktop > **Home > Get data > Google BigQuery** > Sign in with the same Google account.
2. Open your project > dataset **marts** > tick the 10 tables below > **Load** (Import mode).

**Option B: the Parquet files (works without an account).** Every pipeline run (including the daily
07:00 run) writes the same 11 tables to `powerbi/data/`. In Power BI: **Get data > More... > Parquet** and
paste the full file path, once per table.

| Table | Rows | What it is |
|---|---|---|
| fct_orders | 99,441 real + simulated (grows by ~210 a day) | One row per order: route, timings, outcome, money in EUR, review |
| fct_order_items | 112,650 real + simulated | One row per item: for sellers and product categories |
| dim_date | Sep 2016 to today | Calendar with holidays and the EUR/BRL rate |
| dim_states | 27 | Brazilian states and regions |
| dim_sellers | 3,095 | Seller location |
| dim_products | 32,951 | Category (English) and weight band |
| mart_monthly_kpis | 20 | Month-level KPIs (for checking) |
| mart_route_performance | ~400 | One row per route, ranked |
| mart_seller_performance | ~3,000 | One row per seller, with watchlist flag |
| mart_late_drivers | 6 | Late rate with and without each condition |
| mart_live_daily | one row per simulated day | SYNTHETIC DATA: the simulated live shop, day by day |

## 2. Model view: relationships

Drag these (all many-to-one, single direction, from the fact to the dimension):

| From | To |
|---|---|
| fct_orders[purchase_date] | dim_date[date_day] |
| fct_orders[customer_state] | dim_states[state_code] |
| fct_orders[primary_seller_id] | dim_sellers[seller_id] |
| fct_order_items[purchase_date] | dim_date[date_day] |
| fct_order_items[product_id] | dim_products[product_id] |
| fct_order_items[seller_id] | dim_sellers[seller_id] |

Then select dim_date > **Table tools > Mark as date table** > `date_day`. The four mart_ tables stay
unconnected: each is used on its own on the page that needs it.

**View > Themes > Browse for themes** > `powerbi/theme.json`, so the colours match the charts in `docs/images`.

## 3. Measures (Modeling > New measure, on fct_orders)

```DAX
Orders = COUNTROWS ( fct_orders )
Delivered Orders = CALCULATE ( COUNTROWS ( fct_orders ), fct_orders[is_delivered] = TRUE () )
Late Orders = CALCULATE ( COUNTROWS ( fct_orders ), fct_orders[is_late] = TRUE () )
Late Rate % = DIVIDE ( [Late Orders], [Delivered Orders] )
On-time Rate % = 1 - [Late Rate %]
Overdue Orders = CALCULATE ( COUNTROWS ( fct_orders ), fct_orders[delivery_outcome] = "Overdue, not delivered" )

GMV (EUR) = SUM ( fct_orders[gmv_eur] )
Late GMV (EUR) = SUM ( fct_orders[late_gmv_eur] )
Revenue at Risk (EUR) = SUM ( fct_orders[revenue_at_risk_eur] )
Revenue at Risk % = DIVIDE ( [Revenue at Risk (EUR)], [GMV (EUR)] )

Avg Promised Days = CALCULATE ( AVERAGE ( fct_orders[promised_days] ), fct_orders[is_delivered] = TRUE () )
Avg Actual Days = AVERAGE ( fct_orders[actual_days] )
Promise Buffer (days) = [Avg Promised Days] - [Avg Actual Days]

Avg Review = AVERAGE ( fct_orders[review_score] )
Low Review % = DIVIDE ( CALCULATE ( COUNTROWS ( fct_orders ), fct_orders[is_low_review] = TRUE () ), COUNT ( fct_orders[review_score] ) )
Seller-caused Share of Late % = DIVIDE ( CALCULATE ( [Late Orders], fct_orders[late_cause] = "Seller shipped late" ), [Late Orders] )

Late Rate 3M Rolling % =
VAR LastDay = MAX ( dim_date[date_day] )
RETURN CALCULATE ( [Late Rate %], DATESINPERIOD ( dim_date[date_day], LastDay, -3, MONTH ) )

Late Rate vs Prior Month (pts) =
[Late Rate %] - CALCULATE ( [Late Rate %], DATEADD ( dim_date[date_day], -1, MONTH ) )
```

Format: % measures as Percentage (1 decimal); EUR measures as Currency EUR, no decimals.

**Page filters** (Filters pane > Filters on this page): on pages 1-5 set `fct_orders[is_in_kpi_window]`
to **True** (real orders, the 20 complete months). On page 6 set `fct_orders[is_synthetic]` to **True**.
Do not use a report-level filter: it would hide the simulated orders from page 6 or mix them into pages 1-5.

## 4. Pages

**Page 1: Overview** (the one a manager reads)
- Cards: GMV (EUR), Late Rate %, Revenue at Risk (EUR), Revenue at Risk %, Avg Review.
- Line and clustered column chart: x = dim_date[year_month], columns = Delivered Orders, line = Late Rate %.
- Bar chart: Revenue at Risk (EUR) by fct_orders[revenue_at_risk_reason].
- Bar chart: Low Review % by fct_orders[delivery_outcome].
- Slicers: dim_states[region], fct_orders[main_payment_type].

**Page 2: Routes and regions**
- Table from mart_route_performance (filter is_rankable = True), sorted by revenue_at_risk_rank:
  route, delivered_orders, late_rate, avg_promised_days, avg_actual_days, p90_actual_days,
  revenue_at_risk_eur. Conditional formatting (background colour) on late_rate.
- Pareto: line and clustered column chart, x = route (top 20), columns = revenue_at_risk_eur,
  line = cumulative_share_of_revenue_at_risk.
- Scatter: x = avg_distance_km, y = late_rate, size = delivered_orders, details = route.
- Optional map: Filled map with dim_states[state_name] (set its Data category to "State or Province")
  coloured by Late Rate %.

**Page 3: Sellers**
- Table from mart_seller_performance (is_rankable = True): seller_id, seller_state, delivered_orders,
  late_rate, missed_ship_by_rate, avg_review_score, revenue_at_risk_eur, is_on_watchlist.
- Slicer: is_on_watchlist.
- Scatter: x = missed_ship_by_rate, y = late_rate, size = gmv_eur. Sellers top right miss their
  hand-over deadline and arrive late: the call list.

**Page 4: Why orders are late**
- Clustered bar from mart_late_drivers: y = driver, values = raw_late_rate_difference and
  adjusted_late_rate_difference.
- Clustered bar: adjusted_actual_days_difference vs adjusted_promised_days_difference by driver
  (lateness happens where the first is bigger than the second).
- Bar: Late Orders by fct_orders[late_cause].
- Text box: "Compared within the same customer state and week; see docs/results/02_findings.md."

**Page 5 (optional): Promise what-if (slider)**
- Modeling > New parameter > Numeric range: name "Extra Promise Days", -7 to 7, increment 1, default 0.
- Measure:

```DAX
Simulated Late Rate % =
VAR Extra = 'Extra Promise Days'[Extra Promise Days Value]
RETURN
DIVIDE (
    CALCULATE (
        COUNTROWS ( fct_orders ),
        FILTER ( fct_orders, fct_orders[is_delivered] && fct_orders[actual_days] > fct_orders[promised_days] + Extra )
    ),
    [Delivered Orders]
)
```

- Cards: Late Rate % (actual) and Simulated Late Rate %, plus the slider. Add a column chart of
  Simulated Late Rate % by dim_states[region]. Moving the slider shows how many extra promise days
  it would take to bring a region's late rate down, and what shortening promises would cost.

**Page 6: Live (simulated) - SYNTHETIC DATA**
- A text box across the top, in the orange accent colour: "SIMULATED DATA. Generated daily by the
  project's simulator from patterns in the 2017-2018 Olist orders. Not real orders."
- Page filter: `fct_orders[is_synthetic]` = True.
- Cards: Orders, Late Rate %, Revenue at Risk (EUR), and from mart_live_daily the latest `sim_as_of`
  (label it "Data as of, Sao Paulo time").
- Stacked column chart from mart_live_daily: x = purchase_date, values = delivered_orders, open_orders,
  overdue_orders, cancelled_orders. The newest days are mostly "open": those parcels are still travelling.
- Line chart from mart_live_daily: late_rate_last_30_days by purchase_date.
- Table from fct_orders sorted by purchased_at (newest first): order_id, purchased_at, route,
  main_payment_type, order_status, promised_date, delivery_outcome, gmv_eur. Each morning after 07:00,
  **Home > Refresh** shows the new day.

## 5. Check it

With the KPI-window filter on, the Overview cards must match `docs/results/02_findings.md` and
`docs/results/03_verification.md` (they never change, because synthetic orders are fenced out):

| Card | Expected |
|---|---|
| Orders | 99,092 |
| Late Rate % | 6.8% (6,531 of 96,203 delivered) |
| GMV (EUR) | 4,003,947 |
| Revenue at Risk (EUR) | 264,032 |
| Avg Review, late vs on time | 2.27 vs 4.29 |

If a card is off, check the report-level filter first, then the relationship on purchase_date.

## 6. Publish for the portfolio

Save as `powerbi/delivery_risk.pbix`. Take screenshots of each page into `docs/images/dashboard_*.png`
and export **File > Export > PDF** to `powerbi/delivery_risk.pdf`, so people can see the dashboard
without Power BI. (Publishing to the web needs a Power BI work account; screenshots and the PDF are enough.)
