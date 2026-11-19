"""LangGraph 人工介入工具。

该工具只负责暂停图执行并返回人工答复，本身不执行业务写操作。敏感动作应像
``create_ops_task_draft`` 一样，在恢复执行后继续校验用户是否明确确认。
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_human(question: str) -> str:
    """暂停当前图执行，等待用户补充信息或作出确认。

    模型在缺少关键信息时调用此工具。创建运营任务的审批由
    ``create_ops_task_draft`` 自身处理，不要先调用本工具。
    ``interrupt`` 会触发 checkpoint，用户下一次发送的消息将作为恢复值返回。

    Args:
        question: 展示给用户的澄清或确认问题。

    Returns:
        用户恢复该次中断时提交的文本。
    """
    user_response = interrupt(question)
    return str(user_response)
