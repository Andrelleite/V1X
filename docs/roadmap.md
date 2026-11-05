# Roadmap

Phase 1 is done (this repo's `security/knowledge/` + root `CLAUDE.md`). The
phases below are **not implemented yet** — this is a plan, not a status
report.

## Phase 2 — Event-driven trigger + Fixer agent

- Jira webhook, filtered by JQL so it only fires on
  `issuetype = "security-bug" AND labels = "sec-ai-fix"` (or similar) —
  avoid firing on every ticket edit.
- A lightweight receiver (FastAPI, or a CI provider's native trigger —
  GitHub `repository_dispatch` / GitLab pipeline trigger token) that starts
  the pipeline asynchronously (Jira webhooks will time out on a synchronous
  multi-minute agent run).
- Pipeline: clone repo → branch `fix/ai-<JIRA-KEY>` → run the Fixer agent
  headless, using this repo's `CLAUDE.md` → commit → push → open an MR
  referencing the Jira ticket ID. The Fixer tries **Gemini CLI first**
  (cost reasons) and **falls back to Claude Code** if Gemini isn't
  configured or its run fails — see `orchestrator/runners.py`.

## Phase 3 — CodeRabbit iteration loop

- CodeRabbit reviews the MR (its native Jira integration pulls ticket
  context automatically if linked).
- A second webhook (PR/MR comment events) routes CodeRabbit's comments back
  to the same agent workspace, following the decision tree in this repo's
  `CLAUDE.md` (fix vs. false-positive defense).
- Loop until CodeRabbit approves or all threads resolve.

## Phase 4 — Blast-radius / final sign-off

- On approval, pack the full repo + final diff and send to a large-context
  model (e.g. Gemini) for a whole-repo breakage analysis — this is the one
  step that benefits from a model with a much larger context window than
  the per-file Fixer loop needs.
- Post the structured final comment (fix summary, confidence score, blast
  radius) to the MR; this is what the human reviewer actually reads before
  merging.

## Phase 5 — Feedback loops (make it get better over time)

- **Project-specific ledger**: append dated lessons to this repo's
  `CLAUDE.md` → "Project-specific ledger" whenever a review cycle catches
  something the general cheat sheets didn't.
- **CodeRabbit native learning**: humans resolving a CodeRabbit false
  positive with `@coderabbitai resolve` trains CodeRabbit's own model for
  this repo — keep doing this even after the agent exists.
- **Vector store of past fixes (optional, later)**: embed merged
  ticket+patch pairs so a new ticket can retrieve "how we fixed something
  like this before" — only worth building once there's enough history to
  retrieve against.

## Explicit non-goals for now

- No autonomous merge. A human always clicks merge.
- No credential rotation automation — the agent flags leaked secrets, a
  human rotates them (see `security/knowledge/cheatsheets/secrets-management.md`).
- No A04 (Insecure Design) auto-fix — design gaps get flagged for human
  review, not patched silently.
