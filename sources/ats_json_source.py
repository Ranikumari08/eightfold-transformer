"""
Reads and parses candidate/job data exported from ATS systems in JSON format into a standardized raw record format.
"""

import json
from typing import Any, Dict, List, Optional, Tuple, Type, Union


def read_ats_json_source(filepath: str) -> list[dict]:
    """
    Read an ATS JSON export and return a list of raw candidate dicts.

    Field mapping applied:
        personal.first + personal.last       → full_name
        personal.contact_email               → emails
        personal.mobile                      → phones
        personal.city + personal.country_code → location
        professional.tech_tags               → skills
        professional.total_exp_months / 12   → years_experience
        social.li_url                        → links.linkedin
        social.gh_url                        → links.github

    Each dict follows the common raw format:
        {
            "source_name": "ats_json",
            "raw_data": { ...all extracted fields... }
        }

    Args:
        filepath: Absolute or relative path to the ATS JSON file.

    Returns:
        A list of raw candidate dicts (may be empty on error or empty input).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"[ats_json_source] File not found: {filepath}")
        return []
    except json.JSONDecodeError as exc:
        print(f"[ats_json_source] Invalid JSON in '{filepath}': {exc}")
        return []
    except Exception as exc:
        print(f"[ats_json_source] Failed to read '{filepath}': {exc}")
        return []

    applicants = data.get("applicants", [])
    if not isinstance(applicants, list):
        print("[ats_json_source] 'applicants' key is missing or not a list.")
        return []

    records: list[dict] = []

    for applicant in applicants:
        if not isinstance(applicant, dict):
            continue

        personal = applicant.get("personal") or {}
        professional = applicant.get("professional") or {}
        social = applicant.get("social") or {}
        academics = applicant.get("academics") or []

        # ── full_name ──────────────────────────────────────────────────────
        first = _str_or_none(personal.get("first"))
        last = _str_or_none(personal.get("last"))
        full_name = " ".join(p for p in [first, last] if p) or None

        # ── contact info ───────────────────────────────────────────────────
        email = _str_or_none(personal.get("contact_email"))
        mobile = _str_or_none(personal.get("mobile"))

        # ── location ───────────────────────────────────────────────────────
        city = _str_or_none(personal.get("city"))
        country_code = _str_or_none(personal.get("country_code"))
        location = {
            "city": city,
            "region": None,
            "country": country_code,
        }

        # ── professional ───────────────────────────────────────────────────
        tech_tags = professional.get("tech_tags")
        skills = (
            [str(t).strip() for t in tech_tags if t]
            if isinstance(tech_tags, list)
            else None
        )

        total_exp_months = professional.get("total_exp_months")
        years_experience: Optional[float] = (
            round(total_exp_months / 12, 2)
            if isinstance(total_exp_months, (int, float)) and total_exp_months is not None
            else None
        )

        # ── social links ───────────────────────────────────────────────────
        linkedin = _str_or_none(social.get("li_url"))
        github = _str_or_none(social.get("gh_url"))

        # ── education (preserve list from ATS) ────────────────────────────
        education_list = [
            {
                "institution": _str_or_none(edu.get("inst")),
                "degree": _str_or_none(edu.get("qual")),
                "field": _str_or_none(edu.get("stream")),
                "end_year": edu.get("pass_year"),
            }
            for edu in academics
            if isinstance(edu, dict)
        ]

        raw_data = {
            "applicant_id": _str_or_none(applicant.get("applicant_id")),
            "full_name": full_name,
            "emails": [email] if email else None,
            "phones": [mobile] if mobile else None,
            "location": location,
            "current_company": _str_or_none(professional.get("current_employer")),
            "title": _str_or_none(professional.get("designation")),
            "years_experience": years_experience,
            "skills": skills,
            "links": {
                "linkedin": linkedin,
                "github": github,
            },
            "education": education_list if education_list else None,
        }

        records.append({"source_name": "ats_json", "raw_data": raw_data})

    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str_or_none(value) -> Optional[str]:
    """Return stripped string or None if blank / null."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
