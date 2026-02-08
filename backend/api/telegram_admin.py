"""
Telegram Admin API for monitoring and managing Telegram users and messages.

Feature #314: Telegram admin panel in UI

This module provides endpoints for:
- Viewing Telegram users with activity stats
- Viewing message history per user
- Sending test messages
- Getting message statistics
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy import select, func, desc
from core.database import engine
from models.telegram import DBTelegramUser, DBTelegramMessage

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for API responses
class TelegramUserResponse(BaseModel):
    id: str
    chat_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    message_count: int = 0
    created_at: datetime
    last_message_at: Optional[datetime] = None


class TelegramMessageResponse(BaseModel):
    id: str
    user_id: str
    telegram_message_id: Optional[int] = None
    chat_id: int
    direction: str  # 'inbound' or 'outbound'
    content: Optional[str] = None
    media_type: Optional[str] = None
    media_file_id: Optional[str] = None
    created_at: datetime


class TelegramUserListResponse(BaseModel):
    users: List[TelegramUserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class TelegramMessageListResponse(BaseModel):
    messages: List[TelegramMessageResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
    user: Optional[TelegramUserResponse] = None


class TelegramStatsResponse(BaseModel):
    total_users: int
    total_messages: int
    messages_today: int
    messages_this_week: int
    messages_this_month: int
    active_users_today: int
    active_users_this_week: int
    inbound_messages: int
    outbound_messages: int


class SendTestMessageRequest(BaseModel):
    chat_id: int
    message: str


class SendTestMessageResponse(BaseModel):
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None


@router.get("/users", response_model=TelegramUserListResponse)
async def list_telegram_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    """
    List all Telegram users with pagination and optional filters.

    Args:
        page: Page number (1-based)
        per_page: Number of users per page (max 100)
        search: Optional search query for username, first_name, or last_name

    Returns:
        List of Telegram users with pagination info
    """
    with engine.connect() as conn:
        # Build base query
        query = select(DBTelegramUser)

        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (DBTelegramUser.username.ilike(search_pattern)) |
                (DBTelegramUser.first_name.ilike(search_pattern)) |
                (DBTelegramUser.last_name.ilike(search_pattern))
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = conn.execute(count_query).scalar() or 0

        # Apply ordering and pagination
        query = query.order_by(desc(DBTelegramUser.last_message_at))
        query = query.offset((page - 1) * per_page).limit(per_page)

        # Execute query
        result = conn.execute(query)
        rows = result.fetchall()

        users = []
        for row in rows:
            # Count messages for this user
            msg_count_query = select(func.count()).select_from(DBTelegramMessage).where(
                DBTelegramMessage.user_id == row.id
            )
            message_count = conn.execute(msg_count_query).scalar() or 0

            users.append(TelegramUserResponse(
                id=row.id,
                chat_id=row.chat_id,
                username=row.username,
                first_name=row.first_name,
                last_name=row.last_name,
                message_count=message_count,
                created_at=row.created_at,
                last_message_at=row.last_message_at
            ))

        total_pages = max(1, (total + per_page - 1) // per_page)

        return TelegramUserListResponse(
            users=users,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )


@router.get("/users/{chat_id}", response_model=TelegramUserResponse)
async def get_telegram_user(chat_id: int):
    """
    Get a specific Telegram user by chat_id.

    Args:
        chat_id: The user's Telegram chat_id

    Returns:
        Telegram user details
    """
    with engine.connect() as conn:
        query = select(DBTelegramUser).where(DBTelegramUser.chat_id == chat_id)
        result = conn.execute(query)
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        # Count messages for this user
        msg_count_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.user_id == row.id
        )
        message_count = conn.execute(msg_count_query).scalar() or 0

        return TelegramUserResponse(
            id=row.id,
            chat_id=row.chat_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            message_count=message_count,
            created_at=row.created_at,
            last_message_at=row.last_message_at
        )


@router.get("/users/{chat_id}/messages", response_model=TelegramMessageListResponse)
async def get_user_messages(
    chat_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100)
):
    """
    Get message history for a specific user by chat_id.

    Args:
        chat_id: The user's Telegram chat_id
        page: Page number (1-based)
        per_page: Number of messages per page (max 100)

    Returns:
        List of messages with pagination info and user details
    """
    with engine.connect() as conn:
        # First check user exists and get user info
        user_query = select(DBTelegramUser).where(DBTelegramUser.chat_id == chat_id)
        user_result = conn.execute(user_query)
        user_row = user_result.fetchone()

        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        # Count messages for this user
        msg_count_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.user_id == user_row.id
        )
        message_count = conn.execute(msg_count_query).scalar() or 0

        user = TelegramUserResponse(
            id=user_row.id,
            chat_id=user_row.chat_id,
            username=user_row.username,
            first_name=user_row.first_name,
            last_name=user_row.last_name,
            message_count=message_count,
            created_at=user_row.created_at,
            last_message_at=user_row.last_message_at
        )

        # Build message query using user_id (not chat_id for efficiency)
        query = select(DBTelegramMessage).where(DBTelegramMessage.user_id == user_row.id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = conn.execute(count_query).scalar() or 0

        # Apply ordering and pagination (newest first)
        query = query.order_by(desc(DBTelegramMessage.created_at))
        query = query.offset((page - 1) * per_page).limit(per_page)

        # Execute query
        result = conn.execute(query)
        rows = result.fetchall()

        messages = []
        for row in rows:
            messages.append(TelegramMessageResponse(
                id=row.id,
                user_id=row.user_id,
                telegram_message_id=row.telegram_message_id,
                chat_id=row.chat_id,
                direction=row.direction,
                content=row.content,
                media_type=row.media_type,
                media_file_id=row.media_file_id,
                created_at=row.created_at
            ))

        total_pages = max(1, (total + per_page - 1) // per_page)

        return TelegramMessageListResponse(
            messages=messages,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            user=user
        )


@router.post("/send", response_model=SendTestMessageResponse)
async def send_test_message(request: SendTestMessageRequest):
    """
    Send a test message to a Telegram user.

    Args:
        request: SendTestMessageRequest with chat_id and message

    Returns:
        Send result with success status and message_id if successful
    """
    from services.telegram_send_service import get_telegram_send_service

    try:
        send_service = get_telegram_send_service()

        if not send_service.is_configured():
            return SendTestMessageResponse(
                success=False,
                error="Telegram Bot Token not configured"
            )

        result = await send_service.send_message(
            chat_id=request.chat_id,
            text=request.message,
            parse_mode="Markdown"
        )

        if result.get('success'):
            logger.info(f"Test message sent to chat_id={request.chat_id}")
            return SendTestMessageResponse(
                success=True,
                message_id=result.get('message_id')
            )
        else:
            logger.warning(f"Failed to send test message: {result.get('error')}")
            return SendTestMessageResponse(
                success=False,
                error=result.get('error', 'Unknown error')
            )

    except Exception as e:
        logger.error(f"Error sending test message: {e}")
        return SendTestMessageResponse(
            success=False,
            error=str(e)
        )


@router.get("/stats", response_model=TelegramStatsResponse)
async def get_telegram_stats():
    """
    Get overall Telegram messaging statistics.

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
        total_users_query = select(func.count()).select_from(DBTelegramUser)
        total_users = conn.execute(total_users_query).scalar() or 0

        # Total messages
        total_messages_query = select(func.count()).select_from(DBTelegramMessage)
        total_messages = conn.execute(total_messages_query).scalar() or 0

        # Messages today
        messages_today_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.created_at >= start_of_today
        )
        messages_today = conn.execute(messages_today_query).scalar() or 0

        # Messages this week
        messages_week_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.created_at >= start_of_week
        )
        messages_this_week = conn.execute(messages_week_query).scalar() or 0

        # Messages this month
        messages_month_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.created_at >= start_of_month
        )
        messages_this_month = conn.execute(messages_month_query).scalar() or 0

        # Active users today
        active_today_query = select(func.count()).select_from(DBTelegramUser).where(
            DBTelegramUser.last_message_at >= start_of_today
        )
        active_users_today = conn.execute(active_today_query).scalar() or 0

        # Active users this week
        active_week_query = select(func.count()).select_from(DBTelegramUser).where(
            DBTelegramUser.last_message_at >= start_of_week
        )
        active_users_this_week = conn.execute(active_week_query).scalar() or 0

        # Inbound messages
        inbound_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.direction == 'inbound'
        )
        inbound_messages = conn.execute(inbound_query).scalar() or 0

        # Outbound messages
        outbound_query = select(func.count()).select_from(DBTelegramMessage).where(
            DBTelegramMessage.direction == 'outbound'
        )
        outbound_messages = conn.execute(outbound_query).scalar() or 0

        return TelegramStatsResponse(
            total_users=total_users,
            total_messages=total_messages,
            messages_today=messages_today,
            messages_this_week=messages_this_week,
            messages_this_month=messages_this_month,
            active_users_today=active_users_today,
            active_users_this_week=active_users_this_week,
            inbound_messages=inbound_messages,
            outbound_messages=outbound_messages
        )
