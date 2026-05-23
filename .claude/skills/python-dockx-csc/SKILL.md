---
name: python-dockx-csc-claude
description: Claude-specific mirror for /home/zack/Documents/Python_Dockx CSC DOCX automation work, including local python-docx changes, review sync, handoffs, and bundled repo tool dispatch.
---

# Python_Dockx CSC Claude

Use this skill when Claude works in `/home/zack/Documents/Python_Dockx`.

Follow the canonical repository skill at `skills/python-dockx-csc/SKILL.md`.
This mirror sets the authoring namespace to `review/claude/` and should not
rewrite Codex or Kimi-authored findings; add a Claude handoff or correction.

## Commands

```bash
python3 .claude/skills/python-dockx-csc/scripts/python_dockx_csc.py check-handoff --all
python3 .claude/skills/python-dockx-csc/scripts/python_dockx_csc.py sync --once
python3 .claude/skills/python-dockx-csc/scripts/python_dockx_csc.py extract-questions csc_samples/"Chapitre A - modele.docx"
```

## Handoff Rule

When Claude changes code, sync rules, CSC annotations, or skill behavior, write
the authored note under `review/claude/{handoff,proposition,corrections}/` and
run `python3 scripts/sync_reviews.py --once`.
