-- The central fact table: one row per order with its route, timings, outcome, money (BRL and EUR),
-- customer review and outside conditions. Every Olist order is kept (99,441), plus the simulated live
-- orders (SYNTHETIC DATA, is_synthetic = true). Headline numbers use is_in_kpi_window, which is only
-- ever true for real Olist orders.
with timeline as (
    select * from {{ ref('int_order_timeline') }}
),

customers as (
    select * from {{ ref('int_customers_unioned') }}
),

items as (
    select * from {{ ref('int_order_items_summary') }}
),

payments as (
    select * from {{ ref('int_order_payments_summary') }}
),

reviews as (
    select * from {{ ref('int_order_reviews_latest') }}
),

context as (
    select * from {{ ref('int_order_context') }}
),

sellers as (
    select * from {{ ref('stg_olist__sellers') }}
),

zips as (
    select * from {{ ref('int_zip_centroids') }}
),

fx as (
    select * from {{ ref('int_fx_rates_daily') }}
),

states as (
    select * from {{ ref('brazil_states') }}
),

joined as (
    select
        timeline.order_id,
        timeline.data_source,
        timeline.is_synthetic,
        timeline.sim_as_of,
        customers.customer_unique_id,
        customers.customer_city,
        customers.customer_state,
        customer_states.region as customer_region,
        items.primary_seller_id,
        sellers.seller_state,
        seller_states.region as seller_region,
        concat(sellers.seller_state, ' -> ', customers.customer_state) as route,
        {{ haversine_km('seller_zip.latitude', 'seller_zip.longitude', 'customer_zip.latitude', 'customer_zip.longitude') }} as distance_km,

        timeline.order_status,
        timeline.delivery_outcome,
        timeline.late_cause,
        timeline.is_delivered,
        timeline.is_late,
        timeline.days_late,
        timeline.purchased_at,
        timeline.purchase_date,
        timeline.approved_at,
        timeline.shipped_at,
        timeline.delivered_at,
        timeline.shipped_date,
        timeline.delivered_date,
        timeline.promised_date,
        timeline.promised_days,
        timeline.actual_days,
        timeline.approval_hours,
        timeline.handover_days,
        timeline.transit_days,
        timeline.seller_missed_ship_by,
        timeline.has_timestamp_anomaly,

        payments.main_payment_type,
        payments.max_installments,
        payments.used_voucher,

        coalesce(items.item_count, 0) as item_count,
        coalesce(items.seller_count, 0) as seller_count,
        coalesce(items.products_brl, 0) as products_brl,
        coalesce(items.freight_brl, 0) as freight_brl,
        coalesce(items.gmv_brl, 0) as gmv_brl,
        fx.brl_per_eur,
        -- Converted at the ECB rate of the purchase date.
        coalesce(items.gmv_brl, 0) / fx.brl_per_eur as gmv_eur,
        coalesce(items.freight_brl, 0) / fx.brl_per_eur as freight_eur,

        reviews.review_score,
        reviews.review_score <= 2 as is_low_review,
        reviews.review_sent_date,

        context.weekday_holidays_first_10_days,
        context.heavy_rain_days_first_7_days_transit,
        context.rain_mm_first_7_days_transit,

        timeline.data_source = 'olist'
            and timeline.purchase_date between cast('{{ var("kpi_window_start") }}' as date)
            and cast('{{ var("kpi_window_end") }}' as date) as is_in_kpi_window
    from timeline
    inner join customers on customers.customer_id = timeline.customer_id
    left join states as customer_states on customer_states.state_code = customers.customer_state
    left join items on items.order_id = timeline.order_id
    left join sellers on sellers.seller_id = items.primary_seller_id
    left join states as seller_states on seller_states.state_code = sellers.seller_state
    left join zips as customer_zip on customer_zip.zip_prefix = customers.customer_zip_prefix
    left join zips as seller_zip on seller_zip.zip_prefix = sellers.seller_zip_prefix
    left join payments on payments.order_id = timeline.order_id
    left join reviews on reviews.order_id = timeline.order_id
    left join context on context.order_id = timeline.order_id
    left join fx on fx.rate_date = timeline.purchase_date
),

final as (
    select
        *,
        case
            when distance_km is null then 'Unknown'
            when distance_km < 250 then '1: under 250 km'
            when distance_km < 750 then '2: 250-750 km'
            when distance_km < 1500 then '3: 750-1,500 km'
            else '4: over 1,500 km'
        end as distance_band,
        -- Revenue at risk: the promise was broken AND there is evidence of damage.
        case
            when delivery_outcome = 'Late' and is_low_review then 'Late and rated 1-2 stars'
            when delivery_outcome = 'Overdue, not delivered' then 'Overdue, never delivered'
        end as revenue_at_risk_reason
    from joined
)

select
    *,
    case when delivery_outcome = 'Late' then gmv_eur else 0 end as late_gmv_eur,
    case when revenue_at_risk_reason is not null then gmv_eur else 0 end as revenue_at_risk_eur
from final
