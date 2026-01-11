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
| Delta Sync | MD5 hash tracking, skip unchanged files | ✅ |
| AST Chunking | tree-sitter via langchain (20+ languages) | ✅ |
| Secret Scrubbing | Regex redaction of API keys/tokens | ✅ |
| Branch Tagging | Metadata includes branch, path | ✅ |
| Contextual Headers | Haiku-generated summaries per chunk | ✅ |
| Smart Commit | Session summary + re-index changed files | ✅ |

### Retrieval Pipeline

| Step | Description | Status |
|------|-------------|--------|
| Git-Aware Filtering | Filter by current branch + main/master | ✅ |
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
- ⬜ Not started
- 🔄 In progress
