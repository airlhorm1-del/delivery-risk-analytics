-- One row per route (seller state -> customer state): reliability, speed, money at risk, and a
-- Pareto ranking of where the revenue at risk is concentrated.
with orders as (
    select * from {{ ref('fct_orders') }}
    where is_in_kpi_window and seller_state is not null
),

routes as (
    select
        route,
        seller_state,
        customer_state,
        count(*) as orders,
        sum(case when is_delivered then 1 else 0 end) as delivered_orders,
        sum(case when is_late then 1 else 0 end) as late_orders,
        avg(distance_km) as avg_distance_km,
        avg(case when is_delivered then promised_days end) as avg_promised_days,
        avg(actual_days) as avg_actual_days,
        {{ percentile('actual_days', 0.9) }} as p90_actual_days,
        sum(gmv_eur) as gmv_eur,
        sum(late_gmv_eur) as late_gmv_eur,
        sum(revenue_at_risk_eur) as revenue_at_risk_eur
    from orders
    group by route, seller_state, customer_state
),

scored as (
    select
        *,
        late_orders * 1.0 / nullif(delivered_orders, 0) as late_rate,
        avg_promised_days - avg_actual_days as avg_buffer_days,
        delivered_orders >= {{ var('min_orders_for_ranking') }} as is_rankable
    from routes
)

select
    *,
    case when is_rankable then
        rank() over (partition by is_rankable order by revenue_at_risk_eur desc)
    end as revenue_at_risk_rank,
    case when is_rankable then
        rank() over (partition by is_rankable order by late_orders * 1.0 / nullif(delivered_orders, 0) desc)
    end as late_rate_rank,
    revenue_at_risk_eur / nullif(sum(revenue_at_risk_eur) over (), 0) as share_of_revenue_at_risk,
    sum(revenue_at_risk_eur) over (
        order by revenue_at_risk_eur desc, route
        rows between unbounded preceding and current row
    ) / nullif(sum(revenue_at_risk_eur) over (), 0) as cumulative_share_of_revenue_at_risk
from scored
