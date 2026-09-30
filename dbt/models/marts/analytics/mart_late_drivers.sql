-- Which conditions go with late deliveries, and how strongly?
--
-- For each driver, delivered orders are split into "exposed" and "not exposed". A raw comparison can
-- mislead: rain is seasonal, boleto use differs by state, and events such as Black Friday or Carnival
-- change lateness within a month. So the adjusted figures compare exposed and unexposed orders only
-- within the same customer state and the same week, then average those differences weighted by the
-- number of exposed orders (a standardised difference). The week is the purchase week, except for
-- rain, which is measured from hand-over and so is compared within the same shipping week (otherwise
-- fast-shipping sellers would pick up more of the week's rain and bias the result).
--
-- Besides the late rate, the table shows how much longer the delivery actually took and how much
-- longer Olist's promise was. A driver makes orders late when it adds more to the delivery than the
-- promise allows for.
with orders as (
    select
        order_id,
        customer_state,
        cast({{ dbt.dateadd('day', '(1 - ' ~ iso_day_of_week('purchase_date') ~ ')', 'purchase_date') }} as date) as purchase_week,
        cast({{ dbt.dateadd('day', '(1 - ' ~ iso_day_of_week('shipped_date') ~ ')', 'shipped_date') }} as date) as shipped_week,
        case when is_late then 1 else 0 end as late,
        promised_days,
        actual_days,
        shipped_date,
        seller_missed_ship_by,
        main_payment_type,
        weekday_holidays_first_10_days,
        heavy_rain_days_first_7_days_transit,
        seller_state,
        distance_km
    from {{ ref('fct_orders') }}
    where is_delivered and is_in_kpi_window
),

{% set drivers = [
    ('Seller shipped after its deadline', 'seller_missed_ship_by', 'purchase_week'),
    ('Seller in another state', 'seller_state <> customer_state', 'purchase_week'),
    ('Distance over 1,000 km', 'distance_km > 1000', 'purchase_week'),
    ('Heavy rain at destination, first 7 days of transit', 'heavy_rain_days_first_7_days_transit > 0', 'shipped_week'),
    ('Paid by boleto (bank slip)', "main_payment_type = 'boleto'", 'purchase_week'),
    ('Weekday holiday in the first 10 days', 'weekday_holidays_first_10_days > 0', 'purchase_week'),
] %}

exposures as (
    {% for label, condition, comparison_week in drivers %}
    select
        '{{ label }}' as driver,
        customer_state,
        {{ comparison_week }} as comparison_week,
        late,
        promised_days,
        actual_days,
        {{ condition }} as exposed
    from orders
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

strata as (
    select
        driver,
        customer_state,
        comparison_week,
        sum(case when exposed then 1 else 0 end) as exposed_orders,
        sum(case when not exposed then 1 else 0 end) as unexposed_orders,
        avg(case when exposed then late end) as exposed_late_rate,
        avg(case when not exposed then late end) as unexposed_late_rate,
        avg(case when exposed then promised_days end) - avg(case when not exposed then promised_days end) as promised_days_difference,
        avg(case when exposed then actual_days end) - avg(case when not exposed then actual_days end) as actual_days_difference,
        sum(case when exposed then late else 0 end) as exposed_late,
        sum(case when not exposed then late else 0 end) as unexposed_late
    from exposures
    where exposed is not null
    group by driver, customer_state, comparison_week
),

overall as (
    select
        driver,
        sum(exposed_orders) as exposed_orders,
        sum(unexposed_orders) as unexposed_orders,
        sum(exposed_late) * 1.0 / nullif(sum(exposed_orders), 0) as late_rate_exposed,
        sum(unexposed_late) * 1.0 / nullif(sum(unexposed_orders), 0) as late_rate_not_exposed
    from strata
    group by driver
),

adjusted as (
    select
        driver,
        sum(exposed_orders) as exposed_orders_compared,
        sum(exposed_orders * (exposed_late_rate - unexposed_late_rate)) / sum(exposed_orders) as adjusted_late_rate_difference,
        sum(exposed_orders * actual_days_difference) / sum(exposed_orders) as adjusted_actual_days_difference,
        sum(exposed_orders * promised_days_difference) / sum(exposed_orders) as adjusted_promised_days_difference
    from strata
    where exposed_orders > 0 and unexposed_orders > 0
    group by driver
)

select
    overall.driver,
    overall.exposed_orders,
    overall.exposed_orders * 1.0 / (overall.exposed_orders + overall.unexposed_orders) as share_exposed,
    overall.late_rate_exposed,
    overall.late_rate_not_exposed,
    overall.late_rate_exposed - overall.late_rate_not_exposed as raw_late_rate_difference,
    adjusted.adjusted_late_rate_difference,
    adjusted.adjusted_actual_days_difference,
    adjusted.adjusted_promised_days_difference,
    adjusted.exposed_orders_compared,
    adjusted.exposed_orders_compared * 1.0 / overall.exposed_orders as share_of_exposed_compared
from overall
left join adjusted on adjusted.driver = overall.driver
