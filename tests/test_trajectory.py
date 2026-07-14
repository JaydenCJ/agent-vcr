"""Trajectory assertions: the full API, including drift being caught."""

from __future__ import annotations

import pytest

from agent_vcr import Cassette, Interaction, Trajectory, VCR, assert_trajectory


def build_cassette(*calls) -> Cassette:
    cassette = Cassette(name="t")
    for seq, (tool, args) in enumerate(calls):
        cassette.add(Interaction(seq=seq, tool_name=tool, args=args, result={"ok": True}))
    return cassette


@pytest.fixture
def trajectory() -> Trajectory:
    return Trajectory(
        build_cassette(
            ("get_weather", {"city": "Tokyo"}),
            ("get_weather", {"city": "Osaka"}),
            ("suggest_outfit", {"temp_c": 31}),
        )
    )


def test_tool_sequence_property(trajectory):
    assert trajectory.tool_sequence == ["get_weather", "get_weather", "suggest_outfit"]


def test_tools_called_sequence_passes_and_chains(trajectory):
    result = trajectory.tools_called(
        ["get_weather", "get_weather", "suggest_outfit"]
    ).max_steps(3)
    assert result is trajectory


def test_tools_called_sequence_fails_on_drift(trajectory):
    with pytest.raises(AssertionError, match="expected tool sequence"):
        trajectory.tools_called(["get_weather", "suggest_outfit"])


def test_tools_called_subsequence(trajectory):
    trajectory.tools_called(["get_weather", "suggest_outfit"], mode="subsequence")
    with pytest.raises(AssertionError, match="ordered subsequence"):
        trajectory.tools_called(["suggest_outfit", "get_weather"], mode="subsequence")


def test_tools_called_rejects_unknown_mode(trajectory):
    with pytest.raises(ValueError, match="unknown mode"):
        trajectory.tools_called(["get_weather"], mode="fuzzy")


def test_tool_called_with_dict_and_callable(trajectory):
    trajectory.tool_called_with("get_weather", {"city": "Osaka"})
    trajectory.tool_called_with("suggest_outfit", lambda args: args["temp_c"] > 30)
    with pytest.raises(AssertionError, match="no call to 'get_weather'"):
        trajectory.tool_called_with("get_weather", {"city": "Sapporo"})


def test_max_steps_budget(trajectory):
    trajectory.max_steps(3)
    with pytest.raises(AssertionError, match="exceeding budget"):
        trajectory.max_steps(2)


def test_no_unexpected_tools(trajectory):
    trajectory.no_unexpected_tools(["get_weather", "suggest_outfit"])
    with pytest.raises(AssertionError, match="unexpected tools called: \\['get_weather'\\]"):
        trajectory.no_unexpected_tools(["suggest_outfit"])


def test_tool_call_count(trajectory):
    trajectory.tool_call_count("get_weather", 2)
    with pytest.raises(AssertionError, match="called 1 time"):
        trajectory.tool_call_count("get_weather", 1)


def test_failure_message_includes_numbered_trajectory_summary(trajectory):
    with pytest.raises(AssertionError) as excinfo:
        trajectory.max_steps(1)
    message = str(excinfo.value)
    assert "trajectory (3 steps):" in message
    assert "0. get_weather" in message
    assert "2. suggest_outfit" in message


def test_summary_marks_errored_calls():
    cassette = build_cassette(("send", {"to": "x"}))
    cassette.interactions[0].error = "TimeoutError: 30s"
    text = Trajectory(cassette).summary()
    assert "ERROR TimeoutError: 30s" in text


def test_empty_trajectory_summary():
    assert "empty" in Trajectory(Cassette(name="e")).summary()


def test_assert_trajectory_accepts_path_and_cassette(tmp_path):
    path = tmp_path / "c.json"
    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("ping", lambda: "pong")()
    assert assert_trajectory(str(path)).tool_sequence == ["ping"]
    assert assert_trajectory(vcr.cassette).tool_sequence == ["ping"]


def test_drift_is_caught_end_to_end(tmp_path):
    """Reverse validation: a drifted recording must turn the assertions red."""
    baseline_checks = [
        lambda t: t.tools_called(["get_weather", "suggest_outfit"]),
        lambda t: t.tool_call_count("get_weather", 1),
        lambda t: t.max_steps(2),
    ]

    good = Trajectory(
        build_cassette(
            ("get_weather", {"city": "Tokyo"}), ("suggest_outfit", {"temp_c": 31})
        )
    )
    for check in baseline_checks:
        check(good)  # all green on the baseline

    drifted = Trajectory(
        build_cassette(
            ("get_weather", {"city": "Tokyo"}),
            ("get_weather", {"city": "Tokyo"}),
            ("suggest_outfit", {"temp_c": 31}),
        )
    )
    for check in baseline_checks:
        with pytest.raises(AssertionError):
            check(drifted)  # every baseline check catches the extra call
