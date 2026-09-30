-- Outside conditions around each order, measured over FIXED-length windows:
--   holidays: weekday public or bank holidays in the customer's state in the 10 days from purchase
--   rain:     heavy-rain days at the customer's state capital in the 7 days from hand-over to the carrier
--
-- Why fixed windows: a first version counted holidays and rain up to the promised date. Orders with
-- longer promises then collected more holidays and rainy days AND were rarely late (they had more
-- time), which made rain and holidays look like they prevented late deliveries. With the same window
-- length for every order, the comparison is fair. (10 and 7 days are the median purchase-to-delivery
-- time and the median carrier transit time.)
with orders as (
    select
        timeline.order_id,
        timeline.purchase_date,
        timeline.shipped_date,
        customers.customer_state
    from {{ ref('int_order_timeline') }} as timeline
    inner join {{ ref('int_customers_unioned') }} as customers
        on customers.customer_id = timeline.customer_id
),

holiday_exposure as (
    select
        orders.order_id,
        count(holidays.holiday_date) as weekday_holidays_first_10_days
    from orders
    left join {{ ref('int_state_holidays') }} as holidays
        on holidays.state_code = orders.customer_state
        and holidays.holiday_date between orders.purchase_date
            and cast({{ dbt.dateadd('day', 9, 'orders.purchase_date') }} as date)
        and holidays.is_weekday
    group by orders.order_id
),

rain_exposure as (
    select
        orders.order_id,
        sum(case when weather.precipitation_mm >= {{ var('heavy_rain_mm') }} then 1 else 0 end) as heavy_rain_days_first_7_days_transit,
        sum(weather.precipitation_mm) as rain_mm_first_7_days_transit
    from orders
    left join {{ ref('stg_external__weather') }} as weather
        on weather.state_code = orders.customer_state
        and weather.weather_date between orders.shipped_date
            and cast({{ dbt.dateadd('day', 6, 'orders.shipped_date') }} as date)
    group by orders.order_id
)

select
    orders.order_id,
    holiday_exposure.weekday_holidays_first_10_days,
    -- Unknown (null) when the order never reached the carrier.
    case when orders.shipped_date is not null then rain_exposure.heavy_rain_days_first_7_days_transit end
        as heavy_rain_days_first_7_days_transit,
    case when orders.shipped_date is not null then rain_exposure.rain_mm_first_7_days_transit end
        as rain_mm_first_7_days_transit
from orders
inner join holiday_exposure on holiday_exposure.order_id = orders.order_id
inner join rain_exposure on rain_exposure.order_id = orders.order_id
