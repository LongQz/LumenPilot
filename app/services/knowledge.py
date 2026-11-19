"""LumaFeed 运营知识 RAG。

运营手册写入独立的 pgvector 表，查询时先做 Embedding 相似度检索；数据库或
百炼不可用时自动退回确定性的词法检索，保证 Agent 仍可工作。两种结果都带
稳定来源编号，避免模型生成无法核验的引用。
"""

import hashlib
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import psycopg
from langchain_openai import OpenAIEmbeddings
from psycopg.rows import dict_row

from app.core.config import settings
from app.core.logging import logger


class OperationsKnowledgeService:
    """管理运营知识的向量索引、相似度检索和词法降级。"""

    def __init__(self) -> None:
        """解析知识目录并初始化懒加载状态。"""
        self._root = Path(__file__).resolve().parents[2] / "knowledge"
        self._embedding: OpenAIEmbeddings | None = None
        self._vector_ready = False
        self._index_lock = threading.Lock()

    def _terms(self, text: str) -> set[str]:
        """生成中英文词项，供数据库不可用时进行词法检索。"""
        lowered = text.lower()
        terms = set(re.findall(r"[a-z0-9_]{2,}", lowered))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        terms.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
        return terms

    def _chunks(self, path: Path) -> list[str]:
        """按二级标题切分 Markdown，保证标题和正文处于同一片段。"""
        text = path.read_text(encoding="utf-8")
        sections = [section.strip() for section in re.split(r"(?m)(?=^## )", text)]
        chunks: list[str] = []
        for section in sections:
            if not section:
                continue
            if len(section) <= 900:
                chunks.append(section)
                continue
            heading = section.splitlines()[0] if section.startswith("## ") else ""
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section) if part.strip()]
            for paragraph in paragraphs:
                chunk = f"{heading}\n{paragraph}".strip() if heading and not paragraph.startswith("## ") else paragraph
                chunks.append(chunk[:900])
        return chunks

    def _documents(self) -> list[dict[str, str]]:
        """构建带稳定来源和内容哈希的知识片段。"""
        documents: list[dict[str, str]] = []
        for path in sorted(self._root.glob("*.md")):
            for index, chunk in enumerate(self._chunks(path)):
                source = f"{path.stem}#{index + 1}"
                documents.append(
                    {
                        "id": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        "source": source,
                        "title": path.stem,
                        "content": chunk,
                        "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    }
                )
        return documents

    def _get_embedding(self) -> OpenAIEmbeddings | None:
        """懒加载百炼 Embedding；未配置 API Key 时返回 None。"""
        if not settings.OPENAI_API_KEY:
            return None
        if self._embedding is None:
            self._embedding = OpenAIEmbeddings(
                model=settings.KNOWLEDGE_RAG_EMBEDDING_MODEL,
                dimensions=settings.KNOWLEDGE_RAG_EMBEDDING_DIMS,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL or None,
                chunk_size=10,
                # 百炼兼容接口要求 input 为字符串，不能使用 OpenAI 的 token ID 预处理。
                check_embedding_ctx_length=False,
            )
        return self._embedding

    def _connection(self) -> psycopg.Connection:
        """创建运营知识向量库连接。"""
        conninfo = (
            "postgresql://"
            f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )
        return psycopg.connect(
            conninfo,
            autocommit=True,
            connect_timeout=5,
            row_factory=dict_row,
        )

    def _ensure_vector_store(self) -> None:
        """创建向量表并幂等更新知识片段。"""
        if self._vector_ready:
            return
        embedding = self._get_embedding()
        if embedding is None:
            raise RuntimeError("Embedding API key is not configured")

        documents = self._documents()
        if not documents:
            raise RuntimeError("No operations knowledge documents found")

        with self._index_lock:
            if self._vector_ready:
                return
            table = settings.KNOWLEDGE_RAG_TABLE
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                raise RuntimeError("Invalid knowledge RAG table name")
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            id TEXT PRIMARY KEY,
                            source TEXT NOT NULL,
                            title TEXT NOT NULL,
                            content TEXT NOT NULL,
                            content_hash TEXT NOT NULL,
                            embedding vector({settings.KNOWLEDGE_RAG_EMBEDDING_DIMS}) NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                    cursor.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw
                        ON {table} USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                    cursor.execute(f"SELECT id, content_hash FROM {table}")
                    existing = {row["id"]: row["content_hash"] for row in cursor.fetchall()}
                    changed = [
                        document
                        for document in documents
                        if existing.get(document["id"]) != document["content_hash"]
                    ]
                    vectors = embedding.embed_documents(
                        [document["content"] for document in changed]
                    ) if changed else []
                    for document, vector in zip(changed, vectors, strict=True):
                        cursor.execute(
                            f"""
                            INSERT INTO {table}
                                (id, source, title, content, content_hash, embedding, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s::vector, now())
                            ON CONFLICT (id) DO UPDATE SET
                                source = EXCLUDED.source,
                                title = EXCLUDED.title,
                                content = EXCLUDED.content,
                                content_hash = EXCLUDED.content_hash,
                                embedding = EXCLUDED.embedding,
                                updated_at = now()
                            """,
                            (
                                document["id"],
                                document["source"],
                                document["title"],
                                document["content"],
                                document["content_hash"],
                                self._vector_literal(vector),
                            ),
                        )
                    cursor.execute(
                        f"DELETE FROM {table} WHERE NOT (id = ANY(%s))",
                        ([document["id"] for document in documents],),
                    )
            self._vector_ready = True
            logger.info("operations_knowledge_vector_ready", documents=len(documents), table=table)

    def _vector_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """执行 cosine 相似度检索并返回带来源的结果。"""
        self._ensure_vector_store()
        embedding = self._get_embedding()
        if embedding is None:
            return []
        query_vector = self._vector_literal(embedding.embed_query(query))
        table = settings.KNOWLEDGE_RAG_TABLE
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise RuntimeError("Invalid knowledge RAG table name")
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT source, title, content,
                           ROUND((1 - (embedding <=> %s::vector))::numeric, 4) AS score
                    FROM {table}
                    WHERE 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_vector,
                        query_vector,
                        settings.KNOWLEDGE_RAG_MIN_SCORE,
                        query_vector,
                        limit,
                    ),
                )
                rows = cursor.fetchall()
        return [
            {
                "source": row["source"],
                "title": row["title"],
                "score": float(row["score"]),
                "content": row["content"],
                "retrieval": "pgvector",
            }
            for row in rows
        ]

    def _lexical_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """数据库不可用时的确定性检索，保留相同来源格式。"""
        query_terms = self._terms(query)
        if not query_terms or not self._root.exists():
            return []

        candidates: list[dict[str, Any]] = []
        for document in self._documents():
            chunk_terms = self._terms(document["content"])
            overlap = query_terms & chunk_terms
            if not overlap:
                continue
            score = len(overlap) / max(1, len(query_terms))
            candidates.append(
                {
                    "source": document["source"],
                    "title": document["title"],
                    "score": round(score, 4),
                    "content": document["content"],
                    "retrieval": "lexical",
                }
            )
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """优先使用 pgvector，失败时降级到词法检索。"""
        safe_limit = max(1, min(limit, 5))
        if not query.strip() or not self._root.exists():
            return []
        if settings.KNOWLEDGE_RAG_ENABLED:
            try:
                results = self._vector_search(query, safe_limit)
                if results:
                    return results
            except Exception as exception:
                logger.warning(
                    "operations_knowledge_vector_search_failed",
                    error=str(exception),
                    query=query,
                )
        return self._lexical_search(query, safe_limit)

    def reindex(self) -> int:
        """强制重建知识向量，供知识文档更新后的维护脚本调用。"""
        self._vector_ready = False
        self._ensure_vector_store()
        return len(self._documents())

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        """把向量转换成 pgvector 接受的文本格式。"""
        return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


knowledge_service = OperationsKnowledgeService()
