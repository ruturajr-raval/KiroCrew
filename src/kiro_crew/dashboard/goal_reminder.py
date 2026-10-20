"""A crewmate's check-ins: Daily Goal Reminder, Weekly report, Monthly review.

The Goals tab's three switches (``PUT /api/members/{slug}/goals/schedules``) are
stored in the goal record (:mod:`kiro_crew.member_goals`), and each switch keeps
exactly ONE gateway-owned schedule in step with it, through the cron store's
installer key (``managed_by``, ``goal-<cadence>:<slug>``), so no switch can ever
have two schedules and none touches another's:

* on -> that cadence's old schedule (if any) is removed and a fresh one created
  at the shared time of day: daily ``M H * * *``, weekly ``M H * * <weekday>``,
  monthly ``M H <day> * *``, in the user's timezone;
* off -> that cadence's schedule is removed.

When a schedule fires, the gateway's cron callback hands the job here
(:func:`fire`) instead of running it as an ordinary cron turn: the prompt is
built from the CURRENT goal record and dispatched as one gateway-authored turn
in the crewmate's pinned thread (:func:`mate_welcome.dispatch_hidden_turn`), so
the user sees only the crewmate's reply. That turn is not one the user sent, so
``update_self`` and most cards refuse inside it; the goal tools (readings,
``save_goal_report``) are admitted there on purpose
(``handlers.member_goals``), and so are the crewmate's own goal, milestones and
check-ins cards (``set_goal``, ``set_key_results``, ``set_check_ins``), which
any turn in its own thread may raise (``handlers.guide.REQ_OWN_GOAL_TURN``).
Nothing changes until the user presses the card.

The weekly and monthly prompts carry the tasks the crewmate finished in the
period, read from its work ledger (the same items the Crew board shows,
:func:`finished_tasks`). The weekly and monthly turns end with ``save_goal_report``: the gateway saves the
report as an artifact under ``Crewmates/<name>/Reports`` (:func:`save_report`),
remembers it on the goal record, and sends one notification linking it; the
crewmate's reply in the thread is one short line, never the report itself.

A check-in that fires with the thread closed, a turn already running, its switch
off or no goal left does nothing that time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from kiro_crew import member_goals
from kiro_crew import members as members_mod

logger = logging.getLogger(__name__)

#: Installer key prefix per cadence; the rest is the member slug.
MANAGED_PREFIXES = {c: f"goal-{c}:" for c in member_goals.CADENCES}

#: Who the cron store records as removing a check-in schedule.
_ACTOR = "dashboard"
_SOURCE = "goal_checkins"

#: Where reports are filed, under the crewmate's display name.
REPORTS_FOLDER = "Crewmates/{name}/Reports"

#: How far back the weekly report and the monthly review look at readings.
_WINDOW_SECS = {
    member_goals.CADENCE_WEEKLY: 7 * 24 * 3600,
    member_goals.CADENCE_MONTHLY: 31 * 24 * 3600,
}


def managed_key(slug: str, cadence: str = member_goals.CADENCE_DAILY) -> str:
    return MANAGED_PREFIXES[cadence] + members_mod.validate_slug(slug)


def cadence_of(job: Any) -> str | None:
    key = getattr(job, "managed_by", "")
    if not isinstance(key, str):
        return None
    for cadence, prefix in MANAGED_PREFIXES.items():
        if key.startswith(prefix):
            return cadence
    return None


def is_reminder_job(job: Any) -> bool:
    """Whether *job* is one of a crewmate's goal check-ins (daily, weekly, monthly).

    The one predicate every list that leaves them out reads: the Goals tab's
    switches are their only control, so ``GET /api/crons`` (the Schedule page and
    a crewmate's Schedules tab, which filters that same list) omits them while
    the cron store keeps running them.
    """
    return cadence_of(job) is not None


def cron_expr_for(cadence: str, schedules: dict[str, Any]) -> str:
    """The cron expression for *cadence* at the record's shared time."""
    hour, minute = (int(x) for x in str(schedules["time"]).split(":"))
    if cadence == member_goals.CADENCE_WEEKLY:
        return f"{minute} {hour} * * {int(schedules['weekday'])}"
    if cadence == member_goals.CADENCE_MONTHLY:
        return f"{minute} {hour} {int(schedules['month_day'])} * *"
    return f"{minute} {hour} * * *"


async def reminder_jobs(crons: Any, slug: str, cadence: str | None = None) -> list[Any]:
    keys = (
        {managed_key(slug, cadence)}
        if cadence
        else {managed_key(slug, c) for c in member_goals.CADENCES}
    )
    return [j for j in await crons.list_jobs_async(include_disabled=True) if j.managed_by in keys]


_NAMES = {
    member_goals.CADENCE_DAILY: "Daily goal reminder",
    member_goals.CADENCE_WEEKLY: "Weekly report",
    member_goals.CADENCE_MONTHLY: "Monthly review",
}


async def sync_schedule(crons: Any, slug: str, label: str, schedules: dict[str, Any]) -> None:
    """Make the store hold exactly the schedules *schedules* asks for, one per switch.

    A cadence whose job already matches (one job, enabled, same cron expression,
    timezone and name) is left as it is, run history included: saving one
    switch must not wipe the history of the others. A cadence that changed has
    its old schedule removed first, then a fresh one added with a new id when
    its switch is on: the cron store's installer contract replaces a managed
    job that way (no replace-in-place), so a run in flight only removes a dead
    one.
    """
    from kiro_crew.cron_service.schedule import get_local_tz

    tz = schedules.get("timezone") or get_local_tz()[0]
    for cadence in member_goals.CADENCES:
        jobs = await reminder_jobs(crons, slug, cadence)
        wanted = bool(schedules.get(cadence))
        expr = cron_expr_for(cadence, schedules) if wanted else None
        name = f"{_NAMES[cadence]}: {label}"[:200]
        if (
            wanted
            and len(jobs) == 1
            and jobs[0].enabled
            and jobs[0].schedule.kind == "cron"
            and jobs[0].schedule.cron_expr == expr
            and jobs[0].timezone == tz
            and jobs[0].name == name
        ):
            continue
        for job in jobs:
            await crons.remove_job_async(job.id, actor=_ACTOR, source=_SOURCE)
        if not wanted:
            continue
        await crons.add_managed_job_async(
            managed_key(slug, cadence),
            name=name,
            message=f"{_NAMES[cadence]} for {label}. It runs in the crewmate's own chat.",
            cron_expr=cron_expr_for(cadence, schedules),
            timezone=tz,
            silent=True,
            hide_in_chat=True,
            persistent_session=False,
            minimal_context=True,
        )


_PREAMBLE = (
    "Kiro Crew sends this; the user did not type it and sees only your reply, so "
    "keep this note itself out of what you write. Write in the language of the "
    "dashboard's [UI LANGUAGE] when it is shown, else English.\n\n"
)


def _movement_lines(rec: dict[str, Any], cadence: str) -> str:
    since = time.time() - _WINDOW_SECS[cadence]
    lines = []
    for m in member_goals.key_result_movement(rec, since=since):
        start = m["start"] if m["start"] is not None else "not read"
        now = m["now"] if m["now"] is not None else "not read"
        lines.append(
            f"- {m['text']}: {start} -> {now} (target {m['target']}, "
            f"{m['readings_in_window']} readings in this period)"
        )
    return "\n".join(lines) or "(no key results yet)"


#: How many finished tasks a report prompt lists, and how much of each summary.
_MAX_FINISHED_TASKS = 30
_TASK_SUMMARY_MAX_CHARS = 300


def finished_tasks(slot_key: str, cadence: str) -> list[dict[str, str]]:
    """The work-ledger tasks the thread *slot_key* closed in *cadence*'s window.

    Read through the Crew board's own reader
    (:func:`~kiro_crew.dashboard.handlers.work_ledger_board.closed_items`, the
    slot's ledger key), newest last, each ``{title, state, summary}`` and
    scrubbed like every string the crewmate wrote. A thread that owns no ledger
    has finished nothing here. Blocking file IO.
    """
    from kiro_crew.dashboard.handlers import work_ledger_board

    since = datetime.now(timezone.utc) - timedelta(seconds=_WINDOW_SECS[cadence])
    done: list[tuple[datetime, dict[str, str]]] = []
    for row in work_ledger_board.closed_items(slot_key):
        closed = row["closed_at"]
        if closed <= since:
            continue
        done.append(
            (
                closed,
                {
                    "title": member_goals.scrub_text(row["title"]),
                    "state": row["state"],
                    "summary": member_goals.scrub_text(row["summary"])[:_TASK_SUMMARY_MAX_CHARS],
                },
            )
        )
    done.sort(key=lambda pair: pair[0])
    return [task for _closed, task in done][-_MAX_FINISHED_TASKS:]


def _finished_lines(tasks: list[dict[str, str]]) -> str:
    lines = []
    for task in tasks:
        line = f"- [{task['state']}] {task['title']}"
        if task["summary"]:
            line += f": {task['summary']}"
        lines.append(line)
    return "\n".join(lines) or (
        "(none on your task list in this period; summarise what you finished from "
        "your own work log, and say in the report that you did)"
    )


#: Added to a crewmate's daily reminder and goal-setup wake while it has no Dashboard
#: page of its own (:func:`dashboard_line`).
DASHBOARD_BUILD_LINE: str = (
    "Kiro Crew notes: you have no Dashboard page of your own yet, so this wake writes "
    "one: your own HTML page (view.html), saved with dashboard_save and put live with "
    "dashboard_apply; the dashboard skill has the detail. The page shows your goal, each "
    "milestone with its latest reading, what you are working on, and what waits on the "
    "user. Read each value from a crew-log fold where one carries it, so the page stays "
    "current by itself as events land: goal for the goal and its milestones, waiting "
    "for what waits on the user, work and workstreams for your work items; "
    "dashboard_types lists the rest. A fact the page needs that no fold carries yet is a "
    "new crew-log event type, not a value you keep typing; a hand-written field is for "
    "prose only you know, such as your own verdict. Its look comes from this project and "
    "this goal: the repo's README, its domain, its language and what the code does, so "
    "the page reads as part of this work rather than a stock page, unless the user has "
    "asked for a style, which wins and stays on every rebuild. With no style asked, make "
    "it modern, polished and good-looking, with tasteful motion: an entrance as the page "
    "loads and a brief change when a value moves, nothing that loops while the page "
    "sits open, and none under prefers-reduced-motion. Colour only with the variables "
    "the Dashboard tab sets for light and dark: var(--bg), var(--bg-elevated), "
    "var(--card), var(--card-fg), var(--text), var(--text-strong), var(--muted), "
    "var(--border), var(--accent), var(--accent-subtle), var(--ok), var(--warn), "
    "var(--danger); a var() of any other name draws its fixed fallback in both schemes. "
    "Search the Kiro Crew docs with search_docs before guessing "
    "how a fold or a dashboard field works. Once dashboard_apply has put it live, post "
    "one short message, the only one about it: a Dashboard page is ready for the user "
    "on your Dashboard tab, open it to see it. No preview, nothing else."
)


def knows_its_page(rec: dict[str, Any]) -> bool:
    """Whether a crewmate knows what its page is about: a goal and confirmed milestones.

    Milestones are stored only once the person confirms them (the
    ``crewmate.key_results`` card or the Goals tab), so a stored one is a confirmed one.
    """
    return member_goals.has_goal(rec) and bool(rec.get("key_results"))


def dashboard_line(slug: str, rec: dict[str, Any], *, has_mate_tools: bool = True) -> str:
    """The build-your-page line for crewmate *slug*, the one-time page offer, or ``""``.

    The build line only while its Dashboard tab shows nothing of its own: no package bound to it
    (:func:`kiro_crew.dashboard_agentic.bound_package`) and the suggestions page
    (:func:`kiro_crew.dashboard_agentic.tab_shows_suggestions`, the read route's own
    answer), so a template page the person picked, or the page named for the
    crewmate, is never replaced on a wake: a crewmate on a template page gets the
    one-time offer instead (:func:`kiro_crew.dashboard.page_offer.offer_line`), a card
    the person answers. Either only once *rec* holds a goal and
    confirmed milestones (:func:`knows_its_page`), so the page has something to be
    about. The offer needs ``offer_dashboard_page`` (``kirocrew-mate``), so a crewmate
    without those tools (*has_mate_tools* False) gets no offer line. An empty *slug*,
    or a lookup that fails, gets no line. Blocking IO.
    """
    if not slug or not knows_its_page(rec):
        return ""
    from kiro_crew import dashboard_agentic

    try:
        from kiro_crew.dashboard_templates import instance as template_instance

        if template_instance.is_locked(slug):
            # The person locked the layout: an apply would be refused, so no wake
            # asks for a page.
            return ""
        if dashboard_agentic.bound_package(slug):
            return ""
        if not dashboard_agentic.tab_shows_suggestions(slug):
            # A template page is on the tab: never replaced on a wake, only offered,
            # once, on a card (``page_offer``).
            from kiro_crew.dashboard import page_offer

            return page_offer.offer_line(slug, rec) if has_mate_tools else ""
    except Exception:
        logger.debug("dashboard line for %s: page lookup failed", slug, exc_info=True)
        return ""
    return DASHBOARD_BUILD_LINE


def reminder_prompt(
    rec: dict[str, Any],
    cadence: str = member_goals.CADENCE_DAILY,
    *,
    finished: list[dict[str, str]] | None = None,
    dashboard: str = "",
) -> str:
    """The hidden turn's text for *cadence*, built from the current goal record.

    *finished* is :func:`finished_tasks` for the weekly and monthly prompts.
    *dashboard* is :func:`dashboard_line`, added last to the daily prompt.
    """
    block = member_goals.progress_block(rec)
    done = _finished_lines(finished or [])
    if cadence == member_goals.CADENCE_DAILY:
        return (
            "[Daily goal reminder] " + _PREAMBLE + f"{block}\n\n"
            "Take a fresh reading of each key result and record it with "
            "key_result_progress (on the kirocrew-mate server); a reading can be a "
            "number or a short note. Lead your message with those readings and say "
            "briefly where things stand toward each goal, then continue "
            "with your next task. Ask the user something only when you are blocked."
        ) + (f"\n\n{dashboard}" if dashboard else "")
    if cadence == member_goals.CADENCE_WEEKLY:
        return (
            "[Weekly report] "
            + _PREAMBLE
            + f"{block}\n\nHow each key result moved this week, from its readings:\n"
            + _movement_lines(rec, cadence)
            + "\n\nTasks you finished this week, from your work ledger:\n"
            + done
            + "\n\nWrite this week's report for the user in Markdown: how each key "
            "result moved, the tasks you finished, what is stuck and why, "
            "and the plan for next week. Base the numbers on the readings above, and "
            "take a fresh reading first when one is stale. Save it with "
            'save_goal_report (kind "weekly"), then reply in the thread with one short '
            "line pointing at it; the report itself stays out of the chat."
        )
    return (
        "[Monthly review] "
        + _PREAMBLE
        + f"{block}\n\nHow each key result moved this month, from its readings:\n"
        + _movement_lines(rec, cadence)
        + "\n\nTasks you finished this month, from your work ledger:\n"
        + done
        + "\n\nReview whether your goals and their key results still fit the "
        "work you are actually doing. Write the review in Markdown: what the month "
        "showed, whether the direction still holds, and what you would change. Save "
        'it with save_goal_report (kind "monthly"), then reply in the thread with one '
        "short line pointing at it. When the key results or a goal no longer fit the "
        "work, propose the replacement as a card in this turn (set_key_results for the "
        "whole set, set_goal with that goal's id for a goal) with the reason drawn from "
        "the review; the user decides with the card's button. When they still fit, "
        "leave them as they "
        "are and propose nothing."
    )


def _idle_thread(state: Any, slot_key: str, member: str) -> tuple[Any, str]:
    """``(slot, "")`` when *member*'s open thread is idle, else ``(None, reason)``."""
    slot = state.get_slot(slot_key)
    if (
        slot is None
        or getattr(slot, "mode", "") != members_mod.DM_SLOT_MODE
        or getattr(slot, "agent", "") != member
        or getattr(slot, "executor", "") == "remote"
    ):
        return None, "skipped: the crewmate's thread is not open"
    if slot.running or getattr(slot, "_queue", None):
        return None, "skipped: the crewmate is busy"
    return slot, ""


async def fire(state: Any, job: Any) -> str:
    """Run one check-in for *job*'s crewmate; returns a one-line outcome for the run log."""
    from kiro_crew.dashboard.mate_welcome import dispatch_hidden_turn

    cadence = cadence_of(job)
    if cadence is None:
        return "skipped: not a goal check-in"
    slug = str(job.managed_by)[len(MANAGED_PREFIXES[cadence]) :]
    if state is None:
        return "skipped: the dashboard is not running"
    try:
        members_mod.validate_slug(slug)
        binding = await asyncio.to_thread(members_mod.read_dm_binding, slug)
    except (members_mod.MemberSlugError, OSError):
        return "skipped: no crewmate thread"
    if not binding:
        return "skipped: no crewmate thread"
    member = binding.get("member")
    if not isinstance(member, str) or not member:
        return "skipped: no crewmate thread"
    try:
        rec = await asyncio.to_thread(member_goals.read_goals, slug, member)
    except member_goals.GoalsUnreadable:
        logger.warning("goal check-in for %s: goal record unreadable", slug)
        return "skipped: goal record unreadable"
    if not rec["schedules"].get(cadence) or not member_goals.has_goal(rec):
        return "skipped: switch off or no goal"
    slot_key = binding.get("slot_key", "")
    slot, skip = _idle_thread(state, slot_key, member)
    if skip:
        return skip
    finished: list[dict[str, str]] = []
    dashboard = ""
    if cadence == member_goals.CADENCE_DAILY:
        from kiro_crew.member_mate_tools import member_has_mate_tools

        dashboard = await asyncio.to_thread(
            lambda: dashboard_line(slug, rec, has_mate_tools=member_has_mate_tools(member))
        )
        # The binding read ran off the loop: a turn may have started meanwhile.
        again, skip = _idle_thread(state, slot_key, member)
        if skip:
            return skip
        if again is not slot:
            return "skipped: the crewmate's thread is not open"
    if cadence in member_goals.REPORT_KINDS:
        finished = await asyncio.to_thread(finished_tasks, slot_key, cadence)
        # A turn (a cron notification, a user message) can start while the
        # ledger read runs; the check-in then waits for its next time.
        again, skip = _idle_thread(state, slot_key, member)
        if skip:
            return skip
        if again is not slot:
            return "skipped: the crewmate's thread is not open"
    dispatch_hidden_turn(
        state,
        slot,
        reminder_prompt(rec, cadence, finished=finished, dashboard=dashboard),
        human_seen=False,
    )
    return "started"


def _folder_label(label: str) -> str:
    # A path segment: "/" would nest folders, so it reads as a dash.
    clean = label.replace("/", "-").strip() or "crewmate"
    return clean[:100]


def save_report(
    slug: str, member: str, label: str, *, kind: str, title: str, markdown: str, session_key: str
) -> dict[str, Any]:
    """Save one report as a Markdown artifact under ``Crewmates/<name>/Reports``.

    Records it on the goal record and returns ``{"slug", "title", "url",
    "folder"}``. Blocking IO.
    """
    from kiro_crew.artifacts import get_default_folder_store, get_default_store

    if kind not in member_goals.REPORT_KINDS:
        raise member_goals.GoalError("invalid_report_kind", "a report is weekly or monthly")
    if not isinstance(markdown, str) or not markdown.strip():
        raise member_goals.GoalError("empty_report", "the report needs some text")
    # The crewmate wrote the report: scrubbed like every goal string it writes.
    title = member_goals.scrub_text(title)
    markdown = member_goals.scrub_text(markdown)
    folder_path = REPORTS_FOLDER.format(name=_folder_label(label))
    folder_id = get_default_folder_store().resolve_path(folder_path, create_missing=True)
    art = get_default_store().create(
        name=title,
        content=markdown,
        kind="markdown",
        source="chat",
        description=f"{_NAMES[kind]} by {label}",
        tags=["goal-report", kind],
        folder_id=folder_id,
        session_key=session_key,
    )
    member_goals.record_report(slug, member, kind=kind, artifact=art.slug, title=title)
    return {
        "slug": art.slug,
        "title": title,
        "url": f"/artifacts/{art.slug}",
        "folder": folder_path,
    }
