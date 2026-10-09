"""TR-13: the web UI runs on iOS 12.

The boat's iPad mini 3 stops at iOS 12 and shows the racing app full time, and the post
editor is reached from it. Safari 12 cannot parse optional chaining, so one `?.` makes
the whole script fail to load, which is what the dashboard did until this test. The
same floor as the racing app (its CLAUDE.md and DESIGN 9.8.1).

Run in the dev container (dev/README.md):
    python -m pytest event_recorder/tests/test_ios12_floor.py
"""

import re
from pathlib import Path

WEB_UI = Path(__file__).resolve().parent.parent / "web_ui"

# Syntax and built-ins that arrived after Safari 12, with the version that brought them.
JS_TOO_NEW = {
    r"\?\.(?!\d)": "optional chaining (Safari 13.1)",
    r"\?\?": "nullish coalescing (Safari 13.1)",
    r"\.replaceAll\(": "String.replaceAll (Safari 13.1)",
    r"\.matchAll\(": "String.matchAll (Safari 13)",
    r"Promise\.allSettled": "Promise.allSettled (Safari 13)",
    r"\.at\(-?\d": "Array.at (Safari 15.4)",
    r"structuredClone": "structuredClone (Safari 15.4)",
}

# Pages written before the floor was applied here, and only for flexbox gap, which
# iOS 12 ignores rather than failing on: items lose their spacing and nothing breaks.
# Both are being replaced by the event page (FR-27), so they are not worth reworking.
# Anything new is held to the full floor.
FLEX_GAP_LEGACY = {"style.css", "upload.html"}


def _without_strings_and_comments(js):
    """Blank out comments and string bodies, so `'a ?. b'` or `// x ?? y` cannot trip
    the checks. Template literals are blanked whole, including any ${} in them."""
    token = re.compile(
        r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`",
        re.S)
    # Newlines kept, so a failure reports the line it is on
    return token.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), js)


def _scripts():
    for path in sorted(WEB_UI.glob("*.js")):
        yield path.name, path.read_text(encoding="utf-8")
    for path in sorted(WEB_UI.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"<script\b[^>]*>(.*?)</script>", text, re.S)):
            yield "%s <script> %d" % (path.name, i + 1), block


def _stylesheets():
    for path in sorted(WEB_UI.glob("*.css")):
        yield path.name, path.read_text(encoding="utf-8")
    for path in sorted(WEB_UI.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"<style\b[^>]*>(.*?)</style>", text, re.S):
            yield path.name, block


def test_there_are_scripts_to_check():
    assert any(True for _ in _scripts())


def test_no_script_uses_javascript_newer_than_safari_12():
    problems = []
    for name, js in _scripts():
        code = _without_strings_and_comments(js)
        for pattern, what in JS_TOO_NEW.items():
            for match in re.finditer(pattern, code):
                line = code.count("\n", 0, match.start()) + 1
                problems.append("%s line %d: %s" % (name, line, what))
    assert not problems, "\n".join(problems)


def test_every_clamp_has_a_plain_fallback_before_it():
    """clamp() needs Safari 13.1; without a fallback iOS 12 drops the declaration."""
    for name, css in _stylesheets():
        for match in re.finditer(r"([a-z-]+):\s*clamp\(", css):
            prop = match.group(1)
            before = css[max(0, match.start() - 120):match.start()]
            assert re.search(re.escape(prop) + r":\s*[^;{}]+;\s*$", before), (
                "%s: %s: clamp(...) has no plain fallback before it" % (name, prop))


def test_no_dvh_without_a_fallback_before_it():
    """dvh needs Safari 15.4."""
    for name, css in _stylesheets():
        for match in re.finditer(r"([a-z-]+):\s*[^;{}]*\bdvh\b", css):
            prop = match.group(1)
            before = css[max(0, match.start() - 120):match.start()]
            assert re.search(re.escape(prop) + r":\s*[^;{}]+;\s*$", before), (
                "%s: %s uses dvh with no fallback before it" % (name, prop))


def test_no_flex_container_relies_on_gap():
    """Flexbox gap needs Safari 14.1. Grid gap is fine: Safari 12 has that."""
    for name, css in _stylesheets():
        if name in FLEX_GAP_LEGACY:
            continue
        stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for body in re.finditer(r"\{([^{}]*)\}", stripped):
            decls = body.group(1)
            if re.search(r"(^|[;\s])gap:", decls):
                assert "display: grid" in decls, (
                    "%s: gap on a non-grid container, which iOS 12 ignores: %s"
                    % (name, " ".join(decls.split())))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
