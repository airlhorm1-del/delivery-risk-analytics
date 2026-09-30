-- SYNTHETIC DATA: simulated live order items written by simulator/run.py in the Olist file format.
-- Same typing rules as stg_olist__order_items; every row carries data_source = 'simulated'.
with source as (
    select * from {{ source('simulated', 'sim_order_items') }}
),

renamed as (
    select
        order_id,
        cast(order_item_id as {{ dbt.type_int() }}) as order_item_number,
        product_id,
        seller_id,
        -- The deadline for the seller to hand this item to the carrier.
        cast(shipping_limit_date as {{ dbt.type_timestamp() }}) as shipping_limit_at,
        cast(price as {{ dbt.type_numeric() }}) as price_brl,
        cast(freight_value as {{ dbt.type_numeric() }}) as freight_brl,
        data_source,
        cast(is_synthetic as boolean) as is_synthetic,
        -- The moment the simulated snapshot shows: nothing after it has happened yet.
        cast(sim_as_of as {{ dbt.type_timestamp() }}) as sim_as_of
    from source
)

select * from renamed
