"""CLI: ls / show / diff behavior, exit codes, --help/--version consistency."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import agent_vcr
from agent_vcr import VCR
from agent_vcr.cli import EXIT_DRIFT, EXIT_ERROR, EXIT_OK, main


@pytest.fixture
def cassette_pair(tmp_path):
    """Record a baseline cassette and a drifted one (extra call, changed arg)."""
    baseline = tmp_path / "baseline.json"
    drifted = tmp_path / "drifted.json"

    def get_weather(city: str) -> dict:
        return {"city": city, "temp_c": 20}

    def send_alert(level: str) -> str:
        return "sent"

    with VCR(str(baseline), mode="record") as vcr:
        vcr.wrap_tool("get_weather", get_weather)("Tokyo")
    with VCR(str(drifted), mode="record") as vcr:
        vcr.wrap_tool("get_weather", get_weather)("Osaka")
        vcr.wrap_tool("send_alert", send_alert)("high")
    return baseline, drifted


def test_ls_lists_cassettes_with_step_counts(cassette_pair, tmp_path, capsys):
    assert main(["ls", str(tmp_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "STEPS" in out
    assert "baseline.json" in out and "drifted.json" in out
    baseline_row = next(l for l in out.splitlines() if l.startswith("baseline.json"))
    assert " 1 " in baseline_row + " "
    drifted_row = next(l for l in out.splitlines() if l.startswith("drifted.json"))
    assert " 2 " in drifted_row + " "


def test_ls_skips_non_cassette_json_without_crashing(tmp_path, capsys):
    (tmp_path / "other.json").write_text('{"hello": 1}')
    assert main(["ls", str(tmp_path)]) == EXIT_OK
    assert "skipped" in capsys.readouterr().out


def test_ls_on_missing_directory_errors_cleanly(tmp_path, capsys):
    assert main(["ls", str(tmp_path / "nope")]) == EXIT_ERROR
    assert "not a directory" in capsys.readouterr().err


def test_show_prints_trajectory(cassette_pair, capsys):
    baseline, _ = cassette_pair
    assert main(["show", str(baseline)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "cassette: baseline" in out
    assert "format version: 1" in out
    assert "get_weather" in out and '"Tokyo"' in out
    assert '{"city": "Tokyo", "temp_c": 20}' in out


def test_show_missing_file_errors_cleanly(tmp_path, capsys):
    assert main(["show", str(tmp_path / "nope.json")]) == EXIT_ERROR
    assert "no such cassette" in capsys.readouterr().err


def test_show_malformed_cassette_reports_format_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["show", str(bad)]) == EXIT_ERROR
    assert "error" in capsys.readouterr().err


def test_diff_identical_cassettes_exits_zero(cassette_pair, capsys):
    baseline, _ = cassette_pair
    assert main(["diff", str(baseline), str(baseline)]) == EXIT_OK
    assert "cassettes match" in capsys.readouterr().out


def test_diff_drift_exits_nonzero_and_reports_changes(cassette_pair, capsys):
    baseline, drifted = cassette_pair
    assert main(["diff", str(baseline), str(drifted)]) == EXIT_DRIFT
    out = capsys.readouterr().out
    assert "drift detected" in out
    assert "send_alert" in out  # the added call is shown
    assert '"Tokyo"' in out and '"Osaka"' in out  # the argument change is shown


def test_diff_missing_file_exits_two(cassette_pair, tmp_path, capsys):
    baseline, _ = cassette_pair
    assert main(["diff", str(baseline), str(tmp_path / "nope.json")]) == EXIT_ERROR
    assert "no such cassette" in capsys.readouterr().err


def test_diff_ignores_duration_only_changes(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for path in (a, b):
        with VCR(str(path), mode="record") as vcr:
            vcr.wrap_tool("t", lambda x: x)(1)
    text = b.read_text()
    assert main(["diff", str(a), str(b)]) == EXIT_OK, text


def test_no_command_prints_help_and_exits_two(capsys):
    assert main([]) == EXIT_ERROR
    assert "usage: agent-vcr" in capsys.readouterr().out


def test_version_flag_matches_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"agent-vcr {agent_vcr.__version__}"


def test_help_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for command in ("ls", "show", "diff", "--version"):
        assert command in out


def test_console_script_and_module_entry_agree_on_version():
    module_run = subprocess.run(
        [sys.executable, "-m", "agent_vcr", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert module_run.stdout.strip() == f"agent-vcr {agent_vcr.__version__}"

    # Locate the console script next to the running interpreter instead of via
    # shutil.which(): the caller's PATH may not include the venv's bin directory
    # (e.g. `.venv/bin/python -m pytest` without activating the venv), and PATH
    # lookup could also pick up an unrelated system-wide install. POSIX layout
    # only (scripts live in the interpreter's directory); Windows uses a
    # different "Scripts" directory and is intentionally not supported here.
    script = Path(sys.executable).parent / "agent-vcr"
    if script.exists():  # present when the package is pip-installed (e.g. in the venv)
        script_run = subprocess.run(
            [str(script), "--version"], capture_output=True, text=True, check=True
        )
        assert script_run.stdout.strip() == module_run.stdout.strip()
