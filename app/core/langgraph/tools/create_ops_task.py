"""人工确认后的 LumaFeed 运营任务创建工具。

写操作不能由模型直接执行。工具会先调用 LangGraph interrupt 暂停图，
等用户明确回复“确认”后再请求 Java 任务接口。
"""

import json
import re

from langchain_core.tools import tool
from langgraph.types import interrupt

from app.services.lumafeed import lumafeed_service

_CONFIRMATIONS = {
    "确认",
    "确认创建",
    "确认创建任务",
    "创建",
    "创建任务",
    "同意",
    "同意创建",
    "同意创建任务",
    "是",
    "是的",
    "可以",
    "可以创建",
    "批准",
    "yes",
    "y",
    "create",
    "approve",
}
_NEGATIONS = ("取消", "不要", "不创建", "不确认", "别创建", "拒绝", "no", "cancel")


def _is_confirmed(value: object) -> bool:
    """识别明确确认，并优先排除否定或取消语句。"""
    normalized = re.sub(r"[\s，。！？,.!?]+", "", str(value).strip().lower())
    if not normalized or any(negation in normalized for negation in _NEGATIONS):
        return False
    return normalized in _CONFIRMATIONS


@tool
async def create_ops_task_draft(title: str, description: str, priority: str = "MEDIUM") -> str:
    """创建运营任务草稿并等待人工确认。

    interrupt 会把当前图状态写入 PostgreSQL checkpoint。用户下一次发送
    “确认”时，Agent 从暂停位置继续，而不是重新创建另一条任务。

    Args:
        title: 简明任务标题。
        description: 可执行的行动说明和验收目标。
        priority: LOW、MEDIUM 或 HIGH。
    """
    normalized_priority = priority.upper()
    if normalized_priority not in {"LOW", "MEDIUM", "HIGH"}:
        normalized_priority = "MEDIUM"

    confirmation = interrupt(
        {
            "action": "create_ops_task",
            "title": title,
            "description": description,
            "priority": normalized_priority,
            "question": "确认在 LumaFeed 创建这条运营任务吗？",
        }
    )
    # 只有明确确认才写入，模糊回复一律视为取消，避免误建任务。
    if not _is_confirmed(confirmation):
        return json.dumps({"created": False, "reason": "operator_cancelled"}, ensure_ascii=False)

    task = await lumafeed_service.create_ops_task(title, description, normalized_priority)
    return json.dumps({"created": True, "task": task}, ensure_ascii=False)
