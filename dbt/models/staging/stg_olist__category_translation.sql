-- Portuguese to English category names, plus the two categories missing from Olist's own list.
with source as (
    select product_category_name, product_category_name_english
    from {{ source('olist', 'olist_category_translation') }}
),

additions as (
    select product_category_name, product_category_name_english
    from {{ ref('category_translation_additions') }}
),

combined as (
    select * from source
    union all
    select * from additions
)

select
    product_category_name as category_name_pt,
    product_category_name_english as category_name_en
from combined
