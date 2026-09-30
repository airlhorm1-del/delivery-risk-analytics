-- SYNTHETIC DATA: simulated live customers written by simulator/run.py in the Olist file format.
-- Same typing rules as stg_olist__customers; every row carries data_source = 'simulated'.
with source as (
    select * from {{ source('simulated', 'sim_customers') }}
),

renamed as (
    select
        customer_id,
        customer_unique_id,
        -- Kept as text: prefixes such as 01001 (Sao Paulo city) would lose their leading zero as numbers.
        customer_zip_code_prefix as customer_zip_prefix,
        customer_city,
        upper(customer_state) as customer_state,
        data_source,
        cast(is_synthetic as boolean) as is_synthetic,
        -- The moment the simulated snapshot shows: nothing after it has happened yet.
        cast(sim_as_of as {{ dbt.type_timestamp() }}) as sim_as_of
    from source
)

select * from renamed
