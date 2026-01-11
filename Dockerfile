FROM python:3.11-slim

WORKDIR /app

# Build arguments for version tracking
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

# Set as environment variables for runtime access
ENV CORTEX_GIT_COMMIT=$GIT_COMMIT
ENV CORTEX_BUILD_TIME=$BUILD_TIME

# Install git for branch detection and build-essential for Chroma/Numpy
RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

# Install dependencies (cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create persistence directory
RUN mkdir -p /app/cortex_db

# Expose ports:
#   8000 - MCP daemon HTTP API
#   8080 - Debug/Phase 2 HTTP endpoints
EXPOSE 8000 8080

# Entrypoint dispatcher supports multiple modes:
#   daemon  - Run HTTP server for MCP requests (default)
#   bridge  - Run stdio-to-HTTP bridge for Claude Code session
#   stdio   - Run original stdio MCP server (backward compatibility)
#
# Environment variables:
#   CORTEX_DEBUG=true           Enable debug logging
#   CORTEX_LOG_FILE=path        Log file path
#   CORTEX_HEADER_PROVIDER=X    Header provider: "anthropic", "claude-cli", or "none"
#   CORTEX_DB_PATH=path         Custom database path
#   CORTEX_DAEMON_URL=url       Daemon URL (for bridge mode)
ENTRYPOINT ["python", "entrypoint.py"]
CMD ["daemon"]
