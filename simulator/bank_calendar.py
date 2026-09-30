"""Brazilian bank calendar and Black Friday: the real-world dates the simulator plays by."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from ingestion.config import RAW_DATA_DIR


def load_bank_holidays(raw_dir: Path = RAW_DATA_DIR) -> set[date]:
    """Nationwide days when banks are closed (public holidays and bank holidays such as Carnival).

    Boleto payments only clear on bank business days, so these decide when a boleto order is approved.
    """
    holidays = set()
    for path in sorted((raw_dir / "holidays").glob("holidays_BR_*.ndjson")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["global"] and {"Public", "Bank"} & set(record["types"]):
                holidays.add(date.fromisoformat(record["date"]))
    return holidays


def is_bank_day(day: date, bank_holidays: set[date]) -> bool:
    return day.isoweekday() <= 5 and day not in bank_holidays


def add_bank_days(day: date, bank_days: int, bank_holidays: set[date]) -> date:
    """The date `bank_days` bank business days after `day` (0 = the same day)."""
    current = day
    remaining = bank_days
    while remaining > 0:
        current += timedelta(days=1)
        if is_bank_day(current, bank_holidays):
            remaining -= 1
    return current


def bank_days_between(start: date, end: date, bank_holidays: set[date]) -> int:
    """Number of bank business days after `start` up to and including `end` (0 if the same day)."""
    return sum(
        1 for offset in range(1, (end - start).days + 1) if is_bank_day(start + timedelta(days=offset), bank_holidays)
    )


def black_friday(year: int) -> date:
    """The Friday after the fourth Thursday of November."""
    first = date(year, 11, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3, days=1)
