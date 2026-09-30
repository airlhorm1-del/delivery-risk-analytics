-- One row per order: how it was paid. The main payment type is the method that paid the most.
with payments as (
    select * from {{ ref('stg_olist__order_payments') }}
),

ranked as (
    select
        order_id,
        payment_type,
        row_number() over (
            partition by order_id
            order by payment_brl desc, payment_sequence
        ) as payment_rank
    from payments
),

totals as (
    select
        order_id,
        count(*) as payment_count,
        sum(payment_brl) as paid_brl,
        max(installments) as max_installments,
        max(case when payment_type = 'voucher' then 1 else 0 end) = 1 as used_voucher
    from payments
    group by order_id
)

select
    totals.order_id,
    ranked.payment_type as main_payment_type,
    totals.payment_count,
    totals.paid_brl,
    totals.max_installments,
    totals.used_voucher
from totals
inner join ranked
    on ranked.order_id = totals.order_id
    and ranked.payment_rank = 1
