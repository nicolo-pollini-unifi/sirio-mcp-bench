"""
This module defines custom exceptions for the agent execution loop and benchmarking errors.
"""

class AgentLoopError(Exception):
    """
    Base exception for all agentic loop execution failures.
    """
    pass

class SemanticLoopError(AgentLoopError):
    """
    Raised when the agent repeats almost identical reasoning or tool calls without making progress.
    """
    pass

class MaxTurnsExceededError(AgentLoopError):
    """
    Raised when the agent exceeds the maximum allowed turn budget without yielding a valid output.
    """
    pass

class ToolCallBudgetExceededError(AgentLoopError):
    """
    Raised when the total number of tool calls exceeds the configured budget.
    """
    pass

class NetworkError(AgentLoopError):
    """
    Raised when a connection error or timeout occurs while communicating with the LLM API.
    """
    pass
