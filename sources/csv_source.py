"""
Reads and parses candidate/job data from CSV files into a standardized raw record format.
"""

import pandas as pd
from typing import Any, Dict, List, Optional, Tuple, Type, Union


# Columns we expect in the CSV; any missing ones will be filled with None.
EXPECTED_COLUMNS = [
    "name",
    "email",
    "phone",
    "current_company",
    "title",
    "linkedin",
    "github",
    "location_city",
    "location_country",
    "years_experience",
    "skills",
    "education_institution",
    "education_degree",
    "education_field",
    "education_end_year",
]


def read_csv_source(filepath: str) -> list[dict]:
    """
    Read a CSV file of candidates and return a list of raw candidate dicts.

    Each dict follows the common raw format:
        {
            "source_name": "csv",
            "raw_data": { ...all extracted fields... }
        }

    Missing columns are filled with None; rows that are entirely empty are
    skipped silently.

    Args:
        filepath: Absolute or relative path to the CSV file.

    Returns:
        A list of raw candidate dicts (may be empty if the file has no data rows).
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
    except FileNotFoundError:
        print(f"[csv_source] File not found: {filepath}")
        return []
    except Exception as exc:
        print(f"[csv_source] Failed to read '{filepath}': {exc}")
        return []

    # Add any missing expected columns as NaN so downstream code can rely on them.
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Replace pandas NaN / empty strings with Python None for consistency.
    df = df.where(pd.notna(df), other=None)

    records: list[dict] = []

    for _, row in df.iterrows():
        # Skip rows where every expected field is missing.
        values = [row.get(col) for col in EXPECTED_COLUMNS]
        if all(v is None or (isinstance(v, str) and v.strip() == "") for v in values):
            continue

        # Parse skills string into a list if present.
        skills_raw: Optional[str] = row.get("skills")
        skills: Optional[list[str]] = (
            [s.strip() for s in skills_raw.split(",") if s.strip()]
            if skills_raw
            else None
        )

        raw_data = {
            "full_name": _str_or_none(row.get("name")),
            "emails": [row["email"]] if _str_or_none(row.get("email")) else None,
            "phones": [row["phone"]] if _str_or_none(row.get("phone")) else None,
            "current_company": _str_or_none(row.get("current_company")),
            "title": _str_or_none(row.get("title")),
            "location": {
                "city": _str_or_none(row.get("location_city")),
                "region": None,
                "country": _str_or_none(row.get("location_country")),
            },
            "years_experience": _float_or_none(row.get("years_experience")),
            "skills": skills,
            "links": {
                "linkedin": _str_or_none(row.get("linkedin")),
                "github": _str_or_none(row.get("github")),
            },
            "education": {
                "institution": _str_or_none(row.get("education_institution")),
                "degree": _str_or_none(row.get("education_degree")),
                "field": _str_or_none(row.get("education_field")),
                "end_year": _int_or_none(row.get("education_end_year")),
            },
        }

        records.append({"source_name": "csv", "raw_data": raw_data})

    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_or_none(value) -> Optional[str]:
    """Return stripped string or None if blank / NaN."""
    if value is None or pd.isna(value):
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _float_or_none(value) -> Optional[float]:
    """Coerce to float or return None."""
    if value is None or pd.isna(value):
        return None
    try:
        f = float(value)
        return None if pd.isna(f) else f
    except (ValueError, TypeError):
        return None


def _int_or_none(value) -> Optional[int]:
    """Coerce to int or return None."""
    if value is None or pd.isna(value):
        return None
    try:
        f = float(value)
        return None if pd.isna(f) else int(f)
    except (ValueError, TypeError):
        return None



