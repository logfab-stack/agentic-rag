"""
API package for Agentic RAG System.
"""

from .documents import router as documents_router
from .conversations import router as conversations_router
from .chat import router as chat_router

__all__ = ["documents_router", "conversations_router", "chat_router"]
# Force reload mar  3 feb 2026 20:37:44 CET
