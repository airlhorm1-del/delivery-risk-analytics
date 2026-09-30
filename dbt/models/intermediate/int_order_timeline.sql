-- The delivery rules in one place: how long each stage took, whether the promise was kept, and
-- (for late orders) whose stage it was. Unit-tested in _intermediate.yml.
with orders as (
    select * from {{ ref('int_orders_unioned') }}
),

items as (
    select order_id, seller_ship_by_at
    from {{ ref('int_order_items_summary') }}
),

joined as (
    select
        orders.*,
        items.seller_ship_by_at,
        cast(orders.purchased_at as date) as purchase_date,
        cast(orders.shipped_at as date) as shipped_date,
        cast(orders.delivered_at as date) as delivered_date,
        (orders.order_status = 'delivered' and orders.delivered_at is not null) as is_delivered,
        -- Events recorded in an impossible order (1.4% of orders). Kept, but excluded from stage timings.
        coalesce(
            orders.shipped_at < orders.purchased_at
            or orders.shipped_at < orders.approved_at
            or orders.delivered_at < orders.shipped_at,
            false
        ) as has_timestamp_anomaly
    from orders
    left join items on items.order_id = orders.order_id
),

measured as (
    select
        *,
        -- Compared as dates: a parcel arriving at 18:00 on the promised day is on time.
        is_delivered and delivered_date > promised_date as is_late_delivery
    from joined
)

select
    order_id,
    customer_id,
    data_source,
    is_synthetic,
    sim_as_of,
    order_status,
    purchased_at,
    approved_at,
    shipped_at,
    delivered_at,
    purchase_date,
    shipped_date,
    delivered_date,
    promised_date,
    seller_ship_by_at,
    is_delivered,
    has_timestamp_anomaly,

    {{ days_between('purchase_date', 'promised_date') }} as promised_days,
    case when is_delivered then {{ days_between('purchase_date', 'delivered_date') }} end as actual_days,
    case when is_delivered then is_late_delivery end as is_late,
    case when is_late_delivery then {{ days_between('promised_date', 'delivered_date') }} else 0 end as days_late,

    -- Stage timings: payment approval (hours), seller hand-over and carrier transit (days).
    {{ hours_between('purchased_at', 'approved_at') }} as approval_hours,
    case when not has_timestamp_anomaly then {{ hours_between('approved_at', 'shipped_at') }} / 24 end as handover_days,
    case when not has_timestamp_anomaly then {{ hours_between('shipped_at', 'delivered_at') }} / 24 end as transit_days,
    case when shipped_at is not null then shipped_at > seller_ship_by_at end as seller_missed_ship_by,

    case
        when is_late_delivery then 'Late'
        when is_delivered then 'On time'
        when order_status in ('canceled', 'unavailable') then 'Cancelled'
        when order_status = 'delivered' then 'Delivered, date missing'
        -- "Overdue" is judged at the moment the data shows: the Olist export date, or the simulated snapshot time.
        when promised_date < coalesce(cast(sim_as_of as date), cast('{{ var("data_cutoff_date") }}' as date))
            then 'Overdue, not delivered'
        else 'Open, not yet due'
    end as delivery_outcome,

    case
        when not is_late_delivery then null
        when has_timestamp_anomaly or shipped_at is null or seller_ship_by_at is null then 'Unclear (timestamp issue)'
        when shipped_at > seller_ship_by_at then 'Seller shipped late'
        else 'After hand-over (carrier or promise)'
    end as late_cause
from measured
