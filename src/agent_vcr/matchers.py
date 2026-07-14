"""Argument matchers used to pair an incoming call with a recorded interaction.

A matcher is any callable ``(recorded_args, actual_args) -> bool``. The default
is deep equality. The helpers here build common relaxed matchers so recorded
cassettes survive noisy fields such as timestamps or floating-point drift.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List

Matcher = Callable[[Dict[str, Any], Dict[str, Any]], bool]


def exact() -> Matcher:
    """Match when recorded and actual arguments are deeply equal."""

    def _match(recorded: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        return recorded == actual

    return _match


def ignore_fields(*paths: str) -> Matcher:
    """Match after removing the given dotted field paths from both sides.

    Example: ``ignore_fields("request_id", "meta.timestamp")`` matches two calls
    that differ only in those fields.
    """

    parts_list = [p.split(".") for p in paths]

    def _match(recorded: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        a = _drop_all(recorded, parts_list)
        b = _drop_all(actual, parts_list)
        return a == b

    return _match


def fuzzy_numbers(rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> Matcher:
    """Match when structures are equal up to numeric tolerance.

    Non-numeric values must be exactly equal; ``int``/``float`` values are
    compared with :func:`math.isclose` using the given tolerances.
    """

    def _match(recorded: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        return _close(recorded, actual, rel_tol, abs_tol)

    return _match


def combine(*matchers: Matcher) -> Matcher:
    """Match only when every supplied matcher matches."""

    def _match(recorded: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        return all(m(recorded, actual) for m in matchers)

    return _match


def subset(*paths: str) -> Matcher:
    """Match when the given dotted paths are present and equal on both sides.

    Fields outside ``paths`` are ignored. Useful when only a few arguments are
    meaningful for identity.
    """

    parts_list = [p.split(".") for p in paths]

    def _match(recorded: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        for parts in parts_list:
            found_r, val_r = _get_path(recorded, parts)
            found_a, val_a = _get_path(actual, parts)
            if not (found_r and found_a) or val_r != val_a:
                return False
        return True

    return _match


def _drop_all(value: Any, parts_list: List[List[str]]) -> Any:
    result = value
    for parts in parts_list:
        result = _drop_path(result, parts)
    return result


def _drop_path(value: Any, parts: List[str]) -> Any:
    if not parts:
        return value
    if isinstance(value, dict):
        head, rest = parts[0], parts[1:]
        new = {}
        for k, v in value.items():
            if k == head:
                if rest:
                    new[k] = _drop_path(v, rest)
                # else: drop this key entirely
            else:
                new[k] = v
        return new
    if isinstance(value, list):
        return [_drop_path(v, parts) for v in value]
    return value


def _get_path(value: Any, parts: List[str]):
    cur = value
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _close(a: Any, b: Any, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_close(a[k], b[k], rel_tol, abs_tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_close(x, y, rel_tol, abs_tol) for x, y in zip(a, b))
    return a == b
