"""Cassette format: the on-disk record of an agent's tool/MCP calls.

A cassette is a single JSON file. Its schema is documented in
``docs/cassette-format.md`` and versioned via the ``agent_vcr_version`` field so
that readers can refuse or migrate incompatible files. Cassettes are written
with sorted keys and stable indentation so they are human-readable and produce
clean ``git diff`` output.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import CassetteFormatError

# Bump this when the on-disk schema changes in a backward-incompatible way.
CASSETTE_VERSION = "1"


@dataclass
class Interaction:
    """A single recorded tool/MCP call and its outcome.

    Attributes:
        seq: Monotonic index of the call within the cassette, starting at 0.
        tool_name: Name of the tool that was called.
        args: Normalized call arguments as a JSON object (see ``vcr._normalize_args``).
        result: JSON-serializable return value of the call. ``None`` when the
            call raised.
        error: String representation of the raised exception, or ``None``.
        duration_ms: Wall-clock duration of the recorded call, in milliseconds.
        tags: Optional list of user-supplied labels for filtering.
    """

    seq: int
    tool_name: str
    args: Dict[str, Any]
    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict, omitting empty optional fields."""
        data: Dict[str, Any] = {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "duration_ms": round(self.duration_ms, 3),
        }
        if self.error is not None:
            data["error"] = self.error
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Interaction":
        """Build an :class:`Interaction` from a decoded cassette entry."""
        try:
            return cls(
                seq=int(data["seq"]),
                tool_name=str(data["tool_name"]),
                args=data.get("args", {}),
                result=data.get("result"),
                error=data.get("error"),
                duration_ms=float(data.get("duration_ms", 0.0)),
                tags=data.get("tags"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CassetteFormatError(f"invalid interaction entry: {exc}") from exc


@dataclass
class Cassette:
    """An ordered collection of :class:`Interaction` objects plus metadata."""

    name: str = "cassette"
    interactions: List[Interaction] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = CASSETTE_VERSION

    def add(self, interaction: Interaction) -> None:
        """Append an interaction to the cassette."""
        self.interactions.append(interaction)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the whole cassette to a plain dict."""
        return {
            "agent_vcr_version": self.version,
            "metadata": {"name": self.name, **self.metadata},
            "interactions": [i.to_dict() for i in self.interactions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Cassette":
        """Build a :class:`Cassette` from a decoded JSON document."""
        if not isinstance(data, dict):
            raise CassetteFormatError("cassette root must be a JSON object")
        version = str(data.get("agent_vcr_version", ""))
        if version != CASSETTE_VERSION:
            raise CassetteFormatError(
                f"unsupported cassette version {version!r}; "
                f"this build reads version {CASSETTE_VERSION!r}"
            )
        raw = data.get("interactions", [])
        if not isinstance(raw, list):
            raise CassetteFormatError("'interactions' must be a list")
        metadata = dict(data.get("metadata") or {})
        name = str(metadata.pop("name", "cassette"))
        return cls(
            name=name,
            interactions=[Interaction.from_dict(i) for i in raw],
            metadata=metadata,
            version=version,
        )


def dumps(cassette: Cassette) -> str:
    """Serialize a cassette to canonical JSON text.

    Keys are sorted and indentation is fixed so the output is stable across runs
    and diff-friendly. A trailing newline is appended for POSIX-friendliness.
    """
    return (
        json.dumps(cassette.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def loads(text: str) -> Cassette:
    """Parse cassette JSON text into a :class:`Cassette`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CassetteFormatError(f"cassette is not valid JSON: {exc}") from exc
    return Cassette.from_dict(data)


def load(path: str) -> Cassette:
    """Read and parse a cassette file from disk."""
    with open(path, "r", encoding="utf-8") as handle:
        return loads(handle.read())


def save(cassette: Cassette, path: str) -> None:
    """Atomically write a cassette to ``path``.

    The file is written to a temporary sibling and then moved into place with
    ``os.replace`` so a crash mid-write never leaves a truncated cassette.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = dumps(cassette)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".agent-vcr-",
        suffix=".tmp",
        delete=False,
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
