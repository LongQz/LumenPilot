"""This file contains the graph schema for the application."""

from langgraph.graph import MessagesState


class GraphState(MessagesState):
    """State definition for the LangGraph Agent/Workflow."""

    long_term_memory: str = ""
