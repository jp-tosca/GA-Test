from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).parents[1] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from archive_issue import (  # noqa: E402
    render_issue,
    render_issue_comment,
)
from claude_issue_analysis import (  # noqa: E402
    ClaudeAnalysis,
    DuplicateMatch,
    RelatedMatch,
    WorkEstimate,
    build_system_prompt,
    request_claude_analysis,
)
from issue_context import (  # noqa: E402
    RelatedItem,
    _item_from_api,
    RepositorySnapshot,
    collect_related_items,
    collect_repository_snapshot,
    fetch_issue_event,
)
from post_issue_comment import COMMENT_MARKER, upsert_issue_comment  # noqa: E402
import manual_triage  # noqa: E402


def issue_event(body: str | None = "Please add CSV export.") -> dict:
    return {
        "issue": {
            "number": 42,
            "title": "Add export support; $(not-a-command)",
            "html_url": "https://github.com/example/repo/issues/42",
            "created_at": "2026-08-17T12:00:00Z",
            "user": {
                "login": "octocat",
                "html_url": "https://github.com/octocat",
            },
            "labels": [{"name": "enhancement"}],
            "body": body,
        }
    }


def related_issue() -> RelatedItem:
    return RelatedItem(
        candidate_id="issue-12",
        number=12,
        kind="issue",
        state="open",
        title="CSV export support",
        url="https://github.com/example/repo/issues/12",
        body_excerpt="Add CSV exports.",
        updated_at="2026-08-16T12:00:00Z",
    )


def related_pull_request() -> RelatedItem:
    return RelatedItem(
        candidate_id="pr-30",
        number=30,
        kind="pull request",
        state="merged",
        title="Refactor the report writer",
        url="https://github.com/example/repo/pull/30",
        body_excerpt="Rewrites the report writer used by exports.",
        updated_at="2026-08-15T12:00:00Z",
    )


def snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        tree=("README.MD", "src/export.py"),
        files=(("src/export.py", "def export():\n    pass\n"),),
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def claude_response(assessment: dict) -> dict:
    return {
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": json.dumps(assessment)}],
        "usage": {"input_tokens": 300, "output_tokens": 80},
    }


class ClaudeAnalysisTests(unittest.TestCase):
    def test_parses_validated_duplicate_and_ignores_invented_id(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {
                                "candidate_id": "issue-12",
                                "reason": "Requests the same CSV export feature.",
                            },
                            {"candidate_id": "issue-999", "reason": "Invented."},
                        ],
                        "duplicate_summary": "A likely duplicate is already open.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_issue(),),
            snapshot(),
            "test-secret",
            "test-model",
            opener=opener,
        )

        self.assertEqual(len(analysis.duplicate_matches), 1)
        self.assertEqual(analysis.duplicate_matches[0].item.number, 12)
        self.assertIn("Issue #12", analysis.text)
        self.assertNotIn("999", analysis.text)
        request_body = json.loads(captured["request"].data)
        prompt = request_body["messages"][0]["content"]
        self.assertIn("src/export.py", prompt)
        self.assertIn("$(not-a-command)", prompt)
        self.assertIn("check-duplicate-issues", request_body["system"])
        self.assertIn("estimate-issue-work", request_body["system"])

    def test_duplicate_only_mode_loads_only_duplicate_skill(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data)
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_issue(),),
            RepositorySnapshot(tree=(), files=()),
            "test-secret",
            mode="duplicates",
            opener=opener,
        )

        self.assertIsNone(analysis.estimate)
        self.assertIn("Duplicate check", analysis.text)
        self.assertIn("check-duplicate-issues", captured["payload"]["system"])
        self.assertNotIn("estimate-issue-work", captured["payload"]["system"])

    def test_estimate_only_mode_loads_only_estimate_skill(self):
        def opener(request, timeout):
            payload = json.loads(request.data)
            self.assertIn("estimate-issue-work", payload["system"])
            self.assertNotIn("check-duplicate-issues", payload["system"])
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "Duplicate check not requested",
                        "estimate": {
                            "size": "small",
                            "summary": "Localized change.",
                            "areas": ["src/export.py"],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (),
            snapshot(),
            "test-secret",
            mode="estimate",
            opener=opener,
        )

        self.assertEqual(analysis.estimate.size, "small")
        self.assertNotIn("Duplicate check", analysis.text)

    def test_skill_files_are_loadable(self):
        prompt = build_system_prompt("full")
        self.assertIn("Compare intent, affected behavior", prompt)
        self.assertIn("Classify the work as", prompt)

    def test_escapes_markdown_from_candidate_titles_and_claude_fields(self):
        unsafe_item = RelatedItem(
            candidate_id="issue-12",
            number=12,
            kind="issue",
            state="open",
            title="](https://malicious.example)",
            url="https://github.com/example/repo/issues/12",
            body_excerpt="",
            updated_at="2026-08-16T00:00:00Z",
        )

        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {
                                "candidate_id": "issue-12",
                                "reason": "<script>not formatting</script>",
                            }
                        ],
                        "duplicate_summary": "[unsafe](https://malicious.example)",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (unsafe_item,),
            snapshot(),
            "test-secret",
            opener=opener,
        )

        self.assertNotIn("[unsafe]", analysis.text)
        self.assertNotIn("<script>", analysis.text)
        self.assertNotIn("](https://malicious.example)", analysis.text)

    def test_parses_no_duplicate_work_estimate(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "estimate": {
                            "size": "medium",
                            "summary": "Add an exporter and tests.",
                            "areas": ["src/export.py", "integration tests"],
                            "risks": ["CSV escaping requirements are unclear."],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(), (), snapshot(), "test-secret", opener=opener
        )

        self.assertEqual(analysis.duplicate_matches, ())
        self.assertEqual(analysis.estimate.size, "medium")
        self.assertIn("Preliminary implementation estimate", analysis.text)

    def test_parses_assessment_wrapped_in_markdown_fence(self):
        assessment = {
            "duplicate_matches": [],
            "duplicate_summary": "No strong duplicate was found.",
            "estimate": {
                "size": "small",
                "summary": "Localized change.",
                "areas": ["src/export.py"],
                "risks": [],
            },
        }

        def opener(request, timeout):
            return FakeResponse(
                {
                    "model": "claude-haiku-4-5-20251001",
                    "content": [
                        {
                            "type": "text",
                            "text": "Here is the assessment:\n```json\n"
                            + json.dumps(assessment)
                            + "\n```",
                        }
                    ],
                    "usage": {"input_tokens": 300, "output_tokens": 80},
                }
            )

        analysis = request_claude_analysis(
            issue_event(), (), snapshot(), "test-secret", opener=opener
        )

        self.assertEqual(analysis.estimate.size, "small")

    def test_retries_malformed_json_then_succeeds(self):
        attempts = []
        sleeps = []

        def opener(request, timeout):
            attempts.append(request)
            if len(attempts) < 2:
                return FakeResponse(
                    {
                        "model": "claude-haiku-4-5-20251001",
                        "content": [
                            {"type": "text", "text": "I cannot assess this issue."}
                        ],
                        "usage": {"input_tokens": 300, "output_tokens": 10},
                    }
                )
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No duplicate.",
                        "estimate": {
                            "size": "unknown",
                            "summary": "More information is required.",
                            "areas": [],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (),
            snapshot(),
            "test-secret",
            opener=opener,
            sleeper=sleeps.append,
        )
        self.assertEqual(len(attempts), 2)
        self.assertEqual(analysis.estimate.size, "unknown")

    def test_raises_readable_error_after_repeated_malformed_json(self):
        def opener(request, timeout):
            return FakeResponse(
                {
                    "model": "claude-haiku-4-5-20251001",
                    "content": [
                        {"type": "text", "text": "I cannot assess this issue."}
                    ],
                    "usage": {"input_tokens": 300, "output_tokens": 10},
                }
            )

        with self.assertRaises(RuntimeError) as context:
            request_claude_analysis(
                issue_event(),
                (),
                snapshot(),
                "test-secret",
                opener=opener,
                sleeper=lambda seconds: None,
            )
        self.assertIn("cannot assess this issue", str(context.exception))

    def test_retries_temporary_claude_errors(self):
        attempts = []
        sleeps = []

        def opener(request, timeout):
            attempts.append(request)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(
                    request.full_url, 429, "rate limited", {}, None
                )
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No duplicate.",
                        "estimate": {
                            "size": "unknown",
                            "summary": "More information is required.",
                            "areas": [],
                            "risks": [],
                        },
                    }
                )
            )

        request_claude_analysis(
            issue_event(),
            (),
            snapshot(),
            "test-secret",
            opener=opener,
            sleeper=sleeps.append,
        )
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1, 2])


class RelatedWorkTests(unittest.TestCase):
    def test_full_mode_reports_related_work_alongside_estimate(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data)
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "related_matches": [
                            {
                                "candidate_id": "pr-30",
                                "relationship": "touches the same code",
                                "reason": "Rewrote the report writer this export uses.",
                            }
                        ],
                        "related_summary": "One merged pull request is adjacent.",
                        "estimate": {
                            "size": "medium",
                            "summary": "Add an exporter and tests.",
                            "areas": ["src/export.py"],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_issue(), related_pull_request()),
            snapshot(),
            "test-secret",
            opener=opener,
        )

        self.assertEqual(len(analysis.related_matches), 1)
        self.assertEqual(analysis.related_matches[0].item.number, 30)
        self.assertEqual(
            analysis.related_matches[0].relationship, "touches the same code"
        )
        self.assertIn("Related issues and pull requests", analysis.text)
        self.assertIn("PR #30", analysis.text)
        self.assertIn("touches the same code", analysis.text)
        # Related work must not suppress the estimate.
        self.assertIn("Preliminary implementation estimate", analysis.text)
        self.assertIn("find-related-issues", captured["payload"]["system"])

    def test_related_work_is_reported_even_when_a_duplicate_exists(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {
                                "candidate_id": "issue-12",
                                "reason": "Requests the same CSV export feature.",
                            }
                        ],
                        "duplicate_summary": "A likely duplicate is already open.",
                        "related_matches": [
                            {
                                "candidate_id": "pr-30",
                                "relationship": "builds on",
                                "reason": "Earlier refactor of the same writer.",
                            }
                        ],
                        "related_summary": "One adjacent pull request.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_issue(), related_pull_request()),
            snapshot(),
            "test-secret",
            opener=opener,
        )

        self.assertIn("Issue #12", analysis.text)
        self.assertIn("PR #30", analysis.text)
        self.assertIsNone(analysis.estimate)

    def test_item_reported_as_duplicate_is_not_repeated_as_related(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {
                                "candidate_id": "issue-12",
                                "reason": "Same CSV export request.",
                            }
                        ],
                        "duplicate_summary": "A likely duplicate is already open.",
                        "related_matches": [
                            {
                                "candidate_id": "issue-12",
                                "relationship": "shares context",
                                "reason": "Repeated by the model.",
                            },
                            {
                                "candidate_id": "issue-999",
                                "relationship": "depends on",
                                "reason": "Invented identifier.",
                            },
                        ],
                        "related_summary": "Adjacent work.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_issue(), related_pull_request()),
            snapshot(),
            "test-secret",
            opener=opener,
        )

        self.assertEqual(analysis.related_matches, ())
        self.assertNotIn("999", analysis.text)
        self.assertEqual(analysis.text.count("Issue #12"), 1)

    def test_unknown_relationship_falls_back_to_a_neutral_label(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "related_matches": [
                            {
                                "candidate_id": "pr-30",
                                "relationship": "**totally invented**",
                                "reason": "Adjacent change.",
                            }
                        ],
                        "related_summary": "One adjacent pull request.",
                        "estimate": {
                            "size": "small",
                            "summary": "Localized change.",
                            "areas": [],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_pull_request(),),
            snapshot(),
            "test-secret",
            opener=opener,
        )

        self.assertEqual(analysis.related_matches[0].relationship, "related")
        self.assertNotIn("totally invented", analysis.text)

    def test_related_only_mode_loads_only_the_related_skill(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data)
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "Duplicate check not requested",
                        "related_matches": [
                            {
                                "candidate_id": "pr-30",
                                "relationship": "depends on",
                                "reason": "Provides the writer this work needs.",
                            }
                        ],
                        "related_summary": "One dependency was found.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_pull_request(),),
            RepositorySnapshot(tree=(), files=()),
            "test-secret",
            mode="related",
            opener=opener,
        )

        self.assertIsNone(analysis.estimate)
        self.assertEqual(analysis.duplicate_matches, ())
        self.assertIn("Related issues and pull requests", analysis.text)
        self.assertNotIn("Duplicate check", analysis.text)
        self.assertIn("find-related-issues", captured["payload"]["system"])
        self.assertNotIn("check-duplicate-issues", captured["payload"]["system"])
        self.assertNotIn("estimate-issue-work", captured["payload"]["system"])

    def test_full_mode_survives_an_omitted_related_list(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "estimate": {
                            "size": "small",
                            "summary": "Localized change.",
                            "areas": [],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(),
            (related_pull_request(),),
            snapshot(),
            "test-secret",
            opener=opener,
            sleeper=lambda seconds: None,
        )

        self.assertEqual(analysis.related_matches, ())
        self.assertIn("No related issues or pull requests were identified", analysis.text)
        self.assertIn("Preliminary implementation estimate", analysis.text)

    def test_escapes_markdown_from_related_titles_and_reasons(self):
        unsafe_item = RelatedItem(
            candidate_id="pr-30",
            number=30,
            kind="pull request",
            state="merged",
            title="](https://malicious.example)",
            url="https://github.com/example/repo/pull/30",
            body_excerpt="",
            updated_at="2026-08-15T12:00:00Z",
        )

        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [],
                        "duplicate_summary": "No strong duplicate was found.",
                        "related_matches": [
                            {
                                "candidate_id": "pr-30",
                                "relationship": "shares context",
                                "reason": "<script>not formatting</script>",
                            }
                        ],
                        "related_summary": "[unsafe](https://malicious.example)",
                        "estimate": {
                            "size": "small",
                            "summary": "Localized change.",
                            "areas": [],
                            "risks": [],
                        },
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(), (unsafe_item,), snapshot(), "test-secret", opener=opener
        )

        self.assertNotIn("[unsafe]", analysis.text)
        self.assertNotIn("<script>", analysis.text)
        self.assertNotIn("](https://malicious.example)", analysis.text)

    def test_related_skill_body_is_loaded_for_full_triage(self):
        prompt = build_system_prompt("full")
        self.assertIn("Compare intent, affected behavior", prompt)
        self.assertIn("touches the same code", prompt)
        self.assertIn("Classify the work as", prompt)

    def test_comment_points_at_related_work_when_no_duplicate_exists(self):
        analysis = ClaudeAnalysis(
            text="### Duplicate check\n\nNone.\n\n### Related issues and pull requests",
            model="test-model",
            input_tokens=None,
            output_tokens=None,
            duplicate_matches=(),
            estimate=WorkEstimate("small", "Small change.", (), ()),
            checked_items=5,
            inspected_files=2,
            related_matches=(
                RelatedMatch(related_pull_request(), "builds on", "Earlier refactor."),
            ),
        )

        comment = render_issue_comment(analysis)

        self.assertIn("related work listed above", comment)
        self.assertNotIn("please close this issue as a duplicate", comment)


class CandidateAgeAndStateTests(unittest.TestCase):
    def _analysis_with_duplicate(self, state: str) -> ClaudeAnalysis:
        item = RelatedItem(
            candidate_id="issue-12",
            number=12,
            kind="issue",
            state=state,
            title="CSV export support",
            url="https://github.com/example/repo/issues/12",
            body_excerpt="",
            updated_at="2019-03-04T12:00:00Z",
            created_at="2019-01-02T12:00:00Z",
        )
        return ClaudeAnalysis(
            text="### Possible duplicates or prior solutions",
            model="test-model",
            input_tokens=None,
            output_tokens=None,
            duplicate_matches=(DuplicateMatch(item, "Same request."),),
            estimate=None,
            checked_items=1,
            inspected_files=0,
        )

    def test_candidate_dates_are_sent_to_claude(self):
        data = related_issue().as_prompt_data()
        self.assertEqual(data["last_activity_at"], "2026-08-16T12:00:00Z")
        self.assertIn("created_at", data)

    def test_api_items_carry_both_dates(self):
        item = _item_from_api(
            {
                "number": 7,
                "title": "Old request",
                "html_url": "https://github.com/example/repo/issues/7",
                "state": "closed",
                "state_reason": "not_planned",
                "body": "Please add CSV export.",
                "created_at": "2018-02-03T09:00:00Z",
                "updated_at": "2019-04-05T09:00:00Z",
            },
            "issue",
        )
        self.assertEqual(item.created_at, "2018-02-03T09:00:00Z")
        self.assertEqual(item.state, "closed (not_planned)")

    def test_rendered_match_shows_last_activity_date(self):
        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {"candidate_id": "issue-12", "reason": "Same request."}
                        ],
                        "duplicate_summary": "A likely duplicate exists.",
                        "related_matches": [],
                        "related_summary": "None.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(), (related_issue(),), snapshot(), "test-secret", opener=opener
        )
        self.assertIn("last active 2026-08-16", analysis.text)

    def test_malformed_date_is_omitted_rather_than_rendered(self):
        item = RelatedItem(
            candidate_id="issue-12",
            number=12,
            kind="issue",
            state="open",
            title="CSV export support",
            url="https://github.com/example/repo/issues/12",
            body_excerpt="",
            updated_at="not-a-date](https://malicious.example)",
        )

        def opener(request, timeout):
            return FakeResponse(
                claude_response(
                    {
                        "duplicate_matches": [
                            {"candidate_id": "issue-12", "reason": "Same request."}
                        ],
                        "duplicate_summary": "A likely duplicate exists.",
                        "related_matches": [],
                        "related_summary": "None.",
                        "estimate": None,
                    }
                )
            )

        analysis = request_claude_analysis(
            issue_event(), (item,), snapshot(), "test-secret", opener=opener
        )
        self.assertNotIn("last active", analysis.text)
        self.assertNotIn("malicious.example", analysis.text)

    def test_declined_duplicate_does_not_ask_for_a_duplicate_close(self):
        comment = render_issue_comment(
            self._analysis_with_duplicate("closed (not_planned)")
        )
        self.assertIn("considered earlier and not carried out", comment)
        self.assertNotIn("please close this issue as a duplicate", comment)

    def test_delivered_duplicate_asks_about_a_regression(self):
        comment = render_issue_comment(self._analysis_with_duplicate("merged"))
        self.assertIn("already delivered", comment)
        self.assertIn("regression", comment)

    def test_closed_without_reason_is_not_treated_as_rejected(self):
        comment = render_issue_comment(self._analysis_with_duplicate("closed"))
        self.assertIn("without a recorded reason", comment)
        self.assertNotIn("not carried out", comment)

    def test_open_duplicate_still_asks_the_author_to_close(self):
        comment = render_issue_comment(self._analysis_with_duplicate("open"))
        self.assertIn("please close this issue as a duplicate", comment)

    def test_skills_cover_state_and_age_guidance(self):
        prompt = build_system_prompt("full")
        self.assertIn("closed (not_planned)", prompt)
        self.assertIn("last_activity_at", prompt)
        self.assertIn("still a duplicate", prompt)


class ContextCollectionTests(unittest.TestCase):
    def test_collects_issues_and_merged_pull_requests(self):
        responses = [
            [
                {
                    "number": 12,
                    "title": "Existing issue",
                    "html_url": "https://github.com/example/repo/issues/12",
                    "state": "open",
                    "body": "Existing body",
                    "updated_at": "2026-08-16T00:00:00Z",
                },
                {
                    "number": 42,
                    "title": "Current issue",
                    "html_url": "https://github.com/example/repo/issues/42",
                    "state": "open",
                    "updated_at": "2026-08-17T00:00:00Z",
                },
            ],
            [
                {
                    "number": 8,
                    "title": "Implemented exporter",
                    "html_url": "https://github.com/example/repo/pull/8",
                    "state": "closed",
                    "merged_at": "2026-08-15T00:00:00Z",
                    "body": "Implementation",
                    "updated_at": "2026-08-15T00:00:00Z",
                }
            ],
        ]

        def opener(request, timeout):
            return FakeResponse(responses.pop(0))

        items = collect_related_items(
            "example/repo", 42, "github-token", opener=opener
        )

        self.assertEqual([item.candidate_id for item in items], ["issue-12", "pr-8"])
        self.assertEqual(items[1].state, "merged")

    def test_fetches_existing_issue_for_manual_triage(self):
        def opener(request, timeout):
            return FakeResponse(
                {
                    "number": 12,
                    "title": "Existing issue",
                    "body": "Issue body",
                    "html_url": "https://github.com/example/repo/issues/12",
                }
            )

        event = fetch_issue_event(
            "example/repo", 12, "github-token", opener=opener
        )
        self.assertEqual(event["issue"]["number"], 12)

    def test_repository_snapshot_excludes_sensitive_and_generated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "issues").mkdir()
            (root / "src" / "export.py").write_text("def csv_export(): pass")
            (root / ".env").write_text("TOKEN=do-not-send")
            (root / "issues" / "issue-1.md").write_text("generated")

            result = collect_repository_snapshot(root, issue_event())

        selected_paths = [path for path, _ in result.files]
        self.assertIn("src/export.py", selected_paths)
        self.assertNotIn(".env", result.tree)
        self.assertNotIn("issues/issue-1.md", result.tree)


class ArchiveRenderingTests(unittest.TestCase):
    def test_renders_duplicate_analysis_and_close_request(self):
        item = related_issue()
        analysis = ClaudeAnalysis(
            text="### Possible duplicates\n\n- Issue #12",
            model="test-model",
            input_tokens=100,
            output_tokens=20,
            duplicate_matches=(DuplicateMatch(item, "Same request."),),
            estimate=None,
            checked_items=10,
            inspected_files=3,
        )

        number, rendered = render_issue(issue_event(), analysis)
        comment = render_issue_comment(analysis)

        self.assertEqual(number, 42)
        self.assertIn("## Claude analysis", rendered)
        self.assertIn(COMMENT_MARKER, comment)
        self.assertIn("please close this issue as a duplicate", comment)

    def test_renders_no_duplicate_estimate_comment(self):
        estimate = WorkEstimate("small", "Small change.", ("src/export.py",), ())
        analysis = ClaudeAnalysis(
            text="### Duplicate check\n\nNone.\n\n### Preliminary implementation estimate",
            model="test-model",
            input_tokens=None,
            output_tokens=None,
            duplicate_matches=(),
            estimate=estimate,
            checked_items=0,
            inspected_files=1,
        )
        comment = render_issue_comment(analysis)
        self.assertIn("No strong duplicate was found", comment)
        self.assertIn("not a delivery commitment", comment)


class CommentPostingTests(unittest.TestCase):
    def test_creates_comment_when_marker_does_not_exist(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse([] if request.method == "GET" else {"id": 10})

        result = upsert_issue_comment(
            "example/repo",
            42,
            "github-token",
            f"{COMMENT_MARKER}\nComment",
            opener=opener,
        )
        self.assertEqual(result, "created")
        self.assertEqual([request.method for request in requests], ["GET", "POST"])

    def test_updates_existing_bot_comment_on_rerun(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.method == "GET":
                return FakeResponse(
                    [
                        {
                            "id": 99,
                            "body": COMMENT_MARKER,
                            "user": {"login": "github-actions[bot]"},
                        }
                    ]
                )
            return FakeResponse({"id": 99})

        result = upsert_issue_comment(
            "example/repo",
            42,
            "github-token",
            f"{COMMENT_MARKER}\nUpdated",
            opener=opener,
        )
        self.assertEqual(result, "updated")
        self.assertEqual([request.method for request in requests], ["GET", "PATCH"])
        self.assertTrue(requests[1].full_url.endswith("/issues/comments/99"))


class ManualTriageTests(unittest.TestCase):
    def test_writes_read_only_estimate_to_job_summary(self):
        analysis = ClaudeAnalysis(
            text="### Preliminary implementation estimate\n\n- **Size:** small",
            model="test-model",
            input_tokens=100,
            output_tokens=20,
            duplicate_matches=(),
            estimate=WorkEstimate("small", "Localized change.", (), ()),
            checked_items=0,
            inspected_files=1,
            mode="estimate",
        )
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            environment = {
                "TRIAGE_MODE": "estimate",
                "TRIAGE_ISSUE_NUMBER": "",
                "TRIAGE_TITLE": "Add CSV export",
                "TRIAGE_REQUIREMENT": "Export reports as CSV.",
                "GITHUB_REPOSITORY": "example/repo",
                "GITHUB_TOKEN": "github-token",
                "ANTHROPIC_API_KEY": "test-secret",
                "CLAUDE_MODEL": "test-model",
                "GITHUB_STEP_SUMMARY": str(summary_path),
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch.object(
                    manual_triage,
                    "collect_repository_snapshot",
                    return_value=snapshot(),
                ),
                patch.object(
                    manual_triage,
                    "request_claude_analysis",
                    return_value=analysis,
                ) as request_mock,
            ):
                manual_triage.main()

            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("Claude repository triage", summary)
        self.assertIn("Add CSV export", summary)
        self.assertIn("Preliminary implementation estimate", summary)
        self.assertEqual(request_mock.call_args.kwargs["mode"], "estimate")


if __name__ == "__main__":
    unittest.main()
