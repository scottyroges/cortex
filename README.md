# Cortex

A local, privacy-first memory system for Claude Code. Provides RAG capabilities with ChromaDB vector storage, BM25 keyword search, and FlashRank reranking.

## Features

- **Hybrid Search**: Vector + BM25 with Reciprocal Rank Fusion, then FlashRank cross-encoder reranking
- **Semantic Memory**: Insights, notes, and session commits that capture understanding
- **Initiative Tracking**: Multi-session work with focus system and progress summaries
- **AST-Aware Chunking**: Respects function/class boundaries for 20+ languages
- **Delta Sync**: Only re-indexes changed files (git-based change detection)
- **Secret Scrubbing**: Automatically redacts API keys, tokens, and credentials
- **Memory Browser**: Web UI at `http://localhost:8080` for exploring stored memories
- **Auto-Update**: `cortex update` command with migrations and health checks
- **Auto-Capture**: Automatic session memory via Claude Code hooks - no manual saves needed

## Quick Start

### 1. Clone and Symlink

```bash
# Clone the repository
git clone https://github.com/scottyroges/Cortex.git
cd Cortex

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

This will ask you for:
- **Code paths**: Directories containing code to index
- **Header provider**: AI-generated summaries (none/claude-cli/anthropic)
- **Debug mode**: Enable verbose logging
- **Daemon port**: Port for MCP communication (default: 8000)
- **HTTP port**: Port for debug server and CLI (default: 8080)

### 3. Start the Daemon

```bash
cortex daemon start
```

This builds the Docker image (first time only) and starts the daemon.

### 4. Add to Claude Code

```bash
claude mcp add cortex cortex --scope user
```

The `--scope user` flag makes Cortex available in all projects. Then restart Claude Code. That's it!

## Configuration

### Config File

Cortex configuration lives at `~/.cortex/config.yaml`. Create it with `cortex init` or edit manually:

```yaml
# Directories containing code to index (mounted into Docker)
code_paths:
  - ~/Projects
  - ~/Work

# Daemon port for MCP communication
daemon_port: 8000

# HTTP debug server port
http_port: 8080

# Enable debug logging
debug: false

# LLM provider for summarization
llm:
  primary_provider: "claude-cli"

# Auto-capture settings
autocapture:
  enabled: true
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `code_paths` | list | `[]` | Directories containing code to index |
| `debug` | bool | `false` | Enable debug logging |
| `daemon_port` | int | `8000` | Daemon port for MCP communication |
| `http_port` | int | `8080` | HTTP debug server port |
| `llm.primary_provider` | string | `"claude-cli"` | LLM provider for summarization |
| `autocapture.enabled` | bool | `true` | Enable auto-capture on session end |

### Managing Configuration

```bash
# View current config
cortex config

# Edit config in your $EDITOR
cortex config edit
```

After changing config, restart the daemon:
```bash
cortex daemon restart
```

### Environment Variable Overrides

Environment variables can override config.yaml (useful for CI/testing):

| Variable | Description |
|----------|-------------|
| `CORTEX_CODE_PATHS` | Comma-separated code directories |
| `CORTEX_DEBUG` | Enable debug logging |
| `CORTEX_DAEMON_PORT` | Daemon port (default: `8000`) |
| `CORTEX_HTTP_PORT` | HTTP debug server port (default: `8080`) |
| `ANTHROPIC_API_KEY` | Required for LLM provider="anthropic" |

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

# Update Cortex (pull, rebuild, migrate, restart)
cortex update

# Health check
cortex doctor              # Quick essential checks
cortex doctor --verbose    # Comprehensive diagnostics

# Hook management (for auto-capture)
cortex hooks status        # Check hook installation status
cortex hooks install       # Install Claude Code hooks
cortex hooks repair        # Fix broken hook installation
cortex hooks uninstall     # Remove hooks
```

### Checking if Daemon is Up to Date

After pulling code changes or making local edits, verify the daemon is current:

```bash
cortex daemon status
```

This shows the daemon's git commit vs your local HEAD. If they differ, run `cortex update` to pull latest changes, rebuild, and restart.

You can also check from within a Claude Code session using `orient_session` - it now includes `update_available: true` when your local code is newer than the running daemon.

## MCP Tools (12 Consolidated)

### Session & Search

| Tool | Description |
|------|-------------|
| `orient_session` | Entry point for sessions - returns index status, context, initiatives, and update availability |
| `search_cortex` | Search memory with hybrid retrieval + reranking |
| `recall_recent_work` | Timeline view of recent work. Answers "What did I work on this week?" |

### Memory Storage

| Tool | Description |
|------|-------------|
| `save_memory` | Save notes or insights. Use `kind="note"` for decisions/docs, `kind="insight"` for file-linked analysis |
| `conclude_session` | End-of-session summary with changed files. Captures context for next session |
| `validate_insight` | Verify stale insights against current code. Deprecate if invalid, optionally create replacement |

### Initiatives

| Tool | Description |
|------|-------------|
| `manage_initiative` | Unified initiative management: `action="create"`, `"list"`, `"focus"`, `"complete"`, or `"summarize"` |

### Ingestion & Structure

| Tool | Description |
|------|-------------|
| `ingest_codebase` | Index codebase with AST chunking. Use `action="ingest"` or `action="status"` for async tasks |
| `get_skeleton` | Get file tree structure for a repository |

### Configuration

| Tool | Description |
|------|-------------|
| `configure_cortex` | Unified config: runtime settings, repo tech stack (`repository` + `tech_stack`), autocapture, and `get_status=True` for system status |

### Storage Management

| Tool | Description |
|------|-------------|
| `cleanup_storage` | Remove orphaned file_metadata, insights, and dependencies for deleted files. Use `action="preview"` to see what would be deleted, `action="execute"` to delete |
| `delete_document` | Delete a single document by ID (e.g., `note:abc123`, `insight:def456`) |

**Initiative Workflow:**
- New session summaries and notes are automatically tagged with the focused initiative
- `orient_session` detects stale initiatives (inactive > 5 days) and prompts for action
- `conclude_session` detects completion signals ("done", "complete", "shipped") and prompts to close
- Completed initiatives remain searchable with recency decay

**Insight Staleness Detection (Remember but Verify):**
- When insights are created, file hashes are stored for linked files
- Search results include staleness warnings when linked files have changed
- Claude should re-read linked files before trusting stale insights
- Use `validate_insight` to mark insights as still valid (refreshes hashes) or deprecated

## Auto-Capture

Cortex automatically captures session summaries when Claude Code sessions end. No manual `conclude_session` calls needed.

### How It Works

1. **Hook Installation**: Cortex registers a `SessionEnd` hook with Claude Code
2. **Transcript Parsing**: When a session ends, the hook parses the JSONL transcript
3. **Significance Detection**: Only "significant" sessions are captured (configurable thresholds)
4. **LLM Summarization**: An LLM generates a summary of what was accomplished
5. **Async Storage**: Summary is queued and saved by the daemon (non-blocking)

### Setup

Hooks are installed automatically when the daemon starts. Verify with:

```bash
cortex hooks status
```

If hooks aren't installed, run:

```bash
cortex hooks install
```

### Configuration

Auto-capture settings live in `~/.cortex/config.yaml`:

```yaml
autocapture:
  enabled: true
  significance:
    min_tokens: 1000       # Minimum tokens in session
    min_file_edits: 1      # Minimum files edited
    min_tool_calls: 3      # Minimum tool calls

llm:
  primary_provider: claude-cli  # Or: anthropic, ollama, openrouter
  fallback_chain:
    - claude-cli
    - ollama
```

A session is captured if it meets ANY threshold (not all).

### LLM Providers

| Provider | Requirements |
|----------|--------------|
| `claude-cli` | Claude CLI installed and authenticated (default) |
| `anthropic` | `ANTHROPIC_API_KEY` environment variable |
| `ollama` | Ollama running locally with a model |
| `openrouter` | `OPENROUTER_API_KEY` environment variable |

### Debugging

Check auto-capture status:

```bash
# Via MCP tool
get_autocapture_status

# Hook logs
cat ~/.cortex/hook.log

# Captured sessions list
cat ~/.cortex/captured_sessions.json
```

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

Enable debug logging in `~/.cortex/config.yaml`:
```yaml
debug: true
```

Then restart the daemon and tail the log:
```bash
cortex daemon restart
tail -f ~/.cortex/cortex.log
```

### HTTP Server & Memory Browser

The HTTP server runs on port 8080 by default when the daemon is running.

**Memory Browser**: Visit `http://localhost:8080` to explore stored memories with a web UI.

API endpoints:
- `GET /search?q=X&limit=5` - Search with reranking
- `POST /ingest` - Ingest web content
- `POST /note` - Save a note
- `GET /info` - Build info and version
- `GET /migrations/status` - Schema version info
- `POST /admin/backup` - Create database backup
- `GET /admin/backups` - List available backups

Debug endpoints:
- `GET /debug/stats` - Collection statistics by repository/type/language
- `GET /debug/sample?limit=10` - Sample documents
- `GET /debug/list?repository=X` - List documents by repository
- `GET /debug/get/{doc_id}` - Get specific document
- `GET /debug/search?q=X` - Raw search with timing info

Browse endpoints (for Memory Browser):
- `GET /browse/stats` - Memory statistics
- `GET /browse/documents` - Paginated document list
- `GET /browse/document/{doc_id}` - Document details

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

### Health Check

Use the `doctor` command to verify your Cortex installation:

```bash
# Quick essential checks
cortex doctor

# Comprehensive diagnostics
cortex doctor --verbose
```

### Updating Cortex

Users can update their Cortex installation with a single command:

```bash
cortex update
```

This will:
1. Create a backup of the database
2. Pull the latest code (if installed via git clone)
3. Rebuild the Docker image
4. Run any pending migrations
5. Restart the daemon

### Creating a Release

To create a new release:

1. **Update version number** in `src/version.py`:
   ```python
   "version": "1.1.0",  # Update this
   ```

2. **Run the test suite**:
   ```bash
   pytest tests/ -v
   ```

3. **Commit and tag**:
   ```bash
   git add -A
   git commit -m "Release v1.1.0"
   git tag v1.1.0
   git push origin main --tags
   ```

4. **Verify** users can update:
   ```bash
   cortex update
   cortex doctor --verbose  # Should show new version
   ```

### Migration System

Cortex uses schema versioning for database migrations:

- **Schema version** is tracked in `~/.cortex/db/schema_version.json`
- **Migrations run automatically** on daemon startup
- **Backups are created** before each migration at `~/.cortex/backups/`

To add a new migration:

1. Increment `SCHEMA_VERSION` in `src/migrations/runner.py`
2. Add migration function in `src/migrations/migrations.py`
3. Register it in `get_migrations()` in `runner.py`

```python
# src/migrations/migrations.py
def migration_002_add_new_field():
    """Add new_field to all documents of type X."""
    from src.tools.services import get_collection
    collection = get_collection()
    # ... migration logic
```

```python
# src/migrations/runner.py
SCHEMA_VERSION = 2  # Increment

def get_migrations():
    return [
        (1, "Initial schema version tracking", m.migration_001_initial),
        (2, "Add new field", m.migration_002_add_new_field),  # Add new migration
    ]
```

### Project Structure

```
Cortex/
├── cortex                 # Wrapper script (install to /usr/local/bin)
├── hooks/                 # Claude Code hook scripts
│   └── claude_session_end.py  # SessionEnd hook for auto-capture
├── src/
│   ├── server.py          # MCP server entry point
│   ├── version.py         # Version checking and update detection
│   ├── config.py          # Configuration (config.yaml)
│   ├── tools/             # MCP tool implementations (12 consolidated tools)
│   │   ├── orient.py      # orient_session (session entry point)
│   │   ├── search.py      # search_cortex
│   │   ├── ingest.py      # ingest_codebase (action="ingest" or "status")
│   │   ├── notes.py       # save_memory, conclude_session, validate_insight
│   │   ├── initiatives.py # manage_initiative (action=create/list/focus/complete/summarize)
│   │   ├── recall.py      # recall_recent_work
│   │   ├── admin.py       # configure_cortex, get_skeleton
│   │   └── storage.py     # cleanup_storage, delete_document
│   ├── autocapture/       # Auto-capture system
│   │   ├── transcript.py  # JSONL transcript parsing
│   │   ├── significance.py # Significance detection
│   │   └── queue_processor.py # Async queue processing
│   ├── llm/               # LLM provider abstraction
│   │   ├── provider.py    # Base LLMProvider class
│   │   ├── anthropic_provider.py
│   │   ├── claude_cli_provider.py
│   │   ├── ollama_provider.py
│   │   └── openrouter_provider.py
│   ├── install/           # Hook installation
│   │   ├── hooks.py       # Hook management interface
│   │   └── claude_code.py # Claude Code integration
│   ├── migrations/        # Schema versioning and database migrations
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
