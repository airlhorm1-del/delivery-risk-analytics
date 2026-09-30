-- SYNTHETIC DATA: simulated live order payments written by simulator/run.py in the Olist file format.
-- Same typing rules as stg_olist__order_payments; every row carries data_source = 'simulated'.
with source as (
    select * from {{ source('simulated', 'sim_order_payments') }}
),

renamed as (
    select
        order_id,
        cast(payment_sequential as {{ dbt.type_int() }}) as payment_sequence,
        -- boleto = Brazilian bank payment slip, paid at a bank or online and confirmed a day or more later.
        payment_type,
        cast(payment_installments as {{ dbt.type_int() }}) as installments,
        cast(payment_value as {{ dbt.type_numeric() }}) as payment_brl,
        data_source,
        cast(is_synthetic as boolean) as is_synthetic,
        -- The moment the simulated snapshot shows: nothing after it has happened yet.
        cast(sim_as_of as {{ dbt.type_timestamp() }}) as sim_as_of
    from source
)

select * from renamed
