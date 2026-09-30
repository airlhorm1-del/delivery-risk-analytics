-- One row per order: typed timestamps and clearer names. No rows are removed here.
with source as (
    select * from {{ source('olist', 'olist_orders') }}
),

renamed as (
    select
        order_id,
        customer_id,
        order_status,
        cast(order_purchase_timestamp as {{ dbt.type_timestamp() }}) as purchased_at,
        cast(nullif(order_approved_at, '') as {{ dbt.type_timestamp() }}) as approved_at,
        -- Olist calls this "delivered to carrier": when the seller hands the parcel to the logistics partner.
        cast(nullif(order_delivered_carrier_date, '') as {{ dbt.type_timestamp() }}) as shipped_at,
        cast(nullif(order_delivered_customer_date, '') as {{ dbt.type_timestamp() }}) as delivered_at,
        -- The promised date is always midnight in the source, so it is a date, not a time.
        cast(cast(order_estimated_delivery_date as {{ dbt.type_timestamp() }}) as date) as promised_date,
        -- Which feed the row came from (see int_orders_unioned).
        'olist' as data_source,
        false as is_synthetic,
        cast(null as {{ dbt.type_timestamp() }}) as sim_as_of
    from source
)

select * from renamed
