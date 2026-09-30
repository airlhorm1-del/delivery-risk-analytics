-- SYNTHETIC DATA: simulated live order reviews written by simulator/run.py in the Olist file format.
-- Same typing rules as stg_olist__order_reviews; every row carries data_source = 'simulated'.
with source as (
    select * from {{ source('simulated', 'sim_order_reviews') }}
),

renamed as (
    select
        review_id,
        order_id,
        cast(review_score as {{ dbt.type_int() }}) as review_score,
        coalesce(trim(review_comment_message) <> '', false) as has_comment,
        cast(cast(review_creation_date as {{ dbt.type_timestamp() }}) as date) as review_sent_date,
        cast(review_answer_timestamp as {{ dbt.type_timestamp() }}) as review_answered_at,
        data_source,
        cast(is_synthetic as boolean) as is_synthetic,
        -- The moment the simulated snapshot shows: nothing after it has happened yet.
        cast(sim_as_of as {{ dbt.type_timestamp() }}) as sim_as_of
    from source
)

select * from renamed
