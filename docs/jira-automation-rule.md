# Jira Automation Rule — AI Remediation Trigger

Your real Jira site (`vixai.atlassian.net`) has a dedicated project for
this: **`VD` ("Vulnerability Dump")**, which has its own **Security Bug**
issue type — use that instead of plain `Bug`.

This is a **standing rule that fires automatically on your real Jira
project** — created by you in the UI (Project settings → Automation →
Create rule), not programmatically, since a persistent automation rule is
exactly the kind of standing configuration that should only be created
with explicit say-so, in Jira's own UI where you can see and adjust it
directly. (Already done as of this writing — "AI Security Fix Trigger",
live on the `VD` project.)

## Labeling convention

Tag any ticket you want the pipeline to pick up with the label
**`sec-ai-fix`**. Nothing fires without it, so unrelated `VD` tickets are
never touched by accident.

## Architecture: centralized in V1X, not copied into every target repo

The rule calls **`V1X`'s** `dispatches` endpoint, not the target repo's.
`.github/workflows/ai-fix.yml` lives in `V1X` (the "brain": orchestrator +
`CLAUDE.md` + `security/knowledge`) and checks out the *target* repo named
in the ticket's payload as a second path, patches it there, and opens the
PR there. `V1X` itself is never written to. This means adding a new target
repo later needs zero new workflow files — just a different `repo` value
in the webhook body (see below). The tradeoff: the CodeRabbit review-reply
loop (Phase 3, not built yet) will need something listening on the target
repo itself, since PR comment events are repo-scoped and `V1X`'s Actions
can't see them — deferred on purpose for now.

## Rule definition (as actually configured)

**Trigger**: Work item created (Jira's newer UI calls issues "work items").

**Condition** (JQL):
```
project = VD AND issuetype = "Security Bug" AND labels = "sec-ai-fix"
```

**Action**: *Send web request*
- URL: `https://api.github.com/repos/Andrelleite/V1X/dispatches`
- Method: `POST`
- Headers:
  - `Authorization: Bearer <GITHUB_PAT>` (classic PAT, `repo` scope —
    needed because this one token both reads `V1X` during checkout *and*
    pushes/opens a PR on whatever target repo is named below)
  - `Accept: application/vnd.github+json`
  - `Content-Type: application/json`
- Body (custom data):
  ```json
  {
    "event_type": "trigger_ai_fix",
    "client_payload": {
      "issue_key": "{{issue.key}}",
      "summary": "{{issue.summary}}",
      "description": "{{issue.description}}",
      "repo": "Andrelleite/juice-shop"
    }
  }
  ```
  The `repo` field is hardcoded in the rule's static body for now (one
  rule = one target repo). If you want tickets to target different repos,
  either make one rule per target repo, or add a custom Jira field/label
  for the target repo and reference it here instead of a literal string.

This matches `.github/workflows/ai-fix.yml`'s `repository_dispatch`
trigger and the `VulnTicket.from_jira_payload` shape in
`orchestrator/models.py`.

## Secret this needs in V1X (not the target repo)

`TARGET_REPO_TOKEN` — the same classic PAT used in the rule's
`Authorization` header above, added as a GitHub Actions secret on `V1X`
(`https://github.com/Andrelleite/V1X/settings/secrets/actions`). This is
what lets the workflow check out *and* push to the target repo (`juice-shop`
today). `GEMINI_API_KEY` and `CLAUDE_CODE_OAUTH_CREDS` also live on `V1X`,
same as before — nothing needs adding to the target repo at all.

## Second rule — status sync (optional, add once the first rule works)

**Trigger**: Issue transitioned, or a webhook from GitHub (needs a receiving
endpoint — simplest is a second GitHub Actions step calling Jira's REST API
`POST /rest/api/3/issue/{issueIdOrKey}/transitions` when the PR opens/merges,
rather than a second inbound Jira rule).

## Before wiring it to the real endpoint

1. Create the rule with the web request pointed at a scratch endpoint
   (e.g. https://webhook.site) first, label a throwaway `VD` ticket, and
   confirm the JSON body actually looks like the example above.
2. Only then swap the URL to the real GitHub `dispatches` endpoint.
3. Keep the PAT out of the rule's visible config where possible — Jira
   Automation's "Send web request" action doesn't support secret storage
   the way GitHub Actions secrets do, so scope the PAT as narrowly as
   possible and rotate it if this rule is ever duplicated/exported.
