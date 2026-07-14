"""auto mode: record when the cassette is missing, replay when it exists."""

from __future__ import annotations

import os

from agent_vcr import AUTO, RECORD, REPLAY, VCR, with_cassette


def test_auto_records_on_first_run_and_replays_on_second(tmp_path):
    path = tmp_path / "auto.json"
    live_calls = []

    def tool(x: int) -> int:
        live_calls.append(x)
        return x * 10

    with VCR(str(path), mode="auto") as vcr:
        assert vcr.mode == RECORD
        assert vcr.wrap_tool("tool", tool)(3) == 30
    assert path.exists()
    assert live_calls == [3]

    with VCR(str(path), mode="auto") as vcr:
        assert vcr.mode == REPLAY
        assert vcr.wrap_tool("tool", tool)(3) == 30
    # Second run served from the cassette; the live tool was not called again.
    assert live_calls == [3]


def test_with_cassette_defaults_to_auto(tmp_path):
    assert "AGENT_VCR_MODE" not in os.environ
    vcr = with_cassette(str(tmp_path / "c.json"))
    assert vcr.requested_mode == AUTO
    assert vcr.mode == RECORD  # no cassette on disk yet


def test_with_cassette_reads_mode_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    path = tmp_path / "c.json"
    path.write_text('{"agent_vcr_version": "1", "interactions": []}')
    vcr = with_cassette(str(path))
    # auto would have replayed here; the env var forces a re-record.
    assert vcr.mode == RECORD


def test_with_cassette_explicit_mode_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_VCR_MODE", "record")
    with with_cassette(str(tmp_path / "c.json"), mode="passthrough") as vcr:
        assert vcr.mode == "passthrough"
