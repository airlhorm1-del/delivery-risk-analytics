-- One row per seller: volume, reliability, hand-over discipline and revenue at risk, ranked against
-- the platform. A seller joins the watchlist when its late rate is at least twice the platform's.
with items as (
    select * from {{ ref('fct_order_items') }}
    where is_in_kpi_window
),

seller_orders as (
    -- One row per seller per order: a seller shares an order's delivery result only once.
    select
        seller_id,
        seller_state,
        order_id,
        max(case when is_delivered then 1 else 0 end) as is_delivered,
        max(case when is_late then 1 else 0 end) as is_late,
        max(case when seller_missed_ship_by then 1 else 0 end) as missed_ship_by,
        max(case when seller_missed_ship_by is not null then 1 else 0 end) as has_ship_by_result,
        max(review_score) as review_score,
        sum(item_gmv_eur) as gmv_eur,
        sum(late_gmv_eur) as late_gmv_eur,
        sum(revenue_at_risk_eur) as revenue_at_risk_eur
    from items
    group by seller_id, seller_state, order_id
),

sellers as (
    select
        seller_id,
        seller_state,
        count(*) as orders,
        sum(is_delivered) as delivered_orders,
        sum(is_late) as late_orders,
        sum(missed_ship_by) * 1.0 / nullif(sum(has_ship_by_result), 0) as missed_ship_by_rate,
        avg(review_score) as avg_review_score,
        sum(gmv_eur) as gmv_eur,
        sum(late_gmv_eur) as late_gmv_eur,
        sum(revenue_at_risk_eur) as revenue_at_risk_eur
    from seller_orders
    group by seller_id, seller_state
),

scored as (
    select
        *,
        late_orders * 1.0 / nullif(delivered_orders, 0) as late_rate,
        sum(late_orders) over () * 1.0 / sum(delivered_orders) over () as platform_late_rate,
        delivered_orders >= {{ var('min_orders_for_ranking') }} as is_rankable
    from sellers
)

select
    *,
    case when is_rankable then
        rank() over (partition by is_rankable order by revenue_at_risk_eur desc)
    end as revenue_at_risk_rank,
    case when is_rankable then
        percent_rank() over (partition by is_rankable order by late_rate)
    end as late_rate_percentile,
    is_rankable and late_rate >= 2 * platform_late_rate as is_on_watchlist
from scored
