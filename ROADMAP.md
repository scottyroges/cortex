# Cortex Roadmap

A local, privacy-first "Second Brain" for Claude Code. Acts as an **Episodic & Long-Term Memory Bridge**, solving the "Context Window Limit" via efficient state management and the "Lost in the Middle" problem via SOTA Reranking.

## Core Principles

1. **State over Chat**: Store *decisions* (Squash Commits), not raw logs
2. **Code != Text**: AST Chunking respects function boundaries
3. **Proactive Injection**: Load "Project Context" *before* the first prompt
4. **Universal I/O**: Capture data from IDE (MCP), Terminal (CLI), and Web (Clipper)

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

| Feature | Description |
|---------|-------------|
| Async Long-Running Tasks | Make `commit_to_cortex` and `ingest_code_into_cortex` async with background processing |
| Datastore Analysis | `analyze_cortex` tool - stats by type, project, branch, storage size |
| Datastore Cleanup | `cleanup_cortex` tool - remove orphaned chunks, stale entries |
| Selective Purge | Delete by filter (project, branch, type, date range) |

---

## Phase 3: External Input & Specialized Memory ⬜

*Goal: Capture knowledge from outside the codebase and enable domain-specific retrieval.*

| Feature | Description |
|---------|-------------|
| Universal Web Clipper | Tampermonkey "Save to Brain" for Gemini, ChatGPT, Confluence, docs |
| Error DB | Exact-match stack trace lookup with `log_error_to_cortex` and `solve_error_from_cortex` |
| Constraints | Negative rules ("DO NOT USE X") in preamble injection |

---

## Phase 4: Enterprise Scale (Future) ⬜

*Goal: Scale to large teams and codebases.*

| Feature | Description |
|---------|-------------|
| Federated Router | Shard memory by domain (Frontend DB, Backend DB) |
| Routing Agent | Auto-route queries to correct shard |
| Nightly Builds | Cron job for `git diff` summaries |
| Log Eater | Ingest `~/.claude/sessions` JSON logs |
| Multi-User | Team-shared memory with access control |

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
