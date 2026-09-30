-- One row per order: item totals, the seller's hand-over deadline, and the "primary" seller.
-- 1.3% of orders have several sellers; the primary seller is the one with the highest item value,
-- so every order can be placed on one seller-to-customer route.
with items as (
    select * from {{ ref('stg_olist__order_items') }}
),

per_seller as (
    select
        order_id,
        seller_id,
        sum(price_brl) as seller_products_brl
    from items
    group by order_id, seller_id
),

ranked_sellers as (
    select
        order_id,
        seller_id,
        row_number() over (
            partition by order_id
            order by seller_products_brl desc, seller_id
        ) as seller_rank
    from per_seller
),

order_totals as (
    select
        order_id,
        count(*) as item_count,
        count(distinct seller_id) as seller_count,
        sum(price_brl) as products_brl,
        sum(freight_brl) as freight_brl,
        -- If items carry different deadlines, the seller only counts as late once the last one has passed.
        max(shipping_limit_at) as seller_ship_by_at
    from items
    group by order_id
)

select
    order_totals.order_id,
    order_totals.item_count,
    order_totals.seller_count,
    order_totals.products_brl,
    order_totals.freight_brl,
    order_totals.products_brl + order_totals.freight_brl as gmv_brl,
    order_totals.seller_ship_by_at,
    ranked_sellers.seller_id as primary_seller_id
from order_totals
inner join ranked_sellers
    on ranked_sellers.order_id = order_totals.order_id
    and ranked_sellers.seller_rank = 1
