"""Whether a crewmate's milestone is met, read from the milestone record alone.

A reading is free text the crewmate writes, so "met" is judged from what the text
settles and nothing else. The crewmate's Dashboard page reads the answer through the
``goal`` fold (``dashboard.crewmate_feed.goal_snapshot``), which counts met, open and
total milestones.
"""

from __future__ import annotations

import re
from typing import Any

#: A number in a target or reading, the comparison a target may lead with, and
#: the unit word right after it ("4 fixes", "0 failing", "85%").
_NUMBER_RE = re.compile(
    r"(?P<cmp><=|>=|≤|≥|<|>)?\s*(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:[.,]\d+)?)"
    r"\s*%?(?:\s*(?P<unit>[^\W\d_]+))?"
)
#: A number written with ``,`` thousands groups ("1,000", "12,500.5").
_GROUPED = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
#: Words after a number that are not its unit ("3 of 5", "1 or more").
_NOT_UNITS = frozenset({"of", "or", "out", "and", "to", "in", "on", "per"})
#: A reading that says the target is reached, whatever the target's form.
_DONE_WORDS = frozenset({"met", "done", "yes", "reached", "achieved", "complete", "completed"})
#: Phrases in a target that ask for at least its number, before or after it.
_AT_LEAST = re.compile(
    r"\b(?:at least|no fewer than|over|above|more than)\s*-?\d|\d\S*\s*(?:or more|\+)"
)
#: Words in a milestone's text or target that make a smaller reading the better one.
#: Only words that govern the measured count: a bare verb ("Open 10 pull requests",
#: "Cut 3 releases") says what is done, not that fewer is better.
_REDUCE_WORDS = re.compile(
    r"\b(?:reduce[ds]?|reducing|lower|fewer|less than|below|under|at most|no more than|"
    r"down to|shrink|remaining|left|failing|errors?|mismatch(?:es)?)\b"
)


def _number(text: str) -> tuple[str, float, str] | None:
    m = _NUMBER_RE.search(text)
    if m is None:
        return None
    unit = (m.group("unit") or "").casefold()
    if unit in _NOT_UNITS:
        unit = ""
    num = m.group("num")
    # "1,000" groups thousands; a lone "," before other than three digits is a decimal mark.
    value = float(num.replace(",", "") if _GROUPED.fullmatch(num) else num.replace(",", "."))
    return m.group("cmp") or "", value, unit


def _same_unit(a: str, b: str) -> bool:
    """Whether two unit words name one thing: either is absent, or they match up to a plural."""
    if not a or not b:
        return True
    return _singular(a) == _singular(b)


def _singular(word: str) -> str:
    """*word* with one plural suffix taken off: ``classes`` -> ``class``, ``fixes`` -> ``fix``."""
    if word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def key_result_met(kr: dict[str, Any]) -> bool:
    """Whether *kr*'s latest reading reaches its target, judged from the record alone.

    A reading is free text, so this answers only what the text settles:

    * a reading that leads with a word saying so (``done``, ``met``, ``yes``...)
      and carries no number;
    * a word target the reading repeats from its start ("all docs in sync");
    * numbers, when both the reading and the target carry one and their unit
      words agree (a missing unit agrees with any): the target's own comparison
      when it names one ("<= 2", "> 80%", "1 or more", "at most 3"); otherwise
      fewer is better when the milestone's text or target speaks of reducing
      (reduce, below, at most, left, failing...) or the target is 0, and
      more is better in every other case ("4 fixes proposed" meets "3").

    Anything else is not met: a reading this cannot place reads as still open.
    """
    current = str(kr.get("current") or "").strip()
    target = str(kr.get("target") or "").strip()
    if not current or not target:
        return False
    words = _words(current)
    target_words = _words(target)
    cur_num = _number(current)
    if words and words[0] in _DONE_WORDS and cur_num is None:
        return True
    tgt_num = _number(target)
    if tgt_num is None or cur_num is None:
        return bool(target_words) and words[: len(target_words)] == target_words
    cmp, goal, goal_unit = tgt_num
    _cmp, now, now_unit = cur_num
    if not _same_unit(now_unit, goal_unit):
        return False
    if cmp in ("<=", "≤"):
        return now <= goal
    if cmp in (">=", "≥"):
        return now >= goal
    if cmp == "<":
        return now < goal
    if cmp == ">":
        return now > goal
    low_target = target.casefold()
    if _AT_LEAST.search(low_target):
        return now >= goal
    reduce = goal == 0 or _REDUCE_WORDS.search(f"{kr.get('text') or ''} {target}".casefold())
    return now <= goal if reduce else now >= goal
