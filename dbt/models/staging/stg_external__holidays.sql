-- One row per holiday. `state_iso_codes` lists the states a regional holiday applies to (e.g. BR-SP)
-- and is empty for nationwide holidays. `types` says whether banks and/or everyone stop work.
with source as (
    select * from {{ source('external', 'holidays') }}
)

select
    cast(h.date as date) as holiday_date,
    h.name as holiday_name,
    h.localName as holiday_name_local,
    h.global as is_nationwide,
    h.counties as state_iso_codes,
    {{ array_contains('h.types', "'Public'") }} as is_public_holiday,
    {{ array_contains('h.types', "'Bank'") }} as is_bank_holiday
from source as h
