"""LumaFeed 商户口碑风险查询工具。"""

import json

from langchain_core.tools import tool

from app.services.lumafeed import lumafeed_service


@tool
async def query_merchant_risk(limit: int = 5) -> str:
    """查询评分较低、评论量较高的商户，用于生成人工回访名单。

    Args:
        limit: 返回商户数量，服务端会限制到 1～20。
    """
    data = await lumafeed_service.query_merchant_metrics(limit)
    return json.dumps(data, ensure_ascii=False)
