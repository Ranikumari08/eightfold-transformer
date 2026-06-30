# Validates the final projected output against schema rules and required field constraints before export.

"""
Validator — Stage 6 of the pipeline.

Validates projected output records against a schema that defines:
  - required fields (absence → ValueError)
  - optional fields (absence → WARNING log)
  - expected types (mismatch → WARNING log, not fatal)

The validator does NOT mutate the record; it returns a ValidationResult
with a list of errors and warnings so the caller can decide how to handle them.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema definition
# ---------------------------------------------------------------------------

# Each entry: (field_name, required, expected_types, description)
# expected_types = None means any type is accepted.
_SCHEMA: list[tuple[str, bool, Optional[tuple], str]] = [
    ("full_name",        True,  (str,),              "Candidate's full name"),
    ("emails",           False,  (list,),             "List of email addresses"),
    ("phones",           False, (list,),             "List of phone numbers in E.164"),
    ("location",         False, (dict,),             "Structured location object"),
    ("current_company",  False, (str,),              "Current or most recent employer"),
    ("title",            False, (str,),              "Job title / designation"),
    ("years_experience", False, (int, float),        "Total years of professional experience"),
    ("skills",           False, (list,),             "Normalised skill list"),
    ("experience",       False, (list,),             "List of experience records"),
    ("linkedin",         False, (str,),              "LinkedIn profile URL"),
    ("github",           False, (str,),              "GitHub profile URL"),
    ("education",        False, (list,),             "List of education records"),
    ("bio",              False, (str,),              "Free-text biography or notes"),
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Holds the outcome of a single record validation."""
    is_valid: bool = True
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(record: dict, strict: bool = True) -> ValidationResult:
    """
    Validate a single projected output record against the canonical schema.

    Args:
        record: The projected output dict (from projector.project()).
        strict: When True (default), missing required fields cause a
                ValueError to be raised after collecting all violations.
                When False, errors are only collected in the result.

    Returns:
        A ValidationResult with .is_valid, .errors, and .warnings.

    Raises:
        ValueError: (only when strict=True) if any required field is absent.
        TypeError:  Never — type mismatches are treated as warnings.
    """
    result = ValidationResult()

    for field_name, required, expected_types, description in _SCHEMA:
        value = record.get(field_name)
        present = _is_present(value)

        # ── Presence check ─────────────────────────────────────────────────
        if not present:
            if required:
                msg = (
                    f"Required field '{field_name}' ({description}) is "
                    f"missing or null in the output record."
                )
                result.add_error(msg)
                logger.error("[validator] %s", msg)
            else:
                msg = f"Optional field '{field_name}' ({description}) is not present."
                result.add_warning(msg)
                logger.debug("[validator] %s", msg)
            continue

        # ── Type check (only when field is present) ────────────────────────
        if expected_types is not None and not isinstance(value, expected_types):
            type_names = " | ".join(t.__name__ for t in expected_types)
            msg = (
                f"Field '{field_name}' has unexpected type "
                f"'{type(value).__name__}' (expected: {type_names})."
            )
            result.add_warning(msg)
            logger.warning("[validator] %s", msg)

        # ── List content checks ────────────────────────────────────────────
        if isinstance(value, list):
            if len(value) == 0:
                msg = f"Field '{field_name}' is an empty list."
                result.add_warning(msg)
                logger.warning("[validator] %s", msg)

    # ── Raise on fatal errors when strict mode is on ───────────────────────
    if strict and not result.is_valid:
        error_summary = "; ".join(result.errors)
        raise ValueError(
            f"[validator] Validation failed with {len(result.errors)} error(s): "
            f"{error_summary}"
        )

    return result


def validate_many(
    records: list[dict],
    strict: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Validate a list of projected records.

    Args:
        records: List of projected output dicts.
        strict:  When True, the first invalid record raises a ValueError.
                 When False (default), invalid records are separated out.

    Returns:
        A tuple of (valid_records, invalid_records).
    """
    valid: list[dict] = []
    invalid: list[dict] = []

    for i, record in enumerate(records):
        try:
            result = validate(record, strict=strict)
            if result.is_valid:
                valid.append(record)
            else:
                logger.warning(
                    "[validator] Record %d failed validation: %s",
                    i,
                    result.errors,
                )
                invalid.append(record)
        except ValueError as exc:
            logger.error("[validator] Record %d raised: %s", i, exc)
            raise

    return valid, invalid


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_present(value: Any) -> bool:
    """Return True if value is a meaningful, non-empty value."""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, dict)) and not value:
        # Empty collections count as absent for presence purposes.
        return False
    return True
