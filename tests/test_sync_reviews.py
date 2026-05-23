from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

sync_reviews = importlib.import_module("sync_reviews")


def configure_sync_root(monkeypatch, root: Path) -> None:
    review_root = root / "review"
    monkeypatch.setattr(sync_reviews, "ROOT", root)
    monkeypatch.setattr(sync_reviews, "REVIEW_ROOT", review_root)
    monkeypatch.setattr(sync_reviews, "GLOBAL_HANDOFF_DIR", review_root / "global_handoff")
    monkeypatch.setattr(sync_reviews, "AGENTS_FILE", review_root / "agents.json")
    monkeypatch.setattr(
        sync_reviews,
        "SUMMARY_FILE",
        root / "knowledge" / "80_summaries" / "team_review_latest.md",
    )
    monkeypatch.setattr(
        sync_reviews,
        "CHANGELOG_FILE",
        root / "knowledge" / "80_summaries" / "team_review_changelog.md",
    )
    monkeypatch.setattr(sync_reviews, "CATALOG_FILE", root / "mcp" / "catalog.json")
    monkeypatch.setattr(sync_reviews, "SYNC_STATE_FILE", root / "mcp" / "review_sync_state.json")


def write_agents(root: Path) -> None:
    path = root / "review" / "agents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agents": [
                    {"id": "claude", "display_name": "Claude"},
                    {"id": "codex", "display_name": "Codex"},
                ],
            },
        )
        + "\n",
        encoding="utf-8",
    )


def write_handoff(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "id: codex-001",
                "title: Test handoff",
                "date: 2026-05-21",
                "status: active",
                "agent: codex",
                "type: handoff",
                "synopsis: Test sync note.",
                "reviewed_revision: abc123+dirty",
                "---",
                "",
                "# Test handoff",
                "",
                "A short body.",
                "",
            ],
        ),
        encoding="utf-8",
    )


def it_runs_sync_collects_receipts_catalog_and_broadcast(monkeypatch, tmp_path):
    configure_sync_root(monkeypatch, tmp_path)
    write_agents(tmp_path)
    source = tmp_path / "review" / "codex" / "handoff" / "001_2026-05-21_test.md"
    write_handoff(source)

    assert sync_reviews.run_sync() == 0

    global_copy = tmp_path / "review" / "global_handoff" / "codex" / "handoff" / source.name
    claude_copy = tmp_path / "review" / "claude" / "handoff" / "codex" / "handoff" / source.name
    catalog = json.loads((tmp_path / "mcp" / "catalog.json").read_text(encoding="utf-8"))

    assert global_copy.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert claude_copy.exists()
    assert Path(f"{source}.receipt.json").exists()
    assert Path(f"{global_copy}.receipt.json").exists()
    assert catalog["stats"]["errors"] == 0
    assert catalog["stats"]["documents"] >= 2


def it_reports_missing_frontmatter(monkeypatch, tmp_path):
    configure_sync_root(monkeypatch, tmp_path)
    write_agents(tmp_path)
    note = tmp_path / "review" / "codex" / "handoff" / "001_2026-05-21_bad.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Missing frontmatter\n", encoding="utf-8")

    assert sync_reviews.run_sync() == 1

    catalog = json.loads((tmp_path / "mcp" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["stats"]["errors"] == 1
    assert "missing YAML frontmatter" in catalog["errors"][0]
