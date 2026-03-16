"""
fetch.py — Download raw data from SSB (Statistics Norway) API and KLASS classification.

Run once; re-run to refresh.
Output: data/raw/{occupations,wages,education}.json + data/raw/labels_no.json
"""

import json
import os
import sys

import requests

DATA_RAW = os.path.join(os.path.dirname(__file__), "data", "raw")

BASE = "https://data.ssb.no/api/pxwebapi/v2/tables/{id}/data"

TABLES = {
    "occupations": "13114",  # Employees by occupation (STYRK-08 4-digit)
    "wages": "11611",        # Monthly wages by occupation
    "education": "12629",    # Occupation × education level
}

# Query parameters shared by all tables
COMMON_PARAMS = {
    "lang": "en",
    "outputformat": "json-stat2",
    "valueCodes[Tid]": "top(1)",  # latest year only
}

# Per-table extra value codes to pull all occupation codes and other dimensions
TABLE_PARAMS: dict[str, dict] = {
    "occupations": {
        "valueCodes[Yrke]": "*",
        "valueCodes[Kjonn]": "*",
    },
    "wages": {
        "valueCodes[Yrke]": "*",
        "valueCodes[Sektor]": "*",
    },
    "education": {
        "valueCodes[Yrke]": "*",
        "valueCodes[Utdnivaa]": "*",
    },
}

KLASS_URL = (
    "https://data.ssb.no/api/klass/v1/classifications/7/codes"
    "?from=2024-01-01&language=nb"
)


def fetch_table(name: str, table_id: str) -> dict:
    url = BASE.format(id=table_id)
    params = {**COMMON_PARAMS, **TABLE_PARAMS.get(name, {})}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_klass() -> dict:
    resp = requests.get(KLASS_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  saved {path}")


def main() -> None:
    os.makedirs(DATA_RAW, exist_ok=True)

    for name, table_id in TABLES.items():
        print(f"Fetching table {table_id} ({name})...")
        data = fetch_table(name, table_id)
        save(data, os.path.join(DATA_RAW, f"{name}.json"))

    print("Fetching KLASS classification 7 (STYRK-08 labels)...")
    labels = fetch_klass()
    save(labels, os.path.join(DATA_RAW, "labels_no.json"))

    print("Done.")


if __name__ == "__main__":
    main()
