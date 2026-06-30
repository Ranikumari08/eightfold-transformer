# Entry point for the Eightfold Transformer pipeline: loads config, orchestrates source ingestion, and runs the full transformation pipeline.

"""
main.py — Eightfold Transformer CLI

Usage examples
--------------
# All sources together
python main.py --csv samples/sample_candidates.csv ^
               --ats samples/sample_ats.json ^
               --notes samples/sample_recruiter_notes.txt

# GitHub only
python main.py --github torvalds

# CSV + custom config, filtered to one candidate
python main.py --csv samples/sample_candidates.csv ^
               --config config/sample_config.json ^
               --candidate "Aarav Mehta"

# All sources, custom output path
python main.py --csv samples/sample_candidates.csv ^
               --ats samples/sample_ats.json ^
               --output output/candidates_2026.json
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type, Union


# Pipeline stages
from pipeline.extractor  import extract
from pipeline.normalizer import normalize
from pipeline.merger     import merge_all
from pipeline.confidence import score as confidence_score, score_merged
from pipeline.projector  import project
from pipeline.validator  import validate_many, ValidationResult

# Source readers
from sources.csv_source      import read_csv_source
from sources.ats_json_source import read_ats_json_source
from sources.txt_source      import read_txt_source
from sources.github_source   import read_github_source


# ============================================================================
# ANSI colour helpers  (no third-party dep; works in Windows Terminal / PS7)
# ============================================================================

_COLOURS_ENABLED = (
    sys.stdout.isatty()
    or os.environ.get("FORCE_COLOR", "").lower() in ("1", "true", "yes")
)

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_DIM    = "\033[2m"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI codes when colour output is enabled."""
    if not _COLOURS_ENABLED:
        return text
    return "".join(codes) + text + _RESET


def ok(msg: str)   -> None: print(_c(f"  [OK]  {msg}", _GREEN))
def warn(msg: str) -> None: print(_c(f"  [!!]  {msg}", _YELLOW))
def err(msg: str)  -> None: print(_c(f"  [ERR] {msg}", _RED))
def info(msg: str) -> None: print(_c(f"  [ ]   {msg}", _DIM))
def head(msg: str) -> None: print(_c(f"\n{msg}", _BOLD, _CYAN))


# ============================================================================
# Config helpers
# ============================================================================

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "config", "default_config.json"
)


def _load_config(path: Optional[str]) -> dict:
    """Load and return the pipeline config from *path* (or the default)."""
    target = path or _DEFAULT_CONFIG_PATH
    try:
        with open(target, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        info(f"Config loaded: {target}")
        return cfg
    except FileNotFoundError:
        warn(f"Config not found at '{target}' — using built-in defaults.")
        return {}
    except json.JSONDecodeError as exc:
        warn(f"Config JSON parse error ({exc}) — using built-in defaults.")
        return {}


def _config_to_projector_format(cfg: dict) -> dict:
    """
    Convert the list-of-field-objects config format to the dict format
    expected by projector.project().

    Input field object keys:
        path      → output field name AND default source path
        from      → source path override (optional)
        type      → ignored here (used by validator)
        required  → True  → on_missing "error"
                    False → use global on_missing (default "null")
        normalize → "E164" | "canonical" | "date" → mapped to projector ops
        on_missing → explicit override

    Also injects the global on_missing and include_confidence settings.
    """
    fields_list = cfg.get("fields", [])
    global_on_missing = cfg.get("on_missing", "null")

    # Normalizer operation aliases used in config → projector operation names.
    _NORMALIZE_MAP = {
        "e164":      "phone",
        "canonical": "skill",
        "date":      "date",
        "phone":     "phone",
        "skill":     "skill",
    }

    if isinstance(fields_list, dict):
        # Already in projector-native dict format — pass through.
        return cfg

    projector_fields: dict[str, dict] = {}

    for field_def in fields_list:
        if not isinstance(field_def, dict):
            continue

        output_name  = field_def.get("path") or field_def.get("name")
        if not output_name:
            continue

        source_path  = field_def.get("from") or output_name
        required     = field_def.get("required", False)
        normalize_op = field_def.get("normalize")
        on_missing   = field_def.get("on_missing")

        # Resolve on_missing policy.
        if on_missing is None:
            on_missing = "error" if required else global_on_missing

        # Map normalize alias.
        normalized_op = None
        if normalize_op:
            normalized_op = _NORMALIZE_MAP.get(normalize_op.lower())

        spec: dict = {
            "from":       source_path,
            "on_missing": on_missing,
        }
        if normalized_op:
            spec["normalize"] = normalized_op

        projector_fields[output_name] = spec

    return {
        "fields":             projector_fields or None,   # None → projector uses its defaults
        "include_confidence": cfg.get("include_confidence", True),
        "include_sources":    cfg.get("include_sources", True),
    }


# ============================================================================
# Candidate ID generation
# ============================================================================

def _make_candidate_id(merged: dict, index: int) -> str:
    """
    Generate a short deterministic ID for a candidate.

    Priority: first email → full_name → sequential index.
    """
    emails = merged.get("emails")
    if isinstance(emails, list) and emails:
        raw = emails[0].strip().lower()
        return "C-" + hashlib.md5(raw.encode()).hexdigest()[:8].upper()

    name = merged.get("full_name")
    if name:
        raw = name.strip().lower()
        return "C-" + hashlib.md5(raw.encode()).hexdigest()[:8].upper()

    return f"C-{index + 1:04d}"


# ============================================================================
# Source loading
# ============================================================================

def _load_sources(args: argparse.Namespace) -> list[dict]:
    """
    Run every requested source reader and return the combined list of raw
    records.  Source failures print an error but never crash the pipeline.
    """
    raw_records: list[dict] = []

    if args.csv:
        head("Loading CSV source")
        try:
            records = read_csv_source(args.csv)
            ok(f"CSV: {len(records)} record(s) read from '{args.csv}'")
            raw_records.extend(records)
        except Exception as exc:
            err(f"CSV source failed: {exc}")

    if args.ats:
        head("Loading ATS JSON source")
        try:
            records = read_ats_json_source(args.ats)
            ok(f"ATS JSON: {len(records)} record(s) read from '{args.ats}'")
            raw_records.extend(records)
        except Exception as exc:
            err(f"ATS JSON source failed: {exc}")

    if args.notes:
        head("Loading recruiter notes source")
        try:
            records = read_txt_source(args.notes)
            ok(f"Recruiter notes: {len(records)} record(s) read from '{args.notes}'")
            raw_records.extend(records)
        except Exception as exc:
            err(f"Recruiter notes source failed: {exc}")

    if args.github:
        head("Loading GitHub source")
        try:
            record = read_github_source(args.github)
            if record:
                ok(f"GitHub: profile fetched for '{args.github}'")
                raw_records.append(record)
            else:
                warn(f"GitHub: no data returned for username '{args.github}'")
        except Exception as exc:
            err(f"GitHub source failed: {exc}")

    return raw_records


# ============================================================================
# Pipeline execution
# ============================================================================

def _run_pipeline(
    raw_records: list[dict],
    projector_cfg: dict,
    candidate_filter: Optional[str],
) -> tuple[list[dict], list[dict]]:
    """
    Execute all pipeline stages and return (valid_outputs, invalid_outputs).

    Stages:
        1. Extract  — raw → canonical
        2. Normalize — phones, dates, skills
        3. Confidence score (pre-merge, per source)
        4. Merge — group by candidate identity
        5. Confidence score (post-merge, with cross-source bonuses)
        6. Inject candidate_id
        7. Filter by candidate name (if --candidate flag used)
        8. Project — apply config field mapping
        9. Validate — check required fields & types
    """

    # ── Stage 1 & 2: Extract + Normalize ────────────────────────────────────
    head("Stage 1 & 2 — Extract + Normalize")
    canonical_records: list[dict] = []
    for raw in raw_records:
        canonical = extract(raw)
        canonical = normalize(canonical)
        canonical_records.append(canonical)
    ok(f"{len(canonical_records)} canonical record(s) produced")

    # ── Stage 3: Per-source confidence scoring ───────────────────────────────
    head("Stage 3 — Confidence scoring (per source)")
    for rec in canonical_records:
        confidence_score(rec)
    ok("Per-source confidence scores assigned")

    # ── Stage 4: Merge ───────────────────────────────────────────────────────
    head("Stage 4 — Merge candidates")
    merged_records = merge_all(canonical_records)
    ok(f"{len(merged_records)} unique candidate(s) after merging")

    # ── Stage 5: Post-merge confidence ──────────────────────────────────────
    head("Stage 5 — Confidence scoring (post-merge)")
    for merged in merged_records:
        # Collect the contributing source records for cross-source bonus.
        source_names = set()
        for p in (merged.get("provenance") or []):
            for s in p.get("source", "").split(","):
                if s:
                    source_names.add(s)
        contributing = [
            r for r in canonical_records
            if (r.get("_meta") or {}).get("source_name") in source_names
        ]
        score_merged(merged, contributing)
    ok("Post-merge confidence scores with cross-source bonuses applied")

    # ── Stage 6: Inject candidate_id ────────────────────────────────────────
    for i, merged in enumerate(merged_records):
        merged["candidate_id"] = _make_candidate_id(merged, i)

    # ── Stage 7: Candidate filter ────────────────────────────────────────────
    if candidate_filter:
        head(f"Stage 7 — Filtering by name: '{candidate_filter}'")
        needle = candidate_filter.strip().lower()
        filtered = [
            r for r in merged_records
            if needle in (r.get("full_name") or "").lower()
        ]
        info(
            f"{len(filtered)} of {len(merged_records)} candidate(s) match "
            f"filter '{candidate_filter}'"
        )
        merged_records = filtered
        if not merged_records:
            warn(f"No candidates matched filter '{candidate_filter}'")

    # ── Stage 8: Project ────────────────────────────────────────────────────
    head("Stage 8 — Projector")
    projected: list[dict] = []
    include_conf = projector_cfg.get("include_confidence", True)

    for merged in merged_records:
        try:
            output = project(merged, projector_cfg, include_confidence=include_conf)
            projected.append(output)
        except ValueError as exc:
            err(f"Projection error for '{merged.get('full_name', '?')}': {exc}")

    ok(f"{len(projected)} record(s) projected")

    # ── Stage 9: Validate ────────────────────────────────────────────────────
    head("Stage 9 — Validate")
    valid, invalid = validate_many(projected, strict=False)

    if valid:
        ok(f"{len(valid)} record(s) passed validation")
    if invalid:
        warn(f"{len(invalid)} record(s) failed validation (see warnings above)")

    return valid, invalid


# ============================================================================
# Output
# ============================================================================

def _write_output(records: list[dict], path: str) -> None:
    """Write the list of output records to a JSON file at *path*."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total":        len(records),
                "candidates":   records,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )


def _print_summary(valid: list[dict], invalid: list[dict], output_path: str, elapsed: float) -> None:
    """Print a concise terminal summary after the pipeline completes."""
    head("-" * 56)
    total = len(valid) + len(invalid)
    print(_c(f"\n  Pipeline completed in {elapsed:.2f}s\n", _BOLD))
    print(f"  Total candidates processed : {_c(str(total), _BOLD)}")
    print(f"  Valid records              : {_c(str(len(valid)),   _GREEN  if valid   else _DIM)}")
    print(f"  Invalid records            : {_c(str(len(invalid)), _RED    if invalid else _DIM)}")
    print()

    if valid:
        ok(f"Output written -> {output_path}")
        print()

    # Per-candidate mini table
    if valid:
        col_w = 30
        header = (
            f"  {'Candidate':<{col_w}}  {'Email':<35}  {'Conf':>5}  Sources"
        )
        print(_c(header, _DIM))
        print(_c("  " + "-" * (col_w + 55), _DIM))
        for rec in valid:
            name     = (rec.get("full_name") or rec.get("candidate_id") or "?")[:col_w]
            email    = ((rec.get("emails") or rec.get("primary_email") or [""])[0]
                        if isinstance(rec.get("emails"), list)
                        else (rec.get("primary_email") or ""))[:35]
            conf     = rec.get("confidence", rec.get("overall_confidence", 0.0))
            conf_str = f"{conf:.2f}" if isinstance(conf, float) else " —  "
            sources_set = set()
            for p in (rec.get("provenance") or []):
                for s in p.get("source", "").split(","):
                    if s:
                        sources_set.add(s)
            sources = ", ".join(sorted(sources_set))
            line = f"  {name:<{col_w}}  {email:<35}  {conf_str:>5}  {sources}"
            colour = _GREEN if conf >= 0.8 else (_YELLOW if conf >= 0.6 else _RED)
            print(_c(line, colour))

    print()


# ============================================================================
# CLI
# ============================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eightfold_transformer",
        description=(
            "Eightfold Transformer — merge candidate data from multiple "
            "sources into a normalised output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.strip(),
    )

    src = parser.add_argument_group("sources  (at least one required)")
    src.add_argument("--csv",    metavar="FILE",     help="Path to candidates CSV file")
    src.add_argument("--ats",    metavar="FILE",     help="Path to ATS JSON export file")
    src.add_argument("--notes",  metavar="FILE",     help="Path to recruiter notes TXT file")
    src.add_argument("--github", metavar="USERNAME", help="GitHub username to fetch")

    cfg = parser.add_argument_group("configuration")
    cfg.add_argument(
        "--config",
        metavar="FILE",
        help=(
            "Path to pipeline config JSON "
            f"(default: {_DEFAULT_CONFIG_PATH})"
        ),
    )
    cfg.add_argument(
        "--output",
        metavar="FILE",
        default=os.path.join(os.path.dirname(__file__), "output", "result.json"),
        help="Path to write the output JSON (default: output/result.json)",
    )
    cfg.add_argument(
        "--candidate",
        metavar="NAME",
        help="Filter output to candidates whose name contains NAME (case-insensitive)",
    )
    cfg.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour output",
    )

    return parser


def main() -> int:
    """
    CLI entry point.

    Returns:
        0  on success (all records valid)
        1  on partial failure (some records invalid)
        2  on total failure (no sources provided / no records processed)
    """
    parser = _build_parser()
    args   = parser.parse_args()

    # Disable colour if requested.
    global _COLOURS_ENABLED
    if args.no_color:
        _COLOURS_ENABLED = False

    # ── Banner ───────────────────────────────────────────────────────────────
    print(_c("\n+======================================+", _CYAN, _BOLD))
    print(_c("|   Eightfold Transformer  v1.0        |", _CYAN, _BOLD))
    print(_c("+======================================+", _CYAN, _BOLD))

    # ── Guard: at least one source ──────────────────────────────────────────
    if not any([args.csv, args.ats, args.notes, args.github]):
        err("No source provided. Use --csv, --ats, --notes, or --github.")
        parser.print_usage()
        return 2

    t_start = time.perf_counter()

    # ── Load config ──────────────────────────────────────────────────────────
    head("Configuration")
    raw_cfg        = _load_config(args.config)
    projector_cfg  = _config_to_projector_format(raw_cfg)

    # ── Load sources ─────────────────────────────────────────────────────────
    raw_records = _load_sources(args)

    if not raw_records:
        err("No records were loaded from any source — nothing to process.")
        return 2

    info(f"Total raw records loaded: {len(raw_records)}")

    # ── Run pipeline ─────────────────────────────────────────────────────────
    try:
        valid, invalid = _run_pipeline(raw_records, projector_cfg, args.candidate)
    except Exception as exc:
        err(f"Pipeline crashed unexpectedly: {exc}")
        import traceback
        traceback.print_exc()
        return 2

    # ── Write output ─────────────────────────────────────────────────────────
    if valid:
        try:
            _write_output(valid, args.output)
        except OSError as exc:
            err(f"Could not write output file '{args.output}': {exc}")
            return 2

    elapsed = time.perf_counter() - t_start
    _print_summary(valid, invalid, args.output, elapsed)

    return 0 if not invalid else 1


if __name__ == "__main__":
    sys.exit(main())
