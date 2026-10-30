"""Check a site's pages and derived.yml against the feeds that exist (DESIGN 9.4).

    python ui/tools/lint_pages.py provisioning/shannstainable/emon-ui --broker localhost
    python ui/tools/lint_pages.py provisioning/shannstainable/emon-ui \\
        --capture python/emon_live/tests/data/retained_shannstainable.jsonl

The feeds that exist are the names the bridge publishes, read from the broker's retained
emon/# messages (--broker, a read-only subscribe) or from a capture of them (--capture,
JSON lines of [topic, payload]). Checking against those rather than working names out
from emon_config means this needs no build of the C++ extension, and it checks the
names the decoder really produces.

Errors (exit 1):
  - a page or derived.yml names a feed that does not exist and no derived entry computes;
  - derived.yml does not load (unknown op, cycle, bad reset, bad expression);
  - an input of derived.yml has no Influx series, so a restart cannot replay it;
  - two topics publish the same name (DESIGN 5);
  - a page file is not valid JSON, or a placeholder is not closed.
Warnings: a derived feed that nothing reads, on a page or in derived.yml; a feed listed
under derived.yml's `external:` (published by Node-RED, DESIGN D5) that is not on the
broker yet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, Iterable, List, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "python", "emon_live"))

from state import emon_feed, page_feeds  # noqa: E402  (also puts pyEmon on the path)


def known_from_messages(messages: Iterable[Tuple[str, object]]) -> Tuple[Set[str], Dict[str, set]]:
    catalogue = emon_feed.Catalogue()
    for topic, payload in messages:
        if topic == emon_feed.CONFIG_TOPIC:
            continue
        reading = emon_feed.parse(topic, payload)
        if reading is not None and reading.legacy_topic is None:
            catalogue.add(reading)
    return set(catalogue.keys()), catalogue.duplicates


def capture_messages(path: str) -> List[Tuple[str, str]]:
    with open(path, encoding="utf-8") as f:
        return [tuple(json.loads(line)) for line in f if line.strip()]


def broker_messages(host: str, port: int, wait: float = 3.0) -> List[Tuple[str, bytes]]:
    import paho.mqtt.client as mqtt
    got: List[Tuple[str, bytes]] = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"lint-pages-{os.getpid()}")
    c.on_message = lambda client, u, m: got.append((m.topic, m.payload)) if m.retain else None
    c.connect(host, port, 30)
    c.subscribe("emon/#")
    c.loop_start()
    time.sleep(wait)
    c.loop_stop()
    c.disconnect()
    return got


def unclosed(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0 or depth > 1:
            return True
    return depth != 0


def strings(node) -> Iterable[str]:
    if isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)
    elif isinstance(node, str):
        yield node


def lint(site_dir: str, known: Set[str], duplicates: Dict[str, set]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    for name, topics in sorted(duplicates.items()):
        errors.append(f"name {name!r} is published on several topics: {sorted(topics)}")

    computed: Set[str] = set()
    derived_reads: Set[str] = set()
    external: Set[str] = set()
    derived_file = os.path.join(site_dir, "derived.yml")
    if os.path.isfile(derived_file):
        import yaml
        with open(derived_file, encoding="utf-8") as f:
            external = set((yaml.safe_load(f) or {}).get("external") or [])
        for name in sorted(external - known):
            warnings.append(f"{name} is published by Node-RED (external) but not on the broker yet")
        computed |= external
        import derived
        try:
            d = derived.load(derived_file)
        except Exception as ex:
            errors.append(f"derived.yml: {ex}")
            d = None
        if d is not None:
            computed |= set(d.entries)
            for entry in d.entries.values():
                for name in entry.inputs:
                    derived_reads.add(name)
                    if name not in known and name not in computed:
                        errors.append(f"derived.yml derived/{entry.id}: no feed {name!r}")
            for name in d.inputs_outside():
                if name not in d.influx and name in known:
                    errors.append(f"derived.yml: {name!r} has no influx series, so a restart cannot replay it")
        # The sankey: block names feeds the derived entries need not mention (energy.py),
        # and every feed a past window reads has to be in Influx or that ribbon is blank.
        import energy
        try:
            with open(derived_file, encoding="utf-8") as f:
                sankey = energy.Sankey(yaml.safe_load(f) or {})
        except Exception as ex:
            errors.append(f"derived.yml sankey: {ex}")
            sankey = None
        if sankey is not None:
            for flow in sankey.flows:
                for name in flow.feeds():
                    derived_reads.add(name)
                    if name not in known and name not in computed:
                        errors.append(f"derived.yml sankey/{flow.id}: no feed {name!r}")
                for name in flow.of:
                    if d is not None and name not in d.influx:
                        errors.append(f"derived.yml sankey/{flow.id}: {name!r} has no influx "
                                      f"series, so a past period cannot be answered")
            # The split view (supply.py) likewise.
            for name in sankey.split.feeds():
                derived_reads.add(name)
                if name not in known and name not in computed:
                    errors.append(f"derived.yml sankey/split: no feed {name!r}")
            for name in sankey.split.series_feeds():
                if d is not None and name not in d.influx:
                    errors.append(f"derived.yml sankey/split: {name!r} has no influx series, "
                                  f"so a past period cannot be answered")

        # The banks: block likewise (banks.py): every feed it shows must exist, and every
        # one must have a series, from the influx: map or its cells' pattern, or a past
        # period shows that reading blank.
        import banks
        try:
            with open(derived_file, encoding="utf-8") as f:
                bank_block = banks.load(yaml.safe_load(f) or {})
        except Exception as ex:
            errors.append(f"derived.yml banks: {ex}")
            bank_block = None
        if bank_block is not None:
            series = dict(d.influx) if d is not None else {}
            series.update(bank_block.series())
            for bank in bank_block.list:
                for name in bank.feeds():
                    derived_reads.add(name)
                    if name not in known and name not in computed:
                        errors.append(f"derived.yml banks/{bank.id}: no feed {name!r}")
                    if d is not None and name not in series:
                        errors.append(f"derived.yml banks/{bank.id}: {name!r} has no influx "
                                      f"series, so a past period cannot be answered")

        if d is not None:
            reads = set(d.inputs_outside()) | (set(sankey.feeds()) if sankey else set())
            reads |= set(bank_block.feeds()) if bank_block else set()
            for name in sorted(set(d.influx) - reads):
                warnings.append(f"derived.yml influx: {name!r} is mapped but nothing reads it")

    pages_dir = os.path.join(site_dir, "pages")
    used: Set[str] = set()
    for fname in sorted(os.listdir(pages_dir)) if os.path.isdir(pages_dir) else []:
        if not fname.endswith(".json"):
            continue
        path = os.path.join(pages_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                page = json.load(f)
        except ValueError as ex:
            errors.append(f"pages/{fname}: not valid JSON: {ex}")
            continue
        for text in strings(page):
            if unclosed(text):
                errors.append(f"pages/{fname}: unbalanced braces in {text!r}")
        for name in sorted(page_feeds([page])):
            used.add(name)
            if name not in known and name not in computed:
                errors.append(f"pages/{fname}: no feed {name!r}")

    for key in sorted(computed - used - derived_reads - external):
        warnings.append(f"{key} is computed but no page or derived entry reads it")
    return errors, warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("site", help="the site's emon-ui folder")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--broker", help="read retained emon/# from this broker")
    src.add_argument("--capture", help="a capture of retained messages, JSON lines")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args(argv)

    messages = capture_messages(args.capture) if args.capture else broker_messages(args.broker, args.port)
    known, duplicates = known_from_messages(messages)
    if not known:
        print("no emon/# feeds found: is the bridge publishing envelopes?", file=sys.stderr)
        return 2
    errors, warnings = lint(args.site, known, duplicates)
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    print(f"{len(known)} feeds known; {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
