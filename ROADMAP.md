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
| Shell Aliases | `cortex search`, `cortex save` bypass LLM | ✅ |
| In-Chat Macros | `cortex>> search auth` direct tool call | ✅ |

### Claude Integration

| Feature | Description | Status |
|---------|-------------|--------|
| Custom `CLAUDE.md` | Guide Claude on Cortex usage - when to search, commit, save notes | ✅ |

### Initiative Management

| Feature | Description | Status |
|---------|-------------|--------|
| `list_initiatives` | List all initiatives (active, completed, paused) with last updated timestamps | ⬜ |
| `resume_initiative` | Resume a previous initiative by ID/name, restore context | ⬜ |
| `complete_initiative` | Mark initiative as done, archive with summary | ⬜ |
| `pause_initiative` | Pause current work, save state for later | ⬜ |
| Initiative History | Track initiative lifecycle: created → active → paused → completed | ⬜ |

### Ingestion

| Feature | Description | Status |
|---------|-------------|--------|
| Selective Ingestion | Index specific paths/globs instead of entire codebase (e.g., `src/api/**`, `packages/auth`) | ✅ |
| Include/Exclude Patterns | Support `.cortexignore` or config-based patterns for fine-grained control | ✅ |

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

*No outstanding tech debt items.*

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
