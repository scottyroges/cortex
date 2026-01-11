# Cortex Roadmap

A local, privacy-first "Second Brain" for Claude Code. Acts as an **Episodic & Long-Term Memory Bridge**, solving the "Context Window Limit" via efficient state management and the "Lost in the Middle" problem via SOTA Reranking.

## Core Principles

1. **State over Chat**: Store *decisions* (Squash Commits), not raw logs
2. **Code != Text**: AST Chunking respects function boundaries
3. **Proactive Injection**: Load "Project Context" *before* the first prompt
4. **Universal I/O**: Capture data from IDE (MCP), Terminal (CLI), and Web (Clipper)

---

## Phase 1: MVP (Localhost Core) ✅

*Goal: A Dockerized, high-precision memory running locally. Solves "I forgot the code structure."*

### Infrastructure Stack

| Component | Implementation | Status |
|-----------|---------------|--------|
| Runtime | Docker (Python 3.11 Slim) | ✅ |
| MCP Interface | Stdio transport | ✅ |
| FastAPI Interface | HTTP for Web Clipper/CLI | 🔄 |
| Vector Storage | ChromaDB (Persistent) | ✅ |
| Keyword Search | BM25 (rank_bm25) | ✅ |
| Reranking | FlashRank (Local Cross-Encoder) | ✅ |
| Helper LLM | Claude 3 Haiku (Contextual Headers) | ✅ |

### Ingestion Engine

| Feature | Description | Status |
|---------|-------------|--------|
| AST Scanner | Recursive folder scan with language-aware chunking | ✅ |
| Delta Sync | MD5 hash tracking, skip unchanged files | ⚠️ |
| AST Chunking | tree-sitter via langchain (20+ languages) | ✅ |
| Secret Scrubbing | Regex redaction of API keys/tokens | ✅ |
| Branch Tagging | Metadata includes branch, path | ✅ |
| Contextual Headers | Haiku-generated summaries per chunk | ✅ |
| Smart Commit | Session summary + re-index changed files | ✅ |

### Retrieval Pipeline

| Step | Description | Status |
|------|-------------|--------|
| Git-Aware Filtering | Filter by current branch + main/master | ⚠️ |
| Hybrid Search | Vector + BM25 with RRF fusion | ✅ |
| Reranking | FlashRank top 50 → top 5 | ✅ |
| Runtime Tuning | min_score, verbose, top_k knobs | ✅ |

### Phase 1 Tools

| Tool | Arguments | Status |
|------|-----------|--------|
| `search_cortex` | `query, scope, min_score` | ✅ |
| `ingest_code_into_cortex` | `path, project_name, force_full` | ✅ |
| `commit_to_cortex` | `summary, changed_files, project` | ✅ |
| `save_note_to_cortex` | `content, title, tags, project` | ✅ |
| `configure_cortex` | `min_score, verbose, top_k_*` | ✅ |
| `toggle_cortex` | `enabled` | ✅ |

---

## Phase 2: Working Memory (Workflow Integration) ⬜

*Goal: Deep integration into daily workflow. Solves "Long Running Projects" and "External Research."*

### Context Composition

| Feature | Description | Status |
|---------|-------------|--------|
| Domain Context | Static tech stack config (e.g., "NestJS, Postgres") | ✅ |
| Project Context | Dynamic project status (e.g., "Migration V1: Phase 2 Blocked") | ✅ |
| `set_context_in_cortex` | Load domain + project context | ✅ |
| `update_project_status` | Update mutable project state | ✅ |
| `get_context_from_cortex` | Retrieve stored context | ✅ |
| Context Auto-Injection | Context included in search_cortex results | ✅ |

### Universal Web Clipper

| Feature | Description | Status |
|---------|-------------|--------|
| FastAPI Bridge | HTTP endpoint at `localhost:8080/ingest` | ✅ |
| Tampermonkey Script | "Save to Brain" button for browsers | ⬜ |
| Target Sites | Gemini, ChatGPT, Confluence, docs sites | ⬜ |
| `ingest_web_to_cortex` | URL + content ingestion endpoint | ✅ |

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
| Skeleton Index | `tree` output for file-path grounding | ✅ |

### Phase 2 Tools

| Tool | Arguments | Status |
|------|-----------|--------|
| `get_skeleton` | `project` | ✅ |
| `set_context_in_cortex` | `project, domain, project_status` | ✅ |
| `update_project_status` | `status, project` | ✅ |
| `get_context_from_cortex` | `project` | ✅ |
| `ingest_web_to_cortex` | `url, content` | ⬜ |
| `log_error_to_cortex` | `signature, fix` | ⬜ |
| `solve_error_from_cortex` | `signature` | ⬜ |

---

## Phase 3: Enterprise Scale (Future) ⬜

*Goal: Scale to large teams and codebases.*

### Features

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

### Delta Sync Improvements ⬜

**Problem 1: Garbage Collection** - When files are deleted or renamed, their chunks remain in ChromaDB forever.

| Issue | Impact |
|-------|--------|
| No deleted file cleanup | Orphaned chunks accumulate, search returns dead code |
| No file rename/move handling | Refactoring creates duplicate entries |
| State file bloat | `ingest_state.json` grows indefinitely |

**Problem 2: Performance** - Current MD5 hashing reads every file even to check if nothing changed.

| Codebase Size | Current Approach | With Git-Based |
|---------------|------------------|----------------|
| 1,000 files | ~10 sec (read all) | ~instant |
| 10,000 files | ~2 min (read all) | ~instant |
| 50,000 files | ~10 min (read all) | ~instant |

**Fix Required** (`ingest.py`):

1. **Git-based change detection** (instead of MD5 hashing every file):
```python
def get_changed_files(project_path: str, last_indexed_commit: str) -> list[str]:
    if last_indexed_commit:
        # Fast: only files changed since last index
        return git("diff", "--name-only", last_indexed_commit, "HEAD")
    else:
        # First index: all files
        return walk_all_files(project_path)
```

2. **Track indexed commit** in metadata:
```python
{
    "indexed_commit": "abc123",  # HEAD at index time
    "indexed_at": "2024-01-11T10:00:00Z"
}
```

3. **Garbage collection** for deleted files:
   - Use `git diff --name-only --diff-filter=D` to find deleted files
   - Delete their chunks from ChromaDB
   - Clean up state file entries

4. **Handle renames**:
   - Use `git diff --name-status` to detect renames (R status)
   - Delete old path chunks, index new path

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

**Design Decision: Re-index vs Re-tag After Merge**

Considered re-tagging existing documents after branch merge (update `branch: "feature"` → `branch: "main"`).

| Approach | Pros | Cons |
|----------|------|------|
| **Re-index** (chosen) | Always accurate, handles conflicts/squash | Must read changed files |
| **Re-tag** | Faster, no file I/O | Inaccurate for conflict resolution, squash, rebase |

**Decision**: Use re-indexing with git-based delta sync. After merge, only changed files are re-indexed (~instant). Re-tagging adds complexity for marginal gain since:
- Git-based delta sync is already O(changed files)
- Merge conflicts, squash merges, rebases all modify code
- Notes/commits aren't branch-filtered anyway (no action needed)

If historical audit trail needed later, could change `branch` → `branches: []` array.

### Retrieval Quality Improvements ⬜

**Problem**: Default settings and tokenization aren't optimized for code search.

| Issue | Current | Recommended |
|-------|---------|-------------|
| `min_score` default | 0.3 (too permissive) | 0.5 (stricter) |
| Dead `scope` parameter | Unused in `search_cortex` | Remove it |
| BM25 tokenization | Naive `.split()` | Respect camelCase, snake_case |
| FlashRank model | MS MARCO (web search) | Consider code-optimized model |

**Fix Required** (`server.py`, `rag_utils.py`):

1. **Raise `min_score` default** (1 line):
```python
CONFIG = {
    "min_score": 0.5,  # Was 0.3
}
```

2. **Remove dead `scope` parameter** from `search_cortex`:
```python
# Remove: scope: str = "global"  # Never used
def search_cortex(query: str, project: Optional[str] = None, min_score: Optional[float] = None):
```

3. **Fix BM25 tokenization for code** (`rag_utils.py`):
```python
def tokenize_code(text: str) -> list[str]:
    # Split camelCase: "calculateTotal" → ["calculate", "total"]
    # Split snake_case: "calculate_total" → ["calculate", "total"]
    # Preserve keywords: "async", "await", "def", "fn"
    tokens = re.split(r'(?<=[a-z])(?=[A-Z])|_|\s+', text.lower())
    return [t for t in tokens if t]
```

4. **Consider code-optimized reranker** (future):
   - Current: `ms-marco-MiniLM-L-12-v2` (web search)
   - Options: CodeBERT-based rerankers, UniXcoder
   - Requires research and benchmarking

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

### Robustness Improvements ⬜

**Problem**: State file can corrupt, no tests validate ranking quality.

| Issue | Risk | Impact |
|-------|------|--------|
| Non-atomic state file | Concurrent writes, crash mid-write | Corrupted delta sync state |
| No reranking quality tests | Tests check "runs", not "ranks correctly" | No confidence in results |

**Fix Required** (`ingest.py`, `tests/`):

1. **Atomic state file writes**:
```python
import tempfile
import shutil

def save_state(state: dict, state_file: str) -> None:
    # Write to temp file, then atomic rename
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(state_file))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)
        shutil.move(tmp_path, state_file)  # Atomic on POSIX
    except:
        os.unlink(tmp_path)
        raise
```

2. **Or migrate to SQLite** (more robust for concurrent access):
```python
# Future consideration - better for multi-process scenarios
import sqlite3
# Store file hashes, indexed commits, etc. in SQLite
```

3. **Add reranking quality tests**:
```python
def test_rerank_prefers_semantic_match():
    """Verify reranker ranks semantically relevant results higher."""
    docs = [
        {"text": "def authenticate_user(username, password): ..."},
        {"text": "def calculate_total(items): ..."},
        {"text": "The user authentication flow starts with..."},
    ]
    results = reranker.rerank("user login authentication", docs, top_k=3)

    # Auth-related docs should rank above calculate_total
    assert "authenticate" in results[0]["text"] or "authentication" in results[0]["text"]
    assert results[0]["rerank_score"] > results[-1]["rerank_score"]
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

**Usage Flow**:
```
Session 1 (new project):
→ set_repo_context(tech_stack="Python + ChromaDB")
→ set_initiative(name="Delta Sync Fix", status="Starting")

Session 2 (continuing):
→ search_cortex("delta sync")
→ Returns: code + tech stack + initiative context

Session 3 (finishing):
→ set_initiative(status="Complete - GC implemented")
→ commit_to_cortex("Implemented garbage collection...")
```

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

**Metadata stored during indexing**:
```python
{
    "project": "Cortex",
    "indexed_at": "2024-01-11T10:00:00Z",
    "indexed_branch": "main",
    "indexed_commit": "abc123",  # HEAD at index time
    "file_count": 42
}
```

**Usage Flow**:
```
Session starts:
→ Claude: orient_session("/path/to/project")
→ Returns: {indexed: true, tech_stack: "Python + ChromaDB",
            active_initiative: {name: "Delta Sync Fix", status: "In progress"}}
→ Claude: "I see you're working on Delta Sync Fix. Continue?"

Fresh project:
→ Claude: orient_session("/path/to/project")
→ Returns: {indexed: false, tech_stack: null, active_initiative: null}
→ Claude: "This project isn't indexed. Should I index it?"
→ User: "yes"
→ Claude: ingest_code_into_cortex(path)
→ Claude: "What's the tech stack? What are you working on?"
```

**Fix Required** (`server.py`):
1. Add `orient_session()` tool
2. Remove `get_skeleton`, `update_project_status`, `get_context_from_cortex`, `toggle_cortex`
3. Rename `set_context_in_cortex` → `set_repo_context`
4. Add `set_initiative` tool (split from project_status)
5. Update all docstrings with "When to use" guidance

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


Phase 2 Addition:
                                   ┌──────────────────┐
                                   │   FastAPI HTTP   │◄──── Web Clipper / CLI
                                   └────────┬─────────┘
                                            │
                                            ▼
                                   ┌──────────────────┐
                                   │  Same Ingestion  │
                                   │     Pipeline     │
                                   └──────────────────┘
```

---

## Legend

- ✅ Implemented
- ⚠️ Has known issues
- ⬜ Not started
- 🔄 In progress
