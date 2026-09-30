"""Learn the patterns of real Olist orders and save them as simulator/model/sim_model.json.

Reads the tested historical tables in the warehouse (marts.fct_orders etc., Olist rows only) and
writes one readable JSON file: how many orders per weekday and month, at what hours, how payments
clear, how long sellers and carriers take per seller and route, what is promised, how often orders
are lost or cancelled, and how customers review. The file is committed to git, so the simulated
history only changes when the model is deliberately refitted.

Periods used:
- Volume level and weekday pattern: Jan-Aug 2018 (the latest complete months). Sep-Dec pattern and
  the Black Friday spike: 2017, the only year with those months.
- Delivery journeys (promise, seller deadline, hand-over, transit) are not summarised here: each
  simulated order copies the journey of a real order from the "normal" months (templates.py), which
  keeps promise and journey linked. Only the Christmas-season slowdown is learned here, as a factor.

Run from the project root (after `dbt build`); normally only when the model should change:
    uv run python -m simulator.fit
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

import duckdb
import pandas as pd

from ingestion.config import SIM_MODEL_PATH, WAREHOUSE_PATH
from simulator.bank_calendar import bank_days_between, black_friday, load_bank_holidays
from simulator.distributions import PERCENTILE_GRID, to_percentiles, to_shares
from simulator.templates import EXCLUDED_MONTHS

SEED = 20260702
BLACK_FRIDAY_DAYS = 7  # Black Friday and the six days after it (Cyber Monday week)
PEAK_WINDOW = ("11-20", "12-31")  # orders shipped in this window move more slowly (Christmas season)

HISTORICAL = "is_in_kpi_window"
NORMAL = f"{HISTORICAL} and strftime(purchase_date, '%Y-%m') not in {EXCLUDED_MONTHS}"


def fit_volume(con) -> dict:
    daily = con.execute(f"""
        select purchase_date, count(*) as orders from marts.fct_orders where {HISTORICAL} group by 1 order by 1
    """).df()
    daily["purchase_date"] = pd.to_datetime(daily["purchase_date"])
    daily["weekday"] = daily["purchase_date"].dt.isocalendar().day
    daily["month"] = daily["purchase_date"].dt.strftime("%Y-%m")

    level = daily[(daily["purchase_date"] >= "2018-01-01") & (daily["purchase_date"] <= "2018-08-31")]
    weekday_mean = level.groupby("weekday")["orders"].mean()
    per_day_2018 = level.groupby(level["purchase_date"].dt.month)["orders"].mean()
    month_factor = {month: per_day_2018[month] / per_day_2018.mean() for month in range(1, 9)}

    # Sep-Dec only exist in 2017: take their size relative to Aug 2017 and chain it onto Aug 2018.
    bf_2017 = pd.Timestamp(black_friday(2017))
    bf_window = daily["purchase_date"].between(bf_2017, bf_2017 + timedelta(days=BLACK_FRIDAY_DAYS - 1))
    y2017 = daily[(daily["purchase_date"].dt.year == 2017) & ~bf_window]
    per_day_2017 = y2017.groupby(y2017["purchase_date"].dt.month)["orders"].mean()
    for month in range(9, 13):
        month_factor[month] = month_factor[8] * per_day_2017[month] / per_day_2017[8]

    # Black Friday week: each day's orders relative to a normal November day of the same weekday.
    weekday_share = weekday_mean / weekday_mean.mean()
    november_base = per_day_2017[11]
    black_friday_factor = {}
    for offset in range(BLACK_FRIDAY_DAYS):
        day = bf_2017 + timedelta(days=offset)
        orders = int(daily.loc[daily["purchase_date"] == day, "orders"].iloc[0])
        black_friday_factor[str(offset)] = round(float(orders / (november_base * weekday_share[day.isoweekday()])), 3)

    return {
        "weekday_mean_orders": {str(day): round(float(value), 2) for day, value in weekday_mean.items()},
        "month_factor": {str(month): round(float(value), 4) for month, value in sorted(month_factor.items())},
        "black_friday_factor": black_friday_factor,
    }


def fit_hours(con) -> list[float]:
    hours = con.execute(f"""
        select hour(purchased_at) as hour, count(*) as orders from marts.fct_orders where {HISTORICAL} group by 1 order by 1
    """).df()
    total = hours["orders"].sum()
    return [round(float(hours.loc[hours["hour"] == hour, "orders"].sum() / total), 6) for hour in range(24)]


def fit_approval(con, bank_holidays: set[date]) -> dict:
    approvals = con.execute(f"""
        select main_payment_type, purchased_at, approved_at, approval_hours
        from marts.fct_orders
        where {HISTORICAL} and approved_at is not null and approval_hours >= 0 and main_payment_type is not null
    """).df()
    boleto = approvals[approvals["main_payment_type"] == "boleto"].copy()
    boleto["lag"] = [
        min(bank_days_between(p.date(), a.date(), bank_holidays), 7)
        for p, a in zip(boleto["purchased_at"], boleto["approved_at"], strict=True)
    ]
    later = boleto[boleto["lag"] >= 1]
    hour_counts = Counter(later["approved_at"].dt.hour)
    others = approvals[approvals["main_payment_type"] != "boleto"]
    return {
        "boleto": {
            "bank_day_lag_share": to_shares(Counter(boleto["lag"])),
            "same_day_minutes": to_percentiles(boleto.loc[boleto["lag"] == 0, "approval_hours"] * 60),
            "approval_hour_share": [round(hour_counts.get(hour, 0) / len(later), 6) for hour in range(24)],
        },
        "other_minutes": {
            payment_type: to_percentiles(group["approval_hours"] * 60)
            for payment_type, group in others.groupby("main_payment_type")
        },
    }


def fit_peak_season(con) -> dict:
    """How much slower carriers are between 20 Nov and 31 Dec (Black Friday and Christmas), from 2017."""
    peak = con.execute(f"""
        select median(transit_days) from marts.fct_orders
        where {HISTORICAL} and is_delivered and not has_timestamp_anomaly and transit_days >= 0
          and cast(shipped_at as date) between '2017-{PEAK_WINDOW[0]}' and '2017-{PEAK_WINDOW[1]}'
    """).fetchone()[0]
    normal = con.execute(f"""
        select median(transit_days) from marts.fct_orders
        where {NORMAL} and is_delivered and not has_timestamp_anomaly and transit_days >= 0
    """).fetchone()[0]
    return {"window": list(PEAK_WINDOW), "transit_factor": round(float(peak / normal), 3)}


def fit_outcomes(con) -> dict[str, float]:
    counts = con.execute(f"""
        select case
                 when order_status = 'canceled' then 'canceled'
                 when order_status = 'unavailable' then 'unavailable'
                 when delivery_outcome = 'Overdue, not delivered' and order_status = 'shipped' then 'lost_in_transit'
                 when delivery_outcome = 'Overdue, not delivered' then 'stuck_before_shipping'
                 else 'delivered'
               end as outcome,
               count(*) as orders
        from marts.fct_orders where {HISTORICAL} group by 1
    """).df()
    return to_shares(dict(zip(counts["outcome"], counts["orders"], strict=True)))


def review_bucket_sql() -> str:
    return """case
        when delivery_outcome = 'On time' then 'on_time'
        when delivery_outcome = 'Late' and days_late <= 2 then 'late_1_2_days'
        when delivery_outcome = 'Late' and days_late <= 7 then 'late_3_7_days'
        when delivery_outcome = 'Late' and days_late <= 14 then 'late_8_14_days'
        when delivery_outcome = 'Late' then 'late_over_14_days'
        when delivery_outcome = 'Overdue, not delivered' then 'never_delivered'
        when delivery_outcome = 'Cancelled' then 'cancelled'
    end"""


def fit_reviews(con) -> dict:
    orders = con.execute(f"""
        select {review_bucket_sql()} as bucket, o.review_score, o.delivery_outcome,
               date_diff('day', o.delivered_date, o.review_sent_date) as sent_after_delivery,
               date_diff('day', o.promised_date, o.review_sent_date) as sent_after_promise,
               date_diff('minute', cast(r.review_sent_date as timestamp), r.review_answered_at) / 60.0 as answer_hours
        from marts.fct_orders o
        left join intermediate.int_order_reviews_latest r using (order_id)
        where o.{HISTORICAL} and o.delivery_outcome <> 'Delivered, date missing'
    """).df()
    reviewed = orders[orders["review_score"].notna()]
    on_time = reviewed.loc[reviewed["bucket"] == "on_time", "sent_after_delivery"].clip(-2, 7)
    return {
        "no_review_share": round(float(orders["review_score"].isna().mean()), 6),
        "score_share_by_bucket": {
            bucket: to_shares(Counter(int(score) for score in group["review_score"]))
            for bucket, group in reviewed.groupby("bucket")
        },
        "on_time_sent_after_delivery_days_share": to_shares(Counter(int(day) for day in on_time)),
        "sent_after_promise_days": {
            "late": to_percentiles(reviewed.loc[reviewed["delivery_outcome"] == "Late", "sent_after_promise"]),
            "never_delivered": to_percentiles(
                reviewed.loc[reviewed["bucket"] == "never_delivered", "sent_after_promise"]
            ),
            "cancelled": to_percentiles(reviewed.loc[reviewed["bucket"] == "cancelled", "sent_after_promise"]),
        },
        "answer_hours": to_percentiles(reviewed["answer_hours"].clip(lower=0)),
    }


def run() -> dict:
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    bank_holidays = load_bank_holidays()
    model = {
        "about": "SYNTHETIC-DATA MODEL. Patterns learned from real Olist orders (2017-2018) by simulator/fit.py; "
        "used by simulator/run.py to generate simulated live orders. Distributions are stored as values at the "
        "percentiles in percentile_grid.",
        "seed": SEED,
        "periods": {
            "historical_window": ["2017-01-01", "2018-08-31"],
            "journey_templates_exclude_months": list(EXCLUDED_MONTHS),
        },
        "percentile_grid": PERCENTILE_GRID,
        "volume": fit_volume(con),
        "purchase_hour_share": fit_hours(con),
        "approval": fit_approval(con, bank_holidays),
        "peak_season": fit_peak_season(con),
        "outcome_share": fit_outcomes(con),
        "reviews": fit_reviews(con),
    }
    SIM_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIM_MODEL_PATH.write_text(json.dumps(model, indent=1), encoding="utf-8", newline="\n")
    return model


if __name__ == "__main__":
    fitted = run()
    volume = fitted["volume"]
    print(f"Wrote {SIM_MODEL_PATH}")
    print("orders per weekday (Mon..Sun):", list(volume["weekday_mean_orders"].values()))
    print("month factors:", volume["month_factor"])
    print("Black Friday week factors:", volume["black_friday_factor"])
    print("outcomes:", fitted["outcome_share"])
    print("peak season transit factor:", fitted["peak_season"]["transit_factor"])
