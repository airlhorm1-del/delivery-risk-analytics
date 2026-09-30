"""Unit tests for the FX and weather extractors and the loaders' shared pieces. All offline."""

import json
from datetime import date

import pytest

from ingestion import fx, weather
from ingestion.load_bigquery import combined_ndjson, csv_job_config, ndjson_job_config
from ingestion.sources import RAW_TABLES, RawTable

# ---------- FX ----------


def fx_payload(rates: dict) -> dict:
    return {"amount": 1.0, "base": "EUR", "rates": {day: {"BRL": rate} for day, rate in rates.items()}}


def test_fx_records_keep_the_published_rate():
    records = fx.to_records(
        fx_payload({"2017-01-02": 3.4305, "2017-01-03": 3.4412}), date(2017, 1, 2), date(2017, 1, 3)
    )
    assert records == [
        {"date": "2017-01-02", "base": "EUR", "quote": "BRL", "rate": 3.4305},
        {"date": "2017-01-03", "base": "EUR", "quote": "BRL", "rate": 3.4412},
    ]


def test_fx_rejects_implausible_rate():
    with pytest.raises(ValueError, match="Implausible"):
        fx.to_records(fx_payload({"2017-01-02": 34.305}), date(2017, 1, 2), date(2017, 1, 2))


def test_fx_rejects_gap_longer_than_a_holiday_break():
    with pytest.raises(ValueError, match="Gaps"):
        fx.to_records(fx_payload({"2017-01-02": 3.4, "2017-01-20": 3.5}), date(2017, 1, 2), date(2017, 1, 20))


def test_fx_rejects_wrong_base_currency():
    with pytest.raises(ValueError, match="Unexpected"):
        fx.to_records({"base": "USD", "rates": {"2017-01-02": {"BRL": 3.2}}}, date(2017, 1, 2), date(2017, 1, 2))


# ---------- Weather ----------


def weather_payload(days: list[str], rain: list) -> dict:
    return {
        "latitude": -23.5,
        "longitude": -46.6,
        "timezone": "America/Sao_Paulo",
        "daily": {
            "time": days,
            "precipitation_sum": rain,
            "temperature_2m_max": [30.0] * len(days),
            "temperature_2m_min": [20.0] * len(days),
        },
    }


def test_weather_columns_become_one_row_per_day():
    payload = weather_payload(["2017-01-01", "2017-01-02"], [2.0, 25.5])
    records = weather.to_records(payload, "SP", date(2017, 1, 1), date(2017, 1, 2))
    assert len(records) == 2
    assert records[1] == {
        "state_code": "SP",
        "grid_latitude": -23.5,
        "grid_longitude": -46.6,
        "timezone": "America/Sao_Paulo",
        "time": "2017-01-02",
        "precipitation_sum": 25.5,
        "temperature_2m_max": 30.0,
        "temperature_2m_min": 20.0,
    }


def test_weather_rejects_missing_day():
    payload = weather_payload(["2017-01-01"], [2.0])
    with pytest.raises(ValueError, match="expected 2"):
        weather.to_records(payload, "SP", date(2017, 1, 1), date(2017, 1, 2))


def test_weather_rejects_variable_with_wrong_length():
    payload = weather_payload(["2017-01-01", "2017-01-02"], [2.0])
    with pytest.raises(ValueError, match="precipitation_sum"):
        weather.to_records(payload, "SP", date(2017, 1, 1), date(2017, 1, 2))


def test_every_state_has_capital_coordinates():
    states = weather.load_states()
    assert len(states) == 27
    for state in states:
        assert -34 < float(state["capital_latitude"]) < 6
        assert -74 < float(state["capital_longitude"]) < -34


# ---------- Loaders ----------


def test_raw_table_names_are_unique():
    names = [table.name for table in RAW_TABLES]
    assert len(names) == len(set(names))


def test_row_count_uses_a_real_csv_parser(tmp_path):
    (tmp_path / "reviews.csv").write_text('id,comment\n1,"line one\nline two"\n2,short\n', encoding="utf-8")
    assert RawTable("reviews", "reviews.csv", "csv").source_row_count(tmp_path) == 2


def test_bigquery_csv_config_loads_every_column_as_text():
    config = csv_job_config(["order_id", "price"])
    assert [(field.name, field.field_type) for field in config.schema] == [("order_id", "STRING"), ("price", "STRING")]
    assert config.skip_leading_rows == 1
    assert config.allow_quoted_newlines is True
    assert config.write_disposition == "WRITE_TRUNCATE"


def test_bigquery_ndjson_config_replaces_the_table():
    config = ndjson_job_config()
    assert config.autodetect is True
    assert config.write_disposition == "WRITE_TRUNCATE"


def test_several_ndjson_files_are_combined_into_one_upload(tmp_path, monkeypatch):
    (tmp_path / "weather_AC.ndjson").write_text('{"state_code": "AC"}\n', encoding="utf-8")
    (tmp_path / "weather_AL.ndjson").write_text('{"state_code": "AL"}', encoding="utf-8")  # no trailing newline
    table = RawTable("weather_daily", "weather_*.ndjson", "ndjson")
    monkeypatch.setattr(RawTable, "files", lambda self, raw_dir=tmp_path: sorted(tmp_path.glob(self.pattern)))
    lines = combined_ndjson(table).read().decode("utf-8").splitlines()
    assert [json.loads(line)["state_code"] for line in lines] == ["AC", "AL"]
