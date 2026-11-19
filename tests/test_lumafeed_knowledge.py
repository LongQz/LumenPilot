"""Tests for the local LumaFeed operations knowledge retrieval."""

from app.services.knowledge import knowledge_service
from app.core.langgraph.tools.create_ops_task import _is_confirmed


def test_search_returns_source_grounded_merchant_guidance() -> None:
    """Merchant guidance should include a source and relevant content."""
    results = knowledge_service.search("商户口碑风险应该怎么处理", limit=3)

    assert results
    assert all(result["source"] for result in results)
    assert any("商户" in result["content"] for result in results)


def test_search_returns_empty_for_empty_query() -> None:
    """An empty query should not inject arbitrary knowledge chunks."""
    assert knowledge_service.search("") == []


def test_documents_have_stable_citation_ids() -> None:
    """Every chunk should have a deterministic vector ID and traceable source."""
    documents = knowledge_service._documents()

    assert documents
    assert all(len(document["id"]) == 64 for document in documents)
    assert all("#" in document["source"] for document in documents)


def test_natural_confirmation_and_negation() -> None:
    """Natural confirmations succeed while cancellation phrases remain rejected."""
    assert _is_confirmed("确认创建")
    assert _is_confirmed("同意，创建任务")
    assert not _is_confirmed("取消，不要创建")
    assert not _is_confirmed("不确认")
