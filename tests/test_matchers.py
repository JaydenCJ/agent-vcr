"""Argument matchers: built-ins and custom per-tool matchers."""

from __future__ import annotations

import pytest

from agent_vcr import CassetteMissError, VCR, matchers


def test_exact_matcher_is_deep_equality():
    match = matchers.exact()
    assert match({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]})
    assert not match({"a": 1}, {"a": 2})


def test_ignore_fields_drops_dotted_paths_on_both_sides():
    match = matchers.ignore_fields("request_id", "meta.timestamp")
    recorded = {"q": "x", "request_id": "r1", "meta": {"timestamp": 1, "lang": "en"}}
    actual = {"q": "x", "request_id": "r2", "meta": {"timestamp": 2, "lang": "en"}}
    assert match(recorded, actual)
    actual["meta"]["lang"] = "ja"
    assert not match(recorded, actual)


def test_subset_matches_only_the_named_paths():
    match = matchers.subset("city")
    assert match({"city": "Tokyo", "units": "C"}, {"city": "Tokyo", "units": "F"})
    assert not match({"city": "Tokyo"}, {"city": "Osaka"})
    assert not match({"units": "C"}, {"city": "Tokyo"})  # path missing on one side


def test_fuzzy_numbers_tolerates_float_drift():
    match = matchers.fuzzy_numbers(rel_tol=1e-3)
    assert match({"lat": 35.6895}, {"lat": 35.6896})
    assert not match({"lat": 35.6895}, {"lat": 36.0})
    assert not match({"flag": True}, {"flag": 0.999999})  # bools get no tolerance
    assert match({"xs": [1.0, 2.0]}, {"xs": [1.0, 2.0000001]})
    assert not match({"xs": [1.0]}, {"xs": [1.0, 2.0]})


def test_combine_requires_all_matchers():
    match = matchers.combine(
        matchers.ignore_fields("request_id"), matchers.subset("city")
    )
    assert match({"city": "Tokyo", "request_id": 1}, {"city": "Tokyo", "request_id": 2})
    assert not match({"city": "Tokyo", "request_id": 1}, {"city": "Osaka", "request_id": 1})


def test_per_tool_matcher_lets_replay_survive_noisy_fields(tmp_path):
    path = tmp_path / "c.json"

    def search(query: str, request_id: str) -> dict:
        return {"hits": [query]}

    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("search", search)("docs", request_id="req-1")

    # Without a matcher, the new request_id is a strict miss.
    with VCR(str(path), mode="replay-strict") as vcr:
        with pytest.raises(CassetteMissError):
            vcr.wrap_tool("search", search)("docs", request_id="req-2")

    # With ignore_fields registered for the tool, replay matches.
    with VCR(str(path), mode="replay-strict") as vcr:
        vcr.matcher("search", matchers.ignore_fields("request_id"))
        assert vcr.wrap_tool("search", search)("docs", request_id="req-2") == {
            "hits": ["docs"]
        }


def test_custom_callable_matcher(tmp_path):
    path = tmp_path / "c.json"

    def fetch(url: str) -> str:
        return "body"

    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("fetch", fetch)("https://example.test/a?v=1")

    def same_path_ignoring_query(recorded, actual):
        return recorded["url"].split("?")[0] == actual["url"].split("?")[0]

    with VCR(str(path), mode="replay-strict") as vcr:
        vcr.matcher("fetch", same_path_ignoring_query)
        assert vcr.wrap_tool("fetch", fetch)("https://example.test/a?v=2") == "body"


def test_default_matcher_applies_to_all_tools(tmp_path):
    path = tmp_path / "c.json"

    def t(x: int, nonce: int) -> int:
        return x

    with VCR(str(path), mode="record") as vcr:
        vcr.wrap_tool("t", t)(1, nonce=111)

    with VCR(
        str(path),
        mode="replay-strict",
        default_matcher=matchers.ignore_fields("nonce"),
    ) as vcr:
        assert vcr.wrap_tool("t", t)(1, nonce=222) == 1
