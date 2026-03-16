"""
score.py — LLM-score each occupation for AI/automation exposure.

Requires: ANTHROPIC_API_KEY environment variable.

Output: data/scores.json — {styrk_code: {score: 0-10, rationale: "..."}}

Usage:
  ANTHROPIC_API_KEY=sk-ant-... python score.py [--limit N]
"""

import argparse
import json
import os
import sys
import time

import anthropic
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OCCUPATIONS_CSV = os.path.join(DATA_DIR, "occupations.csv")
SCORES_JSON = os.path.join(DATA_DIR, "scores.json")

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are an expert labour economist specialising in automation and AI.
Your task is to score occupations on their exposure to AI and automation.

Scoring rubric (0–10):
  0–2: Very unlikely to be automated. Requires complex physical dexterity, deep human judgement,
       or interpersonal care that AI cannot replicate in the near term.
       Examples: plumbers, nurses, social workers.
  3–4: Low-to-moderate exposure. Some routine tasks could be automated but core work is human.
  5–6: Moderate exposure. A significant portion of tasks could be partially automated.
  7–8: High exposure. Most tasks are routine, rule-based, or pattern-matching.
  9–10: Very high exposure. Tasks are almost entirely automatable with current or near-term AI.
        Examples: data entry clerks, telemarketers, bookkeepers.

Respond ONLY with valid JSON in this exact format (no prose, no markdown):
{"score": <number 0-10 with one decimal>, "rationale": "<one sentence, max 120 chars>"}"""


def build_prompt(row: pd.Series) -> str:
    parts = [f"Occupation: {row['name_en']} (STYRK-08: {row['styrk_code']})"]
    if pd.notna(row.get("employed")):
        parts.append(f"Workers employed: {int(row['employed']):,}")
    if pd.notna(row.get("median_monthly_wage")):
        parts.append(f"Median monthly wage: {int(row['median_monthly_wage']):,} NOK")
    if pd.notna(row.get("edu_level_mode")):
        parts.append(f"Most common education: {row['edu_level_mode']}")
    if pd.notna(row.get("pct_female")):
        parts.append(f"Female share: {row['pct_female']*100:.0f}%")
    return "\n".join(parts)


def score_occupation(client: anthropic.Anthropic, row: pd.Series) -> dict:
    prompt = build_prompt(row)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    # Parse JSON response
    result = json.loads(text)
    return {
        "score": float(result["score"]),
        "rationale": str(result["rationale"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-score occupations for AI exposure")
    parser.add_argument("--limit", type=int, default=None, help="Score only first N occupations")
    parser.add_argument("--delay", type=float, default=0.2, help="Seconds between API calls")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(OCCUPATIONS_CSV):
        print(f"Error: {OCCUPATIONS_CSV} not found. Run process.py first.", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(OCCUPATIONS_CSV, dtype={"styrk_code": str})
    if args.limit:
        df = df.head(args.limit)

    # Load existing scores to allow resuming
    existing: dict = {}
    if os.path.exists(SCORES_JSON):
        with open(SCORES_JSON, encoding="utf-8") as f:
            existing = json.load(f)

    client = anthropic.Anthropic(api_key=api_key)

    scores = dict(existing)
    todo = df[~df["styrk_code"].isin(scores)].copy()
    print(f"Scoring {len(todo)} occupations (skipping {len(scores)} already done)...")

    for i, (_, row) in enumerate(todo.iterrows()):
        code = str(row["styrk_code"])
        try:
            result = score_occupation(client, row)
            scores[code] = result
            print(f"  [{i+1}/{len(todo)}] {code} {row['name_en']}: {result['score']}")
        except (json.JSONDecodeError, KeyError, anthropic.APIError) as exc:
            print(f"  [{i+1}/{len(todo)}] {code} ERROR: {exc}")
            scores[code] = {"score": None, "rationale": f"Error: {exc}"}

        # Save incrementally
        with open(SCORES_JSON, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)

        if args.delay > 0:
            time.sleep(args.delay)

    print(f"Done. {len(scores)} scores saved to {SCORES_JSON}")


if __name__ == "__main__":
    main()
