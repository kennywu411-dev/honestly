---
name: catches
description: Show what honestly stopped this week (unbacked claims and piped test runs), by project and assistant.
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/hooks/run.py" catches)
---

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/run.py" catches
```

Summarise the result for the user in a few lines. If a catch looks wrong, `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/run.py" feedback` prints an issue-ready report.
