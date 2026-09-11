# Issue #6: Add keyboard shortcuts for common actions

- **Original issue:** [#6](https://github.com/jp-tosca/GA-Test/issues/6)
- **Author:** [jp-tosca](https://github.com/jp-tosca)
- **Opened:** 2026-09-11T02:44:41Z
- **Labels at opening:** None

## Description

Frequent tasks require several clicks. Please add keyboard shortcuts for common actions, with a small help overlay listing the available shortcuts, and let a signed-in person turn the shortcuts off if they conflict with assistive software.

## Claude analysis

- **Model:** `claude-haiku-4-5-20251001`
- **Usage:** 36137 input tokens, 635 output tokens

### Duplicate check

No strong duplicates found. The proposed work is a new feature request for keyboard shortcuts with a help overlay and user preference toggle. While issue-7523 addresses accessibility broadly and issue-4423 addressed keyboard navigation for a specific component, neither proposes keyboard shortcuts for common actions.

### Related issues and pull requests

Three items provide useful context: a broad accessibility initiative (issue-7523) that keyboard shortcuts would support, a prior keyboard navigation fix (issue-4423) that established the importance of keyboard access, and a recent PR (pr-12188) demonstrating feature-flag patterns for opt-in hardening that could apply to keyboard shortcuts.

- [Issue #7523: Accessibility: Universal Design alignment of Dataverse](https://github.com/IQSS/dataverse/issues/7523) — **open**, last active 2024-12-19 · _shares context_: Open accessibility issue tracking Universal Design alignment; keyboard shortcuts are an accessibility enhancement that aligns with this broader initiative
- [Issue #4423: Accessibility - Subject selection in "Add Dataset" can't be accessed via keyboard tabbing](https://github.com/IQSS/dataverse/issues/4423) — **closed (completed)**, last active 2019-11-20 · _shares context_: Closed issue about keyboard accessibility for subject selection; keyboard shortcuts build on keyboard navigation improvements and share the goal of keyboard-first usability
- [PR #12188: 12178 session cookie CSRF protections](https://github.com/IQSS/dataverse/pull/12188) — **open**, last active 2026-09-10 · _shares context_: Open PR adding session cookie CSRF protections and feature flags; keyboard shortcuts would likely need a feature flag for opt-in behavior, similar to the pattern in this PR

### Preliminary implementation estimate

- **Size:** medium
- **Summary:** Keyboard shortcuts require UI component work (help overlay), keyboard event handling, user preference storage, and testing. The feature flag pattern is established in the codebase. Main unknowns are scope (which actions get shortcuts) and whether to integrate with existing accessibility settings or create new ones.

**Likely work areas**

- Frontend UI component for help overlay (likely React or JSF template)
- Keyboard event listener and routing logic (likely in main layout or app shell)
- User preference storage (settings table or user profile)
- Feature flag or configuration for opt-in behavior
- Accessibility settings or preferences page
- Integration tests for keyboard event handling
- Documentation of available shortcuts

**Risks and open questions**

- Conflict with browser and assistive software keyboard shortcuts—requires careful selection and user override capability
- Scope creep on which actions receive shortcuts
- Complexity of keyboard event handling across different UI contexts (JSF vs. modern SPA)
- Ensuring help overlay is itself keyboard-accessible
- Performance impact if event listeners are not efficiently scoped
