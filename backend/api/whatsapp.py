"""
WhatsApp Webhook API for receiving messages via Twilio.

This module handles incoming WhatsApp messages from Twilio webhooks.
It validates Twilio request signatures for security and extracts
message content for processing by the RAG system.
"""

from fastapi import APIRouter, Request, HTTPException, Query, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import hmac
import hashlib
import base64
import json
import uuid
from typing import Optional, List
from urllib.parse import urlencode
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from sqlalchemy import select, update
from core.database import engine, get_db, AsyncSessionLocal
from models.whatsapp import DBWhatsAppUser, DBWhatsAppMessage
from services.whatsapp_service import WhatsAppService
from services.twilio_send_service import get_twilio_send_service
from services.whatsapp_document_service import get_whatsapp_document_service

logger = logging.getLogger(__name__)

router = APIRouter()


def validate_twilio_signature(
    request_url: str,
    params: dict,
    signature: str,
    auth_token: str
) -> bool:
    """
    Validate Twilio request signature to ensure the request is authentic.

    Twilio signs all requests by:
    1. Sorting POST parameters alphabetically
    2. Appending key=value pairs to the URL
    3. Creating HMAC-SHA1 hash with auth token
    4. Base64 encoding the hash

    Args:
        request_url: The full URL Twilio sent the request to
        params: The POST parameters from the request
        signature: The X-Twilio-Signature header value
        auth_token: Your Twilio Auth Token

    Returns:
        True if signature is valid, False otherwise
    """
    # Build the data string for signature validation
    # Start with the URL
    data = request_url

    # Sort parameters alphabetically by key and append to URL
    if params:
        sorted_params = sorted(params.items())
        for key, value in sorted_params:
            data += str(key) + str(value)

    # Create HMAC-SHA1 hash
    computed_sig = base64.b64encode(
        hmac.new(
            auth_token.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha1
        ).digest()
    ).decode('utf-8')

    # Compare signatures using constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_sig, signature)


def get_twilio_config():
    """Get Twilio configuration from settings store."""
    from core.store import settings_store

    account_sid = settings_store.get('twilio_account_sid', '')
    auth_token = settings_store.get('twilio_auth_token', '')
    whatsapp_number = settings_store.get('twilio_whatsapp_number', '')

    return {
        'account_sid': account_sid,
        'auth_token': auth_token,
        'whatsapp_number': whatsapp_number,
        'configured': bool(account_sid and auth_token and whatsapp_number)
    }


def extract_phone_number(whatsapp_id: str) -> str:
    """
    Extract phone number from WhatsApp ID format.

    Args:
        whatsapp_id: WhatsApp ID like "whatsapp:+1234567890"

    Returns:
        Phone number like "+1234567890"
    """
    if whatsapp_id.startswith("whatsapp:"):
        return whatsapp_id[9:]  # Remove "whatsapp:" prefix
    return whatsapp_id


async def store_whatsapp_message(
    sender: str,
    message_sid: str,
    body: str,
    media_urls: list,
    conversation_id: Optional[str] = None
):
    """
    Store incoming WhatsApp message in database.

    Creates or updates user record and stores the message.
    Links the conversation_id to the user for conversation tracking.

    Args:
        sender: WhatsApp sender ID (e.g., "whatsapp:+1234567890")
        message_sid: Twilio MessageSid
        body: Message text content
        media_urls: List of media URLs
        conversation_id: Optional conversation ID to link to user
    """
    phone_number = extract_phone_number(sender)
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        # Check if user exists
        user_query = select(DBWhatsAppUser).where(DBWhatsAppUser.phone_number == phone_number)
        user_result = conn.execute(user_query)
        user_row = user_result.fetchone()

        if user_row:
            # Update existing user
            user_id = user_row.id
            is_blocked = user_row.is_blocked

            # Check if user is blocked
            if is_blocked:
                logger.info(f"Ignoring message from blocked user: {phone_number}")
                return

            # Build update values
            update_values = {
                'message_count': DBWhatsAppUser.message_count + 1,
                'last_active_at': now,
                'updated_at': now
            }

            # Update conversation_id if provided
            if conversation_id:
                update_values['conversation_id'] = conversation_id

            update_stmt = (
                update(DBWhatsAppUser)
                .where(DBWhatsAppUser.id == user_id)
                .values(**update_values)
            )
            conn.execute(update_stmt)
        else:
            # Create new user
            user_id = str(uuid.uuid4())
            insert_stmt = DBWhatsAppUser.__table__.insert().values(
                id=user_id,
                phone_number=phone_number,
                conversation_id=conversation_id,
                is_blocked=False,
                message_count=1,
                first_seen_at=now,
                last_active_at=now,
                created_at=now,
                updated_at=now
            )
            conn.execute(insert_stmt)

        # Store the message
        message_id = str(uuid.uuid4())
        media_urls_json = json.dumps(media_urls) if media_urls else None

        message_stmt = DBWhatsAppMessage.__table__.insert().values(
            id=message_id,
            user_id=user_id,
            message_sid=message_sid if message_sid else None,
            direction='inbound',
            body=body,
            media_urls=media_urls_json,
            status='received',
            created_at=now
        )
        conn.execute(message_stmt)
        conn.commit()

        logger.info(f"Stored WhatsApp message from {phone_number} (user_id: {user_id}, conversation_id: {conversation_id})")


@router.get("/webhook")
async def webhook_verification(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """
    Handle Twilio webhook verification (GET request).

    Twilio uses this endpoint to verify webhook setup.
    This is called when you configure the webhook URL in the Twilio console.

    Note: Twilio's WhatsApp webhooks don't require challenge-response verification
    like some other platforms, but we support it for flexibility.
    """
    logger.info("WhatsApp webhook GET verification request received")
    logger.info(f"  hub.mode: {hub_mode}")
    logger.info(f"  hub.challenge: {hub_challenge}")
    logger.info(f"  hub.verify_token: {hub_verify_token}")

    # For Twilio, a simple 200 OK response is usually sufficient for verification
    # If this is a verification challenge, return the challenge value
    if hub_challenge:
        logger.info(f"Returning challenge: {hub_challenge}")
        return Response(content=hub_challenge, media_type="text/plain")

    # Standard verification response
    return Response(
        content="WhatsApp webhook endpoint is active",
        media_type="text/plain",
        status_code=200
    )


@router.post("/webhook")
async def webhook_receive(request: Request):
    """
    Handle incoming WhatsApp messages from Twilio.

    This endpoint receives POST requests from Twilio when a WhatsApp message
    is sent to your Twilio WhatsApp number. It:
    1. Validates the Twilio signature for security
    2. Extracts the sender (From), message body (Body), and any media URLs
    3. Logs the incoming message
    4. Returns a TwiML response to acknowledge receipt

    Request Headers:
        X-Twilio-Signature: HMAC-SHA1 signature for validation

    Form Data (from Twilio):
        From: Sender phone number (e.g., "whatsapp:+1234567890")
        To: Your Twilio WhatsApp number
        Body: Message text content
        NumMedia: Number of media attachments
        MediaUrl0, MediaUrl1, ...: URLs of media attachments
        MediaContentType0, ...: MIME types of media attachments
        MessageSid: Unique message identifier
        AccountSid: Your Twilio Account SID

    Returns:
        TwiML response (empty 200 OK to acknowledge receipt)
    """
    # Get Twilio configuration
    config = get_twilio_config()

    if not config['configured']:
        logger.warning("WhatsApp webhook received but Twilio is not configured")
        # Still return 200 to prevent Twilio from retrying
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
            status_code=200
        )

    # Parse form data from request
    try:
        form_data = await request.form()
        params = {key: value for key, value in form_data.items()}
    except Exception as e:
        logger.error(f"Failed to parse form data: {e}")
        params = {}

    # Get Twilio signature from header
    twilio_signature = request.headers.get("X-Twilio-Signature", "")

    # Build the full request URL for signature validation
    # Note: In production, you may need to use X-Forwarded-Proto and X-Forwarded-Host
    # if behind a reverse proxy
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    forwarded_host = request.headers.get("X-Forwarded-Host", request.url.netloc)

    # Construct the URL that Twilio used to sign the request
    request_url = f"{forwarded_proto}://{forwarded_host}{request.url.path}"

    # Validate Twilio signature
    if twilio_signature:
        is_valid = validate_twilio_signature(
            request_url=request_url,
            params=params,
            signature=twilio_signature,
            auth_token=config['auth_token']
        )

        if not is_valid:
            logger.warning(f"Invalid Twilio signature for request from {params.get('From', 'unknown')}")
            logger.warning(f"Request URL used for validation: {request_url}")
            # Return 403 for invalid signature
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    else:
        logger.warning("No X-Twilio-Signature header present - skipping validation")
        # In production, you might want to reject requests without signatures
        # For development/testing, we allow requests without signatures

    # Extract message information
    sender = params.get('From', '')
    recipient = params.get('To', '')
    body = params.get('Body', '')
    message_sid = params.get('MessageSid', '')
    account_sid = params.get('AccountSid', '')

    # Extract media information
    num_media = int(params.get('NumMedia', 0))
    media_urls = []
    media_types = []

    for i in range(num_media):
        media_url = params.get(f'MediaUrl{i}')
        media_type = params.get(f'MediaContentType{i}')
        if media_url:
            media_urls.append(media_url)
            media_types.append(media_type or 'unknown')

    # Log incoming message
    logger.info("=" * 60)
    logger.info("INCOMING WHATSAPP MESSAGE")
    logger.info("=" * 60)
    logger.info(f"  MessageSid: {message_sid}")
    logger.info(f"  From: {sender}")
    logger.info(f"  To: {recipient}")
    logger.info(f"  Body: {body[:100]}{'...' if len(body) > 100 else ''}")
    logger.info(f"  NumMedia: {num_media}")

    if media_urls:
        for i, (url, mtype) in enumerate(zip(media_urls, media_types)):
            logger.info(f"  Media[{i}]: {mtype} - {url}")

    logger.info("=" * 60)

    # Note: We store the message after processing so we can link to conversation_id
    # Process message through RAG and send response (fire-and-forget background task)
    # We return immediately to Twilio but process the response asynchronously
    import asyncio
    from core.database import AsyncSessionLocal

    async def process_and_respond():
        """Background task to process message and send WhatsApp response."""
        try:
            # Create a new database session for the background task
            async with AsyncSessionLocal() as db:
                # Create WhatsApp service with database session
                whatsapp_service = WhatsAppService(db)
                twilio_service = get_twilio_send_service()

                # FEATURE #172: Check if this is a document upload (has media attachments)
                if num_media > 0 and media_urls:
                    logger.info(f"Detected {num_media} media attachment(s) - processing as document upload")

                    # Get the document service
                    doc_service = get_whatsapp_document_service()

                    # FEATURE #173: Get target collection for document upload
                    # This checks: 1) explicit collection in message, 2) user's default collection
                    target_collection = await whatsapp_service.get_target_collection(
                        phone_number=sender,
                        message=body if body.strip() else None
                    )
                    collection_id = target_collection.get("id") if target_collection else None
                    collection_name = target_collection.get("name") if target_collection else None

                    if collection_id:
                        logger.info(f"Document will be saved to collection: {collection_name} (ID: {collection_id})")
                    else:
                        logger.info("No collection specified - document will be uncategorized")

                    # Process each media attachment
                    for i, (media_url, media_type) in enumerate(zip(media_urls, media_types)):
                        logger.info(f"Processing media attachment {i+1}/{num_media}: {media_type}")

                        # Try to extract original filename from the URL or use a default
                        # Twilio URLs don't typically include filenames
                        original_filename = None

                        # Process the document upload with collection
                        upload_result = await doc_service.process_document_upload(
                            media_url=media_url,
                            media_content_type=media_type,
                            original_filename=original_filename,
                            message_text=body if body.strip() else None,  # Use message text as document name
                            phone_number=extract_phone_number(sender),
                            collection_id=collection_id,
                            collection_name=collection_name
                        )

                        # Send response back to user
                        response_text = upload_result.get("message", "")
                        if response_text:
                            send_result = await twilio_service.send_response(
                                phone_number=sender,
                                response=response_text,
                                conversation_id=None
                            )

                            if send_result.get("success"):
                                logger.info(f"Document upload response sent to {sender}")
                            else:
                                logger.error(f"Failed to send document upload response: {send_result.get('errors')}")

                        # Store the message in database for admin dashboard
                        try:
                            await store_whatsapp_message(
                                sender,
                                message_sid,
                                f"[Document Upload] {body}" if body else "[Document Upload]",
                                media_urls,
                                conversation_id=None
                            )
                        except Exception as e:
                            logger.error(f"Failed to store WhatsApp document message: {e}")

                    return  # Don't process through RAG for document uploads

                # Standard text message - process through RAG
                logger.info(f"Processing WhatsApp message from {sender} through RAG...")
                result = await whatsapp_service.process_message(
                    phone_number=sender,
                    message_body=body,
                    message_sid=message_sid
                )

                response_text = result.get("response", "")
                conversation_id = result.get("conversation_id")

                # Store message in database for admin dashboard (with conversation_id link)
                try:
                    await store_whatsapp_message(
                        sender,
                        message_sid,
                        body,
                        media_urls,
                        conversation_id=conversation_id
                    )
                except Exception as e:
                    logger.error(f"Failed to store WhatsApp message: {e}")
                    # Continue even if storage fails

                if response_text:
                    # Send the response back via Twilio
                    send_result = await twilio_service.send_response(
                        phone_number=sender,
                        response=response_text,
                        conversation_id=conversation_id
                    )

                    if send_result.get("success"):
                        logger.info(f"WhatsApp response sent to {sender}: {send_result.get('parts_sent')}/{send_result.get('total_parts')} parts")
                    else:
                        logger.error(f"Failed to send WhatsApp response to {sender}: {send_result.get('errors')}")
                else:
                    logger.warning(f"No response generated for WhatsApp message from {sender}")

        except Exception as e:
            logger.error(f"Error in background WhatsApp processing for {sender}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # Schedule the background task (don't await - let it run in background)
    asyncio.create_task(process_and_respond())

    # Return empty TwiML response to acknowledge receipt immediately
    # This tells Twilio we received the message successfully
    # The response will be sent asynchronously after processing
    twiml_response = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

    return Response(
        content=twiml_response,
        media_type="application/xml",
        status_code=200
    )


@router.get("/status")
async def whatsapp_status():
    """
    Get WhatsApp integration status.

    Returns configuration status and whether the webhook is ready to receive messages.
    """
    config = get_twilio_config()

    return {
        "configured": config['configured'],
        "has_account_sid": bool(config['account_sid']),
        "has_auth_token": bool(config['auth_token']),
        "has_whatsapp_number": bool(config['whatsapp_number']),
        "whatsapp_number": config['whatsapp_number'] if config['whatsapp_number'] else None,
        "webhook_endpoint": "/api/whatsapp/webhook"
    }


# =============================================================================
# WhatsApp RAG Processing Endpoints
# =============================================================================

class ProcessMessageRequest(BaseModel):
    """Request model for processing a WhatsApp message through RAG."""
    phone_number: str = Field(..., description="WhatsApp phone number (e.g., 'whatsapp:+1234567890' or '+1234567890')")
    message: str = Field(..., min_length=1, description="Message text to process")
    message_sid: Optional[str] = Field(None, description="Optional Twilio MessageSid for tracking")


class ProcessMessageResponse(BaseModel):
    """Response model for processed WhatsApp message."""
    response: str = Field(..., description="AI response text (truncated for WhatsApp if needed)")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for this phone number")
    was_truncated: bool = Field(..., description="Whether the response was truncated to fit WhatsApp limit")
    original_length: int = Field(..., description="Original response length before truncation")
    truncated_length: int = Field(..., description="Final response length after truncation")
    tool_used: Optional[str] = Field(None, description="Tool used by AI (if any)")
    response_source: Optional[str] = Field(None, description="Source: 'rag', 'direct', 'hybrid', or 'error'")


@router.post("/process", response_model=ProcessMessageResponse)
async def process_whatsapp_message(
    request: ProcessMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Process a WhatsApp message through the RAG pipeline.

    This endpoint:
    1. Maps the phone number to a virtual conversation (creates if needed)
    2. Saves the user message to conversation history
    3. Processes the message through the AI/RAG pipeline
    4. Truncates the response if > 1600 chars (WhatsApp limit)
    5. Saves the assistant response to conversation history
    6. Returns the response ready to send via WhatsApp

    The conversation history is maintained per phone number, so users can
    have contextual conversations across multiple messages.

    Args:
        request: ProcessMessageRequest with phone_number and message

    Returns:
        ProcessMessageResponse with AI response and metadata
    """
    logger.info(f"Processing WhatsApp message for {request.phone_number}")

    # Create WhatsApp service with database session
    whatsapp_service = WhatsAppService(db)

    # Process the message through RAG
    result = await whatsapp_service.process_message(
        phone_number=request.phone_number,
        message_body=request.message,
        message_sid=request.message_sid
    )

    return ProcessMessageResponse(
        response=result["response"],
        conversation_id=result.get("conversation_id"),
        was_truncated=result.get("was_truncated", False),
        original_length=result.get("original_length", len(result["response"])),
        truncated_length=result.get("truncated_length", len(result["response"])),
        tool_used=result.get("tool_used"),
        response_source=result.get("response_source")
    )


@router.get("/conversation/{phone_number}")
async def get_whatsapp_conversation(
    phone_number: str,
    limit: int = Query(20, ge=1, le=100, description="Maximum messages to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get conversation history for a WhatsApp phone number.

    Args:
        phone_number: WhatsApp phone number (with or without 'whatsapp:' prefix)
        limit: Maximum number of messages to return (default 20, max 100)

    Returns:
        List of messages with role, content, and timestamp
    """
    whatsapp_service = WhatsAppService(db)
    history = await whatsapp_service.get_conversation_history(phone_number, limit)

    return {
        "phone_number": phone_number,
        "message_count": len(history),
        "messages": history
    }


# =============================================================================
# WhatsApp Send Endpoints
# =============================================================================

class SendMessageRequest(BaseModel):
    """Request model for sending a WhatsApp message."""
    to: str = Field(..., description="Recipient phone number (e.g., '+1234567890' or 'whatsapp:+1234567890')")
    body: str = Field(..., min_length=1, description="Message text to send")
    split_if_needed: bool = Field(True, description="Whether to split long messages into multiple parts")


class SendMessageResponse(BaseModel):
    """Response model for sent WhatsApp message."""
    success: bool = Field(..., description="Whether all message parts were sent successfully")
    parts_sent: int = Field(..., description="Number of message parts sent")
    total_parts: int = Field(..., description="Total number of message parts")
    message_sids: List[str] = Field(..., description="List of Twilio message SIDs for sent parts")
    statuses: List[str] = Field(..., description="List of delivery statuses for each part")
    errors: List[str] = Field(default_factory=list, description="List of any errors encountered")
    to: str = Field(..., description="Formatted recipient number")
    original_length: int = Field(..., description="Original message length before splitting")


@router.post("/send", response_model=SendMessageResponse)
async def send_whatsapp_message(request: SendMessageRequest):
    """
    Send a WhatsApp message via Twilio.

    This endpoint sends a message directly to a WhatsApp number without going
    through the RAG pipeline. Useful for testing or sending notifications.

    If the message exceeds 1600 characters, it will be automatically split into
    multiple parts with part indicators (e.g., "[1/3] message content...").

    The endpoint includes retry logic with exponential backoff for failed sends.

    Args:
        request: SendMessageRequest with recipient and message body

    Returns:
        SendMessageResponse with send results and message SIDs
    """
    logger.info(f"Send WhatsApp message request to {request.to}")

    twilio_service = get_twilio_send_service()

    if not twilio_service.is_configured():
        return SendMessageResponse(
            success=False,
            parts_sent=0,
            total_parts=0,
            message_sids=[],
            statuses=[],
            errors=["Twilio WhatsApp is not configured. Please configure credentials in Settings."],
            to=request.to,
            original_length=len(request.body)
        )

    result = await twilio_service.send_message(
        to=request.to,
        body=request.body,
        split_if_needed=request.split_if_needed
    )

    return SendMessageResponse(
        success=result.get("success", False),
        parts_sent=result.get("parts_sent", 0),
        total_parts=result.get("total_parts", 0),
        message_sids=result.get("message_sids", []),
        statuses=result.get("statuses", []),
        errors=result.get("errors", []),
        to=result.get("to", request.to),
        original_length=result.get("original_length", len(request.body))
    )


@router.post("/process-and-send", response_model=SendMessageResponse)
async def process_and_send_whatsapp(
    request: ProcessMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Process a WhatsApp message through RAG and send the response via Twilio.

    This endpoint combines the /process and /send endpoints into a single call.
    It processes the incoming message through the RAG pipeline and immediately
    sends the response back to the sender via Twilio WhatsApp.

    Args:
        request: ProcessMessageRequest with phone_number and message

    Returns:
        SendMessageResponse with send results
    """
    logger.info(f"Process and send WhatsApp message for {request.phone_number}")

    # First, process through RAG
    whatsapp_service = WhatsAppService(db)
    rag_result = await whatsapp_service.process_message(
        phone_number=request.phone_number,
        message_body=request.message,
        message_sid=request.message_sid
    )

    response_text = rag_result.get("response", "")
    conversation_id = rag_result.get("conversation_id")

    if not response_text:
        return SendMessageResponse(
            success=False,
            parts_sent=0,
            total_parts=0,
            message_sids=[],
            statuses=[],
            errors=["No response generated from RAG pipeline"],
            to=request.phone_number,
            original_length=0
        )

    # Now send the response
    twilio_service = get_twilio_send_service()

    if not twilio_service.is_configured():
        return SendMessageResponse(
            success=False,
            parts_sent=0,
            total_parts=0,
            message_sids=[],
            statuses=[],
            errors=["Twilio WhatsApp is not configured. RAG response was generated but could not be sent."],
            to=request.phone_number,
            original_length=len(response_text)
        )

    send_result = await twilio_service.send_response(
        phone_number=request.phone_number,
        response=response_text,
        conversation_id=conversation_id
    )

    return SendMessageResponse(
        success=send_result.get("success", False),
        parts_sent=send_result.get("parts_sent", 0),
        total_parts=send_result.get("total_parts", 0),
        message_sids=send_result.get("message_sids", []),
        statuses=send_result.get("statuses", []),
        errors=send_result.get("errors", []),
        to=send_result.get("to", request.phone_number),
        original_length=send_result.get("original_length", len(response_text))
    )


@router.get("/send-status")
async def get_send_status():
    """
    Get the status of the WhatsApp send service.

    Returns whether Twilio is properly configured for sending WhatsApp messages.
    """
    twilio_service = get_twilio_send_service()
    config = get_twilio_config()

    return {
        "configured": twilio_service.is_configured(),
        "has_account_sid": bool(config['account_sid']),
        "has_auth_token": bool(config['auth_token']),
        "has_whatsapp_number": bool(config['whatsapp_number']),
        "from_number": twilio_service.from_number if twilio_service.is_configured() else None
    }


# =============================================================================
# WhatsApp Conversation Management Endpoints
# =============================================================================

class ResetConversationRequest(BaseModel):
    """Request model for resetting a WhatsApp conversation."""
    phone_number: str = Field(..., description="WhatsApp phone number (e.g., '+1234567890' or 'whatsapp:+1234567890')")


class ResetConversationResponse(BaseModel):
    """Response model for conversation reset."""
    success: bool = Field(..., description="Whether the reset was successful")
    phone_number: str = Field(..., description="Normalized phone number")
    old_conversation_id: Optional[str] = Field(None, description="ID of archived conversation (if any)")
    new_conversation_id: str = Field(..., description="ID of the new conversation")
    message: str = Field(..., description="Status message")


@router.post("/reset-conversation", response_model=ResetConversationResponse)
async def reset_whatsapp_conversation(
    request: ResetConversationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset a WhatsApp conversation for a phone number.

    Archives the current conversation and creates a new one.
    This is the same as the user sending 'reset' or 'nuova chat'.

    Args:
        request: ResetConversationRequest with phone_number

    Returns:
        ResetConversationResponse with old and new conversation IDs
    """
    logger.info(f"API request to reset WhatsApp conversation for {request.phone_number}")

    whatsapp_service = WhatsAppService(db)

    # Get current conversation ID before reset
    old_conversation = None
    normalized_phone = whatsapp_service._normalize_phone_number(request.phone_number)

    try:
        # Check for existing user with conversation
        user = await whatsapp_service._get_whatsapp_user(normalized_phone)
        old_conversation_id = user.conversation_id if user else None

        # Perform the reset
        new_conversation = await whatsapp_service.reset_conversation(request.phone_number)

        return ResetConversationResponse(
            success=True,
            phone_number=normalized_phone,
            old_conversation_id=old_conversation_id,
            new_conversation_id=new_conversation.id,
            message=f"Conversation reset successfully. Old conversation archived, new conversation created."
        )
    except Exception as e:
        logger.error(f"Failed to reset WhatsApp conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commands")
async def get_whatsapp_commands():
    """
    Get list of available WhatsApp commands.

    Returns the commands that users can send to control their WhatsApp conversation.
    """
    return {
        "commands": [
            {
                "keywords": ["reset", "nuova chat", "nuova conversazione", "ricomincia", "restart", "new chat"],
                "description": "Start a fresh conversation (archives the current one)",
                "example": "reset"
            },
            {
                "keywords": ["help", "aiuto", "comandi", "commands", "?"],
                "description": "Show available commands and usage instructions",
                "example": "help"
            },
            {
                "keywords": ["collezioni", "collections", "/collection", "/collezioni", "cartelle", "folders"],
                "description": "List all available collections",
                "example": "collezioni"
            },
            {
                "keywords": ["setcollezione", "setcollection", "/setcollection", "/setcollezione", "usa collezione", "usa cartella"],
                "description": "Set default collection for document uploads",
                "example": "setcollezione Normative Nautiche"
            },
            {
                "keywords": ["/documenti", "/documents", "/docs", "/list", "documenti", "documents", "miei documenti"],
                "description": "List your uploaded documents. Optionally filter by collection name.",
                "example": "documenti",
                "example_with_filter": "documenti Normative"
            },
            {
                "keywords": ["/elimina", "/delete", "elimina", "delete", "cancella", "rimuovi"],
                "description": "Delete a document you uploaded (requires document name)",
                "example": "/elimina Nome Documento"
            }
        ],
        "notes": {
            "conversation_expiry": "Conversations are automatically archived after 24 hours of inactivity",
            "context_preserved": "Message history is preserved within the conversation for context",
            "document_upload": "Send a document (PDF, Word, Excel, CSV, JSON, TXT, Markdown) to upload it to the system",
            "collection_selection": "Specify collection in message (e.g., 'salva in Normative') or set a default with 'setcollezione'",
            "document_listing": "List shows name, type, date, and collection. Use 'documenti <collection>' to filter by collection."
        }
    }


# =============================================================================
# WhatsApp Collection Management Endpoints (Feature #173)
# =============================================================================

class SetDefaultCollectionRequest(BaseModel):
    """Request model for setting a user's default collection."""
    phone_number: str = Field(..., description="WhatsApp phone number (e.g., '+1234567890' or 'whatsapp:+1234567890')")
    collection_name: str = Field(..., description="Name of the collection to set as default")


class SetDefaultCollectionResponse(BaseModel):
    """Response model for setting default collection."""
    success: bool = Field(..., description="Whether the operation was successful")
    phone_number: str = Field(..., description="Normalized phone number")
    collection_id: Optional[str] = Field(None, description="ID of the collection")
    collection_name: Optional[str] = Field(None, description="Name of the collection")
    created_new: bool = Field(..., description="Whether a new collection was created")
    message: str = Field(..., description="Status message")


class UserCollectionInfoResponse(BaseModel):
    """Response model for user's collection info."""
    phone_number: str = Field(..., description="Normalized phone number")
    has_default_collection: bool = Field(..., description="Whether user has a default collection set")
    default_collection_id: Optional[str] = Field(None, description="ID of the default collection")
    default_collection_name: Optional[str] = Field(None, description="Name of the default collection")


@router.get("/user/{phone_number}/collection", response_model=UserCollectionInfoResponse)
async def get_user_default_collection(
    phone_number: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a WhatsApp user's default collection for document uploads.

    Args:
        phone_number: WhatsApp phone number (with or without 'whatsapp:' prefix)

    Returns:
        UserCollectionInfoResponse with collection info
    """
    whatsapp_service = WhatsAppService(db)
    normalized_phone = whatsapp_service._normalize_phone_number(phone_number)

    default_collection = await whatsapp_service.get_user_default_collection(phone_number)

    return UserCollectionInfoResponse(
        phone_number=normalized_phone,
        has_default_collection=default_collection is not None,
        default_collection_id=default_collection.id if default_collection else None,
        default_collection_name=default_collection.name if default_collection else None
    )


@router.post("/user/set-collection", response_model=SetDefaultCollectionResponse)
async def set_user_default_collection(
    request: SetDefaultCollectionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Set a WhatsApp user's default collection for document uploads.

    If the collection doesn't exist and auto-create is enabled (default),
    a new collection will be created.

    Args:
        request: SetDefaultCollectionRequest with phone_number and collection_name

    Returns:
        SetDefaultCollectionResponse with operation result
    """
    logger.info(f"API request to set default collection for {request.phone_number}: {request.collection_name}")

    whatsapp_service = WhatsAppService(db)
    result = await whatsapp_service.handle_set_collection(
        phone_number=request.phone_number,
        collection_name=request.collection_name
    )

    # Parse result for API response
    success = result.get("response_source") == "command" and "Errore" not in result.get("response", "")
    normalized_phone = whatsapp_service._normalize_phone_number(request.phone_number)

    # Try to get collection info
    collection_info = await whatsapp_service.get_user_default_collection(request.phone_number)

    return SetDefaultCollectionResponse(
        success=success,
        phone_number=normalized_phone,
        collection_id=collection_info.id if collection_info else None,
        collection_name=collection_info.name if collection_info else None,
        created_new="creata" in result.get("response", "").lower(),
        message=result.get("response", "")
    )


# =============================================================================
# WhatsApp Document Upload Endpoints (Feature #172)
# =============================================================================

@router.get("/document-formats")
async def get_supported_document_formats():
    """
    Get list of supported document formats for WhatsApp upload.

    Returns the file types that can be uploaded via WhatsApp.
    """
    from services.whatsapp_document_service import SUPPORTED_MIME_TYPES, WHATSAPP_MAX_FILE_SIZE

    formats = []
    for mime_type, ext in SUPPORTED_MIME_TYPES.items():
        friendly_names = {
            "application/pdf": "PDF Document",
            "text/plain": "Plain Text",
            "text/csv": "CSV Spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel Spreadsheet (.xlsx)",
            "application/vnd.ms-excel": "Excel Spreadsheet (.xls)",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word Document",
            "application/json": "JSON Data",
            "text/markdown": "Markdown Document",
        }
        formats.append({
            "mime_type": mime_type,
            "extension": f".{ext}",
            "name": friendly_names.get(mime_type, ext.upper())
        })

    return {
        "supported_formats": formats,
        "max_file_size_bytes": WHATSAPP_MAX_FILE_SIZE,
        "max_file_size_mb": WHATSAPP_MAX_FILE_SIZE / (1024 * 1024),
        "notes": {
            "naming": "Include a message with your document to set its name, otherwise the filename will be used",
            "structured_data": "CSV, Excel, and JSON files are processed as tabular data for SQL queries",
            "unstructured_data": "PDF, Word, TXT, and Markdown files are processed for semantic search"
        }
    }


class DocumentUploadTestRequest(BaseModel):
    """Request model for testing document upload via URL."""
    media_url: str = Field(..., description="URL of the media file to download")
    media_content_type: str = Field(..., description="MIME type of the media file")
    original_filename: Optional[str] = Field(None, description="Original filename")
    document_name: Optional[str] = Field(None, description="Custom document name")
    phone_number: Optional[str] = Field(None, description="Phone number for attribution")


class DocumentUploadTestResponse(BaseModel):
    """Response model for document upload test."""
    success: bool
    message: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    error_type: Optional[str] = None


@router.post("/test-document-upload", response_model=DocumentUploadTestResponse)
async def test_document_upload(request: DocumentUploadTestRequest):
    """
    Test document upload functionality with a URL.

    This endpoint allows testing the document upload pipeline without
    going through the actual WhatsApp webhook. Useful for development
    and debugging.

    Note: For Twilio media URLs, you need valid Twilio credentials configured.
    """
    logger.info(f"Test document upload request: {request.media_url}")

    doc_service = get_whatsapp_document_service()

    result = await doc_service.process_document_upload(
        media_url=request.media_url,
        media_content_type=request.media_content_type,
        original_filename=request.original_filename,
        message_text=request.document_name,
        phone_number=request.phone_number
    )

    return DocumentUploadTestResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        document_id=result.get("document_id"),
        document_name=result.get("document_name"),
        error_type=result.get("error_type")
    )
