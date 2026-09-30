"""Stage 2: profile the raw data before changing anything. Writes docs/results/01_data_profile.md.

Every number in the file is computed here from the warehouse, so re-running the script after a
data refresh updates the profile.

Run from the project root (after the load step):
    uv run python -m analysis.profile
"""

from __future__ import annotations

from analysis.common import RESULTS_DIR, connect, md_table, query

CHECKS = {
    "Rows per raw table": """
        select table_name as "table", estimated_size as "rows"
        from duckdb_tables() where schema_name = 'raw' order by table_name
    """,
    "Order status": """
        select order_status as status, count(*) as orders,
               count(order_delivered_customer_date) as with_delivery_date
        from raw.olist_orders group by 1 order by 2 desc
    """,
    "Orders per purchase month (months with few orders are left out of KPIs)": """
        select strftime(cast(order_purchase_timestamp as timestamp), '%Y-%m') as month, count(*) as orders
        from raw.olist_orders group by 1 order by 1
    """,
    "Timestamps recorded in an impossible order (delivered orders)": """
        select
            count(*) filter (where shipped_at < purchased_at) as handed_to_carrier_before_purchase,
            count(*) filter (where shipped_at < approved_at) as handed_to_carrier_before_payment_approval,
            count(*) filter (where delivered_at < shipped_at) as delivered_before_hand_over,
            count(*) filter (where order_status = 'delivered' and delivered_at is null) as delivered_without_date
        from staging.stg_olist__orders where order_status = 'delivered'
    """,
    "Promised date vs. comparing timestamps (why lateness is judged on dates)": """
        select
            count(*) filter (where cast(delivered_at as date) > promised_date) as late_by_date,
            count(*) filter (where delivered_at > cast(promised_date as timestamp)) as late_by_timestamp,
            count(*) filter (where cast(delivered_at as date) = promised_date) as delivered_on_promised_day
        from staging.stg_olist__orders where order_status = 'delivered' and delivered_at is not null
    """,
    "Reviews": """
        select count(*) as review_rows,
               count(distinct order_id) as orders_reviewed,
               (select count(*) from (select order_id from staging.stg_olist__order_reviews group by 1 having count(*) > 1)) as orders_with_several_reviews,
               (select count(*) from raw.olist_orders o where not exists
                   (select 1 from raw.olist_order_reviews r where r.order_id = o.order_id)) as orders_without_review
        from staging.stg_olist__order_reviews
    """,
    "Payments by type": """
        select payment_type, count(*) as payments, count(distinct order_id) as orders,
               round(sum(payment_brl), 0) as brl
        from staging.stg_olist__order_payments group by 1 order by 2 desc
    """,
    "Do payments match item prices + freight?": """
        with items as (select order_id, sum(price_brl + freight_brl) as brl from staging.stg_olist__order_items group by 1),
             paid as (select order_id, sum(payment_brl) as brl from staging.stg_olist__order_payments group by 1)
        select count(*) as orders_with_both,
               count(*) filter (where abs(items.brl - paid.brl) <= 0.01) as match_to_the_cent,
               count(*) filter (where paid.brl > items.brl + 0.01) as paid_more,
               count(*) filter (where paid.brl < items.brl - 0.01) as paid_less
        from items join paid using (order_id)
    """,
    "Customers": """
        select count(*) as customer_ids, count(distinct customer_unique_id) as people,
               (select count(*) from (select customer_unique_id from staging.stg_olist__customers
                                      group by 1 having count(*) > 1)) as people_with_several_orders,
               count(*) filter (where customer_zip_prefix like '0%') as zip_prefixes_with_leading_zero
        from staging.stg_olist__customers
    """,
    "When does the seller's deadline start counting? (whole days after payment approval vs. after purchase)": """
        with gaps as (
            select date_diff('second', o.approved_at, i.shipping_limit_at) as after_approval,
                   date_diff('second', o.purchased_at, i.shipping_limit_at) as after_purchase
            from staging.stg_olist__order_items i
            join staging.stg_olist__orders o using (order_id)
            where o.approved_at is not null
        )
        select count(*) as items,
               round(100.0 * count(*) filter (where after_approval % 86400 = 0) / count(*), 1) as pct_exact_days_after_approval,
               round(100.0 * count(*) filter (where after_purchase % 86400 = 0) / count(*), 1) as pct_exact_days_after_purchase,
               mode(after_approval // 86400) filter (where after_approval % 86400 = 0) as most_common_days
        from gaps
    """,
    "Orders with several sellers": """
        select count(*) as orders from
            (select order_id from staging.stg_olist__order_items group by 1 having count(distinct seller_id) > 1)
    """,
    "Products and categories": """
        select count(*) as products,
               count(*) filter (where category_name_pt is null) as without_category,
               (select count(distinct category_name_pt) from staging.stg_olist__products p
                where category_name_pt is not null and category_name_pt not in
                    (select product_category_name from raw.olist_category_translation)) as categories_missing_translation
        from staging.stg_olist__products
    """,
    "Geolocation": """
        select count(*) as points, count(distinct zip_prefix) as zip_prefixes,
               count(*) filter (where not is_inside_brazil) as points_outside_brazil
        from staging.stg_olist__geolocation
    """,
    "External data": """
        select 'holidays' as source, count(*) as records_in_raw, min(holiday_date)::varchar as first, max(holiday_date)::varchar as last
            from staging.stg_external__holidays
        union all
        select 'weather (27 capitals)', count(*), min(weather_date)::varchar, max(weather_date)::varchar from staging.stg_external__weather
        union all
        select 'EUR/BRL rates', count(*), min(rate_date)::varchar, max(rate_date)::varchar from staging.stg_external__fx_rates
    """,
}


def run() -> str:
    con = connect()
    sections = ["# Data profile\n", "Generated by `analysis/profile.py` from the raw and staging layers.\n"]
    for title, sql in CHECKS.items():
        sections.append(f"## {title}\n\n{md_table(query(con, sql))}\n")
    text = "\n".join(sections)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "01_data_profile.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    run()
    print(f"Wrote {RESULTS_DIR / '01_data_profile.md'}")
