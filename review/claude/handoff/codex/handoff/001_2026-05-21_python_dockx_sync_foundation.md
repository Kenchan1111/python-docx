---
id: codex-001
title: Python_Dockx CSC sync foundation
date: 2026-05-21
status: active
agent: codex
type: handoff
synopsis: Initial local review-sync foundation for the Python_Dockx CSC automation fork.
reviewed_revision: e45454602b53e8e572b179ccf1c91093ec9f4ed7+dirty
---

# Python_Dockx CSC sync foundation

## Context

- repo: `/home/zack/Documents/Python_Dockx`
- objective: improve the local `python-docx` fork and addons for automated CSC document workflows in roadworks projects
- source pattern: review-sync infrastructure adapted from `Gestion_Projet`, originally derived from `Depollution_Sols`

## Decisions

- Keep this review history local to `Python_Dockx`; do not mix imported review notes from the source repositories.
- Use `review/agents.json` as the declarative agent registry.
- Use `scripts/sync_reviews.py --once` to collect authored notes, broadcast global handoffs, create receipt sidecars, and refresh `mcp/catalog.json`.
- Require frontmatter on handoffs, propositions, and corrections. Handoffs also require `reviewed_revision`.

## Current Scope

- Added the sync scripts and initial protocol template.
- Added a first project skill under `skills/python-dockx-csc/`.
- Validation is intentionally focused on the sync layer and a narrow existing python-docx smoke baseline.

## Next Action

- Port/adapt domain skills from the voirie workbook repo only when their assumptions match document automation rather than Excel workbook generation.
