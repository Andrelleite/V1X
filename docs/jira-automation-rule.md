# Jira Automation Rule — AI Remediation Trigger

Your real Jira site (`vixai.atlassian.net`) currently has one project:
**`SEC` ("Security")**, with issue types `Epic, Subtask, Task, Story,
Feature, Bug` — there's no dedicated "security-bug" issue type, so the
trigger uses `issuetype = Bug` plus a label, per the convention below.

This is a **standing rule that fires automatically on your real Jira
project** — create it yourself in the UI (Project settings → Automation →
Create rule); I'm not creating it programmatically even though the
connected Jira MCP could technically call the API, since a persistent
automation rule is exactly the kind of standing configuration that should
only be created with your explicit say-so, in Jira's own UI where you can
see and adjust it directly.

## Labeling convention

Tag any ticket you want the pipeline to pick up with the label
**`sec-ai-fix`**. Nothing fires without it, so existing/unrelated `SEC`
tickets are never touched by accident.

## Rule definition

**Trigger**: Issue created OR Issue updated (combine with an "or" in the
rule, or make two rules sharing the same condition+action).

**Condition** (JQL-equivalent, or built with the condition blocks):
```
project = SEC AND issuetype = Bug AND labels = "sec-ai-fix"
```

**Action**: *Send web request*
- URL: `https://api.github.com/repos/<your-org>/<your-repo>/dispatches`
- Method: `POST`
- Headers:
  - `Authorization: Bearer <GITHUB_PAT>` (fine-grained PAT, `contents:write`
    + `pull-requests:write` scoped to this one repo)
  - `Accept: application/vnd.github+json`
  - `Content-Type: application/json`
- Body (custom data):
  ```json
  {
    "event_type": "trigger_ai_fix",
    "client_payload": {
      "issue_key": "{{issue.key}}",
      "summary": "{{issue.summary}}",
      "description": "{{issue.description}}"
    }
  }
  ```

This matches `.github/workflows/ai-fix.yml`'s `repository_dispatch` trigger
and the `VulnTicket.from_jira_payload` shape in `orchestrator/models.py`.

## Second rule — status sync (optional, add once the first rule works)

**Trigger**: Issue transitioned, or a webhook from GitHub (needs a receiving
endpoint — simplest is a second GitHub Actions step calling Jira's REST API
`POST /rest/api/3/issue/{issueIdOrKey}/transitions` when the PR opens/merges,
rather than a second inbound Jira rule).

## Before wiring it to the real endpoint

1. Create the rule with the web request pointed at a scratch endpoint
   (e.g. https://webhook.site) first, label a throwaway `SEC` ticket, and
   confirm the JSON body actually looks like the example above.
2. Only then swap the URL to the real GitHub `dispatches` endpoint.
3. Keep the PAT out of the rule's visible config where possible — Jira
   Automation's "Send web request" action doesn't support secret storage
   the way GitHub Actions secrets do, so scope the PAT as narrowly as
   possible (single repo, minimum permissions) and rotate it if this rule
   is ever duplicated/exported.
