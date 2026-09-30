# Local data folder

Everything in `data/` except this file is git-ignored: `run_pipeline.py` rebuilds it from the sources.
The Olist data is about 126 MB unpacked, and the API data can be fetched again in about a minute.

```
data/
├── raw/                    # landing zone: files exactly as the sources sent them
│   ├── olist/              # 9 CSVs from Kaggle + _manifest.json (sizes, row counts, SHA-256 hashes)
│   ├── holidays/           # Nager.Date, one NDJSON file per year
│   ├── weather/            # Open-Meteo, one NDJSON file per state capital (weather_live_*: recent days)
│   ├── fx/                 # ECB EUR/BRL reference rates via Frankfurter, 2016 to today
│   ├── ipca/               # Brazil's monthly inflation (Banco Central do Brasil)
│   └── sim/                # SYNTHETIC: simulated live orders in the Olist format (simulator/run.py)
├── sim/                    # simulator cache (order templates) and run_log.csv (one line per run)
└── warehouse/
    └── delivery_risk.duckdb   # local warehouse: raw, staging, intermediate and marts schemas
```

Raw files are never edited by hand. All cleaning happens in SQL (dbt), where it is versioned and tested.

Olist data: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce),
licence CC BY-NC-SA 4.0 (non-commercial use with attribution).
