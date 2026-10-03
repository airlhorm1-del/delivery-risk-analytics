"""Project-wide settings: paths, API endpoints, the analysis window and the simulator settings."""

from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse" / "delivery_risk.duckdb"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"

# One list of Brazil's 27 states and their capitals, shared by the weather extractor and dbt (as a seed).
BRAZIL_STATES_CSV = DBT_PROJECT_DIR / "seeds" / "brazil_states.csv"

# Olist orders run from Sep 2016 to Oct 2018, and promised delivery dates spill
# into late 2018, so every external source must cover this window.
ANALYSIS_START_DATE = date(2016, 9, 1)
ANALYSIS_END_DATE = date(2018, 12, 31)
ANALYSIS_START_YEAR = ANALYSIS_START_DATE.year
ANALYSIS_END_YEAR = ANALYSIS_END_DATE.year

COUNTRY_CODE = "BR"

OLIST_DOWNLOAD_URL = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
NAGER_BASE_URL = "https://date.nager.at/api/v3"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"
# Banco Central do Brasil time-series API; series 433 = IPCA, Brazil's official monthly consumer price inflation.
BCB_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"
# Backup for the same index from IBGE, which compiles IPCA (SIDRA table 1737, variable 63 = monthly change).
IBGE_SIDRA_IPCA_URL = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/63/p"

# ---------- Simulated live orders (synthetic) ----------
# The simulated shop runs on Brazilian time (Sao Paulo, UTC-3, no daylight saving since 2019).
SIM_TIMEZONE = "America/Sao_Paulo"
# First simulated day: 90 days before the first run on 30 Sep 2026, so the live view starts with
# orders that have already been delivered and reviewed.
SIM_START_DATE = date(2026, 7, 2)
# Live weather is fetched from a week before the first simulated order.
LIVE_WEATHER_START_DATE = SIM_START_DATE - timedelta(days=7)
SIM_DIR = PROJECT_ROOT / "data" / "sim"
SIM_RAW_DIR = RAW_DATA_DIR / "sim"
SIM_MODEL_PATH = PROJECT_ROOT / "simulator" / "model" / "sim_model.json"
