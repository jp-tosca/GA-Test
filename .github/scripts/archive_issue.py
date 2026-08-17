"""Create a Markdown snapshot from a GitHub `issues` webhook payload."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid {field}")
    return value


def render_issue(event: dict[str, Any]) -> tuple[int, str]:
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
    return number, content


def main() -> None:
    event_path = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(event_path.read_text(encoding="utf-8"))
    number, content = render_issue(event)

    output_path = Path("issues") / f"issue-{number}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8", newline="\n")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
