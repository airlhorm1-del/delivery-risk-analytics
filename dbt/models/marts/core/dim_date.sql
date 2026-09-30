-- One row per calendar day, with nationwide holidays and the day's EUR/BRL rate.
with days as (
    select rate_date as date_day, brl_per_eur, is_published_rate
    from {{ ref('int_fx_rates_daily') }}
),

nationwide_holidays as (
    select
        holiday_date,
        {{ dbt.listagg('holiday_name', "' / '", "order by holiday_name") }} as holiday_names,
        max(case when is_public_holiday then 1 else 0 end) = 1 as is_public_holiday,
        max(case when is_bank_holiday then 1 else 0 end) = 1 as is_bank_holiday
    from {{ ref('stg_external__holidays') }}
    where is_nationwide
    group by holiday_date
),

enriched as (
    select
        days.date_day,
        extract(year from days.date_day) as year_number,
        extract(quarter from days.date_day) as quarter_number,
        extract(month from days.date_day) as month_number,
        cast({{ dbt.date_trunc('month', 'days.date_day') }} as date) as month_start,
        {{ iso_day_of_week('days.date_day') }} as iso_day_of_week,
        coalesce(nationwide_holidays.is_public_holiday, false) as is_public_holiday,
        coalesce(nationwide_holidays.is_bank_holiday, false) as is_bank_holiday,
        nationwide_holidays.holiday_names,
        days.brl_per_eur,
        days.is_published_rate,
        days.date_day between cast('{{ var("kpi_window_start") }}' as date)
            and cast('{{ var("kpi_window_end") }}' as date) as is_in_kpi_window
    from days
    left join nationwide_holidays on nationwide_holidays.holiday_date = days.date_day
)

select
    *,
    concat(cast(year_number as {{ dbt.type_string() }}), '-', lpad(cast(month_number as {{ dbt.type_string() }}), 2, '0')) as year_month,
    case month_number
        when 1 then 'Jan' when 2 then 'Feb' when 3 then 'Mar' when 4 then 'Apr' when 5 then 'May' when 6 then 'Jun'
        when 7 then 'Jul' when 8 then 'Aug' when 9 then 'Sep' when 10 then 'Oct' when 11 then 'Nov' else 'Dec'
    end as month_name,
    case iso_day_of_week
        when 1 then 'Mon' when 2 then 'Tue' when 3 then 'Wed' when 4 then 'Thu' when 5 then 'Fri' when 6 then 'Sat' else 'Sun'
    end as day_name,
    iso_day_of_week >= 6 as is_weekend
from enriched
