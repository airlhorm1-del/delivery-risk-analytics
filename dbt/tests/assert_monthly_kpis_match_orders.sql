-- The monthly table and the order table must report the same revenue at risk for the KPI window.
with monthly as (
    select sum(revenue_at_risk_eur) as total from {{ ref('mart_monthly_kpis') }}
),

orders as (
    select sum(revenue_at_risk_eur) as total from {{ ref('fct_orders') }} where is_in_kpi_window
)

select monthly.total as monthly_total, orders.total as orders_total
from monthly
cross join orders
where abs(monthly.total - orders.total) > 0.01
