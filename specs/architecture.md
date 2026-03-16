# norjobs — architecture

> A research tool for visually exploring Norwegian labour market data from SSB (Statistics Norway).
> Inspired by karpathy/jobs. Not a report or publication — a dev tool for exploring data visually.

---

## What this is

karpathy/jobs took BLS OOH data (342 occupations, scraped HTML), ran LLM scoring, and built a treemap.
This project does the same for Norway, but the data pipeline is cleaner: SSB publishes everything
through a free, open REST API (PxWebApi v2) with no scraping required.

The output is a single `site/index.html` — a static file you can open in a browser or host anywhere.

---

## Repository layout

```
norjobs/
├── data/
│   ├── raw/                  # API responses, never edited by hand
│   │   ├── occupations.json  # SSB table 13114 — employees by occupation
│   │   ├── wages.json        # SSB table 11611 — wages by occupation
│   │   ├── education.json    # SSB table 12629 — occupation × education
│   │   └── labels_no.json    # KLASS classification 7 — STYRK-08 code labels
│   ├── occupations.csv       # one row per 4-digit occupation, all fields merged
│   └── scores.json           # LLM scores (optional, see score.py)
├── fetch.py                  # fetch raw data from SSB API → data/raw/
├── process.py                # merge raw → occupations.csv
├── score.py                  # optional: LLM-score each occupation
├── build_site_data.py        # occupations.csv + scores.json → site/data.json
├── site/
│   ├── index.html            # the entire frontend (single file)
│   └── data.json             # generated, not checked in (or check in for GH Pages)
├── specs/                    # task briefs live here
│   └── 01-fetch.md
├── requirements.txt
└── ARCHITECTURE.md           # this file
```

---

## Data sources

All SSB data is CC BY 4.0. No API key. No scraping.

### Primary tables (PxWebApi v2)

Base URL: `https://data.ssb.no/api/pxwebapi/v2/tables/{id}/data`

| Table | ID | What it contains | Key dimensions |
|---|---|---|---|
| Employees by occupation | `13114` | Headcount per 4-digit STYRK-08 code | Yrke (occupation), Kjonn (sex), Alder (age), Tid (year) |
| Wages by occupation | `11611` | Monthly wages, full/part-time | Yrke, Sektor (public/private), Arbeidstid, Tid |
| Occupation × education | `12629` | What education workers actually have | Yrke, Utdnivaa (edu level), Tid |

Example GET request (all occupations, latest year):
```
https://data.ssb.no/api/pxwebapi/v2/tables/13114/data?lang=en&valueCodes[Yrke]=*&valueCodes[Tid]=top(1)&outputformat=json-stat2
```

### Classification labels

STYRK-08 occupation codes with Norwegian + English names:
```
https://data.ssb.no/api/klass/v1/classifications/7/codes?from=2024-01-01&language=en
```

Returns a flat list of `{code, name}` pairs at 1, 2, 3, and 4-digit levels.
1-digit = major group (9 groups), used for treemap top-level grouping.
4-digit = individual occupations (~400 codes), one row in the final CSV.

### Optional: NAV job vacancies

Open vacancies by occupation, updated monthly:
```
https://data.nav.no/api/...   # see nav.no/statistikk/ledige-stillinger
```
Adds a "demand signal" column: vacancies / employed. Nice-to-have, not in v1.

---

## Pipeline

```
fetch.py  →  data/raw/*.json
process.py  →  data/occupations.csv
score.py  →  data/scores.json          (optional)
build_site_data.py  →  site/data.json
```

### fetch.py

Fetches each SSB table with a GET request. Saves raw JSON-stat2 response.
Run once; re-run to refresh data.

```python
# rough shape — agent fills in the details
TABLES = {
    "occupations": "13114",
    "wages":       "11611",
    "education":   "12629",
}
BASE = "https://data.ssb.no/api/pxwebapi/v2/tables/{id}/data"
PARAMS = "?lang=en&outputformat=json-stat2&valueCodes[Tid]=top(1)"
```

No pagination needed for these tables — each is well under the 800k cell limit.

### process.py

Reads `data/raw/*.json` and `data/raw/labels_no.json`, outputs `data/occupations.csv`.

One row per 4-digit STYRK-08 code. Columns:

| Column | Source | Notes |
|---|---|---|
| `styrk_code` | KLASS | e.g. `2111` |
| `name_en` | KLASS | English label |
| `name_no` | KLASS | Norwegian label |
| `major_group` | derived | first digit of styrk_code |
| `major_group_name` | KLASS 1-digit | e.g. "Professionals" |
| `employed` | table 13114 | total headcount, latest year |
| `pct_female` | table 13114 | sex breakdown |
| `median_monthly_wage` | table 11611 | NOK, all sectors |
| `pct_public_sector` | table 11611 | share in public employment |
| `edu_level_mode` | table 12629 | most common education level among workers |

### score.py (optional)

Sends each occupation name + stats to an LLM with a scoring rubric.
Saves `data/scores.json`: `{styrk_code: {score: 0-10, rationale: "..."}}`

Default prompt scores AI/automation exposure, same as karpathy/jobs.
Fork this to score anything: physical demand, outdoor work, remote-friendliness, etc.

Uses `litellm` so model is swappable. Gemini Flash is cheap and fast for bulk scoring.

### build_site_data.py

Merges `occupations.csv` and (optionally) `scores.json` into `site/data.json`.

```json
[
  {
    "code": "2111",
    "name": "Physicists and astronomers",
    "name_no": "Fysikere og astronomer",
    "major_group": 2,
    "major_group_name": "Professionals",
    "employed": 1240,
    "pct_female": 0.38,
    "median_monthly_wage": 72000,
    "pct_public_sector": 0.81,
    "edu_level_mode": "master",
    "ai_score": 6.2
  },
  ...
]
```

Compact: drop columns unused by the frontend, round numbers.

---

## Frontend — site/index.html

Single self-contained file. No build step. No framework. Open it directly.

Loads `data.json` via `fetch('./data.json')`.

### Layout

```
┌─────────────────────────────────────────────────────┐
│  norjobs   [color by: ▾ Wage | Growth | Education]  │
│            [group by: ▾ Major group]   [search...]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│              treemap (D3 v7)                        │
│      rectangle area ∝ employed (headcount)          │
│      color = selected metric                        │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [detail panel — appears on click]                  │
│  Occupation name · STYRK code · Major group         │
│  Employed: 12,400 · Median wage: 68 000 kr/mnd      │
│  Female share: 72% · Public sector: 81%             │
│  Education: Master's degree (most common)           │
│  AI score: 4.1/10                                   │
└─────────────────────────────────────────────────────┘
```

### Color layers (toggle in header)

| Layer | Scale | Notes |
|---|---|---|
| Median wage | sequential blue | NOK/month |
| Female share | diverging | 0% → 50% → 100% |
| Public sector share | sequential | 0% → 100% |
| Education mode | categorical | 5 levels |
| AI score | diverging green→red | 0–10 (only if scores.json exists) |

### Libraries (CDN, no install)

```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
```

That's it. No React, no bundler.

### Treemap details

- `d3.treemap()` with `d3.treemapSquarify`
- Top level: 9 major ISCO groups (1-digit STYRK)
- Leaves: individual 4-digit occupations
- Rectangle area: `employed` (headcount)
- Labels: shown when rectangle is large enough (> ~2000px²), hidden otherwise
- Click: opens detail panel, highlights rectangle
- Search: filters to matching occupations, greys out non-matches

---

## Running locally

```bash
pip install -r requirements.txt

# 1. Fetch data (once)
python fetch.py

# 2. Process into CSV
python process.py

# 3. (Optional) LLM scoring
OPENROUTER_API_KEY=... python score.py

# 4. Build site data
python build_site_data.py

# 5. Serve
cd site && python -m http.server 8000
```

Open http://localhost:8000.

---

## requirements.txt

```
requests
pandas
litellm        # only needed for score.py
```

---

## What the coding agent should implement first

In order:

1. `fetch.py` — GET three SSB tables + KLASS labels, save to `data/raw/`. Test: files exist and parse as valid JSON.
2. `process.py` — merge into `occupations.csv`. Test: ~350–420 rows, no nulls in core columns.
3. `build_site_data.py` — emit `site/data.json`. Test: valid JSON array, all required keys present.
4. `site/index.html` — treemap renders from data.json, color toggle works, detail panel on click.
5. `score.py` — last, it costs money to run.

---

## Norway-specific notes for the agent

- STYRK-08 uses 4-digit codes. 1st digit = major group. Map:
  `1` Managers, `2` Professionals, `3` Technicians, `4` Clerical, `5` Service/sales,
  `6` Agriculture, `7` Crafts, `8` Plant operators, `9` Elementary
- SSB API returns JSON-stat2. Values are a flat array; dimensions tell you the index ordering.
  Use `pandas` or manual index arithmetic to reshape into a flat table.
- Some occupation codes have suppressed data (small counts). These appear as `null` in the
  values array. Drop or flag them — do not fill with zero.
- Wages table (11611) is at 2-digit occupation level, not 4-digit. Join on the first 2 digits
  of `styrk_code`. Note this in the CSV (`wage_precision: "2-digit"`).
- All monetary values from SSB are in NOK. Keep them in NOK; label clearly in the UI.
