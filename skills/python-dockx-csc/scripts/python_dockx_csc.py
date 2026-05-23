#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

COMMANDS = {
    "audit-coverage": ("tools", "audit_coverage.py"),
    "bootstrap": ("scripts", "sync_review_bootstrap.py"),
    "check-handoff": ("scripts", "check_handoff.py"),
    "dump-paragraphs": ("tools", "dump_paragraphs.py"),
    "extract-questions": ("tools", "extract_questions.py"),
    "sync": ("scripts", "sync_reviews.py"),
    "watch": ("scripts", "sync_reviews_watch.py"),
}


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "docx").exists():
            return candidate
    raise RuntimeError(f"Cannot locate Python_Dockx repo root from {start}")


def usage() -> str:
    commands = ", ".join(sorted(COMMANDS))
    return f"Usage: {Path(sys.argv[0]).name} <command> [args...]\nCommands: {commands}"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(usage())
        return 0 if argv else 2

    command, *rest = argv
    if command not in COMMANDS:
        print(f"Unknown command: {command}\n{usage()}", file=sys.stderr)
        return 2

    folder, filename = COMMANDS[command]
    repo_root = find_repo_root(Path(__file__).resolve())
    target = repo_root / folder / filename
    if not target.exists():
        print(f"Target script not found: {target}", file=sys.stderr)
        return 2

    sys.argv = [str(target), *rest]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
