"""Project-wide settings: paths, API endpoints and the analysis window."""

from datetime import date
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
