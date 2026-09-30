-- ECB reference rate as published: 1 euro buys `brl_per_eur` reais. Working days only.
with source as (
    select * from {{ source('external', 'fx_rates') }}
)

select
    cast(f.date as date) as rate_date,
    cast(f.rate as {{ type_double() }}) as brl_per_eur
from source as f
where f.base = 'EUR' and f.quote = 'BRL'
