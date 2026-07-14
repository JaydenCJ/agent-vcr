"""The pytest plugin: agent_vcr fixture, AGENT_VCR_MODE switching, markers."""

from __future__ import annotations

TEST_FILE = """
    import itertools

    counter = itertools.count(1)

    def live_tool(city):
        return {"city": city, "reading": next(counter)}

    def test_agent(agent_vcr):
        tool = agent_vcr.wrap_tool("live_tool", live_tool)
        assert tool("Tokyo") == {"city": "Tokyo", "reading": 1}
"""


def test_fixture_records_cassette_next_to_the_test(pytester, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    pytester.makepyfile(TEST_FILE)
    result = pytester.runpytest("-p", "no:asyncio")
    result.assert_outcomes(passed=1)
    cassette = pytester.path / "cassettes" / "test_agent.json"
    assert cassette.exists()
    assert '"tool_name": "live_tool"' in cassette.read_text()


def test_fixture_replays_in_strict_mode_without_hitting_live_tools(pytester, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    pytester.makepyfile(TEST_FILE)
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)

    # Second run in strict replay: the live counter would yield reading=1
    # again in a fresh process, so replace the tool with one that must not run.
    monkeypatch.setenv("AGENT_VCR_MODE", "replay-strict")
    pytester.makepyfile(
        """
        def exploding_tool(city):
            raise RuntimeError("live tool must not be called during replay")

        def test_agent(agent_vcr):
            tool = agent_vcr.wrap_tool("live_tool", exploding_tool)
            assert tool("Tokyo") == {"city": "Tokyo", "reading": 1}
        """
    )
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)


def test_fixture_defaults_to_auto_mode_when_env_is_unset(pytester, monkeypatch):
    monkeypatch.delenv("AGENT_VCR_MODE", raising=False)
    pytester.makepyfile(
        """
        def test_agent(agent_vcr):
            assert agent_vcr.requested_mode == "auto"
            assert agent_vcr.mode == "record"  # no cassette yet
            agent_vcr.wrap_tool("t", lambda: "ok")()
        """
    )
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)
    assert (pytester.path / "cassettes" / "test_agent.json").exists()


def test_strict_replay_miss_fails_the_test_with_a_diff(pytester, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    pytester.makepyfile(TEST_FILE)
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)

    monkeypatch.setenv("AGENT_VCR_MODE", "replay-strict")
    pytester.makepyfile(
        """
        def live_tool(city):
            return {}

        def test_agent(agent_vcr):
            tool = agent_vcr.wrap_tool("live_tool", live_tool)
            tool("Osaka")  # drifted argument -> CassetteMissError
        """
    )
    result = pytester.runpytest("-p", "no:asyncio")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*CassetteMissError*"])


def test_failed_test_does_not_persist_a_cassette(pytester, monkeypatch):
    """A failing first run in auto mode must not poison later replays.

    If the fixture saved unconditionally, the broken partial recording would be
    silently replayed on the next auto run even after the agent was fixed.
    """
    monkeypatch.delenv("AGENT_VCR_MODE", raising=False)
    pytester.makepyfile(
        """
        def test_agent(agent_vcr):
            agent_vcr.wrap_tool("t", lambda: "partial")()
            assert False, "agent is broken on the first recording run"
        """
    )
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(failed=1)
    assert not (pytester.path / "cassettes" / "test_agent.json").exists()

    # Once the test passes, the same auto run records a fresh, good cassette.
    pytester.makepyfile(
        """
        def test_agent(agent_vcr):
            assert agent_vcr.mode == "record"  # still no cassette on disk
            assert agent_vcr.wrap_tool("t", lambda: "fixed")() == "fixed"
        """
    )
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)
    cassette = pytester.path / "cassettes" / "test_agent.json"
    assert cassette.exists()
    assert '"fixed"' in cassette.read_text()
    assert '"partial"' not in cassette.read_text()


def test_marker_overrides_mode_and_cassette_path(pytester, monkeypatch):
    monkeypatch.delenv("AGENT_VCR_MODE", raising=False)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.agent_vcr(mode="passthrough", cassette="custom/place.json")
        def test_agent(agent_vcr):
            assert agent_vcr.mode == "passthrough"
            assert agent_vcr.cassette_path == "custom/place.json"
            assert agent_vcr.wrap_tool("t", lambda: 41)() == 41
        """
    )
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)
    # Passthrough never writes cassettes.
    assert not (pytester.path / "custom" / "place.json").exists()


def test_cassette_dir_is_configurable_via_ini(pytester, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    pytester.makeini(
        """
        [pytest]
        agent_vcr_cassette_dir = tapes
        """
    )
    pytester.makepyfile(TEST_FILE)
    pytester.runpytest("-p", "no:asyncio").assert_outcomes(passed=1)
    assert (pytester.path / "tapes" / "test_agent.json").exists()
