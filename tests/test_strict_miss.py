"""replay-strict miss behavior: CassetteMissError, its diff, lenient fallback."""

from __future__ import annotations

import warnings

import pytest

from agent_vcr import AgentVCRWarning, CassetteMissError, CassetteNotFoundError, VCR


def record_weather(path):
    def get_weather(city: str) -> dict:
        return {"city": city, "temp_c": 20}

    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("get_weather", get_weather)("Tokyo")


def test_strict_replay_raises_on_argument_drift_with_diff(tmp_path):
    path = tmp_path / "c.json"
    record_weather(path)

    with VCR(str(path), mode="replay-strict") as vcr:
        tool = vcr.wrap_tool("get_weather", lambda city: None)
        with pytest.raises(CassetteMissError) as excinfo:
            tool("Osaka")

    err = excinfo.value
    assert err.tool_name == "get_weather"
    assert err.actual_args == {"city": "Osaka"}
    assert err.candidates == [{"city": "Tokyo"}]
    message = str(err)
    # The diff shows expected vs actual and flags the mismatching argument.
    assert "expected (recorded)" in message
    assert '"Tokyo"' in message and '"Osaka"' in message
    assert "!!" in message


def test_strict_replay_raises_on_unknown_tool_listing_recorded_tools(tmp_path):
    path = tmp_path / "c.json"
    record_weather(path)

    with VCR(str(path), mode="replay-strict") as vcr:
        tool = vcr.wrap_tool("send_email", lambda to: None)
        with pytest.raises(CassetteMissError) as excinfo:
            tool("a@example.test")
    assert "no interaction recorded for tool 'send_email'" in str(excinfo.value)
    assert "get_weather" in str(excinfo.value)


def test_strict_replay_fails_fast_when_cassette_file_is_missing(tmp_path):
    """A missing file is CassetteNotFoundError, distinguishable from drift."""
    path = str(tmp_path / "nope.json")
    with pytest.raises(CassetteNotFoundError, match="cassette not found") as excinfo:
        VCR(path, mode="replay-strict")
    assert excinfo.value.cassette_path == path
    # Backward compatible: it is still a CassetteMissError subclass.
    assert isinstance(excinfo.value, CassetteMissError)


def test_lenient_replay_tolerates_drift_with_a_warning(tmp_path):
    path = tmp_path / "c.json"
    record_weather(path)

    with VCR(str(path), mode="replay") as vcr:
        tool = vcr.wrap_tool("get_weather", lambda city: None)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = tool("Osaka")  # args drifted; lenient serves the recording
    assert result == {"city": "Tokyo", "temp_c": 20}
    assert any(issubclass(w.category, AgentVCRWarning) for w in caught)
    assert any("argument drift" in str(w.message) for w in caught)
    assert vcr.warnings  # drift is also kept on the instance for reporting


def test_lenient_replay_still_raises_when_nothing_left_to_serve(tmp_path):
    path = tmp_path / "c.json"
    record_weather(path)

    with VCR(str(path), mode="replay") as vcr:
        tool = vcr.wrap_tool("get_weather", lambda city: None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tool("Tokyo")
            with pytest.raises(CassetteMissError):
                tool("Tokyo")  # cassette only holds one interaction


def test_unused_interactions_reports_leftovers(tmp_path):
    path = tmp_path / "c.json"

    def get_weather(city: str) -> dict:
        return {"city": city}

    with VCR(str(path), mode="record") as vcr:
        tool = vcr.wrap_tool("get_weather", get_weather)
        tool("Tokyo")
        tool("Osaka")

    with VCR(str(path), mode="replay-strict") as vcr:
        vcr.wrap_tool("get_weather", get_weather)("Tokyo")
        leftover = vcr.unused_interactions()
    assert [i.args for i in leftover] == [{"city": "Osaka"}]
