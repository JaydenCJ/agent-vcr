#!/usr/bin/env bash
# Smoke test for agent-vcr: record + replay the example agent, assert the
# trajectory, and verify that drift makes `agent-vcr diff` exit non-zero.
# Self-contained: pure stdlib, no network, idempotent (works from a clean tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# The package has zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-vcr-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 1. Record + strict replay + trajectory assertions + drift caught (examples).
demo_out="$("$PYTHON" "$ROOT/examples/record_replay_demo.py" "$WORKDIR")" \
  || fail "record_replay_demo.py exited non-zero"
echo "$demo_out" | sed 's/^/[demo] /'
echo "$demo_out" | grep -q "byte-identical to recording: True" \
  || fail "replay was not byte-identical to the recording"
echo "$demo_out" | grep -q "v1 trajectory assertions passed" \
  || fail "trajectory assertions did not pass on the baseline"
echo "$demo_out" | grep -q "drift caught by tool_call_count" \
  || fail "trajectory assertion did not catch the drift"
echo "$demo_out" | grep -q "DEMO OK" || fail "demo did not finish"
[ -f "$WORKDIR/baseline.json" ] || fail "baseline cassette missing"
[ -f "$WORKDIR/v2.json" ] || fail "v2 cassette missing"

# 2. CLI: ls sees both cassettes with correct step counts.
ls_out="$("$PYTHON" -m agent_vcr ls "$WORKDIR")"
echo "$ls_out" | sed 's/^/[ls] /'
echo "$ls_out" | grep -E 'baseline\.json +baseline +2 ' >/dev/null \
  || fail "ls did not report baseline with 2 steps"
echo "$ls_out" | grep -E 'v2\.json +v2 +3 ' >/dev/null \
  || fail "ls did not report v2 with 3 steps"

# 3. CLI: show pretty-prints the trajectory.
show_out="$("$PYTHON" -m agent_vcr show "$WORKDIR/baseline.json")"
echo "$show_out" | grep -q "format version: 1" || fail "show missing version line"
echo "$show_out" | grep -q "get_weather" || fail "show missing tool call"

# 4. CLI: diff of identical cassettes exits 0.
"$PYTHON" -m agent_vcr diff "$WORKDIR/baseline.json" "$WORKDIR/baseline.json" >/dev/null \
  || fail "diff of identical cassettes should exit 0"

# 5. CLI: diff of drifted cassettes exits non-zero and reports drift.
set +e
diff_out="$("$PYTHON" -m agent_vcr diff "$WORKDIR/baseline.json" "$WORKDIR/v2.json")"
diff_rc=$?
set -e
echo "$diff_out" | sed 's/^/[diff] /'
[ "$diff_rc" -eq 1 ] || fail "diff on drift should exit 1, got $diff_rc"
echo "$diff_out" | grep -q "drift detected" || fail "diff did not report drift"

# 6. CLI: --help and --version agree with the package version.
version_out="$("$PYTHON" -m agent_vcr --version)"
pkg_version="$("$PYTHON" -c 'import agent_vcr; print(agent_vcr.__version__)')"
[ "$version_out" = "agent-vcr $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"
"$PYTHON" -m agent_vcr --help | grep -q "diff" || fail "--help missing diff command"

echo "SMOKE OK"
