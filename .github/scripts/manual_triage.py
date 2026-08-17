"""Run skill-guided issue triage manually and write a GitHub job summary."""

from __future__ import annotations

import os
from pathlib import Path

from claude_issue_analysis import (
    ALLOWED_MODES,
    DEFAULT_MODEL,
    request_claude_analysis,
    safe_markdown_text,
)
from issue_context import (
    RepositorySnapshot,
    collect_related_items,
    collect_repository_snapshot,
    fetch_issue_event,
)


def _manual_event(title: str, requirement: str) -> dict:
    if not title.strip():
        raise RuntimeError("Provide an issue number or a proposed title")
    return {
        "issue": {
            "number": 0,
            "title": title.strip(),
            "body": requirement.strip() or "No additional description was provided.",
        }
    }


def main() -> None:
    mode = os.environ.get("TRIAGE_MODE", "full")
    if mode not in ALLOWED_MODES:
        raise RuntimeError(f"Unsupported TRIAGE_MODE: {mode}")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
    raw_issue_number = os.environ.get("TRIAGE_ISSUE_NUMBER", "").strip()

    if raw_issue_number:
        if not raw_issue_number.isdigit() or int(raw_issue_number) < 1:
            raise RuntimeError("TRIAGE_ISSUE_NUMBER must be a positive integer")
        issue_number = int(raw_issue_number)
        event = fetch_issue_event(repository, issue_number, github_token)
    else:
        issue_number = 0
        event = _manual_event(
            os.environ.get("TRIAGE_TITLE", ""),
            os.environ.get("TRIAGE_REQUIREMENT", ""),
        )

    related_items = ()
    if mode in {"duplicates", "full"}:
        related_items = collect_related_items(repository, issue_number, github_token)

    repository_snapshot = RepositorySnapshot(tree=(), files=())
    if mode in {"estimate", "full"}:
        repository_snapshot = collect_repository_snapshot(Path.cwd(), event)

    analysis = request_claude_analysis(
        event,
        related_items,
        repository_snapshot,
        api_key,
        model,
        mode=mode,
    )

    issue = event["issue"]
    safe_title = safe_markdown_text(" ".join(str(issue["title"]).split()))
    summary = (
        f"# Claude repository triage\n\n"
        f"- **Mode:** `{mode}`\n"
        f"- **Subject:** {safe_title}\n"
        f"- **Model:** `{analysis.model}`\n"
        f"- **History checked:** {analysis.checked_items} issues/pull requests\n"
        f"- **Files inspected:** {analysis.inspected_files}\n\n"
        f"{analysis.text}\n"
    )
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8", newline="\n") as summary_file:
            summary_file.write(summary)


if __name__ == "__main__":
    main()
