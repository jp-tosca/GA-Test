"""Create a Markdown snapshot from a GitHub `issues` webhook payload."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from claude_issue_analysis import ClaudeAnalysis, DEFAULT_MODEL, request_claude_analysis
from issue_context import collect_related_items, collect_repository_snapshot


COMMENT_MARKER = "<!-- claude-issue-triage:v1 -->"


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid {field}")
    return value


def render_issue(
    event: dict[str, Any], claude_analysis: ClaudeAnalysis | None = None
) -> tuple[int, str]:
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise ValueError("Event payload does not contain an issue")

    number = issue.get("number")
    if not isinstance(number, int) or number < 1:
        raise ValueError("Missing or invalid issue.number")

    title = require_string(issue.get("title"), "issue.title").replace("\r", " ").replace("\n", " ")
    url = require_string(issue.get("html_url"), "issue.html_url")
    created_at = require_string(issue.get("created_at"), "issue.created_at")

    user = issue.get("user")
    if not isinstance(user, dict):
        raise ValueError("Missing or invalid issue.user")
    author = require_string(user.get("login"), "issue.user.login")
    author_url = require_string(user.get("html_url"), "issue.user.html_url")

    raw_labels = issue.get("labels", [])
    labels = []
    if isinstance(raw_labels, list):
        labels = [label["name"] for label in raw_labels if isinstance(label, dict) and isinstance(label.get("name"), str)]

    body = issue.get("body")
    if not isinstance(body, str) or not body.strip():
        body = "_No description provided._"

    label_text = ", ".join(f"`{label}`" for label in labels) if labels else "None"
    content = (
        f"# Issue #{number}: {title}\n\n"
        f"- **Original issue:** [#{number}]({url})\n"
        f"- **Author:** [{author}]({author_url})\n"
        f"- **Opened:** {created_at}\n"
        f"- **Labels at opening:** {label_text}\n\n"
        "## Description\n\n"
        f"{body.rstrip()}\n"
    )
    if claude_analysis is not None:
        model = claude_analysis.model.replace("`", "")
        usage_parts = []
        if claude_analysis.input_tokens is not None:
            usage_parts.append(f"{claude_analysis.input_tokens} input tokens")
        if claude_analysis.output_tokens is not None:
            usage_parts.append(f"{claude_analysis.output_tokens} output tokens")

        content += f"\n## Claude analysis\n\n- **Model:** `{model}`\n"
        if usage_parts:
            content += f"- **Usage:** {', '.join(usage_parts)}\n"
        content += f"\n{claude_analysis.text.rstrip()}\n"

    return number, content


def render_issue_comment(analysis: ClaudeAnalysis) -> str:
    lines = [
        COMMENT_MARKER,
        "## Automated Claude triage",
        "",
        "> This is an automated preliminary review. A maintainer should verify "
        "duplicate matches and effort estimates.",
        "",
        analysis.text,
        "",
    ]
    if analysis.duplicate_matches:
        lines.extend(
            [
                "If one of the items above already covers or resolves this request, "
                "please close this issue as a duplicate. If it is materially different, "
                "please explain the distinction so a maintainer can review it.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No strong duplicate was found in the bounded history checked. The "
                "estimate above is based on a quick code snapshot and is not a delivery "
                "commitment.",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            f"Checked {analysis.checked_items} recent issues/pull requests and "
            f"inspected {analysis.inspected_files} repository files with "
            f"`{analysis.model.replace('`', '')}`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    event_path = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(event_path.read_text(encoding="utf-8"))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)

    issue = event.get("issue")
    if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
        raise ValueError("Event payload does not contain a valid issue number")
    related_items = collect_related_items(
        repository, issue["number"], github_token
    )
    repository_snapshot = collect_repository_snapshot(Path.cwd(), event)
    analysis = request_claude_analysis(
        event, related_items, repository_snapshot, api_key, model, mode="full"
    )
    number, content = render_issue(event, analysis)

    output_path = Path("issues") / f"issue-{number}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8", newline="\n")

    comment_path_value = os.environ.get("ISSUE_COMMENT_PATH")
    if not comment_path_value:
        raise RuntimeError("ISSUE_COMMENT_PATH is not configured")
    comment_path = Path(comment_path_value)
    comment_path.parent.mkdir(parents=True, exist_ok=True)
    comment_path.write_text(
        render_issue_comment(analysis), encoding="utf-8", newline="\n"
    )
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
