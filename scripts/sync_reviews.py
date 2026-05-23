#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for minimal Python envs.
    yaml = None


ROOT = Path(__file__).resolve().parent.parent
REVIEW_ROOT = ROOT / "review"
GLOBAL_HANDOFF_DIR = REVIEW_ROOT / "global_handoff"
AGENTS_FILE = REVIEW_ROOT / "agents.json"
SUMMARY_FILE = ROOT / "knowledge" / "80_summaries" / "team_review_latest.md"
CHANGELOG_FILE = ROOT / "knowledge" / "80_summaries" / "team_review_changelog.md"
CATALOG_FILE = ROOT / "mcp" / "catalog.json"
SYNC_STATE_FILE = ROOT / "mcp" / "review_sync_state.json"

REVIEW_KINDS = ("handoff", "proposition", "corrections")
COMMON_REQUIRED_FRONTMATTER = {"id", "title", "date", "status", "agent", "type", "synopsis"}
HANDOFF_REQUIRED_FRONTMATTER = COMMON_REQUIRED_FRONTMATTER | {"reviewed_revision"}
DEFAULT_AGENTS = ("claude", "codex", "kimi")


def now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def short_digest(path: Path) -> str:
    return sha256_hex(path)[:12]


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_agents() -> list[str]:
    payload = load_json(AGENTS_FILE)
    agents: list[str] = []
    for agent in payload.get("agents", []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("id") or "").strip()
        if agent_id:
            agents.append(agent_id)

    if not agents:
        agents = list(DEFAULT_AGENTS)

    return sorted(set(agents))


def ensure_review_dirs(agents: list[str]) -> None:
    for path in (
        GLOBAL_HANDOFF_DIR,
        REVIEW_ROOT / "_protocol",
        ROOT / "knowledge" / "80_summaries",
        ROOT / "mcp",
    ):
        path.mkdir(parents=True, exist_ok=True)

    for agent in agents:
        for kind in REVIEW_KINDS:
            (REVIEW_ROOT / agent / kind).mkdir(parents=True, exist_ok=True)


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str, bool]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text, False

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, False

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}, text, False

    raw = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1 :]).lstrip("\n")
    metadata: dict[str, Any]
    if yaml is not None:
        parsed = yaml.safe_load(raw) or {}
        metadata = parsed if isinstance(parsed, dict) else {}
    else:
        metadata = parse_simple_frontmatter(raw)
    return normalize_metadata(metadata), body, True


def parse_simple_frontmatter(raw: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def normalize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_metadata(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


def title_from_body(body: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else fallback


def first_paragraph(body: str, max_chars: int = 280) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:max_chars] + ("..." if len(stripped) > max_chars else "")
    return ""


def iter_authored_markdown(agent: str, kind: str) -> list[Path]:
    source_dir = REVIEW_ROOT / agent / kind
    if not source_dir.exists():
        return []
    return sorted(
        path
        for path in source_dir.glob("*.md")
        if path.is_file() and path.stem.upper() != "README"
    )


def iter_global_root_markdown() -> list[Path]:
    if not GLOBAL_HANDOFF_DIR.exists():
        return []
    return sorted(
        path
        for path in GLOBAL_HANDOFF_DIR.glob("*.md")
        if path.is_file() and path.stem.upper() != "README"
    )


def iter_structured_global_markdown(agents: list[str]) -> list[tuple[str, str, Path]]:
    documents: list[tuple[str, str, Path]] = []
    if not GLOBAL_HANDOFF_DIR.exists():
        return documents

    agent_set = set(agents)
    for source_dir in sorted(GLOBAL_HANDOFF_DIR.iterdir()):
        if not source_dir.is_dir() or source_dir.name not in agent_set:
            continue
        source_agent = source_dir.name
        for kind in REVIEW_KINDS:
            kind_dir = source_dir / kind
            if not kind_dir.exists():
                continue
            for path in sorted(kind_dir.glob("*.md")):
                if path.is_file() and path.stem.upper() != "README":
                    documents.append((source_agent, kind, path))
    return documents


def validate_frontmatter(
    path: Path,
    kind: str,
    metadata: dict[str, Any],
    has_frontmatter: bool,
) -> list[str]:
    errors: list[str] = []
    if not has_frontmatter:
        return [f"{rel(path)}: missing YAML frontmatter"]

    required = HANDOFF_REQUIRED_FRONTMATTER if kind == "handoff" else COMMON_REQUIRED_FRONTMATTER
    missing = sorted(key for key in required if not metadata.get(key))
    if missing:
        errors.append(f"{rel(path)}: missing required frontmatter fields: {', '.join(missing)}")
    return errors


def receipt_path(note_path: Path) -> Path:
    return Path(f"{note_path}.receipt.json")


def receipt_core(
    note_path: Path,
    *,
    source_agent: str,
    kind: str,
    source_note_path: Path | None = None,
) -> dict[str, Any]:
    metadata, body, has_frontmatter = parse_frontmatter(note_path)
    note_hash = sha256_hex(note_path)
    identifier = str(metadata.get("review_session_id") or metadata.get("id") or note_path.stem)
    title = str(metadata.get("title") or title_from_body(body, note_path.stem))
    warnings = validate_frontmatter(note_path, kind, metadata, has_frontmatter)

    payload: dict[str, Any] = {
        "receipt_version": 2,
        "generated_by": "scripts/sync_reviews.py",
        "review_session_id": identifier,
        "note_path": str(note_path.resolve()),
        "note_rel_path": rel(note_path),
        "note_sha256": note_hash,
        "sha256": note_hash,
        "source_path": rel(note_path),
        "agent": str(metadata.get("agent") or source_agent),
        "source_agent": source_agent,
        "review_kind": kind,
        "title": title,
        "date": str(metadata.get("date") or ""),
        "status": str(metadata.get("status") or ""),
        "reviewed_revision": str(metadata.get("reviewed_revision") or "unavailable"),
        "frontmatter_valid": not warnings,
        "frontmatter_warnings": warnings,
    }
    if source_note_path is not None:
        payload["source_note_path"] = str(source_note_path.resolve())
        payload["source_note_rel_path"] = rel(source_note_path)
        payload["source_note_sha256"] = sha256_hex(source_note_path)
    return payload


def stable_receipt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "updated_at"}
    }


def ensure_receipt(
    note_path: Path,
    *,
    source_agent: str,
    kind: str,
    source_note_path: Path | None = None,
) -> str:
    path = receipt_path(note_path)
    core = receipt_core(
        note_path,
        source_agent=source_agent,
        kind=kind,
        source_note_path=source_note_path,
    )
    existing = load_json(path)
    if existing and stable_receipt_payload(existing) == core:
        return "unchanged"

    previous_generated_at = existing.get("generated_at") if isinstance(existing, dict) else None
    payload = dict(core)
    payload["generated_at"] = str(previous_generated_at or now_local())
    payload["updated_at"] = now_local()
    atomic_write_json(path, payload)
    return "created" if not existing else "updated"


def copy_markdown_if_changed(source_file: Path, target_file: Path) -> str:
    source_bytes = source_file.read_bytes()
    if target_file.exists() and target_file.read_bytes() == source_bytes:
        return "unchanged"
    atomic_write_bytes(target_file, source_bytes)
    return "created" if not target_file.exists() else "updated"


def sync_record(
    *,
    channel: str,
    source_file: Path,
    target_file: Path,
    status: str,
    source_agent: str,
    target_agent: str,
    kind: str,
) -> dict[str, str]:
    return {
        "sync_key": f"{channel}::{rel(source_file)}::{rel(target_file)}",
        "channel": channel,
        "source_agent": source_agent,
        "target_agent": target_agent,
        "review_kind": kind,
        "source_path": rel(source_file),
        "target_path": rel(target_file),
        "digest": sha256_hex(source_file),
        "status": status,
    }


def collect_authored_documents(
    agents: list[str],
) -> tuple[dict[str, int], list[dict[str, str]], list[str]]:
    stats = defaultdict(int)
    records: list[dict[str, str]] = []
    errors: list[str] = []

    for agent in agents:
        for kind in REVIEW_KINDS:
            for source_file in iter_authored_markdown(agent, kind):
                metadata, _, has_frontmatter = parse_frontmatter(source_file)
                errors.extend(validate_frontmatter(source_file, kind, metadata, has_frontmatter))
                ensure_receipt(source_file, source_agent=agent, kind=kind)

                target_file = GLOBAL_HANDOFF_DIR / agent / kind / source_file.name
                existed = target_file.exists()
                status = copy_markdown_if_changed(source_file, target_file)
                if status == "updated" and not existed:
                    status = "created"
                ensure_receipt(
                    target_file,
                    source_agent=agent,
                    kind=kind,
                    source_note_path=source_file,
                )

                stats[status] += 1
                records.append(
                    sync_record(
                        channel="collect",
                        source_file=source_file,
                        target_file=target_file,
                        status=status,
                        source_agent=agent,
                        target_agent="global_handoff",
                        kind=kind,
                    )
                )

    return dict(stats), records, errors


def broadcast_documents(agents: list[str]) -> tuple[dict[str, int], list[dict[str, str]]]:
    stats = defaultdict(int)
    records: list[dict[str, str]] = []

    for source_file in iter_global_root_markdown():
        ensure_receipt(source_file, source_agent="global", kind="handoff")
        for target_agent in agents:
            target_file = REVIEW_ROOT / target_agent / "handoff" / "global" / source_file.name
            existed = target_file.exists()
            status = copy_markdown_if_changed(source_file, target_file)
            if status == "updated" and not existed:
                status = "created"
            ensure_receipt(
                target_file,
                source_agent="global",
                kind="handoff",
                source_note_path=source_file,
            )
            stats[status] += 1
            records.append(
                sync_record(
                    channel="broadcast",
                    source_file=source_file,
                    target_file=target_file,
                    status=status,
                    source_agent="global",
                    target_agent=target_agent,
                    kind="handoff",
                )
            )

    for source_agent, kind, source_file in iter_structured_global_markdown(agents):
        ensure_receipt(source_file, source_agent=source_agent, kind=kind)
        for target_agent in agents:
            if target_agent == source_agent:
                continue
            target_file = (
                REVIEW_ROOT
                / target_agent
                / "handoff"
                / source_agent
                / kind
                / source_file.name
            )
            existed = target_file.exists()
            status = copy_markdown_if_changed(source_file, target_file)
            if status == "updated" and not existed:
                status = "created"
            ensure_receipt(
                target_file,
                source_agent=source_agent,
                kind=kind,
                source_note_path=source_file,
            )
            stats[status] += 1
            records.append(
                sync_record(
                    channel="broadcast",
                    source_file=source_file,
                    target_file=target_file,
                    status=status,
                    source_agent=source_agent,
                    target_agent=target_agent,
                    kind=kind,
                )
            )

    return dict(stats), records


def document_entry(path: Path, *, owner_agent: str, kind: str, collection: str) -> dict[str, Any]:
    metadata, body, has_frontmatter = parse_frontmatter(path)
    stat = path.stat()
    return {
        "path": rel(path),
        "owner_agent": owner_agent,
        "review_kind": kind,
        "collection": collection,
        "title": str(metadata.get("title") or title_from_body(body, path.stem)),
        "id": str(metadata.get("id") or path.stem),
        "status": str(metadata.get("status") or ""),
        "date": str(metadata.get("date") or ""),
        "agent": str(metadata.get("agent") or owner_agent),
        "reviewed_revision": str(metadata.get("reviewed_revision") or ""),
        "has_frontmatter": has_frontmatter,
        "frontmatter_errors": validate_frontmatter(path, kind, metadata, has_frontmatter),
        "digest": short_digest(path),
        "bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "synopsis": str(metadata.get("synopsis") or first_paragraph(body)),
        "receipt": rel(receipt_path(path)) if receipt_path(path).exists() else "",
    }


def scan_documents(agents: list[str]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for agent in agents:
        for kind in REVIEW_KINDS:
            for path in iter_authored_markdown(agent, kind):
                documents.append(
                    document_entry(path, owner_agent=agent, kind=kind, collection="authored"),
                )

    for path in iter_global_root_markdown():
        documents.append(
            document_entry(
                path,
                owner_agent="global",
                kind="handoff",
                collection="global_root",
            ),
        )

    for source_agent, kind, path in iter_structured_global_markdown(agents):
        documents.append(
            document_entry(
                path,
                owner_agent=source_agent,
                kind=kind,
                collection="global_structured",
            ),
        )

    return sorted(
        documents,
        key=lambda item: (
            item["collection"],
            item["owner_agent"],
            item["review_kind"],
            item["path"],
        ),
    )


def nonzero_stats(stats: dict[str, int]) -> dict[str, int]:
    return {key: stats.get(key, 0) for key in ("created", "updated", "unchanged")}


def write_catalog(
    *,
    agents: list[str],
    documents: list[dict[str, Any]],
    collect_stats: dict[str, int],
    broadcast_stats: dict[str, int],
    collect_records: list[dict[str, str]],
    broadcast_records: list[dict[str, str]],
    errors: list[str],
) -> None:
    counts_by_kind: dict[str, int] = defaultdict(int)
    counts_by_owner: dict[str, int] = defaultdict(int)
    for document in documents:
        counts_by_kind[str(document["review_kind"])] += 1
        counts_by_owner[str(document["owner_agent"])] += 1

    payload = {
        "schema_version": 1,
        "last_sync": now_local(),
        "agents": agents,
        "stats": {
            "documents": len(documents),
            "errors": len(errors),
            "collect": nonzero_stats(collect_stats),
            "broadcast": nonzero_stats(broadcast_stats),
            "by_kind": dict(sorted(counts_by_kind.items())),
            "by_owner": dict(sorted(counts_by_owner.items())),
        },
        "documents": documents,
        "collect_records": collect_records,
        "broadcast_records": broadcast_records,
        "errors": errors,
    }
    atomic_write_json(CATALOG_FILE, payload)


def write_sync_state(
    collect_records: list[dict[str, str]],
    broadcast_records: list[dict[str, str]],
) -> None:
    payload = {
        "schema_version": 1,
        "last_sync": now_local(),
        "records": collect_records + broadcast_records,
    }
    atomic_write_json(SYNC_STATE_FILE, payload)


def write_summary(
    documents: list[dict[str, Any]],
    collect_stats: dict[str, int],
    broadcast_stats: dict[str, int],
    errors: list[str],
) -> None:
    lines = [
        "# Python_Dockx CSC Review Sync",
        f"Derniere mise a jour: {now_local()}",
        "",
        f"- Documents indexes: {len(documents)}",
        (
            "- Collecte: "
            f"{collect_stats.get('created', 0)} crees, "
            f"{collect_stats.get('updated', 0)} mis a jour, "
            f"{collect_stats.get('unchanged', 0)} inchanges"
        ),
        (
            "- Diffusion: "
            f"{broadcast_stats.get('created', 0)} crees, "
            f"{broadcast_stats.get('updated', 0)} mis a jour, "
            f"{broadcast_stats.get('unchanged', 0)} inchanges"
        ),
        f"- Erreurs: {len(errors)}",
        "",
        "| Collection | Owner | Kind | Title | Status | Path |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for document in documents:
        lines.append(
            f"| `{document['collection']}` | `{document['owner_agent']}` | "
            f"`{document['review_kind']}` | {document['title']} | "
            f"`{document['status']}` | `{document['path']}` |"
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
    atomic_write_text(SUMMARY_FILE, "\n".join(lines) + "\n")


def append_changelog(
    collect_stats: dict[str, int],
    broadcast_stats: dict[str, int],
    document_count: int,
    error_count: int,
) -> None:
    lines = [
        f"\n## Sync {now_local()}",
        (
            "- Collecte: "
            f"{collect_stats.get('created', 0)} crees, "
            f"{collect_stats.get('updated', 0)} mis a jour, "
            f"{collect_stats.get('unchanged', 0)} inchanges"
        ),
        (
            "- Diffusion: "
            f"{broadcast_stats.get('created', 0)} crees, "
            f"{broadcast_stats.get('updated', 0)} mis a jour, "
            f"{broadcast_stats.get('unchanged', 0)} inchanges"
        ),
        f"- Documents indexes: {document_count}",
        f"- Erreurs: {error_count}",
    ]
    append_text(CHANGELOG_FILE, "\n".join(lines) + "\n")


def run_sync() -> int:
    agents = load_agents()
    ensure_review_dirs(agents)
    collect_stats, collect_records, errors = collect_authored_documents(agents)
    broadcast_stats, broadcast_records = broadcast_documents(agents)
    documents = scan_documents(agents)

    write_catalog(
        agents=agents,
        documents=documents,
        collect_stats=collect_stats,
        broadcast_stats=broadcast_stats,
        collect_records=collect_records,
        broadcast_records=broadcast_records,
        errors=errors,
    )
    write_sync_state(collect_records, broadcast_records)
    write_summary(documents, collect_stats, broadcast_stats, errors)
    append_changelog(collect_stats, broadcast_stats, len(documents), len(errors))

    print(
        "Review sync OK - "
        f"agents={len(agents)}, "
        f"collect_created={collect_stats.get('created', 0)}, "
        f"collect_updated={collect_stats.get('updated', 0)}, "
        f"broadcast_created={broadcast_stats.get('created', 0)}, "
        f"broadcast_updated={broadcast_stats.get('updated', 0)}, "
        f"documents={len(documents)}, "
        f"errors={len(errors)}"
    )
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize Python_Dockx CSC review handoffs and receipts.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sync pass. This is the default.",
    )
    parser.parse_args()
    return run_sync()


if __name__ == "__main__":
    sys.exit(main())
