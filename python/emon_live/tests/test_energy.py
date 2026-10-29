"""The Sankey's flows: energy.Sankey, the window methods, and /api/energy.

No broker and no Influx. The live view comes from the retained capture through the
LiveState; the past windows come from a fake Window that answers from tables, so the
arithmetic each method does is checked without a database.
"""

import json

import pytest

from conftest import CAPTURED_AT, retained_messages
from app import create_app
from state import Site, handle_message

import energy

BLOCK = {
    "sankey": {
        "hub": "House",
        "flows": [
            {"id": "solar", "label": "Solar", "side": "source", "domain": "solar",
             "now": "derived/solar/now",
             "window": {"method": "integral",
                        "of": ["Inverter One / pvInputPower", "Inverter Two / pvInputPower"]}},
            {"id": "grid", "label": "Grid", "side": "source", "domain": "power",
             "now": "Power board / Imported",
             "window": {"method": "counter", "of": ["Power board / Imported (pulse)"]}},
            {"id": "car", "label": "Car", "side": "load", "domain": "car",
             "now": "Power board / Car",
             "window": {"method": "counter", "of": ["Power board / Car (pulse)"]}},
            {"id": "export", "label": "Export", "side": "load", "domain": "solar",
             "now": "derived/export/now",
             "window": {"method": "expr",
                        "expr": "max(0, {Inverter Two / pvInputPower} - {import_avg})",
                        "scalars": {"import_avg": {"feed": "Power board / Imported",
                                                   "agg": "mean", "positive_only": True}}}},
        ],
        "other": {"id": "other", "label": "House", "side": "load", "domain": "other"},
    }
}


class FakeWindow:
    """What influx.Window would answer, from tables rather than queries."""

    def __init__(self, counters=None, integrals=None, scalars=None, buckets=None, fail=()):
        self.counters = counters or {}
        self.integrals = integrals or {}
        self.scalars = scalars or {}
        self._buckets = buckets or {}
        self.fail = set(fail)
        self.asked = []

    def _check(self, name):
        self.asked.append(name)
        if name in self.fail:
            raise RuntimeError("influx said no")

    def counter_delta(self, name, since, until):
        self._check(name)
        return self.counters.get(name)

    def integral_wh(self, name, since, until):
        self._check(name)
        return self.integrals.get(name)

    def aggregate(self, name, since, until, agg="mean", positive_only=False):
        self._check(name)
        return self.scalars.get(name)

    def buckets(self, name, since, until, step, agg="mean"):
        self._check(name)
        return self._buckets.get(name, [])


@pytest.fixture
def sankey():
    return energy.Sankey(BLOCK)


@pytest.fixture
def live(state):
    for topic, payload in retained_messages():
        handle_message(state, topic, payload)
    return state


def by_id(doc):
    return {f["id"]: f for f in doc["flows"]}


# --- the block ---------------------------------------------------------------------------

def test_an_empty_block_is_falsey():
    assert not energy.Sankey({})
    assert not energy.Sankey(None)


def test_a_flow_needs_an_id_and_a_known_side():
    with pytest.raises(ValueError):
        energy.Sankey({"sankey": {"flows": [{"label": "no id"}]}})
    with pytest.raises(ValueError):
        energy.Sankey({"sankey": {"flows": [{"id": "x", "side": "sideways"}]}})


def test_a_repeated_id_is_an_error():
    flow = {"id": "solar", "side": "source"}
    with pytest.raises(ValueError):
        energy.Sankey({"sankey": {"flows": [flow, dict(flow)]}})


def test_an_unknown_method_is_an_error():
    with pytest.raises(ValueError):
        energy.Sankey({"sankey": {"flows": [{"id": "x", "window": {"method": "guess"}}]}})


def test_an_expr_flow_reads_its_inputs_but_not_its_scalars(sankey):
    export = [f for f in sankey.flows if f.id == "export"][0]
    assert export.of == ["Inverter Two / pvInputPower"]
    assert "import_avg" not in export.of
    assert "Power board / Imported" in export.feeds()   # the scalar's feed, for the linter


# --- windows -----------------------------------------------------------------------------

def test_today_runs_from_midnight_to_now():
    start, end = energy.window("today", CAPTURED_AT)
    assert end == CAPTURED_AT
    assert 0 < CAPTURED_AT - start <= 86400


def test_yesterday_is_the_whole_of_the_day_before():
    midnight, _ = energy.window("today", CAPTURED_AT)
    start, end = energy.window("yesterday", CAPTURED_AT)
    assert end == midnight
    assert 86400 - 3600 <= end - start <= 86400 + 3600    # a daylight-saving day differs


def test_week_and_month_run_back_from_now():
    assert energy.window("week", CAPTURED_AT) == (CAPTURED_AT - 7 * 86400, CAPTURED_AT)
    assert energy.window("month", CAPTURED_AT) == (CAPTURED_AT - 30 * 86400, CAPTURED_AT)


# --- now ---------------------------------------------------------------------------------

def test_now_reads_the_live_store_and_asks_influx_nothing(sankey, live):
    window = FakeWindow()
    doc = sankey.document("now", live, window, now=CAPTURED_AT)
    assert doc["unit"] == "W"
    assert window.asked == []
    assert by_id(doc)["grid"]["value"] == live.store.snapshot()["Power board / Imported"].value


def test_a_flow_whose_live_feed_has_never_arrived_has_no_value(live):
    sankey = energy.Sankey({"sankey": {"flows": [
        {"id": "ghost", "side": "source", "now": "No such / feed"}]}})
    doc = sankey.document("now", live, None, now=CAPTURED_AT)
    assert by_id(doc)["ghost"]["value"] is None


# --- past periods -------------------------------------------------------------------------

def test_counter_and_integral_sum_their_series(sankey, live):
    window = FakeWindow(
        counters={"Power board / Imported (pulse)": 4000.0, "Power board / Car (pulse)": 1500.0},
        integrals={"Inverter One / pvInputPower": 6000.0, "Inverter Two / pvInputPower": 2000.0},
        buckets={"Inverter Two / pvInputPower": []})
    flows = by_id(sankey.document("today", live, window, now=CAPTURED_AT))
    assert flows["solar"]["value"] == 8000.0
    assert flows["grid"]["value"] == 4000.0
    assert flows["car"]["value"] == 1500.0


def test_other_is_the_remainder_and_the_diagram_balances(sankey, live):
    window = FakeWindow(
        counters={"Power board / Imported (pulse)": 4000.0, "Power board / Car (pulse)": 1500.0},
        integrals={"Inverter One / pvInputPower": 6000.0, "Inverter Two / pvInputPower": 2000.0},
        scalars={"Power board / Imported": 300.0},
        buckets={"Inverter Two / pvInputPower": [(0.0, 500.0), (60.0, 500.0)]})
    doc = sankey.document("today", live, window, now=CAPTURED_AT)
    flows = by_id(doc)
    sources = sum(f["value"] for f in doc["flows"] if f["side"] == "source")
    loads = sum(f["value"] for f in doc["flows"] if f["side"] == "load")
    assert flows["other"]["value"] > 0
    assert sources == pytest.approx(loads)


def test_an_expr_flow_is_integrated_over_its_buckets(sankey, live):
    # Two minutes at 500 W above a 300 W average import: 200 W for 120 s, 6.67 Wh.
    window = FakeWindow(
        scalars={"Power board / Imported": 300.0},
        buckets={"Inverter Two / pvInputPower": [(0.0, 500.0), (60.0, 500.0), (120.0, 500.0)]})
    flows = by_id(sankey.document("today", live, window, now=CAPTURED_AT))
    assert flows["export"]["value"] == round(200 * 120 / 3600.0, 1)   # values go out to 0.1
    assert flows["export"]["approx"] is True


def test_a_gap_in_the_buckets_is_not_bridged(sankey, live):
    window = FakeWindow(
        scalars={"Power board / Imported": 0.0},
        buckets={"Inverter Two / pvInputPower": [(0.0, 360.0), (60.0, 360.0),
                                                 (6000.0, 360.0), (6060.0, 360.0)]})
    flows = by_id(sankey.document("today", live, window, now=CAPTURED_AT))
    assert flows["export"]["value"] == pytest.approx(2 * 360 * 60 / 3600.0, rel=1e-6)


def test_month_buckets_are_bridged_one_bucket_at_a_time(sankey, live):
    """A month is bucketed every 900 s, wider than integrate's 5 min gap rule. Before
    this was allowed for, every month's export came out as nothing (29 Oct 2026)."""
    window = FakeWindow(
        scalars={"Power board / Imported": 0.0},
        buckets={"Inverter Two / pvInputPower": [(0.0, 400.0), (900.0, 400.0), (1800.0, 400.0),
                                                 (3600.0, 400.0)]})
    flows = by_id(sankey.document("month", live, window, now=CAPTURED_AT))
    # 0 to 1800 s at 400 W is 200 Wh; the missing bucket at 2700 s leaves 1800 to 3600 out.
    assert flows["export"]["value"] == pytest.approx(200.0, rel=1e-6)


def test_a_failed_query_leaves_the_rest_of_the_diagram(sankey, live):
    window = FakeWindow(counters={"Power board / Car (pulse)": 1500.0},
                        fail=["Power board / Imported (pulse)"])
    doc = sankey.document("today", live, window, now=CAPTURED_AT)
    assert by_id(doc)["grid"]["value"] is None
    assert doc["failed"] == ["grid"]
    assert by_id(doc)["car"]["value"] == 1500.0


def test_without_influx_every_past_flow_is_blank(sankey, live):
    doc = sankey.document("today", live, None, now=CAPTURED_AT)
    assert all(f["value"] is None for f in doc["flows"] if f["id"] != "other")
    assert set(doc["failed"]) == {"solar", "grid", "car", "export"}


def test_an_unknown_period_is_refused(sankey, live):
    with pytest.raises(ValueError):
        sankey.document("fortnight", live, None, now=CAPTURED_AT)


# --- the cache ------------------------------------------------------------------------------

def test_a_past_period_is_queried_once_for_every_screen(sankey, live):
    window = FakeWindow(counters={"Power board / Car (pulse)": 1500.0})
    sankey.document("today", live, window, now=CAPTURED_AT)
    asked = len(window.asked)
    sankey.document("today", live, window, now=CAPTURED_AT + 5)
    assert len(window.asked) == asked


def test_the_cache_expires_and_never_spans_midnight(sankey, live):
    window = FakeWindow(counters={"Power board / Car (pulse)": 1500.0})
    sankey.document("today", live, window, now=CAPTURED_AT)
    asked = len(window.asked)
    sankey.document("today", live, window, now=CAPTURED_AT + energy.TTL_S["today"] + 1)
    assert len(window.asked) > asked
    # Yesterday is held for an hour; a day later it must not be the same answer.
    doc = sankey.document("yesterday", live, window, now=CAPTURED_AT)
    later = sankey.document("yesterday", live, window, now=CAPTURED_AT + 86400)
    assert later["from"] != doc["from"]


# --- the route ------------------------------------------------------------------------------

@pytest.fixture
def client(live, tmp_path, tmp_path_factory, sankey):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text(json.dumps({"title": "Home"}))
    (tmp_path / "pages" / "energy.json").write_text(json.dumps({"tiles": [{"sankey": {}}]}))
    ui = tmp_path_factory.mktemp("ui")
    (ui / "index.html").write_text("<!doctype html><title>emon</title>")
    window = FakeWindow(counters={"Power board / Car (pulse)": 1500.0})
    return create_app(live, Site(tmp_path), ui, sankey, window).test_client()


def test_api_energy_defaults_to_now(client):
    doc = client.get("/api/energy").get_json()
    assert doc["period"] == "now" and doc["unit"] == "W"


def test_api_energy_answers_a_past_period(client):
    doc = client.get("/api/energy?period=today").get_json()
    assert doc["unit"] == "Wh" and doc["label"] == "Today"
    assert by_id(doc)["car"]["value"] == 1500.0


def test_api_energy_refuses_an_unknown_period(client):
    assert client.get("/api/energy?period=fortnight").status_code == 400


def test_api_energy_is_absent_without_a_sankey_block(live, tmp_path, tmp_path_factory):
    (tmp_path / "pages").mkdir()
    (tmp_path / "site.json").write_text("{}")
    ui = tmp_path_factory.mktemp("ui")
    client = create_app(live, Site(tmp_path), ui).test_client()
    assert client.get("/api/energy").status_code == 404


# --- the real site -----------------------------------------------------------------------

def test_shannstainables_block_loads_and_its_feeds_exist():
    import os
    import yaml
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "..", "provisioning", "shannstainable",
                        "emon-ui", "derived.yml")
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    sankey = energy.Sankey(doc)
    assert {f.id for f in sankey.flows} >= {"solar", "grid", "battery_out", "battery_in",
                                            "car", "hws", "export"}
    # Every feed a past window reads must be mapped into Influx, or that ribbon is blank.
    for flow in sankey.flows:
        for name in flow.of:
            assert name in doc["influx"], f"{flow.id} reads {name!r}, which has no series"
