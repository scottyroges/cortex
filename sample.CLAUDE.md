## Cortex Quick Commands

| Command | What it does |
|---------|--------------|
| `cortex>> search <query>` | Search memory for code, notes, decisions |
| `cortex>> save <content>` | Save a note, decision, or learning |
| `cortex>> ingest <path>` | Index a codebase into memory |
| `cortex>> skeleton` | Show project file structure |
| `cortex>> status` | Check if Cortex daemon is running |

## Workflow

- **Start of session**: Search for relevant context from past work
- **During work**: Search before implementing; save architectural decisions
- **End of session**: Use `commit_to_cortex` with summary and changed files

## What to Save

- Architectural decisions and their rationale
- Non-obvious patterns in the codebase
- Gotchas and learnings
- Future work / TODOs
