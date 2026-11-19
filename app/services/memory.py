"""基于 mem0 与 pgvector 的长期记忆服务。

短期对话由 LangGraph checkpoint 保存，长期偏好和事实由 mem0 提取后写入
pgvector。缓存只用于加速重复检索，不替代持久化记忆。
"""

from langchain_core.messages import BaseMessage
from mem0 import AsyncMemory

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.logging import logger
from app.core.prompts import load_memory_capture_prompt
from app.utils import latest_user_text


class MemoryService:
    """管理用户级长期记忆的读写、缓存和懒初始化。"""

    def __init__(self):
        """Initialize the memory service."""
        self._memory: AsyncMemory | None = None

    async def _get_memory(self) -> AsyncMemory:
        """按需初始化 mem0，避免应用启动时重复建立连接资源。"""
        if self._memory is None:
            # 向量库、事实抽取模型和 Embedding 模型分别配置；三者失败不会
            # 影响普通聊天，但当前轮不会有长期记忆增强。
            self._memory = await AsyncMemory.from_config(
                config_dict={
                    "vector_store": {
                        "provider": "pgvector",
                        "config": {
                            "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                            "dbname": settings.POSTGRES_DB,
                            "user": settings.POSTGRES_USER,
                            "password": settings.POSTGRES_PASSWORD,
                            "host": settings.POSTGRES_HOST,
                            "port": settings.POSTGRES_PORT,
                        },
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": settings.LONG_TERM_MEMORY_MODEL,
                            "api_key": settings.OPENAI_API_KEY,
                            "openai_base_url": settings.OPENAI_BASE_URL or None,
                        },
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": settings.LONG_TERM_MEMORY_EMBEDDER_MODEL,
                            "api_key": settings.OPENAI_API_KEY,
                            "openai_base_url": settings.OPENAI_BASE_URL or None,
                            "embedding_dims": settings.LONG_TERM_MEMORY_EMBEDDING_DIMS,
                        },
                    },
                    "custom_fact_extraction_prompt": load_memory_capture_prompt(),
                }
            )
        return self._memory

    async def initialize(self) -> None:
        """应用启动时预热 mem0 和 pgvector 连接池，降低首轮检索延迟。"""
        await self._get_memory()
        logger.info("memory_service_initialized")

    async def search(self, user_id: str | None, query: str) -> str:
        """检索与当前问题相关的用户长期记忆。

        匿名会话不读取长期记忆，防止多个访客落到同一记忆分区。检索失败时返回
        空字符串，让主对话继续执行，而不是把记忆服务故障扩散成聊天故障。
        """
        if user_id is None:
            return ""
        try:
            # Check cache first
            key = cache_key("memory", str(user_id), query)
            cached = await cache_service.get(key)
            if cached is not None:
                logger.debug("memory_search_cache_hit", user_id=user_id)
                return cached

            memory = await self._get_memory()
            results = await memory.search(user_id=str(user_id), query=query)
            result = "\n".join([f"* {r['memory']}" for r in results["results"]])

            # Cache successful results
            if result:
                await cache_service.set(key, result)

            return result
        except Exception as e:
            logger.error("failed_to_get_relevant_memory", error=str(e), user_id=user_id, query=query)
            return ""

    async def add(self, user_id: str | None, messages: list[BaseMessage]) -> None:
        """把最近一条用户消息交给 mem0 抽取长期记忆。

        仅提交用户原话，不提交助手回复。否则助手给出的建议可能被误写成用户偏好，
        导致后续分析持续引用错误事实。
        """
        if user_id is None:
            return
        user_text = latest_user_text(messages).strip()
        if not user_text:
            logger.debug("long_term_memory_skipped_empty_turn", user_id=user_id)
            return

        try:
            memory = await self._get_memory()
            await memory.add(
                [{"role": "user", "content": user_text}],
                user_id=str(user_id),
            )
            logger.info("long_term_memory_updated_successfully", user_id=user_id)
        except Exception as e:
            logger.exception("failed_to_update_long_term_memory", user_id=user_id, error=str(e))


memory_service = MemoryService()
