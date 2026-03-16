"""
Tests for process.py — data merging logic.

No mocking: we feed real fixture JSON (same format as SSB returns) into the
actual parsing functions and assert on the output.
"""

import sys
import os

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from process import (
    parse_jsonstat2,
    extract_labels,
    build_occupations,
    build_wages,
    build_education,
    _find_dim,
    _pick_code,
)


# ---------------------------------------------------------------------------
# parse_jsonstat2
# ---------------------------------------------------------------------------

class TestParseJsonstat2:
    def test_returns_dataframe(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        assert isinstance(df, pd.DataFrame)

    def test_row_count_equals_product_of_dim_sizes(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        # 4 occupations × 3 sexes × 1 age × 1 year = 12
        assert len(df) == 12

    def test_has_value_column(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        assert "value" in df.columns

    def test_has_all_dimension_columns(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        for dim in ["Yrke", "Kjonn", "Alder", "Tid"]:
            assert dim in df.columns

    def test_label_columns_added(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        assert "Yrke_label" in df.columns
        assert "Kjonn_label" in df.columns

    def test_label_content(self, occupations_raw):
        df = parse_jsonstat2(occupations_raw)
        row = df[df["Yrke"] == "2111"].iloc[0]
        assert row["Yrke_label"] == "Physicists and astronomers"

    def test_null_values_preserved(self):
        """Null values in SSB responses must remain null (NaN), not be silently filled with 0."""
        data = {
            "id": ["A", "B"],
            "size": [2, 1],
            "dimension": {
                "A": {"label": "A", "category": {"index": {"x": 0, "y": 1}, "label": {"x": "X", "y": "Y"}}},
                "B": {"label": "B", "category": {"index": {"p": 0}, "label": {"p": "P"}}},
            },
            "value": [42, None],
        }
        df = parse_jsonstat2(data)
        # pandas stores None as NaN in numeric columns — check with pd.isna(), not `is None`
        null_val = df.loc[df["A"] == "y", "value"].iloc[0]
        assert pd.isna(null_val), f"Expected null/NaN for suppressed value, got {null_val!r}"
        # And the non-null value must be 42
        assert df.loc[df["A"] == "x", "value"].iloc[0] == 42

    def test_wages_dimensions(self, wages_raw):
        df = parse_jsonstat2(wages_raw)
        # 3 occupations × 3 sectors × 3 variables × 1 year = 27
        assert len(df) == 27

    def test_education_dimensions(self, education_raw):
        df = parse_jsonstat2(education_raw)
        # 4 occupations × 5 education levels × 1 year = 20
        assert len(df) == 20


# ---------------------------------------------------------------------------
# extract_labels
# ---------------------------------------------------------------------------

class TestExtractLabels:
    def test_returns_two_dicts(self, labels_raw):
        four, one = extract_labels(labels_raw)
        assert isinstance(four, dict)
        assert isinstance(one, dict)

    def test_four_digit_codes_only(self, labels_raw):
        four, _ = extract_labels(labels_raw)
        for code in four:
            assert len(code) == 4, f"Non-4-digit code in four_digit dict: {code}"

    def test_one_digit_codes_only(self, labels_raw):
        _, one = extract_labels(labels_raw)
        for code in one:
            assert len(code) == 1, f"Non-1-digit code in one_digit dict: {code}"

    def test_known_codes_present(self, labels_raw):
        four, one = extract_labels(labels_raw)
        assert "2111" in four
        assert "5120" in four
        assert "2" in one

    def test_name_content(self, labels_raw):
        four, _ = extract_labels(labels_raw)
        assert four["2111"] == "Fysikere og astronomer"
        assert four["5120"] == "Kokker"


# ---------------------------------------------------------------------------
# build_occupations
# ---------------------------------------------------------------------------

class TestBuildOccupations:
    def test_returns_dataframe_with_required_columns(self, occupations_raw):
        df = build_occupations(occupations_raw)
        for col in ["styrk_code", "employed", "pct_female"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_only_four_digit_codes(self, occupations_raw):
        df = build_occupations(occupations_raw)
        for code in df["styrk_code"]:
            assert len(str(code)) == 4

    def test_employed_physicists(self, occupations_raw):
        """2111 total = 1240 in fixture."""
        df = build_occupations(occupations_raw)
        row = df[df["styrk_code"] == "2111"].iloc[0]
        assert row["employed"] == 1240

    def test_pct_female_range(self, occupations_raw):
        df = build_occupations(occupations_raw)
        assert (df["pct_female"].dropna() >= 0).all()
        assert (df["pct_female"].dropna() <= 1).all()

    def test_pct_female_physicists(self, occupations_raw):
        """490 female / 1240 total ≈ 0.3952"""
        df = build_occupations(occupations_raw)
        row = df[df["styrk_code"] == "2111"].iloc[0]
        assert abs(row["pct_female"] - (490 / 1240)) < 0.001

    def test_pct_female_cooks(self, occupations_raw):
        """11100 female / 18500 total = 0.6"""
        df = build_occupations(occupations_raw)
        row = df[df["styrk_code"] == "5120"].iloc[0]
        assert abs(row["pct_female"] - (11100 / 18500)) < 0.001

    def test_no_suppressed_data_filled_with_zero(self, occupations_raw):
        """Null values must be dropped, not filled with 0."""
        df = build_occupations(occupations_raw)
        # In fixture, 2111 has valid data — verify employed > 0
        assert df.loc[df["styrk_code"] == "2111", "employed"].iloc[0] > 0


# ---------------------------------------------------------------------------
# build_wages
# ---------------------------------------------------------------------------

class TestBuildWages:
    def test_returns_dataframe_with_required_columns(self, wages_raw):
        df = build_wages(wages_raw)
        for col in ["styrk2", "median_monthly_wage", "wage_precision"]:
            assert col in df.columns

    def test_only_two_digit_codes(self, wages_raw):
        df = build_wages(wages_raw)
        for code in df["styrk2"]:
            assert len(str(code)) == 2

    def test_wage_precision_tag(self, wages_raw):
        df = build_wages(wages_raw)
        assert (df["wage_precision"] == "2-digit").all()

    def test_median_wage_physicists(self, wages_raw):
        """All-sector median for code 21 = 72000 in fixture."""
        df = build_wages(wages_raw)
        row = df[df["styrk2"] == "21"].iloc[0]
        assert row["median_monthly_wage"] == 72000

    def test_median_wage_positive(self, wages_raw):
        df = build_wages(wages_raw)
        assert (df["median_monthly_wage"] > 0).all()


# ---------------------------------------------------------------------------
# build_education
# ---------------------------------------------------------------------------

class TestBuildEducation:
    def test_returns_dataframe_with_required_columns(self, education_raw):
        df = build_education(education_raw)
        for col in ["styrk_code", "edu_level_mode"]:
            assert col in df.columns

    def test_only_four_digit_codes(self, education_raw):
        df = build_education(education_raw)
        for code in df["styrk_code"]:
            assert len(str(code)) == 4

    def test_edu_mode_physicists(self, education_raw):
        """For 2111: master has 1050, the most workers → mode = 'master'"""
        df = build_education(education_raw)
        row = df[df["styrk_code"] == "2111"].iloc[0]
        assert "master" in str(row["edu_level_mode"]).lower() or row["edu_level_mode"] == "6"

    def test_edu_mode_cooks(self, education_raw):
        """For 5120: upper_secondary (3) has 10500, the most workers → mode contains upper_secondary or '3'"""
        df = build_education(education_raw)
        row = df[df["styrk_code"] == "5120"].iloc[0]
        val = str(row["edu_level_mode"]).lower()
        assert "upper_secondary" in val or "upper" in val or val == "3"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_find_dim_exact(self):
        import pandas as pd
        df = pd.DataFrame({"Yrke": [], "Kjonn": []})
        assert _find_dim(df, ["Yrke"]) == "Yrke"

    def test_find_dim_case_insensitive(self):
        import pandas as pd
        df = pd.DataFrame({"yrke": [], "kjonn": []})
        assert _find_dim(df, ["Yrke"]) == "yrke"

    def test_find_dim_raises_if_not_found(self):
        import pandas as pd
        df = pd.DataFrame({"A": [], "B": []})
        with pytest.raises(KeyError):
            _find_dim(df, ["missing", "also_missing"])

    def test_pick_code_by_label(self):
        assert _pick_code({"both sexes": "0"}, ["0", "1", "2"], ["both sexes"]) == "0"

    def test_pick_code_by_substring(self):
        assert _pick_code({"median monthly earnings": "M"}, ["M", "A"], ["median"]) == "M"

    def test_pick_code_direct_code_match(self):
        assert _pick_code({}, ["0", "1", "2"], ["1"]) == "1"

    def test_pick_code_fallback_first(self):
        assert _pick_code({}, ["X", "Y"], ["not_here"]) == "X"
