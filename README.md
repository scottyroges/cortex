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

### Install

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

### Configure Claude Code

**Option 1: CLI (recommended)**
```bash
claude mcp add -s user -e CORTEX_CODE_PATHS=~/Projects,~/Work -- cortex cortex
```

**Option 2: Manual config**

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex",
      "env": {
        "CORTEX_CODE_PATHS": "~/Projects,~/Work"
      }
    }
  }
}
```

Then restart Claude Code. The wrapper handles Docker mounting automatically.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_cortex` | Search memory with hybrid retrieval + reranking |
| `ingest_code_into_cortex` | Index a codebase with AST chunking and delta sync |
| `commit_to_cortex` | Save session summary + re-index changed files |
| `save_note_to_cortex` | Store notes, decisions, or documentation |
| `configure_cortex` | Adjust min_score, verbose mode, top_k settings |
| `toggle_cortex` | Enable/disable for A/B testing |

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

## Configuration

### Environment Variables

Set these in your MCP config's `env` block:

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_CODE_PATHS` | - | Comma-separated code directories (e.g., `~/Projects,~/Work`) |
| `CORTEX_DATA_PATH` | `~/.cortex` | Where to store Cortex data |
| `CORTEX_HEADER_PROVIDER` | `none` | Header provider: `anthropic`, `claude-cli`, or `none` |
| `CORTEX_DEBUG` | `false` | Enable debug logging |
| `CORTEX_LOG_FILE` | `$CORTEX_DATA_PATH/cortex.log` | Log file path |
| `CORTEX_HTTP` | `false` | Enable HTTP debug server |
| `CORTEX_HTTP_PORT` | `8080` | HTTP server port |
| `ANTHROPIC_API_KEY` | - | Required for `header_provider=anthropic` |

**Example with all options** (in `~/.claude.json`):
```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex",
      "env": {
        "CORTEX_CODE_PATHS": "~/Projects,~/Work",
        "CORTEX_HEADER_PROVIDER": "claude-cli",
        "CORTEX_DEBUG": "true"
      }
    }
  }
}
```

### Runtime Settings

Adjust via `configure_cortex` tool:

| Setting | Default | Description |
|---------|---------|-------------|
| `min_score` | 0.3 | Minimum rerank score threshold (0-1) |
| `verbose` | false | Include debug info in responses |
| `top_k_retrieve` | 50 | Candidates before reranking |
| `top_k_rerank` | 5 | Final results after reranking |

### Header Providers

Contextual headers add AI-generated summaries to each code chunk:

| Provider | Description |
|----------|-------------|
| `none` | No headers (fastest, default) |
| `claude-cli` | Uses Claude CLI - leverages your existing Claude auth |
| `anthropic` | Uses Anthropic API - requires `ANTHROPIC_API_KEY` |

## Debugging

### Debug Logging

Enable debug logging in your MCP config:
```json
"env": {
  "CORTEX_DEBUG": "true"
}
```

Then tail the log:
```bash
tail -f ~/.cortex/cortex.log
```

### HTTP Debug Server

```json
"env": {
  "CORTEX_HTTP": "true"
}
```

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
   - **Docker** (or Docker Desktop)

This allows the Docker build process to access the Cortex source directory without triggering macOS TCC (Transparency, Consent, and Control) prompts.

## Development

### Run Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

### Project Structure

```
Cortex/
├── cortex             # Wrapper script (install to /usr/local/bin)
├── server.py          # MCP server + tool definitions
├── rag_utils.py       # ChromaDB, FlashRank, BM25, secret scrubbing
├── ingest.py          # File walking, AST chunking, delta sync
├── http_server.py     # FastAPI debug/Phase 2 endpoints
├── logging_config.py  # Debug logging configuration
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container definition
└── tests/             # pytest test suite
```

## License

MIT
