-- One row per state per holiday date: nationwide holidays apply to all 27 states, regional ones
-- only to the states listed. Several holidays on the same day are combined into one row.
with states as (
    select state_code from {{ ref('brazil_states') }}
),

holidays as (
    select * from {{ ref('stg_external__holidays') }}
),

state_holidays as (
    select
        states.state_code,
        holidays.holiday_date,
        holidays.holiday_name,
        holidays.is_public_holiday,
        holidays.is_bank_holiday
    from states
    cross join holidays
    where holidays.is_nationwide
        or {{ array_contains('holidays.state_iso_codes', "concat('BR-', states.state_code)") }}
)

select
    state_code,
    holiday_date,
    {{ dbt.listagg('holiday_name', "' / '", "order by holiday_name") }} as holiday_names,
    max(case when is_public_holiday then 1 else 0 end) = 1 as is_public_holiday,
    max(case when is_bank_holiday then 1 else 0 end) = 1 as is_bank_holiday,
    {{ iso_day_of_week('holiday_date') }} <= 5 as is_weekday
from state_holidays
group by state_code, holiday_date
