"""Shared paths, the warehouse connection and small formatting helpers for the analysis scripts."""

from __future__ import annotations

import duckdb
import pandas as pd

from ingestion.config import PROJECT_ROOT, WAREHOUSE_PATH

RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
IMAGES_DIR = PROJECT_ROOT / "docs" / "images"
POWERBI_DATA_DIR = PROJECT_ROOT / "powerbi" / "data"

# One palette for every chart: late / at-risk is always orange, on time / neutral is blue-grey.
COLORS = {
    "primary": "#2F5D8A",
    "late": "#D9822B",
    "risk": "#B8442C",
    "muted": "#9AA5B1",
    "light": "#DCE3EA",
    "text": "#1F2933",
}


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE_PATH), read_only=True)


def query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def md_table(df: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """A DataFrame as a Markdown table. `formats` maps column -> format spec, e.g. {"late_rate": "{:.1%}"}."""
    formats = formats or {}

    def cell(column: str, value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        if column in formats:
            return formats[column].format(value)
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
            return f"{value:,.0f}"
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    header = "| " + " | ".join(df.columns) + " |"
    divider = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = [
        "| " + " | ".join(cell(col, val) for col, val in zip(df.columns, row, strict=True)) + " |"
        for row in df.itertuples(index=False)
    ]
    return "\n".join([header, divider, *rows])


def eur(value: float) -> str:
    """Euro amounts for text: EUR 1.2m, EUR 264k, EUR 950."""
    if abs(value) >= 1_000_000:
        return f"EUR {value / 1_000_000:.2f}m"
    if abs(value) >= 1_000:
        return f"EUR {value / 1_000:,.0f}k"
    return f"EUR {value:,.0f}"
