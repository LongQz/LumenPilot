"""注册给 LumaFeed 运营分析 Agent 的工具集合。

工具列表同时决定模型的调用边界，因此这里只暴露运营分析和人工确认所需的能力，
不开放数据库、Shell、联网搜索等通用执行权限。
"""

from langchain_core.tools.base import BaseTool

from .ask_human import ask_human
from .create_ops_task import create_ops_task_draft
from .merchant_reputation import query_merchant_risk
from .ops_knowledge import search_ops_knowledge
from .platform_metrics import query_platform_metrics

tools: list[BaseTool] = [
    # 前三个工具只读取 LumaFeed 聚合数据和本地运营知识。
    query_platform_metrics,
    query_merchant_risk,
    search_ops_knowledge,
    # 写操作必须经过 interrupt 人工确认，避免模型直接修改运营任务。
    create_ops_task_draft,
    ask_human,
]
