-- Brazil's 27 states (26 states plus the Federal District), for slicing by customer location.
select
    state_code,
    state_name,
    region,
    capital,
    capital_latitude,
    capital_longitude
from {{ ref('brazil_states') }}
