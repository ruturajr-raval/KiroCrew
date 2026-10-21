# SPDX-License-Identifier: Apache-2.0
"""Dynamic capabilities behind ``dashboard.crewmate_dynamic_capabilities``, off by default.

Nested under Crewmate 2.0. Off (with 2.0 on), the crewmate-driven capability
path is withheld: no find_capabilities or request_capabilities on the conductor
and their routes answer 404, no capability summary on hand-off, a worker's gap
reaches the conductor as one plain "ask the user" line and never a card, no
``[Capabilities added]`` nudge, and the worker is asked for no
``MISSING CAPABILITY:`` line. The user adding worker capabilities by hand in the
crewmate's advanced settings keeps working. With 2.0 off the switch has no
effect. The rest of the suite runs with it on
(``conftest._crewmate_dynamic_capabilities_on``).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from kiro_crew import crewmate_dynamic_capabilities as dyn
from kiro_crew import crewmate_prompts, crewmate_v2, mcp_mate
from kiro_crew.config.loader import KiroCrewConfig

CAPABILITY_TOOLS = {"find_capabilities", "request_capabilities"}


@pytest.fixture
def off():
    dyn._latched = False


@pytest.fixture
def v2_off():
    crewmate_v2._latched = False


# ── the switch itself ──


def test_the_switch_ships_off_and_is_a_restart_setting():
    from kiro_crew.config import loader
    from kiro_crew.config.schema import requires_restart
    from kiro_crew.dashboard.handlers import core

    assert KiroCrewConfig().dashboard.crewmate_dynamic_capabilities is False
    assert loader._build_dashboard_config(set(), {}).crewmate_dynamic_capabilities is False
    built = loader._build_dashboard_config(set(), {"crewmate_dynamic_capabilities": True})
    assert built.crewmate_dynamic_capabilities is True
    assert requires_restart(dyn.CONFIG_KEY)
    assert core._EDITABLE_CONFIG[dyn.CONFIG_KEY] == {"type": "bool"}


def test_the_switch_is_read_once_per_process(monkeypatch):
    reads = iter([True, False])
    monkeypatch.setattr(dyn, "_read", lambda: next(reads))
    assert dyn.latch() is True
    assert dyn.enabled() is True


def test_an_unreadable_config_reads_off_and_is_not_latched(monkeypatch):
    dyn._latched = None
    monkeypatch.setattr(dyn, "_read", lambda: None)
    assert dyn.enabled() is False
    assert dyn._latched is None


def test_the_effective_value_is_2_0_and_this_switch(v2_off):
    # 2.0 off: the switch has no effect, either way.
    for own in (True, False):
        dyn._latched = own
        assert dyn.enabled() is False
        assert dyn.restricted() is False
    crewmate_v2._latched = True
    dyn._latched = True
    assert (dyn.enabled(), dyn.restricted()) == (True, False)
    dyn._latched = False
    assert (dyn.enabled(), dyn.restricted()) == (False, True)


# ── off: the conductor's tools and their routes ──


def test_off_the_conductor_mounts_neither_tool(off):
    names = {t["name"] for t in mcp_mate._list_tools()}
    assert not names & CAPABILITY_TOOLS
    # Everything else the crewmate asks for on a card stays.
    assert {"update_self", "set_model", "set_goal", "set_check_ins"} <= names
    for tool in CAPABILITY_TOOLS:
        assert "unknown tool" in mcp_mate._call_tool_inner(tool, {})
    dyn._latched = True
    assert CAPABILITY_TOOLS <= {t["name"] for t in mcp_mate._list_tools()}


def test_2_0_off_keeps_request_capabilities_as_before(v2_off, off):
    names = {t["name"] for t in mcp_mate._list_tools()}
    assert "request_capabilities" in names and "find_capabilities" not in names


@pytest.fixture
def routes(monkeypatch):
    from guide_route_helpers import FakeState, agent, run_guide_app

    from kiro_crew import members as members_mod
    from kiro_crew.dashboard.handlers import guide as guide_routes
    from kiro_crew.dashboard.handlers import member_capability_catalog as catalog_routes
    from kiro_crew.dashboard.handlers import member_self as self_routes

    class _Null:
        def log_api_access(self, **_kw):
            return None

    monkeypatch.setattr(guide_routes, "sel", lambda: _Null())
    state = FakeState()
    slot = state.open_slot("member-pixel")
    slot.mode = members_mod.DM_SLOT_MODE
    slot.agent = "pixel"
    table = {
        "find": (
            "POST",
            "/api/member/self/capabilities",
            catalog_routes.api_member_self_capabilities,
        ),
        "propose": ("POST", "/api/member/self/propose", self_routes.api_member_self_propose),
    }

    def post(which, body):
        method, path, handler = table[which]

        async def go(c):
            r = await c.post(path, json=body, headers=agent("dashboard:member-pixel"))
            return r.status, await r.json()

        return run_guide_app(go, state, extra_routes=[(method, path, handler)])

    return post


ADDITIONS = {"request": "capabilities", "params": {"draft": {"additions": [{"server": "jira"}]}}}
OPERATIONS = {
    "request": "capabilities",
    "params": {"draft": {"operations": [{"section": "skills", "id": "x", "action": "set"}]}},
}


def test_off_both_routes_answer_404(off, routes):
    assert routes("find", {})[0] == 404
    for body in (ADDITIONS, OPERATIONS):
        status, answer = routes("propose", body)
        assert (status, answer["code"]) == (404, "not_found")


def test_off_the_other_crewmate_cards_are_still_proposed(off, routes, monkeypatch):
    from kiro_crew.dashboard.handlers import change_cards

    seen: list[str] = []

    async def propose(request, slot_key, sk, *, kind, params, reason):
        from aiohttp import web

        seen.append(kind)
        return web.json_response({"kind": kind})

    monkeypatch.setattr(change_cards, "propose_for_caller", propose)
    from kiro_crew.dashboard.handlers.member_self import SELF_PROPOSALS

    status, _ = routes("propose", {"request": "model", "params": {"model": "m"}})
    assert (status, seen) == (200, [SELF_PROPOSALS["model"]])


# ── off: no gap card, a plain line instead ──


def _report(text):
    return [{"turns": 1, "title": "t", "key": "k", "reply": text}]


@pytest.mark.parametrize(
    "reply",
    [
        "MISSING CAPABILITY: the jira server -- the task reads tickets\nDid the rest.",
        "Step 2: blocked on jira (no jira tool)",
    ],
)
def test_off_a_worker_gap_is_a_plain_line_and_no_card(off, reply):
    from kiro_crew.dashboard import mate_thread_wakes

    prompt = mate_thread_wakes.report_prompt(_report(reply))
    assert "advanced settings" in prompt
    assert "find_capabilities" not in prompt and "request_capabilities" not in prompt
    dyn._latched = True
    prompt = mate_thread_wakes.report_prompt(_report(reply))
    assert "request_capabilities" in prompt and "advanced settings" not in prompt


def test_off_a_crewmate_cannot_raise_the_card_through_propose_change(off, monkeypatch):
    from kiro_crew.dashboard.handlers import change_cards

    crew_slot = SimpleNamespace(mode="member-dm", agent="pixel", executor="")
    other_slot = SimpleNamespace(mode="", agent="", executor="")
    monkeypatch.setattr(
        "kiro_crew.dashboard.mate_thread_wakes.is_crewmate_thread",
        lambda slot: slot is crew_slot,
    )
    slots = {"crew": crew_slot, "other": other_slot}
    request = {"state": SimpleNamespace(get_slot=lambda key: slots.get(key))}
    req = SimpleNamespace(app=request)
    refuse = change_cards._crewmate_drives_capabilities_off
    assert refuse(req, "crew", "dashboard:crew") is True
    # The main assistant asked to add a tool to a crewmate still proposes it.
    assert refuse(req, "other", "dashboard:other") is False
    # A crewmate's own worker is refused too.
    from kiro_crew import members

    members.note_crewmate_worker_session("dashboard:w-dyn")
    assert refuse(req, "other", "dashboard:w-dyn") is True
    dyn._latched = True
    assert refuse(req, "crew", "dashboard:crew") is False


# ── off: no summary on hand-off, no nudge ──


def test_off_the_hand_off_carries_no_capability_summary(off, monkeypatch):
    from kiro_crew.dashboard import chat_utils, crewmate_dispatch_capabilities
    from kiro_crew.dashboard.session_control_parts import caller_access

    monkeypatch.setattr(crewmate_dispatch_capabilities, "_note", lambda *a: "worker has: jira")
    monkeypatch.setattr(caller_access, "caller_slot_key", lambda state, key: key)
    monkeypatch.setattr(chat_utils, "slot_history_key", lambda slot: slot)
    state = SimpleNamespace(get_slot=lambda key: key)
    note = crewmate_dispatch_capabilities.own_worker_note
    assert asyncio.run(note(None, state, "a", "b")) == ""
    dyn._latched = True
    assert asyncio.run(note(None, state, "a", "b")) == "worker has: jira"


def _complete_capabilities_card(monkeypatch):
    from kiro_crew import change_card_catalog as catalog
    from kiro_crew.dashboard import goal_setup
    from kiro_crew.dashboard.handlers import change_cards

    nudged: list[str] = []
    store = SimpleNamespace(complete_apply=lambda rec, **kw: None)
    monkeypatch.setattr(change_cards, "card_store_for", lambda state: store)

    async def read_state(*a, **k):
        return {}

    monkeypatch.setattr(change_cards.cards, "read_state", read_state)
    monkeypatch.setattr(change_cards.cards, "after_shows_the_write", lambda *a: True)
    monkeypatch.setattr(catalog, "applied_write_count", lambda *a: 1)
    monkeypatch.setattr(catalog, "build_undo", lambda *a: (None, "x"))
    monkeypatch.setattr(goal_setup, "schedule_capabilities_nudge", lambda s, k, t: nudged.append(t))
    rec = {
        "id": "c1",
        "kind": catalog.KIND_CREWMATE_CAPABILITIES,
        "params": {},
        "before": {},
        "evidence": [],
        "plan": {"apply": []},
        "slot_key": "member-pixel",
        "title": "Add jira to Pixel's worker",
    }
    request = SimpleNamespace(app={"state": SimpleNamespace()})
    asyncio.run(change_cards._complete(request, rec, partial=False))
    return nudged


def test_off_no_capabilities_added_nudge(off, monkeypatch):
    assert _complete_capabilities_card(monkeypatch) == []
    dyn._latched = True
    assert _complete_capabilities_card(monkeypatch) == ["Add jira to Pixel's worker"]


# ── off: the prompts ──


def test_off_the_worker_is_asked_for_no_missing_capability_line(off, monkeypatch):
    from kiro_crew import agent as agent_mod
    from kiro_crew import mate_worker
    from kiro_crew.agent_materialization import service_agents

    assert mate_worker.mate_worker_prompt() == mate_worker.MATE_WORKER_PROMPT_MANUAL
    assert mate_worker.MISSING_CAPABILITY_PREFIX not in mate_worker.mate_worker_prompt()
    assert "advanced settings" in mate_worker.mate_worker_prompt()
    written: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent_config", lambda *a, **k: {"prompt": "Base."})
    monkeypatch.setattr(
        service_agents, "_write_mate_service_spec", lambda f, c, w: written.update(c)
    )
    service_agents._install_mate_worker_agent()
    assert written["prompt"] == f"Base.\n\n{mate_worker.MATE_WORKER_PROMPT_MANUAL}"
    dyn._latched = True
    assert mate_worker.mate_worker_prompt() == mate_worker.MATE_WORKER_PROMPT
    service_agents._install_mate_worker_agent()
    assert mate_worker.MISSING_CAPABILITY_PREFIX in written["prompt"]


def test_off_the_conductor_prompt_names_neither_tool(off, monkeypatch, tmp_path):
    from kiro_crew import context as ctx
    from kiro_crew import member_mate_tools
    from kiro_crew.context_assembly import member

    monkeypatch.setenv("KIROCREW_HOME", str(tmp_path / "home"))
    cfg = ctx.KiroCrewConfig()
    cfg.agents["Ada"] = SimpleNamespace(
        description="", triggers="", kiro_agent="", workspace="", member_id=""
    )
    monkeypatch.setattr(ctx.KiroCrewConfig, "load", staticmethod(lambda *a, **k: cfg))
    monkeypatch.setattr(member_mate_tools, "binding_has_mate_tools", lambda *a, **k: True)
    monkeypatch.setattr(member, "binding_has_mate_tools", lambda *a, **k: True, raising=False)
    text = member.build_member_section("Ada")
    assert "[YOUR CREW LOG, DASHBOARD AND TOOLS]" in text
    assert "find_capabilities" not in text and "request_capabilities" not in text
    assert "advanced settings" in text
    dyn._latched = True
    text = member.build_member_section("Ada")
    assert "request_capabilities" in text


def test_the_manual_pieces_differ_from_the_card_pieces_only_where_they_must():
    card = crewmate_prompts.text("conductor.crew_log_section").splitlines()
    manual = crewmate_prompts.text("conductor.crew_log_section_manual").splitlines()
    assert card[:-1] == manual[:-1]
    for key in (
        "conductor.crew_log_section_manual",
        "conductor.mate_tools_identity_manual",
        "worker.principles_manual",
        "worker_report.missing_capability_manual",
    ):
        piece = crewmate_prompts.text(key)
        assert "find_capabilities" not in piece and "request_capabilities" not in piece, key
        assert "MISSING CAPABILITY" not in piece, key


# ── off: the user still adds capabilities by hand, and a fresh worker has them ──


@pytest.fixture
def mate_home(tmp_path, monkeypatch):
    from kiro_crew import mate_capabilities
    from kiro_crew.config import paths

    user, mates = tmp_path / "agents", tmp_path / "mates" / "agents"
    user.mkdir()
    mates.mkdir(parents=True)
    (mates / "pixel.json").write_text(
        json.dumps({"name": "pixel", "prompt": "", "tools": [], "mcpServers": {}}),
        encoding="utf-8",
    )
    (user / "release-bot.json").write_text(
        json.dumps(
            {
                "name": "release-bot",
                "prompt": "Release SOP.",
                "tools": ["@jira"],
                "mcpServers": {"jira": {"command": "jira-mcp"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "kiro_agents_dir", lambda: user)
    monkeypatch.setattr(paths, "mate_agents_dir", lambda: mates)
    monkeypatch.setattr(mate_capabilities, "mate_agents_dir", lambda: mates, raising=False)
    monkeypatch.setattr(mate_capabilities, "binding_is_mate", lambda member: member == "pixel")
    return mates


def _fresh_worker(mates):
    from kiro_crew import mate_worker

    base = {"name": "kirocrew-mate-worker", "prompt": "Worker.", "mcpServers": {}, "tools": []}
    own = json.loads((mates / "pixel.json").read_text(encoding="utf-8"))
    return mate_worker.merge_worker_spec(base, mate_worker.worker_additions(base, own))


def test_off_a_skill_added_in_advanced_settings_reaches_a_fresh_worker(off, mate_home):
    from kiro_crew import mate_capabilities as mc

    catalog = {"kiro-user/release": "skill://release/SKILL.md"}
    revision = mc._revision(json.loads((mate_home / "pixel.json").read_text()))
    op = {"section": "skills", "id": "kiro-user/release", "action": "set", "value": True}
    body = {
        "revision": revision,
        "operations": [op],
        "preview_token": revision,
        "accept_parent": [],
        "accept_members": [],
    }
    assert mc.put("pixel", body, catalog)["mode"] == "mate"
    assert "skill://release/SKILL.md" in _fresh_worker(mate_home).get("resources", [])


def test_off_a_custom_template_still_configures_the_worker(off, mate_home):
    from kiro_crew import mate_worker_kit

    ask = {"template": "release-bot", "keep_additions": True}
    preview = mate_worker_kit.preview("pixel", ask)
    mate_worker_kit.apply("pixel", {**ask, "revision": preview["revision"]})
    worker = _fresh_worker(mate_home)
    assert "jira" in worker["mcpServers"]
    assert "Release SOP." in worker["prompt"]
