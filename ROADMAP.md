# Cortex Roadmap

A local, privacy-first "Second Brain" for Claude Code. Acts as an **Episodic & Long-Term Memory Bridge**, solving the "Context Window Limit" via efficient state management and the "Lost in the Middle" problem via SOTA Reranking.

## Core Principles

1. **State over Chat**: Store *decisions* (Squash Commits), not raw logs
2. **Code != Text**: AST Chunking respects function boundaries
3. **Proactive Injection**: Load "Project Context" *before* the first prompt
4. **Universal I/O**: Capture data from IDE (MCP), Terminal (CLI), and Web (Clipper)

---

## Phase 1: MVP (Localhost Core) ✅

*Dockerized, high-precision memory running locally.*

**Stack**: Docker, ChromaDB, BM25 + FlashRank reranking, Claude Haiku headers

**Tools**: `search_cortex`, `ingest_code_into_cortex`, `commit_to_cortex`, `save_note_to_cortex`, `configure_cortex`, `toggle_cortex`

---

## Phase 2: Working Memory (Workflow Integration) 🔄

*Goal: Deep integration into daily workflow. Solves "Long Running Projects" and "External Research."*

### Completed ✅

- Context Composition (domain/project context with auto-injection)
- Skeleton Index (`tree` output for file-path grounding)
- FastAPI Bridge (HTTP endpoint at `localhost:8080/ingest`)

### CLI & Slash Commands

| Feature | Description | Status |
|---------|-------------|--------|
| Shell Aliases | `memsave`, `memsearch` bypass LLM | ⬜ |
| In-Chat Macros | `>> search auth` direct tool call | ⬜ |

### Claude Integration

| Feature | Description | Status |
|---------|-------------|--------|
| Custom `CLAUDE.md` | Guide Claude on Cortex usage - when to search, commit, save notes | ⬜ |

### Initiative Management

| Feature | Description | Status |
|---------|-------------|--------|
| `list_initiatives` | List all initiatives (active, completed, paused) with last updated timestamps | ⬜ |
| `resume_initiative` | Resume a previous initiative by ID/name, restore context | ⬜ |
| `complete_initiative` | Mark initiative as done, archive with summary | ⬜ |
| `pause_initiative` | Pause current work, save state for later | ⬜ |
| Initiative History | Track initiative lifecycle: created → active → paused → completed | ⬜ |

### Performance & UX

| Feature | Description | Status |
|---------|-------------|--------|
| Async Long-Running Tasks | Make `commit_to_cortex` and `ingest_code_into_cortex` async - return success immediately, process in background | ⬜ |

### Admin & Maintenance

| Feature | Description | Status |
|---------|-------------|--------|
| Datastore Analysis | `analyze_cortex` tool - show stats by type (code/notes/commits), project, branch, storage size, stale entries | ⬜ |
| Datastore Cleanup | `cleanup_cortex` tool - remove orphaned chunks, old notes/commits, entries from deleted projects | ⬜ |
| Selective Purge | Delete by filter (project, branch, type, date range) | ⬜ |

---

## Phase 3: External Input & Specialized Memory ⬜

*Goal: Capture knowledge from outside the codebase and enable domain-specific retrieval.*

### Universal Web Clipper

| Feature | Description | Status |
|---------|-------------|--------|
| Tampermonkey Script | "Save to Brain" button for browsers | ⬜ |
| Target Sites | Gemini, ChatGPT, Confluence, docs sites | ⬜ |

### Domain-Specific Memories

| Feature | Description | Status |
|---------|-------------|--------|
| Error DB | Exact-match stack trace lookup | ⬜ |
| `log_error_to_cortex` | Save error signature + fix | ⬜ |
| `solve_error_from_cortex` | Query by stack trace | ⬜ |
| Constraints | Negative rules ("DO NOT USE X") in preamble | ⬜ |

---

## Phase 4: Enterprise Scale (Future) ⬜

*Goal: Scale to large teams and codebases.*

| Feature | Description | Status |
|---------|-------------|--------|
| Federated Router | Shard memory by domain (Frontend DB, Backend DB) | ⬜ |
| Routing Agent | Auto-route queries to correct shard | ⬜ |
| Nightly Builds | Cron job for `git diff` summaries | ⬜ |
| Log Eater | Ingest `~/.claude/sessions` JSON logs | ⬜ |
| Multi-User | Team-shared memory with access control | ⬜ |

---

## Technical Debt & Bug Fixes

*Critical issues that affect data integrity or correctness.*

### Completed ✅

- **Delta Sync**: Git-based change detection, garbage collection for deleted/renamed files, atomic state writes
- **Retrieval Quality**: min_score 0.3→0.5, removed dead `scope` param, BM25 camelCase/snake_case tokenization

### Branch Filtering ✅

Fixed branch filtering with smart document-type-aware behavior:

**What was fixed**:
1. Replaced 6 hardcoded `/projects` paths with `get_repo_path()` helper using `os.getcwd()`
2. Added `build_branch_aware_filter()` for smart ChromaDB filtering
3. Added optional `branch` parameter to `search_cortex` tool
4. Skeleton now filtered by branch with fallback

**Smart filtering by document type**:

| Document Type | Branch Behavior | Implementation |
|---------------|-----------------|----------------|
| Code chunks | Filter by `[current, "main"]` | `{"type": "code", "branch": {"$in": branches}}` |
| Skeleton | Filter by branch | Same as code |
| Notes/commits | NO filter | Always visible cross-branch |
| Tech stack/initiatives | NO filter | Repo-level context |

**Files modified**: `services.py`, `search.py`, `notes.py`, `context.py`, `admin.py`

**Tests added**: 14 new tests (136 total) covering filter construction, repo path detection, and branch-aware search integration.

### Metadata Quality Improvements ✅

Added function/class scope extraction and fixed tags storage:

1. **Extract function/class names during chunking**: New `extract_scope_from_chunk()` in `ingest.py` uses language-specific regex patterns to detect containing scope. Metadata now includes `function_name`, `class_name`, and `scope` (full path like `AuthService.validate_token`).

2. **Store tags as JSON array**: Changed from `",".join(tags)` to `json.dumps(tags)` in `save_note_to_cortex()`.

### Missing Timestamps on Documents ✅

Added timestamp metadata to all document types for time-based queries:
- `created_at` on commits in `commit_to_cortex()`
- `created_at` on notes in `save_note_to_cortex()`
- `indexed_at` on code chunks in `ingest_file()`
- All timestamps use ISO 8601 format: `datetime.now(timezone.utc).isoformat()`

### Context Model Refactor ✅

Refactored confusing context parameters to a clearer model:

| Old | New | Description |
|-----|-----|-------------|
| `project` | `repository` | The codebase identifier |
| `domain` | `tech_stack` | Static repo context - technologies, patterns |
| `project_status` | `initiative` + `status` | Current workstream/epic and its state |

**New Tools**:
- `set_repo_context(repository, tech_stack)` - Static tech stack, set once per repo
- `set_initiative(repository, name, status)` - Dynamic workstream, updated frequently
- `update_initiative_status(status, repository)` - Quick status update
- `get_context_from_cortex(repository)` - Retrieve both contexts

**Document IDs**: `{repository}:tech_stack`, `{repository}:initiative`

### MCP Tool Redesign ✅

Consolidated tools from 12 to 11, adding session entry point and removing redundant tools.

**Final Tool Set (11 tools)**:

| Tool | Type | Purpose |
|------|------|---------|
| `orient_session` | High-level | **NEW** - Entry point with staleness detection |
| `search_cortex` | Atomic | Search memory for relevant context |
| `ingest_code_into_cortex` | Atomic | Index a codebase |
| `set_repo_context` | Atomic | Set static tech stack info |
| `set_initiative` | Atomic | Set/update current workstream |
| `get_context_from_cortex` | Atomic | Quick context retrieval |
| `commit_to_cortex` | Atomic | Save session summary |
| `save_note_to_cortex` | Atomic | Save notes/decisions |
| `configure_cortex` | Atomic | Tune retrieval settings + enable/disable |
| `get_skeleton` | Atomic | File tree for path grounding |
| `get_cortex_version` | Atomic | Version and rebuild detection |

**Tools Removed**:
- `toggle_cortex` - absorbed into `configure_cortex(enabled=bool)`
- `update_initiative_status` - redundant, use `set_initiative` directly

**`orient_session` implementation**:

```python
def orient_session(project_path: str) -> dict:
    """
    Entry point for starting a session. Returns everything Claude needs to orient.
    Detects stale index and prompts for reindexing after merges.

    Returns:
        project: str - Project name
        branch: str - Current git branch
        indexed: bool - Is this repo indexed?
        last_indexed: str - When was it last indexed?
        file_count: int - How many files indexed?
        needs_reindex: bool - Is the index stale?
        reindex_reason: str - Why reindex is needed (if applicable)
        skeleton: dict - File tree structure (if available)
        tech_stack: str - Technologies and patterns (if set)
        active_initiative: dict - Current workstream (if any)
    """
```

**Stale Index Detection** (in `orient_session`):

| Signal | Detection | Meaning |
|--------|-----------|---------|
| New commits | `git log --since=last_indexed` | Code changed since index |
| File count diff | Indexed count vs files on disk | Files added/removed |
| Branch switch | Current branch ≠ indexed branch | Context changed |
| Merge detected | `git log --merges --since=last_indexed` | Feature branch merged |

See `SCENARIOS.md` for detailed usage workflows.

---

## Architecture

```
┌─────────────────┐     stdio      ┌──────────────────┐
│   Claude Code   │ ◄────────────► │   MCP Server     │
└─────────────────┘                └────────┬─────────┘
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        │                                   │                                   │
┌───────▼───────┐                  ┌────────▼────────┐                 ┌────────▼────────┐
│    Search     │                  │    Ingestion    │                 │   Notes/Commits │
│ Vector + BM25 │                  │  AST + Haiku    │                 │     Storage     │
└───────┬───────┘                  └────────┬────────┘                 └─────────────────┘
        │                                   │
┌───────▼───────┐                  ┌────────▼────────┐
│   FlashRank   │                  │    ChromaDB     │
│   Reranker    │                  │   (Embedded)    │
└───────────────┘                  └─────────────────┘
```

---

## Legend

- ✅ Implemented
- 🔄 In progress
- ⬜ Not started
