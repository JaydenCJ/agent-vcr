"""pytest version of the weather-agent example: record, replay, assert, drift.

These tests double as documentation: they exercise the exact flow shown in
``record_replay_demo.py`` with real assertions.
"""

from __future__ import annotations

import json

import pytest

from agent_vcr import VCR, CassetteMissError, assert_trajectory

from weather_agent import (
    PLAN_V1,
    PLAN_V2,
    ScriptedPlanner,
    make_wrapped_tools,
    run_weather_agent,
)


@pytest.fixture
def baseline_cassette(tmp_path):
    """Record the v1 agent once and return the cassette path."""
    path = tmp_path / "baseline.json"
    with VCR(str(path), mode="record") as vcr:
        run_weather_agent(ScriptedPlanner(PLAN_V1), make_wrapped_tools(vcr))
    return path


def test_record_then_strict_replay_is_byte_identical(tmp_path):
    path = tmp_path / "weather.json"
    with VCR(str(path), mode="record") as vcr:
        recorded = run_weather_agent(ScriptedPlanner(PLAN_V1), make_wrapped_tools(vcr))
    with VCR(str(path), mode="replay-strict") as vcr:
        replayed = run_weather_agent(ScriptedPlanner(PLAN_V1), make_wrapped_tools(vcr))
    assert json.dumps(recorded, sort_keys=True) == json.dumps(replayed, sort_keys=True)


def test_v1_trajectory_assertions_pass(baseline_cassette):
    (
        assert_trajectory(str(baseline_cassette))
        .tools_called(["get_weather", "suggest_outfit"])
        .tool_called_with("get_weather", {"city": "Tokyo"})
        .tool_call_count("get_weather", 1)
        .max_steps(2)
        .no_unexpected_tools(["get_weather", "suggest_outfit"])
    )


def test_v2_prompt_drift_turns_assertions_red(tmp_path):
    path = tmp_path / "v2.json"
    with VCR(str(path), mode="record") as vcr:
        run_weather_agent(ScriptedPlanner(PLAN_V2), make_wrapped_tools(vcr))
    trajectory = assert_trajectory(str(path))
    with pytest.raises(AssertionError, match="get_weather"):
        trajectory.tool_call_count("get_weather", 1)
    with pytest.raises(AssertionError, match="budget"):
        trajectory.max_steps(2)
    with pytest.raises(AssertionError):
        trajectory.tools_called(["get_weather", "suggest_outfit"])


def test_v2_agent_misses_v1_cassette_in_strict_mode(baseline_cassette):
    # The extra get_weather call has no recorded counterpart once the first
    # one is consumed, so strict replay fails loudly with a diff.
    with VCR(str(baseline_cassette), mode="replay-strict") as vcr:
        with pytest.raises(CassetteMissError):
            run_weather_agent(ScriptedPlanner(PLAN_V2), make_wrapped_tools(vcr))
