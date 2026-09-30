"""The list of raw tables: which landed files become which table in the warehouse's `raw` schema.

Both loaders (DuckDB for local development, BigQuery for the cloud) read this list,
so the two warehouses always end up with identically named raw tables.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ingestion.config import RAW_DATA_DIR

RAW_SCHEMA = "raw"


@dataclass(frozen=True)
class RawTable:
    name: str
    pattern: str  # glob relative to data/raw; several matching files are loaded into one table
    file_format: str  # "csv" or "ndjson"

    def files(self, raw_dir: Path = RAW_DATA_DIR) -> list[Path]:
        matches = sorted(raw_dir.glob(self.pattern))
        if not matches:
            raise FileNotFoundError(
                f"No files for raw table '{self.name}' at data/raw/{self.pattern}. Run the extract first."
            )
        return matches

    def source_row_count(self, raw_dir: Path = RAW_DATA_DIR) -> int:
        """Count records straight from the files, with a CSV parser (review texts contain line breaks)."""
        total = 0
        for path in self.files(raw_dir):
            with path.open(encoding="utf-8", newline="") as file:
                if self.file_format == "csv":
                    total += sum(1 for _ in csv.reader(file)) - 1
                else:
                    total += sum(1 for line in file if line.strip())
        return total


RAW_TABLES = [
    RawTable("olist_orders", "olist/olist_orders_dataset.csv", "csv"),
    RawTable("olist_order_items", "olist/olist_order_items_dataset.csv", "csv"),
    RawTable("olist_order_payments", "olist/olist_order_payments_dataset.csv", "csv"),
    RawTable("olist_order_reviews", "olist/olist_order_reviews_dataset.csv", "csv"),
    RawTable("olist_customers", "olist/olist_customers_dataset.csv", "csv"),
    RawTable("olist_sellers", "olist/olist_sellers_dataset.csv", "csv"),
    RawTable("olist_products", "olist/olist_products_dataset.csv", "csv"),
    RawTable("olist_geolocation", "olist/olist_geolocation_dataset.csv", "csv"),
    RawTable("olist_category_translation", "olist/product_category_name_translation.csv", "csv"),
    RawTable("holidays", "holidays/holidays_BR_*.ndjson", "ndjson"),
    RawTable("weather_daily", "weather/weather_*.ndjson", "ndjson"),
    RawTable("fx_rates", "fx/fx_EUR_BRL.ndjson", "ndjson"),
    RawTable("ipca_monthly", "ipca/ipca_BR.ndjson", "ndjson"),
    # SYNTHETIC DATA: the simulated live orders (simulator/run.py), in the Olist file format.
    RawTable("sim_orders", "sim/sim_orders.csv", "csv"),
    RawTable("sim_order_items", "sim/sim_order_items.csv", "csv"),
    RawTable("sim_order_payments", "sim/sim_order_payments.csv", "csv"),
    RawTable("sim_order_reviews", "sim/sim_order_reviews.csv", "csv"),
    RawTable("sim_customers", "sim/sim_customers.csv", "csv"),
]
