#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_AGENTS = [
    {
        "id": "claude",
        "display_name": "Claude",
        "active": True,
        "model": "unknown",
        "version_source": "not_reported",
    },
    {
        "id": "codex",
        "display_name": "Codex",
        "active": True,
        "model": "unknown",
        "version_source": "not_reported",
    },
    {
        "id": "kimi",
        "display_name": "Kimi",
        "active": True,
        "model": "unknown",
        "version_source": "not_reported",
    },
]


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_or_create_agents(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    payload = {
        "schema_version": 1,
        "policy": {
            "agent_detection": "declarative",
            "delete_inactive_agent_dirs": False,
            "model_version_detection": "manual_or_agent_reported",
            "notes": (
                "Do not call model provider APIs from the sync layer. "
                "Keep Python_Dockx review history separate from Gestion_Projet "
                "and Depollution_Sols."
            ),
        },
        "agents": DEFAULT_AGENTS,
    }
    atomic_write_json(path, payload)
    return payload


def agent_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for agent in payload.get("agents", []):
        if not isinstance(agent, dict):
            continue
        agent_id = agent.get("id")
        if isinstance(agent_id, str) and agent_id.strip():
            ids.append(agent_id.strip())
    return sorted(set(ids))


def ensure_dirs(root: Path, agents: list[str]) -> list[Path]:
    created_or_present: list[Path] = []
    for rel in [
        "review/global_handoff",
        "review/_protocol",
        "knowledge/80_summaries",
        "mcp",
    ]:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        created_or_present.append(path)

    for agent_id in agents:
        for bucket in ("handoff", "proposition", "corrections"):
            path = root / "review" / agent_id / bucket
            path.mkdir(parents=True, exist_ok=True)
            created_or_present.append(path)

    return created_or_present


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure Python_Dockx CSC review sync directories exist.",
    )
    parser.add_argument("--root", default=".", help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    agents_path = root / "review" / "agents.json"
    payload = load_or_create_agents(agents_path)
    agents = agent_ids(payload)
    paths = ensure_dirs(root, agents)

    result = {
        "status": "ok",
        "root": str(root),
        "agents": agents,
        "directories": [str(path.relative_to(root)) for path in paths],
        "policy": {
            "delete_inactive_agent_dirs": False,
            "model_version_detection": "manual_or_agent_reported",
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
