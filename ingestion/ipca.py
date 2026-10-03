"""Extract Brazil's monthly consumer price inflation (IPCA) from the Banco Central do Brasil API.

Why: the simulated live orders copy real 2017-2018 baskets. Selling them at 2017 prices in 2026
would be unrealistic (Brazilian prices rose about 55% since January 2018), so the simulator
scales each price by the official inflation index between the original month and today.

If the Banco Central API cannot be reached, the same index is taken from IBGE, which compiles it.
If both are down, the saved file is kept: IPCA changes once a month, so yesterday's copy is still
right for today's orders, as long as it is not older than MAX_STALENESS_MONTHS.

Run from the project root:
    uv run python -m ingestion.ipca

Output: data/raw/ipca/ipca_BR.ndjson, one month per line: {"month": "2026-08", "pct_change": -0.32}
plus lineage fields (the URL shows which source was used). The API returns dates as "01/08/2026"
and numbers as text; both are kept readable here, and the record stays one-to-one with the API's rows.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

import requests

from ingestion.config import ANALYSIS_START_DATE, BCB_SGS_URL, IBGE_SIDRA_IPCA_URL, PROJECT_ROOT, RAW_DATA_DIR
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


def fetch_ipca_ibge(session: requests.Session, start: date, end: date) -> tuple[object, str]:
    """Backup source. Months not yet published are simply left out of IBGE's answer."""
    url = f"{IBGE_SIDRA_IPCA_URL}/{start:%Y%m}-{end:%Y%m}"
    response = session.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return ibge_to_bcb_rows(response.json()), url


def ibge_to_bcb_rows(payload: object) -> list[dict]:
    """Turn IBGE's rows {"D3C": "202608", "V": "-0.32"} (after one header row) into BCB's layout."""
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError(f"Unexpected IBGE response: {str(payload)[:200]}")
    return [{"data": f"01/{row['D3C'][4:]}/{row['D3C'][:4]}", "valor": row["V"]} for row in payload[1:]]


def month_index(month: str) -> int:
    year, number = month.split("-")
    return int(year) * 12 + int(number) - 1


def months_old(month: str, today: date) -> int:
    return today.year * 12 + today.month - 1 - month_index(month)


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
    if months_old(records[-1]["month"], today) > MAX_STALENESS_MONTHS:
        raise ValueError(f"Latest IPCA month {records[-1]['month']} is older than {MAX_STALENESS_MONTHS} months")
    return records


def keep_saved_file(today: date) -> int:
    """Both sources failed: keep the last saved series if it is recent enough, otherwise stop."""
    if not OUTPUT_PATH.exists():
        raise RuntimeError("IPCA: both sources failed and there is no saved file to fall back on")
    records = [json.loads(line) for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines()]
    latest = records[-1]["month"]
    if months_old(latest, today) > MAX_STALENESS_MONTHS:
        raise RuntimeError(f"IPCA: both sources failed and the saved series ends in {latest}, too old to use")
    logger.warning(
        "IPCA: both sources failed; keeping the saved file (%d months up to %s, fetched %s)",
        len(records),
        latest,
        records[-1].get("_ingested_at", "unknown"),
    )
    return len(records)


def run(start: date = SERIES_START, today: date | None = None) -> int:
    today = today or date.today()
    sources = (("Banco Central do Brasil", fetch_ipca), ("IBGE", fetch_ipca_ibge))
    with build_session() as session:
        for name, fetch in sources:
            try:
                payload, url = fetch(session, start, today)
                records = to_records(payload, today)
                break
            except (requests.RequestException, ValueError, KeyError) as error:
                logger.warning("IPCA from %s failed: %s", name, error)
        else:
            return keep_saved_file(today)
    write_ndjson(add_lineage(records, url, utc_now_iso()), OUTPUT_PATH)
    logger.info(
        "IPCA from %s: %d months %s..%s -> %s",
        name,
        len(records),
        records[0]["month"],
        records[-1]["month"],
        OUTPUT_PATH.relative_to(PROJECT_ROOT),
    )
    return len(records)


def main() -> None:
    argparse.ArgumentParser(
        description="Land monthly IPCA inflation from Banco Central do Brasil (IBGE as backup) as NDJSON."
    ).parse_args()
    configure_logging()
    run()


if __name__ == "__main__":
    main()
