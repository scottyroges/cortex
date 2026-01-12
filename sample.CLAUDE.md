## Cortex Quick Commands

| Command | What it does |
|---------|--------------|
| `cortex>> orient` | Start session - check index status, get project context |
| `cortex>> search <query>` | Search memory for code, notes, decisions |
| `cortex>> save <content>` | Save a note, decision, or learning |
| `cortex>> ingest <path>` | Index a codebase into memory |
| `cortex>> ingest <path> --include "src/**"` | Selective ingestion (only matching paths) |
| `cortex>> skeleton` | Show project file structure |
| `cortex>> status` | Check if Cortex daemon is running |

## Workflow

- **Start of session**: Run `cortex>> orient` to check index freshness and get context
- **During work**: Search before implementing; save architectural decisions
- **End of session**: Use `commit_to_cortex` with summary and changed files

## What to Save

- Architectural decisions and their rationale
- Non-obvious patterns in the codebase
- Gotchas and learnings
- Future work / TODOs
