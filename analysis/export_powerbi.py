"""Export the mart tables to Parquet files in powerbi/data/.

The dashboard's main source is BigQuery (see powerbi/DASHBOARD_GUIDE.md). These files hold exactly the
same tables, so the dashboard can be built or checked before the BigQuery account is set up. Parquet
keeps column types (dates, true/false, decimals), which avoids CSV problems such as a German-locale
Power BI reading 3.45 as 345. Exact-decimal money columns are written as ordinary floating-point
numbers, the type Power BI's Parquet reader handles most reliably.

Run from the project root (after `dbt build`):
    uv run python -m analysis.export_powerbi
"""

from __future__ import annotations

from analysis.common import POWERBI_DATA_DIR, connect

TABLES = [
    "fct_orders",
    "fct_order_items",
    "dim_date",
    "dim_sellers",
    "dim_products",
    "dim_states",
    "mart_monthly_kpis",
    "mart_route_performance",
    "mart_seller_performance",
    "mart_late_drivers",
]


def select_list(con, table: str) -> str:
    columns = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'marts' and table_name = ? order by ordinal_position",
        [table],
    ).fetchall()
    return ", ".join(
        f"cast({name} as double) as {name}" if data_type.startswith(("DECIMAL", "HUGEINT")) else name
        for name, data_type in columns
    )


def run() -> None:
    POWERBI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    for table in TABLES:
        path = (POWERBI_DATA_DIR / f"{table}.parquet").as_posix()
        con.execute(f"copy (select {select_list(con, table)} from marts.{table}) to '{path}' (format parquet)")
        rows = con.execute(f"select count(*) from marts.{table}").fetchone()[0]
        print(f"{table:26s} {rows:>9,} rows -> powerbi/data/{table}.parquet")


if __name__ == "__main__":
    run()
