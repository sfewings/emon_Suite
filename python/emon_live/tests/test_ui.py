"""ui/: the page linter, and static checks that hold the engine to the iOS 12 floor.

The iOS 12 failures are invisible on a development machine and each one reached the boat
once (enchantee_racing/CLAUDE.md), so they are pinned here rather than remembered.
"""

import json
import os
import re
import sys

import pytest

from conftest import RETAINED

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UI = os.path.join(REPO, "ui")
SITE = os.path.join(REPO, "provisioning", "shannstainable", "emon-ui")
sys.path.insert(0, os.path.join(UI, "tools"))

import lint_pages  # noqa: E402


def known():
    return lint_pages.known_from_messages(lint_pages.capture_messages(RETAINED))


def test_shannstainable_pages_and_derived_lint_clean():
    names, duplicates = known()
    errors, warnings = lint_pages.lint(SITE, names, duplicates)
    assert errors == []
    # The capture predates Node-RED publishing its results (PLAN 2d), so those, and only
    # those, are reported as not on the broker yet.
    assert all("(external) but not on the broker yet" in w for w in warnings), warnings


def test_lint_catches_a_misspelt_feed_and_a_missing_series(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p.json").write_text(json.dumps({"tiles": [
        {"values": [{"feed": "Power board / Consumd"}]},
        {"lines": ["{Power board / Consumed|0} W {unclosed"]},
        {"values": [{"feed": "derived/nothing/here"}]},
    ]}))
    (tmp_path / "derived.yml").write_text(
        "influx: {}\nderived:\n  - {id: a, op: daily_delta, feed: Power board / Car (pulse)}\n")
    names, duplicates = known()
    errors, _ = lint_pages.lint(str(tmp_path), names, duplicates)
    text = "\n".join(errors)
    assert "'Power board / Consumd'" in text
    assert "'derived/nothing/here'" in text
    assert "unbalanced braces" in text
    assert "has no influx series" in text


def test_lint_reports_a_broken_derived_file(tmp_path):
    (tmp_path / "derived.yml").write_text("derived:\n  - {id: a, op: daily_delta, feed: x, reset: 9am}\n")
    errors, _ = lint_pages.lint(str(tmp_path), *known())
    assert errors and errors[0].startswith("derived.yml:")


def _sources(ext):
    for root, _, files in os.walk(UI):
        if os.sep + "tools" in root:
            continue
        for f in files:
            if f.endswith(ext):
                path = os.path.join(root, f)
                with open(path, encoding="utf-8") as fh:
                    # Comments stripped: they may name what is forbidden.
                    text = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)
                    if ext == ".js":
                        text = re.sub(r"(^|\s)//.*$", "", text, flags=re.M)
                yield os.path.relpath(path, REPO), text


@pytest.mark.parametrize("pattern, why", [
    (r"=>", "arrow functions are fine on iOS 12 but the front end is var and function"),
    (r"\?\.", "optional chaining needs Safari 13.1"),
    (r"\?\?", "nullish coalescing needs Safari 13.1"),
    (r"\b(let|const)\s", "var, to match the race app"),
    (r"\bclass\s+\w+\s*\{", "no classes, to match the race app"),
    (r"`", "no template literals, to match the race app"),
    (r"""fetch\(\s*["']/""", "fetch must be relative, from location.pathname"),
])
def test_engine_js_keeps_to_the_floor(pattern, why):
    for path, text in _sources(".js"):
        assert not re.search(pattern, text), f"{path}: {why}"


@pytest.mark.parametrize("pattern, why", [
    (r"\bclamp\(", "clamp() needs Safari 13.1"),
    (r"color-mix\(", "color-mix() needs Safari 16.2"),
    (r"\b\d+dvh\b", "dvh needs Safari 15.4"),
    (r"-webkit-overflow-scrolling", "stops content painting on iOS 12"),
    (r"@container", "container queries need Safari 16"),
])
def test_css_keeps_to_the_floor(pattern, why):
    for path, text in _sources(".css"):
        assert not re.search(pattern, text), f"{path}: {why}"


def test_no_flexbox_gap():
    """gap is fine on a grid, but on a flex container needs Safari 14.1."""
    for path, text in _sources(".css"):
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            if "display: flex" in body or "display:flex" in body:
                assert not re.search(r"(^|;)\s*(row-|column-)?gap\s*:", body), f"{path}: {selector.strip()}"


def test_every_svg_gets_a_width_and_height():
    """iOS 12 sizes an SVG with only a viewBox at 300 px wide."""
    for path, text in _sources(".js"):
        if 'createElementNS(NS, "svg")' in text:
            assert re.search(r'setAttribute\("width"', text) and re.search(r'setAttribute\("height"', text), path


def test_index_uses_only_relative_urls():
    with open(os.path.join(UI, "index.html"), encoding="utf-8") as f:
        html = f.read()
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not url.startswith(("/", "http:", "https:")), url


def test_lint_knows_external_feeds_and_warns_until_they_arrive(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p.json").write_text(json.dumps({"tiles": [{"lines": ["{derived/dog/lastFed|time}"]}]}))
    (tmp_path / "derived.yml").write_text("external: [derived/dog/lastFed]\n")
    names, duplicates = known()
    errors, warnings = lint_pages.lint(str(tmp_path), names, duplicates)
    assert errors == [] and len(warnings) == 1
    errors, warnings = lint_pages.lint(str(tmp_path), names | {"derived/dog/lastFed"}, duplicates)
    assert errors == [] and warnings == []
