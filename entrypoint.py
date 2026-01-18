#!/usr/bin/env python3
"""
Cortex Container Entrypoint

Dispatches to the appropriate mode based on command line argument.

Modes:
  daemon  - Run HTTP server for MCP requests (default)
  bridge  - Run stdio-to-HTTP bridge for Claude Code session
  stdio   - Run original stdio MCP server (backward compatibility)
"""

import sys


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if mode == "daemon":
        # Run HTTP server as daemon
        import os
        from logging_config import get_logger
        from src.http import run_server
        from src.autocapture import start_processor

        logger = get_logger("entrypoint")

        # Check and run migrations before starting server
        try:
            from src.migrations import needs_migration, run_migrations, backup_database

            if needs_migration():
                logger.info("Schema migration required")
                try:
                    # Backup before migration
                    backup_path = backup_database(label="pre_migration")
                    logger.info(f"Backup created: {backup_path}")

                    # Run migrations
                    result = run_migrations()
                    if result["status"] == "complete":
                        logger.info(f"Migrations complete: v{result['current_version']}")
                    else:
                        logger.warning(f"Migration incomplete: {result}")
                except Exception as e:
                    logger.error(f"Migration failed: {e}")
                    # Continue anyway - migrations should be non-destructive
        except Exception as e:
            logger.warning(f"Could not check migrations: {e}")

        # Start the queue processor for async auto-capture
        start_processor()
        logger.info("Queue processor started")

        port = int(os.environ.get("CORTEX_HTTP_PORT", "8080"))
        run_server(host="0.0.0.0", port=port)

    elif mode == "bridge":
        # Run stdio-to-HTTP bridge
        from mcp_bridge import main as bridge_main
        bridge_main()

    elif mode == "stdio":
        # Original stdio MCP server (backward compatibility)
        from src.server import mcp
        mcp.run()

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        print("Usage: entrypoint.py [daemon|bridge|stdio]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
