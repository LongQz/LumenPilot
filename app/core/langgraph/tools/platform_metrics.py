"""LumaFeed 内容与互动指标工具。

当模型需要判断内容增长、互动下降或热门笔记变化时，应首先调用本工具。
工具返回的是 Java 平台计算后的稳定指标，不由模型自行编造。
"""

import json

from langchain_core.tools import tool

from app.services.lumafeed import lumafeed_service


@tool
async def query_platform_metrics(days: int = 7) -> str:
    """查询 LumaFeed 内容、互动、热门笔记和商户口碑风险。

    调用前不需要人工确认，因为这里只执行只读查询。返回 JSON 会包含精确的
    起止时间，模型引用指标时必须带上这个时间范围。

    Args:
        days: 回看天数，服务端会限制到 1～90 天。
    """
    data = await lumafeed_service.query_overview(days)
    return json.dumps(data, ensure_ascii=False)
