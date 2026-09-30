"""Helpers every extractor uses to land data in data/raw the same way."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path


def utc_now_iso() -> str:
    """One timestamp per run, so every record from the same run shares the same `_ingested_at`."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def add_lineage(records: list[dict], source_url: str, ingested_at: str) -> list[dict]:
    """Stamp every record with where and when it was fetched, so any row can be traced back."""
    return [{**record, "_source_url": source_url, "_ingested_at": ingested_at} for record in records]


def write_ndjson(records: list[dict], path: Path) -> None:
    """Write one JSON record per line, via a temp file and rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
