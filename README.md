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
│                             #   project, validate
├── config/                  # default + sample runtime configs
├── samples/                 # sample input data
├── tests/                   # pytest edge-case tests
└── output/                  # generated JSON output

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Run with all sources:
```bash
python main.py --csv samples/sample_candidates.csv --ats samples/sample_ats.json --notes samples/sample_recruiter_notes.txt --github aaravmehta --output output/result.json
```

Run with custom config:
```bash
python main.py --csv samples/sample_candidates.csv --config config/sample_config.json --output output/custom_result.json
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
