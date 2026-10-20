"""Whether a milestone's latest reading meets its target (member_goal_met)."""

from __future__ import annotations

import pytest

from kiro_crew import member_goal_met


@pytest.mark.parametrize(
    ("text", "target", "readings", "met"),
    [
        ("Tests written", "40", ["12", "40"], True),
        ("Tests written", "40", ["12", "39"], False),
        ("Tests", "0 failing", ["3 failing", "0 failing"], True),
        ("Tests", "0 failing", ["3 failing", "1 failing"], False),
        ("Reduce open bugs", "5", ["9", "4"], True),
        ("Reduce open bugs", "5", ["9", "6"], False),
        ("Docs pages", "5", ["2", "6"], True),
        ("Docs pages", "5", ["4"], False),
        ("Flaky tests", "<= 2", ["4", "2"], True),
        ("Coverage", "> 80%", ["85%"], True),
        ("Coverage", "> 80%", ["80%"], False),
        ("Docs", "all docs in sync", ["all docs in sync since the 4pm pass"], True),
        ("Docs", "all docs in sync", ["two docs still behind"], False),
        ("Merged", "yes", ["done: merged on main"], True),
        ("Steps", "5 of 5", ["done 3 of 5"], False),
        ("Tests written", "40", [], False),
        # A bare verb says what is done, not that fewer is better.
        ("Open 10 pull requests", "10", ["2"], False),
        ("Open 10 pull requests", "10", ["11"], True),
        ("Cut 3 releases", "3", ["1"], False),
        # "," groups thousands before exactly three digits, and is a decimal mark otherwise.
        ("Users", "1,000 users", ["50 users"], False),
        ("Users", "10,000", ["12"], False),
        ("Users", "1,000 users", ["1,200 users"], True),
        ("Rating", "4,5", ["4,6"], True),
        # One plural suffix comes off a unit word, so class and classes agree.
        ("Classes written", "1 class", ["2 classes"], True),
        ("Passes", "3 passes", ["3 pass"], True),
        ("Stories", "2 stories", ["2 story"], True),
        # Reading/target shapes the crewmates wrote during the soak rounds.
        ("Fixes proposed for triaged issues", "3", ["4 fixes proposed"], True),
        ("Fixes proposed for triaged issues", "3", ["2 fixes proposed"], False),
        ("Fixes proposed", "3 fixes", ["4 fixes proposed"], True),
        ("Passing test count", ">= 5", ["5"], True),
        ("Proposed fixes landed with a passing test", "1 or more", ["1 (ISSUE-1 fixed)"], True),
        ("Known bugs found and logged into issues.md", "1 or more", ["0 so far"], False),
        (
            "Issues in issues.md left untriaged (no severity, cause, or fix)",
            "0",
            ["1 (ISSUE-2 is new and not yet triaged; triage dispatched)"],
            False,
        ),
        (
            "Issues in issues.md left untriaged (no severity, cause, or fix)",
            "0",
            ["0 (ISSUE-1 triaged in triage/ISSUE-1.md; it was the only issue)"],
            True,
        ),
        ("README commands match the real CLI (mismatch count)", "0", ["2 mismatches"], False),
        (
            "Triaged issues that have a written proposed fix",
            "100%",
            ["100% (2 of 2 have a written proposed fix)"],
            True,
        ),
        (
            "Changelog top version matches pyproject.toml version",
            "yes",
            ["yes (0.2.0 == 0.2.0 on branch docs/sync-0.2.0, awaiting push/PR)"],
            True,
        ),
        (
            "CI runs the tests on every push",
            "yes",
            ["workflow added locally; not pushed, so not yet run"],
            False,
        ),
        ("Bugs below", "at most 2", ["3"], False),
        ("Open issues triaged this week", "2 or more", ["3 triaged"], True),
        ("Pages written", "at most 4", ["5"], False),
        ("Pages", "3 pages", ["4 failing"], False),
    ],
)
def test_a_milestone_is_met_only_when_its_reading_settles_it(
    text: str, target: str, readings: list[str], met: bool
) -> None:
    kr = {
        "text": text,
        "target": target,
        "current": readings[-1] if readings else "",
        "readings": [{"value": v, "at": float(i)} for i, v in enumerate(readings)],
    }
    assert member_goal_met.key_result_met(kr) is met
