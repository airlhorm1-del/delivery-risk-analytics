-- Seller and product analysis uses item rows; each order's items must add up to the order's EUR value.
with item_totals as (
    select order_id, sum(item_gmv_eur) as item_gmv_eur, sum(revenue_at_risk_eur) as item_revenue_at_risk_eur
    from {{ ref('fct_order_items') }}
    group by order_id
)

select orders.order_id, orders.gmv_eur, item_totals.item_gmv_eur
from {{ ref('fct_orders') }} as orders
inner join item_totals on item_totals.order_id = orders.order_id
where abs(orders.gmv_eur - item_totals.item_gmv_eur) > 0.001
    or abs(orders.revenue_at_risk_eur - item_totals.item_revenue_at_risk_eur) > 0.001
