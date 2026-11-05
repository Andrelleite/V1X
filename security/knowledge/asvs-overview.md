# OWASP ASVS — Verification-Level Mindset

Full standard: [OWASP/ASVS on GitHub](https://github.com/OWASP/ASVS). Don't
treat this file as a verbatim copy of the standard — it's the operating
mindset the remediation agent should apply, condensed.

## Why this matters for an automated fixer

ASVS exists to answer "how much security control is *enough*?" — which
matters because an autonomous agent's default failure mode is either
under-fixing (patches the literal line, ignores the class of bug) or
over-fixing (adds enterprise-grade controls to a low-risk internal tool,
inflating the diff and the blast radius). ASVS gives a calibration knob.

## The three levels

- **L1 (Opportunistic)** — defends against attacks that are easy to execute
  with widely-available tools. This is the *floor*: every fix should at least
  satisfy the relevant L1 requirement, with no exceptions.
- **L2 (Standard)** — defends against most real-world risk for apps handling
  meaningful business or personal data. Default target for most tickets
  unless the repo/app is explicitly marked low-risk.
- **L3 (Advanced)** — for high-value targets (payments, health data,
  critical infra). Only apply L3-grade fixes if the repo's own
  `SECURITY.md`/`CLAUDE.md` says the app is in this tier, or the Jira ticket
  says so explicitly — otherwise this is scope creep.

Levels are cumulative: L3 implies L2 implies L1. **When unsure which level
applies, default to L2** and say so in the MR's confidence/blast-radius
summary so a human can downgrade or upgrade it.

## Chapter groups worth knowing (maps loosely to Top 10 + cheat sheets)

| Area | What ASVS checks | Cheat sheet |
|---|---|---|
| Architecture & design | Threat modeling, trust boundaries documented | — (flag for design review) |
| Authentication | Credential handling, lockout, MFA, recovery flows | [authentication.md](cheatsheets/authentication.md) |
| Session management | Token generation, expiry, invalidation on logout/privilege change | [session-management.md](cheatsheets/session-management.md) |
| Access control | Authorization enforced server-side, per-request, deny-by-default | [access-control.md](cheatsheets/access-control.md) |
| Validation, sanitization, encoding | Input validated server-side; output encoded for its sink (HTML/SQL/shell/etc.) | [input-validation.md](cheatsheets/input-validation.md), [injection.md](cheatsheets/injection.md), [xss.md](cheatsheets/xss.md) |
| Cryptography | Approved algorithms, key management, no home-grown crypto | [cryptography.md](cheatsheets/cryptography.md) |
| Error handling & logging | No sensitive data in errors/logs, security events logged | see A09 note in [owasp-top10-2021.md](owasp-top10-2021.md) |
| Data protection | Sensitive data classified and protected at rest/in transit/in use | [cryptography.md](cheatsheets/cryptography.md), [secrets-management.md](cheatsheets/secrets-management.md) |
| Communications | TLS configuration, certificate validation | [cryptography.md](cheatsheets/cryptography.md) |
| Malicious/integrity | Code and data integrity verified, safe deserialization | [deserialization.md](cheatsheets/deserialization.md) |
| Business logic | Workflow can't be skipped, replayed, or raced | flag for design review (A04) |
| Files & resources | Safe upload handling, path traversal prevention, SSRF on fetch | [file-upload.md](cheatsheets/file-upload.md), [ssrf.md](cheatsheets/ssrf.md) |
| API & web service | Same controls apply to REST/GraphQL/gRPC endpoints, not just HTML forms | [api-security.md](cheatsheets/api-security.md) |
| Configuration | Hardened defaults, no debug features in production, CORS locked down | [api-security.md](cheatsheets/api-security.md) |

## How the agent should use this

When writing a patch, state internally (and in the `<fix_summary>`): "this
fix targets ASVS level L_", and justify L2-by-default unless the repo says
otherwise. This becomes part of the confidence score at final sign-off: a fix
that only reaches L1 against an app that clearly needs L2 should report a
lower confidence / higher residual-risk rating, not silently pass as "done."
