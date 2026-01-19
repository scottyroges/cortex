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
1. `ingest_codebase(path=path)` - Index the codebase with AST-aware chunking
2. `configure_cortex(repository=repo, tech_stack="Python, FastAPI, ChromaDB...")` - Set tech stack (optional but recommended)
3. `manage_initiative(action="create", repository=repo, name="Building feature X", goal="...")` - Start tracking work (optional)

**Tools Used:** `ingest_codebase`, `configure_cortex`, `manage_initiative`

---

## Scenario 3: Searching for Context

**Context:** Claude needs to find relevant code, docs, or past decisions.

**Examples:**
- "How does auth work in this codebase?"
- "What was the decision about database choice?"
- "Find the error handling pattern"

**Flow:**
1. `search_cortex("how does auth work")` - Semantic search across code, notes, session summaries

**Tools Used:** `search_cortex`

---

## Scenario 4: Resuming Work After Time Away

**Context:** User returns to project after days/weeks away.

**Problem:** Context is lost - what was I working on? What changed?

**Flow:**
1. `orient_session(path)` - Check staleness, see what initiative was active
2. If `needs_reindex: true`, run `ingest_codebase(path=path)` to catch up
3. `search_cortex("recent session summaries")` - Find what changed
4. `get_skeleton(repository)` - Re-orient on file structure

**Tools Used:** `orient_session`, `ingest_codebase`, `search_cortex`, `get_skeleton`

---

## Scenario 5: Saving Session Progress

**Context:** Claude finishes a chunk of work and wants to preserve context for next session.

**Flow:**
1. `conclude_session(summary=summary, changed_files=changed_files, repository=repository)` - Save detailed session summary
2. If summary contains completion signals (e.g., "complete", "done", "shipped"), Claude will be prompted to mark the initiative as complete

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

**Tools Used:** `conclude_session`

---

## Scenario 6: Capturing External Research

**Context:** Claude learns something useful from docs, web research, or user explanation that should be remembered.

**Examples:**
- OAuth2 best practices from documentation
- User's preference for error handling
- Architecture decision rationale

**Flow:**
1. `save_memory(content="OAuth2 best practices: use PKCE for mobile, refresh tokens for web...", kind="note", title="OAuth2 Patterns", tags=["auth", "security"])`

**Tools Used:** `save_memory`

---

## Scenario 7: Quick Context Check

**Context:** Claude needs to see current initiative or tech stack without full orientation.

**Flow (context):**
1. `configure_cortex(get_status=True)` - Get system status including tech stack and current initiative

**Flow (file structure):**
1. `get_skeleton(repository)` - Get file tree for path grounding

**Tools Used:** `configure_cortex`, `get_skeleton`

---

## Scenario 8: Selective Ingestion (Large Codebases)

**Context:** User has a large monorepo and only wants to index specific parts.

**Problem:** Full indexing is slow and includes irrelevant code.

**Flow (selective paths):**
1. `ingest_codebase(path=path, include_patterns=["services/api/**", "packages/auth/**"])` - Index only specific directories

**Flow (using cortexignore):**
1. Create `~/.cortex/cortexignore` for global exclusions (all projects)
2. Create `<project>/.cortexignore` for project-specific exclusions
3. `ingest_codebase(path=path)` - Automatically respects both ignore files

**Example `.cortexignore`:**
```
# Large generated files
*.pb.go
*_generated.py

# Test fixtures
fixtures/
test_data/
```

**Tools Used:** `ingest_codebase`

---

## Scenario 9: Starting a New Initiative

**Context:** User begins work on a new epic, migration, or multi-session feature.

**Problem:** Need to track work across multiple sessions and tag session summaries/notes.

**Flow:**
1. `manage_initiative(action="create", repository=repository, name="Auth Migration", goal="Migrate from session-based to JWT auth")` - Creates initiative and auto-focuses it
2. All subsequent `conclude_session` and `save_memory` calls are automatically tagged with this initiative

**Tools Used:** `manage_initiative`

---

## Scenario 10: Switching Between Initiatives

**Context:** User needs to context-switch to a different workstream (e.g., hotfix, another feature).

**Flow:**
1. `manage_initiative(action="create", repository=repository, name="Hotfix: Login Bug")` - Creates and focuses new initiative
2. Work on hotfix, session summaries are tagged with "Hotfix: Login Bug"
3. `manage_initiative(action="complete", repository=repository, initiative="Hotfix: Login Bug", summary="Fixed race condition in auth...")` - Mark done
4. `manage_initiative(action="focus", repository=repository, initiative="Auth Migration")` - Return to previous work

**Tools Used:** `manage_initiative`

---

## Scenario 11: Completing an Initiative

**Context:** User finishes a multi-session piece of work.

**Trigger 1 - Completion signal in session summary:**
```
conclude_session(summary="Auth migration complete. All tests passing...", changed_files=[...])
# Response includes: initiative.completion_signal_detected = True
# Claude asks: "Ready to mark 'Auth Migration' as complete?"
```

**Trigger 2 - Explicit completion:**
```
manage_initiative(action="complete", repository=repository, initiative="Auth Migration", summary="Successfully migrated to JWT auth. Key changes: ...")
```

**What happens:**
- Initiative status set to "completed"
- Summary stored for future reference
- Focus cleared (no initiative focused)
- Initiative and tagged content remain searchable with recency decay

**Tools Used:** `manage_initiative`

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
4. User can either continue or run `manage_initiative(action="complete", ...)` to close it out

**Tools Used:** `orient_session`, `manage_initiative` (optional)

---

## Scenario 13: Searching Within an Initiative

**Context:** User wants to find decisions, code, or notes from a specific initiative.

**Examples:**
- "What did we decide about token storage during the auth migration?"
- "Find the database schema changes from the Postgres migration"

**Flow:**
1. `search_cortex("token storage", initiative="Auth Migration")` - Filter to specific initiative
2. Results only include session summaries/notes tagged with that initiative (plus untagged code)

**Flow (completed initiatives):**
1. `manage_initiative(action="list", repository=repository, status="completed")` - Find old initiative name
2. `search_cortex("database schema", initiative="Postgres Migration", include_completed=True)`

**Tools Used:** `search_cortex`, `manage_initiative`

---

## Scenario 14: Listing and Managing Initiatives

**Context:** User wants to see all initiatives for a repository.

**Flow:**
1. `manage_initiative(action="list", repository=repository, status="all")` - See all initiatives
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

**Tools Used:** `manage_initiative`

---

## Scenario 15: Recalling Recent Work

**Context:** User returns to a project and wants to know what they worked on recently.

**Problem:** "What did I do last week?" requires manual search queries.

**Flow:**
1. `recall_recent_work(repository, days=7)` - Get timeline of recent session summaries/notes

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
        {"type": "session_summary", "content": "Added auth middleware..."},
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
1. `manage_initiative(action="summarize", repository=repository, initiative="Auth Migration")` - Get narrative summary with timeline

**Example Response:**
```json
{
  "initiative": {
    "name": "Auth Migration",
    "goal": "Migrate to JWT auth",
    "status": "active"
  },
  "stats": {
    "session_summaries": 5,
    "notes": 3,
    "files_touched": 12,
    "duration": "2 weeks"
  },
  "timeline": [
    {"date": "Jan 01", "type": "session_summary", "summary": "Initial auth scaffolding..."},
    {"date": "Jan 05", "type": "note", "summary": "Decided on refresh token strategy..."}
  ],
  "narrative": "**Auth Migration**: Migrate to JWT auth\n\nActivity: 5 session summaries and 3 notes recorded.\n\nStatus: Active\n\nLast activity: 2 days ago"
}
```

**Tools Used:** `manage_initiative`

---

## Scenario 17: Debugging/Admin

**Context:** User needs to check Cortex status or adjust behavior.

**Flow (status check):**
1. `configure_cortex(get_status=True)` - Get full system status including version, autocapture, and config

**Flow (tuning):**
1. `configure_cortex(min_score=0.6, top_k_rerank=10)` - Adjust retrieval parameters

**Flow (disable for testing):**
1. `configure_cortex(enabled=False)` - Disable memory for A/B testing

**Tools Used:** `configure_cortex`

---

## Scenario 18: Capturing Code Insights

**Context:** Claude has done significant analysis on code and wants to preserve the understanding.

**Problem:** Insights about code architecture, patterns, or gotchas are lost when the session ends.

**Trigger (automatic):** Claude uses this tool proactively after:
- Deep-diving into complex code
- Discovering non-obvious patterns
- Understanding architectural decisions
- Finding potential issues or gotchas

**Flow:**
1. Claude analyzes code (e.g., "explain how auth works")
2. Claude captures insight: `save_memory(content="The auth system uses...", kind="insight", files=["src/auth/middleware.py", "src/auth/tokens.py"])`
3. Future search for "auth" returns both code AND the insight

**Example:**
```python
save_memory(
    content="Auth uses two-phase token refresh. Access tokens expire in 15min, refresh tokens rotate on use. Key gotcha: refresh endpoint must be excluded from token validation.",
    kind="insight",
    files=["src/auth/middleware.py", "src/auth/tokens.py"],
    title="Auth Token Refresh Pattern"
)
```

**Tools Used:** `save_memory`

---

## Scenario 19: Stale Insight Detection and Validation

**Context:** Claude retrieves an insight that was created months ago, but the underlying code may have changed.

**Problem:** Old insights might be outdated - Claude needs to "remember but verify."

**Flow (automatic detection):**
1. `search_cortex("auth pattern")` - Search includes staleness check
2. Response includes verification warning:
   ```json
   {
     "results": [{
       "content": "Auth uses two-phase token refresh...",
       "staleness": {
         "level": "likely_stale",
         "verification_required": true,
         "files_changed": ["src/auth/middleware.py"]
       },
       "verification_warning": "VERIFICATION REQUIRED - FILES CHANGED: This insight references files that have been modified..."
     }],
     "staleness_summary": {
       "verification_required_count": 1
     }
   }
   ```
3. Claude re-reads the linked files to verify the insight

**Flow (validation - insight still valid):**
1. After re-reading files, Claude confirms insight is accurate
2. `validate_insight(insight_id, "still_valid")` - Updates verified_at timestamp and refreshes file hashes

**Flow (validation - insight outdated):**
1. Claude finds the insight is no longer accurate
2. `validate_insight(insight_id, "no_longer_valid", deprecate=True, replacement_insight="New understanding: auth now uses...")`
3. Old insight marked deprecated, new one created with link

**Staleness Levels:**
| Level | Trigger | Action |
|-------|---------|--------|
| `fresh` | No changes | Trust as-is |
| `possibly_stale` | >30 days old | Advisory warning |
| `likely_stale` | Linked files modified | Verification required |
| `files_deleted` | Linked files missing | Verification required |
| `deprecated` | Explicitly marked invalid | Show replacement link |

**Tools Used:** `search_cortex`, `validate_insight`, `save_memory`

---

## Scenario 20: Auto-Capture Session Summary

**Context:** User ends a Claude Code session after doing significant work.

**Problem:** Manual `conclude_session` requires discipline and is often forgotten.

**How Auto-Capture Works:**
1. Claude Code triggers `SessionEnd` hook when session closes
2. Hook parses transcript, checks significance thresholds
3. If significant, queues session for processing (<100ms, non-blocking)
4. Daemon's background worker generates LLM summary
5. Summary saved to Cortex memory automatically

**No tools needed** - happens automatically via Claude Code hooks.

**Configuration:**
```yaml
# ~/.cortex/config.yaml
autocapture:
  enabled: true
  significance:
    min_tokens: 1000
    min_file_edits: 1
    min_tool_calls: 3
```

---

## Scenario 21: Checking Auto-Capture Status

**Context:** User wants to verify auto-capture is working.

**Flow:**
1. `configure_cortex(get_status=True)` - Returns full system status including autocapture info

**Example Response (autocapture section):**
```json
{
  "autocapture": {
    "hooks": {
      "claude_code_installed": true,
      "hook_script_exists": true
    },
    "llm_providers": {
      "available": ["claude-cli"],
      "configured_primary": "claude-cli"
    },
    "statistics": {
      "captured_sessions_count": 15
    }
  }
}
```

**Tools Used:** `configure_cortex`

---

## Scenario 22: Configuring Auto-Capture

**Context:** User wants to adjust auto-capture thresholds or change LLM provider.

**Flow (change provider):**
1. `configure_cortex(autocapture_llm_provider="ollama")` - Switch to Ollama for summarization

**Flow (adjust thresholds):**
1. `configure_cortex(autocapture_min_file_edits=2, autocapture_min_tokens=2000)` - Capture only larger sessions

**Flow (disable):**
1. `configure_cortex(autocapture_enabled=False)` - Turn off auto-capture

**Tools Used:** `configure_cortex`

---

## Tool Summary by Scenario

| Scenario | Primary Tools |
|----------|---------------|
| Starting session | `orient_session` |
| First indexing | `ingest_codebase`, `configure_cortex`, `manage_initiative` |
| Searching | `search_cortex` |
| Resuming work | `orient_session`, `ingest_codebase`, `search_cortex` |
| Saving progress | `conclude_session` |
| Capturing research | `save_memory` |
| Quick context | `configure_cortex`, `get_skeleton` |
| Selective ingestion | `ingest_codebase` (with `include_patterns` or `.cortexignore`) |
| Starting initiative | `manage_initiative` |
| Switching initiatives | `manage_initiative` |
| Completing initiative | `manage_initiative` |
| Stale initiative | `orient_session`, `manage_initiative` |
| Search within initiative | `search_cortex`, `manage_initiative` |
| Managing initiatives | `manage_initiative` |
| Recalling recent work | `recall_recent_work` |
| Summarizing initiatives | `manage_initiative` |
| Capturing insights | `save_memory` |
| Validating stale insights | `search_cortex`, `validate_insight` |
| Admin/debug | `configure_cortex` |
| Auto-capture status | `configure_cortex` |
| Configure auto-capture | `configure_cortex` |

---

## Final Tool Set (10 Consolidated Tools)

| Tool | Purpose |
|------|---------|
| `orient_session` | Session entry point with staleness and initiative detection |
| `search_cortex` | Semantic search with initiative filtering, boosting, and staleness detection |
| `recall_recent_work` | Timeline view of recent work for a repository |
| `save_memory` | Save notes (`kind="note"`) or insights (`kind="insight"`) - auto-tagged with initiative |
| `conclude_session` | Save end-of-session summary with changed files (auto-tagged, completion detection) |
| `validate_insight` | Verify stale insights against current code, deprecate if invalid |
| `manage_initiative` | Create, list, focus, complete, or summarize initiatives (`action` parameter) |
| `ingest_codebase` | Index codebase with AST chunking or check async status (`action="ingest"` or `"status"`) |
| `get_skeleton` | File tree for path grounding |
| `configure_cortex` | Unified config: runtime settings, repo tech stack, autocapture, and system status |
