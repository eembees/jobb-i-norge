"""
Tests for build_site_data.py — CSV → site/data.json serialisation.

No mocking: we write real CSV/JSON fixture files to a temp directory and
invoke the actual module logic.
"""

import json
import math
import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import build_site_data


SAMPLE_OCCUPATIONS = [
    {
        "styrk_code": "2111",
        "name_en": "Physicists and astronomers",
        "name_no": "Fysikere og astronomer",
        "major_group": "2",
        "major_group_name": "Professionals",
        "employed": 1240,
        "pct_female": 0.3952,
        "median_monthly_wage": 72000,
        "pct_public_sector": 0.81,
        "wage_precision": "2-digit",
        "edu_level_mode": "master",
    },
    {
        "styrk_code": "5120",
        "name_en": "Cooks",
        "name_no": "Kokker",
        "major_group": "5",
        "major_group_name": "Service and sales workers",
        "employed": 18500,
        "pct_female": 0.6,
        "median_monthly_wage": 38000,
        "pct_public_sector": 0.35,
        "wage_precision": "2-digit",
        "edu_level_mode": "upper_secondary",
    },
    {
        "styrk_code": "9112",
        "name_en": "Cleaning and laundry workers",
        "name_no": "Renholdere",
        "major_group": "9",
        "major_group_name": "Elementary occupations",
        "employed": 12000,
        "pct_female": 0.7,
        "median_monthly_wage": None,   # suppressed
        "pct_public_sector": None,
        "wage_precision": "2-digit",
        "edu_level_mode": None,
    },
]


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def sample_csv(tmp_dir):
    path = os.path.join(tmp_dir, "occupations.csv")
    df = pd.DataFrame(SAMPLE_OCCUPATIONS)
    df.to_csv(path, index=False)
    return path


@pytest.fixture()
def output_path(tmp_dir):
    return os.path.join(tmp_dir, "data.json")


def run_build(csv_path: str, output_path: str, scores: dict | None = None):
    """
    Call the actual build logic by temporarily monkey-patching the module-level
    paths, without mocking any functions.
    """
    scores_path = os.path.join(os.path.dirname(csv_path), "scores.json")
    if scores is not None:
        with open(scores_path, "w") as f:
            json.dump(scores, f)

    orig_csv = build_site_data.OCCUPATIONS_CSV
    orig_scores = build_site_data.SCORES_JSON
    orig_out = build_site_data.OUTPUT_JSON

    build_site_data.OCCUPATIONS_CSV = csv_path
    build_site_data.SCORES_JSON = scores_path
    build_site_data.OUTPUT_JSON = output_path
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        build_site_data.main()
    finally:
        build_site_data.OCCUPATIONS_CSV = orig_csv
        build_site_data.SCORES_JSON = orig_scores
        build_site_data.OUTPUT_JSON = orig_out

    with open(output_path, encoding="utf-8") as f:
        return json.load(f)


class TestBuildSiteData:
    def test_output_is_list(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        assert isinstance(result, list)

    def test_row_count_matches_csv(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        assert len(result) == len(SAMPLE_OCCUPATIONS)

    def test_required_keys_present(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        required = {"code", "name", "name_no", "major_group", "major_group_name",
                    "employed", "pct_female", "median_monthly_wage", "pct_public_sector",
                    "edu_level_mode"}
        for rec in result:
            missing = required - rec.keys()
            assert not missing, f"Missing keys in record {rec['code']}: {missing}"

    def test_physicist_values(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        rec = next(r for r in result if r["code"] == "2111")
        assert rec["name"] == "Physicists and astronomers"
        assert rec["major_group"] == 2
        assert rec["employed"] == 1240
        assert abs(rec["pct_female"] - 0.3952) < 0.001
        assert rec["median_monthly_wage"] == 72000
        assert abs(rec["pct_public_sector"] - 0.81) < 0.001
        assert rec["edu_level_mode"] == "master"

    def test_null_fields_are_none_not_nan(self, sample_csv, output_path):
        """NaN from pandas must become JSON null, not the string 'NaN'."""
        result = run_build(sample_csv, output_path)
        rec = next(r for r in result if r["code"] == "9112")
        assert rec["median_monthly_wage"] is None
        assert rec["pct_public_sector"] is None
        assert rec["edu_level_mode"] is None

    def test_output_is_valid_json(self, sample_csv, output_path):
        """File must be parseable JSON (no NaN literals etc.)."""
        run_build(sample_csv, output_path)
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
        # json.loads raises if invalid
        parsed = json.loads(content)
        assert isinstance(parsed, list)

    def test_no_nan_strings_in_json(self, sample_csv, output_path):
        run_build(sample_csv, output_path)
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
        assert "NaN" not in content
        assert "Infinity" not in content

    def test_ai_scores_merged_when_present(self, sample_csv, output_path):
        scores = {
            "2111": {"score": 6.5, "rationale": "Complex analytical work"},
            "5120": {"score": 3.2, "rationale": "Manual skill required"},
        }
        result = run_build(sample_csv, output_path, scores=scores)
        physicist = next(r for r in result if r["code"] == "2111")
        cook = next(r for r in result if r["code"] == "5120")
        cleaner = next(r for r in result if r["code"] == "9112")

        assert physicist.get("ai_score") == 6.5
        assert cook.get("ai_score") == 3.2
        assert "ai_score" not in cleaner  # no score for this code

    def test_no_scores_when_file_absent(self, sample_csv, output_path):
        # Don't pass scores — file won't exist
        result = run_build(sample_csv, output_path)
        for rec in result:
            assert "ai_score" not in rec

    def test_major_group_is_int(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        for rec in result:
            if rec["major_group"] is not None:
                assert isinstance(rec["major_group"], int)

    def test_employed_is_int(self, sample_csv, output_path):
        result = run_build(sample_csv, output_path)
        for rec in result:
            if rec["employed"] is not None:
                assert isinstance(rec["employed"], int)


class TestCleanValue:
    def test_none_passthrough(self):
        assert build_site_data.clean_value(None) is None

    def test_nan_becomes_none(self):
        assert build_site_data.clean_value(float("nan")) is None

    def test_inf_becomes_none(self):
        assert build_site_data.clean_value(float("inf")) is None

    def test_normal_float_unchanged(self):
        assert build_site_data.clean_value(3.14) == 3.14

    def test_string_unchanged(self):
        assert build_site_data.clean_value("hello") == "hello"
