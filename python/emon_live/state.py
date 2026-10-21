"""What emon_live knows, and the state document pages poll (DESIGN 4.4).

No Flask and no paho here, so all of it runs in a test with injected messages and a fake
clock. mqtt_client.py feeds handle_message; app.py serves state_document.

Feeds are keyed by name, `group / name` as in emon_config, never by topic (DESIGN D2).
The names arrive in the envelopes themselves, and envelopes are retained, so subscribing
to emon/# fills the store and the catalogue at once (DESIGN 5).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time as _time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

# emon_feed comes from the source tree, not the pyemonlib wheel. It is standard library
# only and pyemonlib/__init__.py imports nothing, so this needs neither the C++ extension
# nor numpy, and an edit to emon_feed is live in a bind-mounted checkout without a wheel
# rebuild (DESIGN 4.4).
_PYEMON = Path(__file__).resolve().parents[1] / "pyEmon"
if _PYEMON.is_dir() and str(_PYEMON) not in sys.path:
    sys.path.insert(0, str(_PYEMON))

from pyemonlib import emon_feed  # noqa: E402

log = logging.getLogger(__name__)

THEMES = ("day", "night")
DEFAULT_THEME = "day"


class LiveState:
    """The store, the catalogue, the active emon_config and the theme, for one site."""

    def __init__(self, clock: Callable[[], float] = _time.time, theme: str = DEFAULT_THEME) -> None:
        self.clock = clock
        self.store = emon_feed.Store(clock=clock)
        self.catalogue = emon_feed.Catalogue()
        self.config: Optional[dict] = None
        self._theme = theme if theme in THEMES else DEFAULT_THEME
        self._lock = threading.Lock()

    @property
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: Any) -> str:
        """Server state, so every screen on a site switches together (race app DESIGN
        9.7). Anything that is not one of the two themes is ignored, and the caller is
        told the theme in force."""
        if theme in THEMES:
            with self._lock:
                self._theme = theme
        return self._theme


def handle_message(state: LiveState, topic: str, payload: Any) -> bool:
    """Route one message into the state. Returns whether it was kept.

    Never raises: a malformed reading must not take the network loop down with it, and
    the broker carries plenty that is not ours.
    """
    if topic == emon_feed.CONFIG_TOPIC:
        try:
            doc = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload)
        except (ValueError, TypeError, UnicodeDecodeError):
            return False
        if not isinstance(doc, dict):
            return False
        state.config = doc
        return True

    reading = emon_feed.parse(topic, payload, arrival=state.clock())
    if reading is None:
        return False
    state.catalogue.add(reading)
    state.store.put(reading)
    return True


def page_feeds(pages: Iterable[Any]) -> Set[str]:
    """Every feed name a set of page files refers to.

    Looks for "feed" values and {feed} placeholders in strings, anywhere in the page, so
    it does not need to know each tile type's schema (still being settled, DESIGN 6.2).
    """
    found: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "feed" and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            found.update(_placeholders(node))

    for page in pages:
        walk(page)
    return found


def _placeholders(text: str) -> List[str]:
    out, start = [], text.find("{")
    while start != -1:
        end = text.find("}", start)
        if end == -1:
            break
        out.append(text[start + 1:end].strip())
        start = text.find("{", end)
    return [name for name in out if name]


def state_document(state: LiveState, feeds: Optional[Set[str]] = None) -> Dict[str, Any]:
    """{"theme": .., "feeds": {name: {"v", "u", "age"}}} (DESIGN 4.4).

    `feeds` limits the document to the names the pages use; None means every feed known.
    A name a page asks for that has never arrived is left out, and the page shows dashes.

    Ages are worked out here, from the bridge's `t`, and browsers never see `t` (DESIGN
    4.3): a phone with a wrong clock still dims correctly. A small negative age, from the
    bridge's clock and ours disagreeing, is shown as zero.
    """
    now = state.clock()
    out: Dict[str, Dict[str, Any]] = {}
    for key, reading in state.store.snapshot().items():
        if feeds is not None and key not in feeds:
            continue
        age = None if reading.t is None else round(max(0.0, now - reading.t), 1)
        out[key] = {"v": emon_feed.plain(reading.value), "u": reading.unit, "age": age}
    return {"theme": state.theme, "feeds": out}


class Site:
    """site.json and pages/*.json from a site's emon-ui folder (DESIGN 6).

    Re-read whenever a file in it changes, so editing a page on the Pi takes effect on
    the next poll with no restart, as the rest of the checkout does.

    Missing pieces are not an error: emon_live with no site folder still serves
    /api/state?all=1, which is how a site's first page gets written. A file that does
    not parse is logged and the last good version kept, so a half-saved edit does not
    blank every screen.
    """

    def __init__(self, site_dir: Optional[os.PathLike]) -> None:
        self.root = Path(site_dir) if site_dir is not None else None
        self.site: Dict[str, Any] = {}
        self.pages: Dict[str, Any] = {}
        self.feeds: Set[str] = set()
        self._stamp: Optional[tuple] = None
        self._lock = threading.Lock()
        self.refresh()

    def _files(self) -> List[Path]:
        if self.root is None:
            return []
        files = [self.root / "site.json"] + sorted((self.root / "pages").glob("*.json"))
        return [f for f in files if f.is_file()]

    def refresh(self) -> None:
        files = self._files()
        stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files)
        with self._lock:
            if stamp == self._stamp:
                return
            site, pages = self.site, dict(self.pages)
            for f in files:
                try:
                    doc = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError) as ex:
                    log.error("%s: %s; keeping the last good version", f, ex)
                    continue
                if f.name == "site.json" and f.parent == self.root:
                    site = doc
                else:
                    pages[f.stem] = doc
            names = {f.stem for f in files if f.parent != self.root}
            pages = {k: v for k, v in pages.items() if k in names}
            self.site, self.pages, self._stamp = site, pages, stamp
            self.feeds = page_feeds(pages.values())
