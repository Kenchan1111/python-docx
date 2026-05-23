#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW_ROOT = ROOT / "review"
GLOBAL_HANDOFF_DIR = REVIEW_ROOT / "global_handoff"
SYNC_SCRIPT = ROOT / "scripts" / "sync_reviews.py"
AGENTS_FILE = REVIEW_ROOT / "agents.json"
REVIEW_KINDS = ("handoff", "proposition", "corrections")
DEFAULT_AGENTS = ("claude", "codex", "kimi")


def load_agents() -> tuple[str, ...]:
    if not AGENTS_FILE.exists():
        return DEFAULT_AGENTS
    try:
        payload = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_AGENTS

    agents: list[str] = []
    for agent in payload.get("agents", []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("id") or "").strip()
        if agent_id:
            agents.append(agent_id)
    return tuple(sorted(set(agents))) if agents else DEFAULT_AGENTS


def file_fingerprint(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def capture_snapshot() -> dict[str, object]:
    files: dict[str, list[int]] = {}

    if AGENTS_FILE.exists():
        files[AGENTS_FILE.relative_to(ROOT).as_posix()] = file_fingerprint(AGENTS_FILE)

    if GLOBAL_HANDOFF_DIR.exists():
        for path in sorted(GLOBAL_HANDOFF_DIR.glob("*.md")):
            if path.is_file() and path.stem.upper() != "README":
                files[path.relative_to(ROOT).as_posix()] = file_fingerprint(path)

    for agent in load_agents():
        for kind in REVIEW_KINDS:
            source_dir = REVIEW_ROOT / agent / kind
            if not source_dir.exists():
                continue
            for path in sorted(source_dir.glob("*.md")):
                if path.is_file() and path.stem.upper() != "README":
                    files[path.relative_to(ROOT).as_posix()] = file_fingerprint(path)

    return {"agents": list(load_agents()), "files": files}


def sync_once() -> int:
    command = [sys.executable, str(SYNC_SCRIPT), "--once"]
    result = subprocess.run(command, check=False, cwd=str(ROOT))
    return result.returncode


def watch_loop(poll_seconds: float, debounce_seconds: float) -> int:
    print(
        "Python_Dockx CSC review sync watcher started - "
        f"poll={poll_seconds}s debounce={debounce_seconds}s root={ROOT}"
    )

    if sync_once() != 0:
        return 1

    last_applied = capture_snapshot()
    pending_snapshot: str | None = None
    pending_since = 0.0

    while True:
        current = capture_snapshot()
        current_serialized = json.dumps(current, sort_keys=True)
        applied_serialized = json.dumps(last_applied, sort_keys=True)

        if current_serialized == applied_serialized:
            pending_snapshot = None
            pending_since = 0.0
            time.sleep(poll_seconds)
            continue

        if pending_snapshot != current_serialized:
            pending_snapshot = current_serialized
            pending_since = time.monotonic()
            time.sleep(poll_seconds)
            continue

        if time.monotonic() - pending_since < debounce_seconds:
            time.sleep(poll_seconds)
            continue

        print("Change detected in Python_Dockx CSC review sources - running sync.")
        if sync_once() != 0:
            return 1
        last_applied = capture_snapshot()
        pending_snapshot = None
        pending_since = 0.0
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Watch and synchronize Python_Dockx CSC review handoffs.",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--debounce-seconds", type=float, default=2.0)
    args = parser.parse_args()
    return watch_loop(args.poll_seconds, args.debounce_seconds)


if __name__ == "__main__":
    sys.exit(main())
