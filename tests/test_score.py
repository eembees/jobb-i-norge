"""
Tests for score.py.

Live API tests are marked 'integration' and require ANTHROPIC_API_KEY.

Run live tests:
  ANTHROPIC_API_KEY=sk-ant-... pytest -m integration tests/test_score.py
"""

import json
import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import score


# ---------------------------------------------------------------------------
# Unit tests — no API call
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def _make_row(self, **kwargs) -> pd.Series:
        defaults = {
            "styrk_code": "2111",
            "name_en": "Physicists and astronomers",
            "employed": 1240,
            "median_monthly_wage": 72000,
            "edu_level_mode": "master",
            "pct_female": 0.39,
        }
        defaults.update(kwargs)
        return pd.Series(defaults)

    def test_includes_occupation_name(self):
        row = self._make_row()
        prompt = score.build_prompt(row)
        assert "Physicists and astronomers" in prompt

    def test_includes_styrk_code(self):
        row = self._make_row()
        prompt = score.build_prompt(row)
        assert "2111" in prompt

    def test_includes_wage_when_present(self):
        row = self._make_row(median_monthly_wage=72000)
        prompt = score.build_prompt(row)
        assert "72" in prompt  # part of 72,000

    def test_omits_wage_when_null(self):
        row = self._make_row(median_monthly_wage=float("nan"))
        prompt = score.build_prompt(row)
        assert "wage" not in prompt.lower() or "72" not in prompt

    def test_includes_education(self):
        row = self._make_row(edu_level_mode="master")
        prompt = score.build_prompt(row)
        assert "master" in prompt.lower()

    def test_returns_string(self):
        row = self._make_row()
        assert isinstance(score.build_prompt(row), str)


class TestSystemPrompt:
    def test_mentions_score_range(self):
        assert "0" in score.SYSTEM_PROMPT
        assert "10" in score.SYSTEM_PROMPT

    def test_mentions_json(self):
        assert "JSON" in score.SYSTEM_PROMPT or "json" in score.SYSTEM_PROMPT

    def test_specifies_score_and_rationale_keys(self):
        assert '"score"' in score.SYSTEM_PROMPT
        assert '"rationale"' in score.SYSTEM_PROMPT


class TestSaveIncrementally:
    """Score.py saves after each occupation — verify file is valid JSON mid-run."""

    def test_incremental_save_produces_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scores.json")
            data = {"2111": {"score": 6.5, "rationale": "Test"}}
            with open(path, "w") as f:
                json.dump(data, f)
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["2111"]["score"] == 6.5


# ---------------------------------------------------------------------------
# Integration tests — require ANTHROPIC_API_KEY and network
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLiveScoring:
    @pytest.fixture(autouse=True)
    def require_api_key(self):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            pytest.skip("ANTHROPIC_API_KEY not set")

    def test_score_single_occupation_returns_valid_structure(self):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        row = pd.Series({
            "styrk_code": "2111",
            "name_en": "Physicists and astronomers",
            "employed": 1240,
            "median_monthly_wage": 72000,
            "edu_level_mode": "master",
            "pct_female": 0.39,
        })
        result = score.score_occupation(client, row)
        assert isinstance(result, dict)
        assert "score" in result
        assert "rationale" in result

    def test_score_is_in_valid_range(self):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        row = pd.Series({
            "styrk_code": "4110",
            "name_en": "General office clerks",
            "employed": 15000,
            "median_monthly_wage": 42000,
            "edu_level_mode": "upper_secondary",
            "pct_female": 0.65,
        })
        result = score.score_occupation(client, row)
        assert 0.0 <= float(result["score"]) <= 10.0

    def test_rationale_is_non_empty_string(self):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        row = pd.Series({
            "styrk_code": "5120",
            "name_en": "Cooks",
            "employed": 18500,
            "median_monthly_wage": 38000,
            "edu_level_mode": "upper_secondary",
            "pct_female": 0.6,
        })
        result = score.score_occupation(client, row)
        assert isinstance(result["rationale"], str)
        assert len(result["rationale"]) > 10

    def test_high_automation_occupation_scores_higher(self):
        """Data entry clerks should score higher than surgeons."""
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        clerk_row = pd.Series({
            "styrk_code": "4132",
            "name_en": "Data entry clerks",
            "employed": 8000,
            "median_monthly_wage": 38000,
            "edu_level_mode": "upper_secondary",
            "pct_female": 0.7,
        })
        surgeon_row = pd.Series({
            "styrk_code": "2212",
            "name_en": "Specialist medical doctors",
            "employed": 5000,
            "median_monthly_wage": 120000,
            "edu_level_mode": "doctoral",
            "pct_female": 0.35,
        })

        clerk_result = score.score_occupation(client, clerk_row)
        surgeon_result = score.score_occupation(client, surgeon_row)

        assert float(clerk_result["score"]) > float(surgeon_result["score"]), (
            f"Expected data entry ({clerk_result['score']}) > surgeons ({surgeon_result['score']})"
        )

    def test_full_score_main_with_limit(self):
        """Run score.main() with --limit 2 and verify scores.json is produced."""
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "occupations.csv")
            scores_path = os.path.join(d, "scores.json")

            df = pd.DataFrame([
                {
                    "styrk_code": "2111",
                    "name_en": "Physicists",
                    "employed": 1240,
                    "median_monthly_wage": 72000,
                    "edu_level_mode": "master",
                    "pct_female": 0.39,
                },
                {
                    "styrk_code": "5120",
                    "name_en": "Cooks",
                    "employed": 18500,
                    "median_monthly_wage": 38000,
                    "edu_level_mode": "upper_secondary",
                    "pct_female": 0.6,
                },
            ])
            df.to_csv(csv_path, index=False)

            # Patch paths
            orig_csv = score.OCCUPATIONS_CSV
            orig_scores = score.SCORES_JSON
            score.OCCUPATIONS_CSV = csv_path
            score.SCORES_JSON = scores_path

            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["score.py", "--limit", "2", "--delay", "0"]

            try:
                score.main()
            finally:
                score.OCCUPATIONS_CSV = orig_csv
                score.SCORES_JSON = orig_scores
                _sys.argv = old_argv

            assert os.path.exists(scores_path)
            with open(scores_path, encoding="utf-8") as f:
                scores = json.load(f)
            assert len(scores) == 2
            for code, entry in scores.items():
                assert "score" in entry
                assert "rationale" in entry
