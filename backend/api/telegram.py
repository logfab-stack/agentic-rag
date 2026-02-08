"""
Telegram Bot Webhook API for receiving messages.

Feature #308: Telegram webhook endpoint
Feature #313: Telegram webhook registration endpoint

This module handles incoming Telegram messages via webhook.
Telegram sends JSON with message/callback_query objects.
We validate using bot token in URL path for security.

Handles:
- Text messages
- Documents (for file uploads)
- Commands (e.g., /start, /help)
- Callback queries (for inline keyboards)
- Webhook registration/unregistration with Telegram API
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging
import json
import httpx
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid

from sqlalchemy import select, update
from core.database import engine
from core.store import settings_store
from models.telegram import DBTelegramUser, DBTelegramMessage

logger = logging.getLogger(__name__)

router = APIRouter()


def get_telegram_config() -> Dict[str, Any]:
    """Get Telegram configuration from settings store."""
    bot_token = settings_store.get('telegram_bot_token', '')

    return {
        'bot_token': bot_token,
        'configured': bool(bot_token and len(bot_token) > 0)
    }


def validate_token(url_token: str) -> bool:
    """
    Validate that the token in the URL matches the configured bot token.

    Telegram webhooks use a secret token in the URL path for security.
    This prevents unauthorized access to the webhook endpoint.

    Args:
        url_token: Token from the URL path

    Returns:
        True if token matches configured bot token
    """
    config = get_telegram_config()
    if not config['configured']:
        return False

    # Use constant-time comparison to prevent timing attacks
    import hmac
    return hmac.compare_digest(url_token, config['bot_token'])


class TelegramUpdate:
    """
    Parser for Telegram Update objects.

    Telegram sends updates with various fields depending on the type:
    - message: Regular text/media messages
    - callback_query: Button clicks from inline keyboards
    - edited_message: Edited messages
    - channel_post: Messages in channels

    Ref: https://core.telegram.org/bots/api#update
    """

    def __init__(self, data: Dict[str, Any]):
        self.update_id = data.get('update_id')
        self.message = data.get('message')
        self.callback_query = data.get('callback_query')
        self.edited_message = data.get('edited_message')

    @property
    def chat_id(self) -> Optional[int]:
        """Extract chat_id from the update."""
        if self.message:
            return self.message.get('chat', {}).get('id')
        if self.callback_query:
            return self.callback_query.get('message', {}).get('chat', {}).get('id')
        if self.edited_message:
            return self.edited_message.get('chat', {}).get('id')
        return None

    @property
    def user(self) -> Optional[Dict[str, Any]]:
        """Extract user info from the update."""
        if self.message:
            return self.message.get('from')
        if self.callback_query:
            return self.callback_query.get('from')
        if self.edited_message:
            return self.edited_message.get('from')
        return None

    @property
    def text(self) -> Optional[str]:
        """Extract text content from the update."""
        if self.message:
            return self.message.get('text')
        if self.callback_query:
            return self.callback_query.get('data')
        if self.edited_message:
            return self.edited_message.get('text')
        return None

    @property
    def message_id(self) -> Optional[int]:
        """Extract message_id from the update."""
        if self.message:
            return self.message.get('message_id')
        if self.callback_query:
            return self.callback_query.get('message', {}).get('message_id')
        if self.edited_message:
            return self.edited_message.get('message_id')
        return None

    @property
    def document(self) -> Optional[Dict[str, Any]]:
        """Extract document info from the update (for file uploads)."""
        if self.message:
            return self.message.get('document')
        return None

    @property
    def photo(self) -> Optional[list]:
        """Extract photo info from the update (array of PhotoSize)."""
        if self.message:
            return self.message.get('photo')
        return None

    @property
    def voice(self) -> Optional[Dict[str, Any]]:
        """Extract voice message info."""
        if self.message:
            return self.message.get('voice')
        return None

    @property
    def video(self) -> Optional[Dict[str, Any]]:
        """Extract video info."""
        if self.message:
            return self.message.get('video')
        return None

    @property
    def audio(self) -> Optional[Dict[str, Any]]:
        """Extract audio info."""
        if self.message:
            return self.message.get('audio')
        return None

    @property
    def caption(self) -> Optional[str]:
        """Extract caption for media messages."""
        if self.message:
            return self.message.get('caption')
        return None

    @property
    def is_command(self) -> bool:
        """Check if message is a bot command (starts with /)."""
        text = self.text
        return bool(text and text.startswith('/'))

    @property
    def command(self) -> Optional[str]:
        """Extract command name (without /)."""
        if self.is_command and self.text:
            # Commands can have @botusername suffix, e.g., /start@mybot
            cmd = self.text.split()[0][1:]  # Remove leading /
            return cmd.split('@')[0]  # Remove @botusername
        return None

    @property
    def command_args(self) -> Optional[str]:
        """Extract command arguments (text after command)."""
        if self.is_command and self.text:
            parts = self.text.split(maxsplit=1)
            return parts[1] if len(parts) > 1 else None
        return None

    @property
    def media_type(self) -> Optional[str]:
        """Determine the type of media in the message."""
        if self.document:
            return 'document'
        if self.photo:
            return 'photo'
        if self.voice:
            return 'voice'
        if self.video:
            return 'video'
        if self.audio:
            return 'audio'
        if self.message and self.message.get('sticker'):
            return 'sticker'
        return None

    @property
    def media_file_id(self) -> Optional[str]:
        """Get the file_id for any media type."""
        if self.document:
            return self.document.get('file_id')
        if self.photo:
            # Photo is array of sizes, get largest (last)
            return self.photo[-1].get('file_id') if self.photo else None
        if self.voice:
            return self.voice.get('file_id')
        if self.video:
            return self.video.get('file_id')
        if self.audio:
            return self.audio.get('file_id')
        return None


async def store_telegram_message(
    chat_id: int,
    user: Optional[Dict[str, Any]],
    message_id: Optional[int],
    text: Optional[str],
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
    direction: str = 'inbound'
) -> str:
    """
    Store Telegram message in database and update/create user.

    Args:
        chat_id: Telegram chat ID (unique per user)
        user: User info dict from Telegram
        message_id: Telegram message ID
        text: Message text content
        media_type: Type of media if present
        media_file_id: Telegram file_id for media
        direction: 'inbound' or 'outbound'

    Returns:
        User ID (existing or newly created)
    """
    now = datetime.now(timezone.utc)
    user_id = None

    with engine.connect() as conn:
        # Check if user exists by chat_id
        user_query = select(DBTelegramUser).where(DBTelegramUser.chat_id == chat_id)
        user_result = conn.execute(user_query)
        user_row = user_result.fetchone()

        if user_row:
            # Update existing user
            user_id = user_row.id

            # Update user info and last_message_at
            update_values = {'last_message_at': now}

            # Update username if provided
            if user:
                if user.get('username'):
                    update_values['username'] = user.get('username')
                if user.get('first_name'):
                    update_values['first_name'] = user.get('first_name')
                if user.get('last_name'):
                    update_values['last_name'] = user.get('last_name')

            update_stmt = (
                update(DBTelegramUser)
                .where(DBTelegramUser.id == user_id)
                .values(**update_values)
            )
            conn.execute(update_stmt)
        else:
            # Create new user
            user_id = str(uuid.uuid4())
            insert_stmt = DBTelegramUser.__table__.insert().values(
                id=user_id,
                chat_id=chat_id,
                username=user.get('username') if user else None,
                first_name=user.get('first_name') if user else None,
                last_name=user.get('last_name') if user else None,
                created_at=now,
                last_message_at=now
            )
            conn.execute(insert_stmt)
            logger.info(f"Created new Telegram user: chat_id={chat_id}, user_id={user_id}")

        # Store the message
        msg_id = str(uuid.uuid4())
        message_stmt = DBTelegramMessage.__table__.insert().values(
            id=msg_id,
            user_id=user_id,
            telegram_message_id=message_id,
            chat_id=chat_id,
            direction=direction,
            content=text,
            media_type=media_type,
            media_file_id=media_file_id,
            created_at=now
        )
        conn.execute(message_stmt)
        conn.commit()

        logger.info(f"Stored Telegram message: chat_id={chat_id}, direction={direction}, has_media={bool(media_type)}")

    return user_id


@router.post("/webhook/{token}")
async def webhook_receive(token: str, request: Request):
    """
    Handle incoming Telegram webhook updates.

    Telegram sends a POST request with JSON body containing an Update object.
    The token in the URL path must match the configured bot token for security.

    IMPORTANT: Telegram expects a quick 200 OK response. Any processing
    should be done asynchronously or quickly to avoid timeouts.

    Args:
        token: Bot token from URL path (for validation)
        request: FastAPI request object

    Returns:
        JSON response (Telegram ignores response body, just needs 200 OK)
    """
    # Step 1: Validate token
    if not validate_token(token):
        logger.warning(f"Invalid Telegram webhook token received")
        # Return 401 but still quickly - don't want to hang
        raise HTTPException(status_code=401, detail="Invalid token")

    # Step 2: Parse JSON body
    try:
        body = await request.body()
        data = json.loads(body)
        logger.debug(f"Telegram webhook received: {json.dumps(data)[:500]}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Telegram webhook JSON: {e}")
        # Return 200 anyway to prevent Telegram from retrying
        return JSONResponse(content={"ok": True}, status_code=200)

    # Step 3: Parse Update object
    update = TelegramUpdate(data)

    chat_id = update.chat_id
    if not chat_id:
        logger.warning("Telegram update has no chat_id, ignoring")
        return JSONResponse(content={"ok": True}, status_code=200)

    # Step 4: Extract information
    user_info = update.user
    text = update.text
    message_id = update.message_id
    media_type = update.media_type
    media_file_id = update.media_file_id
    caption = update.caption

    # For media messages, use caption as text if available
    if media_type and not text and caption:
        text = caption

    logger.info(f"Telegram update: chat_id={chat_id}, text={text[:50] if text else None}..., media={media_type}")

    # Step 5: Store message in database
    try:
        user_id = await store_telegram_message(
            chat_id=chat_id,
            user=user_info,
            message_id=message_id,
            text=text,
            media_type=media_type,
            media_file_id=media_file_id,
            direction='inbound'
        )
    except Exception as e:
        import traceback
        logger.error(f"Failed to store Telegram message: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Continue processing even if storage fails
        user_id = None

    # Step 6: Process message through TelegramService
    # Feature #309: Telegram service for RAG processing
    # Feature #334: Import services before if/elif blocks so they're available in all code paths
    from core.database import AsyncSessionLocal
    from services.telegram_service import get_telegram_service
    from services.telegram_send_service import get_telegram_send_service

    try:
        # Only process text messages (skip media-only for now)
        if text:
            # Process in background to avoid timeout
            async def process_and_respond():
                try:
                    async with AsyncSessionLocal() as db:
                        telegram_service = await get_telegram_service(db)
                        result = await telegram_service.process_message(
                            chat_id=chat_id,
                            text=text,
                            user_info=user_info
                        )

                        # Send response back to user
                        if result.get("response"):
                            send_service = get_telegram_send_service()
                            await send_service.send_response(
                                chat_id=chat_id,
                                response=result["response"],
                                reply_to_message_id=message_id,
                                conversation_id=result.get("conversation_id")
                            )

                            # Store outbound message
                            await store_telegram_message(
                                chat_id=chat_id,
                                user=None,
                                message_id=None,
                                text=result["response"],
                                direction='outbound'
                            )

                            logger.info(f"Telegram: Sent response to chat_id={chat_id}, truncated={result.get('was_truncated')}")
                except Exception as e:
                    logger.error(f"Error in background processing: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            # Create background task (don't await to respond quickly)
            asyncio.create_task(process_and_respond())
            logger.info(f"Telegram: Started background processing for chat_id={chat_id}")
        elif media_type == 'document':
            # Feature #311: Handle document uploads
            logger.info(f"Telegram document received: file_id={media_file_id}")

            # Extract document details
            document_info = update.document
            file_name = document_info.get('file_name') if document_info else None
            doc_mime_type = document_info.get('mime_type') if document_info else None
            file_size = document_info.get('file_size') if document_info else None

            # Process document upload in background
            async def process_document_upload():
                try:
                    async with AsyncSessionLocal() as db:
                        telegram_service = await get_telegram_service(db)
                        result = await telegram_service.handle_document_upload(
                            chat_id=chat_id,
                            file_id=media_file_id,
                            file_name=file_name,
                            mime_type=doc_mime_type,
                            file_size=file_size,
                            caption=caption,
                            user_info=user_info
                        )

                        # Send response back to user
                        send_service = get_telegram_send_service()
                        if result.get('success'):
                            response_text = result.get('response', 'Documento caricato con successo!')
                        else:
                            response_text = result.get('error', 'Errore durante il caricamento del documento.')

                        await send_service.send_response(
                            chat_id=chat_id,
                            response=response_text,
                            reply_to_message_id=message_id
                        )

                        # Store outbound message
                        await store_telegram_message(
                            chat_id=chat_id,
                            user=None,
                            message_id=None,
                            text=response_text,
                            direction='outbound'
                        )

                        logger.info(f"Telegram: Document upload processed for chat_id={chat_id}, success={result.get('success')}")
                except Exception as e:
                    logger.error(f"Error processing document upload: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                    # Try to send error message to user
                    try:
                        send_service = get_telegram_send_service()
                        await send_service.send_response(
                            chat_id=chat_id,
                            response="*Errore*\n\nSi e verificato un errore durante l'elaborazione del documento. Riprova piu tardi.",
                            reply_to_message_id=message_id
                        )
                    except Exception:
                        pass

            asyncio.create_task(process_document_upload())
            logger.info(f"Telegram: Started document upload processing for chat_id={chat_id}")
        elif media_type:
            # Other media types (photo, voice, video, etc.) - not currently supported for processing
            logger.info(f"Telegram media received (unsupported for upload): type={media_type}, file_id={media_file_id}")

            # Send message explaining document upload support
            async def send_unsupported_media_response():
                try:
                    send_service = get_telegram_send_service()
                    response_text = (
                        "*Tipo di media non supportato*\n\n"
                        f"Ho ricevuto un file di tipo `{media_type}`, ma al momento supporto solo il caricamento di documenti.\n\n"
                        "*Formati supportati:*\n"
                        "- PDF (.pdf)\n"
                        "- Testo (.txt)\n"
                        "- Word (.docx)\n"
                        "- Markdown (.md)\n"
                        "- CSV (.csv)\n"
                        "- Excel (.xlsx, .xls)\n"
                        "- JSON (.json)\n\n"
                        "_Invia il file come documento (non come foto/video) per caricarlo._"
                    )
                    await send_service.send_response(
                        chat_id=chat_id,
                        response=response_text,
                        reply_to_message_id=message_id
                    )
                except Exception as e:
                    logger.error(f"Error sending unsupported media response: {e}")

            asyncio.create_task(send_unsupported_media_response())
        else:
            logger.info(f"Telegram update with no text or media, ignoring")
    except Exception as e:
        logger.error(f"Error setting up Telegram message processing: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # Step 7: Return 200 OK immediately
    # Telegram expects a quick response, any heavy processing should be async
    return JSONResponse(content={"ok": True}, status_code=200)


@router.get("/webhook/{token}")
async def webhook_info(token: str):
    """
    GET endpoint for webhook - mainly for testing/verification.

    Telegram doesn't require GET verification like some other services,
    but this endpoint can be used to test the webhook URL is reachable.
    """
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    return JSONResponse(content={
        "status": "active",
        "service": "Telegram Bot Webhook",
        "message": "Webhook endpoint is active and ready to receive updates"
    })


# =============================================================================
# Feature #313: Telegram Webhook Registration Endpoints
# =============================================================================

class RegisterWebhookRequest(BaseModel):
    """Request body for webhook registration."""
    webhook_url: Optional[str] = None  # If not provided, auto-detect from ngrok


class RegisterWebhookResponse(BaseModel):
    """Response from webhook registration."""
    success: bool
    message: str
    webhook_url: Optional[str] = None
    description: Optional[str] = None


class WebhookInfoResponse(BaseModel):
    """Response from webhook info endpoint."""
    registered: bool
    url: Optional[str] = None
    has_custom_certificate: bool = False
    pending_update_count: int = 0
    last_error_date: Optional[int] = None
    last_error_message: Optional[str] = None
    max_connections: Optional[int] = None
    allowed_updates: Optional[list] = None
    ip_address: Optional[str] = None


async def get_ngrok_public_url() -> Optional[str]:
    """
    Get the public URL from ngrok's local API.

    Returns:
        The public https URL from ngrok, or None if not available.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:4040/api/tunnels")
            if response.status_code == 200:
                data = response.json()
                tunnels = data.get('tunnels', [])
                for tunnel in tunnels:
                    public_url = tunnel.get('public_url', '')
                    # Prefer https URLs
                    if public_url.startswith('https://'):
                        return public_url
                # Fall back to any URL
                if tunnels:
                    return tunnels[0].get('public_url')
    except Exception as e:
        logger.debug(f"Failed to get ngrok URL: {e}")
    return None


@router.post("/register-webhook", response_model=RegisterWebhookResponse)
async def register_webhook(request: RegisterWebhookRequest):
    """
    Register webhook URL with Telegram servers.

    Uses the Telegram setWebhook API to register a webhook URL.
    If no URL is provided, attempts to auto-detect from ngrok.

    The webhook URL will be: {base_url}/api/telegram/webhook/{bot_token}

    Args:
        request: Contains optional webhook_url to register

    Returns:
        RegisterWebhookResponse with success status and details
    """
    config = get_telegram_config()

    if not config['configured']:
        return RegisterWebhookResponse(
            success=False,
            message="Telegram Bot Token not configured",
            description="Please configure your bot token in Settings first"
        )

    bot_token = config['bot_token']

    # Determine webhook URL
    base_url = request.webhook_url
    if not base_url:
        # Try to auto-detect from ngrok
        base_url = await get_ngrok_public_url()
        if not base_url:
            return RegisterWebhookResponse(
                success=False,
                message="Could not auto-detect webhook URL",
                description="ngrok is not running or no public URL available. Please provide a webhook URL or start ngrok."
            )

    # Construct full webhook URL with token
    # Format: https://your-domain.com/api/telegram/webhook/{bot_token}
    webhook_url = f"{base_url.rstrip('/')}/api/telegram/webhook/{bot_token}"

    # Call Telegram setWebhook API
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

            response = await client.post(
                telegram_api_url,
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "callback_query", "edited_message"]
                }
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info(f"Telegram webhook registered successfully: {webhook_url}")
                    return RegisterWebhookResponse(
                        success=True,
                        message="Webhook registered successfully",
                        webhook_url=webhook_url,
                        description=data.get("description", "Webhook was set")
                    )
                else:
                    error_description = data.get("description", "Unknown error")
                    logger.error(f"Telegram setWebhook failed: {error_description}")
                    return RegisterWebhookResponse(
                        success=False,
                        message="Failed to register webhook",
                        description=error_description
                    )
            elif response.status_code == 401:
                return RegisterWebhookResponse(
                    success=False,
                    message="Invalid Bot Token",
                    description="The configured bot token is not valid"
                )
            else:
                return RegisterWebhookResponse(
                    success=False,
                    message=f"Telegram API error: {response.status_code}",
                    description=response.text[:200] if response.text else None
                )

    except httpx.ConnectError:
        return RegisterWebhookResponse(
            success=False,
            message="Connection error",
            description="Could not connect to Telegram API. Check your internet connection."
        )
    except httpx.TimeoutException:
        return RegisterWebhookResponse(
            success=False,
            message="Timeout",
            description="Request to Telegram API timed out. Please try again."
        )
    except Exception as e:
        logger.error(f"Error registering Telegram webhook: {e}")
        return RegisterWebhookResponse(
            success=False,
            message="Error registering webhook",
            description=str(e)
        )


@router.delete("/unregister-webhook", response_model=RegisterWebhookResponse)
async def unregister_webhook():
    """
    Unregister (delete) the webhook from Telegram servers.

    Calls the Telegram deleteWebhook API to remove the webhook registration.
    After this, Telegram will not send updates to your server until you
    register a new webhook.

    Returns:
        RegisterWebhookResponse with success status
    """
    config = get_telegram_config()

    if not config['configured']:
        return RegisterWebhookResponse(
            success=False,
            message="Telegram Bot Token not configured",
            description="Please configure your bot token in Settings first"
        )

    bot_token = config['bot_token']

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            telegram_api_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"

            response = await client.post(telegram_api_url)

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info("Telegram webhook unregistered successfully")
                    return RegisterWebhookResponse(
                        success=True,
                        message="Webhook unregistered successfully",
                        description=data.get("description", "Webhook was deleted")
                    )
                else:
                    error_description = data.get("description", "Unknown error")
                    logger.error(f"Telegram deleteWebhook failed: {error_description}")
                    return RegisterWebhookResponse(
                        success=False,
                        message="Failed to unregister webhook",
                        description=error_description
                    )
            elif response.status_code == 401:
                return RegisterWebhookResponse(
                    success=False,
                    message="Invalid Bot Token",
                    description="The configured bot token is not valid"
                )
            else:
                return RegisterWebhookResponse(
                    success=False,
                    message=f"Telegram API error: {response.status_code}",
                    description=response.text[:200] if response.text else None
                )

    except httpx.ConnectError:
        return RegisterWebhookResponse(
            success=False,
            message="Connection error",
            description="Could not connect to Telegram API. Check your internet connection."
        )
    except httpx.TimeoutException:
        return RegisterWebhookResponse(
            success=False,
            message="Timeout",
            description="Request to Telegram API timed out. Please try again."
        )
    except Exception as e:
        logger.error(f"Error unregistering Telegram webhook: {e}")
        return RegisterWebhookResponse(
            success=False,
            message="Error unregistering webhook",
            description=str(e)
        )


@router.get("/webhook-info", response_model=WebhookInfoResponse)
async def get_webhook_info():
    """
    Get current webhook status from Telegram servers.

    Calls the Telegram getWebhookInfo API to retrieve the current
    webhook configuration, including URL, pending updates, and any errors.

    Returns:
        WebhookInfoResponse with current webhook status
    """
    config = get_telegram_config()

    if not config['configured']:
        raise HTTPException(
            status_code=400,
            detail="Telegram Bot Token not configured"
        )

    bot_token = config['bot_token']

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            telegram_api_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"

            response = await client.get(telegram_api_url)

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    result = data.get("result", {})
                    webhook_url = result.get("url", "")

                    return WebhookInfoResponse(
                        registered=bool(webhook_url),
                        url=webhook_url if webhook_url else None,
                        has_custom_certificate=result.get("has_custom_certificate", False),
                        pending_update_count=result.get("pending_update_count", 0),
                        last_error_date=result.get("last_error_date"),
                        last_error_message=result.get("last_error_message"),
                        max_connections=result.get("max_connections"),
                        allowed_updates=result.get("allowed_updates"),
                        ip_address=result.get("ip_address")
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=data.get("description", "Unknown error from Telegram API")
                    )
            elif response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid Bot Token"
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Telegram API error: {response.status_code}"
                )

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Could not connect to Telegram API"
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Request to Telegram API timed out"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Telegram webhook info: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =============================================================================
# Feature #312: Telegram Bot Commands for BotFather
# =============================================================================

# BotFather command definitions - paste these into BotFather's /setcommands
BOTFATHER_COMMANDS = [
    {"command": "start", "description": "Avvia il bot e mostra il messaggio di benvenuto"},
    {"command": "help", "description": "Mostra i comandi disponibili"},
    {"command": "reset", "description": "Inizia una nuova conversazione"},
    {"command": "docs", "description": "Mostra i tuoi documenti"},
    {"command": "collezioni", "description": "Mostra le collezioni disponibili"},
    {"command": "setcollezione", "description": "Imposta la collezione predefinita"},
    {"command": "elimina", "description": "Elimina un documento"}
]

# Plain text format for copy-paste to BotFather
BOTFATHER_COMMANDS_TEXT = """start - Avvia il bot e mostra il messaggio di benvenuto
help - Mostra i comandi disponibili
reset - Inizia una nuova conversazione
docs - Mostra i tuoi documenti
collezioni - Mostra le collezioni disponibili
setcollezione - Imposta la collezione predefinita
elimina - Elimina un documento"""


class BotCommandsResponse(BaseModel):
    """Response with bot commands for BotFather registration."""
    commands: list
    text_format: str
    instructions: str


@router.get("/botfather-commands", response_model=BotCommandsResponse)
async def get_botfather_commands():
    """
    Get bot commands formatted for BotFather registration.

    Feature #312: Telegram bot commands

    Returns commands in both JSON format (for setMyCommands API)
    and plain text format (for manual paste into BotFather).

    Usage:
    1. Open Telegram and start a chat with @BotFather
    2. Send /setcommands
    3. Select your bot
    4. Paste the text_format content
    """
    return BotCommandsResponse(
        commands=BOTFATHER_COMMANDS,
        text_format=BOTFATHER_COMMANDS_TEXT,
        instructions=(
            "To register commands with BotFather:\n"
            "1. Open Telegram and message @BotFather\n"
            "2. Send /setcommands\n"
            "3. Select your bot\n"
            "4. Copy and paste the text_format field content"
        )
    )


class SetCommandsResponse(BaseModel):
    """Response from setMyCommands API call."""
    success: bool
    message: str
    description: Optional[str] = None


@router.post("/set-commands", response_model=SetCommandsResponse)
async def set_bot_commands():
    """
    Register bot commands with Telegram using the setMyCommands API.

    Feature #312: Telegram bot commands

    This calls the Telegram setMyCommands API to register commands
    with autocomplete support in the Telegram app.

    The commands will appear when a user types '/' in the chat.
    """
    config = get_telegram_config()

    if not config['configured']:
        return SetCommandsResponse(
            success=False,
            message="Telegram Bot Token not configured",
            description="Please configure your bot token in Settings first"
        )

    bot_token = config['bot_token']

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"

            response = await client.post(
                telegram_api_url,
                json={
                    "commands": BOTFATHER_COMMANDS
                }
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info("Telegram bot commands registered successfully")
                    return SetCommandsResponse(
                        success=True,
                        message="Bot commands registered successfully",
                        description=f"Registered {len(BOTFATHER_COMMANDS)} commands"
                    )
                else:
                    error_description = data.get("description", "Unknown error")
                    logger.error(f"Telegram setMyCommands failed: {error_description}")
                    return SetCommandsResponse(
                        success=False,
                        message="Failed to register commands",
                        description=error_description
                    )
            elif response.status_code == 401:
                return SetCommandsResponse(
                    success=False,
                    message="Invalid Bot Token",
                    description="The configured bot token is not valid"
                )
            else:
                return SetCommandsResponse(
                    success=False,
                    message=f"Telegram API error: {response.status_code}",
                    description=response.text[:200] if response.text else None
                )

    except httpx.ConnectError:
        return SetCommandsResponse(
            success=False,
            message="Connection error",
            description="Could not connect to Telegram API"
        )
    except httpx.TimeoutException:
        return SetCommandsResponse(
            success=False,
            message="Timeout",
            description="Request to Telegram API timed out"
        )
    except Exception as e:
        logger.error(f"Error setting Telegram bot commands: {e}")
        return SetCommandsResponse(
            success=False,
            message="Error setting commands",
            description=str(e)
        )
