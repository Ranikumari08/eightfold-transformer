# Computes confidence scores for extracted and merged fields based on source reliability and data completeness.

"""
Confidence — Stage 4 of the pipeline.

Assigns a per-field confidence score (0.0 – 1.0) to each canonical record
and an overall_confidence as the average of all scored fields.

Scoring rules
-------------
Base confidence by source:
    csv       → 0.80
    ats_json  → 0.85
    txt       → 0.60
    github    → 0.75
    unknown   → 0.50

Cross-source bonuses (applied when the field is present in multiple sources
within the merged _sources list):
    field present in 2+ sources → +0.10
    field present in 3+ sources → +0.15  (replaces, not stacks, the 2+ bonus)

All scores are capped at 1.0.
"""

from typing import Any, Dict, List, Optional, Tuple, Type, Union


# ---------------------------------------------------------------------------
# Base confidence per source
# ---------------------------------------------------------------------------

_BASE_CONFIDENCE: dict[str, float] = {
    "csv":      0.80,
    "ats_json": 0.85,
    "txt":      0.60,
    "github":   0.75,
}
_DEFAULT_BASE = 0.50

# Fields we score (must map 1-to-1 with canonical schema fields).
_SCORED_FIELDS = [
    "full_name",
    "emails",
    "phones",
    "location",
    "current_company",
    "title",
    "years_experience",
    "skills",
    "links",
    "education",
    "bio",
    "avatar_url",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score(canonical: dict) -> dict:
    """
    Attach per-field confidence scores and overall_confidence to *canonical*.

    This function is designed to be called on a *single-source* extracted
    record (before merging) so that the merger can carry individual scores.

    Args:
        canonical: A canonical record produced by extractor.extract().

    Returns:
        The same dict with "_confidence" and "overall_confidence" populated.
        Never raises.
    """
    try:
        meta = canonical.get("_meta") or {}
        source_name = meta.get("source_name", "unknown")
        base = _BASE_CONFIDENCE.get(source_name, _DEFAULT_BASE)

        field_scores: dict[str, float] = {}

        for field in _SCORED_FIELDS:
            val = canonical.get(field)
            if _field_has_value(val):
                field_scores[field] = min(base, 1.0)
            # Fields absent from the record are not scored (no entry in dict).

        canonical["_confidence"] = field_scores
        canonical["overall_confidence"] = _average(field_scores)

    except Exception as exc:
        print(f"[confidence] Unexpected error: {exc}")
        canonical.setdefault("_confidence", {})
        canonical.setdefault("overall_confidence", 0.0)

    return canonical


def score_merged(merged: dict, all_records: list[dict]) -> dict:
    """
    Compute confidence scores for a *merged* record, applying cross-source
    bonuses where the same field appears in multiple contributing sources.

    Args:
        merged:      The merged canonical record (output of merger.merge()).
        all_records: The individual per-source canonical records that were
                     merged together (used to count source coverage per field).

    Returns:
        The merged dict with updated "_confidence" and "overall_confidence".
        Never raises.
    """
    try:
        source_names = set()
        for p in (merged.get("provenance") or []):
            for s in p.get("source", "").split(","):
                if s:
                    source_names.add(s)
        source_names = list(source_names)

        # Build a base score for the merged record using the most-trusted source.
        best_base = max(
            (_BASE_CONFIDENCE.get(sn, _DEFAULT_BASE) for sn in source_names),
            default=_DEFAULT_BASE,
        )

        # Count how many sources provided a non-null value for each field.
        field_source_counts = _count_field_sources(all_records)

        field_scores: dict[str, float] = {}

        for field in _SCORED_FIELDS:
            val = merged.get(field)
            if not _field_has_value(val):
                continue

            score_val = best_base

            # Cross-source bonus.
            count = field_source_counts.get(field, 1)
            if count >= 3:
                score_val += 0.15
            elif count >= 2:
                score_val += 0.10

            field_scores[field] = min(score_val, 1.0)

        merged["_confidence"] = field_scores
        merged["overall_confidence"] = _average(field_scores)

    except Exception as exc:
        print(f"[confidence] Unexpected error during merged scoring: {exc}")
        merged.setdefault("_confidence", {})
        merged.setdefault("overall_confidence", 0.0)

    return merged


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _field_has_value(val: Any) -> bool:
    """Check if a field value is non-empty and non-null."""
    if val is None:
        return False
    if isinstance(val, (list, dict)) and not val:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    # For links dict: check that at least one sub-value is non-None.
    if isinstance(val, dict):
        return any(v is not None for v in val.values())
    return True


def _count_field_sources(records: list[dict]) -> dict[str, int]:
    """Count how many distinct source records provided a non-empty value for each field."""
    counts: dict[str, int] = {}
    for record in records:
        for field in _SCORED_FIELDS:
            if _field_has_value(record.get(field)):
                counts[field] = counts.get(field, 0) + 1
    return counts


def _average(scores: dict[str, float]) -> float:
    """Calculate the average confidence score across all scored fields."""
    if not scores:
        return 0.0
    return round(sum(scores.values()) / len(scores), 4)
