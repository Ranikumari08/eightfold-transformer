"""
Fetches and parses candidate profile and contribution data from the GitHub API into a standardized raw record format.
"""

import urllib.request
import urllib.error
import json
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from collections import Counter


# GitHub REST API v3 base URL — no third-party dependencies required.
_API_BASE = "https://api.github.com"

# Number of repos to fetch per page (max allowed by GitHub API is 100).
_REPOS_PER_PAGE = 100

# Maximum number of repos to inspect when aggregating top languages.
_MAX_REPOS = 100

# Timeout in seconds for each HTTP request.
_REQUEST_TIMEOUT = 10


def read_github_source(username: str) -> Optional[dict]:
    """
    Fetch a GitHub user's public profile and repository data, then return a
    single raw candidate dict.

    Calls:
        GET https://api.github.com/users/{username}
        GET https://api.github.com/users/{username}/repos?per_page=100

    Extracted fields:
        full_name       – display name on GitHub profile
        bio             – profile bio
        location        – self-reported location
        top_languages   – ordered list of languages by total bytes across repos
        public_repos    – count of public repositories
        github_url      – canonical GitHub profile URL
        avatar_url      – profile avatar image URL

    Returns the common raw format:
        {
            "source_name": "github",
            "raw_data": { ...all extracted fields... }
        }

    Returns None if the user is not found (404), the API is unreachable, or
    any other error occurs.  This function never raises an exception.

    Args:
        username: GitHub username (case-insensitive per GitHub API).

    Returns:
        A raw candidate dict, or None on any failure.
    """
    if not username or not isinstance(username, str):
        print("[github_source] Invalid username provided.")
        return None

    username = username.strip()

    # ── 1. Fetch user profile ──────────────────────────────────────────────
    profile = _get_json(f"{_API_BASE}/users/{username}")
    if profile is None:
        return None
    print(f"[github_source] Fetched profile for {username}")

    # ── 2. Fetch repositories ──────────────────────────────────────────────
    repos = _get_json(
        f"{_API_BASE}/users/{username}/repos"
        f"?per_page={_REPOS_PER_PAGE}&sort=updated&type=owner"
    )
    # If repos fail we still return the profile data; just no language info.
    if repos is None:
        repos = []

    # ── 3. Aggregate top languages ─────────────────────────────────────────
    top_languages = _aggregate_languages(repos)

    raw_data = {
        "full_name": _str_or_none(profile.get("name")),
        "bio": _str_or_none(profile.get("bio")),
        "location": {
            "city": _str_or_none(profile.get("location")),
            "region": None,
            "country": None,
        } if _str_or_none(profile.get("location")) else None,
        "emails": (
            [profile["email"]] if _str_or_none(profile.get("email")) else None
        ),
        "top_languages": top_languages,
        "public_repos": profile.get("public_repos"),
        "followers": profile.get("followers"),
        "following": profile.get("following"),
        "github_url": _str_or_none(profile.get("html_url")),
        "avatar_url": _str_or_none(profile.get("avatar_url")),
        "github_username": username,
        "links": {
            "github": _str_or_none(profile.get("html_url")),
            "blog": _str_or_none(profile.get("blog")),
        },
    }

    return {"source_name": "github", "raw_data": raw_data}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_json(url: str) -> Optional[dict | list]:
    """
    Perform a GET request to *url* and parse the JSON response.

    Returns the parsed object, or None on any HTTP / network / parse error.
    Sets a User-Agent header as required by GitHub's API policy.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "eightfold-transformer/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"[github_source] User not found (404): {url}")
        elif exc.code == 403:
            print(f"[github_source] Rate-limited or forbidden (403): {url}")
        else:
            print(f"[github_source] HTTP error {exc.code} for: {url}")
        return None
    except urllib.error.URLError as exc:
        print(f"[github_source] Network error for '{url}': {exc.reason}")
        return None
    except json.JSONDecodeError as exc:
        print(f"[github_source] JSON parse error for '{url}': {exc}")
        return None
    except Exception as exc:
        print(f"[github_source] Unexpected error for '{url}': {exc}")
        return None


def _aggregate_languages(repos: list) -> Optional[list[str]]:
    """
    Count occurrences of each language across all repos and return them in
    descending order of frequency.

    GitHub's /repos endpoint returns a single `language` field per repo
    (the dominant language).  We tally that across repos.

    Returns a list of language names (most common first), or None if no
    language data is available.
    """
    if not isinstance(repos, list) or not repos:
        return None

    counter: Counter = Counter()
    for repo in repos[:_MAX_REPOS]:
        if not isinstance(repo, dict):
            continue
        lang = _str_or_none(repo.get("language"))
        if lang:
            counter[lang] += 1

    if not counter:
        return None

    # Return languages ordered by repo count, highest first.
    return [lang for lang, _ in counter.most_common()]


def _str_or_none(value) -> Optional[str]:
    """Return stripped string or None if blank / null."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
