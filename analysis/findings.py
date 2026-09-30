"""Stage 5: answer the business questions from the marts. Writes docs/results/02_findings.md and the
charts in docs/images/. Every number in those files comes from this script.

Run from the project root (after `dbt build`):
    uv run python -m analysis.findings
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.common import COLORS, IMAGES_DIR, RESULTS_DIR, connect, eur, md_table, query  # noqa: E402

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": COLORS["muted"],
        "axes.labelcolor": COLORS["text"],
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": COLORS["text"],
        "ytick.color": COLORS["text"],
        "axes.titleweight": "bold",
        "axes.titlesize": 11,
        "figure.dpi": 150,
    }
)

# Promise-policy backtest: learn each route's delivery-time percentile from 2017, apply it to Jan-Aug 2018.
BACKTEST_SQL = """
with delivered as (
    select route, customer_state, purchase_date, promised_days, actual_days, is_late
    from marts.fct_orders where is_delivered and route is not null and data_source = 'olist'
),
train as (select * from delivered where purchase_date between '2017-01-01' and '2017-12-31'),
test as (select * from delivered where purchase_date between '2018-01-01' and '2018-08-31'),
route_q as (select route, count(*) as n, quantile_cont(actual_days, {p}) as q from train group by route),
state_q as (select customer_state, quantile_cont(actual_days, {p}) as q from train group by customer_state),
overall_q as (select quantile_cont(actual_days, {p}) as q from train),
scored as (
    select test.*, ceil(coalesce(case when route_q.n >= 30 then route_q.q end, state_q.q, overall_q.q)) as proposed_days
    from test
    left join route_q using (route)
    left join state_q using (customer_state)
    cross join overall_q
)
select
    {p} as percentile,
    count(*) as orders,
    avg(promised_days) as current_avg_promise_days,
    avg(case when is_late then 1.0 else 0 end) as current_late_rate,
    avg(proposed_days) as proposed_avg_promise_days,
    avg(case when actual_days > proposed_days then 1.0 else 0 end) as proposed_late_rate
from scored
"""


def save(fig: plt.Figure, name: str) -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMAGES_DIR / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def chart_headline(kpi: pd.Series, reviews: pd.DataFrame) -> None:
    on_time = reviews.set_index("delivery_outcome").loc["On time", "avg_review"]
    late = reviews.set_index("delivery_outcome").loc["Late", "avg_review"]
    tiles = [
        ("Revenue (GMV)", eur(kpi.gmv_eur), f"{kpi.orders:,.0f} orders, Jan 2017 - Aug 2018"),
        ("Delivered late", f"{kpi.late_rate:.1%}", f"{kpi.late_orders:,.0f} orders after the promised date"),
        ("Revenue at risk", eur(kpi.revenue_at_risk_eur), f"{kpi.revenue_at_risk_eur / kpi.gmv_eur:.1%} of revenue"),
        ("Review score", f"{late:.1f} vs {on_time:.1f}", "late vs on-time orders (stars)"),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(12, 2.2))
    for ax, (label, value, note) in zip(axes, tiles, strict=True):
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=COLORS["light"], zorder=0))
        color = COLORS["risk"] if label in ("Revenue at risk", "Delivered late") else COLORS["primary"]
        ax.text(0.06, 0.72, label, transform=ax.transAxes, fontsize=10, color=COLORS["text"])
        ax.text(0.06, 0.38, value, transform=ax.transAxes, fontsize=20, fontweight="bold", color=color)
        ax.text(0.06, 0.12, note, transform=ax.transAxes, fontsize=8, color=COLORS["text"])
    save(fig, "00_headline.png")


def chart_monthly(monthly: pd.DataFrame) -> None:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    months = pd.to_datetime(monthly["month_start"])
    top.bar(months, monthly["late_rate"] * 100, width=20, color=COLORS["late"])
    top.set_ylabel("Delivered late (%)")
    top.set_title("Late deliveries spike in peak periods")
    events = {
        "2017-11-01": "Black Friday",
        "2018-03-01": "Feb-Mar 2018\n(cause not in the data)",
        "2018-05-01": "Truck drivers'\nstrike (late May)",
    }
    for month, label in events.items():
        row = monthly[months == pd.Timestamp(month)].iloc[0]
        top.annotate(
            label,
            (pd.Timestamp(month), row.late_rate * 100),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=COLORS["text"],
        )
    top.set_ylim(0, monthly["late_rate"].max() * 100 * 1.3)

    bottom.plot(
        months, monthly["avg_promised_days"], color=COLORS["primary"], marker="o", markersize=3, label="Promised"
    )
    bottom.plot(months, monthly["avg_actual_days"], color=COLORS["muted"], marker="o", markersize=3, label="Actual")
    bottom.fill_between(months, monthly["avg_actual_days"], monthly["avg_promised_days"], color=COLORS["light"])
    bottom.set_ylabel("Days, purchase to delivery")
    bottom.set_title("Olist promises about twice the actual delivery time, but cut the buffer in 2018")
    bottom.legend(frameon=False, loc="upper right")
    save(fig, "01_monthly_trend.png")


def chart_reviews(by_days_late: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    labels = by_days_late["days_late_band"].str.split(": ").str[1]
    colors = [COLORS["primary"]] + [COLORS["late"]] * (len(by_days_late) - 1)
    bars = ax.bar(labels, by_days_late["share_low_review"] * 100, color=colors)
    for bar, score in zip(bars, by_days_late["avg_review"], strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5, f"avg {score:.1f} stars", ha="center", fontsize=8
        )
    ax.set_ylabel("Orders rated 1-2 stars (%)")
    ax.set_xlabel("Days after the promised date")
    ax.set_title("Even 1-2 days late nearly triples the share of 1-2 star reviews")
    ax.set_ylim(0, by_days_late["share_low_review"].max() * 100 * 1.2)
    save(fig, "02_reviews_by_days_late.png")


def chart_drivers(drivers: pd.DataFrame) -> None:
    drivers = drivers.sort_values("adjusted_late_rate_difference")
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True, gridspec_kw={"width_ratios": [3, 2]})
    y = range(len(drivers))
    left.barh(
        y,
        drivers["adjusted_late_rate_difference"] * 100,
        color=[COLORS["late"] if v > 0 else COLORS["primary"] for v in drivers["adjusted_late_rate_difference"]],
    )
    left.scatter(
        drivers["raw_late_rate_difference"] * 100,
        y,
        color=COLORS["text"],
        marker="|",
        s=200,
        zorder=3,
        label="Before adjusting",
    )
    left.axvline(0, color=COLORS["muted"], linewidth=0.8)
    left.set_yticks(list(y), drivers["driver"])
    left.set_xlabel("Change in late rate (percentage points)")
    left.set_title("Late rate with vs. without the condition\n(same state, same week)")
    left.legend(frameon=False, loc="lower right", fontsize=8)

    height = 0.38
    right.barh(
        [i + height / 2 for i in y],
        drivers["adjusted_actual_days_difference"],
        height=height,
        color=COLORS["late"],
        label="Extra delivery days",
    )
    right.barh(
        [i - height / 2 for i in y],
        drivers["adjusted_promised_days_difference"],
        height=height,
        color=COLORS["primary"],
        label="Extra promised days",
    )
    right.axvline(0, color=COLORS["muted"], linewidth=0.8)
    right.set_xlabel("Days")
    right.set_title("Late when the delay is bigger\nthan the extra promise")
    right.legend(frameon=False, loc="lower right", fontsize=8)
    save(fig, "03_late_drivers.png")


def chart_routes(routes: pd.DataFrame) -> None:
    top = routes.head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(top["route"], top["revenue_at_risk_eur"] / 1000, color=COLORS["risk"])
    for i, (_, row) in enumerate(top.iterrows()):
        ax.text(
            row.revenue_at_risk_eur / 1000 + 0.5,
            i,
            f"{row.late_rate:.0%} late, {row.delivered_orders:,.0f} orders",
            va="center",
            fontsize=8,
        )
    ax.set_xlabel("Revenue at risk (EUR thousand)")
    top10_share = routes.head(10)["share_of_revenue_at_risk"].sum()
    ax.set_title(f"Top 15 routes by revenue at risk (the top 10 hold {top10_share:.0%} of it)")
    ax.set_xlim(0, top["revenue_at_risk_eur"].max() / 1000 * 1.45)
    save(fig, "04_routes.png")


def chart_promise_tradeoff(backtest: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(
        backtest["proposed_avg_promise_days"], backtest["proposed_late_rate"] * 100, color=COLORS["primary"], marker="o"
    )
    for _, row in backtest.iterrows():
        ax.annotate(
            f"route P{row.percentile * 100:.0f}",
            (row.proposed_avg_promise_days, row.proposed_late_rate * 100),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=8,
        )
    current = backtest.iloc[0]
    ax.scatter(
        [current.current_avg_promise_days], [current.current_late_rate * 100], color=COLORS["late"], s=80, zorder=3
    )
    ax.annotate(
        "Olist's actual promise",
        (current.current_avg_promise_days, current.current_late_rate * 100),
        xytext=(8, -12),
        textcoords="offset points",
        fontsize=9,
        color=COLORS["late"],
    )
    ax.set_xlabel("Average promised days")
    ax.set_ylabel("Delivered late (%)")
    ax.set_title("Route-based promises vs. Olist's (tested on Jan-Aug 2018)")
    save(fig, "05_promise_tradeoff.png")


def run() -> str:
    con = connect()

    kpi = query(
        con,
        """
        select count(*) as orders,
               sum(case when is_delivered then 1 else 0 end) as delivered_orders,
               sum(case when is_late then 1 else 0 end) as late_orders,
               sum(case when is_late then 1.0 else 0 end) / sum(case when is_delivered then 1 else 0 end) as late_rate,
               sum(case when delivery_outcome = 'Overdue, not delivered' then 1 else 0 end) as overdue_orders,
               sum(gmv_eur) as gmv_eur, sum(late_gmv_eur) as late_gmv_eur, sum(revenue_at_risk_eur) as revenue_at_risk_eur,
               avg(case when is_delivered then promised_days end) as avg_promised_days,
               avg(actual_days) as avg_actual_days
        from marts.fct_orders where is_in_kpi_window
    """,
    ).iloc[0]

    risk_by_reason = query(
        con,
        """
        select revenue_at_risk_reason as reason, count(*) as orders, sum(revenue_at_risk_eur) as revenue_at_risk_eur
        from marts.fct_orders where is_in_kpi_window and revenue_at_risk_reason is not null
        group by 1 order by 3 desc
    """,
    )

    outcomes = query(
        con,
        """
        select delivery_outcome, count(*) as orders, sum(gmv_eur) as gmv_eur
        from marts.fct_orders where is_in_kpi_window group by 1 order by 2 desc
    """,
    )

    reviews = query(
        con,
        """
        select delivery_outcome, count(review_score) as reviewed_orders, avg(review_score) as avg_review,
               avg(case when is_low_review then 1.0 else 0 end) as share_low_review
        from marts.fct_orders
        where is_in_kpi_window and delivery_outcome in ('On time', 'Late', 'Overdue, not delivered') and review_score is not null
        group by 1 order by 2 desc
    """,
    )

    by_days_late = query(
        con,
        """
        select case when days_late = 0 then '0: on time'
                    when days_late <= 2 then '1: 1-2 days'
                    when days_late <= 7 then '2: 3-7 days'
                    when days_late <= 14 then '3: 8-14 days'
                    else '4: over 14 days' end as days_late_band,
               count(*) as orders, avg(review_score) as avg_review,
               avg(case when is_low_review then 1.0 else 0 end) as share_low_review
        from marts.fct_orders where is_delivered and is_in_kpi_window and review_score is not null
        group by 1 order by 1
    """,
    )

    stages = query(
        con,
        """
        select case when is_late then 'Late' else 'On time' end as outcome,
               median(approval_hours) as median_approval_hours,
               median(handover_days) as median_seller_days,
               median(transit_days) as median_carrier_days,
               avg(promised_days) as avg_promised_days
        from marts.fct_orders where is_delivered and is_in_kpi_window group by 1 order by 1 desc
    """,
    )

    approval_by_payment = query(
        con,
        """
        select main_payment_type as payment_type, count(*) as delivered_orders,
               median(approval_hours) as median_approval_hours,
               quantile_cont(approval_hours, 0.9) as p90_approval_hours,
               avg(case when is_late then 1.0 else 0 end) as late_rate
        from marts.fct_orders where is_delivered and is_in_kpi_window and main_payment_type <> 'not_defined'
        group by 1 order by 2 desc
    """,
    )

    late_causes = query(
        con,
        """
        select late_cause, count(*) as late_orders, count(*) * 1.0 / sum(count(*)) over () as share,
               sum(late_gmv_eur) as late_gmv_eur
        from marts.fct_orders where is_late and is_in_kpi_window group by 1 order by 2 desc
    """,
    )

    drivers = query(con, "select * from marts.mart_late_drivers order by adjusted_late_rate_difference desc")

    routes = query(
        con,
        """
        select * from marts.mart_route_performance where is_rankable order by revenue_at_risk_rank
    """,
    )

    worst_late_routes = query(
        con,
        """
        select route, delivered_orders, late_rate, avg_promised_days, avg_actual_days, p90_actual_days, avg_distance_km
        from marts.mart_route_performance where is_rankable order by late_rate desc limit 10
    """,
    )

    regions = query(
        con,
        """
        select customer_region, count(*) as delivered_orders, avg(case when is_late then 1.0 else 0 end) as late_rate,
               avg(promised_days) as avg_promised_days, avg(actual_days) as avg_actual_days, sum(revenue_at_risk_eur) as revenue_at_risk_eur
        from marts.fct_orders where is_delivered and is_in_kpi_window group by 1 order by 3 desc
    """,
    )

    sellers = query(
        con,
        """
        select count(*) as sellers,
               sum(case when is_rankable then 1 else 0 end) as sellers_with_30_plus_orders,
               sum(case when is_on_watchlist then 1 else 0 end) as watchlist_sellers,
               max(platform_late_rate) as platform_late_rate,
               sum(case when is_on_watchlist then gmv_eur else 0 end) / sum(gmv_eur) as watchlist_share_of_gmv,
               sum(case when is_on_watchlist then revenue_at_risk_eur else 0 end) / sum(revenue_at_risk_eur) as watchlist_share_of_revenue_at_risk
        from marts.mart_seller_performance
    """,
    ).iloc[0]

    watchlist = query(
        con,
        """
        select left(seller_id, 8) as seller, seller_state as state, delivered_orders, late_rate, missed_ship_by_rate,
               avg_review_score, gmv_eur, revenue_at_risk_eur
        from marts.mart_seller_performance where is_on_watchlist order by revenue_at_risk_eur desc limit 10
    """,
    )

    top_sellers = query(
        con,
        """
        select revenue_at_risk_rank as rank, left(seller_id, 8) as seller, seller_state as state, delivered_orders,
               late_rate, missed_ship_by_rate, avg_review_score, revenue_at_risk_eur, is_on_watchlist as watchlist
        from marts.mart_seller_performance where is_rankable order by revenue_at_risk_rank limit 10
    """,
    )

    monthly = query(con, "select * from marts.mart_monthly_kpis order by month_start")
    backtest = pd.concat([query(con, BACKTEST_SQL.format(p=p)) for p in (0.8, 0.9, 0.95, 0.97)], ignore_index=True)

    chart_headline(kpi, reviews)
    chart_monthly(monthly)
    chart_reviews(by_days_late)
    chart_drivers(drivers)
    chart_routes(routes)
    chart_promise_tradeoff(backtest)

    pct = "{:.1%}"
    money = "{:,.0f}"
    days = "{:.1f}"
    top10_share = routes.head(10)["share_of_revenue_at_risk"].sum()
    text = f"""# Findings

Generated by `analysis/findings.py` from the dbt marts. KPI window: orders purchased 1 Jan 2017 to
31 Aug 2018 (the 20 complete months). Money in euros at the ECB rate of each purchase date.

![Headline](../images/00_headline.png)

## 1. Headline

| Measure | Value |
|---|---|
| Orders | {kpi.orders:,.0f} |
| Delivered | {kpi.delivered_orders:,.0f} |
| Delivered late | {kpi.late_orders:,.0f} ({kpi.late_rate:.2%}) |
| Overdue, never delivered | {kpi.overdue_orders:,.0f} |
| Revenue (GMV) | {eur(kpi.gmv_eur)} |
| Revenue of late orders | {eur(kpi.late_gmv_eur)} |
| **Revenue at risk** | **{eur(kpi.revenue_at_risk_eur)} ({kpi.revenue_at_risk_eur / kpi.gmv_eur:.1%} of GMV)** |
| Average promised vs. actual delivery | {kpi.avg_promised_days:.1f} vs. {kpi.avg_actual_days:.1f} days |

Revenue at risk = orders where the promise was broken **and** there is evidence of damage:

{md_table(risk_by_reason, {"revenue_at_risk_eur": money})}

All outcomes:

{md_table(outcomes, {"gmv_eur": money})}

## 2. Late orders lose the customer

{md_table(reviews, {"avg_review": "{:.2f}", "share_low_review": pct})}

{md_table(by_days_late, {"avg_review": "{:.2f}", "share_low_review": pct})}

![Reviews](../images/02_reviews_by_days_late.png)

## 3. Where the time goes

Median time per stage (approval in hours, seller and carrier stages in days):

{
        md_table(
            stages,
            {
                "median_approval_hours": days,
                "median_seller_days": days,
                "median_carrier_days": days,
                "avg_promised_days": days,
            },
        )
    }

Payment approval by main payment type:

{md_table(approval_by_payment, {"median_approval_hours": days, "p90_approval_hours": days, "late_rate": pct})}

Whose stage made late orders late:

{md_table(late_causes, {"share": pct, "late_gmv_eur": money})}

## 4. What goes with late deliveries

Adjusted = exposed vs. unexposed orders to the same customer state in the same week (rain: same
shipping week). "Extra delivery days" and "extra promised days" are adjusted the same way.

{
        md_table(
            drivers[
                [
                    "driver",
                    "exposed_orders",
                    "share_exposed",
                    "late_rate_exposed",
                    "late_rate_not_exposed",
                    "raw_late_rate_difference",
                    "adjusted_late_rate_difference",
                    "adjusted_actual_days_difference",
                    "adjusted_promised_days_difference",
                ]
            ],
            {
                "share_exposed": pct,
                "late_rate_exposed": pct,
                "late_rate_not_exposed": pct,
                "raw_late_rate_difference": "{:+.1%}",
                "adjusted_late_rate_difference": "{:+.1%}",
                "adjusted_actual_days_difference": "{:+.1f}",
                "adjusted_promised_days_difference": "{:+.1f}",
            },
        )
    }

![Drivers](../images/03_late_drivers.png)

## 5. Routes

The 10 routes with the most revenue at risk hold {top10_share:.0%} of it (routes with 30+ delivered orders).

{
        md_table(
            routes.head(10)[
                [
                    "revenue_at_risk_rank",
                    "route",
                    "delivered_orders",
                    "late_rate",
                    "avg_distance_km",
                    "avg_promised_days",
                    "avg_actual_days",
                    "p90_actual_days",
                    "revenue_at_risk_eur",
                    "cumulative_share_of_revenue_at_risk",
                ]
            ],
            {
                "late_rate": pct,
                "avg_distance_km": money,
                "avg_promised_days": days,
                "avg_actual_days": days,
                "p90_actual_days": days,
                "revenue_at_risk_eur": money,
                "cumulative_share_of_revenue_at_risk": pct,
            },
        )
    }

Highest late rates:

{
        md_table(
            worst_late_routes,
            {
                "late_rate": pct,
                "avg_promised_days": days,
                "avg_actual_days": days,
                "p90_actual_days": days,
                "avg_distance_km": money,
            },
        )
    }

By customer region:

{
        md_table(
            regions,
            {"late_rate": pct, "avg_promised_days": days, "avg_actual_days": days, "revenue_at_risk_eur": money},
        )
    }

![Routes](../images/04_routes.png)

## 6. Sellers

{sellers.sellers:,.0f} sellers sold in the KPI window; {
        sellers.sellers_with_30_plus_orders:,.0f} have 30+ delivered orders.
**{sellers.watchlist_sellers:,.0f} are on the watchlist** (late rate at least twice the platform's {
        sellers.platform_late_rate:.1%}):
they handle {sellers.watchlist_share_of_gmv:.1%} of revenue but {
        sellers.watchlist_share_of_revenue_at_risk:.1%} of revenue at risk.

Top 10 sellers by revenue at risk (mostly large sellers with ordinary late rates: volume, not failure):

{
        md_table(
            top_sellers,
            {"late_rate": pct, "missed_ship_by_rate": pct, "avg_review_score": "{:.2f}", "revenue_at_risk_eur": money},
        )
    }

Top 10 watchlist sellers by revenue at risk (the ones to call first):

{
        md_table(
            watchlist,
            {
                "late_rate": pct,
                "missed_ship_by_rate": pct,
                "avg_review_score": "{:.2f}",
                "gmv_eur": money,
                "revenue_at_risk_eur": money,
            },
        )
    }

## 7. Month by month

{
        md_table(
            monthly.assign(month_start=pd.to_datetime(monthly["month_start"]).dt.strftime("%Y-%m"))[
                [
                    "month_start",
                    "delivered_orders",
                    "late_rate",
                    "late_rate_rolling_3m",
                    "gmv_eur",
                    "revenue_at_risk_eur",
                    "avg_promised_days",
                    "avg_actual_days",
                    "avg_review_score",
                ]
            ],
            {
                "late_rate": pct,
                "late_rate_rolling_3m": pct,
                "gmv_eur": money,
                "revenue_at_risk_eur": money,
                "avg_promised_days": days,
                "avg_actual_days": days,
                "avg_review_score": "{:.2f}",
            },
        )
    }

![Monthly](../images/01_monthly_trend.png)

## 8. Would route-based promises do better?

Each route's promise set to a percentile of its 2017 delivery times (fallback: customer state, then
all orders), tested on Jan-Aug 2018 orders against Olist's actual promises.

{
        md_table(
            backtest,
            {
                "percentile": "{:.0%}",
                "current_avg_promise_days": days,
                "current_late_rate": pct,
                "proposed_avg_promise_days": days,
                "proposed_late_rate": pct,
            },
        )
    }

![Promise trade-off](../images/05_promise_tradeoff.png)
"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "02_findings.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    run()
    print(f"Wrote {RESULTS_DIR / '02_findings.md'} and charts in {IMAGES_DIR}")
