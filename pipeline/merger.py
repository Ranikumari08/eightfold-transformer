# Merges normalized records from multiple sources into a single unified candidate or job profile.

"""
Merger — Stage 3 of the pipeline.

Accepts a list of normalized canonical records (potentially from different
sources) that all belong to the same candidate and folds them into one
authoritative record.

Candidate identity
------------------
Records are grouped by email address (primary key).  Records with no email
are treated as a separate group keyed on full_name (lowercased).

Conflict resolution rules
--------------------------
1.  Lists (skills, emails, phones): UNION across all sources.
2.  Scalar fields: most-trusted source wins.
    Source trust order (highest → lowest):
        ats_json > csv > github > txt
    Within the same trust tier, higher confidence score wins
    (populated by the confidence stage, defaulted to 0.0 here).
3.  Links dict: merge per-key, same trust order.
4.  Education: collect all entries, deduplicate by institution name.
"""

from typing import Any, Dict, List, Optional, Tuple, Type, Union


# ---------------------------------------------------------------------------
# Source trust ranking (higher index = more trusted)
# ---------------------------------------------------------------------------

_SOURCE_TRUST: dict[str, int] = {
    "txt":      0,
    "github":   1,
    "csv":      2,
    "ats_json": 3,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge(records: list[dict]) -> dict:
    """
    Merge a list of canonical records for the *same* candidate.

    Args:
        records: Canonical records (after extractor + normalizer).
                 All records are assumed to belong to the same candidate.

    Returns:
        A single merged canonical record.  Never raises.
    """
    if not records:
        return _empty_merged()



    try:
        return _do_merge(records)
    except Exception as exc:
        print(f"[merger] Unexpected error during merge: {exc}")
        # Return the most-trusted record as a fallback.
        return dict(_pick_best(records))


def merge_all(records: list[dict]) -> list[dict]:
    """
    Group a flat list of canonical records by candidate identity and merge
    each group.

    Identity key: primary email (lowercased) → fallback to full_name
    (lowercased).

    Args:
        records: All canonical records from all sources.

    Returns:
        A list of merged candidate records (one per unique identity).
    """
    groups: dict[str, list[dict]] = {}
    name_to_email_key: dict[str, str] = {}
    github_to_email_key: dict[str, str] = {}

    # First pass: map names and github usernames to email keys
    for record in records:
        emails = record.get("emails")
        if isinstance(emails, list) and emails:
            email_key = f"email:{emails[0].strip().lower()}"
            
            name = record.get("full_name")
            if name:
                name_key = name.strip().lower()
                name_to_email_key[name_key] = email_key
                
            links = record.get("links") or {}
            github = links.get("github")
            if github:
                gh_username = github.strip().lower().rstrip('/').split('/')[-1]
                if gh_username:
                    github_to_email_key[gh_username] = email_key

    for record in records:
        emails = record.get("emails")
        name = record.get("full_name")
        links = record.get("links") or {}
        github = links.get("github")
        gh_username = github.strip().lower().rstrip('/').split('/')[-1] if github else None
        is_github_source = record.get("_meta", {}).get("source_name") == "github"
        
        if isinstance(emails, list) and emails:
            key = f"email:{emails[0].strip().lower()}"
        elif name and name.strip().lower() in name_to_email_key:
            key = name_to_email_key[name.strip().lower()]
        elif gh_username and gh_username in github_to_email_key:
            key = github_to_email_key[gh_username]
        elif is_github_source:
            # Skip creating an orphan record for github source without email
            print(f"[merger] Warning: GitHub profile '{gh_username or name}' could not be matched to an existing candidate. Skipping orphan record.")
            continue
        elif name:
            name_key = name.strip().lower()
            key = f"name:{name_key}"
        else:
            key = f"unknown:{id(record)}"

        groups.setdefault(key, []).append(record)

    return [merge(group) for group in groups.values()]


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def _do_merge(records: list[dict]) -> dict:
    """Perform the actual merge logic on a list of records for the same candidate."""
    # Sort records by trust (lowest first) so higher-trust values overwrite.
    sorted_records = sorted(records, key=_trust_score)

    merged: dict[str, Any] = {}

    # ── 1. Scalar fields: last writer (highest trust) wins ─────────────────
    _SCALAR_FIELDS = [
        "full_name", "location", "current_company", "title",
        "years_experience", "bio", "avatar_url",
    ]
    provenance: list[dict] = []

    for field in _SCALAR_FIELDS:
        best_val = None
        best_source = None
        for rec in sorted_records:
            val = rec.get(field)
            if val is not None:
                best_val = val
                best_source = rec.get("_meta", {}).get("source_name")
        merged[field] = best_val
        if best_val is not None and best_source:
            provenance.append({"field": field, "source": best_source, "method": "direct"})

    # ── 2. List fields: UNION ──────────────────────────────────────────────
    merged["emails"] = _union_list(r.get("emails") for r in records)
    merged["phones"] = _union_phones(r.get("phones") for r in records)
    merged["skills"] = _union_list(r.get("skills") for r in records)
    
    for field in ["emails", "phones", "skills"]:
        if merged.get(field):
            sources = [r.get("_meta", {}).get("source_name") for r in records if r.get(field)]
            if sources:
                provenance.append({
                    "field": field,
                    "source": ",".join(sorted(set(sources))),
                    "method": "merged"
                })

    # ── 3. Links: per-key merge with trust ordering ────────────────────────
    merged["links"] = _merge_links(sorted_records)
    if merged.get("links") and any(merged["links"].values()):
        sources = [r.get("_meta", {}).get("source_name") for r in records if r.get("links")]
        if sources:
            provenance.append({
                "field": "links",
                "source": ",".join(sorted(set(sources))),
                "method": "merged"
            })

    # ── 4. Education & Experience: collect + deduplicate ───────────────────
    merged["education"] = _merge_education(records)
    if merged.get("education"):
        sources = [r.get("_meta", {}).get("source_name") for r in records if r.get("education")]
        if sources:
            provenance.append({"field": "education", "source": ",".join(sorted(set(sources))), "method": "merged"})

    merged["experience"] = _merge_experience(records)
    if merged.get("experience"):
        sources = [r.get("_meta", {}).get("source_name") for r in records if r.get("experience")]
        if sources:
            provenance.append({"field": "experience", "source": ",".join(sorted(set(sources))), "method": "merged"})

    # ── 5. Provenance metadata ─────────────────────────────────────────────
    merged["provenance"] = provenance

    # Carry through any confidence scores added by confidence stage.
    merged["_confidence"] = _merge_confidence(records)

    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trust_score(record: dict) -> tuple[int, float]:
    """Return (trust_rank, confidence) for sort key (ascending = worst)."""
    meta = record.get("_meta") or {}
    source = meta.get("source_name", "")
    trust = _SOURCE_TRUST.get(source, 0)
    confidence = record.get("_confidence", {})
    avg_conf = (
        sum(confidence.values()) / len(confidence)
        if isinstance(confidence, dict) and confidence
        else 0.0
    )
    return (trust, avg_conf)


def _union_list(iterables) -> Optional[list]:
    """Return ordered union of all non-None list values, or None."""
    seen: set = set()
    result: list = []
    for items in iterables:
        if not isinstance(items, list):
            continue
        for item in items:
            if item is not None and item not in seen:
                seen.add(item)
                result.append(item)
    return result if result else None


def _union_phones(iterables) -> Optional[list]:
    """Return ordered union of non-None list values, deduplicating by normalized digits."""
    seen_digits: set = set()
    result: list = []
    for items in iterables:
        if not isinstance(items, list):
            continue
        for item in items:
            if item is None:
                continue
            # Strip all non-digit characters for comparison
            digits = "".join(c for c in str(item) if c.isdigit())
            if digits not in seen_digits:
                seen_digits.add(digits)
                result.append(item)
    return result if result else None


def _merge_links(sorted_records: list[dict]) -> dict:
    """Merge link dictionaries across records, preferring non-null values."""
    link_keys = ["linkedin", "github", "blog"]
    merged_links: dict[str, Optional[str]] = {k: None for k in link_keys}
    for rec in sorted_records:
        links = rec.get("links") or {}
        for key in link_keys:
            val = links.get(key)
            if val is not None:
                merged_links[key] = val
    return merged_links


def _merge_education(records: list[dict]) -> Optional[list[dict]]:
    """Merge education lists across records, deduplicating by exact match."""
    seen_institutions: set[str] = set()
    result: list[dict] = []
    for rec in sorted(records, key=_trust_score, reverse=True):
        edu_list = rec.get("education")
        if not isinstance(edu_list, list):
            continue
        for edu in edu_list:
            if not isinstance(edu, dict):
                continue
            inst = (edu.get("institution") or "").strip().lower()
            if inst and inst in seen_institutions:
                continue
            if inst:
                seen_institutions.add(inst)
            result.append(edu)
    return result if result else None


def _merge_experience(records: list[dict]) -> Optional[list[dict]]:
    """Merge experience lists across records, deduplicating by near-duplicate company and title."""
    result: list[dict] = []
    
    for rec in sorted(records, key=_trust_score, reverse=True):
        exp_list = rec.get("experience")
        if not isinstance(exp_list, list):
            continue
            
        for exp in exp_list:
            if not isinstance(exp, dict):
                continue
                
            c_comp = (exp.get("company") or "").strip()
            c_title = (exp.get("title") or "").strip().lower()
            
            matched = False
            for r_exp in result:
                r_comp = (r_exp.get("company") or "").strip()
                r_title = (r_exp.get("title") or "").strip().lower()
                
                if c_title == r_title:
                    c_comp_l, r_comp_l = c_comp.lower(), r_comp.lower()
                    if not c_comp_l and not r_comp_l:
                        match_comp = True
                    elif c_comp_l and r_comp_l and (c_comp_l.startswith(r_comp_l) or r_comp_l.startswith(c_comp_l) or c_comp_l in r_comp_l or r_comp_l in c_comp_l):
                        match_comp = True
                    else:
                        match_comp = False
                        
                    if match_comp:
                        matched = True
                        # Prefer the longer/more formal company name
                        if len(c_comp) > len(r_comp):
                            r_exp["company"] = c_comp
                        # Keep non-null fields
                        for k in ["title", "start", "end", "summary"]:
                            if not r_exp.get(k) and exp.get(k):
                                r_exp[k] = exp.get(k)
                        break
            
            if not matched:
                result.append(dict(exp))
                
    return result if result else None


def _merge_confidence(records: list[dict]) -> dict:
    """Aggregate per-field confidence dicts from all records."""
    merged: dict[str, float] = {}
    for rec in records:
        conf = rec.get("_confidence")
        if isinstance(conf, dict):
            for field, score in conf.items():
                # Keep the highest field confidence across sources.
                if field not in merged or score > merged[field]:
                    merged[field] = score
    return merged


def _meta_source(record: dict) -> dict:
    """Extract source metadata from a record."""
    meta = record.get("_meta") or {}
    return {
        "source_name":  meta.get("source_name", "unknown"),
        "applicant_id": meta.get("applicant_id"),
    }


def _identity_key(record: dict) -> str:
    """Generate an identity key for a record to group by candidate."""
    emails = record.get("emails")
    if isinstance(emails, list) and emails:
        return f"email:{emails[0].strip().lower()}"
    name = record.get("full_name")
    if name:
        return f"name:{name.strip().lower()}"
    return f"unknown:{id(record)}"


def _pick_best(records: list[dict]) -> dict:
    """Pick the single best record from a list based on trust score."""
    """Return the single most-trusted record (used as fallback)."""
    return max(records, key=_trust_score)


def _empty_merged() -> dict:
    """Return an empty merged canonical record with all fields set to None."""
    return {
        "full_name":        None,
        "emails":           None,
        "phones":           None,
        "location":         None,
        "current_company":  None,
        "title":            None,
        "years_experience": None,
        "skills":           None,
        "links":            {"linkedin": None, "github": None, "blog": None},
        "education":        None,
        "bio":              None,
        "avatar_url":       None,
        "_sources":         [],
        "_confidence":      {},
    }
