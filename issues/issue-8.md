# Issue #8: SchemaDotOrgExporter.java does not close jsonReader

- **Original issue:** [#8](https://github.com/jp-tosca/GA-Test/issues/8)
- **Author:** [jp-tosca](https://github.com/jp-tosca)
- **Opened:** 2026-09-11T02:50:07Z
- **Labels at opening:** None

## Description

Downloading files one at a time is slow for datasets with many files. Please let a person tick several files and download them together as a single zip archive, keeping the folder structure inside the archive.

## Claude analysis

- **Model:** `claude-haiku-4-5-20251001`
- **Usage:** 35829 input tokens, 446 output tokens

### Possible duplicates or prior solutions

The title matches issue-4669 exactly, but the body describes a completely different feature (bulk zip download). This appears to be a mislabeled issue where the title does not match the actual request. The jsonReader resource leak was already fixed in 2018.

- [Issue #4669: SchemaDotOrgExporter.java doesn't close jsonReader](https://github.com/IQSS/dataverse/issues/4669) — **closed (completed)**, last active 2018-05-21: Exact match: issue-4669 is titled 'SchemaDotOrgExporter.java doesn't close jsonReader' and was closed (completed) in 2018. The proposed work title is 'SchemaDotOrgExporter.java does not close jsonReader'. However, the proposed work body describes bulk file download as zip, which is unrelated to the jsonReader issue.

### Related issues and pull requests

The bulk zip download feature would integrate with existing file selection and download infrastructure. Related work includes the modern file uploader/tree component (PR-12382) and file storage/download hardening efforts.

- [PR #12382: Reusable React components on JSF: file uploader and lazy file tree view (#6691, #12179)](https://github.com/IQSS/dataverse/pull/12382) — **open**, last active 2026-09-10 · _touches the same code_: Open PR for reusable React file uploader and tree view that includes file selection and download capabilities, directly relevant to multi-file selection and download workflows.
- [Issue #12660: multipartEnabled breaks downloading/publishing large datafiles uploaded from webui to s3 bucket](https://github.com/IQSS/dataverse/issues/12660) — **closed (completed)**, last active 2026-09-08 · _shares context_: Closed issue about multipart upload/download for large files to S3, relevant to understanding file download infrastructure and constraints.
- [PR #12690: Harden dataset storage cleanup](https://github.com/IQSS/dataverse/pull/12690) — **open**, last active 2026-09-10 · _shares context_: Open PR hardening dataset storage cleanup; touches file management and download logic that would interact with bulk download feature.
