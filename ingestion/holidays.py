"""Extract Brazilian public holidays from the Nager.Date API into the raw landing zone.

Why holidays: Olist promises delivery in calendar days, but carriers and banks
stop on holidays. A national or state holiday inside the delivery window removes
a working day, and bank holidays (e.g. Carnival) also pause boleto payment
clearing, which delays order approval. Joining holidays to orders lets us test
how much of the lateness they explain.

Run from the project root:
    uv run python -m ingestion.holidays              # 2016-2018 plus this year and next (simulated orders)
    uv run python -m ingestion.holidays --live       # this year and next only
    uv run python -m ingestion.holidays --years 2017

Output: one newline-delimited JSON (NDJSON) file per year in data/raw/holidays/,
one holiday per line, exactly as the API returned it plus two lineage fields
(_source_url, _ingested_at). NDJSON is BigQuery's native load format and keeps
the nested `counties` list (the states a regional holiday applies to) intact.
Flattening happens later, in SQL.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import requests

from ingestion.config import (
    ANALYSIS_END_YEAR,
    ANALYSIS_START_YEAR,
    COUNTRY_CODE,
    NAGER_BASE_URL,
    PROJECT_ROOT,
    RAW_DATA_DIR,
)
from ingestion.http_client import DEFAULT_TIMEOUT_SECONDS, build_session
from ingestion.landing import add_lineage, configure_logging, utc_now_iso, write_ndjson

logger = logging.getLogger(__name__)

OUTPUT_DIR = RAW_DATA_DIR / "holidays"
REQUIRED_FIELDS = {"date", "localName", "name", "countryCode", "global", "counties", "types"}


def fetch_holidays(session: requests.Session, year: int, country_code: str) -> tuple[object, str]:
    """Call the API once and return the parsed JSON body with the URL it came from."""
    url = f"{NAGER_BASE_URL}/PublicHolidays/{year}/{country_code}"
    response = session.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json(), url


def validate_holidays(payload: object, year: int, country_code: str) -> list[dict]:
    """Fail loudly on an unexpected response instead of landing bad data in the warehouse."""
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Expected a non-empty list of holidays for {country_code} {year}, got: {payload!r:.200}")
    for holiday in payload:
        missing = REQUIRED_FIELDS - holiday.keys()
        if missing:
            raise ValueError(f"Holiday is missing fields {sorted(missing)}: {holiday}")
        if not holiday["date"].startswith(f"{year}-"):
            raise ValueError(f"Holiday dated outside {year}: {holiday}")
        if holiday["countryCode"] != country_code:
            raise ValueError(f"Holiday for the wrong country (expected {country_code}): {holiday}")
    return payload


def run(years: list[int], country_code: str) -> list[Path]:
    """Fetch, validate and land each year. Re-running overwrites the same files, so it is safe to repeat."""
    ingested_at = utc_now_iso()
    written = []
    with build_session() as session:
        for year in years:
            payload, url = fetch_holidays(session, year, country_code)
            holidays = validate_holidays(payload, year, country_code)
            path = OUTPUT_DIR / f"holidays_{country_code}_{year}.ndjson"
            write_ndjson(add_lineage(holidays, url, ingested_at), path)
            regional = sum(1 for holiday in holidays if holiday["counties"])
            logger.info(
                "%s %s: %d holidays (%d state-level) -> %s",
                country_code,
                year,
                len(holidays),
                regional,
                path.relative_to(PROJECT_ROOT),
            )
            written.append(path)
    return written


def default_years(live: bool = False, today: date | None = None) -> list[int]:
    """Historical years for the analysis, plus this year and next for the simulated live orders
    (next year because a promise made in December can end in January)."""
    today = today or date.today()
    live_years = [today.year, today.year + 1]
    if live:
        return live_years
    return sorted(set(range(ANALYSIS_START_YEAR, ANALYSIS_END_YEAR + 1)) | set(live_years))


def main() -> None:
    parser = argparse.ArgumentParser(description="Land public holidays from Nager.Date as NDJSON.")
    parser.add_argument(
        "--years", type=int, nargs="+", help="Years to fetch (default: analysis years + this year and next)."
    )
    parser.add_argument("--live", action="store_true", help="Only this year and next (for the simulated live orders).")
    parser.add_argument("--country", default=COUNTRY_CODE, help="ISO 3166-1 alpha-2 country code.")
    args = parser.parse_args()

    configure_logging()
    run(args.years or default_years(live=args.live), args.country.upper())


if __name__ == "__main__":
    main()
