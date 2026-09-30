"""Does the simulator behave like the real data? Simulate four normal months and compare with 2017-2018.

Simulates Apr-Jul 2027 (normal months, far from Black Friday, not part of the live data) and lets
every order finish its journey, then compares a dozen measures with the real Olist orders from the
same kind of months. Writes docs/results/04_simulator_validation.md and docs/images/06_simulator_validation.png,
and exits with an error if any measure is outside its tolerance.

Run from the project root (after `dbt build`):
    uv run python -m simulator.validate
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.common import COLORS, IMAGES_DIR, RESULTS_DIR, md_table  # noqa: E402
from ingestion.config import BRAZIL_STATES_CSV, WAREHOUSE_PATH  # noqa: E402
from simulator.run import load_engine, plan_until  # noqa: E402
from simulator.templates import EXCLUDED_MONTHS  # noqa: E402

VALIDATION_START, VALIDATION_END = date(2027, 4, 1), date(2027, 7, 31)
EVERYTHING_FINISHED = datetime(2030, 1, 1)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def simulated_orders() -> pd.DataFrame:
    engine = load_engine()
    orders = plan_until(engine, datetime.combine(VALIDATION_END, datetime.max.time()), start=VALIDATION_START)
    template_value = {
        template_id: sum(price + freight for _, _, price, freight in items)
        for template_id, items in engine.template_items.items()
    }
    with BRAZIL_STATES_CSV.open(encoding="utf-8", newline="") as file:
        region = {row["state_code"]: row["region"] for row in csv.DictReader(file)}
    rows = []
    for order in orders:
        delivered = order.delivered_at is not None and order.delivered_at <= EVERYTHING_FINISHED
        rows.append(
            {
                "weekday": order.purchased_at.isoweekday(),
                "hour": order.purchased_at.hour,
                "payment_type": order.main_payment_type,
                "outcome": order.outcome,
                "promised_days": (order.promised_date - order.purchased_at.date()).days,
                "is_delivered": delivered,
                "actual_days": (order.delivered_at.date() - order.purchased_at.date()).days if delivered else None,
                "is_late": delivered and order.delivered_at.date() > order.promised_date,
                "region": region[order.customer_state],
                "seller_missed_deadline": order.shipped_at is not None and order.shipped_at > order.shipping_limit_at,
                "review_score": order.review["score"] if order.review else None,
                "approval_hours": (order.approved_at - order.purchased_at).total_seconds() / 3600
                if order.approved_at
                else None,
                "gmv_2017_18_prices": template_value[order.template_id],
            }
        )
    return pd.DataFrame(rows)


def real_orders() -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    base = "from marts.fct_orders where is_in_kpi_window"
    normal = f"{base} and strftime(purchase_date, '%Y-%m') not in {EXCLUDED_MONTHS}"
    return {
        "level": con.execute(
            "select isodow(purchase_date) as weekday from marts.fct_orders where purchase_date between '2018-01-01' and '2018-08-31'"
        ).df(),
        "all": con.execute(
            f"select hour(purchased_at) as hour, delivery_outcome, order_status, review_score, is_late, main_payment_type as payment_type, approval_hours, gmv_brl, is_delivered {base}"
        ).df(),
        "normal": con.execute(
            f"select customer_region as region, promised_days, actual_days, is_late, seller_missed_ship_by {normal} and is_delivered"
        ).df(),
    }


def shares(series: pd.Series, index) -> pd.Series:
    return series.value_counts(normalize=True).reindex(index, fill_value=0.0)


def compare() -> tuple[pd.DataFrame, dict]:
    sim, real = simulated_orders(), real_orders()
    delivered = sim[sim["is_delivered"]]
    real_all, real_normal = real["all"], real["normal"]
    real_delivered = real_all[real_all["is_delivered"]]

    weekday = pd.DataFrame(
        {"real": shares(real["level"]["weekday"], range(1, 8)), "simulated": shares(sim["weekday"], range(1, 8))}
    )
    hours = pd.DataFrame({"real": shares(real_all["hour"], range(24)), "simulated": shares(sim["hour"], range(24))})
    payment_types = ["credit_card", "boleto", "voucher", "debit_card"]
    payments = pd.DataFrame(
        {
            "real": shares(real_delivered["payment_type"], payment_types),
            "simulated": shares(sim["payment_type"], payment_types),
        }
    )
    regions = sorted(sim["region"].unique())
    region_late = pd.DataFrame(
        {
            "real": real_normal.groupby("region")["is_late"].mean().reindex(regions),
            "simulated": delivered.groupby("region")["is_late"].mean().reindex(regions),
        }
    )
    real_outcome = real_all["delivery_outcome"].isin(["On time", "Late", "Delivered, date missing"]).mean()
    real_low_on_time = (real_all.loc[real_all["delivery_outcome"] == "On time", "review_score"] <= 2).mean()
    real_low_late = (real_all.loc[real_all["delivery_outcome"] == "Late", "review_score"] <= 2).mean()
    sim_reviewed = sim[sim["review_score"].notna()]
    sim_low_on_time = (
        sim_reviewed.loc[sim_reviewed["is_delivered"] & ~sim_reviewed["is_late"], "review_score"] <= 2
    ).mean()
    sim_low_late = (sim_reviewed.loc[sim_reviewed["is_late"].astype(bool), "review_score"] <= 2).mean()
    approval = {
        kind: (
            real_all.loc[real_all["payment_type"] == kind, "approval_hours"].median(),
            sim.loc[sim["payment_type"] == kind, "approval_hours"].median(),
        )
        for kind in ("credit_card", "boleto")
    }

    pct = "{:.1%}"
    rows = [
        # measure, real, simulated, allowed difference, format, difference is relative?
        (
            "Weekday pattern: largest gap in share of orders",
            0.0,
            (weekday["simulated"] - weekday["real"]).abs().max(),
            0.015,
            "{:.2%}",
            False,
        ),
        (
            "Hour of day: largest gap in share of orders",
            0.0,
            (hours["simulated"] - hours["real"]).abs().max(),
            0.01,
            "{:.2%}",
            False,
        ),
        (
            "Payment mix: largest gap in share",
            0.0,
            (payments["simulated"] - payments["real"]).abs().max(),
            0.015,
            "{:.2%}",
            False,
        ),
        ("Share of orders delivered", real_outcome, (sim["outcome"] == "delivered").mean(), 0.005, pct, False),
        (
            "Average promised days (delivered orders)",
            real_normal["promised_days"].mean(),
            delivered["promised_days"].mean(),
            1.0,
            "{:.1f}",
            False,
        ),
        (
            "Average actual delivery days",
            real_normal["actual_days"].mean(),
            delivered["actual_days"].mean(),
            1.0,
            "{:.1f}",
            False,
        ),
        ("Late rate (delivered orders)", real_normal["is_late"].mean(), delivered["is_late"].mean(), 0.015, pct, False),
        (
            "Late rate by region: largest gap",
            0.0,
            (region_late["simulated"] - region_late["real"]).abs().max(),
            0.03,
            "{:.1%}",
            False,
        ),
        (
            "Seller missed hand-over deadline",
            real_normal["seller_missed_ship_by"].mean(),
            delivered["seller_missed_deadline"].mean(),
            0.02,
            pct,
            False,
        ),
        ("1-2 star reviews, on-time orders", real_low_on_time, sim_low_on_time, 0.02, pct, False),
        ("1-2 star reviews, late orders", real_low_late, sim_low_late, 0.05, pct, False),
        ("Median approval hours, credit card", *approval["credit_card"], 0.5, "{:.1f}", False),
        ("Median approval hours, boleto", *approval["boleto"], 6.0, "{:.1f}", False),
        (
            "Average order value, 2017-18 reais (relative)",
            real_delivered["gmv_brl"].mean(),
            sim["gmv_2017_18_prices"].mean(),
            0.03,
            "{:,.2f}",
            True,
        ),
    ]
    table = []
    for measure, real_value, simulated_value, tolerance, fmt, relative in rows:
        difference = (simulated_value - real_value) / real_value if relative else simulated_value - real_value
        gap_only = real_value == 0.0
        table.append(
            {
                "measure": measure,
                "real 2017-18": "" if gap_only else fmt.format(real_value),
                "simulated": fmt.format(simulated_value) if not gap_only else "",
                "difference": ("{:+.1%}" if relative else ("{:+.2%}" if "%" in fmt else "{:+.2f}")).format(difference)
                if not gap_only
                else fmt.format(simulated_value),
                "allowed": ("+/-" + (f"{tolerance:.0%}" if relative else (fmt.format(tolerance)))),
                "within": abs(difference) <= tolerance,
            }
        )
    details = {
        "weekday": weekday,
        "hours": hours,
        "region_late": region_late,
        "orders": len(sim),
        "delivered": len(delivered),
    }
    return pd.DataFrame(table), details


def chart(details: dict) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    weekday, hours, region_late = details["weekday"], details["hours"], details["region_late"]
    width = 0.4
    x = range(7)
    axes[0].bar([i - width / 2 for i in x], weekday["real"] * 100, width, color=COLORS["primary"], label="Real 2018")
    axes[0].bar([i + width / 2 for i in x], weekday["simulated"] * 100, width, color=COLORS["late"], label="Simulated")
    axes[0].set_xticks(list(x), WEEKDAYS)
    axes[0].set_title("Orders by weekday (%)")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(range(24), hours["real"] * 100, color=COLORS["primary"], label="Real")
    axes[1].plot(range(24), hours["simulated"] * 100, color=COLORS["late"], linestyle="--", label="Simulated")
    axes[1].set_title("Orders by hour of day (%)")
    axes[1].set_xlabel("Hour (Sao Paulo time)")
    y = range(len(region_late))
    axes[2].barh(
        [i + width / 2 for i in y],
        region_late["real"] * 100,
        width,
        color=COLORS["primary"],
        label="Real (normal months)",
    )
    axes[2].barh(
        [i - width / 2 for i in y], region_late["simulated"] * 100, width, color=COLORS["late"], label="Simulated"
    )
    axes[2].set_yticks(list(y), region_late.index)
    axes[2].set_title("Late rate by customer region (%)")
    axes[2].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Simulator check: simulated Apr-Jul 2027 vs. real Olist orders", fontweight="bold")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMAGES_DIR / "06_simulator_validation.png", bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)


def run() -> bool:
    table, details = compare()
    chart(details)
    passed = bool(table["within"].all())
    text = f"""# Simulator validation (SYNTHETIC DATA check)

Generated by `simulator/validate.py`. The simulator created {details["orders"]:,} orders for Apr-Jul 2027
(normal months, no Black Friday) and let every one finish its journey ({details["delivered"]:,} delivered).
They are compared with the real Olist orders: delivery measures with the "normal" months of the KPI
window (without Nov-Dec 2017 and Feb-Mar 2018), the weekday pattern with Jan-Aug 2018, the rest with
the whole KPI window.

{md_table(table)}

**Result: {"every measure is within its tolerance" if passed else "SOME MEASURES ARE OUTSIDE THEIR TOLERANCE - investigate before relying on the live data"}.**

![Simulator validation](../images/06_simulator_validation.png)

What this does and does not show: the simulated orders have the same *shape* as the real ones (when
people buy, how they pay, how long each stage takes, how often orders are late and how customers
react). They are not new evidence about the real world; the historical findings stay based on the
real data only.
"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "04_simulator_validation.md").write_text(text, encoding="utf-8", newline="\n")
    print(md_table(table))
    print("PASSED" if passed else "FAILED")
    return passed


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
