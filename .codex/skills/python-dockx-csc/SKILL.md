---
name: python-dockx-csc-codex
description: Codex-specific mirror for /home/zack/Documents/Python_Dockx CSC DOCX automation work, including local python-docx changes, review sync, handoffs, and bundled repo tool dispatch.
---

# Python_Dockx CSC Codex

Use this skill when Codex works in `/home/zack/Documents/Python_Dockx`.

Follow the canonical repository skill at `skills/python-dockx-csc/SKILL.md`.
This mirror sets the authoring namespace to `review/codex/` and should not
write Claude or Kimi-authored findings except through sync-generated copies.

## Commands

```bash
python3 .codex/skills/python-dockx-csc/scripts/python_dockx_csc.py check-handoff --all
python3 .codex/skills/python-dockx-csc/scripts/python_dockx_csc.py sync --once
python3 .codex/skills/python-dockx-csc/scripts/python_dockx_csc.py extract-questions csc_samples/"Chapitre A - modele.docx"
```

## Handoff Rule

When Codex changes code, sync rules, CSC annotations, or skill behavior, write
the authored note under `review/codex/{handoff,proposition,corrections}/` and
run `python3 scripts/sync_reviews.py --once`.
