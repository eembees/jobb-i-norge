"""
Tests for fetch.py.

The live SSB API tests are marked as 'integration' and require network access.
Run with: pytest -m integration

The unit tests validate the URL construction and file-saving logic without
making any network calls.
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fetch


# ---------------------------------------------------------------------------
# Unit tests — no network
# ---------------------------------------------------------------------------

class TestConstants:
    def test_all_three_tables_defined(self):
        assert "occupations" in fetch.TABLES
        assert "wages" in fetch.TABLES
        assert "education" in fetch.TABLES

    def test_table_ids_are_strings(self):
        for name, tid in fetch.TABLES.items():
            assert isinstance(tid, str), f"{name} table ID should be string"

    def test_base_url_contains_placeholder(self):
        assert "{id}" in fetch.BASE

    def test_klass_url_is_string(self):
        assert isinstance(fetch.KLASS_URL, str)
        assert "klass" in fetch.KLASS_URL.lower()

    def test_common_params_has_outputformat(self):
        assert "outputformat" in fetch.COMMON_PARAMS
        assert fetch.COMMON_PARAMS["outputformat"] == "json-stat2"

    def test_common_params_requests_latest_year(self):
        assert "valueCodes[Tid]" in fetch.COMMON_PARAMS
        assert "top" in fetch.COMMON_PARAMS["valueCodes[Tid]"]


class TestSaveFunction:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            data = {"key": "value", "num": 42}
            fetch.save(data, path)
            assert os.path.exists(path)

    def test_file_content_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            data = {"codes": [{"code": "2111", "name": "Physicists"}]}
            fetch.save(data, path)
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == data

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "deep", "file.json")
            fetch.save({"x": 1}, path)
            assert os.path.exists(path)

    def test_unicode_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "unicode.json")
            data = {"name": "Renholdere og hjelpearbeidere \u00e6\u00f8\u00e5"}
            fetch.save(data, path)
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["name"] == data["name"]


# ---------------------------------------------------------------------------
# Integration tests — require real network access to data.ssb.no
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLiveSSBApi:
    """
    These tests hit the real SSB API. Only run when --run-integration is passed
    or when explicitly marked.

    Usage: pytest -m integration tests/test_fetch.py
    """

    def test_fetch_occupations_returns_jsonstat2(self):
        data = fetch.fetch_table("occupations", fetch.TABLES["occupations"])
        assert "dimension" in data
        assert "value" in data
        assert isinstance(data["value"], list)
        assert len(data["value"]) > 0

    def test_fetch_wages_has_occupation_dimension(self):
        data = fetch.fetch_table("wages", fetch.TABLES["wages"])
        dim_ids = list(data["dimension"].keys())
        # Should have at least an occupation-related dimension
        occ_dims = [d for d in dim_ids if "yrke" in d.lower() or "occ" in d.lower()]
        assert len(occ_dims) > 0

    def test_fetch_education_has_education_dimension(self):
        data = fetch.fetch_table("education", fetch.TABLES["education"])
        dim_ids = list(data["dimension"].keys())
        edu_dims = [d for d in dim_ids if "utd" in d.lower() or "edu" in d.lower()]
        assert len(edu_dims) > 0

    def test_fetch_klass_returns_codes(self):
        data = fetch.fetch_klass()
        assert "codes" in data
        assert len(data["codes"]) > 0
        first = data["codes"][0]
        assert "code" in first
        assert "name" in first

    def test_klass_has_four_digit_codes(self):
        data = fetch.fetch_klass()
        codes = [c["code"] for c in data["codes"]]
        four_digit = [c for c in codes if len(c) == 4]
        assert len(four_digit) >= 300, f"Expected >=300 4-digit codes, got {len(four_digit)}"

    def test_full_pipeline_fetch_to_files(self, tmp_path):
        """End-to-end: fetch all tables and confirm files are saved and parseable."""
        import fetch as fetch_module
        orig_dir = fetch_module.DATA_RAW
        fetch_module.DATA_RAW = str(tmp_path / "raw")

        try:
            fetch_module.main()
        finally:
            fetch_module.DATA_RAW = orig_dir

        raw_dir = tmp_path / "raw"
        for fname in ["occupations.json", "wages.json", "education.json", "labels_no.json"]:
            fpath = raw_dir / fname
            assert fpath.exists(), f"Missing {fname}"
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"{fname} is not a JSON object"
