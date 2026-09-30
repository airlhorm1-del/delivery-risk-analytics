"""Unit tests for the holiday extractor. They use a canned payload, so they run offline."""

import json

import pytest

from ingestion.holidays import validate_holidays
from ingestion.landing import add_lineage, write_ndjson

SAO_PAULO_HOLIDAY = {
    "date": "2017-07-09",
    "localName": "Revolução Constitucionalista de 1932",
    "name": "Constitutionalist Revolution of 1932",
    "countryCode": "BR",
    "fixed": False,
    "global": False,
    "counties": ["BR-SP"],
    "launchYear": None,
    "types": ["Public"],
}


def test_valid_payload_passes():
    assert validate_holidays([SAO_PAULO_HOLIDAY], 2017, "BR") == [SAO_PAULO_HOLIDAY]


@pytest.mark.parametrize("payload", [[], {"error": "rate limited"}, None])
def test_empty_or_non_list_payload_is_rejected(payload):
    with pytest.raises(ValueError, match="non-empty list"):
        validate_holidays(payload, 2017, "BR")


def test_missing_field_is_rejected():
    broken = {key: value for key, value in SAO_PAULO_HOLIDAY.items() if key != "counties"}
    with pytest.raises(ValueError, match="missing fields"):
        validate_holidays([broken], 2017, "BR")


def test_holiday_from_another_year_is_rejected():
    with pytest.raises(ValueError, match="outside 2018"):
        validate_holidays([SAO_PAULO_HOLIDAY], 2018, "BR")


def test_holiday_from_another_country_is_rejected():
    with pytest.raises(ValueError, match="wrong country"):
        validate_holidays([SAO_PAULO_HOLIDAY], 2017, "DE")


def test_lineage_is_added_without_changing_source_fields():
    [record] = add_lineage([SAO_PAULO_HOLIDAY], "https://example.test/2017/BR", "2026-01-01T00:00:00+00:00")
    assert record["_source_url"] == "https://example.test/2017/BR"
    assert record["_ingested_at"] == "2026-01-01T00:00:00+00:00"
    assert {key: record[key] for key in SAO_PAULO_HOLIDAY} == SAO_PAULO_HOLIDAY


def test_ndjson_round_trip_keeps_accents_and_nested_lists(tmp_path):
    path = tmp_path / "holidays.ndjson"
    write_ndjson([SAO_PAULO_HOLIDAY, SAO_PAULO_HOLIDAY], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == SAO_PAULO_HOLIDAY
    assert "Revolução" in lines[0]
    assert not path.with_suffix(".tmp").exists()
