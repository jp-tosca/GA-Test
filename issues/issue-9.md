# Issue #9: Add download of multiple selected files as one zip archive

- **Original issue:** [#9](https://github.com/jp-tosca/GA-Test/issues/9)
- **Author:** [jp-tosca](https://github.com/jp-tosca)
- **Opened:** 2026-09-11T13:21:17Z
- **Labels at opening:** None

## Description

Downloading files one at a time is slow for datasets with many files. Please let a person tick several files and download them together as a single zip archive, keeping the folder structure inside the archive.

## Claude analysis

- **Model:** `claude-haiku-4-5-20251001`
- **Usage:** 43858 input tokens, 667 output tokens

### Possible duplicates or prior solutions

This is a strong duplicate of issue-338, which was completed and merged years ago. The proposed work requests the ability to select multiple files via checkboxes and download them as a single zip archive while preserving folder structure—the exact functionality that issue-338 delivered. Verification needed: confirm whether this feature regressed, was removed, or the requester is unaware it exists.

- [Issue #338: Add download-multiple-files-as-one-zip-archive, similar to 3.6.*](https://github.com/IQSS/dataverse/issues/338) — **closed (completed)**, last active 2015-01-22: Exact duplicate: issue-338 is titled 'Add download-multiple-files-as-one-zip-archive, similar to 3.6.*' and was closed as completed in 2015, implementing the exact feature requested here

### Related issues and pull requests

Multiple related issues exist around archive handling and file download. A critical blocker is issue-11207 (damaged zip archives), which must be resolved before implementing or re-enabling multi-file zip downloads. The API foundation was analyzed in closed spikes (9996, 9997). A modern file-selection UI component is under development (PR-12382) that could support this feature.

- [Issue #11591: Feature Request: Support server-side zipping of select files to reduce number of files in Dataset](https://github.com/IQSS/dataverse/issues/11591) — **open**, last active 2026-01-15 · _shares context_: Open feature request for server-side zipping of selected files to reduce dataset file count; complements multi-file download by offering curator-level compression into a single ZIP
- [Issue #11207: File download via Zipdownloader tool creates damaged archives?](https://github.com/IQSS/dataverse/issues/11207) — **open**, last active 2025-02-05 · _conflicts with_: Open bug: file download via Zipdownloader creates damaged archives with extra bytes; directly impacts the reliability of any multi-file zip download feature
- [Issue #9996: &#91;Spike - API&#93; Extend the API to replicate the JSF behavior of downloading all dataset files](https://github.com/IQSS/dataverse/issues/9996) — **closed (completed)**, last active 2026-01-15 · _builds on_: Closed spike to extend API to replicate JSF dataset download behavior; multi-file zip download is part of the download options that need API support
- [Issue #9997: &#91;Spike - API&#93; Analyze the required API extension to support downloading all dataset files](https://github.com/IQSS/dataverse/issues/9997) — **closed (completed)**, last active 2026-01-15 · _builds on_: Closed spike analyzing API extension for downloading all dataset files; foundational analysis for multi-file download feature
- [Issue #8029: Support uploading of archives (ZIP, other).](https://github.com/IQSS/dataverse/issues/8029) — **open**, last active 2026-05-07 · _shares context_: Open feature request to support uploading archives; inverse operation to downloading multiple files as zip, shares archive handling infrastructure concerns
- [PR #12382: Reusable React components on JSF: file uploader and lazy file tree view (#6691, #12179)](https://github.com/IQSS/dataverse/pull/12382) — **open**, last active 2026-09-11 · _touches the same code_: Open PR for reusable React file tree and uploader component; UI infrastructure that could support file selection for multi-file download
