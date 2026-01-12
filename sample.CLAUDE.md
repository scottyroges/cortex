## Cortex Quick Commands

| Command | What it does |
|---------|--------------|
| `cortex>> orient` | Start session - check index status, get project context, see active initiative |
| `cortex>> search <query>` | Search memory for code, notes, decisions |
| `cortex>> save <content>` | Save a note, decision, or learning |
| `cortex>> ingest <path>` | Index a codebase into memory |
| `cortex>> ingest <path> --include "src/**"` | Selective ingestion (only matching paths) |
| `cortex>> skeleton` | Show project file structure |
| `cortex>> status` | Check if Cortex daemon is running |
| `cortex>> commit` | Use `commit_to_cortex` |

## Initiative Management

| Command | What it does |
|---------|--------------|
| `create_initiative(repo, "Name", goal="...")` | Start tracking a new workstream (auto-focuses) |
| `list_initiatives(repo)` | See all active and completed initiatives |
| `focus_initiative(repo, "Name")` | Switch focus to a different initiative |
| `complete_initiative("Name", summary="...")` | Mark initiative as done |

**How it works:**
- New commits and notes are automatically tagged with the focused initiative
- `orient_session` will warn if an initiative is stale (inactive > 5 days)
- `commit_to_cortex` detects completion signals ("done", "complete", "shipped") and prompts to close

## Workflow

- **Start of session**: Run `cortex>> orient` to check index freshness and get context
- **During work**: Search before implementing; save architectural decisions
- **End of session**: Use `cortex>> commit` with summary and changed files

## What to Save

- Architectural decisions and their rationale
- Non-obvious patterns in the codebase
- Gotchas and learnings
- Future work / TODOs

## Writing Good Commit Summaries

When using `commit_to_cortex`, write detailed summaries that include:
- **What**: What was implemented or changed
- **Why**: The reasoning behind decisions
- **How**: Key implementation details, patterns used
- **Gotchas**: Problems encountered and solutions
- **Future**: TODOs or follow-up work needed

**Bad**: "Added auth feature"

**Good**: "Implemented JWT-based auth with refresh tokens. Used httpOnly cookies for token storage to prevent XSS. Added middleware in src/auth.py that validates tokens on protected routes. Discovered that the existing User model needed a refresh_token field - migrated the schema. TODO: Add token revocation on logout."
