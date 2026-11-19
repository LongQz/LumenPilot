"""Tests for automatic LangGraph diagram export."""

from pathlib import Path

from langgraph.graph import StateGraph

from app.core.langgraph.graph import export_graph_diagram


def test_export_graph_diagram_without_png(tmp_path: Path) -> None:
    """A compiled graph should produce Mermaid and Markdown artifacts."""
    builder = StateGraph(dict)
    builder.add_node("chat", lambda state: state)
    builder.set_entry_point("chat")
    compiled = builder.compile()

    paths = export_graph_diagram(
        compiled,
        output_dir=tmp_path,
        render_png=False,
        filename="test-agent",
    )

    assert paths is not None
    assert Path(paths["mermaid"]).read_text(encoding="utf-8").startswith("---")
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "```mermaid" in markdown
    assert "ASCII fallback" in markdown
    assert "png" not in paths
