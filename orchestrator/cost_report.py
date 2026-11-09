"""Turns the per-run USD figures already surfaced by cost.py (one line per
fix run, one per CodeRabbit review thread -- see cli.py) into the short
report this project's "is this worth it" pilot needs: run a handful of
real tickets through the live pipeline, meter what each one actually
cost end-to-end (initial fix + every review round), and compare that
against a human AppSec engineer doing the same triage by hand.

Deliberately takes already-extracted numbers rather than re-parsing CI
job logs itself -- job log text is free-form and not worth a fragile
regex over when the figures that matter are already printed once, in a
fixed format, per run (cli.py's "cost_usd: ..." lines) and easy to copy
into a small JSON file by hand for a five-ticket pilot. See
docs/cost-pilot.md for the input file format and how to run the pilot.
"""
from __future__ import annotations

from dataclasses import dataclass

# A rough, clearly-labeled baseline, not a market survey -- it only needs
# to be defensible enough to show the order of magnitude of the savings
# (or lack of them), and it's fully visible/overridable via CLI flags
# rather than hidden inside the math.
DEFAULT_BASELINE_HOURLY_USD = 75.0
DEFAULT_BASELINE_HOURS_PER_TICKET = 1.5


@dataclass(frozen=True)
class TicketCost:
    issue_key: str
    fix_cost_usd: float
    # Sum of every review-loop/review-watch thread's cost for this ticket
    # -- zero is a legitimate value (CodeRabbit approved with no findings).
    review_cost_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return self.fix_cost_usd + self.review_cost_usd


@dataclass(frozen=True)
class CostReport:
    tickets: tuple[TicketCost, ...]
    baseline_hourly_usd: float
    baseline_hours_per_ticket: float

    @property
    def total_usd(self) -> float:
        return sum(t.total_usd for t in self.tickets)

    @property
    def average_usd(self) -> float:
        return self.total_usd / len(self.tickets) if self.tickets else 0.0

    @property
    def baseline_total_usd(self) -> float:
        return self.baseline_hourly_usd * self.baseline_hours_per_ticket * len(self.tickets)

    @property
    def savings_usd(self) -> float:
        return self.baseline_total_usd - self.total_usd

    @property
    def savings_percent(self) -> float:
        if not self.baseline_total_usd:
            return 0.0
        return 100.0 * self.savings_usd / self.baseline_total_usd


def build_report(
    entries: list[tuple[str, float, float]],
    baseline_hourly_usd: float = DEFAULT_BASELINE_HOURLY_USD,
    baseline_hours_per_ticket: float = DEFAULT_BASELINE_HOURS_PER_TICKET,
) -> CostReport:
    """`entries` is (issue_key, fix_cost_usd, review_cost_usd) triples --
    see cmd_cost_report in cli.py for the JSON file shape this is built
    from."""
    tickets = tuple(
        TicketCost(issue_key=key, fix_cost_usd=fix, review_cost_usd=review)
        for key, fix, review in entries
    )
    return CostReport(
        tickets=tickets,
        baseline_hourly_usd=baseline_hourly_usd,
        baseline_hours_per_ticket=baseline_hours_per_ticket,
    )


def render_report(report: CostReport) -> str:
    lines = [
        "=== AI AppSec Pipeline — Cost Pilot Report ===",
        f"Tickets run: {len(report.tickets)}",
        "",
    ]
    for t in report.tickets:
        lines.append(
            f"  {t.issue_key}: fix ${t.fix_cost_usd:.4f} + review ${t.review_cost_usd:.4f} "
            f"= ${t.total_usd:.4f}"
        )
    lines += [
        "",
        f"Total actual spend:   ${report.total_usd:.4f}",
        f"Average per ticket:   ${report.average_usd:.4f}",
        f"Manual baseline:      ${report.baseline_total_usd:.2f} "
        f"({len(report.tickets)} ticket(s) x {report.baseline_hours_per_ticket:g}h "
        f"x ${report.baseline_hourly_usd:g}/h)",
        f"Estimated savings:    ${report.savings_usd:.2f} ({report.savings_percent:.1f}%)",
    ]
    return "\n".join(lines)
