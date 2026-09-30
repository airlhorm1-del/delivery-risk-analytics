"""Real Olist orders used as templates for simulated ones.

Each simulated order copies one real delivered order: its *basket* (customer location, items, sellers,
prices, freight, how it was paid) and the *shape of its journey* (days promised, the seller's deadline,
how long the seller and the carrier took). Copying them together keeps the links between them: a bulky
order to a remote town gets a long promise AND a long journey. A first version drew each timing
separately; that broke those links and doubled the late rate (9.3% instead of 4.2%), which the
validation caught. Dates, IDs, prices in today's money, payment clearing on today's bank calendar and
the outcome are new for every simulated order.

Templates come from delivered orders in the "normal" months of the KPI window (without Nov-Dec 2017
and Feb-Mar 2018, see fit.py) with timestamps in a possible order.

Built straight from the raw Olist files (no dbt needed), so the simulator can run before the warehouse
exists. Cached in data/sim/ and rebuilt when missing.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from ingestion.config import RAW_DATA_DIR, SIM_DIR

TEMPLATE_WINDOW = ("2017-01-01", "2018-08-31")  # the complete months, as for the KPIs
# Months left out: Black Friday/Christmas 2017 (the peak is replayed separately by a peak factor) and
# Feb-Mar 2018 (a one-off spike whose cause is not in the data, so it is not assumed to repeat).
EXCLUDED_MONTHS = ("2017-11", "2017-12", "2018-02", "2018-03")
CACHE = {name: SIM_DIR / f"templates_{name}.parquet" for name in ("orders", "items", "payments")}


@dataclass
class Templates:
    orders: pd.DataFrame  # one row per template: location, route, original month, journey in days
    items: dict[int, list[tuple]]  # template_id -> [(product_id, seller_id, price, freight), ...]
    payments: dict[int, list[tuple]]  # template_id -> [(payment_type, installments, value), ...]


def build(raw_dir=RAW_DATA_DIR) -> dict[str, pd.DataFrame]:
    olist = (raw_dir / "olist").as_posix()
    con = duckdb.connect()
    for table, file in {
        "orders": "olist_orders_dataset.csv",
        "items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "customers": "olist_customers_dataset.csv",
        "sellers": "olist_sellers_dataset.csv",
    }.items():
        con.execute(
            f"create view {table} as select * from read_csv('{olist}/{file}', all_varchar = true, header = true)"
        )

    orders = con.execute(f"""
        with typed as (
            select order_id, customer_id,
                   cast(order_purchase_timestamp as timestamp) as purchased_at,
                   cast(nullif(order_approved_at, '') as timestamp) as approved_at,
                   cast(nullif(order_delivered_carrier_date, '') as timestamp) as shipped_at,
                   cast(nullif(order_delivered_customer_date, '') as timestamp) as delivered_at,
                   cast(cast(order_estimated_delivery_date as timestamp) as date) as promised_date
            from orders
            where order_status = 'delivered'
        ),
        deadlines as (
            select order_id, max(cast(shipping_limit_date as timestamp)) as ship_by_at from items group by 1
        ),
        delivered as (
            select typed.order_id, customer_id,
                   strftime(purchased_at, '%Y-%m') as purchase_month,
                   date_diff('day', cast(purchased_at as date), promised_date) as promised_days,
                   date_diff('second', approved_at, ship_by_at) / 86400.0 as deadline_days,
                   date_diff('second', approved_at, shipped_at) / 86400.0 as handover_days,
                   date_diff('second', shipped_at, delivered_at) / 86400.0 as transit_days
            from typed join deadlines using (order_id)
            where purchased_at between '{TEMPLATE_WINDOW[0]}' and '{TEMPLATE_WINDOW[1]} 23:59:59'
              and strftime(purchased_at, '%Y-%m') not in {EXCLUDED_MONTHS}
              and approved_at >= purchased_at and shipped_at >= approved_at and delivered_at >= shipped_at
              and ship_by_at > approved_at
              and typed.order_id in (select order_id from payments)
        ),
        seller_value as (
            select order_id, seller_id, sum(cast(price as double)) as value from items group by 1, 2
        ),
        primary_seller as (
            select order_id, seller_id
            from (select *, row_number() over (partition by order_id order by value desc, seller_id) as rank from seller_value)
            where rank = 1
        )
        select
            row_number() over (order by delivered.order_id) - 1 as template_id,
            delivered.order_id as source_order_id,
            delivered.purchase_month,
            customers.customer_zip_code_prefix,
            customers.customer_city,
            upper(customers.customer_state) as customer_state,
            primary_seller.seller_id as primary_seller_id,
            upper(sellers.seller_state) as seller_state,
            upper(sellers.seller_state) || ' -> ' || upper(customers.customer_state) as route,
            delivered.promised_days,
            delivered.deadline_days,
            delivered.handover_days,
            delivered.transit_days
        from delivered
        join customers using (customer_id)
        join primary_seller using (order_id)
        join sellers on sellers.seller_id = primary_seller.seller_id
        order by template_id
    """).df()
    con.register("template_orders", orders)
    items = con.execute("""
        select t.template_id, cast(i.order_item_id as integer) as item_number, i.product_id, i.seller_id,
               cast(i.price as double) as price, cast(i.freight_value as double) as freight
        from items i join template_orders t on t.source_order_id = i.order_id
        order by t.template_id, item_number
    """).df()
    payments = con.execute("""
        select t.template_id, cast(p.payment_sequential as integer) as sequence, p.payment_type,
               cast(p.payment_installments as integer) as installments, cast(p.payment_value as double) as value
        from payments p join template_orders t on t.source_order_id = p.order_id
        order by t.template_id, sequence
    """).df()
    return {"orders": orders, "items": items, "payments": payments}


def load(rebuild: bool = False) -> Templates:
    if rebuild or not all(path.exists() for path in CACHE.values()):
        SIM_DIR.mkdir(parents=True, exist_ok=True)
        for name, frame in build().items():
            frame.to_parquet(CACHE[name], index=False)
    orders = pd.read_parquet(CACHE["orders"])
    items: dict[int, list[tuple]] = {}
    for row in pd.read_parquet(CACHE["items"]).itertuples(index=False):
        items.setdefault(int(row.template_id), []).append(
            (row.product_id, row.seller_id, float(row.price), float(row.freight))
        )
    payments: dict[int, list[tuple]] = {}
    for row in pd.read_parquet(CACHE["payments"]).itertuples(index=False):
        payments.setdefault(int(row.template_id), []).append(
            (row.payment_type, int(row.installments), float(row.value))
        )
    return Templates(orders=orders, items=items, payments=payments)
