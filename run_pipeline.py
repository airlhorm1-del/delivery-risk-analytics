"""Run the whole pipeline end to end, stopping at the first failure.

    uv run python run_pipeline.py                  # full: extract -> simulate -> load -> dbt -> analysis -> checks
    uv run python run_pipeline.py --skip-extract   # reuse the files already in data/raw
    uv run python run_pipeline.py --daily          # the daily run: today's API data + simulated live orders
    uv run python run_pipeline.py --bigquery       # afterwards, also load BigQuery and build the dbt models there
    uv run python run_pipeline.py --daily --bigquery --log-file logs/daily.log   # what the 07:00 task runs

The BigQuery steps run only after every local test and the independent verification have passed,
so a broken change never reaches the cloud warehouse or the dashboard.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

from ingestion.config import DBT_PROJECT_DIR, PROJECT_ROOT


class Pipeline:
    def __init__(self, log: TextIO | None):
        self.log = log

    def say(self, text: str) -> None:
        print(text, flush=True)
        if self.log:
            self.log.write(text + "\n")
            self.log.flush()

    def step(self, title: str, command: list[str], cwd: Path = PROJECT_ROOT) -> None:
        self.say(f"\n=== {title} ===")
        started = time.perf_counter()
        output = {"stdout": self.log, "stderr": subprocess.STDOUT} if self.log else {}
        result = subprocess.run(command, cwd=cwd, **output)
        if result.returncode != 0:
            self.say(f"Step failed: {title} (exit code {result.returncode})")
            sys.exit(result.returncode)
        self.say(f"--- {title}: done in {time.perf_counter() - started:.0f}s")


def python_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def dbt(*args: str) -> list[str]:
    return [sys.executable, "-m", "dbt.cli.main", *args]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-extract", action="store_true", help="Do not call the APIs or download Olist again.")
    parser.add_argument(
        "--daily", action="store_true", help="Daily run: only today's API data, then the simulated live orders."
    )
    parser.add_argument(
        "--bigquery", action="store_true", help="Also load and build in BigQuery (needs login, GCP_PROJECT_ID)."
    )
    parser.add_argument("--log-file", type=Path, help="Write all output to this file (used by the scheduled task).")
    args = parser.parse_args()

    log = None
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = args.log_file.open("a", encoding="utf-8")
    run = Pipeline(log)
    run.say(f"Pipeline started {time.strftime('%Y-%m-%d %H:%M:%S')} ({'daily' if args.daily else 'full'} run)")

    if not args.skip_extract:
        if not args.daily:
            run.step("Extract: Olist (Kaggle)", python_module("ingestion.olist"))
            run.step("Extract: historical weather (Open-Meteo)", python_module("ingestion.weather"))
        run.step(
            "Extract: public holidays (Nager.Date)",
            python_module("ingestion.holidays", *(["--live"] if args.daily else [])),
        )
        run.step("Extract: EUR/BRL rates up to today (ECB via Frankfurter)", python_module("ingestion.fx"))
        run.step("Extract: recent weather (Open-Meteo)", python_module("ingestion.weather", "--live"))
        run.step(
            "Extract: Brazilian inflation (Banco Central do Brasil, IBGE as backup)", python_module("ingestion.ipca")
        )

    run.step("Simulate: live orders up to now (SYNTHETIC DATA)", python_module("simulator.run"))
    run.step("Load: raw files -> DuckDB", python_module("ingestion.load_duckdb"))
    if not (DBT_PROJECT_DIR / "dbt_packages").exists():
        run.step("dbt: install packages", dbt("deps"), cwd=DBT_PROJECT_DIR)
    run.step("dbt: build models and run all tests (DuckDB)", dbt("build"), cwd=DBT_PROJECT_DIR)
    if not args.daily:
        run.step("Analysis: data profile", python_module("analysis.profile"))
        run.step("Analysis: findings and charts", python_module("analysis.findings"))
    run.step("Check: independent recomputation from raw files", python_module("analysis.verify"))
    if not args.daily:
        run.step("Check: simulator behaves like the real data", python_module("simulator.validate"))
    run.step("Export: Parquet files for Power BI", python_module("analysis.export_powerbi"))

    if args.bigquery:
        run.step("Load: raw files -> BigQuery", python_module("ingestion.load_bigquery"))
        # --full-refresh re-creates the seed tables too, so nothing in the sandbox reaches its 60-day expiry.
        run.step(
            "dbt: build models and run all tests (BigQuery)",
            dbt("build", "--target", "prod", "--full-refresh"),
            cwd=DBT_PROJECT_DIR,
        )

    run.say(
        f"\nPipeline finished {time.strftime('%Y-%m-%d %H:%M:%S')}. Results: docs/results/, Power BI files: powerbi/data/"
    )
    if log:
        log.close()


if __name__ == "__main__":
    main()
