"""pytest integration: an ``agent_vcr`` fixture driven by ``AGENT_VCR_MODE``.

The plugin is registered automatically through the ``pytest11`` entry point
when agent-vcr is installed. Each test that requests the ``agent_vcr`` fixture
gets a :class:`~agent_vcr.vcr.VCR` bound to a per-test cassette file:

    def test_checkout(agent_vcr):
        search = agent_vcr.wrap_tool("search", search)
        run_agent(search)

Modes:

- ``AGENT_VCR_MODE`` unset -> ``auto`` (record on first run, replay after).
- ``AGENT_VCR_MODE=record pytest`` -> re-record every cassette.
- ``AGENT_VCR_MODE=replay-strict pytest`` -> CI mode; any unmatched call fails.

Per-test overrides use the ``agent_vcr`` marker::

    @pytest.mark.agent_vcr(mode="replay-strict", cassette="custom.json")
    def test_pinned(agent_vcr): ...

Cassettes default to ``<test file dir>/cassettes/<test name>.json``; the
directory name is configurable with the ``agent_vcr_cassette_dir`` ini option.

The cassette is saved on teardown only when the test passed, mirroring the
clean-exit semantics of ``with_cassette``: a failing first run in ``auto``
mode must not persist a half-recorded cassette that later runs would silently
replay.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

from .vcr import AUTO, VCR

ENV_MODE = "AGENT_VCR_MODE"

# Set on the item's stash when any phase (setup/call/teardown) fails, so the
# fixture below can skip saving a cassette recorded during a failing test.
_TEST_FAILED = pytest.StashKey[bool]()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Remember per-item failure so the ``agent_vcr`` fixture can see it."""
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        item.stash[_TEST_FAILED] = True


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``agent_vcr_cassette_dir`` ini option."""
    parser.addini(
        "agent_vcr_cassette_dir",
        default="cassettes",
        help=(
            "directory (relative to each test file) where the agent_vcr "
            "fixture stores cassettes"
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``agent_vcr`` marker so ``--strict-markers`` stays happy."""
    config.addinivalue_line(
        "markers",
        "agent_vcr(cassette=..., mode=...): override the cassette path or "
        "record/replay mode for the agent_vcr fixture",
    )


def default_mode() -> str:
    """Return the mode selected by the ``AGENT_VCR_MODE`` env var (or ``auto``)."""
    return os.environ.get(ENV_MODE, AUTO)


@pytest.fixture
def agent_vcr(request: pytest.FixtureRequest) -> Iterator[VCR]:
    """Yield a per-test :class:`VCR`; the cassette is saved when the test passes.

    The mode comes from the ``AGENT_VCR_MODE`` environment variable (default
    ``auto``) and can be overridden per test with the ``agent_vcr`` marker.
    A failing test does not persist its cassette (same rule as the
    ``with_cassette`` context manager, which only saves on clean exit), so a
    broken first recording never poisons subsequent ``auto``-mode replays.
    """
    marker = request.node.get_closest_marker("agent_vcr")
    mode = default_mode()
    cassette_path = None
    if marker is not None:
        mode = marker.kwargs.get("mode", mode)
        cassette_path = marker.kwargs.get("cassette")
    if cassette_path is None:
        cassette_dir = request.config.getini("agent_vcr_cassette_dir")
        base = os.path.dirname(str(request.path))
        safe_name = request.node.name.replace("/", "_").replace(os.sep, "_")
        cassette_path = os.path.join(base, cassette_dir, f"{safe_name}.json")
    vcr = VCR(cassette_path, mode=mode)
    yield vcr
    if request.node.stash.get(_TEST_FAILED, False):
        return
    vcr.save()
