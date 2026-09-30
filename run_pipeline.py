"""Run the whole pipeline end to end, stopping at the first failure.

    uv run python run_pipeline.py                  # extract -> load -> dbt build -> analysis -> checks (local DuckDB)
    uv run python run_pipeline.py --skip-extract   # reuse the files already in data/raw
    uv run python run_pipeline.py --bigquery       # afterwards, also load BigQuery and build the dbt models there

The BigQuery steps run only after every local test and the independent verification have passed,
so a broken change never reaches the cloud warehouse or the dashboard.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

from ingestion.config import DBT_PROJECT_DIR, PROJECT_ROOT


def step(title: str, command: list[str], cwd=PROJECT_ROOT) -> None:
    print(f"\n=== {title} ===", flush=True)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        sys.exit(f"Step failed: {title} (exit code {result.returncode})")
    print(f"--- {title}: done in {time.perf_counter() - started:.0f}s", flush=True)


def python_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def dbt(*args: str) -> list[str]:
    return [sys.executable, "-m", "dbt.cli.main", *args]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-extract", action="store_true", help="Do not call the APIs or download Olist again.")
    parser.add_argument(
        "--bigquery", action="store_true", help="Also load and build in BigQuery (needs login, GCP_PROJECT_ID)."
    )
    args = parser.parse_args()

    if not args.skip_extract:
        step("Extract: Olist (Kaggle)", python_module("ingestion.olist"))
        step("Extract: public holidays (Nager.Date)", python_module("ingestion.holidays"))
        step("Extract: EUR/BRL rates (ECB via Frankfurter)", python_module("ingestion.fx"))
        step("Extract: weather (Open-Meteo)", python_module("ingestion.weather"))

    step("Load: raw files -> DuckDB", python_module("ingestion.load_duckdb"))
    if not (DBT_PROJECT_DIR / "dbt_packages").exists():
        step("dbt: install packages", dbt("deps"), cwd=DBT_PROJECT_DIR)
    step("dbt: build models and run all tests (DuckDB)", dbt("build"), cwd=DBT_PROJECT_DIR)
    step("Analysis: data profile", python_module("analysis.profile"))
    step("Analysis: findings and charts", python_module("analysis.findings"))
    step("Check: independent recomputation from raw files", python_module("analysis.verify"))
    step("Export: Parquet files for Power BI", python_module("analysis.export_powerbi"))

    if args.bigquery:
        step("Load: raw files -> BigQuery", python_module("ingestion.load_bigquery"))
        step("dbt: build models and run all tests (BigQuery)", dbt("build", "--target", "prod"), cwd=DBT_PROJECT_DIR)

    print("\nPipeline finished. Results: docs/results/, charts: docs/images/, Power BI files: powerbi/data/")


if __name__ == "__main__":
    main()
