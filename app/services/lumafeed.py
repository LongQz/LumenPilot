"""LumaFeed 运营接口客户端。

Agent 不直接连接 LumaFeed 的 MySQL。所有业务数据都由受控 HTTP 接口返回，
从而让用户身份、数据范围和接口权限继续由 Java 平台负责。
"""

from typing import Any

import httpx

from app.core.config import settings


class LumaFeedService:
    """通过服务令牌调用 LumaFeed 的只读接口和人工确认后的写接口。"""

    def __init__(self) -> None:
        """Load the LumaFeed endpoint and service token from environment config."""
        self._base_url = settings.LUMAFEED_API_BASE_URL.rstrip("/")
        self._headers = {"X-LumaFeed-Agent-Token": settings.LUMAFEED_AGENT_TOKEN}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """发送请求并统一校验 LumaFeed 的 success 响应结构。"""
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=settings.LUMAFEED_REQUEST_TIMEOUT,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(payload.get("errorMsg") or "LumaFeed request failed")
            return payload.get("data")

    async def query_overview(self, days: int = 7) -> dict[str, Any]:
        """查询指定天数内的内容互动、用户和商户口碑聚合数据。"""
        safe_days = max(1, min(days, 90))
        return await self._request("GET", "/admin/analytics/overview", params={"days": safe_days})

    async def query_merchant_metrics(self, limit: int = 5) -> list[dict[str, Any]]:
        """查询评分较低、评论量较高的商户，用于人工口碑排查。"""
        safe_limit = max(1, min(limit, 20))
        return await self._request("GET", "/admin/analytics/merchants", params={"limit": safe_limit})

    async def create_ops_task(self, title: str, description: str, priority: str = "MEDIUM") -> dict[str, Any]:
        """写入运营任务；调用前必须已经经过 LangGraph 人工确认。"""
        return await self._request(
            "POST",
            "/admin/ops/tasks",
            json={
                "title": title,
                "description": description,
                "priority": priority.upper(),
            },
        )

    async def list_ops_tasks(self) -> list[dict[str, Any]]:
        """查询最近创建的运营任务，供管理端核对人工确认结果。"""
        return await self._request("GET", "/admin/ops/tasks")


lumafeed_service = LumaFeedService()
