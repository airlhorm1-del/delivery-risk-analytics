"""Create simulated orders and decide each order's whole journey when it is placed.

The key idea: the simulated shop is a pure function of (model, day, the day's random seed). Every
run re-creates every day since the start, gets exactly the same orders, and then shows only what has
happened by "now". So nothing needs to be stored between runs, missed days fill themselves in, and
running twice gives identical results.

For each order, at the moment it is placed, the engine decides:
  basket   -> a real Olist order as template (location, items, sellers, payment), prices in today's reais
  payment  -> when it clears (boleto: counted in bank business days on the real 2026 bank calendar)
  journey  -> the template's own promise, seller deadline, hand-over and transit times, measured from
              the new purchase and approval moments (carriers are slower in the Christmas season)
  outcome  -> delivered, or (rarely) cancelled, unavailable, stuck before shipping, lost in transit
  review   -> whether, when and how many stars, depending on how late the order was
Late is never drawn directly: an order is late when its simulated journey takes longer than its promise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np

from ingestion.config import RAW_DATA_DIR
from simulator.bank_calendar import add_bank_days, black_friday
from simulator.distributions import PERCENTILE_GRID, sample
from simulator.templates import Templates


class Categorical:
    """A learned set of shares (e.g. hour of day -> share of orders), ready for fast random picks."""

    def __init__(self, shares: dict[str, float] | list[float]):
        if isinstance(shares, list):
            shares = {str(index): value for index, value in enumerate(shares)}
        self.keys = list(shares)
        weights = np.array([shares[key] for key in self.keys], dtype=float)
        self.cumulative = np.cumsum(weights / weights.sum())

    def pick(self, rng: np.random.Generator) -> str:
        return self.at(rng.random())

    def at(self, u: float) -> str:
        """The category at position u (0-1) of the cumulative shares."""
        return self.keys[min(int(np.searchsorted(self.cumulative, u, side="right")), len(self.keys) - 1)]


@dataclass
class PlannedOrder:
    order_id: str
    customer_id: str
    customer_unique_id: str
    customer_zip_prefix: str
    customer_city: str
    customer_state: str
    route: str
    template_id: int
    main_payment_type: str
    outcome: str
    purchased_at: datetime
    promised_date: date
    approved_at: datetime | None
    shipping_limit_at: datetime
    shipped_at: datetime | None
    delivered_at: datetime | None
    canceled_at: datetime | None
    unavailable_at: datetime | None
    items: list[tuple]  # (item_number, product_id, seller_id, price, freight)
    payments: list[tuple]  # (sequence, payment_type, installments, value)
    review: dict | None  # review_id, score, sent_date, answered_at


def load_price_index(raw_dir=RAW_DATA_DIR) -> dict[str, float]:
    """Brazil's price level by month (IPCA, Jan 2016 = 1.0), from the Banco Central do Brasil extract."""
    index, level = {}, 1.0
    for line in (raw_dir / "ipca" / "ipca_BR.ndjson").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        level *= 1 + record["pct_change"] / 100
        index[record["month"]] = level
    return index


def month_key(day: date, months_back: int = 0) -> str:
    total = day.year * 12 + day.month - 1 - months_back
    return f"{total // 12}-{total % 12 + 1:02d}"


def price_factor(order_day: date, template_month: str, price_index: dict[str, float]) -> float:
    """How much prices rose between the template's month and the order's month.

    Uses inflation up to two months before the order: IPCA is published about ten days after a month
    ends, so that is what a shop would know. Fixed per month, so re-running never changes old prices.
    """
    reference = month_key(order_day, months_back=2)
    available = [month for month in price_index if month <= reference]
    return price_index[available[-1]] / price_index[template_month]


class Engine:
    def __init__(self, model: dict, templates: Templates, bank_holidays: set[date], price_index: dict[str, float]):
        if model["percentile_grid"] != PERCENTILE_GRID:
            raise ValueError("Model was fitted with a different percentile grid; refit with simulator/fit.py")
        self.model = model
        self.templates = templates.orders.to_dict("records")
        self.template_items = templates.items
        self.template_payments = templates.payments
        self.bank_holidays = bank_holidays
        self.price_index = price_index

        approval = model["approval"]
        reviews = model["reviews"]
        self.hour = Categorical(model["purchase_hour_share"])
        self.outcome = Categorical(model["outcome_share"])
        self.boleto_lag = Categorical(approval["boleto"]["bank_day_lag_share"])
        self.boleto_hour = Categorical(approval["boleto"]["approval_hour_share"])
        self.score = {bucket: Categorical(shares) for bucket, shares in reviews["score_share_by_bucket"].items()}
        self.on_time_sent = Categorical(reviews["on_time_sent_after_delivery_days_share"])

    # ---------- volume ----------
    def expected_orders(self, day: date) -> float:
        volume = self.model["volume"]
        expected = volume["weekday_mean_orders"][str(day.isoweekday())] * volume["month_factor"][str(day.month)]
        days_after_black_friday = (day - black_friday(day.year)).days
        return expected * volume["black_friday_factor"].get(str(days_after_black_friday), 1.0)

    def rng_for(self, day: date) -> np.random.Generator:
        # One fixed seed per calendar day: the same day always produces the same orders.
        return np.random.default_rng([self.model["seed"], day.toordinal()])

    def plan_day(self, day: date) -> list[PlannedOrder]:
        rng = self.rng_for(day)
        count = int(rng.poisson(self.expected_orders(day)))
        seconds = sorted(int(self.hour.pick(rng)) * 3600 + int(rng.integers(0, 3600)) for _ in range(count))
        return [
            self.plan_order(
                f"{day:%Y%m%d}-{sequence:05d}", datetime.combine(day, time()) + timedelta(seconds=offset), rng
            )
            for sequence, offset in enumerate(seconds, start=1)
        ]

    # ---------- one order ----------
    def approval_time(self, purchased_at: datetime, payment_type: str, rng: np.random.Generator) -> datetime:
        approval = self.model["approval"]
        if payment_type == "boleto":
            lag = int(self.boleto_lag.pick(rng))
            if lag == 0:
                return purchased_at + timedelta(minutes=sample(approval["boleto"]["same_day_minutes"], rng))
            clearing_day = add_bank_days(purchased_at.date(), lag, self.bank_holidays)
            return datetime.combine(clearing_day, time(int(self.boleto_hour.pick(rng)))) + timedelta(
                seconds=int(rng.integers(0, 3600))
            )
        minutes = approval["other_minutes"].get(payment_type, approval["other_minutes"]["credit_card"])
        return purchased_at + timedelta(minutes=sample(minutes, rng))

    def is_peak_season(self, day: date) -> bool:
        start, end = self.model["peak_season"]["window"]
        return start <= day.strftime("%m-%d") <= end

    def plan_order(self, suffix: str, purchased_at: datetime, rng: np.random.Generator) -> PlannedOrder:
        template = self.templates[int(rng.integers(len(self.templates)))]
        template_id = int(template["template_id"])
        factor = price_factor(purchased_at.date(), template["purchase_month"], self.price_index)

        items = [
            (number, product_id, seller_id, round(price * factor, 2), round(freight * factor, 2))
            for number, (product_id, seller_id, price, freight) in enumerate(self.template_items[template_id], start=1)
        ]
        payments = self.scaled_payments(
            self.template_payments[template_id], sum(price + freight for *_, price, freight in items)
        )
        main_payment_type = max(payments, key=lambda payment: payment[3])[1]

        outcome = self.outcome.pick(rng)
        # The payment clears on today's calendar; the rest of the journey keeps the real order's shape.
        approved_at = self.approval_time(purchased_at, main_payment_type, rng)
        shipping_limit_at = approved_at + timedelta(days=template["deadline_days"])
        promised_days = int(template["promised_days"])
        shipped_at = approved_at + timedelta(days=template["handover_days"])
        transit_days = template["transit_days"]
        if self.is_peak_season(shipped_at.date()):
            transit_days *= self.model["peak_season"]["transit_factor"]
        delivered_at = shipped_at + timedelta(days=transit_days)
        cancel_after_hours, unavailable_after_days = rng.uniform(2, 96), rng.uniform(1, 4)

        canceled_at = unavailable_at = None
        if outcome == "canceled":
            canceled_at = purchased_at + timedelta(hours=cancel_after_hours)
            shipped_at = delivered_at = None
            if approved_at >= canceled_at:
                approved_at = None
        elif outcome == "unavailable":
            unavailable_at = approved_at + timedelta(days=unavailable_after_days)
            shipped_at = delivered_at = None
        elif outcome == "stuck_before_shipping":
            shipped_at = delivered_at = None
        elif outcome == "lost_in_transit":
            delivered_at = None

        promised_date = purchased_at.date() + timedelta(days=promised_days)
        return PlannedOrder(
            order_id=f"sim-{suffix}",
            customer_id=f"sim-cust-{suffix}",
            customer_unique_id=f"sim-person-{suffix}",
            customer_zip_prefix=str(template["customer_zip_code_prefix"]),
            customer_city=template["customer_city"],
            customer_state=template["customer_state"],
            route=template["route"],
            template_id=template_id,
            main_payment_type=main_payment_type,
            outcome=outcome,
            purchased_at=purchased_at,
            promised_date=promised_date,
            approved_at=approved_at,
            shipping_limit_at=shipping_limit_at,
            shipped_at=shipped_at,
            delivered_at=delivered_at,
            canceled_at=canceled_at,
            unavailable_at=unavailable_at,
            items=items,
            payments=payments,
            review=self.plan_review(suffix, outcome, purchased_at, promised_date, delivered_at, rng),
        )

    @staticmethod
    def scaled_payments(template_payments: list[tuple], new_total: float) -> list[tuple]:
        """Keep the template's payment split but make the payments add up to the new total, to the cent."""
        template_total = sum(value for *_, value in template_payments) or 1.0
        payments = [
            [sequence, payment_type, installments, round(value * new_total / template_total, 2)]
            for sequence, (payment_type, installments, value) in enumerate(template_payments, start=1)
        ]
        largest = max(payments, key=lambda payment: payment[3])
        largest[3] = round(largest[3] + new_total - sum(payment[3] for payment in payments), 2)
        return [tuple(payment) for payment in payments]

    def plan_review(self, suffix, outcome, purchased_at, promised_date, delivered_at, rng) -> dict | None:
        reviews = self.model["reviews"]
        # Always exactly five draws, whatever the branch, so a change here never shifts later orders of the day.
        skip, score_draw, sent_draw, on_time_draw, answer_draw = rng.random(5)
        if skip < reviews["no_review_share"]:
            return None
        if outcome == "delivered":
            days_late = (delivered_at.date() - promised_date).days
            bucket = (
                "on_time" if days_late <= 0 else "late_1_2_days" if days_late <= 2 else "late_3_7_days" if days_late <= 7
                else "late_8_14_days" if days_late <= 14 else "late_over_14_days"
            )  # fmt: skip
        else:
            bucket = "never_delivered" if outcome in ("lost_in_transit", "stuck_before_shipping") else "cancelled"

        score = int(self.score[bucket].at(score_draw))
        if bucket == "on_time":
            sent_date = delivered_at.date() + timedelta(days=int(self.on_time_sent.at(on_time_draw)))
        elif outcome == "delivered":
            sent_after_promise = round(
                float(np.interp(sent_draw * 100, PERCENTILE_GRID, reviews["sent_after_promise_days"]["late"]))
            )
            sent_date = min(promised_date + timedelta(days=sent_after_promise), delivered_at.date() + timedelta(days=1))
        else:
            points = reviews["sent_after_promise_days"][bucket]
            sent_date = promised_date + timedelta(
                days=round(float(np.interp(sent_draw * 100, PERCENTILE_GRID, points)))
            )
        sent_date = max(sent_date, purchased_at.date() + timedelta(days=1))
        answer_hours = float(np.interp(answer_draw * 100, PERCENTILE_GRID, reviews["answer_hours"]))
        return {
            "review_id": f"sim-rev-{suffix}",
            "score": score,
            "sent_date": sent_date,
            "answered_at": datetime.combine(sent_date, time()) + timedelta(hours=answer_hours),
        }
