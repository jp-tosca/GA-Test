"""Collect bounded GitHub history and repository context for issue triage."""

from __future__ import annotations

import json
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
MAX_CODE_FILES = 25
MAX_CODE_FILE_CHARACTERS = 6_000
MAX_CODE_CONTEXT_CHARACTERS = 40_000
MAX_TREE_ENTRIES = 300

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

    def as_prompt_data(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "number": self.number,
            "kind": self.kind,
            "state": self.state,
            "title": self.title,
            "url": self.url,
            "body_excerpt": self.body_excerpt,
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
    return RelatedItem(
        candidate_id=f"{'pr' if kind == 'pull request' else 'issue'}-{number}",
        number=number,
        kind=kind,
        state=state,
        title=title[:500],
        url=url,
        body_excerpt=body_excerpt,
        updated_at=updated_at if isinstance(updated_at, str) else "",
    )


def collect_related_items(
    repository: str,
    current_issue_number: int,
    token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[RelatedItem, ...]:
    repo_path = _repository_api_path(repository)
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
            if item is not None and item.number != current_issue_number:
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
        if item is not None and item.number != current_issue_number:
            pull_items.append(item)

    items = issue_items[:50] + pull_items[:50]
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return tuple(items[:MAX_RELATED_ITEMS])


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
