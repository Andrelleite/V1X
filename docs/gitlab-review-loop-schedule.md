# Setting up the review-loop schedule (optional)

The `review_loop` job in `.gitlab-ci.yml` closes the loop with CodeRabbit:
it polls every open pipeline-created MR for unresolved CodeRabbit
discussion threads and has the Fixer either patch the code or post a
false-positive defense for each one.

**By default it needs no setup at all.** It runs on `$CI_PIPELINE_SOURCE
== "trigger"` — the same Jira-fired pipeline the `ai_fix` job already
uses — so every time a Jira ticket fires the pipeline, `review_loop` also
sweeps every currently-open pipeline-created MR for unresolved CodeRabbit
threads, alongside `ai_fix` handling the new ticket. No Pipeline Schedule,
no extra permissions, nothing to configure in the GitLab UI. The
tradeoff: an MR only gets re-swept when the *next* ticket happens to fire
a pipeline, not on a fixed cadence — if tickets stop coming in for a
while, an open MR's unanswered CodeRabbit comment just waits.

For true periodic coverage independent of ticket activity, the job also
runs on a GitLab CI/CD Pipeline Schedule (`$CI_PIPELINE_SOURCE ==
"schedule"`) if one exists — this is optional, and needs a
project-admin-level permission that isn't guaranteed even with a group
Owner role, which is why it isn't the default path. If you later get
that permission (or just want tighter latency), set one up once, by hand,
in the GitLab UI:

1. On `gitlab.com/mumbo-jumbo/juice-shop-revamped` → **Build → Pipeline
   schedules → New schedule**.
2. **Description**: something like `CodeRabbit review-loop poll`.
3. **Interval pattern**: a cron expression — e.g. `*/15 * * * *` for
   every 15 minutes. Pick a cadence that balances responsiveness against
   CI minutes (every run does a fresh `npm install -g` of both CLIs, so
   tighter than ~10 minutes starts adding up).
4. **Target branch**: the repo's default branch (the schedule just needs
   somewhere to read `.gitlab-ci.yml` from — the job itself clones
   `TARGET_REPO` independently, same as `ai_fix` does).
5. **Variables**: add `TARGET_REPO` = `mumbo-jumbo/juice-shop-revamped`.
   Scheduled runs have no Jira ticket to read it from, unlike the
   trigger-fired `ai_fix` job, so it has to be set here explicitly.
6. Save, and **make sure it's not just created but active** — GitLab
   schedules can be toggled off.

To test it without waiting for the interval, open the schedule and use
**Run pipeline schedule now** — this fires a real `schedule`-sourced
pipeline immediately, same as the cron would.
