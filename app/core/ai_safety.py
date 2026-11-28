"""Deterministic safety and response-quality controls for LumenPilot."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from app.core.logging import logger


ALLOWED_TOOLS = {
    "query_platform_metrics",
    "query_merchant_risk",
    "search_ops_knowledge",
    "create_ops_task_draft",
    "ask_human",
}

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|前面).{0,8}(指令|规则)"),
    re.compile(r"(system|developer)\s*prompt", re.IGNORECASE),
    re.compile(r"(泄露|打印|输出).{0,8}(系统提示|密钥|api[_\s-]?key|token)", re.IGNORECASE),
    re.compile(r"(执行|运行).{0,8}(shell|命令|sql)", re.IGNORECASE),
    re.compile(r"(drop|delete)\s+(table|database)", re.IGNORECASE),
    re.compile(r"绕过.{0,8}(登录|权限|确认|审计)"),
    re.compile(r"jailbreak|越狱模式", re.IGNORECASE),
)

_CREATE_INTENT = re.compile(r"(创建|发起|安排|新建).{0,12}(任务|回访|跟进)")
_CREATE_NEGATION = re.compile(r"(不要|禁止|无需|不用|别).{0,8}(创建|发起|安排|新建)")
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9._-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SafetyDecision:
    """Result of a safety inspection."""

    allowed: bool
    category: str
    reason: str
    sanitized_text: str


def redact_sensitive(text: str) -> str:
    """Mask common personal and credential values before logs or model input."""
    redacted = _PHONE_PATTERN.sub("[PHONE]", text)
    redacted = _EMAIL_PATTERN.sub("[EMAIL]", redacted)
    return _SECRET_PATTERN.sub("[SECRET]", redacted)


def inspect_user_input(text: str) -> SafetyDecision:
    """Block prompt injection and normalise sensitive values."""
    normalized = " ".join((text or "").split())
    if not normalized:
        return SafetyDecision(False, "empty_input", "输入为空", "")
    if len(normalized) > 3000:
        return SafetyDecision(False, "oversized_input", "输入超过 3000 字符", "")
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            return SafetyDecision(
                False,
                "prompt_injection",
                "检测到试图绕过系统规则、权限或工具边界的指令",
                "",
            )
    return SafetyDecision(True, "allowed", "", redact_sensitive(normalized))


def current_turn_messages(messages: Iterable[BaseMessage]) -> list[BaseMessage]:
    """Return messages belonging to the latest user turn."""
    ordered = list(messages)
    for index in range(len(ordered) - 1, -1, -1):
        if isinstance(ordered[index], HumanMessage):
            return ordered[index:]
    return ordered


def latest_user_text(messages: Iterable[BaseMessage]) -> str:
    """Return the latest human message content."""
    for message in reversed(list(messages)):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def validate_tool_calls(tool_calls: list[dict], user_text: str) -> tuple[bool, str]:
    """Validate model-selected tools before ToolNode executes them."""
    if not tool_calls:
        return True, ""
    if len(tool_calls) > 6:
        return False, "单轮工具调用数量超过安全上限"

    normalized_user_text = " ".join(user_text.split())
    explicit_create = bool(_CREATE_INTENT.search(normalized_user_text))
    create_negated = bool(_CREATE_NEGATION.search(normalized_user_text))

    for tool_call in tool_calls:
        name = str(tool_call.get("name", ""))
        if name not in ALLOWED_TOOLS:
            return False, f"工具 {name or '<unknown>'} 不在允许列表中"
        if name == "create_ops_task_draft" and (create_negated or not explicit_create):
            return False, "用户没有明确提出创建、发起或安排运营任务的写操作意图"
    return True, ""


def response_quality_issues(messages: list[BaseMessage], user_text: str) -> list[str]:
    """Perform a deterministic Reflection pass over the latest model answer."""
    turn = current_turn_messages(messages)
    ai_messages = [message for message in turn if isinstance(message, AIMessage)]
    if not ai_messages:
        return ["没有生成可展示的助手回答"]

    answer = str(ai_messages[-1].content or "").strip()
    issues: list[str] = []
    if len(answer) < 20:
        issues.append("回答过短，未形成可执行结论")

    if _CREATE_NEGATION.search(user_text) and ("create_ops_task" in answer or "任务已成功创建" in answer):
        issues.append("用户明确禁止创建任务，但回答表现为已创建任务")

    tool_names = {message.name for message in turn if isinstance(message, ToolMessage) and message.name}
    asks_for_data = any(keyword in user_text for keyword in ("查询", "数据", "指标", "趋势", "笔记", "互动", "商户"))
    if asks_for_data and not tool_names:
        issues.append("涉及平台数据，但没有成功调用查询工具")

    if "search_ops_knowledge" in tool_names and not re.search(r"\[[\w-]+#\d+]", answer):
        issues.append("使用知识库检索后，回答缺少可核验的来源引用")

    if any(pattern.search(answer) for pattern in _INJECTION_PATTERNS):
        issues.append("回答包含可能暴露系统规则或越权执行的内容")
    return issues


def audit_event(
    event: str,
    *,
    session_id: str | None,
    user_text: str,
    category: str,
    reason: str = "",
) -> None:
    """Write a privacy-preserving safety audit event."""
    digest = hashlib.sha256(redact_sensitive(user_text).encode("utf-8")).hexdigest()[:16]
    logger.info(
        "ai_safety_audit",
        action=event,
        session_id=session_id,
        input_hash=digest,
        category=category,
        reason=reason,
    )
