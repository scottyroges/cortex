"""
Tests for Autocapture Module

Tests transcript parsing, significance calculation, and queue processing.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.autocapture.transcript import (
    ContentBlockParser,
    ContentBlockResult,
    LegacyFormatHandler,
    Message,
    ParsedTranscript,
    ToolCall,
    TranscriptMetadataExtractor,
    extract_changed_files,
    parse_transcript_file,
    parse_transcript_jsonl,
)
from src.tools.autocapture.significance import (
    DEFAULT_CONFIG,
    SignificanceConfig,
    SignificanceResult,
    calculate_significance,
    create_config_from_dict,
    is_significant,
)


# =============================================================================
# ToolCall Tests
# =============================================================================


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_file_edit_detection_write(self):
        """Write tool is detected as file edit."""
        tc = ToolCall(name="Write", input={"file_path": "/path/to/file.py"})
        assert tc.is_file_edit is True
        assert tc.edited_file == "/path/to/file.py"

    def test_file_edit_detection_edit(self):
        """Edit tool is detected as file edit."""
        tc = ToolCall(name="Edit", input={"file_path": "/path/to/file.py"})
        assert tc.is_file_edit is True
        assert tc.edited_file == "/path/to/file.py"

    def test_file_edit_detection_notebook(self):
        """NotebookEdit tool is detected as file edit."""
        tc = ToolCall(name="NotebookEdit", input={"notebook_path": "/path/to/notebook.ipynb"})
        assert tc.is_file_edit is True
        assert tc.edited_file == "/path/to/notebook.ipynb"

    def test_non_file_edit_tool(self):
        """Non-edit tools are not detected as file edits."""
        tc = ToolCall(name="Bash", input={"command": "ls -la"})
        assert tc.is_file_edit is False
        assert tc.edited_file is None

    def test_read_tool_not_file_edit(self):
        """Read tool is not a file edit."""
        tc = ToolCall(name="Read", input={"file_path": "/path/to/file.py"})
        assert tc.is_file_edit is False
        assert tc.edited_file is None


# =============================================================================
# Message Tests
# =============================================================================


class TestMessage:
    """Tests for Message dataclass."""

    def test_approximate_tokens_short(self):
        """Short content gives small token count."""
        msg = Message(role="user", content="Hello")
        assert msg.approximate_tokens == 1  # 5 chars / 4 = 1

    def test_approximate_tokens_longer(self):
        """Longer content gives proportional token count."""
        msg = Message(role="assistant", content="A" * 400)
        assert msg.approximate_tokens == 100  # 400 / 4 = 100

    def test_empty_content(self):
        """Empty content gives zero tokens."""
        msg = Message(role="user", content="")
        assert msg.approximate_tokens == 0


# =============================================================================
# ParsedTranscript Tests
# =============================================================================


class TestParsedTranscript:
    """Tests for ParsedTranscript dataclass."""

    def test_token_count_aggregates_messages(self):
        """Token count sums all message tokens."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[
                Message(role="user", content="A" * 40),  # 10 tokens
                Message(role="assistant", content="B" * 80),  # 20 tokens
            ],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        assert transcript.token_count == 30

    def test_files_edited_unique(self):
        """Files edited list contains unique sorted paths."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[],
            tool_calls=[
                ToolCall(name="Write", input={"file_path": "/b.py"}),
                ToolCall(name="Edit", input={"file_path": "/a.py"}),
                ToolCall(name="Write", input={"file_path": "/b.py"}),  # duplicate
                ToolCall(name="Read", input={"file_path": "/c.py"}),  # not edit
            ],
            start_time=None,
            end_time=None,
        )
        assert transcript.files_edited == ["/a.py", "/b.py"]

    def test_duration_seconds(self):
        """Duration calculated from start/end times."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 12, 5, 30, tzinfo=timezone.utc)
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[],
            tool_calls=[],
            start_time=start,
            end_time=end,
        )
        assert transcript.duration_seconds == 330  # 5 min 30 sec

    def test_duration_unknown_without_times(self):
        """Duration is 0 when times are unknown."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        assert transcript.duration_seconds == 0

    def test_to_text_basic(self):
        """to_text produces readable output."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[
                Message(role="user", content="Hello"),
                Message(role="assistant", content="Hi there"),
            ],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        text = transcript.to_text()
        assert "[USER]" in text
        assert "Hello" in text
        assert "[ASSISTANT]" in text
        assert "Hi there" in text

    def test_to_text_with_tool_calls(self):
        """to_text includes tool call info."""
        tc = ToolCall(name="Write", input={}, output="OK")
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[
                Message(role="assistant", content="Writing file", tool_calls=[tc]),
            ],
            tool_calls=[tc],
            start_time=None,
            end_time=None,
        )
        text = transcript.to_text()
        assert "[TOOL: Write]" in text
        assert "Output: OK" in text

    def test_to_text_max_chars_truncation(self):
        """to_text respects max_chars limit."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="A" * 1000)],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        text = transcript.to_text(max_chars=100)
        assert len(text) <= 150  # 100 + truncation message
        assert "[... transcript truncated ...]" in text


# =============================================================================
# ContentBlockParser Tests
# =============================================================================


class TestContentBlockParser:
    """Tests for ContentBlockParser."""

    def test_parse_text_block(self):
        """Parses text blocks correctly."""
        parser = ContentBlockParser()
        text = parser.parse_text_block({"type": "text", "text": "Hello"})
        assert text == "Hello"

    def test_parse_text_block_empty(self):
        """Empty text blocks return None."""
        parser = ContentBlockParser()
        text = parser.parse_text_block({"type": "text", "text": ""})
        assert text is None

    def test_parse_tool_use_block(self):
        """Parses tool_use blocks into ToolCall."""
        parser = ContentBlockParser()
        tc = parser.parse_tool_use_block({
            "type": "tool_use",
            "name": "Write",
            "input": {"file_path": "/test.py"},
        })
        assert tc.name == "Write"
        assert tc.input == {"file_path": "/test.py"}

    def test_parse_tool_result_block_string(self):
        """Parses string tool_result content."""
        parser = ContentBlockParser()
        content = parser.parse_tool_result_block({
            "type": "tool_result",
            "content": "Success",
        })
        assert content == "Success"

    def test_parse_tool_result_block_array(self):
        """Parses array tool_result content."""
        parser = ContentBlockParser()
        content = parser.parse_tool_result_block({
            "type": "tool_result",
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
        })
        assert content == "Part 1 Part 2"

    def test_parse_content_array(self):
        """Parses mixed content arrays."""
        parser = ContentBlockParser()
        result = parser.parse_content_array([
            {"type": "text", "text": "Hello"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "text", "text": "Done"},
        ])
        assert len(result.text_parts) == 2
        assert result.text_parts == ["Hello", "Done"]
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "Bash"


# =============================================================================
# TranscriptMetadataExtractor Tests
# =============================================================================


class TestTranscriptMetadataExtractor:
    """Tests for TranscriptMetadataExtractor."""

    def test_extract_timestamp_milliseconds(self):
        """Extracts timestamp from milliseconds."""
        extractor = TranscriptMetadataExtractor()
        ts = extractor.extract_timestamp({"timestamp": 1704067200000})  # 2024-01-01 00:00:00 UTC
        assert ts is not None
        assert ts.year == 2024

    def test_extract_timestamp_updates_bounds(self):
        """Timestamp extraction updates start/end times."""
        extractor = TranscriptMetadataExtractor()
        extractor.extract_timestamp({"timestamp": 1704067200000})  # Earlier
        extractor.extract_timestamp({"timestamp": 1704070800000})  # Later
        assert extractor.start_time is not None
        assert extractor.end_time is not None
        assert extractor.end_time > extractor.start_time

    def test_extract_project_path_cwd(self):
        """Extracts project path from cwd field."""
        extractor = TranscriptMetadataExtractor()
        path = extractor.extract_project_path({"cwd": "/my/project"})
        assert path == "/my/project"
        assert extractor.project_path == "/my/project"

    def test_extract_project_path_first_wins(self):
        """First project path wins."""
        extractor = TranscriptMetadataExtractor()
        extractor.extract_project_path({"cwd": "/first"})
        extractor.extract_project_path({"cwd": "/second"})
        assert extractor.project_path == "/first"


# =============================================================================
# LegacyFormatHandler Tests
# =============================================================================


class TestLegacyFormatHandler:
    """Tests for LegacyFormatHandler."""

    def test_parse_legacy_tool_use(self):
        """Parses legacy toolUse array format."""
        handler = LegacyFormatHandler()
        tools = handler.parse_legacy_tool_use(
            {
                "toolUse": [
                    {"name": "Write", "input": {"file_path": "/a.py"}},
                    {"name": "Bash", "input": {"command": "ls"}},
                ]
            },
            timestamp=None,
        )
        assert len(tools) == 2
        assert tools[0].name == "Write"
        assert tools[1].name == "Bash"


# =============================================================================
# parse_transcript_jsonl Tests
# =============================================================================


class TestParseTranscriptJsonl:
    """Tests for parse_transcript_jsonl function."""

    def test_parse_simple_messages(self):
        """Parses simple user/assistant messages."""
        content = """{"message": {"role": "user", "content": "Hello"}}
{"message": {"role": "assistant", "content": "Hi there"}}"""

        transcript = parse_transcript_jsonl(content, "test-session")
        assert transcript.session_id == "test-session"
        assert len(transcript.messages) == 2
        assert transcript.messages[0].role == "user"
        assert transcript.messages[1].role == "assistant"

    def test_parse_with_tool_calls(self):
        """Parses messages with tool calls."""
        content = json.dumps({
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me write that"},
                    {"type": "tool_use", "name": "Write", "input": {"file_path": "/test.py"}},
                ],
            }
        })

        transcript = parse_transcript_jsonl(content, "test")
        assert len(transcript.tool_calls) == 1
        assert transcript.tool_calls[0].name == "Write"

    def test_parse_with_timestamps(self):
        """Parses entries with timestamps."""
        content = json.dumps({
            "timestamp": 1704067200000,
            "message": {"role": "user", "content": "Hello"},
        })

        transcript = parse_transcript_jsonl(content, "test")
        assert transcript.start_time is not None

    def test_parse_with_project_path(self):
        """Extracts project path from entries."""
        content = json.dumps({
            "cwd": "/my/project",
            "message": {"role": "user", "content": "Hello"},
        })

        transcript = parse_transcript_jsonl(content, "test")
        assert transcript.project_path == "/my/project"

    def test_parse_invalid_json_skipped(self):
        """Invalid JSON lines are skipped."""
        content = """{"message": {"role": "user", "content": "Valid"}}
not valid json
{"message": {"role": "assistant", "content": "Also valid"}}"""

        transcript = parse_transcript_jsonl(content, "test")
        assert len(transcript.messages) == 2

    def test_parse_legacy_format(self):
        """Parses legacy toolUse format."""
        content = json.dumps({
            "message": {"role": "assistant", "content": "Working"},
            "toolUse": [{"name": "Write", "input": {"file_path": "/a.py"}}],
        })

        transcript = parse_transcript_jsonl(content, "test")
        assert len(transcript.tool_calls) == 1


# =============================================================================
# parse_transcript_file Tests
# =============================================================================


class TestParseTranscriptFile:
    """Tests for parse_transcript_file function."""

    def test_parse_file_success(self):
        """Parses transcript from file."""
        content = '{"message": {"role": "user", "content": "Hello"}}'

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(content)
            f.flush()

            try:
                transcript = parse_transcript_file(f.name)
                assert transcript.session_id == Path(f.name).stem
                assert len(transcript.messages) == 1
            finally:
                os.unlink(f.name)

    def test_parse_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_transcript_file("/nonexistent/path.jsonl")


# =============================================================================
# extract_changed_files Tests
# =============================================================================


class TestExtractChangedFiles:
    """Tests for extract_changed_files function."""

    def test_extract_changed_files(self):
        """Extracts edited files from transcript."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[],
            tool_calls=[
                ToolCall(name="Write", input={"file_path": "/a.py"}),
                ToolCall(name="Edit", input={"file_path": "/b.py"}),
            ],
            start_time=None,
            end_time=None,
        )
        files = extract_changed_files(transcript)
        assert files == ["/a.py", "/b.py"]


# =============================================================================
# SignificanceConfig Tests
# =============================================================================


class TestSignificanceConfig:
    """Tests for SignificanceConfig."""

    def test_default_values(self):
        """Default config has expected values."""
        config = SignificanceConfig()
        assert config.min_tokens == 5000
        assert config.min_file_edits == 1
        assert config.min_tool_calls == 3
        assert config.require_all is False

    def test_custom_values(self):
        """Custom config values are applied."""
        config = SignificanceConfig(
            min_tokens=1000,
            min_file_edits=5,
            min_tool_calls=10,
            require_all=True,
        )
        assert config.min_tokens == 1000
        assert config.require_all is True


# =============================================================================
# SignificanceResult Tests
# =============================================================================


class TestSignificanceResult:
    """Tests for SignificanceResult."""

    def test_summary_significant(self):
        """Summary for significant session."""
        result = SignificanceResult(
            is_significant=True,
            token_count=10000,
            file_edit_count=5,
            tool_call_count=20,
            reasons=["10000 tokens (>= 5000)", "5 file edits (>= 1)"],
        )
        summary = result.summary
        assert "Significant:" in summary
        assert "10000 tokens" in summary

    def test_summary_not_significant(self):
        """Summary for non-significant session."""
        result = SignificanceResult(
            is_significant=False,
            token_count=100,
            file_edit_count=0,
            tool_call_count=1,
            reasons=[],
        )
        summary = result.summary
        assert "Not significant:" in summary
        assert "tokens=100" in summary


# =============================================================================
# calculate_significance Tests
# =============================================================================


class TestCalculateSignificance:
    """Tests for calculate_significance function."""

    def _make_transcript(
        self, token_chars: int, files_edited: int, tool_calls: int
    ) -> ParsedTranscript:
        """Helper to create test transcript."""
        return ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="A" * token_chars)],
            tool_calls=[
                ToolCall(name="Write", input={"file_path": f"/file{i}.py"})
                for i in range(files_edited)
            ]
            + [
                ToolCall(name="Bash", input={"command": "ls"})
                for _ in range(tool_calls - files_edited)
            ]
            if tool_calls > files_edited
            else [
                ToolCall(name="Write", input={"file_path": f"/file{i}.py"})
                for i in range(files_edited)
            ],
            start_time=None,
            end_time=None,
        )

    def test_significant_by_tokens(self):
        """Session significant when token threshold met."""
        transcript = self._make_transcript(
            token_chars=20000,  # 5000 tokens
            files_edited=0,
            tool_calls=0,
        )
        result = calculate_significance(transcript)
        assert result.is_significant is True
        assert result.token_count == 5000
        assert any("tokens" in r for r in result.reasons)

    def test_significant_by_file_edits(self):
        """Session significant when file edit threshold met."""
        transcript = self._make_transcript(
            token_chars=100,  # 25 tokens
            files_edited=2,
            tool_calls=2,
        )
        result = calculate_significance(transcript)
        assert result.is_significant is True
        assert result.file_edit_count == 2
        assert any("file edits" in r for r in result.reasons)

    def test_significant_by_tool_calls(self):
        """Session significant when tool call threshold met."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="A" * 100)],
            tool_calls=[
                ToolCall(name="Bash", input={"command": f"cmd{i}"})
                for i in range(5)
            ],
            start_time=None,
            end_time=None,
        )
        result = calculate_significance(transcript)
        assert result.is_significant is True
        assert result.tool_call_count == 5
        assert any("tool calls" in r for r in result.reasons)

    def test_not_significant_below_all_thresholds(self):
        """Session not significant when below all thresholds."""
        transcript = self._make_transcript(
            token_chars=100,  # 25 tokens
            files_edited=0,
            tool_calls=1,
        )
        result = calculate_significance(transcript)
        assert result.is_significant is False
        assert result.reasons == []

    def test_require_all_mode(self):
        """require_all=True requires ALL thresholds met."""
        transcript = self._make_transcript(
            token_chars=20000,  # 5000 tokens - meets token threshold
            files_edited=0,  # does not meet edit threshold
            tool_calls=0,
        )
        config = SignificanceConfig(require_all=True)
        result = calculate_significance(transcript, config)
        # With require_all=True, needs ALL thresholds
        assert result.is_significant is False

    def test_require_all_all_met(self):
        """require_all=True passes when all thresholds met."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="A" * 20000)],
            tool_calls=[
                ToolCall(name="Write", input={"file_path": f"/file{i}.py"})
                for i in range(3)
            ],
            start_time=None,
            end_time=None,
        )
        config = SignificanceConfig(require_all=True)
        result = calculate_significance(transcript, config)
        assert result.is_significant is True

    def test_custom_config(self):
        """Custom config thresholds are respected."""
        transcript = self._make_transcript(
            token_chars=400,  # 100 tokens
            files_edited=0,
            tool_calls=0,
        )
        config = SignificanceConfig(min_tokens=50)  # Lower threshold
        result = calculate_significance(transcript, config)
        assert result.is_significant is True


# =============================================================================
# is_significant Tests
# =============================================================================


class TestIsSignificant:
    """Tests for is_significant helper function."""

    def test_is_significant_true(self):
        """Returns True for significant session."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="A" * 20000)],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        assert is_significant(transcript) is True

    def test_is_significant_false(self):
        """Returns False for non-significant session."""
        transcript = ParsedTranscript(
            session_id="test",
            project_path="/project",
            messages=[Message(role="user", content="Hi")],
            tool_calls=[],
            start_time=None,
            end_time=None,
        )
        assert is_significant(transcript) is False


# =============================================================================
# create_config_from_dict Tests
# =============================================================================


class TestCreateConfigFromDict:
    """Tests for create_config_from_dict function."""

    def test_create_with_all_values(self):
        """Creates config with all values from dict."""
        config = create_config_from_dict({
            "min_tokens": 1000,
            "min_file_edits": 5,
            "min_tool_calls": 10,
            "require_all": True,
        })
        assert config.min_tokens == 1000
        assert config.min_file_edits == 5
        assert config.min_tool_calls == 10
        assert config.require_all is True

    def test_create_with_partial_values(self):
        """Missing values use defaults."""
        config = create_config_from_dict({"min_tokens": 1000})
        assert config.min_tokens == 1000
        assert config.min_file_edits == DEFAULT_CONFIG.min_file_edits
        assert config.min_tool_calls == DEFAULT_CONFIG.min_tool_calls

    def test_create_with_empty_dict(self):
        """Empty dict uses all defaults."""
        config = create_config_from_dict({})
        assert config.min_tokens == DEFAULT_CONFIG.min_tokens
        assert config.min_file_edits == DEFAULT_CONFIG.min_file_edits


# =============================================================================
# QueueProcessor Tests
# =============================================================================


class TestQueueProcessor:
    """Tests for QueueProcessor class."""

    def test_start_stop(self):
        """Processor starts and stops cleanly."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        processor = QueueProcessor()
        processor.start()
        assert processor._running is True
        assert processor._thread is not None
        processor.stop()
        assert processor._running is False

    def test_start_idempotent(self):
        """Starting twice doesn't create duplicate threads."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        processor = QueueProcessor()
        processor.start()
        thread1 = processor._thread
        processor.start()  # Second start should be no-op
        assert processor._thread is thread1
        processor.stop()

    def test_trigger_processing(self):
        """trigger_processing sets the event."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        processor = QueueProcessor()
        processor.start()
        assert not processor._process_event.is_set()
        processor.trigger_processing()
        # Event should be set (briefly, until consumed)
        processor.stop()

    @patch("src.tools.autocapture.queue_processor.QUEUE_FILE")
    def test_process_queue_empty(self, mock_queue_file):
        """Empty queue doesn't cause errors."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        mock_queue_file.exists.return_value = False

        processor = QueueProcessor()
        processor._process_queue()  # Should not raise

    @patch("src.tools.autocapture.queue_processor.QUEUE_FILE")
    def test_process_queue_with_items(self, mock_queue_file):
        """Queue items are processed."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        # Create a temp file with queue data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            queue_data = [
                {
                    "session_id": "test-1",
                    "transcript_text": "Test transcript",
                    "files_edited": ["/a.py"],
                    "repository": "test-repo",
                }
            ]
            json.dump(queue_data, f)
            f.flush()
            temp_path = Path(f.name)

        try:
            mock_queue_file.exists.return_value = True
            mock_queue_file.read_text.return_value = json.dumps(queue_data)
            mock_queue_file.parent = temp_path.parent

            processor = QueueProcessor()

            # Mock _process_session to simulate success
            with patch.object(processor, "_process_session", return_value=True):
                with patch("os.replace"):  # Don't actually replace files
                    processor._process_queue()

        finally:
            if temp_path.exists():
                temp_path.unlink()

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    @patch("src.tools.notes.conclude_session")
    def test_process_session_success(
        self, mock_conclude_session, mock_get_provider, mock_load_config
    ):
        """Session processing succeeds with mocked dependencies."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        # Setup mocks
        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Test summary"
        mock_get_provider.return_value = mock_provider
        mock_conclude_session.return_value = "{}"

        processor = QueueProcessor()
        session = {
            "session_id": "test-1",
            "transcript_text": "User: Hello\nAssistant: Hi",
            "files_edited": ["/a.py"],
            "repository": "test-repo",
        }

        result = processor._process_session(session)

        assert result is True
        mock_provider.summarize_session.assert_called_once()
        mock_conclude_session.assert_called_once()

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    @patch("src.tools.notes.conclude_session")
    def test_process_session_with_initiative(
        self, mock_conclude_session, mock_get_provider, mock_load_config
    ):
        """Session processing passes initiative_id from queue to conclude_session."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        # Setup mocks
        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Test summary"
        mock_get_provider.return_value = mock_provider
        mock_conclude_session.return_value = "{}"

        processor = QueueProcessor()
        session = {
            "session_id": "test-1",
            "transcript_text": "User: Hello\nAssistant: Hi",
            "files_edited": ["/a.py"],
            "repository": "test-repo",
            "initiative_id": "initiative:abc123",  # Initiative captured at session end
        }

        result = processor._process_session(session)

        assert result is True
        mock_conclude_session.assert_called_once()
        # Verify initiative was passed
        call_kwargs = mock_conclude_session.call_args[1]
        assert call_kwargs["initiative"] == "initiative:abc123"

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    @patch("src.tools.notes.conclude_session")
    def test_process_session_without_initiative(
        self, mock_conclude_session, mock_get_provider, mock_load_config
    ):
        """Session processing works when initiative_id is not in queue (legacy sessions)."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        # Setup mocks
        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Test summary"
        mock_get_provider.return_value = mock_provider
        mock_conclude_session.return_value = "{}"

        processor = QueueProcessor()
        session = {
            "session_id": "test-1",
            "transcript_text": "User: Hello\nAssistant: Hi",
            "files_edited": ["/a.py"],
            "repository": "test-repo",
            # No initiative_id - legacy queue entry or no initiative focused
        }

        result = processor._process_session(session)

        assert result is True
        mock_conclude_session.assert_called_once()
        # Verify initiative is None (will trigger fallback to focused initiative)
        call_kwargs = mock_conclude_session.call_args[1]
        assert call_kwargs["initiative"] is None

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    def test_process_session_no_provider(self, mock_get_provider, mock_load_config):
        """Session returns False when no LLM provider available."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        mock_load_config.return_value = {}
        mock_get_provider.side_effect = Exception("No provider")

        processor = QueueProcessor()
        session = {
            "session_id": "test-1",
            "transcript_text": "User: Hello",
            "files_edited": [],
            "repository": "test-repo",
        }

        result = processor._process_session(session)
        assert result is False  # Should fail, stay in queue for retry

    def test_process_session_empty_transcript(self):
        """Empty transcript is considered 'processed' (removed from queue)."""
        from src.tools.autocapture.queue_processor import QueueProcessor

        processor = QueueProcessor()
        session = {
            "session_id": "test-1",
            "transcript_text": "",  # Empty
            "files_edited": [],
            "repository": "test-repo",
        }

        result = processor._process_session(session)
        assert result is True  # Empty transcripts are removed


# =============================================================================
# Module-level Function Tests
# =============================================================================


class TestQueueProcessorModuleFunctions:
    """Tests for module-level queue processor functions."""

    def test_get_processor_singleton(self):
        """get_processor returns same instance."""
        from src.tools.autocapture import queue_processor

        # Reset global state
        queue_processor._processor = None

        p1 = queue_processor.get_processor()
        p2 = queue_processor.get_processor()
        assert p1 is p2

        # Cleanup
        queue_processor._processor = None

    def test_start_stop_processor(self):
        """start_processor and stop_processor work."""
        from src.tools.autocapture import queue_processor

        # Reset global state
        queue_processor._processor = None

        queue_processor.start_processor()
        assert queue_processor._processor is not None
        assert queue_processor._processor._running is True

        queue_processor.stop_processor()
        assert queue_processor._processor._running is False

        # Cleanup
        queue_processor._processor = None

    def test_trigger_processing_no_processor(self):
        """trigger_processing is safe when processor not started."""
        from src.tools.autocapture import queue_processor

        # Reset global state
        queue_processor._processor = None

        # Should not raise
        queue_processor.trigger_processing()


# =============================================================================
# Sync/Async Mode Tests
# =============================================================================


class TestSyncAsyncConfig:
    """Tests for auto_commit_async configuration."""

    def test_default_config_async_true(self):
        """Default config has auto_commit_async=True."""
        from src.configs.yaml_config import DEFAULT_CONFIG_YAML

        assert "auto_commit_async: true" in DEFAULT_CONFIG_YAML

    def test_default_config_sync_timeout(self):
        """Default config has sync_timeout=60."""
        from src.configs.yaml_config import DEFAULT_CONFIG_YAML

        assert "sync_timeout: 60" in DEFAULT_CONFIG_YAML

    def test_configure_cortex_get_status_includes_autocapture(self):
        """configure_cortex(get_status=True) includes autocapture config."""
        from src.tools.configure.admin import configure_cortex

        status = json.loads(configure_cortex(get_status=True))
        assert "autocapture" in status
        assert "config" in status["autocapture"]

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.configs.yaml_config.save_yaml_config")
    @patch("src.configs.yaml_config.create_default_config")
    def test_configure_cortex_autocapture_async_setting(
        self, mock_create, mock_save, mock_load
    ):
        """configure_cortex can set autocapture_async."""
        from src.tools.configure.admin import configure_cortex

        mock_load.return_value = {"autocapture": {"significance": {}}, "llm": {}}
        mock_save.return_value = True

        result = json.loads(configure_cortex(autocapture_async=False))

        assert result["status"] == "configured"
        assert "autocapture_async=False" in result["changes"]


# =============================================================================
# Hook Initiative Capture Tests
# =============================================================================


class TestHookInitiativeCapture:
    """Tests for initiative capture in the session end hook."""

    def test_queue_session_includes_initiative_id(self, temp_dir):
        """Test that queue_session_for_processing includes initiative_id in queue entry."""
        # Import the hook module functions
        import sys
        hook_path = Path(__file__).parent.parent / "hooks"
        sys.path.insert(0, str(hook_path))

        # We need to test the queue structure, so create a temporary queue file
        queue_file = temp_dir / "capture_queue.json"

        # Mock CORTEX_DATA_DIR to use our temp dir
        with patch("hooks.claude_session_end.CORTEX_DATA_DIR", temp_dir):
            from hooks.claude_session_end import queue_session_for_processing

            result = queue_session_for_processing(
                session_id="test-session-123",
                transcript_text="User: Hello\nAssistant: Hi",
                files_edited=["/a.py", "/b.py"],
                repository="test-repo",
                initiative_id="initiative:xyz789",
            )

            assert result is True

            # Verify queue file contents
            queue_data = json.loads(queue_file.read_text())
            assert len(queue_data) == 1
            entry = queue_data[0]
            assert entry["session_id"] == "test-session-123"
            assert entry["repository"] == "test-repo"
            assert entry["initiative_id"] == "initiative:xyz789"
            assert entry["files_edited"] == ["/a.py", "/b.py"]

    def test_queue_session_without_initiative(self, temp_dir):
        """Test that queue works when no initiative is provided."""
        import sys
        hook_path = Path(__file__).parent.parent / "hooks"
        sys.path.insert(0, str(hook_path))

        queue_file = temp_dir / "capture_queue.json"

        with patch("hooks.claude_session_end.CORTEX_DATA_DIR", temp_dir):
            from hooks.claude_session_end import queue_session_for_processing

            result = queue_session_for_processing(
                session_id="test-session-456",
                transcript_text="User: Hello",
                files_edited=[],
                repository="test-repo",
                # No initiative_id
            )

            assert result is True

            queue_data = json.loads(queue_file.read_text())
            assert len(queue_data) == 1
            entry = queue_data[0]
            assert "initiative_id" not in entry  # Should not be present when None

    def test_get_focused_initiative_success(self):
        """Test get_focused_initiative returns initiative from daemon."""
        import sys
        hook_path = Path(__file__).parent.parent / "hooks"
        sys.path.insert(0, str(hook_path))

        from hooks.claude_session_end import get_focused_initiative

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "initiative_id": "initiative:abc123",
            "initiative_name": "Test Initiative",
        }).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = get_focused_initiative("test-repo")

            assert result == "initiative:abc123"

    def test_get_focused_initiative_no_focus(self):
        """Test get_focused_initiative returns None when no initiative focused."""
        import sys
        hook_path = Path(__file__).parent.parent / "hooks"
        sys.path.insert(0, str(hook_path))

        from hooks.claude_session_end import get_focused_initiative

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "initiative_id": None,
            "initiative_name": None,
        }).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = get_focused_initiative("test-repo")

            assert result is None

    def test_get_focused_initiative_daemon_unavailable(self):
        """Test get_focused_initiative returns None when daemon is unavailable."""
        import sys
        import urllib.error
        hook_path = Path(__file__).parent.parent / "hooks"
        sys.path.insert(0, str(hook_path))

        from hooks.claude_session_end import get_focused_initiative

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            result = get_focused_initiative("test-repo")

            assert result is None  # Should gracefully handle failure


class TestProcessSyncEndpoint:
    """Tests for /process-sync API endpoint."""

    def test_process_sync_empty_transcript(self):
        """process_sync skips empty transcripts."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        request = ProcessSyncRequest(
            session_id="test-1",
            transcript_text="",
            files_edited=[],
            repository="test",
        )
        result = process_sync(request)

        assert result["status"] == "skipped"
        assert result["reason"] == "empty transcript"

    def test_process_sync_whitespace_transcript(self):
        """process_sync skips whitespace-only transcripts."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        request = ProcessSyncRequest(
            session_id="test-1",
            transcript_text="   \n\t  ",
            files_edited=[],
            repository="test",
        )
        result = process_sync(request)

        assert result["status"] == "skipped"

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    def test_process_sync_no_provider(self, mock_get_provider, mock_load_config):
        """process_sync returns error when no LLM provider."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        mock_load_config.return_value = {}
        mock_get_provider.return_value = None

        request = ProcessSyncRequest(
            session_id="test-1",
            transcript_text="User: Hello\nAssistant: Hi",
            files_edited=[],
            repository="test",
        )
        result = process_sync(request)

        assert result["status"] == "error"
        assert "No LLM provider" in result["error"]

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    def test_process_sync_success(self, mock_get_provider, mock_load_config):
        """process_sync succeeds with mocked dependencies."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync, save_session_summary

        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Test summary"
        mock_get_provider.return_value = mock_provider

        request = ProcessSyncRequest(
            session_id="test-1",
            transcript_text="User: Hello\nAssistant: Hi there",
            files_edited=["/a.py", "/b.py"],
            repository="test-repo",
        )

        # Mock save_session_summary at module level
        with patch.object(
            __import__("src.controllers.http.api", fromlist=["save_session_summary"]),
            "save_session_summary",
            return_value={"status": "success", "session_id": "test-session"},
        ) as mock_save:
            result = process_sync(request)

            assert result["status"] == "success"
            assert result["session_id"] == "test-1"
            assert result["summary_length"] == len("Test summary")
            mock_provider.summarize_session.assert_called_once()
            mock_save.assert_called_once()

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    def test_process_sync_summarization_error(
        self, mock_get_provider, mock_load_config
    ):
        """process_sync returns error when summarization fails."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.side_effect = Exception("LLM error")
        mock_get_provider.return_value = mock_provider

        request = ProcessSyncRequest(
            session_id="test-1",
            transcript_text="User: Hello",
            files_edited=[],
            repository="test",
        )
        result = process_sync(request)

        assert result["status"] == "error"
        assert "Summarization failed" in result["error"]
