with sellers as (
    select * from {{ ref('stg_olist__sellers') }}
)

select
    sellers.seller_id,
    sellers.seller_city,
    sellers.seller_state,
    states.region as seller_region,
    sellers.seller_zip_prefix,
    zips.latitude,
    zips.longitude
from sellers
left join {{ ref('brazil_states') }} as states on states.state_code = sellers.seller_state
left join {{ ref('int_zip_centroids') }} as zips on zips.zip_prefix = sellers.seller_zip_prefix
