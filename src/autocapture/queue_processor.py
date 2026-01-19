"""
Async Queue Processor for Auto-Capture

Processes queued sessions in the background, generating summaries
and saving to Cortex without blocking Claude Code session exit.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from logging_config import get_logger
from src.config import get_data_path

logger = get_logger("autocapture.queue")

QUEUE_FILE = get_data_path() / "capture_queue.json"
PROCESSING_INTERVAL = 5  # seconds between queue checks


class QueueProcessor:
    """
    Background processor for the auto-capture queue.

    Runs in a daemon thread, periodically checking for queued sessions
    and processing them asynchronously.
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._process_event = threading.Event()

    def start(self):
        """Start the background processor thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Queue processor started")

    def stop(self):
        """Stop the background processor thread."""
        self._running = False
        self._process_event.set()  # Wake up the thread
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Queue processor stopped")

    def trigger_processing(self):
        """Trigger immediate queue processing (called by HTTP endpoint)."""
        self._process_event.set()

    def _run_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                self._process_queue()
            except Exception as e:
                logger.error(f"Queue processing error: {e}")

            # Wait for next interval or trigger
            self._process_event.wait(timeout=PROCESSING_INTERVAL)
            self._process_event.clear()

    def _process_queue(self):
        """Process all pending sessions in the queue."""
        if not QUEUE_FILE.exists():
            return

        with self._lock:
            try:
                queue = json.loads(QUEUE_FILE.read_text())
            except Exception as e:
                logger.warning(f"Failed to read queue: {e}")
                return

            if not queue:
                return

            logger.info(f"Processing {len(queue)} queued sessions")

            # Process each session
            processed_ids = []
            for session in queue:
                session_id = session.get("session_id", "unknown")
                try:
                    success = self._process_session(session)
                    if success:
                        processed_ids.append(session_id)
                        logger.info(f"Processed session: {session_id}")
                    else:
                        logger.warning(f"Failed to process session: {session_id}")
                except Exception as e:
                    logger.error(f"Error processing session {session_id}: {e}")

            # Remove processed sessions from queue (atomic write)
            if processed_ids:
                remaining = [s for s in queue if s.get("session_id") not in processed_ids]
                # Atomic write: write to temp file, then rename
                fd, tmp_path = tempfile.mkstemp(dir=str(QUEUE_FILE.parent))
                try:
                    with os.fdopen(fd, "w") as f:
                        json.dump(remaining, f, indent=2)
                    os.replace(tmp_path, str(QUEUE_FILE))
                except Exception:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    raise
                logger.info(f"Removed {len(processed_ids)} processed sessions from queue")

    def _process_session(self, session: dict) -> bool:
        """
        Process a single queued session.

        Generates summary using LLM and saves to Cortex.
        Returns True if successful.
        """
        from src.config import load_yaml_config
        from src.llm import get_provider
        from src.tools.notes import conclude_session

        session_id = session.get("session_id", "unknown")
        transcript_text = session.get("transcript_text", "")
        files_edited = session.get("files_edited", [])
        repository = session.get("repository", "global")

        if not transcript_text:
            logger.warning(f"Empty transcript for session {session_id}")
            return True  # Consider it "processed" to remove from queue

        # Load config and get LLM provider
        try:
            config = load_yaml_config()
            provider = get_provider(config)
        except Exception as e:
            logger.error(f"No LLM provider available: {e}")
            return False  # Keep in queue for retry

        # Generate summary
        try:
            logger.debug(f"Generating summary for session {session_id}")
            summary = provider.summarize_session(transcript_text)
            logger.debug(f"Generated summary ({len(summary)} chars)")
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return False  # Keep in queue for retry

        # Save to Cortex
        try:
            result = conclude_session(
                summary=summary,
                changed_files=files_edited,
                repository=repository,
            )
            logger.info(f"Saved session summary {session_id} to Cortex: {repository}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session summary to Cortex: {e}")
            return False


# Global processor instance
_processor: Optional[QueueProcessor] = None


def get_processor() -> QueueProcessor:
    """Get the global queue processor instance."""
    global _processor
    if _processor is None:
        _processor = QueueProcessor()
    return _processor


def start_processor():
    """Start the global queue processor."""
    get_processor().start()


def stop_processor():
    """Stop the global queue processor."""
    if _processor:
        _processor.stop()


def trigger_processing():
    """Trigger immediate queue processing."""
    if _processor:
        _processor.trigger_processing()
