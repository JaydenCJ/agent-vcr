"""A tiny weather agent used by the examples and the smoke script.

The "LLM" here is a :class:`ScriptedPlanner`: a deterministic stand-in that
walks a fixed plan instead of sampling tokens. That keeps the example fully
offline and reproducible while still exercising the real agent-vcr flow:
tools are wrapped, every call is recorded to a cassette, and the trajectory
can be asserted afterwards.

Two plans are provided:

- ``PLAN_V1``: the baseline agent -- one ``get_weather`` call, then
  ``suggest_outfit``.
- ``PLAN_V2``: the same agent after a prompt change that makes it
  "double-check" the weather -- an extra ``get_weather`` call. Trajectory
  assertions written against v1 catch this drift.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Dict, List, Tuple

# Fixed conditions for the fake live weather service.
_CITY_WEATHER: Dict[str, Dict[str, Any]] = {
    "Tokyo": {"temp_c": 31, "condition": "humid"},
    "Osaka": {"temp_c": 33, "condition": "sunny"},
    "Sapporo": {"temp_c": 18, "condition": "cloudy"},
}

# Simulates server-side state that changes between calls (an observation id).
# Replay freezes whatever id was recorded, which is exactly the point.
_observation_ids = itertools.count(1)


def get_weather(city: str) -> Dict[str, Any]:
    """Fake live weather API: fixed data per city plus a changing observation id."""
    if city not in _CITY_WEATHER:
        raise KeyError(f"unknown city: {city}")
    return {"city": city, "observation_id": next(_observation_ids), **_CITY_WEATHER[city]}


def suggest_outfit(temp_c: int, condition: str) -> Dict[str, str]:
    """Fake outfit tool: a deterministic rule over temperature and condition."""
    if temp_c >= 28:
        outfit = "t-shirt and shorts"
    elif temp_c >= 18:
        outfit = "light jacket"
    else:
        outfit = "warm coat"
    if condition in ("rainy", "humid"):
        outfit += ", bring an umbrella"
    return {"outfit": outfit}


# A plan step: (tool_name, args_builder). The builder maps observations
# gathered so far to the tool's keyword arguments, mimicking how an LLM
# grounds its next tool call in previous tool results.
PlanStep = Tuple[str, Callable[[Dict[str, Any]], Dict[str, Any]]]

PLAN_V1: List[PlanStep] = [
    ("get_weather", lambda obs: {"city": "Tokyo"}),
    (
        "suggest_outfit",
        lambda obs: {
            "temp_c": obs["get_weather"]["temp_c"],
            "condition": obs["get_weather"]["condition"],
        },
    ),
]

# After a "prompt v2" change the agent double-checks the weather: one extra
# get_weather call before deciding. Same final answer, different trajectory.
PLAN_V2: List[PlanStep] = [
    ("get_weather", lambda obs: {"city": "Tokyo"}),
    ("get_weather", lambda obs: {"city": "Tokyo"}),
    (
        "suggest_outfit",
        lambda obs: {
            "temp_c": obs["get_weather"]["temp_c"],
            "condition": obs["get_weather"]["condition"],
        },
    ),
]


class ScriptedPlanner:
    """Deterministic fake LLM: yields tool calls from a fixed plan."""

    def __init__(self, plan: List[PlanStep]) -> None:
        self.plan = list(plan)

    def actions(self, observations: Dict[str, Any]):
        """Yield ``(tool_name, kwargs)`` pairs, grounding each in observations."""
        for tool_name, build_args in self.plan:
            yield tool_name, build_args(observations)


def run_weather_agent(
    planner: ScriptedPlanner,
    tools: Dict[str, Callable[..., Any]],
) -> Dict[str, Any]:
    """Run the agent loop: ask the planner for actions, execute them via tools.

    Returns the final observations dict; ``observations["suggest_outfit"]`` is
    the agent's answer.
    """
    observations: Dict[str, Any] = {}
    for tool_name, kwargs in planner.actions(observations):
        observations[tool_name] = tools[tool_name](**kwargs)
    return observations


def make_wrapped_tools(vcr: Any) -> Dict[str, Callable[..., Any]]:
    """Wrap both live tools with a :class:`agent_vcr.VCR` instance."""
    return {
        "get_weather": vcr.wrap_tool("get_weather", get_weather),
        "suggest_outfit": vcr.wrap_tool("suggest_outfit", suggest_outfit),
    }
