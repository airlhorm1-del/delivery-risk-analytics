"""Run the simulated shop up to "now" and write its data in the Olist file format (SYNTHETIC DATA).

Every run:
  1. sets the clock to now in Sao Paulo (the shop is Brazilian; 07:00 in Germany is 02:00 there),
  2. re-creates every day from the start date (2 Jul 2026) up to now. Each day has a fixed random
     seed, so earlier days come out exactly as before, and days missed while the laptop was off are
     simply included,
  3. reveals only what has happened by now: an order bought last night may be approved but not yet
     shipped, one bought three weeks ago may be delivered and reviewed,
  4. writes five CSV files to data/raw/sim/ with Olist's own column names plus three labels on every
     row: data_source = 'simulated', is_synthetic = true, sim_as_of = the moment the snapshot shows,
  5. appends a line to data/sim/run_log.csv: how many new orders, deliveries and reviews since last run.

Run from the project root:
    uv run python -m simulator.run                               # now
    uv run python -m simulator.run --as-of "2026-10-05 02:00"    # the shop as it looked at that moment
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ingestion.config import SIM_DIR, SIM_MODEL_PATH, SIM_RAW_DIR, SIM_START_DATE, SIM_TIMEZONE
from simulator import templates as template_store
from simulator.bank_calendar import load_bank_holidays
from simulator.engine import Engine, PlannedOrder, load_price_index

LABELS = {"data_source": "simulated", "is_synthetic": "true"}
RUN_LOG = SIM_DIR / "run_log.csv"


def now_in_brazil() -> datetime:
    return datetime.now(ZoneInfo(SIM_TIMEZONE)).replace(tzinfo=None, microsecond=0)


def load_engine() -> Engine:
    model = json.loads(SIM_MODEL_PATH.read_text(encoding="utf-8"))
    return Engine(model, template_store.load(), load_bank_holidays(), load_price_index())


def plan_until(engine: Engine, as_of: datetime, start: date = SIM_START_DATE) -> list[PlannedOrder]:
    orders = []
    for offset in range((as_of.date() - start).days + 1):
        orders.extend(order for order in engine.plan_day(start + timedelta(days=offset)) if order.purchased_at <= as_of)
    return orders


def happened(moment: datetime | None, as_of: datetime) -> datetime | None:
    return moment if moment is not None and moment <= as_of else None


def status_at(order: PlannedOrder, as_of: datetime) -> str:
    if happened(order.canceled_at, as_of):
        return "canceled"
    if happened(order.unavailable_at, as_of):
        return "unavailable"
    if happened(order.delivered_at, as_of):
        return "delivered"
    if happened(order.shipped_at, as_of):
        return "shipped"
    if happened(order.approved_at, as_of):
        if as_of < order.approved_at + timedelta(hours=12):
            return "approved"
        return "processing" if order.outcome == "stuck_before_shipping" else "invoiced"
    return "created"


def timestamp(moment: datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S") if moment else ""


def snapshot(orders: list[PlannedOrder], as_of: datetime) -> dict[str, pd.DataFrame]:
    """The shop's data exactly as it would look at `as_of`, in Olist's column layout."""
    labels = {**LABELS, "sim_as_of": timestamp(as_of)}
    rows = {name: [] for name in ("orders", "order_items", "order_payments", "order_reviews", "customers")}
    for order in orders:
        canceled_before_approval = order.approved_at is None
        rows["orders"].append(
            {
                "order_id": order.order_id,
                "customer_id": order.customer_id,
                "order_status": status_at(order, as_of),
                "order_purchase_timestamp": timestamp(order.purchased_at),
                "order_approved_at": "" if canceled_before_approval else timestamp(happened(order.approved_at, as_of)),
                "order_delivered_carrier_date": timestamp(happened(order.shipped_at, as_of)),
                "order_delivered_customer_date": timestamp(happened(order.delivered_at, as_of)),
                "order_estimated_delivery_date": f"{order.promised_date:%Y-%m-%d} 00:00:00",
                **labels,
            }
        )
        rows["customers"].append(
            {
                "customer_id": order.customer_id,
                "customer_unique_id": order.customer_unique_id,
                "customer_zip_code_prefix": order.customer_zip_prefix,
                "customer_city": order.customer_city,
                "customer_state": order.customer_state,
                **labels,
            }
        )
        for number, product_id, seller_id, price, freight in order.items:
            rows["order_items"].append(
                {
                    "order_id": order.order_id,
                    "order_item_id": number,
                    "product_id": product_id,
                    "seller_id": seller_id,
                    "shipping_limit_date": timestamp(order.shipping_limit_at),
                    "price": f"{price:.2f}",
                    "freight_value": f"{freight:.2f}",
                    **labels,
                }
            )
        for sequence, payment_type, installments, value in order.payments:
            rows["order_payments"].append(
                {
                    "order_id": order.order_id,
                    "payment_sequential": sequence,
                    "payment_type": payment_type,
                    "payment_installments": installments,
                    "payment_value": f"{value:.2f}",
                    **labels,
                }
            )
        review = order.review
        if review and review["answered_at"] <= as_of:
            rows["order_reviews"].append(
                {
                    "review_id": review["review_id"],
                    "order_id": order.order_id,
                    "review_score": review["score"],
                    "review_comment_title": "",
                    "review_comment_message": "",
                    "review_creation_date": f"{review['sent_date']:%Y-%m-%d} 00:00:00",
                    "review_answer_timestamp": timestamp(review["answered_at"]),
                    **labels,
                }
            )
    return {name: pd.DataFrame(data) for name, data in rows.items()}


def write_snapshot(frames: dict[str, pd.DataFrame]) -> None:
    SIM_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        path = SIM_RAW_DIR / f"sim_{name}.csv"
        temp_path = path.with_suffix(".tmp")
        frame.to_csv(temp_path, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        temp_path.replace(path)


def previous_state() -> tuple[dict[str, str], int, str | None]:
    """Order statuses and review count from the last snapshot, to report what changed since then."""
    orders_path, reviews_path = SIM_RAW_DIR / "sim_orders.csv", SIM_RAW_DIR / "sim_order_reviews.csv"
    if not orders_path.exists():
        return {}, 0, None
    previous = pd.read_csv(orders_path, dtype=str, keep_default_na=False)
    reviews = len(pd.read_csv(reviews_path, dtype=str)) if reviews_path.exists() else 0
    as_of = previous["sim_as_of"].iloc[0] if len(previous) else None
    return dict(zip(previous["order_id"], previous["order_status"], strict=True)), reviews, as_of


def summarise(
    frames: dict[str, pd.DataFrame], previous: tuple[dict[str, str], int, str | None], as_of: datetime
) -> dict:
    statuses, previous_reviews, previous_as_of = previous
    orders = frames["orders"]
    current = dict(zip(orders["order_id"], orders["order_status"], strict=True))
    return {
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sim_as_of": timestamp(as_of),
        "previous_sim_as_of": previous_as_of or "",
        "days_covered_since_last_run": (as_of.date() - datetime.fromisoformat(previous_as_of).date()).days
        if previous_as_of
        else "",
        "orders_total": len(orders),
        "new_orders": sum(1 for order_id in current if order_id not in statuses),
        "orders_changed_status": sum(
            1 for order_id, status in current.items() if order_id in statuses and statuses[order_id] != status
        ),
        "newly_delivered": sum(
            1
            for order_id, status in current.items()
            if status == "delivered" and statuses.get(order_id) not in (None, "delivered")
        ),
        "in_transit": int((orders["order_status"] == "shipped").sum()),
        "delivered_total": int((orders["order_status"] == "delivered").sum()),
        "reviews_total": len(frames["order_reviews"]),
        "new_reviews": len(frames["order_reviews"]) - previous_reviews,
    }


def append_log(summary: dict) -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not RUN_LOG.exists()
    with RUN_LOG.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary))
        if is_new:
            writer.writeheader()
        writer.writerow(summary)


def run(as_of: datetime | None = None) -> dict:
    as_of = as_of or now_in_brazil()
    engine = load_engine()
    previous = previous_state()
    frames = snapshot(plan_until(engine, as_of), as_of)
    write_snapshot(frames)
    summary = summarise(frames, previous, as_of)
    append_log(summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the simulated shop up to now (SYNTHETIC DATA).")
    parser.add_argument("--as-of", help='Show the shop at this Sao Paulo time instead of now, e.g. "2026-10-05 02:00".')
    args = parser.parse_args()
    summary = run(datetime.fromisoformat(args.as_of) if args.as_of else None)
    for key, value in summary.items():
        print(f"{key:30s} {value}")


if __name__ == "__main__":
    main()
