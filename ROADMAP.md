# Cortex Roadmap

**Memory for AI Agents.** A local, privacy-first system that gives AI coding assistants persistent understanding across sessions.

## The Core Insight

> **Code can be grepped. Understanding cannot.**

AI agents already have powerful tools for searching code (Glob, Grep, Read). What they lack is **memory** - the ability to recall decisions, understand context, and learn from past work.

Cortex fills this gap by storing:
- **What was decided** and why (insights, notes)
- **What was done** in past sessions (commits, initiatives)
- **What matters** in this codebase (entry points, patterns, importance)

---

## Core Principles

1. **Understanding over Code**: Store *decisions and insights*, not just code chunks
2. **Zero Friction**: Memory that requires manual discipline won't be used reliably
3. **Proactive Surfacing**: Load relevant context *before* it's needed
4. **Grep's Gaps**: Focus on what search tools fundamentally can't do

---

## Current State (Jan 2026)

| Capability | Status | Notes |
|------------|--------|-------|
| **Semantic Memory** | ✅ Strong | Insights, notes, commits capture understanding |
| **Initiative Tracking** | ✅ Strong | Multi-session work with summaries |
| **Session Recall** | ✅ Good | "What did I work on?" queries |
| **Staleness Detection** | ✅ Good | Insights validated against file changes |
| **Installation & Updates** | ✅ Good | `cortex update`, `cortex doctor`, migrations |
| **Auto-Capture** | ✅ Good | Session hooks, LLM summarization, async queue |
| **Code Indexing** | ⚠️ Marginal | Only ~20-30% of queries benefit over Grep |
| **Structural Knowledge** | ❌ Gap | No dependencies, entry points, importance |

*See `analysis/code-indexing-analysis.md` for full analysis.*

---

## Phase 1: Foundation ✅

*Core infrastructure complete.*

- Dockerized deployment with ChromaDB
- Hybrid search (Vector + BM25 + FlashRank reranking)
- AST-aware code chunking (18+ languages)
- MCP server integration
- Basic tools: `search_cortex`, `ingest_code_into_cortex`, `save_note_to_cortex`

---

## Phase 2: Semantic Memory ✅

*The irreplaceable value layer - complete.*

| Feature | Status | Description |
|---------|--------|-------------|
| Insights | ✅ | Understanding anchored to specific files with staleness detection |
| Notes | ✅ | Decisions, learnings, domain knowledge |
| Commits | ✅ | Session summaries with context |
| Initiatives | ✅ | Multi-session work tracking with focus system |
| Recall | ✅ | "What did I work on this week?" timeline view |
| Summarize | ✅ | Narrative summary of initiative progress |
| Staleness | ✅ | "Remember but Verify" - detect when insights may be outdated |

---

## Phase 3: Zero-Friction & Developer Experience 🔄

*Reduce barriers to adoption and usage. Make Cortex effortless to install, use, and explore.*

### Memory Browser ✅

*Complete - Web UI for exploring memory.*

| Feature | Status | Description |
|---------|--------|-------------|
| **Web UI** | ✅ | Browser-based memory explorer at `http://localhost:8080` |
| **Stats Dashboard** | ✅ | Counts by type, storage stats |
| **Search Preview** | ✅ | Interactive search with result preview |
| **Edit/Delete** | ✅ | Modify or remove stored memories |

### Installation & Updates ✅

*Zero-friction onboarding and maintenance - complete.*

| Feature | Status | Description |
|---------|--------|-------------|
| **Auto-Update Check** | ✅ | `orient_session` returns `update_available: true` when local code differs from daemon |
| **`cortex update`** | ✅ | Single command backs up, pulls, rebuilds, migrates, and restarts |
| **Health Check** | ✅ | `cortex doctor` (essential) and `cortex doctor --verbose` (comprehensive) |
| **Migration System** | ✅ | Schema versioning with auto-migrations on startup, auto-backup before migrate |

### Auto-Capture ✅

*Eliminate manual discipline requirements - complete.*

| Feature | Status | Description |
|---------|--------|-------------|
| **Session Lifecycle Hooks** | ✅ | Claude Code `SessionEnd` hook auto-captures summaries |
| **Transcript Parsing** | ✅ | JSONL parser extracts messages, tool calls, file edits |
| **Significance Detection** | ✅ | Configurable thresholds (tokens, file edits, tool calls) |
| **LLM Summarization** | ✅ | Multi-provider support (Claude CLI, Anthropic, Ollama, OpenRouter) |
| **Async Queue Processing** | ✅ | Non-blocking hook (<100ms), daemon processes in background |
| **Hook Management CLI** | ✅ | `cortex hooks install/status/repair/uninstall` |
| **MCP Tools** | ✅ | `get_autocapture_status`, `configure_autocapture` |

#### Future Enhancements (Lower Priority)

| Feature | Description | Value |
|---------|-------------|-------|
| **Git Commit Watcher** | Background process watches for git commits, auto-indexes changed files + commit messages. | Memory stays fresh automatically |
| **Log Eater** | Ingest `~/.claude/sessions` logs with LLM summarization. Backfill memory retroactively. | Memory from past sessions without workflow change |

### Lower Priority

| Feature | Description | Value |
|---------|-------------|-------|
| **One-Line Installer** | `curl -fsSL https://get.cortex.dev \| bash` - Downloads, configures Claude Code MCP settings, pulls Docker image. | Zero-friction onboarding |
| **Homebrew Formula** | `brew install cortex-memory` - Native package for macOS users. | Platform-native experience |
| **Version Pinning** | Allow users to pin to specific version in config. | Stability for production use |
| **Linux/Windows Packages** | apt/dnf packages, WSL2 support | Broader platform support |

---

## Phase 4: Smarter Search 🔄

*Surface understanding first, not code noise.*

### Completed ✅

| Feature | Description | Value |
|---------|-------------|-------|
| **Type-Based Scoring** | Boost insights (2x), notes (1.5x), commits (1.5x) over code chunks. Implemented in `src/search/type_scoring.py`. | Understanding surfaces before implementation |
| **Document Type Filter** | `types` parameter on `search_cortex` filters by document type (note, insight, commit, code, skeleton, tech_stack, initiative). Branch filtering applies only to code/skeleton. | Skip code noise for "why" questions |

### High Priority

| Feature | Description | Value |
|---------|-------------|-------|
| **Conditional Index Rebuild** | Don't rebuild BM25 index on every query. Cache index state, rebuild only when collection changes. | Performance optimization |
| **Skeleton + Memory Mode** | Option to skip code indexing entirely. Index only skeleton + semantic memory. | 10-100x smaller index, higher signal |

### Medium Priority

| Feature | Description | Value |
|---------|-------------|-------|
| **Importance Scoring** | Analyze git frequency + import centrality. Rank results by importance. | High-impact files surface first |
| **Entry Point Detection** | Auto-detect main/index files. Flag as navigation starting points. | Reduce onboarding friction |

---

## Code Quality Initiative ✅

*Completed Jan 2026. Addressed technical debt from codebase analysis.*

### Critical Fixes ✅

| Issue | Solution | Status |
|-------|----------|--------|
| **Queue processor non-atomic writes** | Tempfile + rename pattern in `queue_processor.py` | ✅ Done |
| **Migration no rollback** | Backup before each migration, restore on failure | ✅ Done |

### Code Duplication Elimination ✅

| Duplication | Solution | Status |
|-------------|----------|--------|
| **Resource initialization** | `src/http/resources.py` with thread-safe ResourceManager | ✅ Done |
| **Subprocess patterns** | `src/git/subprocess_utils.py` | ✅ Done |
| **Initiative resolution** | `resolve_initiative()` in `src/tools/initiative_utils.py` | ✅ Done |
| **`_find_initiative`** | `find_initiative()` in `src/tools/initiative_utils.py` | ✅ Done |

### Function Complexity ✅

| Function | Solution | Status |
|----------|----------|--------|
| `search_cortex` | Extracted `SearchPipeline` dataclass | ✅ Done |
| `ingest_codebase` | Strategy pattern (`DeltaSyncStrategy`) | ✅ Done |
| `orient_session` | Extracted `RepositoryContext`, `StalenessDetector` | ✅ Done |
| `parse_transcript_jsonl` | Extracted `ContentBlockParser`, `TranscriptMetadataExtractor` | ✅ Done |

### Test Coverage Expansion ✅

| Module | Status | Details |
|--------|--------|---------|
| Auto-capture | ✅ Done | 62+ tests in `test_autocapture.py` |
| Performance | ✅ Done | 8 benchmarks in `test_benchmarks.py` (latency, throughput, large codebase) |
| E2E workflow | ✅ Done | 9 tests in `test_e2e.py` (orient→ingest→search→commit, initiatives) |

### Lower Priority Items ✅

| Item | Solution | Status |
|------|----------|--------|
| **Exception hierarchy** | `src/exceptions.py` with `CortexError` base + domain-specific exceptions | ✅ Done |
| **HTTP client standardization** | `src/http/http_client.py` replacing urllib in LLM providers | ✅ Done |
| **Configuration extraction** | `TIMEOUTS` dict in `src/config.py` with `get_timeout()` helper | ✅ Done |

---

## Phase 5: Structural Intelligence ⬜

*Fill the gaps that Grep fundamentally cannot address.*

### Codebase Understanding

| Feature | Description | Value |
|---------|-------------|-------|
| **Dependency Graph** | Parse imports during ingest. Build file→file relationships. | "What depends on X?" / Impact analysis |
| **Entry Point Map** | Systematic capture of "where does feature X start?" | Navigation knowledge |
| **Cross-File Relationships** | Track which files are commonly edited together. | "Related files" for context |
| **Architecture Detection** | Identify patterns: monorepo structure, layer boundaries, module purposes. | Automatic codebase orientation |

### Datastore Management

| Feature | Description | Value |
|---------|-------------|-------|
| **Async Operations** | Background processing for large ingests | Non-blocking workflows |
| **Datastore Analysis** | Stats by type, repository, storage size | Understand storage usage |
| **Cleanup Tools** | Remove orphaned chunks, stale entries | Keep index healthy |
| **Selective Purge** | Delete by repository, branch, type, date range | Fine-grained cleanup |

---

## Phase 6: External Knowledge ⬜

*Capture knowledge from outside the codebase.*

| Feature | Description | Value |
|---------|-------------|-------|
| **Error Database** | Exact-match stack trace lookup. `log_error` / `solve_error` tools. | "I've seen this before" for errors |
| **Documentation Ingest** | Ingest external docs with source attribution. Search returns "from React docs:" context. | Library knowledge in memory |
| **Web Clipper** | Browser extension to save from Confluence, Stack Overflow, ChatGPT. | Capture research and decisions |
| **Constraints** | Negative rules ("DO NOT USE X") injected in preamble. | Prevent known mistakes |

---

## Phase 7: Scale & Teams ⬜

*Future: enterprise features.*

| Feature | Description |
|---------|-------------|
| **Cross-Initiative Search** | "What auth decisions have we made across all projects?" |
| **Pattern Library** | "You've solved rate limiting 3 times - here's what worked." |
| **Multi-User** | Team-shared memory with access control |
| **Memory Sync** | Sync across machines (personal cloud backup) |
| **Federated Routing** | Shard by domain for large codebases |

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
│ Vector + BM25 │                  │  AST Chunking   │                 │   Insights      │
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
- 🔄 In progress / Next up
- ⬜ Not started

