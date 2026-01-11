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

### Universal Web Clipper

| Feature | Description | Status |
|---------|-------------|--------|
| Tampermonkey Script | "Save to Brain" button for browsers | ⬜ |
| Target Sites | Gemini, ChatGPT, Confluence, docs sites | ⬜ |

### CLI & Slash Commands

| Feature | Description | Status |
|---------|-------------|--------|
| Shell Aliases | `memsave`, `memsearch` bypass LLM | ⬜ |
| In-Chat Macros | `>> search auth` direct tool call | ⬜ |

### Domain-Specific Memories

| Feature | Description | Status |
|---------|-------------|--------|
| Error DB | Exact-match stack trace lookup | ⬜ |
| `log_error_to_cortex` | Save error signature + fix | ⬜ |
| `solve_error_from_cortex` | Query by stack trace | ⬜ |
| Constraints | Negative rules ("DO NOT USE X") in preamble | ⬜ |

---

## Phase 3: Enterprise Scale (Future) ⬜

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

### Branch Filtering Non-Functional ⬜

**Problem**: Branch is stored in metadata but never used for filtering. Search returns results from all branches.

| Issue | Impact |
|-------|--------|
| Hardcoded `/projects` path in `get_current_branch()` | Branch detection fails outside MCP container |
| Branch not used in search `where` clause | Results polluted with code from all branches |
| Skeleton not filtered by branch | May show wrong branch's file structure |
| No `branch` parameter on `search_cortex` | Users can't filter by branch |

**Key Insight: Different document types need different branch behavior**:

| Document Type | Branch Behavior | Rationale |
|---------------|-----------------|-----------|
| Code chunks | Filter by branch | Code differs per branch |
| Notes/decisions | NO filter (store `origin_branch` for reference) | Decisions persist after merge |
| Commits | NO filter (store `origin_branch` for reference) | History applies to repo |
| Tech stack | NO filter (repo-level) | Applies to whole repo |
| Initiatives | NO filter (repo-level) | Workstreams span branches |

**Fix Required** (`server.py`, `rag_utils.py`):
1. Pass actual project path to `get_current_branch()` instead of `/projects`
2. Add optional `branch` parameter to `search_cortex` tool
3. Branch filter for code: `{"type": "code", "branch": {"$in": [current, "main"]}}`
4. NO branch filter for notes/commits: `{"type": {"$in": ["note", "commit"]}}`
5. Filter skeleton results by current branch
6. Store `origin_branch` on notes/commits (for reference, not filtering)

### Metadata Quality Improvements ⬜

**Problem**: Chunk metadata lacks semantic context, tags stored incorrectly.

| Issue | Current | Impact |
|-------|---------|--------|
| No function/class names | Only file path | Can't pinpoint which function |
| Tags as comma-string | `"auth,security"` | Can't filter by individual tag |

**Fix Required** (`ingest.py`, `server.py`):

1. **Extract function/class names during chunking**:
```python
# During AST chunking, detect containing scope
metadata = {
    "file_path": "/src/auth.py",
    "function_name": "validate_token",  # NEW
    "class_name": "AuthService",        # NEW
    "scope": "AuthService.validate_token",  # NEW - full path
}
```

2. **Store tags as JSON array** (not comma-separated):
```python
# Before
metadatas=[{"tags": ",".join(tags)}]  # "auth,security"

# After
metadatas=[{"tags": json.dumps(tags)}]  # '["auth", "security"]'
# Or use ChromaDB's native list support if available
```

### Missing Timestamps on Documents ⬜

**Problem**: Commits, notes, and code chunks have no timestamp metadata. Can't query by time.

| Document Type | Missing Field | Impact |
|---------------|---------------|--------|
| Commits | `created_at` | Can't find "commits from last 3 days" |
| Notes | `created_at` | Can't sort notes by recency |
| Code chunks | `indexed_at` | Can't distinguish old vs recently changed code |

**Fix Required** (`server.py`, `ingest.py`):
1. Add `created_at` to commit metadata in `commit_to_cortex()`
2. Add `created_at` to note metadata in `save_note_to_cortex()`
3. Add `indexed_at` to code chunk metadata in `ingest_codebase()`
4. Use ISO 8601 format: `datetime.now(timezone.utc).isoformat()`

### Context Model Refactor ⬜

**Problem**: "Project" is overloaded - means both repository AND task/epic. Parameters are confusingly named.

| Current | Problem |
|---------|---------|
| `project` | Ambiguous - repo or initiative? |
| `domain` | Unclear - means tech stack |
| `project_status` | Really means initiative status |

**New Model**:

| Concept | Description | Example |
|---------|-------------|---------|
| **Repository** | The codebase (auto-detected from path) | `Cortex`, `my-app` |
| **Tech Stack** | Static repo context - technologies, patterns | `Python, ChromaDB, FastMCP` |
| **Initiative** | The current workstream/epic | `Mongo→Postgres Migration` |
| **Status** | Current state of the initiative | `Phase 2: Users done, Orders in progress` |

**Fix Required** (`server.py`):
1. Rename `domain` → `tech_stack` in `set_context_in_cortex()`
2. Split `project_status` into `initiative` + `status`
3. Update docstrings to clarify repository vs initiative
4. Consider splitting into two tools:
   - `set_repo_context(project, tech_stack)` - static, set once
   - `set_initiative(name, status)` - dynamic, updated frequently

### MCP Tool Redesign ⬜

**Problem**: Current 10 tools are confusing - 3 are redundant, workflows unclear, no session entry point.

**New Tool Set (8 tools)**:

| Tool | Type | Purpose |
|------|------|---------|
| `orient_session` | High-level | **Entry point** - returns indexed status, skeleton, tech_stack, active_initiative |
| `search_cortex` | Atomic | Search memory for relevant context |
| `ingest_code_into_cortex` | Atomic | Index a codebase |
| `set_repo_context` | Atomic | Set static tech stack info |
| `set_initiative` | Atomic | Set/update current workstream |
| `commit_to_cortex` | Atomic | Save session summary |
| `save_note_to_cortex` | Atomic | Save notes/decisions |
| `configure_cortex` | Atomic | Tune retrieval settings |

**Tools to Remove**:
- `get_skeleton` - redundant, included in `orient_session` and `search_cortex`
- `update_project_status` - replaced by `set_initiative`
- `get_context_from_cortex` - redundant, included in `orient_session`
- `toggle_cortex` - rarely used, can be a config flag instead

**New Tool: `orient_session`**:

```python
def orient_session(project_path: str) -> dict:
    """
    Entry point for starting a session. Returns everything Claude needs to orient.
    Detects stale index and prompts for reindexing after merges.

    Returns:
        indexed: bool - Is this repo indexed?
        last_indexed: str - When was it last indexed?
        file_count: int - How many files indexed?
        needs_reindex: bool - Is the index stale?
        reindex_reason: str - Why reindex is needed (if applicable)
        skeleton: str - File tree structure
        tech_stack: str - Technologies and patterns (if set)
        active_initiative: dict - Current workstream (if any)
            - name: str
            - status: str
    """
```

**Stale Index Detection** (in `orient_session`):

| Signal | Detection | Meaning |
|--------|-----------|---------|
| New commits | `git log --since=last_indexed` | Code changed since index |
| File count diff | Indexed count vs files on disk | Files added/removed |
| Branch switch | Current branch ≠ indexed branch | Context changed |
| Merge detected | `git log --merges --since=last_indexed` | Feature branch merged |

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
