"""Command line interface: inspect and diff cassettes without writing Python.

Subcommands:

- ``agent-vcr ls <dir>``: list cassettes under a directory with step counts.
- ``agent-vcr show <file>``: pretty-print one cassette's trajectory.
- ``agent-vcr diff <a> <b>``: compare two cassettes; exit 1 when they drift.

Exit codes follow ``diff(1)`` conventions: 0 = success / no drift, 1 = drift
detected, 2 = usage or file errors. Errors go to stderr as one readable line,
never as a raw traceback.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .cassette import Cassette, load
from .errors import AgentVCRError

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the ``agent-vcr`` argument parser (exposed for testing)."""
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="agent-vcr",
        description=(
            "Inspect and diff agent-vcr cassettes: recorded AI agent tool calls."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"agent-vcr {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p_ls = sub.add_parser("ls", help="list cassettes in a directory with step counts")
    p_ls.add_argument("directory", help="directory to scan recursively for cassettes")

    p_show = sub.add_parser("show", help="pretty-print a cassette's trajectory")
    p_show.add_argument("cassette", help="path to a cassette JSON file")

    p_diff = sub.add_parser(
        "diff",
        help="compare two cassettes; exit 1 when the trajectories drift",
    )
    p_diff.add_argument("a", help="baseline cassette (expected)")
    p_diff.add_argument("b", help="candidate cassette (actual)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        if args.command == "ls":
            return _cmd_ls(args.directory)
        if args.command == "show":
            return _cmd_show(args.cassette)
        if args.command == "diff":
            return _cmd_diff(args.a, args.b)
    except AgentVCRError as exc:
        print(f"agent-vcr: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"agent-vcr: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_ERROR


# -- ls ---------------------------------------------------------------------


def _iter_cassettes(directory: str) -> Iterator[Tuple[str, Optional[Cassette], str]]:
    """Yield ``(path, cassette_or_none, error_message)`` for JSON files found."""
    for root, _dirs, files in sorted(os.walk(directory)):
        for filename in sorted(files):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(root, filename)
            try:
                yield path, load(path), ""
            except (AgentVCRError, OSError) as exc:
                yield path, None, str(exc).splitlines()[0]


def _cmd_ls(directory: str) -> int:
    if not os.path.isdir(directory):
        print(f"agent-vcr: error: not a directory: {directory}", file=sys.stderr)
        return EXIT_ERROR
    rows: List[Tuple[str, str, str, str]] = []
    for path, cassette, error in _iter_cassettes(directory):
        rel = os.path.relpath(path, directory)
        if cassette is None:
            rows.append((rel, "-", "-", f"skipped: {error}"))
            continue
        tools = sorted({i.tool_name for i in cassette.interactions})
        rows.append((rel, cassette.name, str(len(cassette.interactions)), ", ".join(tools)))
    if not rows:
        print(f"no cassettes found under {directory}")
        return EXIT_OK
    widths = [
        max(len(r[col]) for r in rows + [("CASSETTE", "NAME", "STEPS", "TOOLS")])
        for col in range(4)
    ]
    header = ("CASSETTE", "NAME", "STEPS", "TOOLS")
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)).rstrip())
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return EXIT_OK


# -- show ---------------------------------------------------------------------


def _compact(value: Any, limit: int = 100) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _cmd_show(path: str) -> int:
    if not os.path.isfile(path):
        print(f"agent-vcr: error: no such cassette: {path}", file=sys.stderr)
        return EXIT_ERROR
    cassette = load(path)
    print(f"cassette: {cassette.name}")
    print(f"format version: {cassette.version}")
    print(f"interactions: {len(cassette.interactions)}")
    if cassette.metadata:
        print(f"metadata: {_compact(cassette.metadata)}")
    print()
    for interaction in cassette.interactions:
        tags = f"  tags={interaction.tags}" if interaction.tags else ""
        print(
            f"  {interaction.seq:>3}. {interaction.tool_name}"
            f"({_compact(interaction.args, 70)})"
            f"  [{interaction.duration_ms:.1f} ms]{tags}"
        )
        if interaction.error is not None:
            print(f"       !! error: {interaction.error}")
        else:
            print(f"       -> {_compact(interaction.result)}")
    return EXIT_OK


# -- diff ---------------------------------------------------------------------


def _cmd_diff(path_a: str, path_b: str) -> int:
    for path in (path_a, path_b):
        if not os.path.isfile(path):
            print(f"agent-vcr: error: no such cassette: {path}", file=sys.stderr)
            return EXIT_ERROR
    a, b = load(path_a), load(path_b)
    lines, drift = diff_cassettes(a, b, label_a=path_a, label_b=path_b)
    for line in lines:
        print(line)
    return EXIT_DRIFT if drift else EXIT_OK


def diff_cassettes(
    a: Cassette,
    b: Cassette,
    label_a: str = "a",
    label_b: str = "b",
) -> Tuple[List[str], bool]:
    """Compare two cassettes and return ``(report_lines, drift_detected)``.

    Tool-name sequences are aligned with :class:`difflib.SequenceMatcher` so
    added, removed, and replaced calls are reported positionally; calls whose
    tool names align are then compared argument-by-argument. ``duration_ms``
    is ignored because wall-clock timing is not part of agent behavior.
    """
    seq_a = [i.tool_name for i in a.interactions]
    seq_b = [i.tool_name for i in b.interactions]
    lines: List[str] = [
        f"--- {label_a} ({len(seq_a)} steps)",
        f"+++ {label_b} ({len(seq_b)} steps)",
    ]
    drift = False
    matcher = difflib.SequenceMatcher(a=seq_a, b=seq_b, autojunk=False)
    for op, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if op == "equal":
            for offset in range(a_end - a_start):
                ia = a.interactions[a_start + offset]
                ib = b.interactions[b_start + offset]
                arg_lines = _diff_args(ia.args, ib.args)
                result_changed = _differs(ia, ib)
                if arg_lines or result_changed:
                    drift = True
                    lines.append(f"~ step {ia.seq}: {ia.tool_name} (arguments/outcome differ)")
                    lines.extend(arg_lines)
                    if result_changed:
                        lines.append(f"    result a: {_compact(ia.result)}")
                        lines.append(f"    result b: {_compact(ib.result)}")
                        if (ia.error is None) != (ib.error is None):
                            lines.append(f"    error a: {ia.error}")
                            lines.append(f"    error b: {ib.error}")
                else:
                    lines.append(f"  step {ia.seq}: {ia.tool_name}")
            continue
        drift = True
        if op in ("delete", "replace"):
            for i in a.interactions[a_start:a_end]:
                lines.append(f"- step {i.seq}: {i.tool_name}({_compact(i.args, 70)})")
        if op in ("insert", "replace"):
            for i in b.interactions[b_start:b_end]:
                lines.append(f"+ step {i.seq}: {i.tool_name}({_compact(i.args, 70)})")
    lines.append("drift detected" if drift else "cassettes match")
    return lines, drift


def _differs(ia: Any, ib: Any) -> bool:
    return ia.result != ib.result or (ia.error or None) != (ib.error or None)


def _diff_args(args_a: Dict[str, Any], args_b: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for key in sorted(set(args_a) | set(args_b)):
        va = args_a.get(key, "<absent>")
        vb = args_b.get(key, "<absent>")
        if va != vb:
            lines.append(
                f"    arg {key}: {_compact(va, 60)} -> {_compact(vb, 60)}"
            )
    return lines


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    sys.exit(main())
