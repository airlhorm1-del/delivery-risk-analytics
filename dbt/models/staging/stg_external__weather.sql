-- One row per state capital per day.
with source as (
    select * from {{ source('external', 'weather_daily') }}
)

select
    w.state_code,
    cast(w.time as date) as weather_date,
    cast(w.precipitation_sum as {{ type_double() }}) as precipitation_mm,
    cast(w.temperature_2m_max as {{ type_double() }}) as temperature_max_c,
    cast(w.temperature_2m_min as {{ type_double() }}) as temperature_min_c
from source as w
