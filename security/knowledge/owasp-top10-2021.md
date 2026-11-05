# OWASP Top 10 (2021) — Triage Taxonomy

Use this file first on every incoming ticket: map the vulnerability
description to exactly one row, then open the linked cheat sheet file(s)
under [`cheatsheets/`](cheatsheets) before writing any patch. Source:
[owasp.org/Top10/2021](https://owasp.org/Top10/2021/A00_2021_Introduction/index.html).

| # | Category | What it actually means | Typical trigger terms in a ticket | Relevant cheat sheets |
|---|---|---|---|---|
| A01 | Broken Access Control | A user can act on, or see, data/functions they shouldn't — missing or wrong authorization checks, not missing authentication. | IDOR, "privilege escalation", "forced browsing", "missing authorization", "any user can access", path/param tampering | [access-control.md](cheatsheets/access-control.md) |
| A02 | Cryptographic Failures | Sensitive data exposed in transit or at rest because it's unencrypted, weakly encrypted, or encrypted with mismanaged keys. (Renamed from "Sensitive Data Exposure" — the *cause*, not the symptom.) | "cleartext", "weak cipher", "MD5/SHA1 for passwords", "hardcoded key", "no TLS", PII/PAN exposure | [cryptography.md](cheatsheets/cryptography.md), [secrets-management.md](cheatsheets/secrets-management.md) |
| A03 | Injection | Untrusted input is interpreted as code/structure by an interpreter (SQL, OS shell, LDAP, XPath, template engine) because it wasn't parameterized/escaped. Includes XSS (merged into this category in 2021). | SQLi, XSS, command injection, "string concatenation into query", template injection | [injection.md](cheatsheets/injection.md), [xss.md](cheatsheets/xss.md) |
| A04 | Insecure Design | The flaw is in the design/threat model, not a single coding bug — e.g. no rate limit on a password reset flow, missing business-logic constraint. Can't be patched with a one-line fix; needs a control added to the design. | "business logic flaw", "missing rate limit", "no anti-automation", "race condition", workflow can be skipped/reordered | [access-control.md](cheatsheets/access-control.md) + flag for human design review |
| A05 | Security Misconfiguration | Insecure defaults, verbose errors, unnecessary features/ports/accounts enabled, missing security headers, permissive CORS. | "debug mode enabled", "default credentials", "directory listing", "missing security headers", "verbose stack trace" | [api-security.md](cheatsheets/api-security.md) (headers/CORS section) |
| A06 | Vulnerable and Outdated Components | A dependency (library, framework, OS package) has a known CVE or is unsupported/EOL. | CVE ID, "outdated dependency", Dependabot/Snyk/Renovate alert, package name + version | No cheat sheet needed — the fix is a version bump + changelog/breaking-change check, not a code rewrite |
| A07 | Identification and Authentication Failures | Weak login, session, or credential-recovery mechanisms — not access control *after* login. | "weak password policy", "session fixation", "credential stuffing", "no MFA", "predictable session token" | [authentication.md](cheatsheets/authentication.md), [session-management.md](cheatsheets/session-management.md) |
| A08 | Software and Data Integrity Failures | Code/data integrity isn't verified — insecure deserialization, unsigned auto-updates, CI/CD supply-chain trust issues. | "insecure deserialization", "unsigned artifact", "pickle/yaml.load", "untrusted plugin" | [deserialization.md](cheatsheets/deserialization.md) |
| A09 | Security Logging and Monitoring Failures | Attacks aren't detectable/forensically reconstructable — missing, insufficient, or sensitive-data-leaking logs; no alerting. | "no audit log", "logs don't capture X", "PII in logs", "no alerting on failed logins" | No dedicated file yet — apply: log auth/access-control events, never log secrets/PII, ensure logs are tamper-evident |
| A10 | Server-Side Request Forgery (SSRF) | The server fetches a URL supplied (directly or indirectly) by a user, letting an attacker reach internal services/metadata endpoints. | "SSRF", "server fetches user-supplied URL", webhook/callback URL fields, image/PDF-from-URL features | [ssrf.md](cheatsheets/ssrf.md) |

## Notes for the agent

- **CSRF is not in the current Top 10** (dropped in 2021 because frameworks
  now mitigate it by default) but is still a real, common finding — see
  [csrf.md](cheatsheets/csrf.md) if a ticket mentions it explicitly.
- A06 (vulnerable components) is the one category where the "small blast
  radius" rule bends: bumping a major version can be a large diff. Flag it
  for human review rather than silently accepting breaking changes.
- A04 (Insecure Design) is a signal to **not** attempt a pure code patch
  without first stating the design gap in the MR description — a code-only
  fix for a design flaw is often incomplete and should lower the confidence
  score reported at sign-off.
