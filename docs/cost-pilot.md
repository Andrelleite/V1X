# Cost pilot: is this worth it?

A small, honest way to answer that: run N real Jira tickets through the
live pipeline exactly as normal, capture what each one actually cost from
the job logs, and turn that into a report comparing it against a human
AppSec engineer doing the same triage by hand. Five tickets is enough to
see the shape of the number without pretending it's a statistically
rigorous sample.

## 1. Run the tickets as usual

File each test ticket the normal way (Jira issue, `sec-ai-fix` label) and
let the pipeline run. Nothing about the pipeline changes for this —
`orchestrator/cost.py` already extracts a `cost_usd` figure from every
backend call, and two places now print it in the job log:

- `fix` prints one line per ticket:
  `[fix] wrote MR description to ... (... cost_usd: 0.4123)`
- `review-loop` / `review-watch` print one line per CodeRabbit thread they
  handle: `[review-loop] MR !14 thread cost_usd: 0.0871 (reported directly
  by Claude Code)`

A ticket's total cost = its `fix` line's figure + every thread-cost line
that mentions the MR that ticket's `fix` run opened. `None` means the
backend's JSON output didn't carry a cost figure that run (see the
`cost_note` next to it for why) — treat it as "not metered", not as zero.

## 2. Write down the five totals

Build one JSON file, one entry per ticket:

```json
[
  {"issue_key": "VD-30", "fix_cost_usd": 0.41, "review_cost_usd": 0.18},
  {"issue_key": "VD-31", "fix_cost_usd": 0.22, "review_cost_usd": 0.00},
  {"issue_key": "VD-32", "fix_cost_usd": 0.37, "review_cost_usd": 0.29},
  {"issue_key": "VD-33", "fix_cost_usd": 0.19, "review_cost_usd": 0.05},
  {"issue_key": "VD-34", "fix_cost_usd": 0.28, "review_cost_usd": 0.11}
]
```

`review_cost_usd` is the sum of that ticket's thread-cost lines across
however many review-loop/review-watch rounds it took; omit it (defaults
to 0) for a ticket CodeRabbit approved with no findings.

## 3. Generate the report

```bash
python -m orchestrator.cli cost-report --entries cost_pilot_entries.json --out cost_pilot_report.txt
```

This prints, and optionally writes, the per-ticket breakdown, total
actual spend, average cost per ticket, and a comparison against a manual
baseline (`--baseline-hourly-usd`, default $75/h; `--baseline-hours-per-
ticket`, default 1.5h — override either if your org's own numbers differ).
The baseline is deliberately a labeled assumption, not a market survey:
the point is the order of magnitude, not a precise number.

## What this does and doesn't tell you

- It's real spend on real tickets, not a benchmark suite — five tickets
  from one target repo, one Jira project. Treat the dollar figure as "what
  this cohort cost," not a guaranteed per-ticket price.
- It only meters backend $ cost (Gemini/Claude). It does not meter the
  human time spent reviewing and merging the resulting MRs, which is real
  but outside what `cost.py` can see.
- A Gemini run's cost is an *estimate* from token counts at a published
  per-1M rate (see `cost.py`'s `GEMINI_PRICE_*` env vars) — Claude's figure
  is reported directly by the CLI and is the more trustworthy of the two.
