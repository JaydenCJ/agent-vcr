"""End-to-end demo: record the weather agent, replay it, assert the trajectory.

Run it directly (no network, no real LLM):

    python examples/record_replay_demo.py [output_dir]

It writes two cassettes (``baseline.json`` for the v1 agent, ``v2.json`` for
the drifted v2 agent) into ``output_dir`` (a temp directory by default), then:

1. replays the baseline in ``replay-strict`` mode and verifies the outputs are
   byte-identical to the recorded run;
2. asserts the v1 trajectory (tool sequence, argument, step budget);
3. shows the same assertions going red against the v2 cassette.

The smoke script diffs the two cassettes afterwards with ``agent-vcr diff``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from agent_vcr import VCR, assert_trajectory

from weather_agent import (
    PLAN_V1,
    PLAN_V2,
    ScriptedPlanner,
    make_wrapped_tools,
    run_weather_agent,
)


def main(argv: list) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path(tempfile.mkdtemp(prefix="agent-vcr-demo-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = out_dir / "baseline.json"
    v2 = out_dir / "v2.json"

    # 1. Record the v1 agent against the "live" fake tools.
    with VCR(str(baseline), mode="record") as vcr:
        recorded = run_weather_agent(ScriptedPlanner(PLAN_V1), make_wrapped_tools(vcr))
    print(f"[record] baseline cassette written: {baseline}")
    print(f"[record] answer: {recorded['suggest_outfit']['outfit']}")

    # 2. Replay in strict mode: the environment is frozen, outputs identical.
    with VCR(str(baseline), mode="replay-strict") as vcr:
        replayed = run_weather_agent(ScriptedPlanner(PLAN_V1), make_wrapped_tools(vcr))
    identical = json.dumps(recorded, sort_keys=True) == json.dumps(replayed, sort_keys=True)
    print(f"[replay] outputs byte-identical to recording: {identical}")
    if not identical:
        return 1

    # 3. Trajectory assertions on the baseline (this is what you put in CI).
    (
        assert_trajectory(str(baseline))
        .tools_called(["get_weather", "suggest_outfit"])
        .tool_called_with("get_weather", {"city": "Tokyo"})
        .tool_call_count("get_weather", 1)
        .max_steps(2)
        .no_unexpected_tools(["get_weather", "suggest_outfit"])
    )
    print("[assert] v1 trajectory assertions passed")

    # 4. Record the v2 agent (prompt change -> one extra get_weather call).
    with VCR(str(v2), mode="record") as vcr:
        run_weather_agent(ScriptedPlanner(PLAN_V2), make_wrapped_tools(vcr))
    print(f"[record] v2 cassette written: {v2}")

    # 5. The same assertions catch the drift.
    try:
        assert_trajectory(str(v2)).tool_call_count("get_weather", 1)
    except AssertionError as exc:
        print("[assert] drift caught by tool_call_count:")
        print("    " + str(exc).splitlines()[0])
    else:
        print("[assert] ERROR: drift was not caught")
        return 1

    try:
        assert_trajectory(str(v2)).max_steps(2)
    except AssertionError as exc:
        print("[assert] drift caught by max_steps:")
        print("    " + str(exc).splitlines()[0])
    else:
        print("[assert] ERROR: drift was not caught")
        return 1

    print("DEMO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
