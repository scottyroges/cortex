"""
Detail Panel Widget

Displays full document content and metadata.
"""

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Markdown, Static

from src.browser.formatting import format_content, format_files, format_metadata
from src.browser.models import Document


class DetailPanel(Widget):
    """
    Panel displaying full document details.

    Shows:
    - Document metadata (title, type, repository, etc.)
    - Full content with proper formatting
    - Type-specific information (linked files for insights, etc.)
    """

    DEFAULT_CSS = """
    DetailPanel {
        width: 100%;
        height: 100%;
        border: solid $primary;
    }

    DetailPanel .detail-header {
        height: auto;
        padding: 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    DetailPanel .detail-title {
        text-style: bold;
        color: $text;
    }

    DetailPanel .detail-meta {
        color: $text-muted;
        margin-top: 1;
    }

    DetailPanel .detail-meta-row {
        height: 1;
    }

    DetailPanel .detail-warning {
        background: $warning;
        color: $text;
        padding: 1;
        margin-top: 1;
    }

    DetailPanel .detail-content {
        padding: 1;
    }

    DetailPanel .detail-files {
        margin-top: 1;
        padding: 1;
        background: $surface;
    }

    DetailPanel .detail-files-title {
        text-style: bold;
        color: $text-muted;
    }

    DetailPanel .detail-loading {
        padding: 2;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }

    DetailPanel .detail-empty {
        padding: 2;
        text-align: center;
        color: $text-muted;
    }
    """

    document: reactive[Document | None] = reactive(None)
    is_loading: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Vertical():
            yield Vertical(id="detail-header", classes="detail-header")
            yield VerticalScroll(
                Static("Select a document to view details", classes="detail-empty"),
                id="detail-body",
            )

    def watch_document(self, document: Document | None) -> None:
        """React to document changes."""
        if document is not None:
            self._render_document(document)

    def watch_is_loading(self, is_loading: bool) -> None:
        """React to loading state changes."""
        if is_loading:
            self._show_loading()

    def _render_document(self, doc: Document) -> None:
        """Render the document details."""
        # Update header
        header = self.query_one("#detail-header", Vertical)
        header.remove_children()

        # Title
        title = doc.title or doc.id
        header.mount(Static(f"[bold]{title}[/bold]", classes="detail-title"))

        # Metadata
        meta_formatted = format_metadata(doc.metadata, doc.doc_type)
        meta_lines = []
        for key, value in meta_formatted.items():
            meta_lines.append(f"[dim]{key}:[/dim] {value}")

        if meta_lines:
            header.mount(Static("\n".join(meta_lines), classes="detail-meta"))

        # Staleness warning for insights
        if doc.doc_type == "insight":
            validation = doc.metadata.get("last_validation_result")
            if validation == "no_longer_valid":
                header.mount(Static(
                    "[bold]Warning:[/bold] This insight may be outdated. "
                    "Linked files have changed since last validation.",
                    classes="detail-warning"
                ))
            elif validation == "partially_valid":
                header.mount(Static(
                    "[bold]Note:[/bold] This insight may need review. "
                    "Some linked files have changed.",
                    classes="detail-warning"
                ))

        # Update body
        body = self.query_one("#detail-body", VerticalScroll)
        body.remove_children()

        # Content
        content = format_content(doc.content)
        # Use Markdown for notes and insights, Static for others
        if doc.doc_type in ("note", "insight", "commit"):
            body.mount(Markdown(content, classes="detail-content"))
        else:
            body.mount(Static(content, classes="detail-content"))

        # Linked files for insights
        if doc.doc_type == "insight":
            files = format_files(doc.metadata.get("files"))
            if files:
                files_content = "[dim]Linked Files:[/dim]\n" + "\n".join(f"  - {f}" for f in files)
                body.mount(Static(files_content, classes="detail-files"))

        # Changed files for commits
        if doc.doc_type == "commit":
            files = format_files(doc.metadata.get("files"))
            if files:
                files_content = "[dim]Changed Files:[/dim]\n" + "\n".join(f"  - {f}" for f in files)
                body.mount(Static(files_content, classes="detail-files"))

    def _show_loading(self) -> None:
        """Show loading state."""
        body = self.query_one("#detail-body", VerticalScroll)
        body.remove_children()
        body.mount(Static("Loading...", classes="detail-loading"))

    def _show_empty(self) -> None:
        """Show empty state."""
        header = self.query_one("#detail-header", Vertical)
        header.remove_children()

        body = self.query_one("#detail-body", VerticalScroll)
        body.remove_children()
        body.mount(Static("Select a document to view details", classes="detail-empty"))

    def set_document(self, document: Document) -> None:
        """Update with a document."""
        self.is_loading = False
        self.document = document

    def set_is_loading(self) -> None:
        """Set loading state."""
        self.is_loading = True

    def set_error(self, message: str) -> None:
        """Set error state."""
        self.is_loading = False
        body = self.query_one("#detail-body", VerticalScroll)
        body.remove_children()
        body.mount(Static(f"[red]Error: {message}[/red]", classes="detail-empty"))

    def clear(self) -> None:
        """Clear the detail view."""
        self.document = None
        self._show_empty()
