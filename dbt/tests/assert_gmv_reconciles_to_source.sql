-- GMV in the fact table must equal item prices + freight in the raw files, to the cent, for each feed
-- (real Olist orders and simulated live orders). Returns a row (= test fails) if a total differs.
with source_totals as (
    select 'olist' as data_source,
           sum(cast(price as {{ dbt.type_numeric() }}) + cast(freight_value as {{ dbt.type_numeric() }})) as gmv_brl
    from {{ source('olist', 'olist_order_items') }}
    union all
    select 'simulated' as data_source,
           sum(cast(price as {{ dbt.type_numeric() }}) + cast(freight_value as {{ dbt.type_numeric() }})) as gmv_brl
    from {{ source('simulated', 'sim_order_items') }}
),

model_totals as (
    select data_source, sum(gmv_brl) as gmv_brl from {{ ref('fct_orders') }} group by data_source
)

select source_totals.data_source, source_totals.gmv_brl as source_gmv_brl, model_totals.gmv_brl as model_gmv_brl
from source_totals
left join model_totals on model_totals.data_source = source_totals.data_source
where model_totals.gmv_brl is null or abs(source_totals.gmv_brl - model_totals.gmv_brl) > 0.01
