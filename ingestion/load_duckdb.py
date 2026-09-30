"""Load every landed file into the local DuckDB warehouse (schema `raw`), unchanged.

DuckDB is the development stand-in for BigQuery: a database in a single file that
needs no account or server. The same dbt models run on both (see dbt/profiles.yml).

CSV columns are loaded as text on purpose. The raw layer stores exactly what the
source sent; converting to numbers and dates happens in the dbt staging models,
where a failed conversion is visible and tested instead of silently guessed.

Run from the project root:
    uv run python -m ingestion.load_duckdb
"""

from __future__ import annotations

import logging

import duckdb

from ingestion.config import WAREHOUSE_PATH
from ingestion.landing import configure_logging
from ingestion.sources import RAW_SCHEMA, RAW_TABLES, RawTable

logger = logging.getLogger(__name__)


def load_table(con: duckdb.DuckDBPyConnection, table: RawTable) -> int:
    paths = [path.as_posix() for path in table.files()]
    if table.file_format == "csv":
        reader = "read_csv(?, header = true, all_varchar = true, quote = '\"', escape = '\"')"
    else:
        reader = "read_json(?, format = 'newline_delimited', sample_size = -1)"
    con.execute(f"create or replace table {RAW_SCHEMA}.{table.name} as select * from {reader}", [paths])
    loaded = con.execute(f"select count(*) from {RAW_SCHEMA}.{table.name}").fetchone()[0]

    expected = table.source_row_count()
    if loaded != expected:
        raise ValueError(f"{table.name}: loaded {loaded:,} rows but the source files hold {expected:,}")
    return loaded


def run() -> None:
    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(WAREHOUSE_PATH)) as con:
        con.execute(f"create schema if not exists {RAW_SCHEMA}")
        for table in RAW_TABLES:
            rows = load_table(con, table)
            logger.info("%s.%-28s %10s rows (matches source files)", RAW_SCHEMA, table.name, f"{rows:,}")


def main() -> None:
    configure_logging()
    run()


if __name__ == "__main__":
    main()
