-- customer_id is created per order; customer_unique_id is the actual person.
with source as (
    select * from {{ source('olist', 'olist_customers') }}
),

renamed as (
    select
        customer_id,
        customer_unique_id,
        -- Kept as text: prefixes such as 01001 (Sao Paulo city) would lose their leading zero as numbers.
        customer_zip_code_prefix as customer_zip_prefix,
        customer_city,
        upper(customer_state) as customer_state
    from source
)

select * from renamed
