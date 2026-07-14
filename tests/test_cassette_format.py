"""Cassette on-disk format: stable key order, versioning, atomic writes."""

from __future__ import annotations

import json

import pytest

from agent_vcr import CASSETTE_VERSION, Cassette, CassetteFormatError, Interaction
from agent_vcr.cassette import dumps, load, loads, save


def test_dumps_sorts_keys_so_output_is_insertion_order_independent():
    a = Cassette(name="c")
    a.metadata.update({"zeta": 1, "alpha": 2})
    a.add(Interaction(seq=0, tool_name="t", args={"b": 1, "a": 2}, result={"y": 1, "x": 2}))

    b = Cassette(name="c")
    b.metadata.update({"alpha": 2, "zeta": 1})
    b.add(Interaction(seq=0, tool_name="t", args={"a": 2, "b": 1}, result={"x": 2, "y": 1}))

    assert dumps(a) == dumps(b)


def test_dumps_is_diff_friendly_and_ends_with_newline():
    cassette = Cassette(name="c")
    cassette.add(Interaction(seq=0, tool_name="t", args={"x": 1}, result="ok"))
    text = dumps(cassette)
    assert text.endswith("\n")
    keys = list(json.loads(text).keys())
    assert keys == sorted(keys)  # top-level keys sorted for stable git diffs


def test_version_field_is_written_and_enforced():
    cassette = Cassette(name="c")
    data = json.loads(dumps(cassette))
    assert data["agent_vcr_version"] == CASSETTE_VERSION

    data["agent_vcr_version"] = "999"
    with pytest.raises(CassetteFormatError, match="unsupported cassette version"):
        loads(json.dumps(data))


def test_loads_rejects_malformed_documents():
    with pytest.raises(CassetteFormatError, match="not valid JSON"):
        loads("{nope")
    with pytest.raises(CassetteFormatError, match="root must be a JSON object"):
        loads("[1, 2]")
    with pytest.raises(CassetteFormatError, match="'interactions' must be a list"):
        loads(json.dumps({"agent_vcr_version": CASSETTE_VERSION, "interactions": {}}))
    with pytest.raises(CassetteFormatError, match="invalid interaction entry"):
        loads(
            json.dumps(
                {"agent_vcr_version": CASSETTE_VERSION, "interactions": [{"seq": 0}]}
            )
        )


def test_save_creates_parent_directories_and_roundtrips(tmp_path):
    cassette = Cassette(name="nested")
    cassette.add(
        Interaction(seq=0, tool_name="t", args={"q": "x"}, result=[1, 2], tags=["a"])
    )
    path = tmp_path / "deep" / "dir" / "c.json"
    save(cassette, str(path))
    loaded = load(str(path))
    assert loaded.name == "nested"
    assert loaded.interactions[0].args == {"q": "x"}
    assert loaded.interactions[0].result == [1, 2]
    assert loaded.interactions[0].tags == ["a"]


def test_save_leaves_no_temp_files_behind(tmp_path):
    save(Cassette(name="c"), str(tmp_path / "c.json"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.json"]


def test_error_and_tags_are_omitted_when_empty():
    entry = Interaction(seq=0, tool_name="t", args={}).to_dict()
    assert "error" not in entry
    assert "tags" not in entry
