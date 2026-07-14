"""The VCR recorder/replayer: the record and replay engine for tool calls.

A :class:`VCR` wraps callables (plain tools, toolkits, or an MCP client) so that
every invocation is either recorded to a cassette or served from one. Wrapping
does not change the call signature, so agent code stays identical between
record and replay.
"""

from __future__ import annotations

import copy
import functools
import inspect
import json
import os
import time
import warnings
from typing import Any, Callable, Dict, List, Optional

from . import matchers as _matchers
from .cassette import Cassette, Interaction, load, save
from .errors import (
    AgentVCRWarning,
    CassetteMissError,
    CassetteNotFoundError,
    ReplayedError,
)
from .matchers import Matcher
from .redact import Redactor

# Recording/playback modes.
RECORD = "record"
REPLAY = "replay"
REPLAY_STRICT = "replay-strict"
PASSTHROUGH = "passthrough"
AUTO = "auto"

_MODES = {RECORD, REPLAY, REPLAY_STRICT, PASSTHROUGH, AUTO}


def _jsonable(value: Any) -> Any:
    """Round-trip ``value`` through JSON so it is canonical and serializable.

    Tuples become lists and any non-serializable leaf falls back to its ``str``
    form. Applying this to both arguments and results guarantees that recorded
    and replayed values are structurally identical.
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class _ToolkitProxy:
    """Attribute proxy that serves wrapped tool methods and forwards the rest."""

    def __init__(self, target: Any, wrapped: Dict[str, Callable[..., Any]]) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_wrapped", wrapped)

    def __getattr__(self, name: str) -> Any:
        wrapped = object.__getattribute__(self, "_wrapped")
        if name in wrapped:
            return wrapped[name]
        return getattr(object.__getattribute__(self, "_target"), name)


class VCR:
    """Records tool calls to a cassette or replays them from one.

    Args:
        cassette_path: Path to the cassette file. Required for record and
            replay; may be ``None`` for in-memory recording or passthrough.
        mode: One of ``record``, ``replay``, ``replay-strict``, ``passthrough``,
            ``auto``. In ``auto`` the VCR replays when the cassette exists and
            records otherwise (VCR.py's "once" semantics).
        name: Cassette name stored in metadata; defaults to the file stem.
        matchers: Per-tool argument matchers, ``{tool_name: matcher}``.
        default_matcher: Matcher used for tools without a specific one. Defaults
            to deep equality.
        redactor: A configured :class:`Redactor`; overrides ``redact_paths``.
        redact_paths: Dotted paths always masked before writing to the cassette.
        record_tags: Tags attached to every interaction recorded by this VCR.
    """

    def __init__(
        self,
        cassette_path: Optional[str] = None,
        mode: str = AUTO,
        *,
        name: Optional[str] = None,
        matchers: Optional[Dict[str, Matcher]] = None,
        default_matcher: Optional[Matcher] = None,
        redactor: Optional[Redactor] = None,
        redact_paths=(),
        record_tags: Optional[List[str]] = None,
    ) -> None:
        if mode not in _MODES:
            raise ValueError(
                f"unknown mode {mode!r}; expected one of {sorted(_MODES)}"
            )
        self.cassette_path = cassette_path
        self.requested_mode = mode
        self.mode = self._resolve_mode(mode, cassette_path)
        self._matchers: Dict[str, Matcher] = dict(matchers or {})
        self._default_matcher: Matcher = default_matcher or _matchers.exact()
        self._redactor = redactor if redactor is not None else Redactor(paths=redact_paths)
        self._record_tags = list(record_tags) if record_tags else None
        self._used: set = set()
        self._seq = 0
        self.hits = 0
        self.warnings: List[str] = []

        stem = name
        if stem is None and cassette_path:
            stem = os.path.splitext(os.path.basename(cassette_path))[0]
        self._name = stem or "cassette"

        if self.mode in (REPLAY, REPLAY_STRICT):
            if not cassette_path or not os.path.exists(cassette_path):
                raise CassetteNotFoundError(cassette_path)
            self.cassette: Cassette = load(cassette_path)
        else:
            self.cassette = Cassette(name=self._name)

    # -- configuration -----------------------------------------------------

    def matcher(self, tool_name: str, fn: Matcher) -> "VCR":
        """Register a per-tool argument matcher and return ``self``."""
        self._matchers[tool_name] = fn
        return self

    # -- wrapping ----------------------------------------------------------

    def wrap_tool(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a single callable so its calls are recorded or replayed.

        The returned wrapper is async when ``fn`` is a coroutine function and
        synchronous otherwise. The call signature is preserved.

        In ``record`` mode the wrapper returns the same JSON-normalized,
        redacted value that is written to the cassette -- exactly what replay
        will serve later -- so a recording run and a replaying run see
        identical values (tuples come back as lists, non-JSON leaves as their
        ``str`` form). Only ``passthrough`` returns the tool's raw result.
        """
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key_args = self._key_args(fn, args, kwargs)
                if self.mode == PASSTHROUGH:
                    return await fn(*args, **kwargs)
                if self.mode in (REPLAY, REPLAY_STRICT):
                    return self._replay(name, key_args)
                start = time.perf_counter()
                error: Optional[BaseException] = None
                result: Any = None
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - recorded and re-raised
                    error = exc
                duration = (time.perf_counter() - start) * 1000.0
                stored = self._store(name, key_args, result, error, duration)
                if error is not None:
                    raise error
                return stored

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key_args = self._key_args(fn, args, kwargs)
            if self.mode == PASSTHROUGH:
                return fn(*args, **kwargs)
            if self.mode in (REPLAY, REPLAY_STRICT):
                return self._replay(name, key_args)
            start = time.perf_counter()
            error2: Optional[BaseException] = None
            result2: Any = None
            try:
                result2 = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - recorded and re-raised
                error2 = exc
            duration = (time.perf_counter() - start) * 1000.0
            stored = self._store(name, key_args, result2, error2, duration)
            if error2 is not None:
                raise error2
            return stored

        return sync_wrapper

    def wrap_toolkit(
        self,
        obj: Any,
        methods: Optional[List[str]] = None,
        prefix: str = "",
    ) -> _ToolkitProxy:
        """Wrap every public callable on ``obj`` and return a forwarding proxy.

        Args:
            obj: Object whose methods are tools.
            methods: Explicit method names to wrap; when ``None`` all public
                callables are wrapped.
            prefix: Prepended to each method name to form the recorded tool name.
        """
        if methods is None:
            methods = [
                n
                for n in dir(obj)
                if not n.startswith("_") and callable(getattr(obj, n, None))
            ]
        wrapped: Dict[str, Callable[..., Any]] = {}
        for method_name in methods:
            fn = getattr(obj, method_name)
            wrapped[method_name] = self.wrap_tool(f"{prefix}{method_name}", fn)
        return _ToolkitProxy(obj, wrapped)

    def wrap_mcp_client(self, client: Any, method: str = "call_tool") -> _ToolkitProxy:
        """Adapt an MCP-style client by wrapping its ``call_tool`` method.

        This duck-types the MCP SDK shape ``call_tool(name, arguments)`` without
        importing it. The recorded tool name is ``name`` and the recorded
        arguments are the ``arguments`` mapping. Other attributes forward to the
        underlying client unchanged.

        Note: return values are normalized to JSON before storage, with
        non-serializable objects falling back to ``str``. SDK result objects
        such as ``CallToolResult`` therefore come back as plain data (in both
        record and replay), not as SDK instances.
        """
        original = getattr(client, method)
        is_async = inspect.iscoroutinefunction(original)

        if is_async:

            async def call_tool(name: str, arguments: Optional[Dict[str, Any]] = None, **extra: Any) -> Any:
                key_args = self._normalize(arguments or {})
                if extra:
                    key_args = {**key_args, "__extra__": self._normalize(extra)}
                if self.mode == PASSTHROUGH:
                    return await original(name, arguments, **extra)
                if self.mode in (REPLAY, REPLAY_STRICT):
                    return self._replay(name, key_args)
                start = time.perf_counter()
                error: Optional[BaseException] = None
                result: Any = None
                try:
                    result = await original(name, arguments, **extra)
                except Exception as exc:  # noqa: BLE001
                    error = exc
                duration = (time.perf_counter() - start) * 1000.0
                stored = self._store(name, key_args, result, error, duration)
                if error is not None:
                    raise error
                return stored

        else:

            def call_tool(name: str, arguments: Optional[Dict[str, Any]] = None, **extra: Any) -> Any:
                key_args = self._normalize(arguments or {})
                if extra:
                    key_args = {**key_args, "__extra__": self._normalize(extra)}
                if self.mode == PASSTHROUGH:
                    return original(name, arguments, **extra)
                if self.mode in (REPLAY, REPLAY_STRICT):
                    return self._replay(name, key_args)
                start = time.perf_counter()
                error2: Optional[BaseException] = None
                result2: Any = None
                try:
                    result2 = original(name, arguments, **extra)
                except Exception as exc:  # noqa: BLE001
                    error2 = exc
                duration = (time.perf_counter() - start) * 1000.0
                stored = self._store(name, key_args, result2, error2, duration)
                if error2 is not None:
                    raise error2
                return stored

        return _ToolkitProxy(client, {method: call_tool})

    # -- persistence -------------------------------------------------------

    def save(self) -> None:
        """Write the recording to ``cassette_path`` (no-op unless recording)."""
        if self.mode == RECORD and self.cassette_path:
            save(self.cassette, self.cassette_path)

    def unused_interactions(self) -> List[Interaction]:
        """Return recorded interactions not yet consumed during replay."""
        if self.mode not in (REPLAY, REPLAY_STRICT):
            return []
        return [
            i
            for idx, i in enumerate(self.cassette.interactions)
            if idx not in self._used
        ]

    def __enter__(self) -> "VCR":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.save()
        return False

    # -- internal ----------------------------------------------------------

    def _resolve_mode(self, mode: str, path: Optional[str]) -> str:
        if mode != AUTO:
            return mode
        if path and os.path.exists(path):
            return REPLAY
        return RECORD

    def _key_args(self, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Dict[str, Any]:
        return self._normalize(_normalize_args(fn, args, kwargs))

    def _normalize(self, value: Any) -> Dict[str, Any]:
        return self._redactor.redact(_jsonable(value))

    def _store(
        self,
        tool_name: str,
        key_args: Dict[str, Any],
        result: Any,
        error: Optional[BaseException],
        duration_ms: float,
    ) -> Any:
        """Record one interaction and return the value the caller should see.

        The returned value is a deep copy of what was stored (JSON-normalized
        and redacted), so record mode hands back exactly what replay will
        serve later and callers cannot mutate the pending cassette.
        """
        if error is not None:
            stored_result = None
            # Exception messages routinely echo credentials (401 responses,
            # URLs with keys), so they go through the redactor like results do.
            error_str: Optional[str] = self._redactor.redact(
                f"{type(error).__name__}: {error}"
            )
        else:
            stored_result = self._redactor.redact(_jsonable(result))
            error_str = None
        interaction = Interaction(
            seq=self._seq,
            tool_name=tool_name,
            args=key_args,
            result=stored_result,
            error=error_str,
            duration_ms=duration_ms,
            tags=self._record_tags,
        )
        self._seq += 1
        self.cassette.add(interaction)
        return copy.deepcopy(stored_result)

    def _matcher_for(self, tool_name: str) -> Matcher:
        return self._matchers.get(tool_name, self._default_matcher)

    def _find_match(self, tool_name: str, key_args: Dict[str, Any]) -> Optional[int]:
        matcher = self._matcher_for(tool_name)
        for idx, interaction in enumerate(self.cassette.interactions):
            if idx in self._used:
                continue
            if interaction.tool_name != tool_name:
                continue
            if matcher(interaction.args, key_args):
                return idx
        return None

    def _find_same_tool_unused(self, tool_name: str) -> Optional[int]:
        for idx, interaction in enumerate(self.cassette.interactions):
            if idx in self._used:
                continue
            if interaction.tool_name == tool_name:
                return idx
        return None

    def _materialize(self, idx: int) -> Any:
        interaction = self.cassette.interactions[idx]
        if interaction.error is not None:
            raise ReplayedError(interaction.error)
        return copy.deepcopy(interaction.result)

    def _replay(self, tool_name: str, key_args: Dict[str, Any]) -> Any:
        idx = self._find_match(tool_name, key_args)
        if idx is not None:
            self._used.add(idx)
            self.hits += 1
            return self._materialize(idx)
        if self.mode == REPLAY_STRICT:
            raise self._miss_error(tool_name, key_args)
        # Lenient mode: tolerate argument drift on the same tool and warn.
        fallback = self._find_same_tool_unused(tool_name)
        if fallback is not None:
            self._used.add(fallback)
            message = (
                f"agent-vcr: argument drift on tool {tool_name!r}; "
                f"serving recorded interaction seq="
                f"{self.cassette.interactions[fallback].seq} despite mismatch"
            )
            warnings.warn(message, AgentVCRWarning, stacklevel=3)
            self.warnings.append(message)
            return self._materialize(fallback)
        message = (
            f"agent-vcr: no recorded interaction for tool {tool_name!r}; "
            f"lenient replay has nothing left to serve"
        )
        warnings.warn(message, AgentVCRWarning, stacklevel=3)
        self.warnings.append(message)
        raise self._miss_error(tool_name, key_args, note=message)

    def _miss_error(
        self,
        tool_name: str,
        key_args: Dict[str, Any],
        note: Optional[str] = None,
    ) -> CassetteMissError:
        candidates = [
            i for i in self.cassette.interactions if i.tool_name == tool_name
        ]
        if candidates:
            closest = candidates[0]
            diff = _format_arg_diff(closest.args, key_args, closest.seq, tool_name)
        else:
            names = sorted({i.tool_name for i in self.cassette.interactions})
            diff = (
                f"no interaction recorded for tool {tool_name!r}.\n"
                f"recorded tools: {names}\n"
                f"actual args: {json.dumps(key_args, sort_keys=True, ensure_ascii=False)}"
            )
        if note:
            diff = note + "\n" + diff
        return CassetteMissError(
            tool_name=tool_name,
            actual_args=key_args,
            candidates=[c.args for c in candidates],
            diff=diff,
        )


def with_cassette(
    cassette_path: str,
    mode: Optional[str] = None,
    **kwargs: Any,
) -> VCR:
    """Create a :class:`VCR` whose mode defaults to the ``AGENT_VCR_MODE`` env var.

    This is the recommended entry point for test suites: leave ``mode`` unset in
    the code and flip the whole suite between recording and replaying from the
    outside, e.g. ``AGENT_VCR_MODE=record pytest`` to re-record and plain
    ``pytest`` to replay (``auto`` is the fallback when the variable is unset).

    Use it as a context manager; the cassette is saved on clean exit::

        with with_cassette("cassettes/checkout.json") as vcr:
            tool = vcr.wrap_tool("search", search)
            run_agent(tool)

    Args:
        cassette_path: Path of the cassette file to record to or replay from.
        mode: Explicit mode; when ``None`` the ``AGENT_VCR_MODE`` environment
            variable is used, defaulting to ``auto``.
        **kwargs: Forwarded to :class:`VCR` (matchers, redactor, ...).

    Returns:
        A configured :class:`VCR` instance (also usable as a context manager).
    """
    if mode is None:
        mode = os.environ.get("AGENT_VCR_MODE", AUTO)
    return VCR(cassette_path, mode=mode, **kwargs)


def _normalize_args(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Dict[str, Any]:
    """Bind ``args``/``kwargs`` to parameter names for a stable representation.

    Positional and keyword arguments are mapped onto the callable's parameter
    names via :func:`inspect.signature`, so ``f("Tokyo")`` and ``f(city="Tokyo")``
    normalize to the same ``{"city": "Tokyo"}``. Callables without an
    introspectable signature fall back to ``{"args": [...], "kwargs": {...}}``.
    """
    try:
        signature = inspect.signature(fn)
        bound = signature.bind(*args, **kwargs)
        normalized: Dict[str, Any] = {}
        for param_name, value in bound.arguments.items():
            if param_name in ("self", "cls"):
                continue
            param = signature.parameters[param_name]
            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                normalized[param_name] = list(value)
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                normalized.update(value)
            else:
                normalized[param_name] = value
        return normalized
    except (TypeError, ValueError):
        return {"args": list(args), "kwargs": dict(kwargs)}


def _format_arg_diff(
    recorded: Dict[str, Any],
    actual: Dict[str, Any],
    seq: int,
    tool_name: str,
) -> str:
    """Build a human-readable expected-vs-actual argument diff."""
    lines = [f"closest recording: seq={seq} tool={tool_name!r}"]
    keys = sorted(set(recorded) | set(actual))
    lines.append("  arg            expected (recorded)      actual")
    for key in keys:
        r = recorded.get(key, "<absent>")
        a = actual.get(key, "<absent>")
        marker = "  " if r == a else "!!"
        lines.append(
            f"{marker} {key:<12} {json.dumps(r, ensure_ascii=False):<24} "
            f"{json.dumps(a, ensure_ascii=False)}"
        )
    return "\n".join(lines)
