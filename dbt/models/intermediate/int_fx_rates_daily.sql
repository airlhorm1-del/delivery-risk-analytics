-- One EUR/BRL rate for every calendar day. The ECB publishes on working days only, so weekends and
-- holidays carry forward the last published rate (the standard accounting convention).
with calendar as (
    {{ calendar_days(var('calendar_start'), var('calendar_end')) }}
),

days as (
    select date_day as rate_date
    from calendar
),

published as (
    select rate_date, brl_per_eur
    from {{ ref('stg_external__fx_rates') }}
),

joined as (
    select
        days.rate_date,
        published.brl_per_eur as published_brl_per_eur
    from days
    left join published on published.rate_date = days.rate_date
)

select
    rate_date,
    last_value(published_brl_per_eur ignore nulls) over (
        order by rate_date
        rows between unbounded preceding and current row
    ) as brl_per_eur,
    published_brl_per_eur is not null as is_published_rate
from joined
