"""Extract daily EUR/BRL reference rates (European Central Bank) from the Frankfurter API.

Why: Olist prices are in Brazilian reais (BRL). The dashboard reports in euros for a
German audience, so each order is converted at the ECB rate of its purchase date.
The range runs from 2016 to today, so the simulated live orders get today's real rate too
(one call; the ECB publishes around 16:00 CET, so a morning run uses the previous day's rate).

We land the rate exactly as the ECB publishes it (1 EUR = x BRL, e.g. 3.4305) rather
than asking the API for the inverse, so the raw layer matches the official source.
The ECB publishes on working days only; weekends and holidays are filled in SQL by
carrying the last published rate forward.

Run from the project root:
    uv run python -m ingestion.fx

Output: data/raw/fx/fx_EUR_BRL.ndjson, one rate per line plus lineage fields.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import requests

from ingestion.config import ANALYSIS_START_DATE, FRANKFURTER_BASE_URL, PROJECT_ROOT, RAW_DATA_DIR
from ingestion.http_client import DEFAULT_TIMEOUT_SECONDS, build_session
from ingestion.landing import add_lineage, configure_logging, utc_now_iso, write_ndjson

logger = logging.getLogger(__name__)

OUTPUT_PATH = RAW_DATA_DIR / "fx" / "fx_EUR_BRL.ndjson"
BASE, QUOTE = "EUR", "BRL"
# EUR/BRL traded between about 3.0 and 6.5 from 2016 to 2026. A value far outside this means a broken response.
PLAUSIBLE_RATE = (2.0, 8.0)
# Longest normal gap between ECB publications (Christmas to the first working day of January).
MAX_GAP_DAYS = 5


def fetch_rates(session: requests.Session, start: date, end: date) -> tuple[dict, str]:
    url = f"{FRANKFURTER_BASE_URL}/{start.isoformat()}..{end.isoformat()}?base={BASE}&symbols={QUOTE}"
    response = session.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json(), url


def to_records(payload: dict, start: date, end: date) -> list[dict]:
    """Turn {"rates": {"2017-01-02": {"BRL": 3.4}}} into one record per day and check it."""
    if payload.get("base") != BASE or not isinstance(payload.get("rates"), dict) or not payload["rates"]:
        raise ValueError(f"Unexpected Frankfurter response: {str(payload)[:200]}")

    records = []
    for day, quotes in sorted(payload["rates"].items()):
        rate = quotes.get(QUOTE)
        if not isinstance(rate, (int, float)) or not PLAUSIBLE_RATE[0] <= rate <= PLAUSIBLE_RATE[1]:
            raise ValueError(f"Implausible {BASE}/{QUOTE} rate on {day}: {rate}")
        records.append({"date": day, "base": BASE, "quote": QUOTE, "rate": rate})

    days = [date.fromisoformat(record["date"]) for record in records]
    # The API also returns the last rate *before* the start date, which is useful for carrying forward.
    if days[0] > start or (end - days[-1]).days > MAX_GAP_DAYS:
        raise ValueError(f"Rates cover {days[0]}..{days[-1]}, expected {start}..{end}")
    gaps = [
        (earlier, later)
        for earlier, later in zip(days, days[1:], strict=False)
        if (later - earlier).days > MAX_GAP_DAYS
    ]
    if gaps:
        raise ValueError(f"Gaps longer than {MAX_GAP_DAYS} days between published rates: {gaps[:5]}")
    return records


def run(start: date = ANALYSIS_START_DATE, end: date | None = None) -> int:
    end = end or date.today()
    with build_session() as session:
        payload, url = fetch_rates(session, start, end)
    records = to_records(payload, start, end)
    write_ndjson(add_lineage(records, url, utc_now_iso()), OUTPUT_PATH)
    logger.info(
        "%s/%s: %d daily rates %s..%s -> %s",
        BASE,
        QUOTE,
        len(records),
        records[0]["date"],
        records[-1]["date"],
        OUTPUT_PATH.relative_to(PROJECT_ROOT),
    )
    return len(records)


def main() -> None:
    argparse.ArgumentParser(description="Land daily ECB EUR/BRL reference rates as NDJSON.").parse_args()
    configure_logging()
    run()


if __name__ == "__main__":
    main()
