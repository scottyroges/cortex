# Cortex Usage Scenarios

This document describes the primary workflows for how Claude Code interacts with Cortex memory. Use these scenarios to inform API design decisions.

---

## Scenario 1: Starting a New Session

**Context:** User opens Claude Code in a project directory.

**Problem:** Claude has no context about what's indexed or what the project is.

**Ideal Flow:**
1. Claude calls `orient_session(project_path)` to understand:
   - Is this repo indexed?
   - Is the index stale (new commits, branch switch)?
   - What's the file structure (skeleton)?
   - What tech stack/initiative context exists?

**Tools Used:** `orient_session`

---

## Scenario 2: First Time Indexing

**Context:** User wants to add a project to Cortex memory for the first time.

**Flow:**
1. `ingest_code_into_cortex(path)` - Index the codebase with AST-aware chunking
2. `set_repo_context(repo, "Python, FastAPI, ChromaDB...")` - Set tech stack (optional but recommended)
3. `create_initiative(repo, "Building feature X", goal="...")` - Start tracking work (optional)

**Tools Used:** `ingest_code_into_cortex`, `set_repo_context`, `create_initiative`

---

## Scenario 3: Searching for Context

**Context:** Claude needs to find relevant code, docs, or past decisions.

**Examples:**
- "How does auth work in this codebase?"
- "What was the decision about database choice?"
- "Find the error handling pattern"

**Flow:**
1. `search_cortex("how does auth work")` - Semantic search across code, notes, commits

**Tools Used:** `search_cortex`

---

## Scenario 4: Resuming Work After Time Away

**Context:** User returns to project after days/weeks away.

**Problem:** Context is lost - what was I working on? What changed?

**Flow:**
1. `orient_session(path)` - Check staleness, see what initiative was active
2. If `needs_reindex: true`, run `ingest_code_into_cortex(path)` to catch up
3. `search_cortex("recent commits")` - Find what changed
4. `get_skeleton(project)` - Re-orient on file structure

**Tools Used:** `orient_session`, `ingest_code_into_cortex`, `search_cortex`, `get_skeleton`

---

## Scenario 5: Saving Session Progress

**Context:** Claude finishes a chunk of work and wants to preserve context for next session.

**Flow:**
1. `commit_to_cortex(summary, changed_files, repository)` - Save detailed session summary + re-index changed files
2. If commit summary contains completion signals (e.g., "complete", "done", "shipped"), Claude will be prompted to mark the initiative as complete

**Example Summary** (write detailed summaries that capture full context):
```
Implemented JWT auth middleware with refresh token rotation. Key decisions:
- Used httpOnly cookies for token storage (prevents XSS)
- Refresh tokens stored in Redis with 7-day TTL
- Added TokenRefreshMiddleware that auto-refreshes tokens within 1hr of expiry

Problems solved:
- User model needed refresh_token_hash field - added migration
- Race condition when multiple tabs refresh simultaneously - added mutex lock

Files: src/auth.py (new middleware), src/models/user.py (added field),
src/middleware.py (integrated auth check)

TODO: Add token revocation endpoint for logout, rate limit refresh attempts
```

**Tools Used:** `commit_to_cortex`

---

## Scenario 6: Capturing External Research

**Context:** Claude learns something useful from docs, web research, or user explanation that should be remembered.

**Examples:**
- OAuth2 best practices from documentation
- User's preference for error handling
- Architecture decision rationale

**Flow:**
1. `save_note_to_cortex("OAuth2 best practices: use PKCE for mobile, refresh tokens for web...", title="OAuth2 Patterns", tags=["auth", "security"])`

**Tools Used:** `save_note_to_cortex`

---

## Scenario 7: Quick Context Check

**Context:** Claude needs to see current initiative or tech stack without full orientation.

**Flow (context):**
1. `get_context_from_cortex(repo)` - Get tech stack + current initiative

**Flow (file structure):**
1. `get_skeleton(project)` - Get file tree for path grounding

**Tools Used:** `get_context_from_cortex`, `get_skeleton`

---

## Scenario 8: Selective Ingestion (Large Codebases)

**Context:** User has a large monorepo and only wants to index specific parts.

**Problem:** Full indexing is slow and includes irrelevant code.

**Flow (selective paths):**
1. `ingest_code_into_cortex(path, include_patterns=["services/api/**", "packages/auth/**"])` - Index only specific directories

**Flow (using cortexignore):**
1. Create `~/.cortex/cortexignore` for global exclusions (all projects)
2. Create `<project>/.cortexignore` for project-specific exclusions
3. `ingest_code_into_cortex(path)` - Automatically respects both ignore files

**Example `.cortexignore`:**
```
# Large generated files
*.pb.go
*_generated.py

# Test fixtures
fixtures/
test_data/
```

**Tools Used:** `ingest_code_into_cortex`

---

## Scenario 9: Starting a New Initiative

**Context:** User begins work on a new epic, migration, or multi-session feature.

**Problem:** Need to track work across multiple sessions and tag commits/notes.

**Flow:**
1. `create_initiative(repository, "Auth Migration", goal="Migrate from session-based to JWT auth")` - Creates initiative and auto-focuses it
2. All subsequent `commit_to_cortex` and `save_note_to_cortex` calls are automatically tagged with this initiative

**Tools Used:** `create_initiative`

---

## Scenario 10: Switching Between Initiatives

**Context:** User needs to context-switch to a different workstream (e.g., hotfix, another feature).

**Flow:**
1. `create_initiative(repository, "Hotfix: Login Bug")` - Creates and focuses new initiative
2. Work on hotfix, commits are tagged with "Hotfix: Login Bug"
3. `complete_initiative("Hotfix: Login Bug", summary="Fixed race condition in auth...")` - Mark done
4. `focus_initiative(repository, "Auth Migration")` - Return to previous work

**Tools Used:** `create_initiative`, `complete_initiative`, `focus_initiative`

---

## Scenario 11: Completing an Initiative

**Context:** User finishes a multi-session piece of work.

**Trigger 1 - Completion signal in commit:**
```
commit_to_cortex(summary="Auth migration complete. All tests passing...")
# Response includes: initiative.completion_signal_detected = True
# Claude asks: "Ready to mark 'Auth Migration' as complete?"
```

**Trigger 2 - Explicit completion:**
```
complete_initiative(initiative="Auth Migration", summary="Successfully migrated to JWT auth. Key changes: ...")
```

**What happens:**
- Initiative status set to "completed"
- Summary stored for future reference
- Focus cleared (no initiative focused)
- Initiative and tagged content remain searchable with recency decay

**Tools Used:** `complete_initiative`

---

## Scenario 12: Stale Initiative Detection

**Context:** User returns to a project with an old, potentially abandoned initiative.

**Flow:**
1. `orient_session(path)` - Called at session start
2. Response includes stale initiative info:
   ```json
   {
     "focused_initiative": {
       "name": "Auth Migration",
       "days_inactive": 8,
       "stale": true,
       "prompt": "still_working_or_complete"
     }
   }
   ```
3. Claude asks: "You were working on 'Auth Migration' (inactive 8 days). Still working on this, or ready to complete it?"
4. User can either continue or run `complete_initiative()` to close it out

**Tools Used:** `orient_session`, `complete_initiative` (optional)

---

## Scenario 13: Searching Within an Initiative

**Context:** User wants to find decisions, code, or notes from a specific initiative.

**Examples:**
- "What did we decide about token storage during the auth migration?"
- "Find the database schema changes from the Postgres migration"

**Flow:**
1. `search_cortex("token storage", initiative="Auth Migration")` - Filter to specific initiative
2. Results only include commits/notes tagged with that initiative (plus untagged code)

**Flow (completed initiatives):**
1. `list_initiatives(repository, status="completed")` - Find old initiative name
2. `search_cortex("database schema", initiative="Postgres Migration", include_completed=True)`

**Tools Used:** `search_cortex`, `list_initiatives`

---

## Scenario 14: Listing and Managing Initiatives

**Context:** User wants to see all initiatives for a repository.

**Flow:**
1. `list_initiatives(repository, status="all")` - See all initiatives
2. Response includes:
   - Currently focused initiative
   - All active initiatives
   - Completed initiatives with summaries

**Example Response:**
```json
{
  "repository": "MyApp",
  "focused": {"id": "...", "name": "Auth Migration"},
  "total": 3,
  "initiatives": [
    {"name": "Auth Migration", "status": "active", "goal": "..."},
    {"name": "Hotfix: Login", "status": "completed", "completed_at": "..."},
    {"name": "Performance Optimization", "status": "active", "goal": "..."}
  ]
}
```

**Tools Used:** `list_initiatives`

---

## Scenario 15: Recalling Recent Work

**Context:** User returns to a project and wants to know what they worked on recently.

**Problem:** "What did I do last week?" requires manual search queries.

**Flow:**
1. `recall_recent_work(repository, days=7)` - Get timeline of recent commits/notes

**Example Response:**
```json
{
  "repository": "MyApp",
  "period": "Last 7 days",
  "total_items": 5,
  "timeline": [
    {
      "date": "2026-01-11",
      "day_name": "Saturday",
      "items": [
        {"type": "commit", "content": "Added auth middleware..."},
        {"type": "note", "title": "OAuth decision", "content": "Using PKCE for mobile..."}
      ]
    }
  ],
  "initiatives_active": [
    {"name": "Auth Migration", "activity_count": 3}
  ]
}
```

**Tools Used:** `recall_recent_work`

---

## Scenario 16: Summarizing Initiative Progress

**Context:** User wants to understand the full history of an initiative.

**Problem:** Commits and notes are scattered; no narrative view exists.

**Flow:**
1. `summarize_initiative(initiative, repository)` - Get narrative summary with timeline

**Example Response:**
```json
{
  "initiative": {
    "name": "Auth Migration",
    "goal": "Migrate to JWT auth",
    "status": "active"
  },
  "stats": {
    "commits": 5,
    "notes": 3,
    "files_touched": 12,
    "duration": "2 weeks"
  },
  "timeline": [
    {"date": "Jan 01", "type": "commit", "summary": "Initial auth scaffolding..."},
    {"date": "Jan 05", "type": "note", "summary": "Decided on refresh token strategy..."}
  ],
  "narrative": "**Auth Migration**: Migrate to JWT auth\n\nActivity: 5 commits and 3 notes recorded.\n\nStatus: Active\n\nLast activity: 2 days ago"
}
```

**Tools Used:** `summarize_initiative`

---

## Scenario 17: Debugging/Admin

**Context:** User needs to check Cortex status or adjust behavior.

**Flow (version check):**
1. `get_cortex_version(expected_commit)` - Check if daemon needs rebuild

**Flow (tuning):**
1. `configure_cortex(min_score=0.6, top_k_rerank=10)` - Adjust retrieval parameters

**Flow (disable for testing):**
1. `configure_cortex(enabled=False)` - Disable memory for A/B testing

**Tools Used:** `get_cortex_version`, `configure_cortex`

---

## Tool Summary by Scenario

| Scenario | Primary Tools |
|----------|---------------|
| Starting session | `orient_session` |
| First indexing | `ingest_code_into_cortex`, `set_repo_context`, `create_initiative` |
| Searching | `search_cortex` |
| Resuming work | `orient_session`, `ingest_code_into_cortex`, `search_cortex` |
| Saving progress | `commit_to_cortex` |
| Capturing research | `save_note_to_cortex` |
| Quick context | `get_context_from_cortex`, `get_skeleton` |
| Selective ingestion | `ingest_code_into_cortex` (with `include_patterns` or `.cortexignore`) |
| Starting initiative | `create_initiative` |
| Switching initiatives | `create_initiative`, `focus_initiative`, `complete_initiative` |
| Completing initiative | `complete_initiative` |
| Stale initiative | `orient_session`, `complete_initiative` |
| Search within initiative | `search_cortex`, `list_initiatives` |
| Managing initiatives | `list_initiatives`, `focus_initiative` |
| Recalling recent work | `recall_recent_work` |
| Summarizing initiatives | `summarize_initiative` |
| Admin/debug | `get_cortex_version`, `configure_cortex` |

---

## Final Tool Set (17 tools)

| Tool | Purpose |
|------|---------|
| `orient_session` | Session entry point with staleness and initiative detection |
| `search_cortex` | Semantic search with initiative filtering and boosting |
| `ingest_code_into_cortex` | Index codebase with AST chunking |
| `save_note_to_cortex` | Save notes, decisions, research (auto-tagged with initiative) |
| `commit_to_cortex` | Save session summary + re-index files (auto-tagged, completion detection) |
| `set_repo_context` | Set static tech stack info |
| `set_initiative` | Legacy - use `create_initiative` instead |
| `get_context_from_cortex` | Quick context retrieval |
| `get_skeleton` | File tree for path grounding |
| `configure_cortex` | Runtime configuration + enable/disable |
| `get_cortex_version` | Version and rebuild detection |
| `create_initiative` | Create and focus a new initiative |
| `list_initiatives` | List initiatives with status filtering |
| `focus_initiative` | Switch focus to a different initiative |
| `complete_initiative` | Mark initiative as done with summary |
| `recall_recent_work` | Timeline view of recent work for a repository |
| `summarize_initiative` | Narrative summary of initiative progress |
