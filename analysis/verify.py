"""Independent check: recompute the headline numbers straight from the raw files with pandas (no SQL,
no dbt) and compare them with the dbt marts. Writes docs/results/03_verification.md and exits with an
error if any number differs, so the pipeline stops before a wrong number reaches the dashboard.

Run from the project root:
    uv run python -m analysis.verify
"""

from __future__ import annotations

import sys

import pandas as pd

from analysis.common import RESULTS_DIR, connect, md_table
from ingestion.config import RAW_DATA_DIR

KPI_START, KPI_END = pd.Timestamp("2017-01-01"), pd.Timestamp("2018-08-31")
DATA_CUTOFF = pd.Timestamp("2018-10-17")
OPEN_STATUSES = {"shipped", "invoiced", "processing", "created", "approved"}
METRICS = [
    "Orders in KPI window",
    "Delivered orders",
    "Late orders",
    "Late rate",
    "Overdue, never delivered",
    "GMV (BRL)",
    "GMV (EUR)",
    "Late GMV (EUR)",
    "Revenue at risk (EUR)",
    "Late orders where the seller shipped late",
]


def pandas_numbers() -> dict[str, float]:
    olist = RAW_DATA_DIR / "olist"
    orders = pd.read_csv(olist / "olist_orders_dataset.csv", dtype=str)
    items = pd.read_csv(olist / "olist_order_items_dataset.csv", dtype=str)
    reviews = pd.read_csv(olist / "olist_order_reviews_dataset.csv", dtype=str)
    fx = pd.read_json(RAW_DATA_DIR / "fx" / "fx_EUR_BRL.ndjson", lines=True)

    for column in [
        "order_purchase_timestamp",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]:
        orders[column] = pd.to_datetime(orders[column])
    orders["purchase_date"] = orders["order_purchase_timestamp"].dt.normalize()
    orders["promised_date"] = orders["order_estimated_delivery_date"].dt.normalize()
    orders["delivered_date"] = orders["order_delivered_customer_date"].dt.normalize()

    # Money: item prices + freight per order, converted at the ECB rate of the purchase date
    # (weekends and holidays use the last published rate: forward fill).
    items["gmv_brl"] = items["price"].astype(float) + items["freight_value"].astype(float)
    items["shipping_limit"] = pd.to_datetime(items["shipping_limit_date"])
    per_order = items.groupby("order_id").agg(gmv_brl=("gmv_brl", "sum"), ship_by=("shipping_limit", "max"))
    rates = fx.assign(date=pd.to_datetime(fx["date"])).set_index("date")["rate"]
    rates = rates.reindex(pd.date_range(rates.index.min(), "2018-12-31")).ffill()

    # Reviews: keep the latest answer per order.
    reviews["answered"] = pd.to_datetime(reviews["review_answer_timestamp"])
    reviews["sent"] = pd.to_datetime(reviews["review_creation_date"])
    latest = (
        reviews.sort_values(["order_id", "answered", "sent", "review_id"], ascending=[True, False, False, True])
        .drop_duplicates("order_id")
        .set_index("order_id")["review_score"]
        .astype(int)
    )

    df = orders.set_index("order_id").join(per_order).join(latest)
    df["gmv_brl"] = df["gmv_brl"].fillna(0)
    df["gmv_eur"] = df["gmv_brl"] / rates.reindex(df["purchase_date"]).to_numpy()
    df = df[(df["purchase_date"] >= KPI_START) & (df["purchase_date"] <= KPI_END)]

    delivered = (df["order_status"] == "delivered") & df["order_delivered_customer_date"].notna()
    late = delivered & (df["delivered_date"] > df["promised_date"])
    overdue = df["order_status"].isin(OPEN_STATUSES) & (df["promised_date"] < DATA_CUTOFF)
    at_risk = (late & (df["review_score"] <= 2)) | overdue
    seller_late = late & (df["order_delivered_carrier_date"] > df["ship_by"])

    values = [
        len(df),
        delivered.sum(),
        late.sum(),
        late.sum() / delivered.sum(),
        overdue.sum(),
        df["gmv_brl"].sum(),
        df["gmv_eur"].sum(),
        df.loc[late, "gmv_eur"].sum(),
        df.loc[at_risk, "gmv_eur"].sum(),
        seller_late.sum(),
    ]
    return dict(zip(METRICS, [float(value) for value in values], strict=True))


def dbt_numbers() -> dict[str, float]:
    row = (
        connect()
        .execute("""
        select count(*),
               sum(case when is_delivered then 1 else 0 end),
               sum(case when is_late then 1 else 0 end),
               sum(case when is_late then 1.0 else 0 end) / sum(case when is_delivered then 1 else 0 end),
               sum(case when delivery_outcome = 'Overdue, not delivered' then 1 else 0 end),
               sum(gmv_brl), sum(gmv_eur), sum(late_gmv_eur), sum(revenue_at_risk_eur),
               sum(case when late_cause = 'Seller shipped late' then 1 else 0 end)
        from marts.fct_orders where is_in_kpi_window
    """)
        .fetchone()
    )
    return dict(zip(METRICS, [float(value) for value in row], strict=True))


def run() -> bool:
    independent, warehouse = pandas_numbers(), dbt_numbers()
    rows = []
    for metric, expected in independent.items():
        actual = warehouse[metric]
        tolerance = 1e-6 if metric == "Late rate" else 0.01
        rows.append(
            {
                "metric": metric,
                "pandas (raw files)": expected,
                "dbt marts": actual,
                "difference": actual - expected,
                "match": abs(actual - expected) <= tolerance,
            }
        )
    table = pd.DataFrame(rows)
    all_match = bool(table["match"].all())
    formats = {"pandas (raw files)": "{:,.4f}", "dbt marts": "{:,.4f}", "difference": "{:,.6f}"}
    text = (
        "# Independent verification\n\n"
        "Generated by `analysis/verify.py`. The pandas column is computed from the raw CSV and NDJSON files\n"
        "without any SQL; the dbt column comes from `marts.fct_orders`. KPI window Jan 2017 - Aug 2018.\n\n"
        f"{md_table(table, formats)}\n\n"
        f"**Result: {'all numbers match' if all_match else 'MISMATCH - investigate before publishing'}.**\n"
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "03_verification.md").write_text(text, encoding="utf-8")
    print(text)
    return all_match


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
