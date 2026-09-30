-- One row per order item, so sellers and product categories get their own share of each order.
-- Delivery results are order-level (Olist records one delivery per order) and are copied onto each item.
with items as (
    select * from {{ ref('int_order_items_unioned') }}
),

orders as (
    select * from {{ ref('fct_orders') }}
),

sellers as (
    select seller_id, seller_state from {{ ref('stg_olist__sellers') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['items.order_id', 'items.order_item_number']) }} as order_item_key,
    items.order_id,
    items.order_item_number,
    orders.data_source,
    orders.is_synthetic,
    items.product_id,
    items.seller_id,
    sellers.seller_state,
    orders.customer_state,
    orders.purchase_date,
    orders.is_in_kpi_window,

    items.shipping_limit_at,
    orders.shipped_at,
    case when orders.shipped_at is not null then orders.shipped_at > items.shipping_limit_at end as seller_missed_ship_by,

    orders.delivery_outcome,
    orders.is_delivered,
    orders.is_late,
    orders.days_late,
    orders.review_score,
    orders.is_low_review,

    items.price_brl,
    items.freight_brl,
    items.price_brl + items.freight_brl as item_gmv_brl,
    orders.brl_per_eur,
    (items.price_brl + items.freight_brl) / orders.brl_per_eur as item_gmv_eur,
    case when orders.delivery_outcome = 'Late' then (items.price_brl + items.freight_brl) / orders.brl_per_eur else 0 end as late_gmv_eur,
    case when orders.revenue_at_risk_reason is not null then (items.price_brl + items.freight_brl) / orders.brl_per_eur else 0 end as revenue_at_risk_eur
from items
inner join orders on orders.order_id = items.order_id
left join sellers on sellers.seller_id = items.seller_id
