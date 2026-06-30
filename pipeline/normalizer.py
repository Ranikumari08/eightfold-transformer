# Normalizes and standardizes extracted field values (e.g., date formats, skill taxonomy, location names).

"""
Normalizer — Stage 2 of the pipeline.

Applies deterministic transformations to canonical records produced by the
extractor.  All normalizations are non-destructive: if a value cannot be
parsed it is left unchanged (never set to None / never crashes).

Normalizations applied
----------------------
phones  → E.164  (+<country_code><number>)  via phonenumbers library.
          Falls back to the original string if parsing fails.
dates   → "YYYY-MM" string.
          Handles: "May 2026", "2026-05", "05/2026", "2026-05-10", etc.
skills  → lowercase + canonical alias mapping.
          e.g. "ML" → "machine-learning", "golang" → "go"
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union

# phonenumbers is an optional but strongly recommended dependency.
try:
    import phonenumbers
    _PHONENUMBERS_AVAILABLE = True
except ImportError:
    _PHONENUMBERS_AVAILABLE = False
    print(
        "[normalizer] WARNING: 'phonenumbers' library not installed. "
        "Phone normalisation will be skipped.  Run: pip install phonenumbers"
    )


# ---------------------------------------------------------------------------
# Skill alias table  (input variants → canonical form)
# ---------------------------------------------------------------------------

_SKILL_ALIASES: dict[str, str] = {
    # ML / AI
    "ml":                    "machine-learning",
    "machine learning":      "machine-learning",
    "machinelearning":       "machine-learning",
    "ai":                    "artificial-intelligence",
    "artificial intelligence": "artificial-intelligence",
    "nlp":                   "natural-language-processing",
    "deep learning":         "deep-learning",
    "deeplearning":          "deep-learning",
    "scikit-learn":          "scikit-learn",
    "scikitlearn":           "scikit-learn",
    "sklearn":               "scikit-learn",
    "tensorflow":            "tensorflow",
    "tf":                    "tensorflow",
    "pytorch":               "pytorch",

    # Go
    "golang":                "go",

    # JavaScript ecosystem
    "nodejs":                "node.js",
    "node":                  "node.js",
    "node js":               "node.js",
    "reactjs":               "react",
    "react js":              "react",
    "react.js":              "react",
    "vuejs":                 "vue",
    "vue.js":                "vue",
    "vue js":                "vue",
    "angularjs":             "angular",
    "angular js":            "angular",
    "nextjs":                "next.js",
    "next js":               "next.js",
    "expressjs":             "express",
    "express.js":            "express",
    "express js":            "express",
    "ts":                    "typescript",
    "js":                    "javascript",

    # Databases
    "postgres":              "postgresql",
    "pg":                    "postgresql",
    "mongo":                 "mongodb",
    "mssql":                 "sql-server",
    "microsoft sql server":  "sql-server",
    "dynamo":                "dynamodb",
    "dynamo db":             "dynamodb",

    # Cloud / infra
    "k8s":                   "kubernetes",
    "gke":                   "kubernetes",
    "amazon web services":   "aws",
    "google cloud":          "gcp",
    "google cloud platform": "gcp",
    "azure cloud":           "azure",
    "docker compose":        "docker",

    # Java ecosystem
    "spring boot":           "spring-boot",
    "springboot":            "spring-boot",
    "spring framework":      "spring",

    # Other
    "c sharp":               "c#",
    "csharp":                "c#",
    "c plus plus":           "c++",
    "cpp":                   "c++",
    "graphql":               "graphql",
    "rest":                  "rest-api",
    "restful":               "rest-api",
    "ci/cd":                 "ci-cd",
    "cicd":                  "ci-cd",
    "microservice":          "microservices",
    "agile scrum":           "agile",
    "product management":    "product-management",
}

_COUNTRY_MAP: dict[str, str] = {
    "india": "IN",
    "ind": "IN",
    "usa": "US",
    "united states": "US",
    "uk": "GB",
    "united kingdom": "GB",
}


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

_MONTH_MAP: dict[str, str] = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}

# "May 2026" or "May, 2026"
_RE_MONTH_YEAR_WORD = re.compile(
    r"(?P<month>[A-Za-z]+)[,\s]+(?P<year>\d{4})"
)
# "2026-05" or "2026-05-10"
_RE_ISO = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})(?:-\d{2})?")
# "05/2026" or "05-2026"
_RE_MM_YYYY = re.compile(r"(?P<month>\d{1,2})[/\-](?P<year>\d{4})")
# "2026/05"
_RE_YYYY_MM_SLASH = re.compile(r"(?P<year>\d{4})/(?P<month>\d{2})")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize(canonical: dict) -> dict:
    """
    Apply all normalizations to a canonical record in-place (returns the same
    dict for convenience).

    Args:
        canonical: A canonical record as produced by extractor.extract().

    Returns:
        The same dict with normalized values.  Never raises.
    """
    try:
        canonical["phones"] = _normalize_phones(canonical.get("phones"))
        canonical["skills"] = _normalize_skills(canonical.get("skills"))

        # Normalize country in location if present
        location = canonical.get("location")
        if isinstance(location, dict) and location.get("country"):
            location["country"] = normalize_country(location["country"])

        # Normalize dates inside education records.
        education = canonical.get("education")
        if isinstance(education, list):
            for edu in education:
                if isinstance(edu, dict) and edu.get("end_year"):
                    edu["end_year_normalized"] = normalize_date(str(edu["end_year"]))

    except Exception as exc:
        print(f"[normalizer] Unexpected error during normalization: {exc}")

    return canonical


def normalize_date(raw: str) -> Optional[str]:
    """
    Parse a date string and return it in "YYYY-MM" format.

    Handles:
        "2026-05-10" → "2026-05"
        "2026-05"    → "2026-05"
        "05/2026"    → "2026-05"
        "May 2026"   → "2026-05"
        "2021"       → "2021-01"  (year only, month defaulted to 01)

    Returns the original string unchanged if it cannot be parsed.
    """
    if not raw:
        return raw
    raw_stripped = str(raw).strip()
    if raw_stripped.lower() == "nan":
        return None

    # ISO: 2026-05 or 2026-05-10
    m = _RE_ISO.fullmatch(raw_stripped) or _RE_ISO.match(raw_stripped)
    if m:
        month = m.group("month").zfill(2)
        if 1 <= int(month) <= 12:
            return f"{m.group('year')}-{month}"

    # YYYY/MM
    m = _RE_YYYY_MM_SLASH.fullmatch(raw_stripped)
    if m:
        month = m.group("month").zfill(2)
        if 1 <= int(month) <= 12:
            return f"{m.group('year')}-{month}"

    # MM/YYYY or MM-YYYY
    m = _RE_MM_YYYY.fullmatch(raw_stripped)
    if m:
        month = m.group("month").zfill(2)
        if 1 <= int(month) <= 12:
            return f"{m.group('year')}-{month}"

    # "May 2026" / "May, 2026"
    m = _RE_MONTH_YEAR_WORD.search(raw_stripped)
    if m:
        month_name = m.group("month").lower()
        year = m.group("year")
        month_num = _MONTH_MAP.get(month_name)
        if month_num:
            return f"{year}-{month_num}"

    # Plain year only: "2021"
    if re.fullmatch(r"\d{4}", raw_stripped):
        return f"{raw_stripped}-01"

    # Cannot parse — return original.
    return raw_stripped


def normalize_phone(raw: str, default_region: str = "IN") -> str:
    """
    Convert a phone string to E.164 format using the phonenumbers library.

    Falls back to the original string if parsing fails.

    Args:
        raw:            Raw phone string in any format.
        default_region: BCP-47 region code used when the number has no
                        country prefix (defaults to "IN" for India).

    Returns:
        E.164 string (e.g. "+919876543210") or the original string.
    """
    if not raw:
        return raw
    
    cleaned = str(raw).strip()
    if cleaned.lower() == "nan":
        return None

    if not _PHONENUMBERS_AVAILABLE:
        return cleaned

    # Try with the provided default region first, then without.
    for region in (default_region, None):
        try:
            parsed = phonenumbers.parse(cleaned, region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
        except Exception:
            continue

    # Cannot parse — return original.
    return raw


def normalize_skill(raw: str) -> str:
    """
    Lowercase a skill token and apply the canonical alias mapping.

    Unknown skills are returned lowercased as-is.

    Args:
        raw: Raw skill string (e.g. "ML", "NodeJS", "Postgres").

    Returns:
        Canonical skill string (e.g. "machine-learning", "node.js", "postgresql").
    """
    if not raw:
        return raw
    lowered = str(raw).strip().lower()
    if lowered == "nan":
        return None
    return _SKILL_ALIASES.get(lowered, lowered)


def normalize_country(raw: str) -> str:
    """Normalize country name to ISO-3166 alpha-2 code."""
    if not raw:
        return raw
    lowered = str(raw).strip().lower()
    if lowered == "nan":
        return None
    return _COUNTRY_MAP.get(lowered, str(raw).strip().upper() if len(str(raw).strip()) == 2 else str(raw).strip())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_phones(phones: Optional[list]) -> Optional[list]:
    if not phones:
        return phones
    return [normalize_phone(str(p)) for p in phones if p is not None]


def _normalize_skills(skills: Optional[list]) -> Optional[list]:
    if not skills:
        return skills
    normalized = [normalize_skill(str(s)) for s in skills if s is not None]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for skill in normalized:
        if skill not in seen:
            seen.add(skill)
            result.append(skill)
    return result if result else None
