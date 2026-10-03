"""Unit tests for the FX, weather and IPCA extractors and the loaders' shared pieces. All offline."""

import json
from datetime import date

import pytest
import requests

from ingestion import fx, ipca, weather
from ingestion.load_bigquery import combined_ndjson, csv_header, csv_job_config, ndjson_job_config
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


# ---------- IPCA ----------


def test_ipca_from_ibge_gives_the_same_records_as_the_central_bank():
    ibge_payload = [
        {"D3C": "Mês (Código)", "V": "Valor"},
        {"D3C": "202607", "V": "0.07"},
        {"D3C": "202608", "V": "-0.32"},
    ]
    bcb_payload = [{"data": "01/07/2026", "valor": "0.07"}, {"data": "01/08/2026", "valor": "-0.32"}]
    today = date(2026, 10, 3)
    assert ipca.to_records(ipca.ibge_to_bcb_rows(ibge_payload), today) == ipca.to_records(bcb_payload, today)


def unreachable(session, start, end):
    raise requests.ConnectionError("Failed to resolve host")


def saved_series(path, last_month: str) -> str:
    text = json.dumps({"month": last_month, "pct_change": -0.32, "_ingested_at": "2026-10-02T18:40:29+00:00"}) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def test_ipca_uses_ibge_when_the_central_bank_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(ipca, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ipca, "OUTPUT_PATH", tmp_path / "ipca_BR.ndjson")
    monkeypatch.setattr(ipca, "fetch_ipca", unreachable)
    monkeypatch.setattr(
        ipca, "fetch_ipca_ibge", lambda session, start, end: ([{"data": "01/08/2026", "valor": "-0.32"}], "ibge-url")
    )
    assert ipca.run(date(2026, 8, 1), date(2026, 10, 3)) == 1
    assert json.loads((tmp_path / "ipca_BR.ndjson").read_text(encoding="utf-8"))["_source_url"] == "ibge-url"


def test_ipca_keeps_the_saved_file_when_both_sources_are_down(tmp_path, monkeypatch):
    path = tmp_path / "ipca_BR.ndjson"
    before = saved_series(path, "2026-08")
    monkeypatch.setattr(ipca, "OUTPUT_PATH", path)
    monkeypatch.setattr(ipca, "fetch_ipca", unreachable)
    monkeypatch.setattr(ipca, "fetch_ipca_ibge", unreachable)
    assert ipca.run(date(2026, 8, 1), date(2026, 10, 3)) == 1
    assert path.read_text(encoding="utf-8") == before


def test_ipca_stops_when_both_sources_are_down_and_the_saved_file_is_too_old(tmp_path, monkeypatch):
    path = tmp_path / "ipca_BR.ndjson"
    saved_series(path, "2026-05")
    monkeypatch.setattr(ipca, "OUTPUT_PATH", path)
    monkeypatch.setattr(ipca, "fetch_ipca", unreachable)
    monkeypatch.setattr(ipca, "fetch_ipca_ibge", unreachable)
    with pytest.raises(RuntimeError, match="too old"):
        ipca.run(date(2026, 1, 1), date(2026, 10, 3))


def test_ipca_stops_when_both_sources_are_down_and_nothing_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(ipca, "OUTPUT_PATH", tmp_path / "ipca_BR.ndjson")
    monkeypatch.setattr(ipca, "fetch_ipca", unreachable)
    monkeypatch.setattr(ipca, "fetch_ipca_ibge", unreachable)
    with pytest.raises(RuntimeError, match="no saved file"):
        ipca.run(date(2026, 8, 1), date(2026, 10, 3))


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


def test_csv_header_ignores_byte_order_mark(tmp_path, monkeypatch):
    byte_order_mark = b"\xef\xbb\xbf"
    content = b"product_category_name,product_category_name_english\nbeleza_saude,health_beauty\n"
    (tmp_path / "translation.csv").write_bytes(byte_order_mark + content)
    table = RawTable("olist_category_translation", "translation.csv", "csv")
    monkeypatch.setattr(RawTable, "files", lambda self, raw_dir=tmp_path: sorted(tmp_path.glob(self.pattern)))
    assert csv_header(table) == ["product_category_name", "product_category_name_english"]


# ---------- BigQuery upload retries ----------


class FlakyClient:
    """Fails the first `failures` uploads with the error BigQuery raised when the laptop slept mid-upload."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def load_table_from_file(self, file, table_id, job_config):
        self.calls += 1
        if self.calls <= self.failures:
            from google.api_core.exceptions import NotFound

            raise NotFound("upload session expired")

        class Job:
            def result(self):
                return None

        return Job()


def test_failed_upload_is_retried_then_succeeds(tmp_path, monkeypatch):
    from ingestion.load_bigquery import upload_with_retries

    (tmp_path / "fx.ndjson").write_text('{"rate": 5.9}\n', encoding="utf-8")
    table = RawTable("fx_rates", "fx.ndjson", "ndjson")
    monkeypatch.setattr(RawTable, "files", lambda self, raw_dir=tmp_path: sorted(tmp_path.glob(self.pattern)))
    client = FlakyClient(failures=2)
    upload_with_retries(client, table, "raw.fx_rates", attempts=3, pause_seconds=0)
    assert client.calls == 3


def test_upload_gives_up_after_the_last_attempt(tmp_path, monkeypatch):
    from google.api_core.exceptions import NotFound

    from ingestion.load_bigquery import upload_with_retries

    (tmp_path / "fx.ndjson").write_text('{"rate": 5.9}\n', encoding="utf-8")
    table = RawTable("fx_rates", "fx.ndjson", "ndjson")
    monkeypatch.setattr(RawTable, "files", lambda self, raw_dir=tmp_path: sorted(tmp_path.glob(self.pattern)))
    client = FlakyClient(failures=5)
    with pytest.raises(NotFound):
        upload_with_retries(client, table, "raw.fx_rates", attempts=3, pause_seconds=0)
    assert client.calls == 3


# ---------- BigQuery sandbox: re-create instead of overwrite ----------


class RecordingClient:
    """Records what the loader asks BigQuery to do, in order."""

    def __init__(self):
        self.steps = []

    def load_table_from_file(self, file, table_id, job_config):
        self.steps.append(("upload", table_id))
        return self

    def query(self, sql):
        self.steps.append(("query", sql))
        return self

    def delete_table(self, table_id, not_found_ok=False):
        self.steps.append(("delete", table_id))

    def result(self):
        return None


def test_sandbox_table_is_recreated_from_a_side_table(tmp_path, monkeypatch):
    from ingestion.load_bigquery import recreate_from_upload

    (tmp_path / "fx.ndjson").write_text('{"rate": 5.9}\n', encoding="utf-8")
    table = RawTable("fx_rates", "fx.ndjson", "ndjson")
    monkeypatch.setattr(RawTable, "files", lambda self, raw_dir=tmp_path: sorted(tmp_path.glob(self.pattern)))
    client = RecordingClient()
    recreate_from_upload(client, table, "raw.fx_rates")
    assert client.steps == [
        ("upload", "raw._reload_fx_rates"),
        ("query", "CREATE OR REPLACE TABLE `raw.fx_rates` AS SELECT * FROM `raw._reload_fx_rates`"),
        ("delete", "raw._reload_fx_rates"),
    ]
