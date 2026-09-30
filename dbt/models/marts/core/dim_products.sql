with products as (
    select * from {{ ref('stg_olist__products') }}
),

translations as (
    select * from {{ ref('stg_olist__category_translation') }}
)

select
    products.product_id,
    coalesce(products.category_name_pt, 'unknown') as category_name_pt,
    coalesce(translations.category_name_en, 'unknown') as category_name_en,
    products.photo_count,
    products.weight_g,
    products.length_cm * products.height_cm * products.width_cm as volume_cm3,
    case
        when products.weight_g is null then 'Unknown'
        when products.weight_g < 500 then '1: under 0.5 kg'
        when products.weight_g < 2000 then '2: 0.5-2 kg'
        when products.weight_g < 10000 then '3: 2-10 kg'
        else '4: over 10 kg'
    end as weight_band
from products
left join translations on translations.category_name_pt = products.category_name_pt
