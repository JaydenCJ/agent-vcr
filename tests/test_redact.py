"""Secret redaction: built-in patterns, key names, dotted paths, end to end."""

from __future__ import annotations

import pytest

from agent_vcr import Redactor, VCR, load_cassette

# Fake credentials assembled at runtime so no secret-shaped literal is committed.
FAKE_OPENAI = "sk-" + "a" * 24
FAKE_AWS = "AKIA" + "A" * 16
FAKE_GITHUB = "ghp_" + "b" * 24
FAKE_JWT = "eyJ" + "x" * 8 + "." + "eyJ" + "y" * 8 + "." + "z" * 12


def test_sensitive_key_names_are_masked():
    redactor = Redactor()
    cleaned = redactor.redact(
        {"api_key": "value", "Authorization": "value", "password": "hunter2", "city": "Tokyo"}
    )
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["Authorization"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["city"] == "Tokyo"


def test_credential_shaped_values_are_masked_anywhere():
    redactor = Redactor()
    cleaned = redactor.redact(
        {
            "note": f"use {FAKE_OPENAI} for auth",
            "items": [FAKE_AWS, {"deep": FAKE_GITHUB}],
            "jwt": FAKE_JWT,
        }
    )
    text = str(cleaned)
    assert FAKE_OPENAI not in text
    assert FAKE_AWS not in text
    assert FAKE_GITHUB not in text
    assert FAKE_JWT.split(".")[0] not in text
    assert cleaned["note"] == "use [REDACTED] for auth"


def test_sensitive_keys_mask_non_string_values_wholesale():
    """Numbers, lists, and nested objects under a sensitive key are all masked."""
    redactor = Redactor()
    cleaned = redactor.redact(
        {
            "api_key": 123456789012345678,
            "token": ["my-plain-secret-value", "another"],
            "authorization": {"scheme": "Basic", "credentials": "dXNlcjpwYXNz"},
            "city": "Tokyo",
        }
    )
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["token"] == "[REDACTED]"
    assert cleaned["authorization"] == "[REDACTED]"
    assert cleaned["city"] == "Tokyo"
    text = str(cleaned)
    assert "123456789012345678" not in text
    assert "my-plain-secret-value" not in text
    assert "dXNlcjpwYXNz" not in text


def test_dotted_paths_are_always_masked():
    redactor = Redactor(paths=["headers.X-Custom", "users.0.ssn"])
    cleaned = redactor.redact(
        {
            "headers": {"X-Custom": "not-secret-shaped", "Accept": "json"},
            "users": [{"ssn": "123-45-6789", "name": "ada"}],
        }
    )
    assert cleaned["headers"]["X-Custom"] == "[REDACTED]"
    assert cleaned["headers"]["Accept"] == "json"
    assert cleaned["users"][0]["ssn"] == "[REDACTED]"
    assert cleaned["users"][0]["name"] == "ada"


def test_disabled_redactor_is_a_noop():
    value = {"api_key": "visible"}
    assert Redactor(enabled=False).redact(value) == value


def test_custom_placeholder():
    cleaned = Redactor(placeholder="***").redact({"token": "x"})
    assert cleaned["token"] == "***"


def test_recorded_cassette_contains_no_secrets(tmp_path):
    """End to end: secrets in args and results never reach the cassette file."""
    path = tmp_path / "c.json"

    def call_api(query: str, api_key: str) -> dict:
        return {"data": query, "used_key": api_key, "trace": f"bearer {FAKE_JWT}"}

    with VCR(str(path), mode="record", redact_paths=("trace",)) as vcr:
        vcr.wrap_tool("call_api", call_api)("weather", api_key=FAKE_OPENAI)

    raw = path.read_text(encoding="utf-8")
    assert FAKE_OPENAI not in raw
    assert FAKE_JWT.split(".")[0] not in raw
    assert "[REDACTED]" in raw

    cassette = load_cassette(str(path))
    assert cassette.interactions[0].args["api_key"] == "[REDACTED]"
    assert cassette.interactions[0].result["trace"] == "[REDACTED]"


def test_exception_messages_are_redacted_before_reaching_the_cassette(tmp_path):
    """Auth failures echo credentials; the error field must be scrubbed too."""
    path = tmp_path / "c.json"

    def call_api(query: str) -> dict:
        raise RuntimeError(f"401 unauthorized: invalid api key {FAKE_OPENAI}")

    with VCR(str(path), mode="record") as vcr:
        with pytest.raises(RuntimeError):
            vcr.wrap_tool("call_api", call_api)("weather")

    raw = path.read_text(encoding="utf-8")
    assert FAKE_OPENAI not in raw
    cassette = load_cassette(str(path))
    assert cassette.interactions[0].error == (
        "RuntimeError: 401 unauthorized: invalid api key [REDACTED]"
    )
