-- SYNTHETIC DATA. The simulated live shop, one row per purchase day: how many orders came in and what
-- has happened to them by the latest run. Recent days naturally show many orders still in transit.
with orders as (
    select * from {{ ref('fct_orders') }}
    where is_synthetic
),

daily as (
    select
        purchase_date,
        count(*) as orders,
        sum(case when is_delivered then 1 else 0 end) as delivered_orders,
        sum(case when is_late then 1 else 0 end) as late_orders,
        sum(case when delivery_outcome = 'Open, not yet due' then 1 else 0 end) as open_orders,
        sum(case when delivery_outcome = 'Overdue, not delivered' then 1 else 0 end) as overdue_orders,
        sum(case when delivery_outcome = 'Cancelled' then 1 else 0 end) as cancelled_orders,
        sum(gmv_eur) as gmv_eur,
        sum(revenue_at_risk_eur) as revenue_at_risk_eur,
        avg(review_score) as avg_review_score,
        max(sim_as_of) as sim_as_of
    from orders
    group by purchase_date
)

select
    *,
    late_orders * 1.0 / nullif(delivered_orders, 0) as late_rate_so_far,
    sum(orders) over (order by purchase_date rows between 6 preceding and current row) as orders_last_7_days,
    sum(late_orders) over (order by purchase_date rows between 29 preceding and current row) * 1.0
        / nullif(sum(delivered_orders) over (order by purchase_date rows between 29 preceding and current row), 0)
        as late_rate_last_30_days
from daily
