# GitHub Actions test repository

This repository is used to test GitHub Actions incrementally.

The first workflow asks Claude to check each newly opened issue against recent
issues and pull requests. It posts possible duplicates or a preliminary
code-based work estimate, then archives the issue and analysis as Markdown.
The same checks are available as project Claude skills and as manual Actions
runs without opening a new issue. See
[GitHub Actions setup](docs/github-actions-setup.md) for configuration, testing,
cost controls, and credential-safety guidance.
