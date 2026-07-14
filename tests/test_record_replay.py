"""Record -> replay determinism, error replay, toolkit and MCP wrapping."""

from __future__ import annotations

import itertools
import json

import pytest

from agent_vcr import VCR, ReplayedError, load_cassette
from agent_vcr.cassette import dumps, loads


def make_counter_tool():
    """A tool whose result changes on every live call (simulates a live API)."""
    counter = itertools.count(1)

    def lookup(city: str) -> dict:
        return {"city": city, "reading": next(counter)}

    return lookup


def test_record_then_replay_returns_byte_identical_results(tmp_path):
    path = tmp_path / "c.json"
    lookup = make_counter_tool()

    with VCR(str(path), mode="record") as vcr:
        tool = vcr.wrap_tool("lookup", lookup)
        recorded = [tool("Tokyo"), tool("Osaka")]

    with VCR(str(path), mode="replay-strict") as vcr:
        tool = vcr.wrap_tool("lookup", lookup)
        replayed = [tool("Tokyo"), tool("Osaka")]

    # The live tool would have produced reading=3,4 by now; replay freezes 1,2.
    assert json.dumps(recorded, sort_keys=True) == json.dumps(replayed, sort_keys=True)
    assert replayed[0]["reading"] == 1
    assert replayed[1]["reading"] == 2


def test_record_and_replay_return_the_same_normalized_value(tmp_path):
    """Record mode returns what replay will serve, not the tool's raw object.

    Otherwise an assertion written against the recording run (tuple, datetime)
    would pass locally and fail in CI where replay serves the JSON form.
    """
    from datetime import datetime

    path = tmp_path / "c.json"

    def coords(city: str):
        return {"pair": ("35.68", "139.69"), "at": datetime(2026, 7, 8, 12, 0)}

    with VCR(str(path), mode="record") as vcr:
        recorded = vcr.wrap_tool("coords", coords)("Tokyo")

    with VCR(str(path), mode="replay-strict") as vcr:
        replayed = vcr.wrap_tool("coords", coords)("Tokyo")

    assert recorded == replayed
    assert recorded["pair"] == ["35.68", "139.69"]  # tuple normalized to list
    assert isinstance(recorded["at"], str)  # datetime normalized via str()


def test_record_return_value_is_a_copy_of_the_stored_result(tmp_path):
    """Mutating the value returned in record mode must not corrupt the cassette."""
    path = tmp_path / "c.json"

    with VCR(str(path), mode="record") as vcr:
        out = vcr.wrap_tool("t", lambda: {"items": [1, 2]})()
        out["items"].append(99)

    assert load_cassette(str(path)).interactions[0].result == {"items": [1, 2]}


def test_replay_does_not_touch_the_cassette_file(tmp_path):
    path = tmp_path / "c.json"
    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("t", lambda x: x * 2)(21)
    before = path.read_bytes()
    with VCR(str(path), mode="replay-strict") as vcr:
        assert vcr.wrap_tool("t", lambda x: x * 2)(21) == 42
    assert path.read_bytes() == before


def test_cassette_serialization_roundtrip_is_stable(tmp_path):
    path = tmp_path / "c.json"
    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("t", lambda a, b: {"sum": a + b})(1, b=2)
    text = path.read_text(encoding="utf-8")
    assert dumps(loads(text)) == text


def test_positional_and_keyword_args_normalize_identically(tmp_path):
    path = tmp_path / "c.json"

    def greet(name: str, punct: str = ".") -> str:
        return f"hi {name}{punct}"

    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("greet", greet)("ada", punct="!")
    # Replay with the same call expressed purely positionally.
    with VCR(str(path), mode="replay-strict") as vcr:
        assert vcr.wrap_tool("greet", greet)("ada", "!") == "hi ada!"


def test_tool_error_is_recorded_and_replayed(tmp_path):
    path = tmp_path / "c.json"

    def boom(x: int) -> int:
        raise ValueError(f"bad input {x}")

    with VCR(str(path), mode="record") as vcr:
        tool = vcr.wrap_tool("boom", boom)
        with pytest.raises(ValueError):
            tool(7)

    cassette = load_cassette(str(path))
    assert cassette.interactions[0].error == "ValueError: bad input 7"

    def never_called(x: int) -> int:
        raise AssertionError("live tool must not run during replay")

    with VCR(str(path), mode="replay-strict") as vcr:
        tool = vcr.wrap_tool("boom", never_called)
        with pytest.raises(ReplayedError, match="bad input 7"):
            tool(7)


def test_passthrough_mode_never_writes_a_cassette(tmp_path):
    path = tmp_path / "c.json"
    calls = []

    def live(x):
        calls.append(x)
        return x + 1

    with VCR(str(path), mode="passthrough") as vcr:
        assert vcr.wrap_tool("live", live)(1) == 2
    assert calls == [1]
    assert not path.exists()


async def test_async_tool_record_and_replay(tmp_path):
    path = tmp_path / "c.json"
    counter = itertools.count(100)

    async def fetch(url: str) -> dict:
        return {"url": url, "etag": next(counter)}

    with VCR(str(path), mode="record") as vcr:
        recorded = await vcr.wrap_tool("fetch", fetch)("https://example.test/a")

    with VCR(str(path), mode="replay-strict") as vcr:
        replayed = await vcr.wrap_tool("fetch", fetch)("https://example.test/a")

    assert replayed == recorded
    assert replayed["etag"] == 100


def test_wrap_toolkit_records_each_method(tmp_path):
    path = tmp_path / "c.json"

    class Kit:
        def add(self, a: int, b: int) -> int:
            return a + b

        def upper(self, text: str) -> str:
            return text.upper()

    with VCR(str(path), mode="record") as vcr:
        kit = vcr.wrap_toolkit(Kit(), prefix="kit.")
        assert kit.add(2, 3) == 5
        assert kit.upper("ok") == "OK"

    cassette = load_cassette(str(path))
    assert [i.tool_name for i in cassette.interactions] == ["kit.add", "kit.upper"]

    with VCR(str(path), mode="replay-strict") as vcr:
        kit = vcr.wrap_toolkit(Kit(), prefix="kit.")
        assert kit.add(2, 3) == 5
        assert kit.upper("ok") == "OK"


def test_wrap_mcp_client_duck_typed_sync(tmp_path):
    path = tmp_path / "c.json"

    class FakeMCPClient:
        """Duck-typed stand-in for an MCP SDK session: call_tool(name, arguments)."""

        def __init__(self):
            self.calls = 0

        def call_tool(self, name, arguments=None):
            self.calls += 1
            return {"tool": name, "echo": arguments, "n": self.calls}

    live = FakeMCPClient()
    with VCR(str(path), mode="record") as vcr:
        client = vcr.wrap_mcp_client(live)
        recorded = client.call_tool("search", {"query": "docs"})

    with VCR(str(path), mode="replay-strict") as vcr:
        client = vcr.wrap_mcp_client(live)
        replayed = client.call_tool("search", {"query": "docs"})

    assert replayed == recorded
    assert live.calls == 1  # replay never reached the real client


async def test_wrap_mcp_client_duck_typed_async(tmp_path):
    path = tmp_path / "c.json"

    class FakeAsyncMCPClient:
        def __init__(self):
            self.calls = 0

        async def call_tool(self, name, arguments=None):
            self.calls += 1
            return {"tool": name, "echo": arguments, "n": self.calls}

    live = FakeAsyncMCPClient()
    with VCR(str(path), mode="record") as vcr:
        client = vcr.wrap_mcp_client(live)
        recorded = await client.call_tool("fetch", {"id": 5})

    with VCR(str(path), mode="replay-strict") as vcr:
        client = vcr.wrap_mcp_client(live)
        replayed = await client.call_tool("fetch", {"id": 5})

    assert replayed == recorded
    assert live.calls == 1


def test_toolkit_proxy_forwards_unwrapped_attributes(tmp_path):
    class Kit:
        banner = "kit-v1"

        def work(self, x):
            return x

    with VCR(str(tmp_path / "c.json"), mode="record") as vcr:
        kit = vcr.wrap_toolkit(Kit(), methods=["work"])
        assert kit.banner == "kit-v1"


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown mode"):
        VCR("x.json", mode="rewind")
