# Jira Automation Rule — AI Remediation Trigger (GitLab)

GitLab is now the real target platform for this pipeline — this document
replaces `docs/jira-automation-rule.md` (the GitHub version, kept for
reference/fallback; both `.github/workflows/ai-fix.yml` and
`.gitlab-ci.yml` exist in this repo and don't conflict with each other).

Projects:
- **Brain** (orchestrator + `CLAUDE.md` + `security/knowledge`):
  `https://gitlab.com/mumbo-jumbo/v1x`
- **Target** (the app actually being patched):
  `https://gitlab.com/mumbo-jumbo/juice-shop-revamped`

Same architecture as the GitHub version: the pipeline lives only in the
**brain** project (`v1x`) and clones/patches/pushes to whatever target repo
the Jira ticket names — nothing needs adding to the target project itself.

## 1. Create a Pipeline Trigger Token on `v1x`

1. Go to `https://gitlab.com/mumbo-jumbo/v1x/-/settings/ci_cd`
2. Expand **Pipeline trigger tokens** → **Add new token**
3. Description: `jira-sec-ai-fix-trigger` → **Create pipeline trigger token**
4. Copy the token value shown

## 2. Add CI/CD Variables to `v1x`

Same page, **Variables** section → **Add variable** for each:

| Key | Value | Masked? |
|---|---|---|
| `TARGET_REPO_TOKEN` | A GitLab Personal Access Token (`api` + `write_repository` scopes) — can reuse the one you created earlier for the manual clone/push, or make a dedicated one | Yes |
| `JIRA_EMAIL` | `black4linka@gmail.com` | Yes |
| `JIRA_API_TOKEN` | The Atlassian API token from `id.atlassian.com/manage-profile/security/api-tokens` (reuse the one from the GitHub setup if you still have it) | Yes |
| `GEMINI_API_KEY` | Your Gemini API key | Yes |
| `CLAUDE_CODE_OAUTH_CREDS` | Your Claude Code subscription session JSON (optional fallback — see `docs/claude-subscription-fallback.md`) | Yes |

Leave **Protect variable** unchecked for now (that restricts a variable to
protected branches/tags only — fine to tighten later once this is stable).

## 3. Configure the Jira Automation rule

Edit the same "AI Security Fix Trigger" rule (or make a new one) —
**Send web request** action:

- **URL**:
  ```
  https://gitlab.com/api/v4/projects/mumbo-jumbo%2Fv1x/trigger/pipeline
  ```
  (`%2F` is the URL-encoded `/` between namespace and project name — GitLab's
  API accepts either the numeric project ID or this encoded path form.)
- **Method**: `POST`
- **Headers**:
  - `Content-Type` → `application/x-www-form-urlencoded`
  (No `Authorization` header this time — GitLab's trigger token goes in the
  body, not a header.)
- **Web request body** → **Custom data**, body type **form-urlencoded**
  text:
  ```
  token=<paste the Pipeline Trigger Token from step 1>&ref=main&variables[ISSUE_KEY]={{issue.key}}&variables[TARGET_REPO]=mumbo-jumbo%2Fjuice-shop-revamped
  ```
  Unlike the GitHub/JSON version, this never had an escaping problem to
  work around in the first place — form encoding handles `{{issue.key}}`
  (e.g. `VD-5`) without any special function needed, because an issue key
  never contains characters that need escaping either way.

Save, confirm the rule is **On**. The rule's **Condition** (JQL) is
unchanged from `docs/jira-automation-rule.md` — only this action's
URL/headers/body changed when moving from GitHub to GitLab — including
the `labels NOT IN ("sec-ai-fix-done")` clause that keeps a successful
run from re-firing on every later edit to the same ticket (see that doc
for why).

## Testing

Same pattern as before: label a `VD` ticket with `sec-ai-fix`, then check:
- Jira's audit log for the "Send web request" step's response (GitLab
  returns `201 Created` with pipeline details on success, not `204`)
- `https://gitlab.com/mumbo-jumbo/v1x/-/pipelines` for a new pipeline run
