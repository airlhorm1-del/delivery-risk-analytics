with source as (
    select * from {{ source('olist', 'olist_sellers') }}
),

renamed as (
    select
        seller_id,
        seller_zip_code_prefix as seller_zip_prefix,
        seller_city,
        upper(seller_state) as seller_state
    from source
)

select * from renamed
