# Cortex Roadmap

**Memory for AI Agents.** A local, privacy-first system that gives AI coding assistants persistent understanding across sessions.

> **Code can be grepped. Understanding cannot.**

---

## Current State (Jan 2026)

Core infrastructure complete. Semantic memory, auto-capture, and developer experience are solid. Focus now shifts to structural intelligence and external knowledge.

---

## Phase 5: Structural Intelligence 🔄

*Fill the gaps that Grep fundamentally cannot address.*

| Feature | Status | Description |
|---------|--------|-------------|
| **Dependency Graph** | ✅ | Imports parsed during ingest, file→file relationships |
| **Entry Point Map** | ✅ | HTTP routes, CLI commands, main functions extracted |
| **Data Contracts** | ✅ | Interfaces, types, schemas extracted |
| **Cross-File Relationships** | ⬜ | Track which files are commonly edited together |
| **Architecture Detection** | ⬜ | Identify patterns: monorepo structure, layer boundaries |
| **Cleanup Tools** | ✅ | Remove orphaned file_metadata, insights, dependencies |
| **Selective Purge** | ✅ | Delete documents by ID, filter-based backend ready |

---

## Phase 6: External Knowledge ⬜

*Capture knowledge from outside the codebase.*

| Feature | Description |
|---------|-------------|
| **Error Database** | Exact-match stack trace lookup. "I've seen this before" for errors |
| **Documentation Ingest** | Ingest external docs with source attribution |
| **Web Clipper** | Browser extension to save from Confluence, Stack Overflow, ChatGPT |
| **Constraints** | Negative rules ("DO NOT USE X") injected in preamble |

---

## Phase 7: IDE Integration ⬜

*Surface Cortex insights while browsing code in any editor.*

| Feature | Description |
|---------|-------------|
| **LSP Server** | Language Server Protocol server for universal editor support |
| **Hover Provider** | Show linked insights on hover |
| **Code Lens** | "N insights" indicator at file top |
| **Stale Diagnostics** | Warning squiggles for outdated insights |
| **VS Code Extension** | Packaged extension for easy installation |

*See `analysis/file-context-lsp.md` for full design.*

---

## Phase 8: Scale & Teams ⬜

*Enterprise features.*

| Feature | Description |
|---------|-------------|
| **Cross-Initiative Search** | "What auth decisions have we made across all projects?" |
| **Pattern Library** | "You've solved rate limiting 3 times - here's what worked" |
| **Multi-User** | Team-shared memory with access control |
| **Memory Sync** | Sync across machines (personal cloud backup) |

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
│    Search     │                  │    Ingestion    │                 │  Semantic Memory│
│ Vector + BM25 │                  │ Metadata-First  │                 │ Notes, Insights │
└───────┬───────┘                  │ + AST Parsing   │                 │ Session Summaries│
        │                          └────────┬────────┘                 └─────────────────┘
┌───────▼───────┐                           │
│   FlashRank   │                  ┌────────▼────────┐
│   Reranker    │                  │    ChromaDB     │
└───────────────┘                  │   (Embedded)    │
                                   └─────────────────┘
```

---

## Completed

### Phase 1-4: Foundation, Semantic Memory, DX, Search ✅

- **Hybrid Search** - Vector + BM25 + FlashRank reranking
- **Metadata-First Indexing** - file_metadata, data_contract, entry_point, dependency documents
- **AST Parsing** - Tree-sitter for Python, TypeScript, Kotlin
- **Insights & Notes** - Understanding anchored to files with staleness detection
- **Initiatives** - Multi-session work tracking with focus system
- **Session Recall** - "What did I work on?" timeline view
- **Auto-Capture** - Session hooks with LLM summarization and async queue
- **Memory Browser** - Web UI at localhost:8080
- **Installation** - `cortex update`, `cortex doctor`, auto-migrations

### Code Quality Initiative ✅

- Atomic writes in queue processor
- Migration rollback with backups
- Resource initialization consolidation
- Exception hierarchy (`CortexError` base)
- Test coverage: 62+ autocapture tests, 8 benchmarks, 9 E2E tests

---

## Legend

- ✅ Implemented
- 🔄 In progress
- ⬜ Not started
