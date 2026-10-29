"""Battery banks: banks.Banks, its two views, and /api/banks.

No broker and no Influx. "now" comes from the retained capture through the LiveState,
which holds every BMS cell and the LiFePO shunts; a past period comes from a fake
Window that answers from tables.
"""

import json
import os
import threading
import time

import pytest
import yaml

from conftest import CAPTURED_AT, retained_messages
from app import create_app
from state import Site, handle_message

import banks

SHANNSTAINABLE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "provisioning",
                              "shannstainable", "emon-ui", "derived.yml")

BLOCK = {"banks": {"list": [
    {"id": "bank1", "title": "Bank 1", "note": "LiFePO4", "soc": "BMS - Bank 1 / batterySoC",
     "cells": {"feed": "BMS - Bank 1 / cellVoltage {n}", "influx": "voltage bms/cellVoltage/0/{n}",
               "count": 16, "decimals": 3, "spread": 0.05},
     "values": [{"label": "Voltage", "feed": "BMS - Bank 1 / batteryVoltage", "decimals": 2},
                {"label": "Power", "feed": "LiFePO monitor 5 / Battery-280Ah", "decimals": 0}],
     "energy": {"in": "LiFePO monitor 5 / Battery-280Ah (pulseOut)",
                "out": "LiFePO monitor 5 / Battery-280Ah (pulseIn)"}},
    {"id": "leaf", "title": "Leaf bank", "soc": "BMS - Leaf Bank / batterySoC",
     "cells": {"feed": "BMS - Leaf Bank / cellVoltage {n}", "count": 16},
     "values": [{"label": "Power", "feed": "BMS - Leaf Bank / power", "scale": -1}]},
    {"id": "bank3", "title": "Bank 3",
     "cells": {"list": [{"feed": "Main battery monitor / B2-1", "label": "S1"},
                        {"feed": "Main battery monitor / B2-2", "label": "S2"}],
               "warn_abs": 1.0}},
]}}


class FakeWindow:
    def __init__(self, stats=None, counters=None, fail=(), delay=0.0):
        self._stats = stats or {}
        self.counters = counters or {}
        self.fail = set(fail)
        self.delay = delay
        self.calls = 0

    def stats(self, name, since, until, valid=None):
        self.calls += 1
        self.valid = getattr(self, "valid", {})
        self.valid[name] = valid
        if name in self.fail:
            raise RuntimeError("influx said no")
        return self._stats.get(name)

    def stats_many(self, names, since, until, valid=None):
        self.calls += 1
        self.cells_valid = valid
        time.sleep(self.delay)
        if any(n in self.fail for n in names):
            raise RuntimeError("influx said no")
        return {n: self._stats[n] for n in names if n in self._stats}

    def counter_delta(self, name, since, until):
        self.calls += 1
        return self.counters.get(name)


def s(lo, hi, mean=None, last=None):
    return {"min": lo, "max": hi, "mean": (lo + hi) / 2 if mean is None else mean,
            "last": hi if last is None else last}


@pytest.fixture
def block():
    return banks.Banks(BLOCK)


@pytest.fixture
def live(state):
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    return state


def by_id(doc):
    return {b["id"]: b for b in doc["banks"]}


# --- the block ---------------------------------------------------------------------------

def test_cells_expand_from_a_pattern_with_their_series(block):
    b = block.list[0]
    assert [c.label for c in b.cells][:3] == ["1", "2", "3"] and len(b.cells) == 16
    assert b.cells[15].feed == "BMS - Bank 1 / cellVoltage 15"
    assert block.series()["BMS - Bank 1 / cellVoltage 15"] == ("voltage", "bms/cellVoltage/0/15")


def test_definition_errors_are_loud():
    with pytest.raises(ValueError):
        banks.Banks({"banks": {"list": [{"title": "no id"}]}})
    with pytest.raises(ValueError):
        banks.Banks({"banks": {"list": [{"id": "a"}, {"id": "a"}]}})
    with pytest.raises(ValueError):
        banks.Banks({"banks": {"list": [{"id": "a", "cells": {"feed": "X {n}"}}]}})
    assert not banks.Banks({})


# --- now ---------------------------------------------------------------------------------

def test_now_reads_the_live_cells_and_marks_lowest_highest_and_spread(block, live):
    doc = block.document("now", live)
    b = by_id(doc)["bank1"]
    cells = [c["now"] for c in b["cells"]["items"]]
    assert all(isinstance(v, float) for v in cells)
    assert b["cells"]["low"]["value"] == min(cells) and b["cells"]["high"]["value"] == max(cells)
    assert b["cells"]["spread"] == pytest.approx(max(cells) - min(cells))
    assert b["soc"]["now"] == live.store.get("BMS - Bank 1 / batterySoC").value
    assert b["energy"] is None, "now has no energy; it is a reading of power"


def test_scale_minus_one_turns_a_bms_power_round(block, live):
    raw = live.store.get("BMS - Leaf Bank / power").value
    leaf = by_id(block.document("now", live))["leaf"]
    assert leaf["values"][0]["now"] == pytest.approx(-raw)


def test_now_asks_influx_nothing(block, live):
    window = FakeWindow()
    block.document("now", live, window)
    assert window.calls == 0


# --- a past period -----------------------------------------------------------------------

def test_a_period_gives_each_cell_its_range_and_names_the_extremes(block, live):
    stats = {f"BMS - Bank 1 / cellVoltage {n}": s(3.20, 3.40) for n in range(16)}
    stats["BMS - Bank 1 / cellVoltage 6"] = s(3.15, 3.41)   # sags lowest
    stats["BMS - Bank 1 / cellVoltage 11"] = s(3.21, 3.49)  # peaks highest
    stats["BMS - Bank 1 / batterySoC"] = s(40, 98, last=60)
    stats["LiFePO monitor 5 / Battery-280Ah"] = s(-2500, 1800, last=900)
    window = FakeWindow(stats, counters={"LiFePO monitor 5 / Battery-280Ah (pulseOut)": 4200.0,
                                         "LiFePO monitor 5 / Battery-280Ah (pulseIn)": 3900.0})
    b = by_id(block.document("today", live, window, now=CAPTURED_AT))["bank1"]
    assert b["cells"]["low"] == {"label": "7", "value": 3.15}
    assert b["cells"]["high"] == {"label": "12", "value": 3.49}
    assert b["cells"]["items"][6]["min"] == 3.15 and b["cells"]["items"][6]["now"] == 3.41
    assert b["soc"] == {"now": 60, "min": 40, "max": 98}
    power = b["values"][1]
    assert (power["min"], power["max"], power["now"]) == (-2500, 1800, 900)
    assert b["energy"] == {"in": 4200.0, "out": 3900.0}


def test_a_negative_scale_swaps_the_ends_of_a_range(block, live):
    window = FakeWindow({"BMS - Leaf Bank / power": s(-300, 50, last=20)})
    leaf = by_id(block.document("week", live, window, now=CAPTURED_AT))["leaf"]
    assert (leaf["values"][0]["min"], leaf["values"][0]["max"], leaf["values"][0]["now"]) == (-50, 300, -20)


def test_a_failed_query_blanks_that_part_and_says_so(block, live):
    window = FakeWindow({"BMS - Bank 1 / batteryVoltage": s(51, 54)},
                        fail=["BMS - Bank 1 / cellVoltage 0", "LiFePO monitor 5 / Battery-280Ah"])
    doc = block.document("yesterday", live, window, now=CAPTURED_AT)
    b = by_id(doc)["bank1"]
    assert "bank1/cells" in doc["failed"] and "bank1/Power" in doc["failed"]
    assert b["cells"]["low"] is None
    assert b["values"][0]["min"] == 51, "the rest of the bank still answers"


def test_bank3_carries_its_absolute_warning(block, live):
    b = by_id(block.document("now", live))["bank3"]
    assert b["cells"]["warn_abs"] == 1.0 and [c["label"] for c in b["cells"]["items"]] == ["S1", "S2"]


def test_a_period_is_queried_once_however_many_screens_ask(block, live):
    stats = {f"BMS - Bank 1 / cellVoltage {n}": s(3.2, 3.4) for n in range(16)}
    window = FakeWindow(stats, delay=0.2)
    docs = []
    threads = [threading.Thread(target=lambda: docs.append(
        block.document("month", live, window, now=CAPTURED_AT))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    calls = window.calls
    assert len(docs) == 4 and all(d is docs[0] for d in docs), "every screen got the one answer"
    block.document("month", live, window, now=CAPTURED_AT + 60)
    assert window.calls == calls, "and the cache answers the next minute"


def test_an_unknown_period_is_refused(block, live):
    with pytest.raises(ValueError):
        block.document("fortnight", live)


# --- the route and the real site ---------------------------------------------------------

@pytest.fixture
def client(live, tmp_path, tmp_path_factory, block):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text(json.dumps({"title": "Home"}))
    ui = tmp_path_factory.mktemp("ui")
    (ui / "index.html").write_text("<!doctype html><title>emon</title>")
    return create_app(live, Site(tmp_path), ui, None, FakeWindow(), block).test_client()


def test_api_banks(client):
    doc = client.get("/api/banks").get_json()
    assert doc["period"] == "now" and [b["id"] for b in doc["banks"]] == ["bank1", "leaf", "bank3"]
    assert client.get("/api/banks?period=today").status_code == 200
    assert client.get("/api/banks?period=fortnight").status_code == 400


def test_api_banks_is_absent_without_a_block(live, tmp_path, tmp_path_factory):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text("{}")
    client = create_app(live, Site(tmp_path), tmp_path_factory.mktemp("ui")).test_client()
    assert client.get("/api/banks").status_code == 404


def test_shannstainables_banks_load_and_every_feed_is_in_the_capture(live):
    with open(SHANNSTAINABLE, encoding="utf-8") as f:
        block = banks.load(yaml.safe_load(f))
    assert [b.id for b in block.list] == ["bank1", "bank2", "bank3", "leaf"]
    known = set(live.store.snapshot())
    assert [n for n in block.feeds() if n not in known] == []
    doc = block.document("now", live)
    assert all(b["cells"]["low"] is not None for b in doc["banks"])


def test_soc_outside_0_to_100_is_a_fault_not_a_reading(block, live):
    """The Leaf BMS sent 610 and 354 among its 98s (29 Oct 2026)."""
    from pyemonlib import emon_feed
    live.store.put(emon_feed.Reading(node="bms", sub=2, field="batterySoC", value=610.0, unit="%",
                                     group="BMS - Leaf Bank", name="batterySoC", t=CAPTURED_AT))
    assert by_id(block.document("now", live))["leaf"]["soc"]["now"] is None
    window = FakeWindow({"BMS - Leaf Bank / batterySoC": s(79, 99)})
    block.document("today", live, window, now=CAPTURED_AT)
    assert window.valid["BMS - Leaf Bank / batterySoC"] == (0.0, 100.0), "and Influx is asked to leave it out"


def test_a_value_range_must_be_two_numbers():
    with pytest.raises(ValueError):
        banks.Banks({"banks": {"list": [{"id": "a", "values": [{"feed": "x", "range": [0]}]}]}})


def test_a_cells_range_reaches_influx_and_the_live_view(live):
    block = banks.Banks({"banks": {"list": [{"id": "bank3", "cells": {
        "list": [{"feed": "Main battery monitor / B2-1", "label": "S1"}], "range": [-10, 10]}}]}})
    window = FakeWindow()
    block.document("week", live, window, now=CAPTURED_AT)
    assert window.cells_valid == (-10.0, 10.0)
    from pyemonlib import emon_feed
    live.store.put(emon_feed.Reading(node="bat", sub=0, field="voltage", idx=8, value=107.49, unit="V",
                                     group="Main battery monitor", name="B2-1", t=CAPTURED_AT))
    assert block.document("now", live)["banks"][0]["cells"]["items"][0]["now"] is None
