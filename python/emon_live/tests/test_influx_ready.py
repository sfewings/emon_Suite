"""influx.py's waiting and retrying: what a cold boot needs (influx.py's docstring).

No Influx and no clock: `Influx._ask` is replaced, and `time.sleep` counted rather than
slept, so a ten-minute wait is tested in milliseconds. Unlike test_derived.py these need
no time zone, so they run on Windows as well as on a Pi.
"""

import pytest

import influx


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Every pause taken, in order, without taking any of them: a sleep moves the clock
    the module reads instead, so a ten-minute limit is reached in milliseconds."""
    slept = []
    clock = [1_000_000.0]

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(influx._time, "sleep", sleep)
    monkeypatch.setattr(influx._time, "time", lambda: clock[0])
    return slept


class Answering:
    """An Influx that refuses `refusals` times and then answers."""

    def __init__(self, refusals: int, error=OSError("connection refused")) -> None:
        self.left, self.error, self.asked = refusals, error, []

    def __call__(self, q, timeout=None):
        self.asked.append((q, timeout))
        if self.left > 0:
            self.left -= 1
            raise self.error
        return [{"name": "measurements", "values": [["power"]]}]


def client(ask, monkeypatch):
    store = influx.Influx("http://influxdb:8086")
    monkeypatch.setattr(store, "_ask", ask)
    return store


def test_wait_ready_waits_out_a_database_still_opening(monkeypatch, no_sleeping):
    ask = Answering(refusals=4)
    assert client(ask, monkeypatch).wait_ready() is True
    assert len(ask.asked) == 5, "four refusals, then the answer"
    assert no_sleeping == list(influx.READY_BACKOFF_S[:4]), "backing off between probes"


def test_the_readiness_probe_is_metadata_only_and_quick(monkeypatch, no_sleeping):
    """The module's rule: never an unbounded query against a database with data since
    2019. SHOW MEASUREMENTS reads no points."""
    ask = Answering(refusals=0)
    client(ask, monkeypatch).wait_ready()
    q, timeout = ask.asked[0]
    assert "SHOW MEASUREMENTS" in q and "SELECT" not in q
    assert timeout == influx.READY_PROBE_TIMEOUT_S


def test_wait_ready_gives_up_so_emon_live_still_starts(monkeypatch, no_sleeping):
    """Ten minutes is a cold boot's shard opening; past that, serving live values beats
    not serving at all."""
    never = Answering(refusals=10 ** 6)
    assert client(never, monkeypatch).wait_ready(limit=20.0) is False
    assert sum(no_sleeping) <= 20.0, "it waited no longer than it was told to"


def test_wait_ready_told_not_to_wait_does_not(monkeypatch, no_sleeping):
    assert client(Answering(refusals=1), monkeypatch).wait_ready(limit=0.0) is False
    assert no_sleeping == []


def test_a_query_dropped_by_the_transport_is_retried(monkeypatch, no_sleeping):
    """Influx restarting under a seeding query loses that feed's whole day; one retry
    keeps it."""
    ask = Answering(refusals=1)
    assert client(ask, monkeypatch).query_series("SELECT value FROM x") != []
    assert len(ask.asked) == 2
    assert no_sleeping == [influx.QUERY_RETRY_S[0]]


def test_a_query_influx_rejects_is_not_retried(monkeypatch, no_sleeping):
    """A malformed query would be rejected again; only the transport is worth retrying."""
    ask = Answering(refusals=1, error=RuntimeError("error parsing query"))
    with pytest.raises(RuntimeError):
        client(ask, monkeypatch).query_series("SELECT nonsense")
    assert len(ask.asked) == 1
    assert no_sleeping == []


def test_a_query_that_never_comes_back_still_raises(monkeypatch, no_sleeping):
    """So seed() logs that feed and carries on, as it always has."""
    ask = Answering(refusals=10 ** 6)
    with pytest.raises(OSError):
        client(ask, monkeypatch).query_series("SELECT value FROM x")
    assert len(ask.asked) == influx.QUERY_ATTEMPTS
