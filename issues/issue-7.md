# Issue #7: Support two-factor authentication at sign-in

- **Original issue:** [#7](https://github.com/jp-tosca/GA-Test/issues/7)
- **Author:** [jp-tosca](https://github.com/jp-tosca)
- **Opened:** 2026-09-11T02:49:30Z
- **Labels at opening:** None

## Description

A password is currently the only thing protecting a login. Please support a second factor at sign-in using a time-based one-time code from an authenticator app, with recovery codes for anyone who loses their phone, and a setting so an administrator can require the second factor for privileged roles.

## Claude analysis

- **Model:** `claude-haiku-4-5-20251001`
- **Usage:** 48252 input tokens, 960 output tokens

### Duplicate check

No strong duplicates found. The proposed work is a new feature request for two-factor authentication (2FA) at sign-in using time-based one-time codes, recovery codes, and admin-configurable enforcement for privileged roles. The candidate history contains extensive authentication-related work but no prior issues requesting this specific 2FA capability.

### Related issues and pull requests

Related work includes prior security-hardening efforts (CAPTCHA, CSRF protections), existing MFA documentation for Shibboleth, and recent authentication architecture refactoring. The authentication system has undergone significant modernization with filter-based design and OIDC support, which provides the foundation for implementing 2FA.

- [Issue #8137: CAPTCHA for Sign Up (creation of local/builtin users)](https://github.com/IQSS/dataverse/issues/8137) — **open**, last active 2023-02-10 · _shares context_: Open issue requesting CAPTCHA for sign-up; both are security-hardening features for user authentication flows, though this addresses registration while the proposed work addresses sign-in.
- [Issue #8076: Shibboleth: document Multi-Factor Authentication](https://github.com/IQSS/dataverse/issues/8076) — **closed (completed)**, last active 2021-08-24 · _shares context_: Closed issue documenting Shibboleth Multi-Factor Authentication; provides precedent for MFA discussion in Dataverse and shows how MFA was handled for federated identity providers.
- [PR #12188: 12178 session cookie CSRF protections](https://github.com/IQSS/dataverse/pull/12188) — **open**, last active 2026-09-10 · _shares context_: Open PR adding CSRF protections for session-cookie auth; both are security enhancements to authentication mechanisms, though this focuses on CSRF while the proposed work adds a second authentication factor.
- [Issue #9293: New filter-based design for the API authentication mechanisms](https://github.com/IQSS/dataverse/issues/9293) — **closed (completed)**, last active 2026-01-15 · _shares context_: Closed issue describing refactor to filter-based API authentication design; understanding the current authentication architecture is essential for implementing 2FA, as it may need to integrate with the new filter-based approach.
- [Issue #5974: As a Dataverse admin, I would like to hook up my installation to an IDM/IAM](https://github.com/IQSS/dataverse/issues/5974) — **closed (completed)**, last active 2022-09-30 · _shares context_: Closed issue about hooking Dataverse to an IDM/IAM system; 2FA implementation may need to consider integration with external identity management systems that already provide MFA capabilities.

### Preliminary implementation estimate

- **Size:** large
- **Summary:** Two-factor authentication is a cross-cutting security feature requiring changes to login flow, user account management, database schema, UI/UX, and admin configuration. Implementation must integrate with existing authentication providers (builtin, OAuth2, OIDC, Shibboleth) and support recovery codes and role-based enforcement.

**Likely work areas**

- Authentication flow and login pages (JSF and SPA)
- AuthenticationServiceBean and related authentication providers
- User account entity and database schema (TOTP secrets, recovery codes, 2FA settings)
- Admin settings and configuration UI for 2FA enforcement policies
- API endpoints for 2FA setup, verification, and recovery code management
- User notification/email for 2FA setup and recovery code backup
- Session management to enforce 2FA verification before granting access
- Tests for 2FA flows across different authentication providers

**Risks and open questions**

- Complexity of integrating 2FA with multiple authentication providers (builtin, OAuth2, OIDC, Shibboleth) which may have different capabilities
- User experience impact: 2FA adds friction to login; recovery code management and loss scenarios need careful handling
- Backward compatibility: existing sessions and API tokens must continue working; 2FA enforcement must be optional initially
- Time-based code generation and validation requires careful clock synchronization handling
- Admin enforcement policy must not lock out administrators or create unrecoverable states
- Unclear whether 2FA should apply to API authentication (bearer tokens, API keys) or only interactive login
- Interaction with existing session-based and token-based authentication mechanisms needs clarification
