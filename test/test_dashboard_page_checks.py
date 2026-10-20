"""The gateway's own checks of a saved crewmate page (dashboard_page_checks).

Both come from crewmate pages seen on a pod: one bound its item list and a time to
text cells (raw ``[]`` and ISO), and one set light-only text colours, so its page was
pale on white in light mode -- with page verification skipped because the host had
no browser.
"""

from __future__ import annotations

from typing import Any

from kiro_crew.dashboard.handlers import dashboard_page_checks as checks


def _package(html: str, types: dict[str, Any], theme: dict[str, Any] | None = None) -> dict:
    return {
        "model": {"types": types},
        "view": {"html": html},
        "theme": theme if theme is not None else {"tokens": {}},
    }


_TYPES = {
    "work_items": {"type": "array", "source": {"fold": "work", "path": "items"}},
    "last_active": {"type": "timestamp", "source": {"fold": "work", "path": "last_entry_at"}},
    "headline": {"type": "text", "source": {"agentic": True}},
}


def test_a_list_and_a_time_bound_to_text_cells_are_named():
    html = (
        '<p data-dashboard-field="work_items"></p>'
        '<p data-dashboard-field="last_active"></p>'
        '<p data-dashboard-field="headline"></p>'
    )
    warnings = checks.shape_warnings(_package(html, _TYPES))
    assert len(warnings) == 2
    assert warnings[0].startswith("last_active is timestamp")
    assert warnings[1].startswith("work_items is array")
    assert checks.RENDERING["array"] in warnings[1]


def test_a_list_read_by_the_page_script_is_not_named():
    html = "<ul id=items></ul><script>window.kirocrew.subscribe('work_items', draw)</script>"
    assert checks.shape_warnings(_package(html, _TYPES)) == []


def test_the_rendering_note_covers_each_type_a_text_cell_cannot_draw():
    assert set(checks.page_rendering()) == {"array", "object", "timestamp"}


def test_light_only_text_colours_are_flagged():
    """Fixed light text and a translucent surface, the background left to the host."""
    light_only = {
        "tokens": {
            "--kc-fg": "#e8ece7",
            "--kc-fg-muted": "#95a08f",
            "--kc-surface": "rgba(255,255,255,0.04)",
        }
    }
    assert checks.theme_warnings(_package("<p></p>", {}, light_only)) == [checks.THEME_ONE_SCHEME]


def test_a_fixed_board_with_fixed_text_reads_in_both_schemes():
    """A chalkboard: dark board and chalk text, both fixed, so no warning."""
    css = ".board{background:#20262a} .board h1{color:#f4f1e8}"
    assert checks.theme_warnings(_package("<p></p>", {}, {"tokens": {}, "css": css})) == []


def test_theme_variables_or_both_schemes_are_left_alone():
    plain = {"tokens": {}, "css": ".v{color:var(--text)} .b{background:var(--bg)}"}
    assert checks.theme_warnings(_package("<p></p>", {}, plain)) == []
    both = {
        "tokens": {},
        "css": ".v{color:#222} @media (prefers-color-scheme: dark){.v{color:#eee}}",
    }
    assert checks.theme_warnings(_package("<p></p>", {}, both)) == []


def test_a_one_scheme_colour_in_the_page_style_counts_too():
    html = "<style>.v{color:#f5f5f5}</style><p class=v></p>"
    assert checks.theme_warnings(_package(html, {})) != []


def test_a_skipped_run_note_says_nothing_was_checked():
    note = checks.skipped_note("no browser on this host")
    assert "NOT run" in note and "no browser on this host" in note
    assert "no reason given" in checks.skipped_note("")


def test_a_fixed_fallback_text_colour_over_the_host_background_is_flagged():
    """A pod crewmate's page: text from var(--kc-fg, #e8e8e8), which nothing sets, on the
    host's own background, beside small dots with a fixed fill. The dots are not the
    page's background, so the pale text still reads pale on white in light mode."""
    css = (
        ".kc-wrap{color:var(--kc-fg,#e8e8e8);padding:20px}"
        ".kc-card{background:var(--kc-surface,rgba(128,128,128,.07))}"
        ".kc-dot-met{background:var(--kc-success,#4caf50)}"
    )
    html = f"<style>{css}</style><div class=kc-wrap></div>"
    theme = {"tokens": {"--kc-accent": "#4caf50"}}
    assert checks.THEME_ONE_SCHEME in checks.theme_warnings(_package(html, {}, theme))


def test_a_host_variable_with_a_fallback_follows_the_scheme():
    css = ".v{color:var(--text,#e6e6e6)} .dot{background:#4caf50}"
    assert checks.theme_warnings(_package(f"<style>{css}</style>", {})) == []


def test_a_token_the_page_reads_is_resolved_to_its_value():
    css = ".v{color:var(--my-ink)} .p{background:var(--my-paper)}"
    fixed_text_only = {"tokens": {"--my-ink": "#f4f4f4"}}
    assert checks.theme_warnings(_package(f"<style>{css}</style>", {}, fixed_text_only)) != []
    both = {"tokens": {"--my-ink": "#f4f4f4", "--my-paper": "#111111"}}
    css_on_page = ".v{color:var(--my-ink)} body{background:var(--my-paper)}"
    assert checks.theme_warnings(_package(f"<style>{css_on_page}</style>", {}, both)) == []


def test_a_fixed_page_background_with_host_text_is_flagged():
    css = "body{background:#101010} .v{font-weight:600}"
    assert checks.theme_warnings(_package(f"<style>{css}</style>", {})) == [checks.THEME_ONE_SCHEME]


def test_a_var_the_tab_never_defines_with_a_fixed_fallback_is_flagged():
    """The light-mode page that read as pale grey on white: every colour was a var()
    the tab never sets, so each one drew its dark-scheme fallback in both schemes --
    even beside a fixed accent token that made the one-scheme check look satisfied."""
    css = (
        ".kc-wrap{color:var(--kc-fg,#e8e8e8)}"
        ".kc-card{border:1px solid var(--kc-border,rgba(128,128,128,.3))}"
        ".kc-num{color:var(--text)}"
    )
    out = checks.theme_warnings(_package(f"<style>{css}</style>", {}))
    (line,) = [w for w in out if "is not a variable" in w]
    assert line.startswith("--kc-fg, --kc-border is not a variable")
    assert "--text" in line and "--bg" in line  # names the ones that work


def test_a_var_the_page_or_its_tokens_define_is_not_flagged():
    own = ":root{--kc-fg:#111} @media (prefers-color-scheme: dark){:root{--kc-fg:#eee}}"
    css = own + ".v{color:var(--kc-fg,#e8e8e8)}"
    assert checks.theme_warnings(_package(f"<style>{css}</style>", {})) == []
    tokens = {"tokens": {"--kc-fg": "var(--text)"}}
    css2 = ".v{color:var(--kc-fg,#e8e8e8)}"
    out = checks.theme_warnings(_package(f"<style>{css2}</style>", {}, tokens))
    assert not [w for w in out if "is not a variable" in w]


def test_a_host_var_with_a_fallback_and_an_unfixed_fallback_are_fine():
    css = ".v{color:var(--text,#e6e6e6)} .w{color:var(--kc-x,var(--muted))}"
    assert checks.theme_warnings(_package(f"<style>{css}</style>", {})) == []


def test_an_inline_style_var_counts_too():
    html = '<p style="color:var(--my-ink,#eeeeee)">x</p>'
    out = checks.theme_warnings(_package(html, {}))
    assert any(w.startswith("--my-ink is not a variable") for w in out)


def test_the_host_stylesheet_falls_back_per_scheme_never_to_dark_only():
    """Read before the tab's variables land (or with none): the body must not be pale
    text on a dark-only fallback."""
    from kiro_crew import dashboard_frame

    css = dashboard_frame._HOST_CSS
    assert "color: var(--text, light-dark(" in css
    assert "background: var(--bg, light-dark(" in css
    assert "color-scheme: light dark" in css


def test_the_skill_names_only_variables_the_tab_sets():
    import re
    from pathlib import Path

    skill = Path(__file__).resolve().parents[1] / "src/kiro_crew/builtin_skills/dashboard/SKILL.md"
    text = skill.read_text("utf-8")
    section = text[text.index("### A look that belongs to the work") :]
    section = section[: section.index("\n## ")]
    named = set(re.findall(r"`(--[\w-]+)`", section))
    assert {"--bg", "--text", "--card", "--border", "--accent"} <= named
    assert named <= checks.HOST_THEME_VARS
    assert "modern, polished" in section and "prefers-reduced-motion" in section


def test_rules_are_read_in_one_pass_including_nested_and_a_long_brace_free_tail():
    css = "@media (min-width: 1px) { .a { color: #fff } } body{background:#000} .b{}"
    assert checks._rules(css) == [
        (" .a ", " color: #fff "),
        (" body", "background:#000"),
        (" .b", ""),
    ]
    # An inlined source map is one long run with no brace; a backtracking pattern spent
    # time quadratic in it, which at the view cap froze the gateway loop.
    tail = "/*# sourceMappingURL=data:application/json;base64," + "Q" * 1_000_000 + " */"
    assert checks._rules(f".a{{color:#fff}}{tail}") == [(".a", "color:#fff")]
    checks.theme_warnings({"view": {"html": f"<style>{tail}</style>"}, "theme": {"css": tail}})


def test_style_bodies_and_alpha_are_read_in_one_pass():
    html = "<STYLE media=x>.a{color:#fff}</style><p></p><style>.b{}</style>"
    assert checks._style_bodies(html) == ".a{color:#fff} .b{}"
    # Many unclosed <style> tags, and a long run inside one colour function.
    checks._style_bodies("<style>" * 200_000)
    assert checks._opaque("rgba(0, 0, 0, 0.04)") is False
    assert checks._opaque("rgb(0 0 0 / 30%)") is False
    assert checks._opaque("rgba(0, 0, 0, 0.9)") is True
    assert checks._opaque("#000") is True
    assert checks._opaque("rgba(" + "0," * 200_000) is True


def test_a_var_with_a_long_run_of_spaces_is_read_in_linear_time():
    # A backtracking \s* before the fallback spent time quadratic in the spaces.
    css = ".a{color: var(--a," + " " * 400_000 + "}"
    checks.theme_warnings({"view": {"html": f"<style>{css}</style>"}, "theme": {}})
    assert checks._resolve("var(--nope,   #fff )", {}) == "#fff"
