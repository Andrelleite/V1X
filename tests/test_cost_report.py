from orchestrator.cost_report import build_report, render_report


def test_build_report_totals_fix_and_review_cost_per_ticket():
    report = build_report([
        ("VD-30", 0.40, 0.10),
        ("VD-31", 0.20, 0.00),
    ])
    assert report.tickets[0].total_usd == 0.50
    assert report.tickets[1].total_usd == 0.20
    assert report.total_usd == 0.70
    assert report.average_usd == 0.35


def test_build_report_empty_entries_has_zero_average_not_a_crash():
    report = build_report([])
    assert report.total_usd == 0.0
    assert report.average_usd == 0.0
    assert report.baseline_total_usd == 0.0
    assert report.savings_percent == 0.0


def test_baseline_and_savings_use_the_given_rate_and_hours():
    report = build_report(
        [("VD-30", 1.0, 0.0), ("VD-31", 1.0, 0.0)],
        baseline_hourly_usd=100.0,
        baseline_hours_per_ticket=2.0,
    )
    assert report.baseline_total_usd == 400.0  # 2 tickets x 2h x $100
    assert report.savings_usd == 398.0
    assert report.savings_percent == 99.5


def test_render_report_includes_every_ticket_and_the_totals():
    report = build_report([("VD-30", 0.40, 0.10)], baseline_hourly_usd=75.0, baseline_hours_per_ticket=1.5)
    text = render_report(report)
    assert "VD-30" in text
    assert "Total actual spend" in text
    assert "Manual baseline" in text
    assert "Estimated savings" in text
