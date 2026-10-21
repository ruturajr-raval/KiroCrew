"""The Dynamic capabilities switch: ``dashboard.crewmate_dynamic_capabilities``, off by default.

Nested under Crewmate 2.0 (:mod:`kiro_crew.crewmate_v2`). It holds only the
crewmate-driven capability path: the crewmate finding a skill or an MCP server
for its own worker and asking for it on a card. With it off, while Crewmate 2.0
is on:

* ``find_capabilities`` and ``request_capabilities`` are not mounted on the
  ``kirocrew-mate`` server (``mcp_mate._list_tools``) and their routes answer 404
  (``member_capability_catalog.api_member_self_capabilities``,
  ``member_self.api_member_self_propose`` for ``capabilities``);
* the hand-off carries no capability summary
  (``crewmate_dispatch_capabilities.own_worker_note``);
* a worker's gap reaches the conductor as one plain line telling it to ask the
  user to add the capability in the crewmate's advanced settings, never a card
  (``mate_thread_wakes.report_prompt``);
* no ``[Capabilities added]`` nudge (``handlers/change_cards._complete``);
* the worker prompt asks for no ``MISSING CAPABILITY:`` line
  (``mate_worker.mate_worker_prompt``) and the conductor prompt names none of
  those tools (``context_assembly/member.build_member_section``).

The user adding or removing worker capabilities by hand in the crewmate's
advanced settings (``/api/agents/{member}/capabilities``, ``/worker-kit``) is
not this switch's; it works either way.

The effective value is Crewmate 2.0 AND this switch (:func:`enabled`). With 2.0
off the gateway runs the shape before the split, which this switch does not
touch (:func:`restricted` is False then). Read ONCE per process like 2.0; a
config that cannot be read answers off and is not latched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The config path of the switch (``config/sections_dashboard.py``).
CONFIG_KEY = "dashboard.crewmate_dynamic_capabilities"

_latched: bool | None = None


def _read() -> bool | None:
    try:
        from kiro_crew.config.loader import KiroCrewConfig

        return bool(KiroCrewConfig.load().dashboard.crewmate_dynamic_capabilities)
    except Exception:  # noqa: BLE001 - an unreadable config is "off", not latched
        logger.debug("dynamic capabilities: config unreadable, reading as off", exc_info=True)
        return None


def _own() -> bool:
    """This switch's own value, latched on the first good read."""
    global _latched
    if _latched is None:
        value = _read()
        if value is None:
            return False
        _latched = value
    return _latched


def enabled() -> bool:
    """Whether the crewmate-driven capability path is on: Crewmate 2.0 AND this switch."""
    from kiro_crew import crewmate_v2

    return crewmate_v2.enabled() and _own()


def restricted() -> bool:
    """Crewmate 2.0 is on and this switch is off: the crewmate-driven path is withheld.

    False while 2.0 is off, so the shape before the split keeps what it had
    (``request_capabilities`` with a raw operations draft).
    """
    from kiro_crew import crewmate_v2

    return crewmate_v2.enabled() and not _own()


def latch() -> bool:
    """Read the switch now and hold it for the rest of the process. Startup calls this."""
    global _latched
    _latched = None
    return _own()
