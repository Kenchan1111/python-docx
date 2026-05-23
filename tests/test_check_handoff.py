from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

check_handoff = importlib.import_module("check_handoff")


def configure_lint_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(check_handoff, "PROJECT_ROOT", root)
    monkeypatch.setattr(check_handoff, "REVIEW_ROOT", root / "review")
    monkeypatch.setattr(check_handoff, "AGENTS_FILE", root / "review" / "agents.json")


def write_agents(root: Path) -> None:
    path = root / "review" / "agents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "agents": [{"id": "codex"}]}) + "\n",
        encoding="utf-8",
    )


def it_accepts_valid_handoff_note(monkeypatch, tmp_path):
    configure_lint_root(monkeypatch, tmp_path)
    write_agents(tmp_path)
    note = tmp_path / "review" / "codex" / "handoff" / "001_2026-05-21_valid.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "\n".join(
            [
                "---",
                "id: codex-001",
                "title: Valid handoff",
                "date: 2026-05-21",
                "status: active",
                "agent: codex",
                "type: handoff",
                "synopsis: Valid note.",
                "reviewed_revision: abc123+dirty",
                "---",
                "",
            ],
        ),
        encoding="utf-8",
    )

    report = check_handoff.lint_handoff(note, {"codex"})

    assert report.errors == 0


def it_rejects_missing_frontmatter(monkeypatch, tmp_path):
    configure_lint_root(monkeypatch, tmp_path)
    write_agents(tmp_path)
    note = tmp_path / "review" / "codex" / "handoff" / "001_2026-05-21_invalid.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Invalid\n", encoding="utf-8")

    report = check_handoff.lint_handoff(note, {"codex"})

    assert report.errors == 1
    assert report.issues[0].code == "frontmatter_missing"
