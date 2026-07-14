"""agent-vcr: record and replay AI agent tool calls, then assert on trajectories.

Like VCR.py for HTTP, but at the tool/MCP layer: wrap your agent's tools once,
record every call to a JSON cassette, replay it deterministically in CI, and
assert on the trajectory (which tools, which arguments, how many steps) to
catch behavior drift.

Public API:

- :class:`VCR` -- the recorder/replayer; wrap tools, toolkits, or MCP clients.
- :func:`with_cassette` -- context-manager entry point honoring ``AGENT_VCR_MODE``.
- :class:`Trajectory` / :func:`assert_trajectory` -- fluent trajectory assertions.
- :mod:`agent_vcr.matchers` -- argument matchers (``exact``, ``ignore_fields``, ...).
- :class:`Redactor` -- secret redaction so cassettes are safe to commit.
- Errors: :class:`CassetteMissError`, :class:`CassetteNotFoundError`,
  :class:`CassetteFormatError`, :class:`ReplayedError`, :class:`AgentVCRError`,
  :class:`AgentVCRWarning`.
"""

from . import matchers
from .cassette import CASSETTE_VERSION, Cassette, Interaction
from .cassette import load as load_cassette
from .cassette import save as save_cassette
from .errors import (
    AgentVCRError,
    AgentVCRWarning,
    CassetteFormatError,
    CassetteMissError,
    CassetteNotFoundError,
    ReplayedError,
)
from .redact import Redactor
from .trajectory import Trajectory, assert_trajectory
from .vcr import AUTO, PASSTHROUGH, RECORD, REPLAY, REPLAY_STRICT, VCR, with_cassette

__version__ = "0.1.0"

__all__ = [
    "VCR",
    "with_cassette",
    "Trajectory",
    "assert_trajectory",
    "Cassette",
    "Interaction",
    "load_cassette",
    "save_cassette",
    "CASSETTE_VERSION",
    "Redactor",
    "matchers",
    "AgentVCRError",
    "AgentVCRWarning",
    "CassetteFormatError",
    "CassetteMissError",
    "CassetteNotFoundError",
    "ReplayedError",
    "RECORD",
    "REPLAY",
    "REPLAY_STRICT",
    "PASSTHROUGH",
    "AUTO",
    "__version__",
]
