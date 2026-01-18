"""
Base LLM Provider Interface

Defines the abstract base class for all LLM providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class LLMConfig:
    """Configuration for an LLM generation request."""

    model: Optional[str] = None  # Use provider default if None
    max_tokens: int = 1000
    temperature: float = 0.3
    timeout: int = 60  # seconds


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    text: str
    model: str
    tokens_used: int = 0
    latency_ms: float = 0.0
    provider: str = ""


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All providers must implement is_available() and generate().
    The summarize_session() method uses the default summarization prompt
    but can be overridden for provider-specific behavior.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and identification."""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model to use if none specified."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if provider is configured and reachable.

        Returns:
            True if the provider can be used, False otherwise.
        """
        pass

    @abstractmethod
    def generate(self, prompt: str, config: Optional[LLMConfig] = None) -> LLMResponse:
        """
        Generate a completion for the given prompt.

        Args:
            prompt: The prompt text
            config: Optional configuration overrides

        Returns:
            LLMResponse with generated text and metadata

        Raises:
            Exception: If generation fails
        """
        pass

    def summarize_session(self, transcript_text: str, max_chars: int = 100000) -> str:
        """
        Generate a session summary using the provider.

        Args:
            transcript_text: The full session transcript text
            max_chars: Maximum characters of transcript to include

        Returns:
            Generated summary text
        """
        # Truncate if needed
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "\n\n[... transcript truncated ...]"

        prompt = self._build_summary_prompt(transcript_text)
        config = LLMConfig(max_tokens=1500, temperature=0.3)
        response = self.generate(prompt, config)
        return response.text.strip()

    def _build_summary_prompt(self, transcript: str) -> str:
        """Build the summarization prompt."""
        return f"""Analyze this Claude Code session transcript and write a detailed summary for future reference.

Focus on:
1. **What was implemented or changed** - Specific features, fixes, or modifications made
2. **Why** - The reasoning and motivation behind the changes
3. **Key architectural decisions** - Important design choices and their rationale
4. **Problems encountered** - Issues faced and how they were resolved
5. **Non-obvious patterns or gotchas** - Learnings that would be helpful to know later
6. **Future work or TODOs** - Items identified for follow-up

Write a comprehensive but concise summary (2-4 paragraphs). Use specific file names and technical details where relevant. This summary will be used to restore context in future sessions.

Session Transcript:
---
{transcript}
---

Summary:"""

    def generate_code_header(
        self,
        chunk: str,
        file_path: str,
        language: str,
    ) -> str:
        """
        Generate a brief description header for a code chunk.

        Args:
            chunk: The code chunk text
            file_path: Path to the source file
            language: Programming language name

        Returns:
            Brief 1-2 sentence description
        """
        prompt = f"""Analyze this {language} code chunk from {file_path} and provide a brief (1-2 sentence) description of what it does. Focus on the purpose and key functionality.

Code:
```{language}
{chunk[:2000]}
```

Respond with only the description, no formatting or prefixes."""

        config = LLMConfig(max_tokens=100, temperature=0.2)
        response = self.generate(prompt, config)
        return response.text.strip()
