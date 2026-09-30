-- Headline KPIs per purchase month (complete months only), with a 3-month rolling late rate
-- and month-on-month change.
with orders as (
    select * from {{ ref('fct_orders') }}
    where is_in_kpi_window
),

monthly as (
    select
        cast({{ dbt.date_trunc('month', 'purchase_date') }} as date) as month_start,
        count(*) as orders,
        sum(case when is_delivered then 1 else 0 end) as delivered_orders,
        sum(case when is_late then 1 else 0 end) as late_orders,
        sum(case when delivery_outcome = 'Overdue, not delivered' then 1 else 0 end) as overdue_orders,
        sum(gmv_eur) as gmv_eur,
        sum(late_gmv_eur) as late_gmv_eur,
        sum(revenue_at_risk_eur) as revenue_at_risk_eur,
        avg(case when is_delivered then promised_days end) as avg_promised_days,
        avg(actual_days) as avg_actual_days,
        avg(review_score) as avg_review_score
    from orders
    group by 1
)

select
    month_start,
    orders,
    delivered_orders,
    late_orders,
    overdue_orders,
    late_orders * 1.0 / nullif(delivered_orders, 0) as late_rate,
    1 - late_orders * 1.0 / nullif(delivered_orders, 0) as on_time_rate,
    sum(late_orders) over (order by month_start rows between 2 preceding and current row) * 1.0
        / nullif(sum(delivered_orders) over (order by month_start rows between 2 preceding and current row), 0)
        as late_rate_rolling_3m,
    gmv_eur,
    gmv_eur - lag(gmv_eur) over (order by month_start) as gmv_eur_change_vs_prior_month,
    late_gmv_eur,
    revenue_at_risk_eur,
    revenue_at_risk_eur / nullif(gmv_eur, 0) as revenue_at_risk_share,
    avg_promised_days,
    avg_actual_days,
    avg_promised_days - avg_actual_days as avg_buffer_days,
    avg_review_score
from monthly
