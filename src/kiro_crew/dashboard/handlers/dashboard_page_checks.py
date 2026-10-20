"""Gateway-side checks of a crewmate's saved page, for the ``dashboard_save`` reply.

The offline page run is skipped on a host with no browser, so two mistakes seen on
crewmate pages are checked here on the package text instead: a list, record or time
bound to a ``data-dashboard-field`` cell, which the host fills as raw text, and a
theme whose fixed colours cover one colour scheme only. Both answer in words and
never refuse the save.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

#: How a page shows each field type a ``data-dashboard-field`` cell shows raw.
RENDERING: Final[dict[str, str]] = {
    "array": (
        "A list of rows. A data-dashboard-field cell shows it as raw JSON text, such as "
        "[]; read it in the page's own script (window.kirocrew.subscribe) and draw one "
        "element per row, with a line for an empty list."
    ),
    "object": (
        "A nested record. A data-dashboard-field cell shows it as raw JSON text; read it "
        "in the page's own script (window.kirocrew.subscribe) and draw the keys it needs."
    ),
    "timestamp": (
        "An ISO-8601 time such as 2026-10-19T01:24:28+00:00. A data-dashboard-field cell "
        "shows it raw; format it in the page's own script (new Date(value)."
        "toLocaleString(), or a relative time such as 5 min ago)."
    ),
}

#: One line of a save reply's ``shape_warnings``.
SHAPE_WARNING: Final[str] = (
    "{field} is {kind} but a data-dashboard-field cell shows it as plain text. {how}"
)

#: A save reply's ``theme_warnings`` line when the theme's colours cover one scheme.
THEME_ONE_SCHEME: Final[str] = (
    "Your theme sets fixed colours for one scheme only, so the page is unreadable in "
    "the other (pale text on white, or dark text on a dark board). Colour with the "
    "dashboard's theme variables (var(--text), var(--bg), var(--accent)...; a var() "
    "the dashboard does not set, such as var(--my-fg, #eee), draws its fixed fallback), "
    "or set "
    "both schemes: a @media (prefers-color-scheme: dark) block, or "
    ':root[data-mode="dark"] rules beside the light ones.'
)

#: A save reply's ``theme_warnings`` line for a ``var()`` the frame never defines.
#: ``{names}`` is the variables, ``{host}`` the ones the frame does define.
UNDEFINED_VAR: Final[str] = (
    "{names} is not a variable the Dashboard tab defines and your theme tokens do not "
    "set it, so the page always draws its fixed fallback colour, which reads in one "
    "scheme only. Use the variables the tab sets for the scheme in force: {host}."
)

#: The host variables a page colours with, in the order the skill names them.
HOST_COLOUR_VARS: Final[str] = (
    "--bg, --bg-elevated, --card, --card-fg, --text, --text-strong, --muted, --border, "
    "--accent, --accent-subtle, --ok, --warn, --danger"
)

#: ``verification.note`` on a save whose page run was skipped.
VERIFICATION_SKIPPED: Final[str] = (
    "The page was NOT run: {reason}. Nothing checked that it draws, that its script "
    "runs or that it reads in light and dark, so check those yourself in the page "
    "before you apply it."
)

#: A save reply's ``manual_note`` when the page holds a hand-written field.
MANUAL_FIELDS_NOTE: Final[str] = (
    "These fields change only when you write them with dashboard_write, so they go "
    "stale the moment you stop. A fact the crew log already records reads better "
    "from its fold (dashboard_types lists them: goal, waiting, work, workstreams, usage...); keep a "
    "manual field for prose only you know, such as your own verdict."
)

#: The field types a page has to draw itself: a text cell shows them raw.
_DRAWN_BY_SCRIPT: Final[tuple[str, ...]] = ("array", "object", "timestamp")


def page_rendering() -> dict[str, str]:
    """How a page shows each field type a ``data-dashboard-field`` cell cannot."""
    return dict(RENDERING)


def skipped_note(reason: str) -> str:
    """The words a skipped page run carries, so it is not read as a pass."""
    return VERIFICATION_SKIPPED.format(reason=reason or "no reason given")


_BOUND_CELL = re.compile(r"""data-dashboard-field\s*=\s*["']?([a-z][a-z0-9_]*)""")


def shape_warnings(package: Mapping[str, Any]) -> list[str]:
    """One line per array, object or timestamp field the page binds as a text cell.

    The host fills a ``data-dashboard-field`` element as TEXT, so a list shows as
    ``[]`` and a time as a raw ISO string. A field the page only reads in its script is
    not bound that way and is not named.
    """
    types = ((package.get("model") or {}).get("types")) or {}
    html = ((package.get("view") or {}).get("html")) or ""
    bound = set(_BOUND_CELL.findall(html)) if isinstance(html, str) else set()
    out: list[str] = []
    for name in sorted(bound):
        spec = types.get(name)
        kind = spec.get("type") if isinstance(spec, Mapping) else None
        if kind in _DRAWN_BY_SCRIPT:
            out.append(SHAPE_WARNING.format(field=name, kind=kind, how=RENDERING[kind]))
    return out


#: A colour written as a value rather than read from a variable.
_FIXED_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(")
_COLOUR_DECL = re.compile(r"(?<![-\w])(color|background(?:-color)?)\s*:\s*([^;}]+)")
#: No ``\s*`` after the comma: it would overlap the fallback's ``[^()]*`` and
#: backtrack quadratically over a long run of spaces. Readers strip the fallback.
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,([^()]*(?:\([^()]*\)[^()]*)*))?\)")
_FG_TOKEN = re.compile(r"(?:fg|text|ink|fore)", re.I)
_BG_TOKEN = re.compile(r"(?:bg|back|surface|panel|board|paper)", re.I)
#: Ways a theme covers both schemes, or defers to the host's scheme-aware variables.
_BOTH_SCHEMES = ("prefers-color-scheme", "light-dark(", "data-mode", "data-theme")
#: The variables the Dashboard tab sets in the page for the scheme in force
#: (``website/src/lib/widgetSrcdoc.ts`` ``THEME_VAR_NAMES``): reading one is never fixed.
HOST_THEME_VARS: Final[frozenset[str]] = frozenset(
    {
        "--bg", "--bg-elevated", "--bg-hover", "--card", "--card-fg", "--text",
        "--text-strong", "--muted", "--muted-strong", "--border", "--border-strong",
        "--accent", "--accent-hover", "--accent-subtle", "--ok", "--ok-subtle", "--warn",
        "--warn-subtle", "--danger", "--danger-subtle", "--info",
    }
)  # fmt: skip
#: Selectors whose background is the whole page's, so every other rule sits on it.
_PAGE_SELECTORS = frozenset({"html", "body", ":root", "*"})


def _opaque(value: str) -> bool:
    """False for a colour that lets the background through (``rgba(..., 0.04)``)."""
    # Read with string splits, not a backtracking pattern: *value* is page text.
    low = value.casefold()
    for m in _COLOUR_FN.finditer(low):
        end = low.find(")", m.end())
        if end < 0:
            break
        inside = low[m.end() : end]
        if "/" in inside:
            raw = inside.rsplit("/", 1)[1].strip()
        elif m.group(1) in ("rgba", "hsla") and "," in inside:
            raw = inside.rsplit(",", 1)[1].strip()
        else:
            continue
        try:
            number = float(raw.rstrip("%")) / (100 if raw.endswith("%") else 1)
        except ValueError:
            return True
        return number >= 0.5
    return True


_COLOUR_FN = re.compile(r"\b(rgba?|hsla?|oklch|oklab|lab|lch)\(")


def _style_bodies(html: str) -> str:
    """The text of every ``<style>`` element in *html*, joined, in one linear pass."""
    low = html.casefold()
    out: list[str] = []
    at = 0
    while True:
        start = low.find("<style", at)
        if start < 0:
            break
        open_end = low.find(">", start)
        if open_end < 0:
            break
        close = low.find("</style>", open_end + 1)
        if close < 0:
            break
        out.append(html[open_end + 1 : close])
        at = close + len("</style>")
    return " ".join(out)


def _resolve(value: str, tokens: Mapping[str, Any]) -> str:
    """*value* with each ``var()`` replaced by what it draws in a scheme the page fixes.

    A host theme variable follows the scheme, so it becomes ``""`` (nothing fixed); a
    theme token becomes its value; any other variable, which nothing defines, draws
    its fallback.
    """

    def one(m: re.Match[str]) -> str:
        name, fallback = m.group(1), (m.group(2) or "").strip()
        if name in HOST_THEME_VARS:
            return ""
        token = tokens.get(name)
        return token if isinstance(token, str) else fallback

    return _VAR.sub(one, value)


def _rules(text: str) -> list[tuple[str, str]]:
    """Each innermost ``selector { body }`` in *text*, in one linear pass.

    A rule nested in ``@media`` yields its own selector. A pattern search here
    would backtrack over a long brace-free tail (an inlined source map) in time
    quadratic in its length, and this runs on text the crewmate wrote.
    """
    out: list[tuple[str, str]] = []
    chunks = text.split("}")
    for chunk in chunks[:-1]:  # the last piece has no closing brace
        head, brace, body = chunk.rpartition("{")
        if not brace:
            continue
        selector = head.rsplit("{", 1)[-1]
        if selector:
            out.append((selector, body))
    return out


def _parts(selector: str) -> list[list[str]]:
    """Each comma-separated selector as its compound steps (``.a > .b`` -> ``.a``, ``.b``)."""
    return [p.split() for p in re.sub(r"[>+~]", " ", selector).split(",") if p.strip()]


def _covered(fg_steps: list[str], bg_selectors: list[list[str]]) -> bool:
    """Whether a rule with these steps sits on a fixed background a rule above it sets."""
    for bg in bg_selectors:
        if len(bg) == 1 and bg[0] in _PAGE_SELECTORS:
            return True
        if bg == fg_steps[: len(bg)]:
            return True
    return False


def theme_warnings(package: Mapping[str, Any]) -> list[str]:
    """A warning when the page's fixed colours cover one scheme only.

    Text with a fixed colour drawn on a background the host paints (or the reverse)
    reads in one scheme and not the other: light text on the host's white page. Each
    CSS rule that fixes a text colour is checked against a fixed opaque background on
    the same rule, on a rule for an ancestor selector (``.board`` above ``.board h1``)
    or on the page itself, so a chalkboard with chalk text reads the same in each and a
    coloured dot elsewhere does not count as the page's background. A ``var()`` of a
    host theme variable follows the scheme; any other ``var()`` draws what its token or
    fallback says. A fixed page background with no fixed text colour is the reverse
    case. A theme that names both schemes is left alone. A heuristic on the CSS text
    (theme tokens, ``theme.css`` and the page's own ``<style>``), run here because the
    page run is skipped on a host with no browser.
    """
    theme = package.get("theme") or {}
    raw_tokens = theme.get("tokens") if isinstance(theme, Mapping) else None
    tokens: Mapping[str, Any] = raw_tokens if isinstance(raw_tokens, Mapping) else {}
    css = theme.get("css") if isinstance(theme, Mapping) else ""
    html = ((package.get("view") or {}).get("html")) or ""
    styles = _style_bodies(html) if isinstance(html, str) else ""
    text = f"{css if isinstance(css, str) else ''}\n{styles}"
    out = _undefined_var_warnings(text, html if isinstance(html, str) else "", tokens)
    if any(marker in text for marker in _BOTH_SCHEMES):
        return out
    fg_token = bg_token = False
    for name, value in tokens.items():
        if isinstance(value, str) and _FIXED_COLOUR.search(value):
            if _FG_TOKEN.search(str(name)):
                fg_token = True
            elif _BG_TOKEN.search(str(name)) and _opaque(value):
                bg_token = True
    fg_rules: list[tuple[list[list[str]], bool]] = []
    bg_selectors: list[list[str]] = []
    for selector, body in _rules(text):
        fixed_fg = fixed_bg = False
        for prop, value in _COLOUR_DECL.findall(body):
            drawn = _resolve(value, tokens)
            if not _FIXED_COLOUR.search(drawn):
                continue
            if prop == "color":
                fixed_fg = True
            elif _opaque(drawn):
                fixed_bg = True
        parts = _parts(selector.strip())
        if fixed_bg:
            bg_selectors.extend(parts)
        if fixed_fg:
            fg_rules.append((parts, fixed_bg))
    page_bg = bg_token or any(len(b) == 1 and b[0] in _PAGE_SELECTORS for b in bg_selectors)
    uncovered = any(
        not own_bg and not page_bg and not all(_covered(p, bg_selectors) for p in parts)
        for parts, own_bg in fg_rules
    )
    one_scheme = (
        (fg_token and not bg_token)
        or uncovered
        or (page_bg and not fg_token and not fg_rules)
        or (bg_token and not fg_token and not fg_rules)
    )
    return ([THEME_ONE_SCHEME] if one_scheme else []) + out


#: A custom property the page's own CSS defines (``--name: value``).
_DEFINED_VAR = re.compile(r"(?<![\w-])(--[\w-]+)\s*:")


def _undefined_var_warnings(text: str, html: str, tokens: Mapping[str, Any]) -> list[str]:
    """One line when a colour ``var()`` names a variable nothing defines, with a fixed fallback.

    The Dashboard tab sets :data:`HOST_THEME_VARS` for the scheme in force; a variable
    neither the tab, the theme tokens nor the page's own CSS defines always draws its
    fallback, so ``var(--my-fg, #e8e8e8)`` is pale text on the light tab whatever the
    rest of the page does. Read over the CSS and the page's inline ``style`` attributes.
    """
    scope = f"{text}\n{html}"
    defined = set(HOST_THEME_VARS) | {str(k) for k in tokens} | set(_DEFINED_VAR.findall(text))
    names: list[str] = []
    for m in _VAR.finditer(scope):
        name, fallback = m.group(1), (m.group(2) or "").strip()
        if name in defined or name in names:
            continue
        if _FIXED_COLOUR.search(_resolve(fallback, tokens)):
            names.append(name)
    if not names:
        return []
    return [UNDEFINED_VAR.format(names=", ".join(names), host=HOST_COLOUR_VARS)]
