"""Load every landed file into Google BigQuery (dataset `raw`), with the same table names as DuckDB.

Before the first run (once):
    1. Create a Google Cloud project in the BigQuery console and note its project ID.
    2. gcloud auth application-default login     (opens the browser to log in)
    3. $env:GCP_PROJECT_ID = "your-project-id"     (PowerShell; or pass --project)

Run from the project root:
    uv run python -m ingestion.load_bigquery

Like the DuckDB loader, CSV columns are loaded as text (STRING) and typed later in dbt.
Each table is replaced in one step (WRITE_TRUNCATE): if an upload fails, the previous table stays in
place. A failed upload is retried, and in the BigQuery sandbox the table's expiry date is pushed forward
after every load, so the data never runs into the sandbox's 60-day limit. Data stays in the EU
multi-region unless BQ_LOCATION says otherwise; dbt's prod target uses the same setting.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import time
from datetime import UTC, datetime, timedelta

import requests
from google.api_core import exceptions as google_errors
from google.cloud import bigquery
from google.resumable_media import common as upload_errors

from ingestion.landing import configure_logging
from ingestion.sources import RAW_SCHEMA, RAW_TABLES, RawTable

logger = logging.getLogger(__name__)

DEFAULT_LOCATION = "EU"
# A long upload can break (network drop, or the laptop going to sleep mid-upload, as on 1 Oct 2026).
UPLOAD_ATTEMPTS = 3
PAUSE_BETWEEN_ATTEMPTS_SECONDS = 30
RETRYABLE_ERRORS = (
    google_errors.GoogleAPIError,
    upload_errors.InvalidResponse,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def csv_header(table: RawTable) -> list[str]:
    # utf-8-sig drops the invisible byte-order mark that starts product_category_name_translation.csv;
    # otherwise BigQuery sees the mark as part of the first column name and rejects it as invalid.
    with table.files()[0].open(encoding="utf-8-sig", newline="") as file:
        return next(csv.reader(file))


def csv_job_config(columns: list[str]) -> bigquery.LoadJobConfig:
    return bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        schema=[bigquery.SchemaField(column, "STRING") for column in columns],
        skip_leading_rows=1,
        allow_quoted_newlines=True,  # review comments contain line breaks inside quotes
        encoding="UTF-8",
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )


def ndjson_job_config() -> bigquery.LoadJobConfig:
    # API data was validated in Python before landing; BigQuery detects the types (dates, arrays).
    return bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )


def combined_ndjson(table: RawTable) -> io.BytesIO:
    """Several NDJSON files (e.g. one per state) become one upload, so the table is replaced in one job."""
    buffer = io.BytesIO()
    for path in table.files():
        content = path.read_bytes()
        buffer.write(content if content.endswith(b"\n") else content + b"\n")
    buffer.seek(0)
    return buffer


def upload(client: bigquery.Client, table: RawTable, table_id: str) -> None:
    """One attempt: replace the table with the file's contents (WRITE_TRUNCATE, all or nothing)."""
    if table.file_format == "csv":
        with table.files()[0].open("rb") as file:
            client.load_table_from_file(file, table_id, job_config=csv_job_config(csv_header(table))).result()
    else:
        client.load_table_from_file(combined_ndjson(table), table_id, job_config=ndjson_job_config()).result()


def upload_with_retries(
    client: bigquery.Client,
    table: RawTable,
    table_id: str,
    attempts: int = UPLOAD_ATTEMPTS,
    pause_seconds: float = PAUSE_BETWEEN_ATTEMPTS_SECONDS,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            upload(client, table, table_id)
            return
        except RETRYABLE_ERRORS as error:
            if attempt == attempts:
                raise
            logger.warning(
                "%s: upload failed (%s); trying again in %ss (attempt %d of %d)",
                table.name, type(error).__name__, pause_seconds, attempt + 1, attempts,
            )  # fmt: skip
            time.sleep(pause_seconds)


def extend_expiry(client: bigquery.Client, table_id: str, keep_for_ms: int | None) -> None:
    """In the sandbox, a table expires a fixed time after it was created, and replacing its contents
    does not change that. So after each load, set the expiry to (almost) the maximum again."""
    if not keep_for_ms:
        return  # a dataset without default expiry (billing enabled): tables never expire, nothing to do
    bq_table = client.get_table(table_id)
    bq_table.expires = datetime.now(UTC) + timedelta(milliseconds=keep_for_ms) - timedelta(days=1)
    client.update_table(bq_table, ["expires"])


def load_table(client: bigquery.Client, table: RawTable, dataset_id: str, keep_for_ms: int | None = None) -> int:
    table_id = f"{dataset_id}.{table.name}"
    upload_with_retries(client, table, table_id)
    extend_expiry(client, table_id, keep_for_ms)

    loaded = client.get_table(table_id).num_rows
    expected = table.source_row_count()
    if loaded != expected:
        raise ValueError(f"{table.name}: loaded {loaded:,} rows but the source files hold {expected:,}")
    return loaded


def run(project: str, location: str) -> None:
    client = bigquery.Client(project=project, location=location)
    dataset = bigquery.Dataset(f"{project}.{RAW_SCHEMA}")
    dataset.location = location
    dataset = client.create_dataset(dataset, exists_ok=True)
    keep_for_ms = client.get_dataset(dataset.reference).default_table_expiration_ms
    for table in RAW_TABLES:
        rows = load_table(client, table, dataset.dataset_id, keep_for_ms)
        logger.info("%s.%-28s %10s rows (matches source files)", RAW_SCHEMA, table.name, f"{rows:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load data/raw into BigQuery dataset `raw`.")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"), help="Google Cloud project ID.")
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", DEFAULT_LOCATION))
    args = parser.parse_args()
    if not args.project:
        parser.error("Set GCP_PROJECT_ID or pass --project (see the instructions at the top of this file).")
    configure_logging()
    run(args.project, args.location)


if __name__ == "__main__":
    main()
