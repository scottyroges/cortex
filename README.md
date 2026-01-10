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

### Build

```bash
docker build -t cortex .
```

### Run

```bash
docker run -i --rm \
  -v ~/cortex_db:/app/cortex_db \
  -v ~/MyProject:/projects \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  cortex
```

### Configure Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/cortex_db:/app/cortex_db",
        "-v", "/path/to/code:/projects",
        "-e", "ANTHROPIC_API_KEY=sk-ant-...",
        "cortex"
      ]
    }
  }
}
```

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

Runtime settings via `configure_cortex`:

| Setting | Default | Description |
|---------|---------|-------------|
| `min_score` | 0.3 | Minimum rerank score threshold (0-1) |
| `verbose` | false | Include debug info in responses |
| `top_k_retrieve` | 50 | Candidates before reranking |
| `top_k_rerank` | 5 | Final results after reranking |
| `use_haiku` | true | Generate contextual headers via Haiku |

## Development

### Run Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

### Project Structure

```
Cortex/
├── server.py          # MCP server + tool definitions
├── rag_utils.py       # ChromaDB, FlashRank, BM25, secret scrubbing
├── ingest.py          # File walking, AST chunking, delta sync
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container definition
└── tests/             # pytest test suite
```

## License

MIT
