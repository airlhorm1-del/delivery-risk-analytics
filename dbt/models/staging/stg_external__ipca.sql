-- Brazil's monthly consumer price inflation (IPCA), one row per month, e.g. 2026-08: -0.32%.
with source as (
    select * from {{ source('external', 'ipca_monthly') }}
)

select
    cast(concat(i.month, '-01') as date) as month_start,
    cast(i.pct_change as {{ type_double() }}) as pct_change
from source as i
