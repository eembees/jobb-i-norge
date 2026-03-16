"""
build_site_data.py — Merge occupations.csv (and optional scores.json) → site/data.json.

Output format: JSON array, one object per occupation.
"""

import json
import math
import os

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SITE_DIR = os.path.join(os.path.dirname(__file__), "site")

OCCUPATIONS_CSV = os.path.join(DATA_DIR, "occupations.csv")
SCORES_JSON = os.path.join(DATA_DIR, "scores.json")
OUTPUT_JSON = os.path.join(SITE_DIR, "data.json")


def load_scores() -> dict[str, dict]:
    if not os.path.exists(SCORES_JSON):
        return {}
    with open(SCORES_JSON, encoding="utf-8") as f:
        return json.load(f)


def clean_value(v):
    """Convert NaN/None/inf to None for JSON serialisation."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def main() -> None:
    print("Loading occupations.csv...")
    df = pd.read_csv(OCCUPATIONS_CSV, dtype={"styrk_code": str, "major_group": str})

    scores = load_scores()
    has_scores = bool(scores)
    if has_scores:
        print(f"Loading scores.json ({len(scores)} entries)...")

    records = []
    for _, row in df.iterrows():
        code = str(row["styrk_code"])
        rec: dict = {
            "code": code,
            "name": row.get("name_en") or row.get("name_no") or code,
            "name_no": row.get("name_no") or "",
            "major_group": int(row["major_group"]) if pd.notna(row["major_group"]) else None,
            "major_group_name": clean_value(row.get("major_group_name")),
            "employed": int(row["employed"]) if pd.notna(row.get("employed")) else None,
            "pct_female": round(float(row["pct_female"]), 4) if pd.notna(row.get("pct_female")) else None,
            "median_monthly_wage": int(row["median_monthly_wage"]) if pd.notna(row.get("median_monthly_wage")) else None,
            "pct_public_sector": round(float(row["pct_public_sector"]), 4) if pd.notna(row.get("pct_public_sector")) else None,
            "edu_level_mode": clean_value(row.get("edu_level_mode")),
        }

        if has_scores and code in scores:
            entry = scores[code]
            rec["ai_score"] = round(float(entry.get("score", 0)), 2)
            rec["ai_rationale"] = entry.get("rationale", "")

        records.append(rec)

    os.makedirs(SITE_DIR, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {len(records)} records to {OUTPUT_JSON}")
    if records:
        print("Sample:", json.dumps(records[0], indent=2))


if __name__ == "__main__":
    main()
