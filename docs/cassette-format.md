# Cassette file format (version 1)

A cassette is a single JSON document holding the ordered tool/MCP calls of one
recorded agent run. The format is a core deliverable of agent-vcr: other
implementations (for example a future TypeScript SDK) are expected to read and
write the same files.

## Design goals

- **Human-readable and reviewable**: cassettes are meant to be committed to
  git and reviewed like any other test fixture.
- **Diff-stable**: serialization uses `sort_keys=True`, 2-space indentation,
  and a trailing newline, so writing the same logical cassette always produces
  byte-identical output regardless of dict insertion order.
- **Versioned**: the top-level `agent_vcr_version` field lets readers refuse
  or migrate incompatible files instead of misreading them.
- **Safe to share**: secrets are redacted at record time (see
  `agent_vcr.redact`), before anything reaches disk.

## Top-level structure

```json
{
  "agent_vcr_version": "1",
  "interactions": [ ... ],
  "metadata": {
    "name": "baseline"
  }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `agent_vcr_version` | string | yes | Format version. This document describes version `"1"`. Readers must reject unknown versions with a clear error (`CassetteFormatError`). |
| `interactions` | array | yes | Ordered list of recorded tool calls (may be empty). |
| `metadata` | object | no | Free-form metadata. The `name` key is reserved for the cassette name (defaults to the file stem at record time). |

## Interaction entries

Each element of `interactions` is one recorded tool call:

```json
{
  "seq": 0,
  "tool_name": "get_weather",
  "args": {"city": "Tokyo"},
  "result": {"city": "Tokyo", "condition": "humid", "temp_c": 31},
  "duration_ms": 0.002
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `seq` | integer | yes | Monotonic call index within the cassette, starting at 0. Defines the trajectory order. |
| `tool_name` | string | yes | Name the tool was wrapped under (`wrap_tool` name, `wrap_toolkit` prefix + method, or the MCP tool name). |
| `args` | object | yes | Normalized call arguments. Positional arguments are bound to parameter names via the callable's signature, so `f("Tokyo")` and `f(city="Tokyo")` both record as `{"city": "Tokyo"}`. Values are round-tripped through JSON and redacted. |
| `result` | any JSON | yes | The tool's return value after JSON round-trip and redaction. `null` when the call raised. |
| `error` | string | omitted when absent | `"ExceptionType: message"` for calls that raised, with the message passed through redaction (auth failures often echo credentials). Replay re-raises it as `ReplayedError`. |
| `duration_ms` | number | yes | Wall-clock duration of the recorded live call in milliseconds, rounded to 3 decimals. Informational only: replay matching and `agent-vcr diff` ignore it. |
| `tags` | array of strings | omitted when empty | User-supplied labels (`record_tags=` on the `VCR`). |

## Value normalization

Before writing, both `args` and `result` pass through:

1. **JSON round-trip** (`json.dumps` then `json.loads`): tuples become lists,
   non-serializable leaves fall back to `str(value)`. This guarantees that
   what you replay is structurally identical to what was recorded.
2. **Redaction**: built-in credential patterns (OpenAI/Anthropic keys, AWS
   access keys, GitHub tokens, Slack tokens, Google API keys, bearer headers,
   JWTs), sensitive key names (`api_key`, `password`, `authorization`, ...),
   and user-supplied dotted paths are replaced with `[REDACTED]`. A sensitive
   key name masks its entire value regardless of type (string, number, list,
   or nested object). Error messages are scrubbed with the same credential
   patterns before they are stored.

In `record` mode the wrapper also *returns* this normalized, redacted value to
the caller — exactly what replay will serve later — so a recording run and a
replaying run behave identically. A consequence for MCP users: rich SDK result
objects (for example `CallToolResult`) are stored via the `str()` fallback and
come back as plain data in both modes, never as SDK instances.

## Matching semantics during replay

Replay walks `interactions` in order and serves the first *unused* entry whose
`tool_name` equals the incoming call and whose `args` satisfy the matcher for
that tool (deep equality by default). Each entry is served at most once, so a
tool called twice with identical arguments consumes two entries. In
`replay-strict` mode an unmatched call raises `CassetteMissError` carrying an
expected-vs-actual argument diff; in lenient `replay` mode an unused entry for
the same tool is served with an `AgentVCRWarning`. A cassette file that does
not exist at all raises `CassetteNotFoundError` (a `CassetteMissError`
subclass), so CI can tell "the recording was never committed" apart from
genuine trajectory drift.

## Versioning policy

- Backward-compatible additions (new optional fields) do not bump the version.
- Any change to the meaning or type of existing fields bumps
  `agent_vcr_version`, and readers must reject files whose version they do not
  support (this is enforced by `Cassette.from_dict` and covered by tests).
