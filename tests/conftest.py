"""Shared test configuration.

Enables the ``pytester`` fixture used to test the pytest plugin in isolated
sub-runs, and keeps the environment-driven mode selection deterministic by
clearing ``AGENT_VCR_MODE`` for every test.
"""

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _clean_agent_vcr_mode(monkeypatch):
    """Ensure tests are not affected by an AGENT_VCR_MODE set in the shell."""
    monkeypatch.delenv("AGENT_VCR_MODE", raising=False)
