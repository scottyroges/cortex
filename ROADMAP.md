# Cortex Roadmap

A local, privacy-first "Second Brain" for Claude Code. Acts as an **Episodic & Long-Term Memory Bridge**, solving the "Context Window Limit" via efficient state management and the "Lost in the Middle" problem via SOTA Reranking.

## Core Principles

1. **State over Chat**: Store *decisions* (Squash Commits), not raw logs
2. **Code != Text**: AST Chunking respects function boundaries
3. **Proactive Injection**: Load "Project Context" *before* the first prompt
4. **Universal I/O**: Capture data from IDE (MCP), Terminal (CLI), and Web (Clipper)

---

## Gap Analysis (Jan 2026)

*Where we are vs where we need to be for true LLM memory.*

| Memory Type | Current State | Gap |
|-------------|---------------|-----|
| **Code Memory** | ✅ Excellent - AST chunking, hybrid search, reranking, insight linking | None |
| **Session Memory** | ✅ Good - `recall_recent_work` answers "what did I do?" | Minor: no auto-capture |
| **Initiative Memory** | ✅ Good - `summarize_initiative` provides narrative view | None |
| **Analysis Memory** | ✅ Good - `insight_to_cortex` captures code analysis | None |
| **Automatic Capture** | ❌ Missing - entirely opt-in | Major: need lifecycle hooks |

**Core insight**: The storage and retrieval layers are strong. The gap is **automation** - memory requires too much manual discipline to be reliable.

---

## Phase 1: MVP (Localhost Core) ✅

Dockerized, high-precision memory with hybrid search (Vector + BM25 + FlashRank reranking), AST-aware chunking, and core MCP tools.

---

## Phase 2: Working Memory (Workflow Integration) 🔄

*Goal: Deep integration into daily workflow. Solves "Long Running Projects" and "External Research."*

### Completed ✅

- **Context Composition** - Domain/project context with auto-injection via `set_repo_context`
- **Skeleton Index** - File tree output for path grounding via `get_skeleton`
- **FastAPI Bridge** - HTTP debug endpoints at `localhost:8080`
- **CLI & Slash Commands** - Shell aliases and `cortex>>` in-chat macros
- **Custom CLAUDE.md** - Guide Claude on Cortex usage patterns
- **Selective Ingestion** - Index specific paths with `include_patterns` and `.cortexignore` support
- **Initiative Management** - Multi-session tracking with `create_initiative`, `list_initiatives`, `focus_initiative`, `complete_initiative`. Auto-tags commits/notes, stale detection, completion signal prompts, search filtering/boosting.

### Remaining

#### Session & Temporal Memory (Priority)

*Addresses the core goal: "What did I work on yesterday/last week?"*

| Feature | Description |
|---------|-------------|
| ✅ **Recall Recent Work** | `recall_recent_work` tool - timeline view of recent commits/notes for a repository. Answers "what did I do this week?" without manual search queries. Returns summaries grouped by day with initiative context. |
| ✅ **Initiative Summarization** | `summarize_initiative` tool - generate narrative summary of an initiative's progress. Gathers all tagged commits/notes and synthesizes a timeline with key decisions, problems solved, and current state. |
| ✅ **Insight Capture** | `insight_to_cortex` tool - save analysis insights about code architecture, patterns, or behavior. Links insights to specific files so retrieval includes both code AND understanding. Claude uses proactively after major analysis. |

#### Datastore Management

| Feature | Description |
|---------|-------------|
| Async Long-Running Tasks | Make `commit_to_cortex` and `ingest_code_into_cortex` async with background processing |
| Datastore Analysis | `analyze_cortex` tool - stats by type, project, branch, storage size |
| Datastore Cleanup | `cleanup_cortex` tool - remove orphaned chunks, stale entries |
| Selective Purge | Delete by filter (project, branch, type, date range) |

---

## Phase 3: External Input & Specialized Memory ⬜

*Goal: Capture knowledge from outside the codebase and enable domain-specific retrieval.*

#### Automatic Capture

| Feature | Description |
|---------|-------------|
| **Session Auto-Prompt** | Detect long/complex sessions and prompt to commit before closing. Heuristics: token count, file edits, elapsed time. Reduces reliance on manual `commit_to_cortex`. |
| **Session Lifecycle Hooks** | Integration with Claude Code hooks system to auto-capture session summaries on exit. Uses LLM to generate summary from session transcript. Zero-friction memory capture. |
| **Git Commit Watcher** | Background process that watches for git commits and auto-indexes changed files + commit messages. Memory stays fresh without manual `ingest`. |

#### External Knowledge

| Feature | Description |
|---------|-------------|
| Universal Web Clipper | Tampermonkey "Save to Brain" for Gemini, ChatGPT, Confluence, docs |
| Error DB | Exact-match stack trace lookup with `log_error_to_cortex` and `solve_error_from_cortex` |
| Constraints | Negative rules ("DO NOT USE X") in preamble injection |
| Documentation Ingest | Ingest external docs (API references, library docs) with source attribution. Search returns "from React docs:" context. |

---

## Phase 4: Enterprise Scale (Future) ⬜

*Goal: Scale to large teams and codebases.*

#### Retroactive Memory (High Value)

| Feature | Description |
|---------|-------------|
| **Log Eater** | Ingest `~/.claude/sessions` JSON logs with LLM summarization. Backfill memory from past sessions retroactively. Filter by significance (session length, file changes). Priority: this gives you session memory without changing workflow. |
| **Session Replay** | Given a session ID, reconstruct context: what files were read, what was discussed, what was decided. "What was I thinking when I wrote this?" |

#### Cross-Project Intelligence

| Feature | Description |
|---------|-------------|
| **Cross-Initiative Search** | Search across all initiatives: "What auth decisions have we made?" Returns results tagged with initiative context. |
| **Pattern Library** | Extract recurring patterns from commits/notes: "You've solved rate limiting 3 times, here's what worked." |
| Nightly Builds | Cron job for `git diff` summaries across all indexed repos |

#### Scale & Team Features

| Feature | Description |
|---------|-------------|
| Federated Router | Shard memory by domain (Frontend DB, Backend DB) |
| Routing Agent | Auto-route queries to correct shard |
| Multi-User | Team-shared memory with access control |
| Memory Sync | Sync memory across machines (personal cloud backup) |

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
