"""Unit tests for the simulated live orders (SYNTHETIC DATA). They use the committed model file and two
hand-made templates, so they run offline in about a second."""

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ingestion.config import SIM_MODEL_PATH
from simulator.bank_calendar import add_bank_days, bank_days_between, black_friday
from simulator.distributions import PERCENTILE_GRID, sample, to_percentiles
from simulator.engine import Engine, price_factor
from simulator.run import plan_until, snapshot, status_at
from simulator.templates import Templates

CHRISTMAS = date(2026, 12, 25)


@pytest.fixture(scope="module")
def engine() -> Engine:
    model = json.loads(SIM_MODEL_PATH.read_text(encoding="utf-8"))
    orders = pd.DataFrame([
        {"template_id": 0, "source_order_id": "a", "purchase_month": "2018-01", "customer_zip_code_prefix": "01001",
         "customer_city": "sao paulo", "customer_state": "SP", "primary_seller_id": "s1", "seller_state": "SP",
         "route": "SP -> SP", "promised_days": 12, "deadline_days": 6.0, "handover_days": 1.5, "transit_days": 4.0},
        {"template_id": 1, "source_order_id": "b", "purchase_month": "2017-06", "customer_zip_code_prefix": "20040",
         "customer_city": "rio de janeiro", "customer_state": "RJ", "primary_seller_id": "s2", "seller_state": "SP",
         "route": "SP -> RJ", "promised_days": 20, "deadline_days": 6.0, "handover_days": 7.0, "transit_days": 16.0},
    ])  # fmt: skip
    templates = Templates(
        orders=orders,
        items={0: [("p1", "s1", 100.0, 10.0)], 1: [("p2", "s2", 50.0, 20.0), ("p3", "s2", 30.0, 20.0)]},
        payments={0: [("boleto", 1, 110.0)], 1: [("credit_card", 3, 100.0), ("voucher", 1, 20.0)]},
    )
    price_index = {"2017-06": 1.0, "2018-01": 1.02, "2026-06": 1.55, "2026-07": 1.56, "2026-08": 1.55}
    return Engine(model, templates, bank_holidays={CHRISTMAS}, price_index=price_index)


def test_same_day_always_gives_the_same_orders(engine):
    first, second = engine.plan_day(date(2026, 9, 1)), engine.plan_day(date(2026, 9, 1))
    assert [o.order_id for o in first] == [o.order_id for o in second]
    assert [(o.purchased_at, o.delivered_at, o.items) for o in first] == [
        (o.purchased_at, o.delivered_at, o.items) for o in second
    ]


def test_order_ids_are_labelled_synthetic_and_chronological(engine):
    orders = engine.plan_day(date(2026, 9, 1))
    assert all(order.order_id.startswith("sim-20260901-") for order in orders)
    assert [order.purchased_at for order in orders] == sorted(order.purchased_at for order in orders)


def test_black_friday_brings_several_times_more_orders(engine):
    assert black_friday(2026) == date(2026, 11, 27)
    assert black_friday(2017) == date(2017, 11, 24)
    assert engine.expected_orders(date(2026, 11, 27)) > 5 * engine.expected_orders(date(2026, 11, 20))


def test_a_later_run_keeps_earlier_orders_and_adds_the_missed_days(engine):
    start = date(2026, 9, 1)
    monday = plan_until(engine, datetime(2026, 9, 2, 2, 0), start=start)
    thursday = plan_until(engine, datetime(2026, 9, 5, 2, 0), start=start)
    earlier = {order.order_id: order.purchased_at for order in monday}
    later = {order.order_id: order.purchased_at for order in thursday}
    assert all(later[order_id] == purchased for order_id, purchased in earlier.items())
    assert {moment.date() for moment in later.values()} == {date(2026, 9, day) for day in range(1, 6)}


def test_snapshot_never_shows_the_future(engine):
    as_of = datetime(2026, 9, 10, 2, 0)
    frames = snapshot(plan_until(engine, as_of, start=date(2026, 8, 20)), as_of)
    orders = frames["orders"]
    for column in [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
    ]:
        revealed = pd.to_datetime(orders[column].replace("", None)).dropna()
        assert (revealed <= as_of).all(), column
    assert (pd.to_datetime(frames["order_reviews"]["review_answer_timestamp"]) <= as_of).all()


def test_every_row_is_labelled_synthetic(engine):
    as_of = datetime(2026, 9, 3, 2, 0)
    for name, frame in snapshot(plan_until(engine, as_of, start=date(2026, 9, 1)), as_of).items():
        if len(frame):
            assert set(frame["data_source"]) == {"simulated"}, name
            assert set(frame["is_synthetic"]) == {"true"}, name
            assert set(frame["sim_as_of"]) == {"2026-09-03 02:00:00"}, name


def test_status_moves_through_the_life_cycle(engine):
    order = next(o for o in engine.plan_day(date(2026, 9, 1)) if o.outcome == "delivered")
    assert status_at(order, order.purchased_at) in ("created", "approved")
    assert status_at(order, order.shipped_at + timedelta(minutes=1)) == "shipped"
    assert status_at(order, order.delivered_at + timedelta(minutes=1)) == "delivered"


def test_boleto_clears_only_on_bank_days():
    friday_christmas_eve = date(2026, 12, 24)  # Thursday 24 Dec; Friday 25 is Christmas, then the weekend
    assert add_bank_days(friday_christmas_eve, 1, {CHRISTMAS}) == date(2026, 12, 28)
    assert add_bank_days(date(2026, 10, 2), 1, set()) == date(2026, 10, 5)  # Friday -> Monday
    assert bank_days_between(date(2026, 10, 2), date(2026, 10, 5), set()) == 1


def test_prices_follow_inflation_known_two_months_earlier(engine):
    # An October 2026 order uses the index of August 2026 (published in September), vs the template's month.
    assert price_factor(date(2026, 10, 15), "2018-01", engine.price_index) == pytest.approx(1.55 / 1.02)


def test_payments_add_up_to_the_new_total_to_the_cent():
    payments = Engine.scaled_payments([("credit_card", 3, 100.0), ("voucher", 1, 20.0)], new_total=187.33)
    assert round(sum(value for *_, value in payments), 2) == 187.33
    assert [payment_type for _, payment_type, _, _ in payments] == ["credit_card", "voucher"]


def test_percentile_sampling_stays_within_the_learned_range():
    points = to_percentiles(np.arange(1, 101))
    assert len(points) == len(PERCENTILE_GRID)
    rng = np.random.default_rng(1)
    draws = [sample(points, rng) for _ in range(1000)]
    assert min(draws) >= 1 and max(draws) <= 100
