-- One review per order. 547 orders were reviewed more than once; the most recent answer wins,
-- because it reflects how the customer felt last.
with reviews as (
    select * from {{ ref('stg_olist__order_reviews') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by order_id
            order by review_answered_at desc, review_sent_date desc, review_id
        ) as review_rank,
        count(*) over (partition by order_id) as reviews_for_order
    from reviews
)

select
    order_id,
    review_id,
    review_score,
    has_comment,
    review_sent_date,
    review_answered_at,
    reviews_for_order
from ranked
where review_rank = 1
