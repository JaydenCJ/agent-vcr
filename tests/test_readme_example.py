"""The README quickstart example, executed verbatim from the README file.

The code block is extracted from README.md at test time, so the documentation
cannot drift from working code: if the README example breaks, this test fails.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def readme_example() -> str:
    """Return the first python code block from README.md."""
    match = re.search(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    assert match, "README.md must contain a python example"
    return match.group(1)


def run_example(code: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(code, str(README), "exec"), {"__name__": "__readme__"})
    return buffer.getvalue()


def test_readme_example_is_at_most_ten_lines():
    code_lines = [l for l in readme_example().splitlines() if l.strip()]
    assert 0 < len(code_lines) <= 10


def test_readme_example_records_then_replays_identically(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = readme_example()

    first = run_example(code)  # run 1: records weather.json
    assert (tmp_path / "weather.json").exists()

    second = run_example(code)  # run 2: replays the cassette
    # The tool output is random on a live call, so identical output proves
    # the second run was served from the cassette, byte for byte.
    assert second == first
    assert "'city': 'Tokyo'" in first
