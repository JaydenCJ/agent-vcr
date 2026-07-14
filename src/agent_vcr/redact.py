"""Secret redaction so cassettes are safe to commit to git.

Redaction runs at record time on both call arguments and results. Two layers
apply:

1. Built-in patterns for common credential shapes (OpenAI, AWS, GitHub, Slack,
   bearer tokens) and sensitive key names (``api_key``, ``password``, ...).
   A sensitive key masks its entire value, whatever the type: strings,
   numbers, lists, and nested objects are all replaced wholesale.
2. User-supplied dotted paths (for example ``headers.Authorization``) that are
   always masked regardless of their value.

The redacted placeholder is ``[REDACTED]``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Pattern, Tuple

PLACEHOLDER = "[REDACTED]"

# (name, compiled pattern) for values that look like credentials.
_VALUE_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("openai", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("bearer", re.compile(r"[Bb]earer\s+[A-Za-z0-9._\-]{12,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
]

# Dict keys whose values are always masked.
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)


class Redactor:
    """Applies built-in and user-defined redaction to JSON-like structures."""

    def __init__(
        self,
        paths: Iterable[str] = (),
        enabled: bool = True,
        placeholder: str = PLACEHOLDER,
    ) -> None:
        """Create a redactor.

        Args:
            paths: Dotted key paths that should always be masked, e.g.
                ``["headers.Authorization", "user.ssn"]``.
            enabled: When ``False`` the redactor is a no-op.
            placeholder: The string substituted for redacted values.
        """
        self.paths = [p for p in paths]
        self.enabled = enabled
        self.placeholder = placeholder

    def redact(self, value: Any) -> Any:
        """Return a redacted deep copy of ``value``."""
        if not self.enabled:
            return value
        cleaned = self._walk(value, key=None)
        for path in self.paths:
            cleaned = self._mask_path(cleaned, path.split("."))
        return cleaned

    def _walk(self, value: Any, key: Any) -> Any:
        if isinstance(key, str) and _SENSITIVE_KEY.search(key):
            # Mask the whole subtree under a sensitive key: numeric secrets,
            # header value lists, and credential objects are all real shapes,
            # and recursing would lose the key that marked them sensitive.
            return self.placeholder
        if isinstance(value, dict):
            return {k: self._walk(v, key=k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._walk(v, key=None) for v in value]
        if isinstance(value, str):
            return self._scrub_string(value)
        return value

    def _scrub_string(self, text: str) -> str:
        for _name, pattern in _VALUE_PATTERNS:
            text = pattern.sub(self.placeholder, text)
        return text

    def _mask_path(self, value: Any, parts: List[str]) -> Any:
        if not parts:
            return self.placeholder
        head, rest = parts[0], parts[1:]
        if isinstance(value, dict) and head in value:
            new = dict(value)
            new[head] = self._mask_path(new[head], rest)
            return new
        if isinstance(value, list) and head.isdigit():
            index = int(head)
            if 0 <= index < len(value):
                new_list = list(value)
                new_list[index] = self._mask_path(new_list[index], rest)
                return new_list
        return value
