-- One point per zip-code prefix: the average of its geolocation points inside Brazil.
-- Accurate to a few km, which is plenty for seller-to-customer distances of hundreds of km.
select
    zip_prefix,
    avg(latitude) as latitude,
    avg(longitude) as longitude,
    count(*) as point_count
from {{ ref('stg_olist__geolocation') }}
where is_inside_brazil
group by zip_prefix
