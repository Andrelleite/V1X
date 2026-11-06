# Setting up the review-loop schedule

The `review_loop` job in `.gitlab-ci.yml` closes the loop with CodeRabbit:
it polls every open pipeline-created MR for unresolved CodeRabbit
discussion threads and has the Fixer either patch the code or post a
false-positive defense for each one.

It only runs on a GitLab CI/CD Pipeline Schedule (`$CI_PIPELINE_SOURCE ==
"schedule"`) — never on the Jira-triggered pipeline source the `ai_fix`
job uses. This is polling, not a live webhook, on purpose: GitLab CI has
no native "run a job when someone comments on an MR" trigger, and a
real-time webhook receiver would need its own always-on host outside
this pipeline's all-GitLab-CI architecture. The tradeoff is latency —
CodeRabbit's comment sits unanswered for up to one polling interval — not
correctness; a thread we've already replied to and resolved drops out of
"unresolved" on the next poll on its own, so nothing is double-handled.

This part has to be done once, by hand, in the GitLab UI — it isn't
something this repo's files can configure:

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
