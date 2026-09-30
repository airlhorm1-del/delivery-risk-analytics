-- One row per item in an order. Money stays in Brazilian reais (BRL) here; euros are added in the marts.
with source as (
    select * from {{ source('olist', 'olist_order_items') }}
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
        cast(freight_value as {{ dbt.type_numeric() }}) as freight_brl
    from source
)

select * from renamed
