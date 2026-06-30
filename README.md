# Eightfold Transformer

A data pipeline to ingest, normalize, and merge candidate profiles from diverse sources (CSV, ATS JSON, recruiter notes, and GitHub).
Produces a unified, high-confidence candidate record conforming to a custom schema.

## Pipeline

detect → extract → normalize → merge → confidence → project → validate

## Project Structure

eightfold_transformer/
├── main.py                  # CLI entry point
├── sources/                 # one reader per source type
├── pipeline/                # extract, normalize, merge, confidence,
│                            # project, validate
├── config/                  # default + sample runtime configs
├── samples/                 # sample input data
├── tests/                   # pytest edge-case tests
└── output/                  # generated JSON output

## Installation

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## Dependencies

pandas — CSV parsing
phonenumbers — phone normalization to E.164
requests — GitHub API calls
colorama — colored terminal output
python-dateutil — date normalization
pytest — test suite

## Usage

Run with all sources:
```bash
python main.py --csv samples/sample_candidates.csv --ats samples/sample_ats.json --notes samples/sample_recruiter_notes.txt --github aaravmehta --output output/result.json
```

Run with custom config:
```bash
python main.py --csv samples/sample_candidates.csv --config config/sample_config.json --output output/custom_result.json
```
Run with a missing/garbage source (graceful degradation check):
```bash
python main.py --csv samples/doesnotexist.csv --output output/test.json
```
## Running Tests

```bash
pytest tests/
```

## Sample Output

```json
{
  "generated_at": "2026-06-30T08:15:00.000000+00:00",
  "total": 1,
  "candidates": [
    {
      "candidate_id": "C-1A2B3C4D",
      "full_name": "Aarav Mehta",
      "emails": [
        "aarav.mehta@gmail.com"
      ],
      "phones": [
        "+919876543210"
      ],
      "location": "Bengaluru, IN",
      "links": {
        "linkedin": "https://linkedin.com/in/aaravmehta",
        "github": "https://github.com/aaravmehta",
        "blog": null
      },
      "headline": "Software Engineer",
      "years_experience": 3.0,
      "skills": [
        "python",
        "django",
        "postgresql",
        "docker",
        "redis"
      ],
      "education": [
        {
          "institution": "IIT Bombay",
          "degree": "Bachelor of Technology",
          "field": "CSE",
          "end_year": 2021
        }
      ],
      "provenance": [
        {
          "source_name": "csv",
          "applicant_id": null
        },
        {
          "source_name": "ats_json",
          "applicant_id": "ATS-001"
        }
      ],
      "overall_confidence": 1.0
    }
  ]
}
```

## Assumptions

1. The same candidate is matched across sources by email address as the primary key, since email was the only consistently present unique identifier across all four sample sources.
2. Structured sources (CSV, ATS JSON) are treated as more reliable than unstructured sources (recruiter notes, GitHub bio) when resolving conflicting field values.
3. When a field appears in 2+ sources with matching values, confidence is boosted; when sources disagree, the higher-confidence source wins for scalar fields, while list fields (skills, emails) are unioned rather than overwritten.
4. GitHub API calls use unauthenticated public endpoints (api.github.com/users/{username}), which are rate-limited; this is acceptable for a sample/demo scale but would need an auth token for production volume.
5. Country names/codes from different sources (IND, IN, India) are normalized to ISO-3166 alpha-2 (IN).

## Limitations

1. Resume PDF/DOCX parsing is not implemented in this submission — the pipeline supports CSV, ATS JSON, recruiter notes (.txt), and GitHub, which satisfies "at least one from each group," but resume ingestion was descoped under time pressure.
2. Experience entries are not deduplicated when company names differ slightly across sources (e.g. "Infosys" from CSV vs "Infosys Limited" from ATS JSON appear as two separate experience entries instead of being merged into one).
3. experience[].start and experience[].end are always null — none of the sample sources contain explicit employment date ranges, so this field is structurally supported but unpopulated. A resume-parsing source would be the natural way to fill this in.
4. GitHub matching only works by explicit username passed via --github, not by guessing a username from a candidate's name or other fields.
5. Confidence scoring uses a simple weighted heuristic (source reliability + cross-source agreement bonus), not a calibrated probabilistic model.

