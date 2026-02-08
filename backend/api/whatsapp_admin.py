"""
WhatsApp Admin API for monitoring and managing WhatsApp users and messages.

This module provides endpoints for:
- Viewing WhatsApp users with activity stats
- Viewing message history per user
- Blocking/unblocking phone numbers
- Getting message statistics
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import logging
import json

from sqlalchemy import select, func, update, desc
from core.database import engine
from models.whatsapp import DBWhatsAppUser, DBWhatsAppMessage

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for API responses
class WhatsAppUserResponse(BaseModel):
    id: str
    phone_number: str
    display_name: Optional[str] = None
    is_blocked: bool
    message_count: int
    first_seen_at: datetime
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime


class WhatsAppMessageResponse(BaseModel):
    id: str
    user_id: str
    message_sid: Optional[str] = None
    direction: str  # 'inbound' or 'outbound'
    body: Optional[str] = None
    media_urls: Optional[List[str]] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class WhatsAppUserListResponse(BaseModel):
    users: List[WhatsAppUserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class WhatsAppMessageListResponse(BaseModel):
    messages: List[WhatsAppMessageResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
    user: Optional[WhatsAppUserResponse] = None


class WhatsAppStatsResponse(BaseModel):
    total_users: int
    total_messages: int
    messages_today: int
    messages_this_week: int
    messages_this_month: int
    active_users_today: int
    active_users_this_week: int
    blocked_users: int
    inbound_messages: int
    outbound_messages: int


class BlockUnblockRequest(BaseModel):
    is_blocked: bool


@router.get("/users", response_model=WhatsAppUserListResponse)
async def list_whatsapp_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    blocked_only: bool = Query(False),
    search: Optional[str] = Query(None)
):
    """
    List all WhatsApp users with pagination and optional filters.

    Args:
        page: Page number (1-based)
        per_page: Number of users per page (max 100)
        blocked_only: If True, only return blocked users
        search: Optional search query for phone number or display name

    Returns:
        List of WhatsApp users with pagination info
    """
    with engine.connect() as conn:
        # Build base query
        query = select(DBWhatsAppUser)

        # Apply filters
        if blocked_only:
            query = query.where(DBWhatsAppUser.is_blocked == True)

        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (DBWhatsAppUser.phone_number.ilike(search_pattern)) |
                (DBWhatsAppUser.display_name.ilike(search_pattern))
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = conn.execute(count_query).scalar() or 0

        # Apply ordering and pagination
        query = query.order_by(desc(DBWhatsAppUser.last_active_at))
        query = query.offset((page - 1) * per_page).limit(per_page)

        # Execute query
        result = conn.execute(query)
        rows = result.fetchall()

        users = []
        for row in rows:
            users.append(WhatsAppUserResponse(
                id=row.id,
                phone_number=row.phone_number,
                display_name=row.display_name,
                is_blocked=row.is_blocked,
                message_count=row.message_count,
                first_seen_at=row.first_seen_at,
                last_active_at=row.last_active_at,
                created_at=row.created_at,
                updated_at=row.updated_at
            ))

        total_pages = (total + per_page - 1) // per_page

        return WhatsAppUserListResponse(
            users=users,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )


@router.get("/users/{user_id}", response_model=WhatsAppUserResponse)
async def get_whatsapp_user(user_id: str):
    """
    Get a specific WhatsApp user by ID.

    Args:
        user_id: The user's unique ID

    Returns:
        WhatsApp user details
    """
    with engine.connect() as conn:
        query = select(DBWhatsAppUser).where(DBWhatsAppUser.id == user_id)
        result = conn.execute(query)
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        return WhatsAppUserResponse(
            id=row.id,
            phone_number=row.phone_number,
            display_name=row.display_name,
            is_blocked=row.is_blocked,
            message_count=row.message_count,
            first_seen_at=row.first_seen_at,
            last_active_at=row.last_active_at,
            created_at=row.created_at,
            updated_at=row.updated_at
        )


@router.get("/users/{user_id}/messages", response_model=WhatsAppMessageListResponse)
async def get_user_messages(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100)
):
    """
    Get message history for a specific user.

    Args:
        user_id: The user's unique ID
        page: Page number (1-based)
        per_page: Number of messages per page (max 100)

    Returns:
        List of messages with pagination info and user details
    """
    with engine.connect() as conn:
        # First check user exists and get user info
        user_query = select(DBWhatsAppUser).where(DBWhatsAppUser.id == user_id)
        user_result = conn.execute(user_query)
        user_row = user_result.fetchone()

        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        user = WhatsAppUserResponse(
            id=user_row.id,
            phone_number=user_row.phone_number,
            display_name=user_row.display_name,
            is_blocked=user_row.is_blocked,
            message_count=user_row.message_count,
            first_seen_at=user_row.first_seen_at,
            last_active_at=user_row.last_active_at,
            created_at=user_row.created_at,
            updated_at=user_row.updated_at
        )

        # Build message query
        query = select(DBWhatsAppMessage).where(DBWhatsAppMessage.user_id == user_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = conn.execute(count_query).scalar() or 0

        # Apply ordering and pagination (newest first)
        query = query.order_by(desc(DBWhatsAppMessage.created_at))
        query = query.offset((page - 1) * per_page).limit(per_page)

        # Execute query
        result = conn.execute(query)
        rows = result.fetchall()

        messages = []
        for row in rows:
            # Parse media_urls from JSON if present
            media_urls = None
            if row.media_urls:
                try:
                    media_urls = json.loads(row.media_urls)
                except:
                    media_urls = None

            messages.append(WhatsAppMessageResponse(
                id=row.id,
                user_id=row.user_id,
                message_sid=row.message_sid,
                direction=row.direction,
                body=row.body,
                media_urls=media_urls,
                status=row.status,
                error_message=row.error_message,
                created_at=row.created_at
            ))

        total_pages = (total + per_page - 1) // per_page

        return WhatsAppMessageListResponse(
            messages=messages,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            user=user
        )


@router.put("/users/{user_id}/block", response_model=WhatsAppUserResponse)
async def block_unblock_user(user_id: str, request: BlockUnblockRequest):
    """
    Block or unblock a WhatsApp user.

    Args:
        user_id: The user's unique ID
        request: BlockUnblockRequest with is_blocked field

    Returns:
        Updated user details
    """
    with engine.connect() as conn:
        # Check user exists
        check_query = select(DBWhatsAppUser).where(DBWhatsAppUser.id == user_id)
        check_result = conn.execute(check_query)
        if not check_result.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        # Update blocked status
        update_stmt = (
            update(DBWhatsAppUser)
            .where(DBWhatsAppUser.id == user_id)
            .values(is_blocked=request.is_blocked, updated_at=datetime.now(timezone.utc))
        )
        conn.execute(update_stmt)
        conn.commit()

        # Fetch and return updated user
        result = conn.execute(check_query)
        row = result.fetchone()

        logger.info(f"WhatsApp user {row.phone_number} {'blocked' if request.is_blocked else 'unblocked'}")

        return WhatsAppUserResponse(
            id=row.id,
            phone_number=row.phone_number,
            display_name=row.display_name,
            is_blocked=row.is_blocked,
            message_count=row.message_count,
            first_seen_at=row.first_seen_at,
            last_active_at=row.last_active_at,
            created_at=row.created_at,
            updated_at=row.updated_at
        )


@router.get("/stats", response_model=WhatsAppStatsResponse)
async def get_whatsapp_stats():
    """
    Get overall WhatsApp messaging statistics.

    Returns:
        Statistics about users, messages, and activity
    """
    now = datetime.now(timezone.utc)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    with engine.connect() as conn:
        # Total users
        total_users_query = select(func.count()).select_from(DBWhatsAppUser)
        total_users = conn.execute(total_users_query).scalar() or 0

        # Total messages
        total_messages_query = select(func.count()).select_from(DBWhatsAppMessage)
        total_messages = conn.execute(total_messages_query).scalar() or 0

        # Messages today
        messages_today_query = select(func.count()).select_from(DBWhatsAppMessage).where(
            DBWhatsAppMessage.created_at >= start_of_today
        )
        messages_today = conn.execute(messages_today_query).scalar() or 0

        # Messages this week
        messages_week_query = select(func.count()).select_from(DBWhatsAppMessage).where(
            DBWhatsAppMessage.created_at >= start_of_week
        )
        messages_this_week = conn.execute(messages_week_query).scalar() or 0

        # Messages this month
        messages_month_query = select(func.count()).select_from(DBWhatsAppMessage).where(
            DBWhatsAppMessage.created_at >= start_of_month
        )
        messages_this_month = conn.execute(messages_month_query).scalar() or 0

        # Active users today
        active_today_query = select(func.count()).select_from(DBWhatsAppUser).where(
            DBWhatsAppUser.last_active_at >= start_of_today
        )
        active_users_today = conn.execute(active_today_query).scalar() or 0

        # Active users this week
        active_week_query = select(func.count()).select_from(DBWhatsAppUser).where(
            DBWhatsAppUser.last_active_at >= start_of_week
        )
        active_users_this_week = conn.execute(active_week_query).scalar() or 0

        # Blocked users
        blocked_query = select(func.count()).select_from(DBWhatsAppUser).where(
            DBWhatsAppUser.is_blocked == True
        )
        blocked_users = conn.execute(blocked_query).scalar() or 0

        # Inbound messages
        inbound_query = select(func.count()).select_from(DBWhatsAppMessage).where(
            DBWhatsAppMessage.direction == 'inbound'
        )
        inbound_messages = conn.execute(inbound_query).scalar() or 0

        # Outbound messages
        outbound_query = select(func.count()).select_from(DBWhatsAppMessage).where(
            DBWhatsAppMessage.direction == 'outbound'
        )
        outbound_messages = conn.execute(outbound_query).scalar() or 0

        return WhatsAppStatsResponse(
            total_users=total_users,
            total_messages=total_messages,
            messages_today=messages_today,
            messages_this_week=messages_this_week,
            messages_this_month=messages_this_month,
            active_users_today=active_users_today,
            active_users_this_week=active_users_this_week,
            blocked_users=blocked_users,
            inbound_messages=inbound_messages,
            outbound_messages=outbound_messages
        )
