# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-08

### Added

- `VCR` record/replay engine for agent tool calls with five modes: `record`,
  `replay`, `replay-strict`, `passthrough`, and `auto`. Record-mode wrappers
  return the same JSON-normalized, redacted value that replay serves later,
  so recording and replaying runs behave identically.
- Wrapping helpers: `wrap_tool` (sync and async callables), `wrap_toolkit`
  (whole objects), and `wrap_mcp_client` (duck-typed MCP `call_tool` clients,
  no MCP SDK dependency).
- Versioned JSON cassette format with sorted keys, atomic writes, and a
  documented schema (`docs/cassette-format.md`).
- Trajectory assertions: `tools_called` (sequence/subsequence),
  `tool_called_with`, `tool_call_count`, `max_steps`, `no_unexpected_tools`,
  with numbered trajectory summaries in failure messages.
- Argument matchers: `exact`, `ignore_fields`, `subset`, `fuzzy_numbers`,
  `combine`, plus per-tool and default custom matchers.
- Secret redaction at record time: built-in credential patterns, sensitive key
  names (masking the whole value, whatever its type), and user-supplied dotted
  paths. Exception messages recorded in the `error` field are scrubbed with
  the same credential patterns.
- `with_cassette` context manager honoring the `AGENT_VCR_MODE` environment
  variable.
- pytest plugin with an `agent_vcr` fixture, an `agent_vcr` marker, and the
  `agent_vcr_cassette_dir` ini option. Cassettes are saved only when the test
  passes, so a failing first recording never poisons later `auto` replays.
- `CassetteNotFoundError` (a `CassetteMissError` subclass) for a missing
  cassette file, distinguishable in CI from a genuine replay miss.
- `agent-vcr` CLI: `ls` (list cassettes with step counts), `show`
  (pretty-print a trajectory), `diff` (compare two cassettes; exit 1 on
  drift).
- Runnable weather-agent example with a deterministic fake LLM planner and a
  prompt-drift regression case.

### Notes

- The repository ships no CI workflow; verification is local — `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.
