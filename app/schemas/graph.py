"""This file contains the graph schema for the application."""

from langgraph.graph import MessagesState


class GraphState(MessagesState):
    """State definition for the LangGraph Agent/Workflow."""

    long_term_memory: str = ""
    safe_user_input: str = ""
    safety_blocked: bool = False
    reflection_count: int = 0
    reflection_feedback: str = ""
    reflection_status: str = "not_run"
    reflection_reason: str = ""
