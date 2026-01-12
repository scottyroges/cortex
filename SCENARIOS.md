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
3. `set_initiative(repo, "Building feature X", "In progress")` - Set current work (optional)

**Tools Used:** `ingest_code_into_cortex`, `set_repo_context`, `set_initiative`

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
1. `commit_to_cortex(summary, changed_files)` - Save detailed session summary + re-index changed files
2. `set_initiative(repo, "Auth system", "Phase 2 complete, ready for testing")` - Update initiative status

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

**Tools Used:** `commit_to_cortex`, `set_initiative`

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

## Scenario 9: Debugging/Admin

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
| First indexing | `ingest_code_into_cortex`, `set_repo_context`, `set_initiative` |
| Searching | `search_cortex` |
| Resuming work | `orient_session`, `ingest_code_into_cortex`, `search_cortex` |
| Saving progress | `commit_to_cortex`, `set_initiative` |
| Capturing research | `save_note_to_cortex` |
| Quick context | `get_context_from_cortex`, `get_skeleton` |
| Selective ingestion | `ingest_code_into_cortex` (with `include_patterns` or `.cortexignore`) |
| Admin/debug | `get_cortex_version`, `configure_cortex` |

---

## Final Tool Set (11 tools)

| Tool | Purpose |
|------|---------|
| `orient_session` | Session entry point with staleness detection |
| `search_cortex` | Semantic search across all memory types |
| `ingest_code_into_cortex` | Index codebase with AST chunking |
| `save_note_to_cortex` | Save notes, decisions, research |
| `commit_to_cortex` | Save session summary + re-index files |
| `set_repo_context` | Set static tech stack info |
| `set_initiative` | Set/update current workstream |
| `get_context_from_cortex` | Quick context retrieval |
| `get_skeleton` | File tree for path grounding |
| `configure_cortex` | Runtime configuration + enable/disable |
| `get_cortex_version` | Version and rebuild detection |
