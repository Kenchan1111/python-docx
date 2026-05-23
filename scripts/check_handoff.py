#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = PROJECT_ROOT / "review"
AGENTS_FILE = REVIEW_ROOT / "agents.json"
REVIEW_KINDS = ("handoff", "proposition", "corrections")
DEFAULT_AGENTS = ("claude", "codex", "kimi")

COMMON_REQUIRED_FRONTMATTER = (
    "id",
    "title",
    "date",
    "status",
    "agent",
    "type",
    "synopsis",
)
HANDOFF_REQUIRED_FRONTMATTER = COMMON_REQUIRED_FRONTMATTER + ("reviewed_revision",)
VALID_STATUS = {"draft", "proposed", "active", "accepted", "completed", "superseded"}
ID_PATTERN = re.compile(r"^(?P<agent>[a-z][a-z0-9_-]*)-(?P<number>\d{3})$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILENAME_PATTERN = re.compile(r"^(?P<number>\d{3})_(?P<date>\d{4}-\d{2}-\d{2})_.+\.md$")


@dataclass
class LintIssue:
    severity: str
    code: str
    message: str


@dataclass
class LintReport:
    path: str
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "errors": self.errors,
            "warnings": self.warnings,
            "issues": [asdict(issue) for issue in self.issues],
        }


def load_agents() -> set[str]:
    if not AGENTS_FILE.exists():
        return set(DEFAULT_AGENTS)

    try:
        payload = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return set(DEFAULT_AGENTS)

    agents: set[str] = set()
    for agent in payload.get("agents", []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("id") or "").strip()
        if agent_id:
            agents.add(agent_id)
    return agents or set(DEFAULT_AGENTS)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, text
    return text[4:end], text[end + 5 :]


def parse_simple_frontmatter(raw: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list_key and line.startswith((" ", "\t")) and stripped.startswith("- "):
            metadata.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            metadata[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            metadata[key] = [item.strip() for item in inner.split(",") if item.strip()]
        elif (
            value.startswith('"')
            and value.endswith('"')
            or value.startswith("'")
            and value.endswith("'")
        ):
            metadata[key] = value[1:-1]
        elif value.lower() in {"true", "false"}:
            metadata[key] = value.lower() == "true"
        else:
            metadata[key] = value
    return metadata


def infer_agent_and_kind(path: Path) -> tuple[str | None, str | None]:
    try:
        parts = path.resolve().relative_to(REVIEW_ROOT.resolve()).parts
    except ValueError:
        return None, None
    if len(parts) >= 3 and parts[1] in REVIEW_KINDS:
        return parts[0], parts[1]
    return None, None


def lint_handoff(path: Path, agents: set[str]) -> LintReport:
    report = LintReport(path=str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        report.issues.append(LintIssue("error", "io", f"Cannot read file: {exc}"))
        return report

    raw_frontmatter, _body = split_frontmatter(text)
    if raw_frontmatter is None:
        report.issues.append(LintIssue("error", "frontmatter_missing", "Missing YAML frontmatter"))
        return report

    metadata = parse_simple_frontmatter(raw_frontmatter)
    path_agent, path_kind = infer_agent_and_kind(path)
    declared_kind = str(metadata.get("type") or path_kind or "").strip()
    required = (
        HANDOFF_REQUIRED_FRONTMATTER
        if declared_kind == "handoff"
        else COMMON_REQUIRED_FRONTMATTER
    )

    for field_name in required:
        if not metadata.get(field_name):
            report.issues.append(
                LintIssue("error", "frontmatter_required", f"Missing required field: {field_name}"),
            )

    file_match = FILENAME_PATTERN.match(path.name)
    if file_match is None:
        report.issues.append(
            LintIssue("warning", "filename", "Filename should match NNN_YYYY-MM-DD_subject.md"),
        )

    handoff_id = str(metadata.get("id") or "")
    id_match = ID_PATTERN.match(handoff_id)
    if handoff_id and id_match is None:
        report.issues.append(
            LintIssue("error", "id_format", "id should match <agent>-NNN, for example codex-001"),
        )

    declared_agent = str(metadata.get("agent") or "")
    if declared_agent and declared_agent not in agents:
        report.issues.append(
            LintIssue("error", "agent_unknown", f"Unknown agent: {declared_agent}"),
        )

    if path_agent and declared_agent and path_agent != declared_agent:
        report.issues.append(
            LintIssue("error", "agent_path_mismatch", "agent does not match review/<agent>/ path"),
        )

    if path_kind and declared_kind and path_kind != declared_kind:
        report.issues.append(
            LintIssue(
                "error",
                "type_path_mismatch",
                "type does not match review/<agent>/<type>/ path",
            ),
        )

    if id_match is not None:
        id_agent = id_match.group("agent")
        id_number = id_match.group("number")
        if declared_agent and id_agent != declared_agent:
            report.issues.append(
                LintIssue("error", "id_agent_mismatch", "id agent prefix mismatch"),
            )
        if file_match is not None and id_number != file_match.group("number"):
            report.issues.append(LintIssue("warning", "id_filename_mismatch", "id number mismatch"))

    date = str(metadata.get("date") or "")
    if date and DATE_PATTERN.match(date) is None:
        report.issues.append(LintIssue("error", "date_format", "date should use YYYY-MM-DD"))
    if file_match is not None and date and date != file_match.group("date"):
        report.issues.append(LintIssue("warning", "date_filename_mismatch", "date mismatch"))

    status = str(metadata.get("status") or "")
    if status and status not in VALID_STATUS:
        report.issues.append(LintIssue("warning", "status_unknown", f"Unknown status: {status}"))

    return report


def iter_all_review_files() -> list[Path]:
    files: list[Path] = []
    for agent in sorted(load_agents()):
        for kind in REVIEW_KINDS:
            root = REVIEW_ROOT / agent / kind
            if root.exists():
                files.extend(sorted(path for path in root.glob("*.md") if path.is_file()))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint Python_Dockx CSC review handoff notes.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="Lint review/<agent>/*.md notes.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args()

    files = iter_all_review_files() if args.all else []
    files.extend(args.paths)
    if not files:
        print("No files to lint. Use --all or pass paths.", file=sys.stderr)
        return 2

    agents = load_agents()
    reports = [lint_handoff(path, agents) for path in files]

    if args.json:
        print(
            json.dumps(
                {
                    "files_checked": len(reports),
                    "total_errors": sum(report.errors for report in reports),
                    "total_warnings": sum(report.warnings for report in reports),
                    "reports": [report.to_dict() for report in reports],
                },
                indent=2,
                ensure_ascii=True,
            ),
        )
    else:
        for report in reports:
            path = Path(report.path)
            try:
                label = path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            except ValueError:
                label = report.path
            print(f"{label}: {report.errors} error(s), {report.warnings} warning(s)")
            for issue in report.issues:
                print(f"  {issue.severity}: [{issue.code}] {issue.message}")

    if any(report.errors for report in reports):
        return 1
    if args.strict and any(report.warnings for report in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
