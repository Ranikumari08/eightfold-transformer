# Projects the merged profile into the Eightfold output schema, mapping internal fields to the target format.

"""
Projector — Stage 5 of the pipeline.

Reads a config JSON (or dict) that describes the desired output shape and
applies it to a merged canonical record.

Config schema (per output field)
---------------------------------
{
    "fields": {
        "<output_field_name>": {
            "from":       "<canonical.path[index]>",  // dotted path + optional [n]
            "normalize":  "date" | "phone" | "skill" | null,
            "on_missing": "null" | "omit" | "error"
        },
        ...
    },
    "include_confidence": true | false
}

Path syntax examples
--------------------
"emails"        → merged["emails"]
"emails[0]"     → merged["emails"][0]
"links.github"  → merged["links"]["github"]
"education[0].institution" → merged["education"][0]["institution"]
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from pipeline import normalizer as _norm


# ---------------------------------------------------------------------------
# Default field projection (used when no config is provided)
# ---------------------------------------------------------------------------

_DEFAULT_FIELDS: dict[str, dict] = {
    "full_name":        {"from": "full_name",        "on_missing": "null"},
    "emails":           {"from": "emails",           "on_missing": "null"},
    "phones":           {"from": "phones",           "on_missing": "null"},
    "location":         {"from": "location",         "on_missing": "null"},
    "current_company":  {"from": "current_company",  "on_missing": "null"},
    "title":            {"from": "title",            "on_missing": "null"},
    "years_experience": {"from": "years_experience", "on_missing": "null"},
    "skills":           {"from": "skills",           "on_missing": "null"},
    "linkedin":         {"from": "links.linkedin",   "on_missing": "null"},
    "github":           {"from": "links.github",     "on_missing": "null"},
    "education":        {"from": "education",        "on_missing": "null"},
    "bio":              {"from": "bio",              "on_missing": "null"},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project(merged: dict, config: dict, include_confidence: bool = True) -> dict:
    """
    Apply a config to a merged canonical record and produce the output dict.

    Args:
        merged:             A merged canonical record (output of merger + confidence).
        config:             A config dict (loaded from JSON).
                            If empty or None, the default field list is used.
        include_confidence: When True, attach "_confidence" and
                            "overall_confidence" to the output.

    Returns:
        The projected output dict.

    Raises:
        ValueError: When a field's "on_missing" policy is "error" and the
                    source path resolves to None.
    """
    if not isinstance(config, dict):
        config = {}

    fields_config: dict = config.get("fields", _DEFAULT_FIELDS)
    # If config exists but has no "fields" key, fall back to defaults.
    if not fields_config:
        fields_config = _DEFAULT_FIELDS

    # Allow config to override include_confidence.
    include_confidence = config.get("include_confidence", include_confidence)

    output: dict[str, Any] = {}

    for output_field, field_spec in fields_config.items():
        if not isinstance(field_spec, dict):
            # Treat bare string as a "from" shorthand.
            field_spec = {"from": str(field_spec), "on_missing": "null"}

        source_path: str = field_spec.get("from", output_field)
        on_missing: str = field_spec.get("on_missing", "null")
        normalize_op: Optional[str] = field_spec.get("normalize")

        # ── Resolve value ─────────────────────────────────────────────────
        value = _resolve_path(merged, source_path)

        # ── Apply normalization ───────────────────────────────────────────
        if value is not None and normalize_op:
            value = _apply_normalize(value, normalize_op)

        # ── Handle missing ────────────────────────────────────────────────
        if value is None:
            if on_missing == "omit":
                continue
            elif on_missing == "error":
                raise ValueError(
                    f"[projector] Required field '{output_field}' (from "
                    f"'{source_path}') is missing in the merged record."
                )
            else:  # "null"
                output[output_field] = None
        else:
            output[output_field] = value

    # ── Confidence passthrough ────────────────────────────────────────────
    if include_confidence:
        output["confidence"] = merged.get("overall_confidence", 0.0)

    # ── Provenance ────────────────────────────────────────────────────────
    if config.get("include_sources", True):
        output["provenance"] = merged.get("provenance", [])

    return output


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Matches "fieldname[0]" → groups: field="fieldname", idx="0"
_RE_INDEX = re.compile(r"^(?P<field>[^\[]+)\[(?P<idx>\d+)\]$")


def _resolve_path(data: dict, path: str) -> Any:
    """
    Resolve a dot-separated and bracket-indexed path against a dictionary.

    Examples:
        "emails"                    → record["emails"]
        "emails[0]"                 → record["emails"][0]
        "links.github"              → record["links"]["github"]
        "education[0].institution"  → record["education"][0]["institution"]

    Returns None if any step in the path is missing or out-of-range.
    """
    if not path:
        return None

    current: Any = data
    parts = path.split(".")

    for part in parts:
        if current is None:
            return None

        # Check for array index syntax: "emails[0]"
        idx_match = _RE_INDEX.match(part)
        if idx_match:
            field = idx_match.group("field")
            idx = int(idx_match.group("idx"))
            current = current.get(field) if isinstance(current, dict) else None
            if isinstance(current, list):
                current = current[idx] if idx < len(current) else None
            else:
                current = None
        else:
            current = current.get(part) if isinstance(current, dict) else None

    return current


# ---------------------------------------------------------------------------
# Inline normalization
# ---------------------------------------------------------------------------

def _apply_normalize(val: Any, norm_type: str) -> Any:
    """
    Apply a named normalizer function to a projected value.

    Supported operations: "date", "phone", "skill".
    Unknown operations are ignored and the value is returned unchanged.
    """
    op = norm_type.strip().lower()

    if op == "date":
        if isinstance(val, str):
            return _norm.normalize_date(val)
        if isinstance(val, list):
            return [_norm.normalize_date(x) for x in val if isinstance(x, str)]
        return val

    if op in ("phone", "e164"):
        if isinstance(val, str):
            return _norm.normalize_phone(val)
        if isinstance(val, list):
            return [_norm.normalize_phone(x) for x in val if isinstance(x, str)]
        return val

    if op in ("skill", "canonical"):
        if isinstance(val, str):
            return _norm.normalize_skill(val)
        if isinstance(val, list):
            return [_norm.normalize_skill(x) for x in val if isinstance(x, str)]
        return val

    return val
