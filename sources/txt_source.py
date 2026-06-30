"""
Reads and parses candidate/job data from plain text files into a standardized raw record format.
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union


# ── Regex patterns ─────────────────────────────────────────────────────────────

# Candidate block header: "--- Candidate: Name ---"
_RE_BLOCK_HEADER = re.compile(
    r"^---\s*Candidate:\s*(.+?)\s*---",
    re.IGNORECASE,
)

# Email address (RFC-ish, handles most real-world cases)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Phone number — matches common international / local formats:
#   +91-98001-23456 | +1-415-555-0192 | 91-9123456789 | 98765-43210 | 8800112233
_RE_PHONE = re.compile(
    r"(?<!\w)"                           # not preceded by word char (avoid matching IDs)
    r"(?:\+?\d{1,3}[-\s]?)"             # optional country code
    r"(?:"
    r"\(?\d{3,5}\)?[-\s]?"              # area / trunk
    r"\d{3,5}[-\s]?"                    # exchange
    r"\d{3,5}"                          # subscriber
    r")"
    r"(?!\w)",                           # not followed by word char
)

# Date (ISO YYYY-MM-DD or long form "Month DD, YYYY")
_RE_DATE = re.compile(
    r"\b(?:"
    r"\d{4}-\d{2}-\d{2}"                        # 2026-05-10
    r"|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s,]+\d{1,2}[\s,]+\d{4}"                 # June 30, 2026
    r")\b",
    re.IGNORECASE,
)

# Skills / tech keywords mentioned as comma-separated lists (heuristic).
# We look for lines that contain a sequence of "word(+)" items separated by commas
# and slashes, e.g. "Python, Django, React" or "React + Node".
_RE_SKILLS_LINE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9#.+\-]*)"
    r"(?:\s*[,/+&]\s*(?:[A-Za-z][A-Za-z0-9#.+\-]*))+",
)

# Known tech terms to identify skill-like tokens in free text.
_KNOWN_TECH = {
    "python", "django", "flask", "fastapi", "java", "spring", "springboot",
    "kafka", "aws", "gcp", "azure", "kubernetes", "docker", "redis", "react",
    "node", "nodejs", "typescript", "javascript", "graphql", "mongodb",
    "postgresql", "mysql", "sql", "tableau", "excel", "tensorflow", "pytorch",
    "nlp", "scikit-learn", "scikitlearn", "ml", "machine learning",
    "microservices", "golang", "go", "kotlin", "swift", "c++", "c#", "ruby",
    "rails", "vue", "angular", "next.js", "nextjs", "figma", "jira", "agile",
}


def read_txt_source(filepath: str) -> list[dict]:
    """
    Parse a plain-text recruiter-notes file into a list of raw candidate dicts.

    Candidates are separated by lines matching "--- Candidate: NAME ---".
    For each block the function extracts:
        - name   (from the header line)
        - emails (regex scan)
        - phones (regex scan)
        - skills (comma/slash-separated tech terms)
        - dates  (ISO and long-form dates found in the block)

    Each dict follows the common raw format:
        {
            "source_name": "txt",
            "raw_data": { ...all extracted fields... }
        }

    Args:
        filepath: Absolute or relative path to the text file.

    Returns:
        A list of raw candidate dicts (may be empty on error or empty input).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        print(f"[txt_source] File not found: {filepath}")
        return []
    except Exception as exc:
        print(f"[txt_source] Failed to read '{filepath}': {exc}")
        return []

    # Split the file into blocks by candidate header lines.
    blocks = _split_into_blocks(content)

    records: list[dict] = []
    for name, block_text in blocks:
        raw_data = {
            "full_name": name,
            "emails": _extract_emails(block_text),
            "phones": _extract_phones(block_text),
            "skills": _extract_skills(block_text),
            "dates": _extract_dates(block_text),
            "notes_raw": block_text.strip(),
        }
        records.append({"source_name": "txt", "raw_data": raw_data})

    return records


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_into_blocks(content: str) -> list[tuple[str, str]]:
    """
    Split the full text into (candidate_name, block_text) pairs.
    Everything before the first header is discarded (file preamble).
    """
    lines = content.splitlines(keepends=True)
    blocks: list[tuple[str, str]] = []
    current_name: Optional[str] = None
    current_lines: list[str] = []

    for line in lines:
        match = _RE_BLOCK_HEADER.match(line.strip())
        if match:
            if current_name is not None:
                blocks.append((current_name, "".join(current_lines)))
            current_name = match.group(1).strip()
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)

    # Flush the last block.
    if current_name is not None:
        blocks.append((current_name, "".join(current_lines)))

    return blocks


def _extract_emails(text: str) -> Optional[list[str]]:
    """Return unique emails found in *text*, or None."""
    found = list(dict.fromkeys(_RE_EMAIL.findall(text)))  # deduplicate, preserve order
    return found if found else None


def _extract_phones(text: str) -> Optional[list[str]]:
    """Return unique phone strings found in *text*, or None."""
    raw_matches = _RE_PHONE.findall(text)
    # Normalise: strip leading/trailing whitespace; keep only distinct values.
    normalised = list(dict.fromkeys(m.strip() for m in raw_matches))
    # Filter out very short tokens that are likely not phone numbers (< 7 digits).
    filtered = [p for p in normalised if len(re.sub(r"\D", "", p)) >= 7]
    return filtered if filtered else None


def _extract_skills(text: str) -> Optional[list[str]]:
    """
    Heuristically extract tech skills from free text.

    Strategy:
    1. Find comma/slash-separated sequences of tokens.
    2. Also scan every word and check against a known-tech vocabulary.
    3. Deduplicate and return sorted list, or None if nothing found.
    """
    found: set[str] = set()

    # Step 1 – known-tech vocabulary scan.
    words = re.findall(r"[A-Za-z][A-Za-z0-9#.+\-]*", text)
    for word in words:
        if word.lower() in _KNOWN_TECH:
            found.add(word)

    # Exclude overly generic English words that sneak through.
    _STOPWORDS = {"and", "or", "the", "for", "with", "from", "has", "at", "in",
                  "on", "of", "to", "is", "she", "he", "her", "his", "they",
                  "their", "are", "was", "were"}
    found = {s for s in found if s.lower() not in _STOPWORDS}

    result = sorted(found, key=str.lower)
    return result if result else None


def _extract_dates(text: str) -> Optional[list[str]]:
    """Return unique date strings found in *text*, or None."""
    found = list(dict.fromkeys(_RE_DATE.findall(text)))
    return found if found else None
