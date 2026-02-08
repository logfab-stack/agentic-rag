"""
Security API endpoints for the Agentic RAG System.

Feature #319: Enhanced prompt injection protection - Admin endpoints for
monitoring security events and managing blocked users.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

from services.security_service import get_security_service, get_security_log, get_security_stats

router = APIRouter()
logger = logging.getLogger(__name__)


class SecurityStatsResponse(BaseModel):
    """Response model for security statistics."""
    total_suspicious_queries: int = Field(..., description="Total number of suspicious queries logged")
    currently_blocked_users: int = Field(..., description="Number of users currently blocked")
    top_categories: Dict[str, int] = Field(..., description="Top injection pattern categories detected")
    avg_risk_score: float = Field(..., description="Average risk score of suspicious queries")
    blocked_user_ids: List[str] = Field(default=[], description="List of currently blocked user IDs")


class SecurityLogEntry(BaseModel):
    """Model for a security log entry."""
    timestamp: str = Field(..., description="ISO timestamp of the event")
    user_id: str = Field(..., description="User identifier")
    query_preview: str = Field(..., description="Preview of the query (truncated)")
    query_length: int = Field(..., description="Length of the original query")
    risk_score: float = Field(..., description="Calculated risk score")
    detection_count: int = Field(..., description="Number of patterns detected")
    categories: List[str] = Field(..., description="Categories of patterns detected")


class SecurityLogResponse(BaseModel):
    """Response model for security log."""
    entries: List[Dict[str, Any]] = Field(..., description="Security log entries")
    total: int = Field(..., description="Total number of entries returned")


class SecurityTestRequest(BaseModel):
    """Request model for testing security analysis."""
    text: str = Field(..., min_length=1, description="Text to analyze for security threats")
    user_id: Optional[str] = Field(default="test_user", description="User ID for rate limiting simulation")


class SecurityTestResponse(BaseModel):
    """Response model for security test."""
    sanitized_text: str = Field(..., description="Sanitized version of the text")
    risk_score: float = Field(..., description="Calculated risk score (0.0 to 1.0)")
    detections: List[Dict[str, Any]] = Field(..., description="Detected injection patterns")
    is_suspicious: bool = Field(..., description="Whether the query is flagged as suspicious")
    is_blocked: bool = Field(..., description="Whether the user would be blocked")
    block_remaining: Optional[int] = Field(None, description="Seconds until unblock (if blocked)")


@router.get("/stats", response_model=SecurityStatsResponse)
async def get_security_statistics():
    """
    Get security monitoring statistics.

    Returns aggregate statistics about detected security threats,
    blocked users, and pattern categories.
    """
    stats = get_security_stats()
    return SecurityStatsResponse(**stats)


@router.get("/log", response_model=SecurityLogResponse)
async def get_security_log_entries(limit: int = 100):
    """
    Get recent security log entries.

    Args:
        limit: Maximum number of entries to return (default 100)

    Returns:
        List of security log entries, newest first
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 1000")

    entries = get_security_log(limit)
    return SecurityLogResponse(entries=entries, total=len(entries))


@router.post("/test", response_model=SecurityTestResponse)
async def test_security_analysis(request: SecurityTestRequest):
    """
    Test the security analysis on a piece of text.

    This is useful for testing and debugging the prompt injection
    detection system without affecting real conversations.

    Args:
        request: SecurityTestRequest with text to analyze

    Returns:
        SecurityTestResponse with analysis results
    """
    security_service = get_security_service()
    result = security_service.analyze_query(request.text, user_id=request.user_id)

    return SecurityTestResponse(
        sanitized_text=result.get("sanitized_text", request.text),
        risk_score=result.get("risk_score", 0.0),
        detections=result.get("detections", []),
        is_suspicious=result.get("is_suspicious", False),
        is_blocked=result.get("is_blocked", False),
        block_remaining=result.get("block_remaining")
    )


@router.delete("/unblock/{user_id}")
async def unblock_user(user_id: str):
    """
    Manually unblock a user.

    This is an admin function to remove a user from the blocked list
    before their automatic timeout expires.

    Args:
        user_id: The user identifier to unblock

    Returns:
        Confirmation message
    """
    from services.security_service import _blocked_users

    if user_id in _blocked_users:
        del _blocked_users[user_id]
        logger.info(f"[Feature #319] Admin unblocked user: {user_id}")
        return {"message": f"User {user_id} has been unblocked", "success": True}

    return {"message": f"User {user_id} was not blocked", "success": False}


@router.get("/patterns")
async def get_injection_patterns():
    """
    Get the list of injection patterns being monitored.

    Returns the pattern categories and a sample of patterns
    (not the full regex for security reasons).
    """
    from services.security_service import INJECTION_PATTERNS

    # Group patterns by category
    categories = {}
    for pattern, category in INJECTION_PATTERNS:
        if category not in categories:
            categories[category] = {
                "count": 0,
                "examples": []
            }
        categories[category]["count"] += 1
        # Don't expose full regex patterns for security
        if len(categories[category]["examples"]) < 2:
            categories[category]["examples"].append(pattern[:30] + "..." if len(pattern) > 30 else pattern)

    return {
        "total_patterns": len(INJECTION_PATTERNS),
        "categories": categories
    }
