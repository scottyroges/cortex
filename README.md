# Cortex

A local, privacy-first memory system for Claude Code. Provides RAG capabilities with ChromaDB vector storage, BM25 keyword search, and FlashRank reranking.

## Features

- **Hybrid Search**: Vector + BM25 with Reciprocal Rank Fusion, then FlashRank cross-encoder reranking
- **AST-Aware Chunking**: Respects function/class boundaries for 20+ languages
- **Delta Sync**: Only re-indexes changed files (MD5 hash tracking)
- **Secret Scrubbing**: Automatically redacts API keys, tokens, and credentials
- **Git-Aware**: Filters search results by current branch + main/master
- **Contextual Headers**: Optional Claude Haiku summaries for each chunk

## Quick Start

### 1. Install

```bash
# Clone and build
git clone https://github.com/scottyroges/Cortex.git
cd Cortex
docker build -t cortex .

# Symlink wrapper script (auto-updates with git pull)
# Option 1: System-wide (requires sudo)
sudo ln -sf "$(pwd)/cortex" /usr/local/bin/cortex

# Option 2: User-local (no sudo, add ~/.local/bin to PATH if needed)
mkdir -p ~/.local/bin
ln -sf "$(pwd)/cortex" ~/.local/bin/cortex
```

### 2. Configure

Run the interactive setup:

```bash
cortex init
```

This creates `~/.cortex/settings.json` with your code paths and preferences.

### 3. Add to Claude Code

```bash
claude mcp add cortex cortex
```

Then restart Claude Code. That's it!

## Configuration

### Settings File

Cortex configuration lives in `~/.cortex/settings.json`. Create it with `cortex init` or edit manually:

```json
{
  "code_paths": ["~/Projects", "~/Work"],
  "header_provider": "none",
  "debug": false
}
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `code_paths` | string[] | `[]` | Directories containing code to index |
| `header_provider` | string | `"none"` | `"none"`, `"claude-cli"`, or `"anthropic"` |
| `debug` | bool | `false` | Enable debug logging |

### Managing Configuration

```bash
# View current settings
cortex config

# Edit settings in your $EDITOR
cortex config edit
```

After changing settings, restart the daemon:
```bash
cortex daemon restart
```

### Environment Variable Overrides

Environment variables can override settings.json (useful for CI/testing):

| Variable | Description |
|----------|-------------|
| `CORTEX_CODE_PATHS` | Comma-separated code directories |
| `CORTEX_HEADER_PROVIDER` | Header provider |
| `CORTEX_DEBUG` | Enable debug logging |
| `CORTEX_DATA_PATH` | Data directory (default: `~/.cortex`) |
| `ANTHROPIC_API_KEY` | Required for `header_provider=anthropic` |

### Header Providers

Contextual headers add AI-generated summaries to each code chunk:

| Provider | Description |
|----------|-------------|
| `none` | No headers (fastest, default) |
| `claude-cli` | Uses Claude CLI - leverages your existing Claude auth |
| `anthropic` | Uses Anthropic API - requires `ANTHROPIC_API_KEY` |

## Daemon Management

Cortex runs as a singleton daemon in Docker. The daemon starts automatically when Claude Code connects, but you can manage it manually:

```bash
# Check daemon status and version
cortex daemon status

# View daemon logs
cortex daemon logs

# Restart with latest code changes
cortex daemon rebuild

# Stop the daemon
cortex daemon stop
```

### Checking if Daemon is Up to Date

After pulling code changes or making local edits, verify the daemon is current:

```bash
cortex daemon status
```

This shows the daemon's git commit vs your local HEAD. If they differ, run `cortex daemon rebuild`.

You can also check from within a Claude Code session using the `get_cortex_version` MCP tool - just ask "is Cortex up to date?"

## MCP Tools

### Core Tools

| Tool | Description |
|------|-------------|
| `search_cortex` | Search memory with hybrid retrieval + reranking |
| `ingest_code_into_cortex` | Index a codebase with AST chunking and delta sync |
| `commit_to_cortex` | Save session summary + re-index changed files |
| `save_note_to_cortex` | Store notes, decisions, or documentation |

### Context Tools

| Tool | Description |
|------|-------------|
| `set_repo_context` | Set static tech stack info for a repository (e.g., "Python, FastAPI, PostgreSQL") |
| `set_initiative` | Set current workstream/epic with name and status |
| `update_initiative_status` | Quick update for initiative status without changing name |
| `get_context_from_cortex` | Retrieve tech stack and initiative context |

### Admin Tools

| Tool | Description |
|------|-------------|
| `configure_cortex` | Adjust min_score, verbose mode, top_k settings |
| `toggle_cortex` | Enable/disable for A/B testing |
| `get_cortex_version` | Check daemon version and if rebuild is needed |
| `get_skeleton` | Get file tree structure for a project |

## Selective Ingestion

For large codebases, you can index only specific directories using glob patterns:

```python
# Index only the API and auth packages
ingest_code_into_cortex("/path/to/monorepo", include_patterns=["services/api/**", "packages/auth/**"])
```

### Cortexignore Files

Cortex supports `.gitignore`-style exclusion files at two levels:

| File | Scope | Description |
|------|-------|-------------|
| `~/.cortex/cortexignore` | Global | Applies to all projects |
| `<project>/.cortexignore` | Project | Project-specific exclusions |

Both files are automatically merged with built-in defaults (node_modules, .venv, dist, etc.).

**Example `~/.cortex/cortexignore`:**
```
# Generated files (all projects)
*.pb.go
*_generated.py
*.min.js

# Large assets
*.wasm
vendor/
```

**Example `<project>/.cortexignore`:**
```
# Project-specific exclusions
fixtures/
test_data/large_files/
```

To skip loading cortexignore files entirely:
```python
ingest_code_into_cortex("/path/to/project", use_cortexignore=False)
```

## Supported Languages (AST Chunking)

Python, JavaScript, TypeScript, Java, Go, Rust, Ruby, PHP, C/C++, C#, Swift, Kotlin, Scala, Solidity, Lua, Haskell, Elixir, Markdown, HTML

Files with unsupported extensions are still indexed using generic text splitting.

## Architecture

```
┌─────────────────┐     stdio      ┌──────────────────┐
│   Claude Code   │ ◄────────────► │   MCP Server     │
└─────────────────┘                └────────┬─────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
            ┌───────▼───────┐      ┌────────▼────────┐     ┌────────▼────────┐
            │ Hybrid Search │      │    Ingestion    │     │   Note/Commit   │
            │ Vector + BM25 │      │  AST + Haiku    │     │     Storage     │
            └───────┬───────┘      └────────┬────────┘     └─────────────────┘
                    │                       │
            ┌───────▼───────┐      ┌────────▼────────┐
            │   FlashRank   │      │    ChromaDB     │
            │   Reranker    │      │   (Embedded)    │
            └───────────────┘      └─────────────────┘
```

## Debugging

### Debug Logging

Enable debug logging in `~/.cortex/settings.json`:
```json
{
  "debug": true
}
```

Then restart the daemon and tail the log:
```bash
cortex daemon restart
tail -f ~/.cortex/cortex.log
```

### HTTP Debug Server

The HTTP debug server runs on port 8080 by default when the daemon is running.

Debug endpoints:
- `GET /debug/stats` - Collection statistics by project/type/language
- `GET /debug/sample?limit=10` - Sample documents
- `GET /debug/list?project=X` - List documents by project
- `GET /debug/get/{doc_id}` - Get specific document
- `GET /debug/search?q=X` - Raw search with timing info

Phase 2 endpoints (for CLI/Web Clipper):
- `GET /search?q=X&limit=5` - Search with reranking
- `POST /ingest` - Ingest web content
- `POST /note` - Save a note

## Troubleshooting

### macOS Permission Popups

If you see repeated "iTerm wants to access data from other applications" popups when the MCP server starts, grant Full Disk Access to your terminal and Docker:

1. Open **System Settings → Privacy & Security → Full Disk Access**
2. Add these applications:
   - **iTerm** (or your terminal app)

This allows the iTerm build process to access the Cortex source directory without triggering macOS TCC (Transparency, Consent, and Control) prompts.

## Development

### Run Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

### Project Structure

```
Cortex/
├── cortex                 # Wrapper script (install to /usr/local/bin)
├── src/
│   ├── server.py          # MCP server entry point
│   ├── tools/             # MCP tool implementations
│   │   ├── search.py      # search_cortex
│   │   ├── ingest.py      # ingest_code_into_cortex
│   │   ├── context.py     # set_repo_context, set_initiative, etc.
│   │   ├── notes.py       # save_note, commit_to_cortex
│   │   └── admin.py       # configure, toggle, get_version, get_skeleton
│   ├── search/            # Hybrid search, BM25, reranker
│   ├── ingest/            # AST chunking, delta sync, skeleton
│   ├── storage/           # ChromaDB, garbage collection
│   ├── security/          # Secret scrubbing
│   ├── git/               # Branch detection, delta tracking
│   └── http/              # FastAPI debug endpoints
├── tests/                 # pytest test suite
├── requirements.txt       # Python dependencies
└── Dockerfile             # Container definition
```

## License

MIT
