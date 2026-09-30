-- One row per review row in the source. Some orders have several reviews; the latest is picked in
-- int_order_reviews_latest. The free-text comments are not needed for this analysis and are left out.
with source as (
    select * from {{ source('olist', 'olist_order_reviews') }}
),

renamed as (
    select
        review_id,
        order_id,
        cast(review_score as {{ dbt.type_int() }}) as review_score,
        coalesce(trim(review_comment_message) <> '', false) as has_comment,
        cast(cast(review_creation_date as {{ dbt.type_timestamp() }}) as date) as review_sent_date,
        cast(review_answer_timestamp as {{ dbt.type_timestamp() }}) as review_answered_at
    from source
)

select * from renamed
