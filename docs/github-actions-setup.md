# GitHub Actions setup

## Issue archive workflow

The `Archive opened issue` workflow runs when an issue is opened. It creates
`issues/issue-N.md` from the issue title, author, creation time, labels, URL,
and description, then commits that file to the repository's default branch.

The workflow must be present on the default branch before the `issues` event
can trigger it. To test it, merge or push these files to the default branch,
open a test issue, and inspect the repository's **Actions** tab. A successful
run creates a commit authored by `github-actions[bot]`.

## Authentication and permissions

No manually created key is required. GitHub automatically creates a short-lived
`GITHUB_TOKEN` for each job. This workflow limits that token to the one
permission it needs:

```yaml
permissions:
  contents: write
```

Do not add a personal access token for this workflow. The checkout action uses
the built-in token and stores it only for the duration of the job so the final
`git push` can authenticate.

In **Settings > Actions > General**:

1. Confirm that GitHub Actions is enabled for the repository.
2. Review **Workflow permissions**. The workflow declares its own least-privilege
   `contents: write` permission, but an organization policy can still restrict it.

If the push is rejected, check the run log and the default branch's ruleset or
branch-protection settings. A rule requiring pull requests can intentionally
block direct pushes by `github-actions[bot]`. Prefer changing this automation to
open a pull request, or granting a narrowly scoped GitHub App an allowed bypass,
instead of weakening protection or using an administrator's personal token.

## Safely adding a secret if a future workflow needs one

The current workflow does not need this procedure. For a future external API or
service credential:

1. Create a dedicated, least-privilege credential with an expiry date. Prefer a
   GitHub App or short-lived identity token over a personal access token.
2. Open **Settings > Secrets and variables > Actions**.
3. Add it as a repository or environment secret. Use an environment when you
   want approval gates or tighter deployment access.
4. Reference it as `${{ secrets.SECRET_NAME }}`. Never place the value in the
   workflow YAML, source files, command arguments, issue text, or logs.
5. Limit the job's `permissions`, pin third-party actions to full commit hashes,
   rotate the credential, and delete it when it is no longer needed.

GitHub attempts to redact registered secrets from logs, but redaction is not a
substitute for avoiding output of secrets. If a secret is exposed, revoke it
immediately, remove it from Git history if committed, and issue a replacement.

## Security notes

- Issue content is untrusted input. The workflow reads it from GitHub's JSON
  event file and writes it as Markdown; it never interpolates the title or body
  into a shell command.
- The checkout action is pinned to a full commit SHA to prevent an upstream tag
  from changing unexpectedly.
- The generated Markdown preserves the issue body, including links or HTML that
  an author supplied. Review rendered links before following them.
- A push is retried after rebasing on the latest default branch, reducing
  failures when issues are opened or other commits land at nearly the same time.

## References

- [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues)
- [Use `GITHUB_TOKEN` for authentication](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication)
- [Managing GitHub Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [Using secrets in GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
