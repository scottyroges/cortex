#!/usr/bin/env python3
"""
Summarization Proxy Server

A lightweight HTTP server that wraps the claude CLI for session summarization.
Runs on the host so the Docker daemon can access the claude CLI.

Usage:
    python -m src.summarizer.server --port 8081

The server exposes a single endpoint:
    POST /summarize
    Body: {"transcript": "...", "model": "haiku"}
    Returns: {"summary": "..."}
"""

import argparse
import json
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

# Default summarization prompt
SUMMARIZE_PROMPT = """Summarize this Claude Code session transcript for future reference.
Focus on:
1. What was implemented or changed
2. Key decisions made and why
3. Problems encountered and solutions
4. Files that were modified

Keep it concise but include enough detail to understand the work done.
Output ONLY the summary, no preamble.

Transcript:
{transcript}"""


class SummarizeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for summarization requests."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/summarize":
            self._handle_summarize()
        elif self.path == "/generate":
            self._handle_generate()
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_summarize(self):
        """Handle /summarize endpoint - wraps input in summarization prompt."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json({"error": f"Invalid JSON: {e}"}, 400)
            return

        transcript = data.get("transcript", "")
        model = data.get("model", "haiku")

        if not transcript:
            self._send_json({"error": "Missing transcript"}, 400)
            return

        # Truncate very long transcripts
        max_chars = 100000
        if len(transcript) > max_chars:
            transcript = transcript[:max_chars] + "\n\n[Transcript truncated...]"

        summary = summarize_with_claude(transcript, model)
        if summary:
            self._send_json({"summary": summary})
        else:
            self._send_json({"error": "Summarization failed"}, 500)

    def _handle_generate(self):
        """Handle /generate endpoint - passes prompt directly to Claude."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json({"error": f"Invalid JSON: {e}"}, 400)
            return

        prompt = data.get("prompt", "")
        model = data.get("model", "haiku")
        max_tokens = data.get("max_tokens", 1024)

        if not prompt:
            self._send_json({"error": "Missing prompt"}, 400)
            return

        # Truncate very long prompts
        max_chars = 100000
        if len(prompt) > max_chars:
            prompt = prompt[:max_chars] + "\n\n[Prompt truncated...]"

        response = generate_with_claude(prompt, model, max_tokens)
        if response:
            self._send_json({"text": response})
        else:
            self._send_json({"error": "Generation failed"}, 500)


def summarize_with_claude(transcript: str, model: str = "haiku") -> Optional[str]:
    """
    Generate a summary using the claude CLI.

    Args:
        transcript: Session transcript text
        model: Model to use (haiku, sonnet, opus)

    Returns:
        Summary text or None on failure
    """
    prompt = SUMMARIZE_PROMPT.format(transcript=transcript)
    return generate_with_claude(prompt, model)


def generate_with_claude(prompt: str, model: str = "haiku", max_tokens: int = 1024) -> Optional[str]:
    """
    Generate completion using the claude CLI (raw pass-through).

    Args:
        prompt: The prompt to send to Claude
        model: Model to use (haiku, sonnet, opus)
        max_tokens: Maximum tokens to generate (not currently used - CLI uses defaults)

    Returns:
        Generated text or None on failure
    """
    try:
        # Note: Claude CLI doesn't support --max-tokens flag, uses its own defaults
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Claude CLI error: {result.stderr}", file=sys.stderr)
            return None

    except subprocess.TimeoutExpired:
        print("Claude CLI timed out", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("Claude CLI not found", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Generation error: {e}", file=sys.stderr)
        return None


def run_server(port: int = 8081):
    """Run the summarization server."""
    server = HTTPServer(("0.0.0.0", port), SummarizeHandler)
    print(f"Summarizer listening on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSummarizer stopped")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Cortex Summarization Proxy")
    parser.add_argument("--port", type=int, default=8081, help="Port to listen on")
    args = parser.parse_args()

    run_server(args.port)


if __name__ == "__main__":
    main()
