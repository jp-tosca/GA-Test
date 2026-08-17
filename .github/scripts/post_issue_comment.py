"""Create or update the workflow's automated GitHub issue comment."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
COMMENT_MARKER = "<!-- claude-issue-triage:v1 -->"
BOT_LOGIN = "github-actions[bot]"


def _repository_api_path(repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY is invalid")
    return urllib.parse.quote(repository, safe="/")


def _request_json(
    method: str,
    url: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        method=method,
    )
    try:
        with opener(request, timeout=30) as response:
            response_body = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub comment request failed with HTTP {error.code}") from None
    except urllib.error.URLError as error:
        raise RuntimeError("GitHub comment request failed") from error

    if not response_body:
        return None
    try:
        return json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub comment API returned invalid JSON") from error


def upsert_issue_comment(
    repository: str,
    issue_number: int,
    token: str,
    body: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    if issue_number < 1:
        raise ValueError("Issue number must be positive")
    if COMMENT_MARKER not in body:
        raise ValueError("Automated comment marker is missing")

    repo_path = _repository_api_path(repository)
    comments_url = (
        f"{GITHUB_API_URL}/repos/{repo_path}/issues/{issue_number}/comments"
    )
    existing_comment_id = None
    for page in range(1, 6):
        comments = _request_json(
            "GET",
            f"{comments_url}?per_page=100&page={page}",
            token,
            opener=opener,
        )
        if not isinstance(comments, list):
            raise RuntimeError("GitHub API returned an unexpected comments response")
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            comment_body = comment.get("body")
            comment_id = comment.get("id")
            if (
                isinstance(user, dict)
                and user.get("login") == BOT_LOGIN
                and isinstance(comment_body, str)
                and COMMENT_MARKER in comment_body
                and isinstance(comment_id, int)
            ):
                existing_comment_id = comment_id
                break
        if existing_comment_id is not None or len(comments) < 100:
            break

    if existing_comment_id is None:
        _request_json(
            "POST", comments_url, token, payload={"body": body}, opener=opener
        )
        return "created"

    _request_json(
        "PATCH",
        f"{GITHUB_API_URL}/repos/{repo_path}/issues/comments/{existing_comment_id}",
        token,
        payload={"body": body},
        opener=opener,
    )
    return "updated"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: post_issue_comment.py COMMENT_FILE")
    comment_body = Path(sys.argv[1]).read_text(encoding="utf-8")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    raw_issue_number = os.environ.get("ISSUE_NUMBER", "")
    if not raw_issue_number.isdigit():
        raise RuntimeError("ISSUE_NUMBER is not configured correctly")

    result = upsert_issue_comment(
        repository, int(raw_issue_number), token, comment_body
    )
    print(f"Automated issue comment {result}.")


if __name__ == "__main__":
    main()
