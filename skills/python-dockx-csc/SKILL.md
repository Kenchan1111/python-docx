---
name: python-dockx-csc
description: Use when working in /home/zack/Documents/Python_Dockx on the local python-docx fork, CSC automation addons, roadworks DOCX templates, review synchronization, or cross-agent handoffs for this document-generation project.
---

# Python_Dockx CSC

Use this skill at startup or when changing `Python_Dockx`.

## Project Frame

This repository is a local `python-docx` fork plus project-specific assets for automating CSC documents for roadworks. Treat it as document-generation infrastructure, not as the Excel workbook app from `Gestion_Projet`.

Preserve upstream `python-docx` behavior unless the task explicitly targets a local extension. Keep changes small, covered by tests, and compatible with OOXML round-tripping expectations.

## Startup

1. Check `git status --short` and do not overwrite user work.
2. Inspect the task surface before editing:
   - library behavior: `src/docx/`, `tests/`
   - CSC examples: `csc_samples/`
   - annotations and extraction hints: `annotations/`
   - review sync: `scripts/sync_reviews.py`, `review/`, `mcp/catalog.json`
3. For code changes, run a narrow baseline with `PYTHONPATH=src`.

## Review Sync

The local sync layout is:

```text
review/
  agents.json
  _protocol/
  claude/{handoff,proposition,corrections}/
  codex/{handoff,proposition,corrections}/
  kimi/{handoff,proposition,corrections}/
  global_handoff/
knowledge/80_summaries/
mcp/catalog.json
```

Use:

```bash
python3 scripts/sync_review_bootstrap.py --root .
python3 scripts/check_handoff.py --all
python3 scripts/sync_reviews.py --once
```

Handoffs, propositions, and corrections require frontmatter: `id`, `title`, `date`, `status`, `agent`, `type`, `synopsis`. Handoffs also require `reviewed_revision`.

Never import the review history from `Gestion_Projet` or `Depollution_Sols` into this repo. Use those repos as patterns only.

## CSC Automation Guardrails

- Use structured DOCX/OOXML APIs where possible; avoid raw string edits inside zipped XML unless no safer API exists.
- Keep roadworks domain assumptions explicit. A CSC text generator may consume CPN/Qualiroutes knowledge, but it must not claim workbook-style quantity validation unless such evidence exists in this repo.
- When adding template extraction or annotation logic, keep sample file paths local and deterministic.
- For binary `.doc` and `.docx` samples, do not rewrite samples unless the user asks.

## Handoffs

Write a handoff when a change affects sync infrastructure, CSC document assumptions, OOXML behavior, or future agent work. Include the exact revision, files touched, validation run, and the next requested action.
