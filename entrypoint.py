#!/usr/bin/env python3
"""
Cortex Container Entrypoint

Dispatches to the appropriate mode based on command line argument.

Modes:
  daemon  - Run HTTP server for MCP requests (default)
  bridge  - Run stdio-to-HTTP bridge for Claude Code session
"""

import sys


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if mode == "daemon":
        # Run HTTP server as daemon
        import os
        from src.configs import get_logger, setup_logging
        from src.controllers.http import run_server
        from src.tools.autocapture import start_processor
        from src.tools.ingest.async_processor import start_worker as start_ingestion_worker

        # Initialize logging (must be called before get_logger)
        setup_logging()
        logger = get_logger("entrypoint")

        # Check and run migrations before starting server
        try:
            from src.storage.migrations import needs_migration, run_migrations, backup_database

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

        # Start the async ingestion worker
        start_ingestion_worker()
        logger.info("Ingestion worker started")

        port = int(os.environ.get("CORTEX_HTTP_PORT", "8080"))
        run_server(host="0.0.0.0", port=port)

    elif mode == "bridge":
        # Run stdio-to-HTTP bridge
        from src.controllers.bridge import main as bridge_main
        bridge_main()

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        print("Usage: entrypoint.py [daemon|bridge]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
