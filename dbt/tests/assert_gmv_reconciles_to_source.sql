-- GMV in the fact table must equal item prices + freight in the raw source file, to the cent.
-- Returns a row (= test fails) if the two totals differ.
with source_total as (
    select sum(cast(price as {{ dbt.type_numeric() }}) + cast(freight_value as {{ dbt.type_numeric() }})) as gmv_brl
    from {{ source('olist', 'olist_order_items') }}
),

model_total as (
    select sum(gmv_brl) as gmv_brl from {{ ref('fct_orders') }}
)

select source_total.gmv_brl as source_gmv_brl, model_total.gmv_brl as model_gmv_brl
from source_total
cross join model_total
where abs(source_total.gmv_brl - model_total.gmv_brl) > 0.01
