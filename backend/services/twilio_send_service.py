"""
Twilio Send Service for sending WhatsApp responses.

This service handles:
- Sending WhatsApp messages via Twilio API
- Splitting long messages into multiple parts (max 1600 chars each)
- Retry logic for failed sends
- Logging sent messages and delivery status
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
import uuid
import json

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from core.store import settings_store

logger = logging.getLogger(__name__)

# WhatsApp message length limit
WHATSAPP_MAX_LENGTH = 1600

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 1  # seconds
RETRY_MAX_WAIT = 10  # seconds


def get_twilio_client() -> Optional[Client]:
    """
    Get configured Twilio client from settings.

    Returns:
        Twilio Client if configured, None otherwise
    """
    account_sid = settings_store.get('twilio_account_sid', '')
    auth_token = settings_store.get('twilio_auth_token', '')

    if not account_sid or not auth_token:
        logger.warning("Twilio credentials not configured")
        return None

    return Client(account_sid, auth_token)


def get_twilio_whatsapp_number() -> Optional[str]:
    """
    Get the configured Twilio WhatsApp number.

    Returns:
        WhatsApp number in format "whatsapp:+14155238886" or None if not configured
    """
    whatsapp_number = settings_store.get('twilio_whatsapp_number', '')

    if not whatsapp_number:
        return None

    # Ensure proper WhatsApp format
    if not whatsapp_number.startswith('whatsapp:'):
        whatsapp_number = f'whatsapp:{whatsapp_number}'

    return whatsapp_number


def format_recipient(phone_number: str) -> str:
    """
    Format recipient phone number for WhatsApp.

    Args:
        phone_number: Phone number (e.g., "+1234567890" or "whatsapp:+1234567890")

    Returns:
        Formatted number like "whatsapp:+1234567890"
    """
    # Remove whatsapp: prefix if present (we'll add it back)
    if phone_number.startswith('whatsapp:'):
        phone_number = phone_number[9:]

    phone_number = phone_number.strip()

    # Ensure + prefix
    if not phone_number.startswith('+'):
        phone_number = f'+{phone_number}'

    return f'whatsapp:{phone_number}'


def split_message(text: str, max_length: int = WHATSAPP_MAX_LENGTH) -> List[str]:
    """
    Split a long message into multiple parts that fit WhatsApp's limit.

    The function attempts to split at natural break points (sentences, newlines, spaces)
    rather than cutting words in half.

    Args:
        text: The full message text to split
        max_length: Maximum length per message (default 1600)

    Returns:
        List of message parts, each within the length limit
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    remaining = text
    part_num = 1

    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break

        # Reserve space for part indicator (e.g., "[1/3] " = 6 chars max for "[99/99] ")
        content_max = max_length - 10  # Leave room for part indicator

        # Find the best break point
        chunk = remaining[:content_max]

        # Try to find a sentence boundary (., !, ?)
        sentence_breaks = []
        for punct in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            idx = chunk.rfind(punct)
            if idx > content_max * 0.5:  # Must be past halfway
                sentence_breaks.append(idx + len(punct) - 1)

        if sentence_breaks:
            break_point = max(sentence_breaks)
        else:
            # Try paragraph break
            para_break = chunk.rfind('\n\n')
            if para_break > content_max * 0.5:
                break_point = para_break + 2
            else:
                # Try line break
                line_break = chunk.rfind('\n')
                if line_break > content_max * 0.5:
                    break_point = line_break + 1
                else:
                    # Try space
                    space_break = chunk.rfind(' ')
                    if space_break > content_max * 0.5:
                        break_point = space_break + 1
                    else:
                        # Hard cut at max length
                        break_point = content_max

        part_content = remaining[:break_point].rstrip()
        parts.append(part_content)
        remaining = remaining[break_point:].lstrip()
        part_num += 1

    # Add part indicators if multiple parts
    if len(parts) > 1:
        total = len(parts)
        parts = [f"[{i+1}/{total}] {part}" for i, part in enumerate(parts)]

    return parts


class TwilioSendService:
    """
    Service for sending WhatsApp messages via Twilio.

    Handles message sending, splitting long messages, retries, and logging.
    """

    def __init__(self):
        """Initialize the Twilio send service."""
        self._client = None
        self._from_number = None

    @property
    def client(self) -> Optional[Client]:
        """Get Twilio client (lazy initialization)."""
        if self._client is None:
            self._client = get_twilio_client()
        return self._client

    @property
    def from_number(self) -> Optional[str]:
        """Get the WhatsApp sender number."""
        if self._from_number is None:
            self._from_number = get_twilio_whatsapp_number()
        return self._from_number

    def is_configured(self) -> bool:
        """Check if Twilio is properly configured."""
        return self.client is not None and self.from_number is not None

    def _send_single_message_sync(
        self,
        to: str,
        body: str
    ) -> Dict[str, Any]:
        """
        Send a single WhatsApp message via Twilio (synchronous).

        This is the actual Twilio API call, wrapped with retry logic.

        Args:
            to: Recipient phone number (whatsapp:+1234567890)
            body: Message content

        Returns:
            Dict with message_sid, status, etc.

        Raises:
            TwilioRestException: If sending fails after retries
        """
        if not self.client:
            raise ValueError("Twilio client not configured")

        if not self.from_number:
            raise ValueError("Twilio WhatsApp number not configured")

        # Use tenacity for retry logic
        @retry(
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
            wait=wait_exponential(
                multiplier=1,
                min=RETRY_MIN_WAIT,
                max=RETRY_MAX_WAIT
            ),
            retry=retry_if_exception_type((TwilioRestException,)),
            before_sleep=before_sleep_log(logger, logging.WARNING)
        )
        def _send_with_retry():
            return self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to
            )

        try:
            message = _send_with_retry()

            result = {
                'success': True,
                'message_sid': message.sid,
                'status': message.status,
                'to': to,
                'from': self.from_number,
                'body_length': len(body),
                'date_created': message.date_created.isoformat() if message.date_created else None,
                'error_code': None,
                'error_message': None
            }

            logger.info(f"WhatsApp message sent: SID={message.sid}, Status={message.status}, To={to}")

            return result

        except TwilioRestException as e:
            logger.error(f"Failed to send WhatsApp message to {to}: {e.code} - {e.msg}")

            return {
                'success': False,
                'message_sid': None,
                'status': 'failed',
                'to': to,
                'from': self.from_number,
                'body_length': len(body),
                'date_created': None,
                'error_code': e.code,
                'error_message': e.msg
            }

    async def send_message(
        self,
        to: str,
        body: str,
        split_if_needed: bool = True
    ) -> Dict[str, Any]:
        """
        Send a WhatsApp message, splitting into multiple parts if needed.

        Args:
            to: Recipient phone number (with or without whatsapp: prefix)
            body: Full message content
            split_if_needed: Whether to split long messages (default True)

        Returns:
            Dict with:
                - success: Whether all parts sent successfully
                - parts_sent: Number of message parts sent
                - total_parts: Total number of parts
                - message_sids: List of Twilio message SIDs
                - statuses: List of delivery statuses
                - errors: List of any errors encountered
        """
        if not self.is_configured():
            logger.error("Cannot send WhatsApp message: Twilio not configured")
            return {
                'success': False,
                'parts_sent': 0,
                'total_parts': 0,
                'message_sids': [],
                'statuses': [],
                'errors': ['Twilio WhatsApp not configured'],
                'to': to,
                'original_length': len(body)
            }

        # Format recipient
        formatted_to = format_recipient(to)

        # Split message if needed
        if split_if_needed:
            parts = split_message(body)
        else:
            parts = [body]

        total_parts = len(parts)
        results = []
        errors = []

        logger.info("=" * 60)
        logger.info("SENDING WHATSAPP MESSAGE")
        logger.info("=" * 60)
        logger.info(f"  To: {formatted_to}")
        logger.info(f"  Original length: {len(body)} chars")
        logger.info(f"  Parts: {total_parts}")

        # Send each part
        for i, part in enumerate(parts):
            logger.info(f"  Sending part {i+1}/{total_parts} ({len(part)} chars)")

            # Run sync Twilio call in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._send_single_message_sync,
                formatted_to,
                part
            )

            results.append(result)

            if not result['success']:
                error_msg = f"Part {i+1}: {result.get('error_code')} - {result.get('error_message')}"
                errors.append(error_msg)
                logger.error(f"  Failed: {error_msg}")
            else:
                logger.info(f"  Sent: SID={result['message_sid']}")

            # Small delay between parts to maintain order
            if i < len(parts) - 1:
                await asyncio.sleep(0.5)

        parts_sent = sum(1 for r in results if r['success'])
        all_success = parts_sent == total_parts

        logger.info("=" * 60)
        logger.info(f"WHATSAPP SEND COMPLETE: {parts_sent}/{total_parts} parts sent")
        logger.info("=" * 60)

        return {
            'success': all_success,
            'parts_sent': parts_sent,
            'total_parts': total_parts,
            'message_sids': [r['message_sid'] for r in results if r['message_sid']],
            'statuses': [r['status'] for r in results],
            'errors': errors,
            'to': formatted_to,
            'original_length': len(body),
            'results': results
        }

    async def send_response(
        self,
        phone_number: str,
        response: str,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a RAG response back to a WhatsApp user.

        This is the main method to be called after processing a message.
        It handles formatting, splitting, sending, and logging.

        Args:
            phone_number: User's phone number
            response: The AI-generated response to send
            conversation_id: Optional conversation ID for logging

        Returns:
            Dict with send results
        """
        logger.info(f"Sending WhatsApp response to {phone_number} (conversation: {conversation_id})")

        result = await self.send_message(to=phone_number, body=response)

        # Add conversation ID to result for tracking
        result['conversation_id'] = conversation_id

        # Log the send operation
        self._log_send_operation(
            phone_number=phone_number,
            response=response,
            result=result,
            conversation_id=conversation_id
        )

        return result

    def _log_send_operation(
        self,
        phone_number: str,
        response: str,
        result: Dict[str, Any],
        conversation_id: Optional[str] = None
    ):
        """
        Log the send operation details for audit/debugging.

        Args:
            phone_number: Recipient phone
            response: Original response text
            result: Send result dict
            conversation_id: Optional conversation ID
        """
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'operation': 'whatsapp_send',
            'phone_number': phone_number,
            'conversation_id': conversation_id,
            'response_length': len(response),
            'parts_sent': result.get('parts_sent', 0),
            'total_parts': result.get('total_parts', 0),
            'success': result.get('success', False),
            'message_sids': result.get('message_sids', []),
            'errors': result.get('errors', [])
        }

        if result.get('success'):
            logger.info(f"WhatsApp send logged: {json.dumps(log_entry)}")
        else:
            logger.error(f"WhatsApp send failed: {json.dumps(log_entry)}")


# Singleton instance for convenience
_twilio_send_service: Optional[TwilioSendService] = None


def get_twilio_send_service() -> TwilioSendService:
    """Get the singleton TwilioSendService instance."""
    global _twilio_send_service
    if _twilio_send_service is None:
        _twilio_send_service = TwilioSendService()
    return _twilio_send_service
