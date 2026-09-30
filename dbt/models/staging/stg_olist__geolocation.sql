-- About 1 million points: many per zip prefix. A few dozen fall outside Brazil (bad geocoding) and are flagged.
with source as (
    select * from {{ source('olist', 'olist_geolocation') }}
),

typed as (
    select
        geolocation_zip_code_prefix as zip_prefix,
        cast(geolocation_lat as {{ type_double() }}) as latitude,
        cast(geolocation_lng as {{ type_double() }}) as longitude,
        geolocation_city as city,
        upper(geolocation_state) as state_code
    from source
)

select
    *,
    -- Brazil's bounding box: from about 5.3 N to 33.8 S and from 34.7 W to 74.0 W.
    (latitude between -33.8 and 5.3 and longitude between -74.0 and -34.7) as is_inside_brazil
from typed
