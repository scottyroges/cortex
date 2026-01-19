# CORTEX MEMORY PROTOCOL

You have long-term memory via Cortex. You are not stateless. You persist knowledge.

## Workflow

1. **START**: Call `orient_session` to see active initiatives and tech stack
2. **SEARCH**: Before implementing, use `search_cortex` to check for existing patterns
3. **WORK**: Implement changes
4. **MEMORIZE**: When you make a significant decision or find a gotcha, use `save_memory`
5. **HANDOFF**: When finished, call `conclude_session` with summary and changed files

## Memory Rules

- **Don't duplicate**: If search shows we already know X, don't save X again
- **Link files**: Always link `save_memory` insights to specific files when possible
- **Be opinionated**: Explain WHY, not just WHAT

## Quick Commands

| Command | What it does |
|---------|--------------|
| `cortex>> orient` | Start session - check index status, get context |
| `cortex>> search <query>` | Search memory for code, notes, decisions |
| `cortex>> save <content>` | Save a note or insight |
| `cortex>> ingest <path>` | Index a codebase into memory |
| `cortex>> skeleton` | Show repository file structure |

## 10 Consolidated Tools

| Tool | Purpose |
|------|---------|
| `orient_session` | Session entry point - returns context, active initiative, staleness |
| `search_cortex` | Search memory with semantic + keyword hybrid search |
| `recall_recent_work` | Timeline view - "What did I do this week?" |
| `get_skeleton` | File tree structure for navigation |
| `manage_initiative` | CRUD for initiatives (action: create/list/focus/complete/summarize) |
| `save_memory` | Save notes or insights (kind: "note" or "insight") |
| `conclude_session` | End-of-session summary with changed files |
| `ingest_codebase` | Index codebase (action: "ingest" or "status") |
| `validate_insight` | Verify stale insights against current code |
| `configure_cortex` | Configuration, repo context, and system status |

## Initiative Management

```
# Start a new initiative
manage_initiative(action="create", repository="my-app", name="Auth Migration", goal="...")

# List all initiatives
manage_initiative(action="list", repository="my-app")

# Switch focus
manage_initiative(action="focus", repository="my-app", initiative="Auth Migration")

# Complete with summary
manage_initiative(action="complete", repository="my-app", initiative="Auth Migration", summary="...")

# Get progress summary
manage_initiative(action="summarize", repository="my-app", initiative="Auth Migration")
```

## Saving Memory

```
# Save a decision/learning (note)
save_memory(content="Decided to use JWT...", kind="note", title="Auth Decision")

# Save understanding linked to files (insight)
save_memory(
    content="This module uses observer pattern...",
    kind="insight",
    files=["src/events.py", "src/handlers.py"]
)
```

## Repository Context

Set tech stack when configuring a new repository:

```
configure_cortex(
    repository="my-app",
    tech_stack="Python FastAPI backend, PostgreSQL, React frontend. Event-driven architecture."
)
```

**Include** (stable info): Languages, frameworks, architecture patterns, module responsibilities
**Exclude** (gets stale): Version numbers, counts, dates, status indicators

## Insight Validation

When search returns old insights with `verification_warning`:

1. Re-read the linked files to verify accuracy
2. If still valid: `validate_insight(insight_id, "still_valid")`
3. If outdated: `validate_insight(insight_id, "no_longer_valid", deprecate=True, replacement_insight="...")`

## What to Save

- Architectural decisions and their rationale
- Non-obvious patterns in the codebase
- Gotchas and learnings discovered during debugging
- Future work / TODOs

## Writing Good Session Summaries

When using `conclude_session`, include:
- **What**: What was implemented or changed
- **Why**: The reasoning behind decisions
- **How**: Key implementation details, patterns used
- **Gotchas**: Problems encountered and solutions
- **Future**: TODOs or follow-up work needed

**Bad**: "Added auth feature"

**Good**: "Implemented JWT-based auth with refresh tokens. Used httpOnly cookies for token storage to prevent XSS. Added middleware in src/auth.py that validates tokens on protected routes. TODO: Add token revocation on logout."
