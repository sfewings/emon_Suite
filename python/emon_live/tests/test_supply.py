"""Supply to demand: supply.Split, its attribution, and /api/energy?view=split.

No broker and no Influx. The attribution is checked on slices made by hand; the slicing
on a fake Window that answers bucket queries from tables; "now" on the retained capture.
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

import energy
import supply

SHANNSTAINABLE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "provisioning",
                              "shannstainable", "emon-ui", "derived.yml")

SPLIT = {
    "circuits": [
        {"id": "main", "label": "Main",
         "solar": {"id": "solar_main", "label": "Solar Main", "power": ["PV1", "PV3"]},
         "battery": {"id": "banks", "label": "Banks", "power": ["Bank A", "Bank B"],
                     "out": ["Bank A (out)"], "in": ["Bank A (in)"]},
         "loads": [{"id": "car", "label": "Car", "domain": "car", "power": "Car", "counter": "Car (pulse)"}],
         "house": {"id": "house_main", "label": "House Main"}},
        {"id": "office", "label": "Office",
         "solar": {"id": "solar_office", "label": "Solar Office", "power": ["PV2"]},
         "battery": {"id": "leaf_bank", "label": "Leaf bank", "power": ["Leaf"]},
         "export": {"id": "export", "label": "Export", "now": "derived/export/now"},
         "house": {"id": "house_office", "label": "House Office"}},
    ],
    "grid": {"id": "grid", "label": "Grid", "power": "Import", "counter": "Import (pulse)",
             "to": {"id": "grid_direct", "label": "Direct from grid"}},
}


class FakeWindow:
    """Bucket queries answered from {(feed, agg): [(t, v), ...]}."""

    def __init__(self, tables=None, fail=(), delay=0.0):
        self.tables = tables or {}
        self.fail = set(fail)
        self.delay = delay
        self.asked = []

    def buckets(self, name, since, until, step, agg="mean"):
        self.asked.append((name, agg))
        time.sleep(self.delay)
        if name in self.fail:
            raise RuntimeError("influx said no")
        return list(self.tables.get((name, agg), []))


@pytest.fixture
def split():
    return supply.Split(SPLIT)


@pytest.fixture
def live(state):
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    return state


def links(split, s):
    return {k: pytest.approx(v) for k, v in split.allocate(s).items()}


# --- the block ---------------------------------------------------------------------------

def test_definition_errors_are_loud():
    with pytest.raises(ValueError):
        supply.Split({"circuits": [{"label": "no id"}]})
    with pytest.raises(ValueError):
        supply.Split({"circuits": [{"id": "a", "solar": {"id": "s"}, "house": {"id": "s"}}]})
    with pytest.raises(ValueError, match="both in and out"):
        supply.Split({"circuits": [{"id": "a", "solar": {"id": "s"}, "house": {"id": "h"},
                                    "battery": {"id": "b", "power": ["x"], "out": ["y"]}}]})
    with pytest.raises(ValueError, match="needs its battery"):
        supply.Split({"circuits": [{"id": "a", "solar": {"id": "s"}, "house": {"id": "h"},
                                    "export": {"id": "e"}}]})
    assert not supply.Split(None)


def test_a_past_period_reads_counters_where_there_are_any(split):
    assert set(split.series_feeds()) == {"PV1", "PV3", "PV2", "Leaf", "Bank A (out)", "Bank A (in)",
                                         "Car (pulse)", "Import (pulse)"}


# --- the attribution ---------------------------------------------------------------------

def test_while_the_battery_charges_every_load_is_solar(split):
    got = split.allocate({"solar_main": 100.0, "banks_charge": 30.0, "car": 50.0})
    assert got == links(split, {}) | {("solar_main", "banks_charge"): 30.0,
                                      ("solar_main", "car"): 50.0,
                                      ("solar_main", "house_main"): 20.0}


def test_while_it_discharges_every_load_gets_the_same_mix(split):
    # 40 of solar and 60 from the banks feed a car of 50 and a house of 50.
    got = split.allocate({"solar_main": 40.0, "banks": 60.0, "car": 50.0})
    assert got[("solar_main", "car")] == pytest.approx(20.0)
    assert got[("banks", "car")] == pytest.approx(30.0)
    assert got[("solar_main", "house_main")] == pytest.approx(20.0)
    assert got[("banks", "house_main")] == pytest.approx(30.0)


def test_export_is_solar_only_and_never_a_battery(split):
    got = split.allocate({"solar_office": 30.0, "leaf_bank": 20.0, "export": 25.0})
    assert got[("solar_office", "export")] == pytest.approx(25.0)
    assert not any(dst == "export" and src != "solar_office" for src, dst in got)
    # The rest of the solar and the Leaf bank's discharge feed the office.
    assert got[("solar_office", "house_office")] == pytest.approx(5.0)
    assert got[("leaf_bank", "house_office")] == pytest.approx(20.0)


def test_one_bank_charging_another_is_its_own_ribbon(split):
    """At night the solar is 0: a bank that charges is charged by the others."""
    got = split.allocate({"banks": 100.0, "banks_charge": 10.0, "car": 0.0})
    assert got[("banks", "banks_charge")] == pytest.approx(10.0)
    assert got[("banks", "house_main")] == pytest.approx(90.0)


def test_demand_beyond_the_supply_is_drawn_from_unmatched(split):
    got = split.allocate({"solar_main": 30.0, "car": 50.0})
    assert got[("solar_main", "car")] == pytest.approx(30.0)
    assert got[("unmatched", "car")] == pytest.approx(20.0)
    assert ("solar_main", "house_main") not in got


def test_the_grid_feeds_only_its_own_load(split):
    got = split.allocate({"grid": 7.0, "car": 5.0})
    assert got[("grid", "grid_direct")] == 7.0
    assert got[("unmatched", "car")] == pytest.approx(5.0), "never the grid"


def test_the_circuits_never_meet(split):
    got = split.allocate({"solar_main": 10.0, "solar_office": 100.0, "car": 50.0, "export": 0.0})
    assert not any(src.endswith("office") and dst in ("car", "house_main") for src, dst in got)


# --- a past period -----------------------------------------------------------------------

def day(*minutes_values, at=0.0):
    start, _ = energy.window("today", CAPTURED_AT)
    return [(start + at + m * 60.0, v) for m, v in minutes_values]


def test_counters_rise_into_their_slices_and_a_fall_is_no_energy(split, live):
    window = FakeWindow({("Car (pulse)", "last"): day((0, 1000.0), (1, 1010.0), (2, 1005.0), (3, 1020.0))})
    doc = split.document("today", live, window, now=CAPTURED_AT)
    car = {n["id"]: n["value"] for n in doc["nodes"]}["car"]
    assert car == 10.0 + 15.0, "the relayed old value (1005) is neither a loss nor counted twice"


def test_a_watt_feed_is_held_over_a_bucket_it_missed(split, live):
    """PV1 and PV3 report every ~27 s, unevenly; a minute with only one of them must not
    count the other as 0 (it took half of Main's solar, 30 Oct 2026)."""
    window = FakeWindow({("PV1", "mean"): day((0, 600.0), (2, 600.0)),
                         ("PV3", "mean"): day((1, 600.0), (2, 600.0))})
    doc = split.document("today", live, window, now=CAPTURED_AT)
    solar = {n["id"]: n["value"] for n in doc["nodes"]}["solar_main"]
    # Minute 0: PV1 only (PV3 has not yet reported); 1 and 2: both.
    assert solar == pytest.approx((600 + 1200 + 1200) / 60.0, abs=0.1)


def test_a_watt_feed_is_not_held_past_the_integrate_gap(split, live):
    window = FakeWindow({("PV1", "mean"): day((0, 600.0)),
                         ("PV2", "mean"): day((0, 0.0), (30, 0.0))})
    doc = split.document("today", live, window, now=CAPTURED_AT)
    assert {n["id"]: n["value"] for n in doc["nodes"]}["solar_main"] == pytest.approx(10.0)


def test_export_is_solar_less_charge_less_the_night_load(split, live):
    # Two night minutes with the Leaf bank giving 300 W, then a day minute with 1 000 W of
    # solar, 100 W of it charging the Leaf bank: 1000 - 100 - 300 = 600 W for a minute.
    window = FakeWindow({("PV2", "mean"): day((0, 0.0), (1, 0.0), (2, 1000.0)),
                         ("Leaf", "mean"): day((0, 300.0), (1, 300.0), (2, -100.0))})
    doc = split.document("today", live, window, now=CAPTURED_AT)
    nodes = {n["id"]: n for n in doc["nodes"]}
    assert nodes["export"]["value"] == pytest.approx(10.0)
    assert nodes["export"]["approx"] is True
    assert nodes["leaf_bank"]["value"] == pytest.approx(10.0)
    assert nodes["leaf_bank_charge"]["value"] == pytest.approx(100 / 60.0, abs=0.1)


def test_the_night_load_starts_again_at_midnight():
    start, _ = energy.window("today", CAPTURED_AT)
    times = [start - 60.0, start + 60.0]
    out = supply._export(times, {start + 60.0: 500.0}, {start - 60.0: 400.0, start + 60.0: 0.0}, 1 / 60.0)
    assert out[start + 60.0] == pytest.approx(500 / 60.0), "yesterday's night is not today's"


def test_every_node_is_the_sum_of_its_ribbons(split, live):
    window = FakeWindow({("PV1", "mean"): day((0, 900.0), (1, 900.0)),
                         ("Bank A (out)", "last"): day((0, 0.0), (1, 5.0)),
                         ("Bank A (in)", "last"): day((0, 0.0), (1, 2.0)),
                         ("Car (pulse)", "last"): day((0, 0.0), (1, 8.0)),
                         ("Import (pulse)", "last"): day((0, 0.0), (1, 1.0))})
    doc = split.document("today", live, window, now=CAPTURED_AT)
    for n in doc["nodes"]:
        side = "source" if n["side"] == "source" else "target"
        carried = sum(l["value"] for l in doc["links"] if l[side] == n["id"])
        assert n["value"] == pytest.approx(carried, abs=0.2), n["id"]


def test_a_failed_series_is_named_and_the_rest_still_answers(split, live):
    window = FakeWindow({("PV1", "mean"): day((0, 600.0), (1, 600.0))}, fail=["Car (pulse)"])
    doc = split.document("today", live, window, now=CAPTURED_AT)
    assert doc["failed"] == ["Car (pulse)"]
    assert {n["id"]: n["value"] for n in doc["nodes"]}["solar_main"] > 0


def test_a_period_is_worked_out_once_however_many_screens_ask(split, live):
    window = FakeWindow({("PV1", "mean"): day((0, 600.0))}, delay=0.05)
    docs = []
    threads = [threading.Thread(target=lambda: docs.append(
        split.document("month", live, window, now=CAPTURED_AT))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    asked = len(window.asked)
    assert all(d is docs[0] for d in docs) and asked == len(split.series_feeds())
    split.document("month", live, window, now=CAPTURED_AT + 60)
    assert len(window.asked) == asked


# --- now ---------------------------------------------------------------------------------

def test_now_is_one_slice_of_the_live_store_in_watts(live):
    with open(SHANNSTAINABLE, encoding="utf-8") as f:
        split = energy.Sankey(yaml.safe_load(f)).split
    window = FakeWindow()
    doc = split.document("now", live, window, now=CAPTURED_AT)
    assert doc["unit"] == "W" and window.asked == []
    snap = live.store.snapshot()
    nodes = {n["id"]: n["value"] for n in doc["nodes"]}
    assert nodes["car"] == pytest.approx(max(0.0, snap["Power board / Car"].value), abs=0.1)


# --- the house view's export, the route, and the real site --------------------------------

def test_the_house_views_export_is_the_split_views(live):
    with open(SHANNSTAINABLE, encoding="utf-8") as f:
        sankey = energy.Sankey(yaml.safe_load(f))
    start, _ = energy.window("today", CAPTURED_AT)
    window = FakeWindow({("Inverter Two / pvInputPower", "mean"): [(start, 1200.0), (start + 60, 1200.0)]})
    window.counter_delta = lambda *a: None
    window.integral_wh = lambda *a: None
    house = {f["id"]: f for f in sankey.document("today", live, window, now=CAPTURED_AT)["flows"]}
    split = {n["id"]: n for n in sankey.document("today", live, window, now=CAPTURED_AT, view="split")["nodes"]}
    assert house["export"]["value"] == split["export"]["value"] == pytest.approx(40.0)
    assert house["export"]["approx"] is True


@pytest.fixture
def client(live, tmp_path, tmp_path_factory):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text(json.dumps({"title": "Home"}))
    ui = tmp_path_factory.mktemp("ui")
    (ui / "index.html").write_text("<!doctype html><title>emon</title>")
    sankey = energy.Sankey({"sankey": {"flows": [{"id": "x", "side": "source"}], "split": SPLIT}})
    return create_app(live, Site(tmp_path), ui, sankey, FakeWindow()).test_client()


def test_api_energy_split(client):
    doc = client.get("/api/energy?view=split").get_json()
    assert doc["view"] == "split" and doc["unit"] == "W"
    assert [c["id"] for c in doc["circuits"]] == ["main", "office"]
    assert client.get("/api/energy?view=split&period=today").status_code == 200
    assert client.get("/api/energy").get_json()["split"] is True
    assert client.get("/api/energy?view=sideways").status_code == 400


def test_shannstainables_split_loads_and_every_series_is_in_influx():
    with open(SHANNSTAINABLE, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    split = energy.Sankey(doc).split
    assert [c.id for c in split.circuits] == ["main", "office"]
    assert [n for n in split.series_feeds() if n not in doc["influx"]] == []
    labels = [c.house.label for c in split.circuits]
    assert labels == ["House Main", "House Office"]
