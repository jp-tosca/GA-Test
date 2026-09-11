"""Collect bounded GitHub history and repository context for issue triage."""

from __future__ import annotations

import base64
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
MAX_RELATED_ITEMS = 100
MAX_RELATED_BODY_CHARACTERS = 600
MAX_SEARCH_TERMS = 3
MAX_SEARCH_RESULTS = 25
MAX_RECENT_ITEMS = 25
MAX_CODE_FILES = 25
MAX_CODE_FILE_CHARACTERS = 6_000
MAX_CODE_CONTEXT_CHARACTERS = 40_000
MAX_TREE_ENTRIES = 300
MAX_REMOTE_CANDIDATES = 40
MAX_REMOTE_FILE_BYTES = 200_000
# A term appearing in more than this share of paths describes the repository
# rather than the issue, and would otherwise swamp the genuinely rare terms.
COMMON_TERM_PATH_RATIO = 0.05
# A ratio alone excludes everything in a small repository, where a relevant term
# legitimately matches a large share of very few files.
MIN_TERM_PATHS = 3
REMOTE_FILE_CHARACTERS = 3_000

EXCLUDED_DIRECTORIES = {
    ".claude",
    ".git",
    ".venv",
    "build",
    "coverage",
    "dist",
    "issues",
    "node_modules",
    "target",
    "vendor",
}
TEXT_SUFFIXES = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".gradle",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".php",
    ".properties",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
}
SPECIAL_TEXT_FILES = {
    "dockerfile",
    "gemfile",
    "makefile",
    "pom.xml",
    "readme",
    "readme.md",
}
SENSITIVE_NAME_PARTS = {".env", "credential", "id_rsa", "private", "secret"}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "been",
    "could",
    "from",
    "have",
    "into",
    "issue",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "want",
    "when",
    "where",
    "which",
    "with",
    "would",
}


@dataclass(frozen=True)
class RelatedItem:
    candidate_id: str
    number: int
    kind: str
    state: str
    title: str
    url: str
    body_excerpt: str
    updated_at: str
    created_at: str = ""

    def as_prompt_data(self) -> dict[str, Any]:
        # Dates let Claude judge how stale a match's context is. They are
        # deliberately included: without them it cannot tell a live discussion
        # from one that predates the current design.
        return {
            "candidate_id": self.candidate_id,
            "number": self.number,
            "kind": self.kind,
            "state": self.state,
            "title": self.title,
            "url": self.url,
            "body_excerpt": self.body_excerpt,
            "created_at": self.created_at,
            "last_activity_at": self.updated_at,
        }


@dataclass(frozen=True)
class RepositorySnapshot:
    tree: tuple[str, ...]
    files: tuple[tuple[str, str], ...]

    def as_prompt_data(self) -> dict[str, Any]:
        return {
            "file_tree": list(self.tree),
            "selected_files": [
                {"path": path, "content": content} for path, content in self.files
            ],
        }


def _github_json(
    url: str,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub API request failed with HTTP {error.code}") from None
    except (urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub API request failed") from error


def _repository_api_path(repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY is invalid")
    return urllib.parse.quote(repository, safe="/")


def _item_from_api(item: Any, kind: str) -> RelatedItem | None:
    if not isinstance(item, dict):
        return None
    number = item.get("number")
    title = item.get("title")
    url = item.get("html_url")
    if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
        return None

    raw_state = item.get("state")
    if kind == "pull request" and isinstance(item.get("merged_at"), str):
        state = "merged"
    elif raw_state == "open":
        state = "open"
    elif kind == "issue" and isinstance(item.get("state_reason"), str):
        state = f"closed ({item['state_reason']})"
    else:
        state = "closed (not merged)" if kind == "pull request" else "closed"

    body = item.get("body")
    body_excerpt = body[:MAX_RELATED_BODY_CHARACTERS] if isinstance(body, str) else ""
    updated_at = item.get("updated_at")
    created_at = item.get("created_at")
    return RelatedItem(
        candidate_id=f"{'pr' if kind == 'pull request' else 'issue'}-{number}",
        number=number,
        kind=kind,
        state=state,
        title=title[:500],
        url=url,
        body_excerpt=body_excerpt,
        updated_at=updated_at if isinstance(updated_at, str) else "",
        created_at=created_at if isinstance(created_at, str) else "",
    )


def collect_related_items(
    repository: str,
    current_issue_number: int,
    token: str,
    *,
    event: dict[str, Any] | None = None,
    source_repository: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[RelatedItem, ...]:
    """Collect duplicate/related candidates from `repository`.

    Two strategies are combined. The recency listing shows what is active now;
    keyword search reaches older history that the listing cannot, which matters
    on large long-lived repositories where recent activity covers only days.

    `current_issue_number` is excluded only when the triaged issue actually lives
    in `repository`; when triaging against a different repository, that number
    refers to an unrelated item and must not be filtered out.
    """
    repo_path = _repository_api_path(repository)
    excluded_number = current_issue_number if source_repository in (None, repository) else None
    issue_items = []
    for page in range(1, 4):
        query = f"state=all&per_page=100&sort=updated&direction=desc&page={page}"
        issues_data = _github_json(
            f"{GITHUB_API_URL}/repos/{repo_path}/issues?{query}",
            token,
            opener=opener,
        )
        if not isinstance(issues_data, list):
            raise RuntimeError("GitHub API returned an unexpected issue response")
        for raw_item in issues_data:
            if isinstance(raw_item, dict) and "pull_request" in raw_item:
                continue
            item = _item_from_api(raw_item, "issue")
            if item is not None and item.number != excluded_number:
                issue_items.append(item)
        if len(issue_items) >= 50 or len(issues_data) < 100:
            break

    pull_query = "state=all&per_page=50&sort=updated&direction=desc"
    pulls_data = _github_json(
        f"{GITHUB_API_URL}/repos/{repo_path}/pulls?{pull_query}",
        token,
        opener=opener,
    )
    if not isinstance(pulls_data, list):
        raise RuntimeError("GitHub API returned an unexpected pull request response")

    pull_items = []
    for raw_item in pulls_data:
        item = _item_from_api(raw_item, "pull request")
        if item is not None and item.number != excluded_number:
            pull_items.append(item)

    recent = issue_items[:MAX_RECENT_ITEMS] + pull_items[:MAX_RECENT_ITEMS]
    recent.sort(key=lambda item: item.updated_at, reverse=True)

    searched: list[RelatedItem] = []
    if event is not None:
        searched = search_related_items(repository, event, token, opener=opener)

    # Search hits lead: they are chosen for similarity, while the recency page is
    # only "what moved lately" and would otherwise crowd them out.
    items: list[RelatedItem] = []
    seen: set[str] = set()
    for item in [*searched, *recent]:
        if item.candidate_id in seen:
            continue
        seen.add(item.candidate_id)
        items.append(item)
    return tuple(items[:MAX_RELATED_ITEMS])


def _ranked_terms(event: dict[str, Any]) -> list[str]:
    """Rank issue words by how much signal they carry for a search query.

    The title is weighted over the body, and longer words are preferred: GitHub
    ANDs search terms, so a handful of specific words finds far more than a long
    literal phrase, which usually matches nothing at all.
    """
    issue = event.get("issue")
    if not isinstance(issue, dict):
        return []

    def words(text: Any) -> list[str]:
        if not isinstance(text, str):
            return []
        return [
            word
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
            if word not in STOP_WORDS
        ]

    scored: dict[str, float] = {}
    for weight, text in ((2.0, issue.get("title")), (1.0, issue.get("body"))):
        for word in words(text):
            scored[word] = scored.get(word, 0.0) + weight * min(len(word), 12) / 12
    return [word for word, _ in sorted(scored.items(), key=lambda p: (-p[1], p[0]))]


def _search_items(
    repository: str,
    query: str,
    kind: str,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[RelatedItem]:
    """Run one search query, returning [] rather than failing the whole run.

    Search is a best-effort recall improvement layered on top of the recency
    listing, so a rejected query must never break triage.
    """
    encoded = urllib.parse.quote(query)
    url = (
        f"{GITHUB_API_URL}/search/issues?q={encoded}"
        f"&per_page={MAX_SEARCH_RESULTS}"
    )
    try:
        payload = _github_json(url, token, opener=opener)
    except RuntimeError:
        return []
    if not isinstance(payload, dict):
        return []
    items = []
    for raw_item in payload.get("items", []) or []:
        # Search returns issues and pull requests from one endpoint, so classify
        # by what came back rather than by what the query asked for.
        actual_kind = kind
        if isinstance(raw_item, dict):
            actual_kind = (
                "pull request" if "pull_request" in raw_item else "issue"
            )
        item = _item_from_api(raw_item, actual_kind)
        if item is not None:
            items.append(item)
    return items


def search_related_items(
    repository: str,
    event: dict[str, Any],
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[RelatedItem]:
    """Find candidates by keyword, reaching history far older than the recency page."""
    terms = _ranked_terms(event)
    if not terms:
        return []

    found: list[RelatedItem] = []
    for kind, scope in (("issue", "in:title"), ("issue", ""), ("pull request", "in:title")):
        qualifier = "is:issue" if kind == "issue" else "is:pr"
        # Narrow first, then widen: GitHub ANDs terms, so too many match nothing.
        for count in range(min(MAX_SEARCH_TERMS, len(terms)), 0, -1):
            selected = " ".join(terms[:count])
            query = f"repo:{repository} {qualifier} {scope} {selected}".replace("  ", " ")
            results = _search_items(repository, query.strip(), kind, token, opener=opener)
            if results:
                found.extend(results)
                break
    return found


def fetch_issue_event(
    repository: str,
    issue_number: int,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if issue_number < 1:
        raise ValueError("Issue number must be positive")
    repo_path = _repository_api_path(repository)
    issue = _github_json(
        f"{GITHUB_API_URL}/repos/{repo_path}/issues/{issue_number}",
        token,
        opener=opener,
    )
    if not isinstance(issue, dict) or "pull_request" in issue:
        raise RuntimeError("GitHub API did not return an issue")
    if not isinstance(issue.get("title"), str):
        raise RuntimeError("GitHub API returned an invalid issue")
    return {"issue": issue}


def _is_excluded(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    lower_parts = {part.lower() for part in relative.parts}
    lower_name = path.name.lower()
    return (
        bool(lower_parts & EXCLUDED_DIRECTORIES)
        or path.is_symlink()
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or any(part in lower_name for part in SENSITIVE_NAME_PARTS)
    )


def _is_text_candidate(path: Path) -> bool:
    lower_name = path.name.lower()
    return path.suffix.lower() in TEXT_SUFFIXES or lower_name in SPECIAL_TEXT_FILES


def _issue_terms(event: dict[str, Any]) -> set[str]:
    issue = event.get("issue")
    if not isinstance(issue, dict):
        return set()
    text = f"{issue.get('title', '')} {issue.get('body', '')}".lower()
    return {
        term
        for term in re.findall(r"[a-z][a-z0-9_-]{2,}", text)
        if term not in STOP_WORDS
    }


def collect_repository_snapshot(root: Path, event: dict[str, Any]) -> RepositorySnapshot:
    root = root.resolve()
    terms = _issue_terms(event)
    candidates = []
    tree = []

    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        if len(tree) < MAX_TREE_ENTRIES:
            tree.append(relative)
        if not _is_text_candidate(path) or path.stat().st_size > 200_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "\x00" in content:
            continue

        search_text = f"{relative.lower()}\n{content[:20_000].lower()}"
        score = sum(1 for term in terms if term in search_text)
        if path.name.lower() in SPECIAL_TEXT_FILES:
            score += 2
        candidates.append((score, relative, content))

    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    selected = []
    remaining = MAX_CODE_CONTEXT_CHARACTERS
    for _, relative, content in candidates[:MAX_CODE_FILES]:
        if remaining <= 0:
            break
        excerpt = content[: min(MAX_CODE_FILE_CHARACTERS, remaining)]
        if excerpt:
            selected.append((relative, excerpt))
            remaining -= len(excerpt)

    return RepositorySnapshot(tree=tuple(sorted(tree)), files=tuple(selected))


def _path_term_weights(terms: set[str], paths: list[str]) -> dict[str, float]:
    """Weight issue terms by how rare they are among the repository's paths.

    In a large repository a short term like "and" appears inside hundreds of
    unrelated path names, so matching it says nothing. Rare terms carry the
    signal and are weighted accordingly.
    """
    total = len(paths) or 1
    lowered = [path.lower() for path in paths]
    weights = {}
    for term in terms:
        frequency = sum(1 for path in lowered if term in path)
        ceiling = max(MIN_TERM_PATHS, COMMON_TERM_PATH_RATIO * total)
        if 0 < frequency <= ceiling:
            weights[term] = math.log(total / (1 + frequency))
    return weights


def _path_score(path: str, weights: dict[str, float]) -> float:
    """Score a path, counting the file name far above its directories."""
    name = Path(path).name.lower()
    directories = path.lower()[: len(path) - len(name)]
    return sum(
        weight * ((3 if term in name else 0) + (1 if term in directories else 0))
        for term, weight in weights.items()
    )


def _remote_default_branch(
    repo_path: str,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    metadata = _github_json(f"{GITHUB_API_URL}/repos/{repo_path}", token, opener=opener)
    branch = metadata.get("default_branch") if isinstance(metadata, dict) else None
    if not isinstance(branch, str) or not branch:
        raise RuntimeError("GitHub API did not return a default branch")
    return branch


def _remote_file_content(
    repo_path: str,
    path: str,
    branch: str,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str | None:
    url = (
        f"{GITHUB_API_URL}/repos/{repo_path}/contents/"
        f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
    )
    try:
        payload = _github_json(url, token, opener=opener)
    except RuntimeError:
        return None
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return None
    raw = payload.get("content")
    if not isinstance(raw, str):
        return None
    try:
        content = base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return None if "\x00" in content else content


def collect_remote_repository_snapshot(
    repository: str,
    event: dict[str, Any],
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> RepositorySnapshot:
    """Build a code snapshot of another repository over the GitHub API.

    The whole tree arrives in one request, so paths are scored first and only a
    small number of promising files are downloaded. Those are then rescored on
    their real content, which keeps selection quality close to a local scan
    without cloning a large repository on every run.
    """
    repo_path = _repository_api_path(repository)
    branch = _remote_default_branch(repo_path, token, opener=opener)
    tree_payload = _github_json(
        f"{GITHUB_API_URL}/repos/{repo_path}/git/trees/"
        f"{urllib.parse.quote(branch)}?recursive=1",
        token,
        opener=opener,
    )
    if not isinstance(tree_payload, dict) or not isinstance(tree_payload.get("tree"), list):
        raise RuntimeError("GitHub API returned an unexpected repository tree")

    terms = _issue_terms(event)
    tree: list[str] = []
    eligible: list[str] = []
    for entry in tree_payload["tree"]:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        candidate = Path(path)
        lower_name = candidate.name.lower()
        lower_parts = {part.lower() for part in candidate.parts}
        if (
            lower_parts & EXCLUDED_DIRECTORIES
            or candidate.suffix.lower() in SENSITIVE_SUFFIXES
            or any(part in lower_name for part in SENSITIVE_NAME_PARTS)
        ):
            continue
        if len(tree) < MAX_TREE_ENTRIES:
            tree.append(path)
        if candidate.suffix.lower() not in TEXT_SUFFIXES and lower_name not in SPECIAL_TEXT_FILES:
            continue
        size = entry.get("size")
        if isinstance(size, int) and size > MAX_REMOTE_FILE_BYTES:
            continue
        eligible.append(path)

    # Computed once over the whole tree, not per path.
    weights = _path_term_weights(terms, eligible)
    scored = [(_path_score(path, weights), path) for path in eligible]
    scored.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    fetched: list[tuple[int, float, str, str]] = []
    for path_score, path in scored[:MAX_REMOTE_CANDIDATES]:
        content = _remote_file_content(repo_path, path, branch, token, opener=opener)
        if content is None:
            continue
        search_text = f"{path.lower()}\n{content[:20_000].lower()}"
        content_score = sum(1 for term in terms if term in search_text)
        fetched.append((content_score, path_score, path, content))

    # Content decides. Where files are equally informative, the path score breaks
    # the tie, so a well-named file is not discarded in favour of an alphabetical
    # accident.
    fetched.sort(key=lambda candidate: (-candidate[0], -candidate[1], candidate[2]))
    selected: list[tuple[str, str]] = []
    remaining = MAX_CODE_CONTEXT_CHARACTERS
    for _, _, path, content in fetched[:MAX_CODE_FILES]:
        if remaining <= 0:
            break
        # Prefer breadth over depth here: locating the right areas in a large
        # unfamiliar codebase beats reading two files in full.
        excerpt = content[: min(REMOTE_FILE_CHARACTERS, remaining)]
        if excerpt:
            selected.append((path, excerpt))
            remaining -= len(excerpt)

    return RepositorySnapshot(tree=tuple(sorted(tree)), files=tuple(selected))


def resolve_repository_snapshot(
    target_repository: str,
    source_repository: str,
    event: dict[str, Any],
    token: str,
    root: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> RepositorySnapshot:
    """Read code from whichever repository the estimate is actually about.

    Triaging against another repository means the local checkout is the wrong
    codebase, so the snapshot is fetched from the target instead.
    """
    if target_repository == source_repository:
        return collect_repository_snapshot(root, event)
    return collect_remote_repository_snapshot(
        target_repository, event, token, opener=opener
    )
