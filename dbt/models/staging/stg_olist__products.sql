-- The source misspells "length" as "lenght" in two column names; fixed here.
-- nullif(..., '') because 610 products have blank measurements, which BigQuery may load as empty text.
with source as (
    select * from {{ source('olist', 'olist_products') }}
),

renamed as (
    select
        product_id,
        nullif(product_category_name, '') as category_name_pt,
        cast(nullif(product_photos_qty, '') as {{ dbt.type_int() }}) as photo_count,
        cast(nullif(product_name_lenght, '') as {{ dbt.type_int() }}) as name_length,
        cast(nullif(product_description_lenght, '') as {{ dbt.type_int() }}) as description_length,
        cast(nullif(product_weight_g, '') as {{ type_double() }}) as weight_g,
        cast(nullif(product_length_cm, '') as {{ type_double() }}) as length_cm,
        cast(nullif(product_height_cm, '') as {{ type_double() }}) as height_cm,
        cast(nullif(product_width_cm, '') as {{ type_double() }}) as width_cm
    from source
)

select * from renamed
