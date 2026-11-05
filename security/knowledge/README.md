# Security Knowledge Base

This directory is the persistent "memory" that the autonomous AppSec remediation
agent (Claude, invoked headlessly or via Aider) consults when it patches a
vulnerability reported in Jira. It exists so the agent's reasoning is grounded
in established OWASP guidance instead of improvising, and so that guidance
doesn't have to be re-sent as raw tokens on every pipeline run.

## How this is organized (and why)

- [`owasp-top10-2021.md`](owasp-top10-2021.md) — the top-level taxonomy. Every
  incoming Jira vulnerability should be mapped to one of these ten categories
  first; that mapping decides which cheat sheet(s) below are relevant.
- [`asvs-overview.md`](asvs-overview.md) — the verification-level mindset
  (L1/L2/L3) and chapter map, used to judge *how much* control is "enough" for
  a given app/ticket rather than gold-plating every fix.
- [`cheatsheets/`](cheatsheets) — one condensed file per vulnerability class,
  distilled from the OWASP Cheat Sheet Series. Each file has the same shape:
  problem, core principles, concrete do/don't, detection heuristics for the
  agent, and known false-positive patterns.
- [`false-positive-patterns.md`](false-positive-patterns.md) — cross-cutting
  patterns that look like a vuln to a scanner/reviewer but usually aren't,
  used by the "defend the patch" step of the iteration loop.

## Token-efficiency rule for the Fixer agent

**Do not load this whole directory into context on every run.** This is a
reference library, not a prompt. The orchestrator (or the agent itself, via
grep/glob) should:

1. Map the Jira ticket's vulnerability description to one OWASP Top 10
   category (keyword match is usually enough — see each cheat sheet's
   "trigger terms").
2. Open only the 1–2 matching files under `cheatsheets/`.
3. Only pull in `false-positive-patterns.md` during the review-defense phase,
   not the initial patch phase.

This mirrors Aider's repo-map approach: compress first, read in full only what
the specific task needs.

## Source of truth

These are summaries in our own words, not reproductions of OWASP's text. When
in doubt, or when a ticket involves a niche variant not covered here, treat
the live pages at [owasp.org/Top10](https://owasp.org/Top10/) and
[cheatsheetseries.owasp.org](https://cheatsheetseries.owasp.org/) as
authoritative, and consider adding a new file here afterward (see
"Keeping this current" below).

## Keeping this current

When a review (CodeRabbit or human) teaches the agent something not captured
here — a project-specific control, a corrected misunderstanding, a new false
positive pattern — add it to the relevant file (or `false-positive-patterns.md`)
rather than letting the agent relearn it every run. This is the "security
ledger" mechanism referenced in the root [`CLAUDE.md`](../../CLAUDE.md).
