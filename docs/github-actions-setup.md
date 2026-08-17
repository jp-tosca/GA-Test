# GitHub Actions setup

## Issue archive and Claude analysis workflow

The `Claude issue triage` workflow runs when an issue is opened. It collects a
bounded view of recent repository history and relevant code, sends that context
with the new issue to the Anthropic Messages API, and asks Claude to:

1. Identify strong matches among existing issues and open, closed, or merged
   pull requests.
2. If no strong duplicate exists, inspect the supplied code excerpts and provide
   a preliminary small, medium, large, or unknown implementation estimate.

The workflow archives the issue and assessment in `issues/issue-N.md`, commits
that file to the default branch as `github-actions[bot]`, and replies to the
issue. A duplicate reply links the possible prior work and asks the author to
close the issue if it is already covered. Otherwise, the reply explains the
preliminary work estimate. Rerunning the workflow updates the bot's existing
marked comment instead of creating another one.

The reply step still runs when the archive push is rejected, provided the Claude
assessment was generated. This keeps branch-protection problems from suppressing
the requested issue triage.

If Claude cannot provide a valid response, the workflow fails without committing
an incomplete snapshot or posting a new reply and can be rerun from **Actions**.

## Shared Claude skills

The analysis procedures live in repository-local Agent Skills:

- `.claude/skills/check-duplicate-issues/SKILL.md`
- `.claude/skills/estimate-issue-work/SKILL.md`

Claude Code discovers these project skills from the repository. They can be
invoked directly without opening an issue:

```text
/check-duplicate-issues 42
/estimate-issue-work 42
/check-duplicate-issues Add CSV export support to reporting
/estimate-issue-work Add CSV export support to reporting
```

The automated workflow loads the instruction bodies from these same files into
its Claude API system prompt. A duplicate-only run loads only the duplicate
skill, an estimate-only run loads only the estimate skill, and full issue triage
loads both. The Python scripts still perform authentication, bounded context
collection, candidate validation, safe rendering, and GitHub mutations.

Changing a skill changes both future Claude Code usage and future automated API
runs after the change reaches the default branch. Treat skill changes like code
changes and review them before merging.

## Required configuration

### 1. Create a dedicated Anthropic API key

1. Sign in to the [Anthropic Console](https://console.anthropic.com/).
2. Create an API key dedicated to this repository or automation purpose.
3. Configure an appropriate usage or spending limit in Anthropic. This is
   especially important for a public repository because anyone who can open an
   issue can trigger a paid API request.
4. Copy the key temporarily. Do not paste it into a source file, issue, workflow,
   chat message, or terminal command that stores it in shell history.

### 2. Add the key as a GitHub Actions secret

1. Open the repository on GitHub.
2. Select **Settings > Secrets and variables > Actions**.
3. Select **New repository secret**.
4. Enter `ANTHROPIC_API_KEY` as the name and the Anthropic API key as the value.
5. Save the secret and clear the key from the clipboard when practical.

The secret must be a GitHub **Actions secret**, not a Dependabot or Codespaces
secret. GitHub does not display its value after it is saved.

As an alternative, GitHub CLI can prompt for the value without placing it in the
command itself:

```shell
gh secret set ANTHROPIC_API_KEY
```

Never use `gh secret set ANTHROPIC_API_KEY --body "the-key"`, because that can
expose the value in shell history or process information.

### 3. Optionally select a Claude model

The workflow defaults to `claude-haiku-4-5`, a fast and economical model suited
to issue summarization. To choose another currently supported model:

1. Open **Settings > Secrets and variables > Actions > Variables**.
2. Create a repository variable named `CLAUDE_MODEL`.
3. Set its value to a model ID from the
   [Anthropic models overview](https://platform.claude.com/docs/en/about-claude/models/overview).

The model name is configuration, not a credential, so it belongs in a variable
rather than a secret.

### 4. Enable and test the workflow

1. Commit and push the workflow and scripts to the repository's default branch.
   The `issues` event cannot trigger a workflow that exists only on another
   branch.
2. In **Settings > Actions > General**, confirm that GitHub Actions is enabled.
3. Open a test issue with a title and description.
4. Inspect the `Claude issue triage` run in the **Actions** tab.
5. Confirm that a new `issues/issue-N.md` file was committed by
   `github-actions[bot]`, contains a `Claude analysis` section, and that the bot
   replied to the issue with the same duplicate or implementation assessment.

The test consumes Anthropic API tokens. Delete or close the test issue as
appropriate; closing it does not trigger another analysis.

### 5. Run a check manually from GitHub Actions

1. Open **Actions > Claude issue triage > Run workflow**.
2. Select the repository's reviewed default branch, then select `full`,
   `duplicates`, or `estimate`. Do not run an unreviewed workflow branch with
   repository secrets.
3. Either enter an existing issue number, or leave it empty and provide a
   proposed title and optional requirement.
4. Run the workflow and open its job summary to read the result.

Manual runs are read-only: they do not create an issue, post a comment, or commit
an archive. They use the same `ANTHROPIC_API_KEY`, model variable, context limits,
validation, and skill instructions as automatic runs.

## Authentication and permissions

Two separate tokens are involved:

- `ANTHROPIC_API_KEY` is the repository secret you configure. It is available
  only to the snapshot-generation step and authenticates the Claude request.
- `GITHUB_TOKEN` is automatically created by GitHub for each workflow job. It is
  short-lived and reads issue/PR history, authenticates the repository push, and
  creates or updates the issue reply. Do not create a personal access token for
  this purpose.

The automatic issue job limits `GITHUB_TOKEN` to its required permissions:

```yaml
permissions:
  contents: write
  issues: write
  pull-requests: read
```

`issues: write` includes the issue access needed to read history and reply.
`pull-requests: read` provides merged pull-request history. No additional GitHub
credential or secret is required.

The manual job cannot write repository or issue content:

```yaml
permissions:
  contents: read
  issues: read
  pull-requests: read
```

An organization policy can still restrict this permission. If the push is
rejected, check the run log and the default branch's ruleset or branch-protection
settings. A rule requiring pull requests can intentionally block direct pushes
by `github-actions[bot]`. Prefer changing the workflow to open a pull request or
granting a narrowly scoped GitHub App an allowed bypass instead of weakening
branch protection or using an administrator's personal token.

## Security and cost controls

- Issue content is untrusted. It is read from GitHub's JSON event file, never
  interpolated into a shell command, and presented to Claude as data under a
  system instruction that rejects embedded directions.
- The committed skill instructions are trusted workflow configuration. Issue,
  pull-request, and repository text cannot replace or modify those instructions
  during a run.
- Claude receives no tools and cannot access the runner, GitHub token, or
  Anthropic key. The API key is sent only in the HTTPS authentication header.
- Claude receives at most 50 recently updated issues and 50 recently updated
  pull requests, with each historical description limited to 600 characters.
  This is a useful bounded duplicate check, not a guarantee that very old or
  semantically distant prior work will always be found.
- Repository inspection is limited to 25 relevant text files, 6,000 characters
  per file, and 40,000 characters total. Generated issue archives, dependency
  directories, skill definitions, binary files, symlinks, and sensitive-looking
  file names or key extensions are excluded.
- The new issue body sent to Claude is limited to 12,000 characters, and Claude's
  response is limited to 1,000 tokens. Temporary API failures are retried at most
  three times.
- Claude must select duplicates by candidate ID from the GitHub results. IDs it
  invents are discarded, and all links in the comment come from GitHub's API.
- The bot comment contains a hidden marker. On a workflow rerun, only a matching
  comment owned by `github-actions[bot]` is updated, preventing duplicate replies.
- The generated Markdown preserves the original issue body and Claude output.
  Review rendered links before following them.
- The checkout action is pinned to a full commit SHA to prevent an upstream tag
  from changing unexpectedly.
- A push is retried after rebasing on the latest default branch, reducing
  failures when issues are opened or other commits land at nearly the same time.
- For a public or high-traffic repository, configure Anthropic spending limits.
  A later hardening step could require a maintainer-applied label or trusted
  author association before making the paid request.

Sending an issue to Claude transfers its title, up to 12,000 characters of its
description, bounded historical issue/PR excerpts, the repository file tree, and
selected code excerpts to Anthropic. Confirm that this is acceptable for the
data, licensing, and privacy requirements of the repository, particularly when
it is private.

## Rotation and incident response

Rotate the Anthropic key periodically and immediately if exposure is suspected:

1. Revoke the old key in the Anthropic Console.
2. Create a replacement key.
3. Update the `ANTHROPIC_API_KEY` Actions secret in GitHub.
4. Review Anthropic usage and GitHub Actions logs for unexpected activity.

GitHub attempts to redact registered secrets from logs, but redaction is not a
substitute for avoiding output of secrets. If a key was committed, revoke it
before removing it from Git history; deleting the visible file alone does not
invalidate the exposed credential.

## Troubleshooting

- **`ANTHROPIC_API_KEY is not configured`:** add or update the repository Actions
  secret using the exact name above.
- **HTTP 401 or 403:** the Anthropic key is invalid, revoked, or not authorized.
- **HTTP 400 or model error:** remove or correct the `CLAUDE_MODEL` variable.
- **HTTP 429:** review the Anthropic rate and spending limits. The workflow
  retries temporary rate limits three times before failing.
- **Push rejected:** review `GITHUB_TOKEN` permissions and default-branch rules.
- **Issue reply rejected:** confirm that the workflow has `issues: write` and
  that organization policy allows that permission.
- **Duplicate was missed:** the automated review is intentionally bounded to 50
  recent issues and 50 recent pull requests. A maintainer should verify uncertain
  results manually.
- **No workflow run:** confirm that the workflow is on the default branch and
  Actions is enabled.
- **Manual run rejects its input:** provide either a positive issue number or a
  proposed title. The requirement alone is not enough to identify the work.
- **Claude Code does not show the skills:** open Claude Code from this repository
  and confirm the two `SKILL.md` files are present on the checked-out branch.

## Local tests

The test suite mocks the Claude HTTP response and does not require a key or
consume API credits:

```shell
python -m unittest discover -s tests -v
```

Validate the skill metadata with the skill validator available in the authoring
environment. The repository tests also verify that each API mode loads the
correct skill body and that full triage loads both.

## References

- [Get started with the Claude API](https://platform.claude.com/docs/en/get-started)
- [Claude Code project skills](https://code.claude.com/docs/en/slash-commands)
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Anthropic models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic prompt-injection guidance](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)
- [GitHub issue workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues)
- [GitHub issue API](https://docs.github.com/en/rest/issues/issues)
- [GitHub issue comments API](https://docs.github.com/en/rest/issues/comments)
- [Using GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [Use `GITHUB_TOKEN` for authentication](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication)
- [Managing GitHub Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
