# GitHub Actions test repository

This repository is used to test GitHub Actions incrementally.

The first workflow asks Claude to check each newly opened issue against another
repository's history, defaulting to `IQSS/dataverse`, using keyword search over
its full issue and pull-request history. It posts possible duplicates, any related work worth
reading first, and a preliminary code-based work estimate, then archives the
issue and analysis as Markdown. The same checks are available as project Claude
skills and as manual Actions runs without opening a new issue. See
[GitHub Actions setup](docs/github-actions-setup.md) for configuration, testing,
cost controls, and credential-safety guidance.
