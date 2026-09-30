"""Download the Olist Brazilian e-commerce dataset from Kaggle and unpack it into the raw landing zone.

Kaggle serves public datasets without a login at the URL in config.py. The files are
unpacked unchanged and a manifest records each file's size, row count and SHA-256
hash, so a later run (or a reviewer) can prove the inputs did not change.

Run from the project root:
    uv run python -m ingestion.olist           # download only if the zip is missing
    uv run python -m ingestion.olist --force   # download again

Output: data/raw/olist/*.csv and data/raw/olist/_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import zipfile
from pathlib import Path

from ingestion.config import OLIST_DOWNLOAD_URL, PROJECT_ROOT, RAW_DATA_DIR
from ingestion.http_client import DEFAULT_TIMEOUT_SECONDS, build_session
from ingestion.landing import configure_logging, utc_now_iso

logger = logging.getLogger(__name__)

OUTPUT_DIR = RAW_DATA_DIR / "olist"
ZIP_PATH = OUTPUT_DIR / "brazilian-ecommerce.zip"
MANIFEST_PATH = OUTPUT_DIR / "_manifest.json"

# The nine files the pipeline depends on. If Kaggle ever renames or drops one, the run stops here.
EXPECTED_FILES = {
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
}


def download(url: str, destination: Path) -> None:
    """Stream the zip to disk in chunks (about 45 MB), via a temp file so a broken download never looks complete."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(".part")
    with build_session() as session, session.get(url, timeout=DEFAULT_TIMEOUT_SECONDS, stream=True) as response:
        response.raise_for_status()
        with temp_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1 << 20):
                file.write(chunk)
    temp_path.replace(destination)


def check_archive(zip_path: Path) -> list[str]:
    """Return the CSV names in the zip, failing if any expected file is missing."""
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".csv"))
    missing = EXPECTED_FILES - set(names)
    if missing:
        raise ValueError(f"Olist archive is missing {sorted(missing)}; found {names}")
    return names


def count_data_rows(path: Path) -> int:
    """Count records with a real CSV parser: review comments contain line breaks, so counting lines would be wrong."""
    with path.open(encoding="utf-8", newline="") as file:
        return sum(1 for _ in csv.reader(file)) - 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(force: bool = False) -> dict:
    if force or not ZIP_PATH.exists():
        logger.info("Downloading %s", OLIST_DOWNLOAD_URL)
        download(OLIST_DOWNLOAD_URL, ZIP_PATH)
    else:
        logger.info("Using existing %s (pass --force to download again)", ZIP_PATH.relative_to(PROJECT_ROOT))

    names = check_archive(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        archive.extractall(OUTPUT_DIR, members=names)

    manifest = {
        "source_url": OLIST_DOWNLOAD_URL,
        "ingested_at": utc_now_iso(),
        "zip_sha256": sha256(ZIP_PATH),
        "files": {
            name: {
                "bytes": (OUTPUT_DIR / name).stat().st_size,
                "rows": count_data_rows(OUTPUT_DIR / name),
                "sha256": sha256(OUTPUT_DIR / name),
            }
            for name in names
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name, info in manifest["files"].items():
        logger.info("%-40s %10s rows", name, f"{info['rows']:,}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and unpack the Olist dataset.")
    parser.add_argument("--force", action="store_true", help="Download again even if the zip exists.")
    args = parser.parse_args()
    configure_logging()
    run(force=args.force)


if __name__ == "__main__":
    main()
