"""
process.py — Merge raw JSON-stat2 files into data/occupations.csv.

One row per 4-digit STYRK-08 occupation code.

Columns produced:
  styrk_code, name_en, name_no, major_group, major_group_name,
  employed, pct_female,
  median_monthly_wage, pct_public_sector, wage_precision,
  edu_level_mode
"""

import json
import os
from typing import Optional

import pandas as pd

DATA_RAW = os.path.join(os.path.dirname(__file__), "data", "raw")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_CSV = os.path.join(DATA_DIR, "occupations.csv")

MAJOR_GROUP_NAMES = {
    "1": "Managers",
    "2": "Professionals",
    "3": "Technicians and associate professionals",
    "4": "Clerical support workers",
    "5": "Service and sales workers",
    "6": "Skilled agricultural, forestry and fishery workers",
    "7": "Craft and related trades workers",
    "8": "Plant and machine operators and assemblers",
    "9": "Elementary occupations",
}

EDU_LEVEL_MAP = {
    "0": "no_formal",
    "1": "primary",
    "2": "lower_secondary",
    "3": "upper_secondary",
    "4": "post_secondary",
    "5": "bachelor",
    "6": "master",
    "7": "doctoral",
    "8": "unspecified",
    # SSB uses various codes — handle extras gracefully
}


def load_json(fname: str) -> dict:
    path = os.path.join(DATA_RAW, fname)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_jsonstat2(data: dict) -> pd.DataFrame:
    """
    Convert a JSON-stat2 response into a flat DataFrame.

    JSON-stat2 structure:
      data["dimension"] — ordered dict of dimension ids → {label, category: {index, label}}
      data["value"]     — flat array of values in row-major order
    """
    dims = data["dimension"]
    dim_ids = list(dims.keys())

    # Build a list of (id, [ordered_codes]) for each dimension
    dim_codes: list[tuple[str, list[str]]] = []
    for dim_id in dim_ids:
        cat = dims[dim_id]["category"]
        # index maps code → int position; invert to get ordered list
        index_map: dict[str, int] = cat["index"]
        ordered = sorted(index_map.keys(), key=lambda k: index_map[k])
        dim_codes.append((dim_id, ordered))

    # Compute total cells and validate
    total = 1
    for _, codes in dim_codes:
        total *= len(codes)

    values = data["value"]
    assert len(values) == total, f"Expected {total} values, got {len(values)}"

    # Build MultiIndex and flatten
    import itertools

    keys = [codes for _, codes in dim_codes]
    rows = []
    for i, combo in enumerate(itertools.product(*keys)):
        row: dict = {dim_id: combo[j] for j, (dim_id, _) in enumerate(dim_codes)}
        row["value"] = values[i]
        rows.append(row)

    df = pd.DataFrame(rows)
    # Add human-readable labels for each dimension
    for dim_id, _ in dim_codes:
        label_map: dict[str, str] = dims[dim_id]["category"].get("label", {})
        if label_map:
            df[f"{dim_id}_label"] = df[dim_id].map(label_map)
    return df


def extract_labels(labels_data: dict) -> tuple[dict[str, str], dict[str, str]]:
    """
    Parse KLASS classification 7 response.
    Returns two dicts: {code: name_no} for 4-digit codes, {code: name_no} for 1-digit.
    """
    codes = labels_data.get("codes", [])
    four_digit: dict[str, str] = {}
    one_digit: dict[str, str] = {}
    for entry in codes:
        code = entry.get("code", "")
        name = entry.get("name", "")
        if len(code) == 4:
            four_digit[code] = name
        elif len(code) == 1:
            one_digit[code] = name
    return four_digit, one_digit


def build_occupations(occ_raw: dict) -> pd.DataFrame:
    """
    From table 13114 (employees by occupation), compute:
      styrk_code, employed, pct_female
    """
    df = parse_jsonstat2(occ_raw)

    # Identify the occupation and sex dimension ids
    # Typical ids: "Yrke", "Kjonn" (or similar)
    occ_col = _find_dim(df, ["Yrke", "yrke", "occupation"])
    sex_col = _find_dim(df, ["Kjonn", "kjonn", "sex", "Sex"])

    # Drop rows with null value (suppressed data)
    df = df.dropna(subset=["value"])
    df["value"] = df["value"].astype(float)

    # Filter to 4-digit occupation codes only
    df = df[df[occ_col].str.len() == 4].copy()

    # Identify sex codes: usually "0"=total, "1"=male, "2"=female
    sex_vals = df[sex_col].unique().tolist()

    # Determine which code means "total", "male", "female" from labels
    sex_label_col = f"{sex_col}_label"
    label_to_code = {}
    if sex_label_col in df.columns:
        for code in sex_vals:
            lbl = df.loc[df[sex_col] == code, sex_label_col].iloc[0].lower()
            label_to_code[lbl] = code

    total_code = _pick_code(label_to_code, sex_vals, ["both sexes", "total", "alle", "0"])
    female_code = _pick_code(label_to_code, sex_vals, ["females", "female", "kvinner", "2"])

    # Total employed per occupation
    total_df = df[df[sex_col] == total_code][[occ_col, "value"]].copy()
    total_df = total_df.rename(columns={occ_col: "styrk_code", "value": "employed"})
    total_df = total_df.groupby("styrk_code", as_index=False)["employed"].sum()

    # Female employed per occupation
    female_df = df[df[sex_col] == female_code][[occ_col, "value"]].copy()
    female_df = female_df.rename(columns={occ_col: "styrk_code", "value": "female_employed"})
    female_df = female_df.groupby("styrk_code", as_index=False)["female_employed"].sum()

    merged = total_df.merge(female_df, on="styrk_code", how="left")
    merged["pct_female"] = (merged["female_employed"] / merged["employed"]).round(4)
    return merged[["styrk_code", "employed", "pct_female"]]


def build_wages(wages_raw: dict) -> pd.DataFrame:
    """
    From the wages table (currently SSB 11418), compute:
      styrk2, median_monthly_wage, pct_public_sector, wage_precision
    """
    df = parse_jsonstat2(wages_raw)
    occ_col = _find_dim(df, ["Yrke", "yrke", "occupation"])
    sector_col = _find_dim(df, ["Sektor", "sektor", "sector"])

    df = df.dropna(subset=["value"])
    df["value"] = df["value"].astype(float)

    # Filter to 2-digit occupation codes only
    df = df[df[occ_col].str.len() == 2].copy()

    # Identify sector codes
    sector_label_col = f"{sector_col}_label"
    sector_vals = df[sector_col].unique().tolist()
    label_to_code: dict[str, str] = {}
    if sector_label_col in df.columns:
        for code in sector_vals:
            rows = df.loc[df[sector_col] == code, sector_label_col]
            if not rows.empty:
                label_to_code[rows.iloc[0].lower()] = code

    total_sector = _pick_code(
        label_to_code, sector_vals,
        ["sum all sectors", "all sectors", "alle sektorer", "total", "0", "alle"]
    )
    public_sector_codes = _pick_codes(
        label_to_code, sector_vals,
        ["public sector", "offentlig sektor", "local government", "municipal", "central government", "state", "1"]
    )

    # Identify the variable that holds "median monthly wage"
    # Table 11611 has a StatistikkVariabel (or ContentsCode) dimension
    var_col = _find_dim(df, ["StatistikkVariabel", "ContentsCode", "statistikkvariabel", "contents"])
    var_vals = df[var_col].unique().tolist()
    var_label_col = f"{var_col}_label"
    var_label_to_code: dict[str, str] = {}
    if var_label_col in df.columns:
        for code in var_vals:
            rows = df.loc[df[var_col] == code, var_label_col]
            if not rows.empty:
                var_label_to_code[rows.iloc[0].lower()] = code

    median_code = _pick_code(
        var_label_to_code, var_vals,
        ["monthly earnings", "median monthly earnings", "median månedlig lønn", "median", "medianlønn", "manedslonn"]
    )

    measure_col = None
    measure_vals: list[str] = []
    measure_label_to_code: dict[str, str] = {}
    for candidate in ["MaaleMetode", "maaleMetode", "maalemetode", "measuring method"]:
        if candidate in df.columns:
            measure_col = candidate
            break
    if measure_col:
        measure_vals = df[measure_col].unique().tolist()
        measure_label_col = f"{measure_col}_label"
        if measure_label_col in df.columns:
            for code in measure_vals:
                rows = df.loc[df[measure_col] == code, measure_label_col]
                if not rows.empty:
                    measure_label_to_code[rows.iloc[0].lower()] = code

    # All-sector median wage per 2-digit code
    wage_df = df[(df[sector_col] == total_sector) & (df[var_col] == median_code)].copy()
    if measure_col:
        median_measure_code = _pick_code(
            measure_label_to_code,
            measure_vals,
            ["median", "01"],
        )
        wage_df = wage_df[wage_df[measure_col] == median_measure_code].copy()
    wage_df = wage_df.rename(columns={occ_col: "styrk2", "value": "median_monthly_wage"})
    wage_df = wage_df.groupby("styrk2", as_index=False)["median_monthly_wage"].mean()
    wage_df["median_monthly_wage"] = wage_df["median_monthly_wage"].round(0).astype(int)

    # Public sector employment share: public / total employed.
    emp_df = None
    if measure_col:
        emp_measure_code = _pick_code(
            measure_label_to_code,
            measure_vals,
            ["number of employments with earnings", "employments with earnings", "number of employments", "10"],
        )
        if emp_measure_code:
            emp_df = df[df[measure_col] == emp_measure_code].copy()
    else:
        emp_code = _pick_code(
            var_label_to_code, var_vals,
            ["number of employees", "employees", "ansatte", "sysselsatte", "employed", "headcount", "antall", "lonsstakere", "lønnstakere"]
        )
        if emp_code:
            emp_df = df[df[var_col] == emp_code].copy()

    if emp_df is not None and public_sector_codes:
        pub_df = emp_df[emp_df[sector_col].isin(public_sector_codes)].copy()
        all_df = emp_df[emp_df[sector_col] == total_sector].copy()
        pub_df = pub_df.rename(columns={occ_col: "styrk2", "value": "pub_emp"})
        all_df = all_df.rename(columns={occ_col: "styrk2", "value": "all_emp"})
        pub_df = pub_df.groupby("styrk2", as_index=False)["pub_emp"].sum()
        all_df = all_df.groupby("styrk2", as_index=False)["all_emp"].sum()
        sec_df = pub_df.merge(all_df, on="styrk2", how="inner")
        sec_df["pct_public_sector"] = (sec_df["pub_emp"] / sec_df["all_emp"]).round(4)
        wage_df = wage_df.merge(sec_df[["styrk2", "pct_public_sector"]], on="styrk2", how="left")
    else:
        wage_df["pct_public_sector"] = None

    wage_df["wage_precision"] = "2-digit"
    return wage_df[["styrk2", "median_monthly_wage", "pct_public_sector", "wage_precision"]]


def build_education(edu_raw: dict) -> pd.DataFrame:
    """
    From table 12629 (occupation × education), compute:
      styrk_code, edu_level_mode
    """
    df = parse_jsonstat2(edu_raw)
    occ_col = _find_dim(df, ["Yrke", "yrke", "occupation"])
    edu_col = _find_dim(df, ["UtdNivaa", "Utdnivaa", "utdnivaa", "education", "Education"])

    df = df.dropna(subset=["value"])
    df["value"] = df["value"].astype(float)

    # Prefer the most detailed occupation level present in the source table.
    df = df[df[occ_col].str.fullmatch(r"\d+")].copy()
    if df.empty:
        return pd.DataFrame(columns=["styrk_code", "edu_level_mode"])
    code_len = int(df[occ_col].str.len().max())
    df = df[df[occ_col].str.len() == code_len].copy()

    # For each occupation find the education level with the most workers
    idx = df.groupby(occ_col)["value"].idxmax()
    mode_df = df.loc[idx, [occ_col, edu_col]].copy()
    mode_df = mode_df.rename(columns={occ_col: "styrk_code", edu_col: "edu_level_raw"})

    # Normalize raw education buckets to the frontend's categorical palette.
    mode_df["edu_level_mode"] = mode_df["edu_level_raw"].map(EDU_LEVEL_MAP).fillna(
        mode_df["edu_level_raw"].map({
            "1": "lower_secondary",
            "2": "upper_secondary",
            "3": "bachelor",
            "4": "master",
            "0+9": "unspecified",
        })
    )

    return mode_df[["styrk_code", "edu_level_mode"]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_dim(df: pd.DataFrame, candidates: list[str]) -> str:
    """Return the first column name in df that matches any candidate (case-insensitive)."""
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    raise KeyError(f"Could not find dimension among candidates {candidates}. Available: {list(df.columns)}")


def _pick_code(label_to_code: dict[str, str], all_codes: list[str], hints: list[str]) -> Optional[str]:
    """Pick a code by matching label hints (case-insensitive substring match)."""
    for hint in hints:
        # Exact label match
        if hint in label_to_code:
            return label_to_code[hint]
        # Substring match
        for lbl, code in label_to_code.items():
            if hint in lbl:
                return code
        # Direct code match
        if hint in all_codes:
            return hint
    # Fallback: return first code
    return all_codes[0] if all_codes else None


def _pick_codes(label_to_code: dict[str, str], all_codes: list[str], hints: list[str]) -> list[str]:
    """Return every matching code for the provided label hints, preserving input order."""
    matches: list[str] = []
    for hint in hints:
        if hint in label_to_code:
            matches.append(label_to_code[hint])
        for lbl, code in label_to_code.items():
            if hint in lbl:
                matches.append(code)
        if hint in all_codes:
            matches.append(hint)
    ordered: list[str] = []
    seen = set()
    for code in matches:
        if code in all_codes and code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading raw data...")
    occ_raw = load_json("occupations.json")
    wages_raw = load_json("wages.json")
    edu_raw = load_json("education.json")
    labels_raw = load_json("labels_no.json")

    print("Parsing KLASS labels...")
    four_digit_labels, one_digit_labels = extract_labels(labels_raw)

    print("Building occupation base (employed + pct_female)...")
    occ_df = build_occupations(occ_raw)

    print("Building wages (2-digit level)...")
    wages_df = build_wages(wages_raw)

    print("Building education modes...")
    edu_df = build_education(edu_raw)

    print("Merging...")
    # Start with KLASS 4-digit codes as the canonical set
    klass_df = pd.DataFrame(
        [{"styrk_code": code, "name_no": name} for code, name in four_digit_labels.items()]
    )

    # English names come from the KLASS en endpoint — we fetched Norwegian; use code as fallback
    # The spec says KLASS returns Norwegian names here; we'll add name_en = name_no as placeholder
    # (In production run fetch.py with lang=en to get English names)
    klass_df["name_en"] = klass_df["name_no"]

    merged = klass_df.merge(occ_df, on="styrk_code", how="left")

    # Join wages on first 2 digits
    merged["styrk2"] = merged["styrk_code"].str[:2]
    merged = merged.merge(wages_df, on="styrk2", how="left")

    # Join education at the most detailed level the source table exposes.
    if not edu_df.empty:
        edu_code_len = int(edu_df["styrk_code"].astype(str).str.len().max())
        if edu_code_len == 4:
            merged = merged.merge(edu_df, on="styrk_code", how="left")
        else:
            merged = merged.merge(
                edu_df.rename(columns={"styrk_code": "styrk2"}),
                on="styrk2",
                how="left",
            )
    else:
        merged["edu_level_mode"] = None

    # Add major group info
    merged["major_group"] = merged["styrk_code"].str[0]
    merged["major_group_name"] = merged["major_group"].map(MAJOR_GROUP_NAMES)

    # Drop rows without any employment data (code exists in KLASS but not in SSB table)
    before = len(merged)
    merged = merged.dropna(subset=["employed"])
    after = len(merged)
    if before != after:
        print(f"  Dropped {before - after} codes with no employment data")

    # Select and order columns
    out = merged[[
        "styrk_code", "name_en", "name_no",
        "major_group", "major_group_name",
        "employed", "pct_female",
        "median_monthly_wage", "pct_public_sector", "wage_precision",
        "edu_level_mode",
    ]].copy()

    out["employed"] = out["employed"].astype(int)

    os.makedirs(DATA_DIR, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(out)} rows to {OUTPUT_CSV}")
    print(f"Columns: {list(out.columns)}")
    print(out.head(3).to_string())


if __name__ == "__main__":
    main()
