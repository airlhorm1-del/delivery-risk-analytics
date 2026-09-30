"""Extract daily historical weather for Brazil's 27 state capitals from the Open-Meteo archive API.

Why: heavy rain slows road transport. Joining the weather at the customer's state
capital to each order's delivery window lets us test whether rain explains late
deliveries. The capital stands in for the whole state (a trade-off: one call per
state instead of one per city; see docs/decisions.md).

Run from the project root:
    uv run python -m ingestion.weather              # historical window 2016-2018
    uv run python -m ingestion.weather --live       # recent weather for the simulated live orders
    uv run python -m ingestion.weather --states SP RJ

Output: one NDJSON file per state in data/raw/weather/ (weather_SP.ndjson; live: weather_live_SP.ndjson),
one day per line. The most recent days can still be empty in the archive; in live mode those
trailing empty days are left out and arrive on a later run. The API
returns columns ({"time": [...], "precipitation_sum": [...]}); we reshape them into
rows but keep the API's own field names and units. Renaming happens in SQL.
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import date, timedelta

import requests

from ingestion.config import (
    ANALYSIS_END_DATE,
    ANALYSIS_START_DATE,
    BRAZIL_STATES_CSV,
    LIVE_WEATHER_START_DATE,
    OPEN_METEO_ARCHIVE_URL,
    PROJECT_ROOT,
    RAW_DATA_DIR,
)
from ingestion.http_client import DEFAULT_TIMEOUT_SECONDS, build_session
from ingestion.landing import add_lineage, configure_logging, utc_now_iso, write_ndjson

logger = logging.getLogger(__name__)

OUTPUT_DIR = RAW_DATA_DIR / "weather"
DAILY_VARIABLES = ["precipitation_sum", "temperature_2m_max", "temperature_2m_min"]
# Open-Meteo's free tier allows 600 calls a minute, and a long date range counts as several calls.
# A short pause between states keeps the whole run well inside that limit.
PAUSE_BETWEEN_CALLS_SECONDS = 2.0
# In live mode, how many days the archive may trail behind yesterday before we give up.
MAX_ARCHIVE_LAG_DAYS = 5


def load_states() -> list[dict]:
    with BRAZIL_STATES_CSV.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def fetch_weather(
    session: requests.Session, latitude: float, longitude: float, start: date, end: date
) -> tuple[dict, str]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "auto",  # days follow the local clock at each capital (Brazil spans four time zones)
    }
    response = session.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json(), response.url


def to_records(payload: dict, state_code: str, start: date, end: date) -> list[dict]:
    """Reshape the column arrays into one record per day, checking every day of the window is present."""
    daily = payload.get("daily")
    if not isinstance(daily, dict) or "time" not in daily:
        raise ValueError(f"Unexpected Open-Meteo response for {state_code}: {str(payload)[:200]}")

    expected_days = [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]
    if daily["time"] != expected_days:
        raise ValueError(f"{state_code}: got {len(daily['time'])} days, expected {len(expected_days)} ({start}..{end})")
    for variable in DAILY_VARIABLES:
        if len(daily.get(variable) or []) != len(expected_days):
            raise ValueError(f"{state_code}: '{variable}' does not have one value per day")

    location = {
        "state_code": state_code,
        "grid_latitude": payload.get("latitude"),
        "grid_longitude": payload.get("longitude"),
        "timezone": payload.get("timezone"),
    }
    return [
        {**location, "time": day, **{variable: daily[variable][index] for variable in DAILY_VARIABLES}}
        for index, day in enumerate(daily["time"])
    ]


def drop_trailing_empty_days(records: list[dict]) -> list[dict]:
    """The archive publishes the last few days with a short delay; stop at the last day that has rain data."""
    while records and records[-1]["precipitation_sum"] is None:
        records = records[:-1]
    return records


def run(
    state_codes: list[str] | None = None,
    start: date = ANALYSIS_START_DATE,
    end: date = ANALYSIS_END_DATE,
    live: bool = False,
) -> int:
    if live:
        # Yesterday is the latest complete day. The archive can lag a little more, so step back if it refuses.
        start, end = LIVE_WEATHER_START_DATE, date.today() - timedelta(days=1)
    states = [state for state in load_states() if not state_codes or state["state_code"] in state_codes]
    ingested_at = utc_now_iso()
    total = 0
    with build_session() as session:
        for position, state in enumerate(states):
            if position:
                time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
            code = state["state_code"]
            latitude, longitude = float(state["capital_latitude"]), float(state["capital_longitude"])
            for days_back in range(MAX_ARCHIVE_LAG_DAYS if live else 1):
                try:
                    payload, url = fetch_weather(session, latitude, longitude, start, end)
                    break
                except requests.HTTPError as error:
                    if (
                        not live
                        or error.response is None
                        or error.response.status_code != 400
                        or days_back == MAX_ARCHIVE_LAG_DAYS - 1
                    ):
                        raise
                    end -= timedelta(days=1)
                    logger.info("Archive has no data for %s yet; trying up to %s", end + timedelta(days=1), end)
            records = to_records(payload, code, start, end)
            if live:
                records = drop_trailing_empty_days(records)
            path = OUTPUT_DIR / f"weather_{'live_' if live else ''}{code}.ndjson"
            write_ndjson(add_lineage(records, url, ingested_at), path)
            missing_rain = sum(1 for record in records if record["precipitation_sum"] is None)
            logger.info(
                "%s (%s): %d days, %d without rain data -> %s",
                code,
                state["capital"],
                len(records),
                missing_rain,
                path.relative_to(PROJECT_ROOT),
            )
            total += len(records)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Land daily weather for Brazil's state capitals as NDJSON.")
    parser.add_argument("--states", nargs="+", help="Two-letter state codes (default: all 27).")
    parser.add_argument("--live", action="store_true", help="Recent weather (for the simulated live orders).")
    args = parser.parse_args()
    configure_logging()
    run([code.upper() for code in args.states] if args.states else None, live=args.live)


if __name__ == "__main__":
    main()
