-- One row per payment method used on an order.
with source as (
    select * from {{ source('olist', 'olist_order_payments') }}
),

renamed as (
    select
        order_id,
        cast(payment_sequential as {{ dbt.type_int() }}) as payment_sequence,
        -- boleto = Brazilian bank payment slip, paid at a bank or online and confirmed a day or more later.
        payment_type,
        cast(payment_installments as {{ dbt.type_int() }}) as installments,
        cast(payment_value as {{ dbt.type_numeric() }}) as payment_brl
    from source
)

select * from renamed
