# Extracts structured fields (skills, experience, education, etc.) from raw source records.

"""
Extractor — Stage 1 of the pipeline.

Takes a raw source record (output of any sources/*.py reader) and maps its
fields to the canonical schema.  Unknown fields are dropped; missing fields
are set to None.  This stage never raises.

Canonical schema
----------------
{
    "full_name":        str | None,
    "emails":           list[str] | None,
    "phones":           list[str] | None,
    "location":         str | None,
    "current_company":  str | None,
    "title":            str | None,
    "years_experience": float | None,
    "skills":           list[str] | None,
    "links": {
        "linkedin":     str | None,
        "github":       str | None,
        "blog":         str | None,
    },
    "education":        list[dict] | None,
    "bio":              str | None,
    "avatar_url":       str | None,
    "_meta": {
        "source_name":  str,
        "applicant_id": str | None,
    }
}
"""

from typing import Any, Dict, List, Optional, Tuple, Type, Union


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract(raw_record: dict) -> dict:
    """
    Map one raw source record to the canonical schema.

    Args:
        raw_record: A dict with keys "source_name" and "raw_data" as produced
                    by any sources/*.py reader.

    Returns:
        A canonical record dict.  Always succeeds; never raises.
    """
    try:
        source_name: str = raw_record.get("source_name", "unknown")
        raw_data: dict = raw_record.get("raw_data") or {}

        dispatcher = {
            "csv":      _extract_csv,
            "ats_json": _extract_ats_json,
            "txt":      _extract_txt,
            "github":   _extract_github,
        }

        extractor_fn = dispatcher.get(source_name, _extract_generic)
        canonical = extractor_fn(raw_data)

        # Always attach metadata.
        canonical["_meta"] = {
            "source_name":  source_name,
            "applicant_id": _v(raw_data.get("applicant_id")),
        }

        return canonical

    except Exception as exc:
        print(f"[extractor] Unexpected error: {exc}")
        return _empty_canonical()


def extract_many(raw_records: list[dict]) -> list[dict]:
    """Convenience wrapper: extract a list of raw records."""
    return [extract(r) for r in raw_records]


# ---------------------------------------------------------------------------
# Per-source extractors
# ---------------------------------------------------------------------------

def _extract_csv(d: dict) -> dict:
    """Extract fields from a CSV raw data record."""
    edu_raw = d.get("education") or {}
    education = None
    if isinstance(edu_raw, dict) and any(edu_raw.values()):
        education = [edu_raw]
    elif isinstance(edu_raw, list):
        education = edu_raw or None

    return _canonical(
        full_name       = _v(d.get("full_name")),
        emails          = _list_or_none(d.get("emails")),
        phones          = _list_or_none(d.get("phones")),
        location        = d.get("location") if isinstance(d.get("location"), dict) else None,
        current_company = _v(d.get("current_company")),
        title           = _v(d.get("title")),
        years_experience= _float(d.get("years_experience")),
        skills          = _list_or_none(d.get("skills")),
        links           = _extract_links(d.get("links")),
        education       = education,
        bio             = None,
        avatar_url      = None,
    )


def _extract_ats_json(d: dict) -> dict:
    """Extract fields from an ATS JSON raw data record."""
    edu_raw = d.get("education")
    education = edu_raw if isinstance(edu_raw, list) and edu_raw else None

    return _canonical(
        full_name       = _v(d.get("full_name")),
        emails          = _list_or_none(d.get("emails")),
        phones          = _list_or_none(d.get("phones")),
        location        = d.get("location") if isinstance(d.get("location"), dict) else None,
        current_company = _v(d.get("current_company")),
        title           = _v(d.get("title")),
        years_experience= _float(d.get("years_experience")),
        skills          = _list_or_none(d.get("skills")),
        links           = _extract_links(d.get("links")),
        education       = education,
        bio             = None,
        avatar_url      = None,
    )


def _extract_txt(d: dict) -> dict:
    """Extract fields from a TXT raw data record."""
    return _canonical(
        full_name       = _v(d.get("full_name")),
        emails          = _list_or_none(d.get("emails")),
        phones          = _list_or_none(d.get("phones")),
        location        = None,       # txt notes don't contain structured location
        current_company = None,
        title           = None,
        years_experience= None,
        skills          = _list_or_none(d.get("skills")),
        links           = None,
        education       = None,
        bio             = _v(d.get("notes_raw")),
        avatar_url      = None,
    )


def _extract_github(d: dict) -> dict:
    """Extract fields from a GitHub raw data record."""
    # top_languages from GitHub become skills in the canonical record.
    gh_skills = _list_or_none(d.get("top_languages"))

    return _canonical(
        full_name       = _v(d.get("full_name")),
        emails          = _list_or_none(d.get("emails")),
        phones          = None,
        location        = d.get("location") if isinstance(d.get("location"), dict) else None,
        current_company = None,
        title           = None,
        years_experience= None,
        skills          = gh_skills,
        links           = _extract_links(d.get("links")),
        education       = None,
        bio             = _v(d.get("bio")),
        avatar_url      = _v(d.get("avatar_url")),
    )


def _extract_generic(d: dict) -> dict:
    """Fallback: best-effort mapping for unknown source types."""
    return _canonical(
        full_name       = _v(d.get("full_name") or d.get("name")),
        emails          = _list_or_none(d.get("emails") or d.get("email")),
        phones          = _list_or_none(d.get("phones") or d.get("phone")),
        location        = d.get("location") if isinstance(d.get("location"), dict) else None,
        current_company = _v(d.get("current_company") or d.get("company")),
        title           = _v(d.get("title") or d.get("designation")),
        years_experience= _float(d.get("years_experience")),
        skills          = _list_or_none(d.get("skills")),
        links           = _extract_links(d.get("links")),
        education       = None,
        bio             = _v(d.get("bio")),
        avatar_url      = None,
    )


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _canonical(
    full_name: Optional[str],
    emails: Optional[list],
    phones: Optional[list],
    location: Optional[dict],
    current_company: Optional[str],
    title: Optional[str],
    years_experience: Optional[float],
    skills: Optional[list],
    links: Optional[dict],
    education: Optional[list],
    bio: Optional[str],
    avatar_url: Optional[str],
    experience: Optional[list] = None,
) -> dict:
    """Helper to construct a canonical schema dict with exact keys."""
    return {
        "full_name":        full_name,
        "emails":           emails,
        "phones":           phones,
        "location":         location,
        "current_company":  current_company,
        "title":            title,
        "experience":       experience or ([{
            "company": current_company,
            "title": title,
            "start": None,
            "end": None,
            "summary": None
        }] if current_company or title else None),
        "years_experience": years_experience,
        "skills":           skills,
        "links":            links or {"linkedin": None, "github": None, "blog": None},
        "education":        education,
        "bio":              bio,
        "avatar_url":       avatar_url,
    }


def _empty_canonical() -> dict:
    """Return a canonical schema dict with all fields set to None."""
    return _canonical(
        full_name=None, emails=None, phones=None, location=None,
        current_company=None, title=None, years_experience=None,
        skills=None, links=None, education=None, bio=None, avatar_url=None,
    )


def _extract_links(links_raw: Any) -> dict:
    """Extract specific link types from a raw links dictionary."""
    if not isinstance(links_raw, dict):
        return {"linkedin": None, "github": None, "blog": None}
    return {
        "linkedin": _v(links_raw.get("linkedin")),
        "github":   _v(links_raw.get("github")),
        "blog":     _v(links_raw.get("blog")),
    }


def _v(value: Any) -> Optional[str]:
    """Return stripped string or None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _list_or_none(value: Any) -> Optional[list]:
    """Return a non-empty list or None."""
    if isinstance(value, list):
        cleaned = [item for item in value if item is not None]
        return cleaned if cleaned else None
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else None
    return None
