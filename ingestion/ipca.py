"""Extract Brazil's monthly consumer price inflation (IPCA) from the Banco Central do Brasil API.

Why: the simulated live orders copy real 2017-2018 baskets. Selling them at 2017 prices in 2026
would be unrealistic (Brazilian prices rose about 55% since January 2018), so the simulator
scales each price by the official inflation index between the original month and today.

Run from the project root:
    uv run python -m ingestion.ipca

Output: data/raw/ipca/ipca_BR.ndjson, one month per line: {"month": "2026-08", "pct_change": -0.32}
plus lineage fields. The API returns dates as "01/08/2026" and numbers as text; both are kept
readable here, and the record stays one-to-one with the API's rows.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import requests

from ingestion.config import ANALYSIS_START_DATE, BCB_SGS_URL, PROJECT_ROOT, RAW_DATA_DIR
from ingestion.http_client import DEFAULT_TIMEOUT_SECONDS, build_session
from ingestion.landing import add_lineage, configure_logging, utc_now_iso, write_ndjson

logger = logging.getLogger(__name__)

OUTPUT_PATH = RAW_DATA_DIR / "ipca" / "ipca_BR.ndjson"
# Monthly IPCA has stayed between -0.7% and +1.7% since 2016. Anything far outside means a broken response.
PLAUSIBLE_PCT = (-3.0, 5.0)
# IPCA for a month is published around the 10th of the next month, so the latest month is at most ~2 months old.
MAX_STALENESS_MONTHS = 3
# From the start of the first year of the analysis window; the simulator's templates go back to 2017.
SERIES_START = ANALYSIS_START_DATE.replace(month=1, day=1)


def fetch_ipca(session: requests.Session, start: date, end: date) -> tuple[object, str]:
    params = {"formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": end.strftime("%d/%m/%Y")}
    response = session.get(BCB_SGS_URL, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json(), response.url


def month_index(month: str) -> int:
    year, number = month.split("-")
    return int(year) * 12 + int(number) - 1


def to_records(payload: object, today: date) -> list[dict]:
    """Turn [{"data": "01/08/2026", "valor": "-0.32"}] into [{"month": "2026-08", "pct_change": -0.32}] and check it."""
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Unexpected BCB response: {str(payload)[:200]}")
    records = []
    for row in payload:
        day, month, year = row["data"].split("/")
        value = float(str(row["valor"]).replace(",", "."))
        if not PLAUSIBLE_PCT[0] <= value <= PLAUSIBLE_PCT[1]:
            raise ValueError(f"Implausible monthly IPCA {value}% for {month}/{year}")
        records.append({"month": f"{year}-{month}", "pct_change": value})

    months = [month_index(record["month"]) for record in records]
    gaps = [(a, b) for a, b in zip(months, months[1:], strict=False) if b != a + 1]
    if gaps:
        raise ValueError(f"Missing months in the IPCA series: {gaps[:3]}")
    if today.year * 12 + today.month - 1 - months[-1] > MAX_STALENESS_MONTHS:
        raise ValueError(f"Latest IPCA month {records[-1]['month']} is older than {MAX_STALENESS_MONTHS} months")
    return records


def run(start: date = SERIES_START, today: date | None = None) -> int:
    today = today or date.today()
    with build_session() as session:
        payload, url = fetch_ipca(session, start, today)
    records = to_records(payload, today)
    write_ndjson(add_lineage(records, url, utc_now_iso()), OUTPUT_PATH)
    logger.info(
        "IPCA: %d months %s..%s -> %s",
        len(records),
        records[0]["month"],
        records[-1]["month"],
        OUTPUT_PATH.relative_to(PROJECT_ROOT),
    )
    return len(records)


def main() -> None:
    argparse.ArgumentParser(
        description="Land monthly IPCA inflation from Banco Central do Brasil as NDJSON."
    ).parse_args()
    configure_logging()
    run()


if __name__ == "__main__":
    main()
