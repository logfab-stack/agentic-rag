"""
Telegram Send Service for sending messages back to Telegram users via Bot API.

Feature #310: Telegram send message service
Feature #341: Fix Telegram message Markdown parsing errors

This service handles:
- Sending text messages via Telegram Bot API
- Markdown/HTML formatting support
- Reply to message threading
- Inline keyboards for interactive responses
- Sending documents/files back to users
- Error handling for common Telegram API errors
- Retry logic for transient failures
- Markdown sanitization to prevent parsing errors (Feature #341)
"""

import logging
import asyncio
import re
from typing import Optional, Dict, Any, List, Union, Tuple
from datetime import datetime, timezone
import json

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from core.store import settings_store

logger = logging.getLogger(__name__)

# Telegram API configuration
TELEGRAM_API_BASE = "https://api.telegram.org/bot"

# Telegram message length limit (UTF-8 characters)
TELEGRAM_MAX_LENGTH = 4096

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 1  # seconds
RETRY_MAX_WAIT = 10  # seconds

# Telegram API error codes
class TelegramErrorCodes:
    """Common Telegram Bot API error codes."""
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    TOO_MANY_REQUESTS = 429

    # Specific error descriptions
    CHAT_NOT_FOUND = "chat not found"
    BOT_BLOCKED = "bot was blocked by the user"
    USER_DEACTIVATED = "user is deactivated"
    CHAT_WRITE_FORBIDDEN = "have no rights to send a message"
    MESSAGE_TOO_LONG = "message is too long"


class TelegramAPIError(Exception):
    """Custom exception for Telegram API errors."""

    def __init__(self, status_code: int, error_code: int, description: str):
        self.status_code = status_code
        self.error_code = error_code
        self.description = description
        super().__init__(f"Telegram API Error {error_code}: {description}")


def get_telegram_bot_token() -> Optional[str]:
    """
    Get the configured Telegram Bot Token from settings.

    Returns:
        Bot token string if configured, None otherwise
    """
    token = settings_store.get('telegram_bot_token', '')

    if not token:
        logger.warning("Telegram Bot Token not configured")
        return None

    return token


# =============================================================================
# Feature #341: Markdown Sanitization for Telegram API
# =============================================================================

def count_marker_occurrences(text: str, marker: str) -> int:
    """
    Count occurrences of a Markdown marker, accounting for escaped characters.

    Args:
        text: The text to search
        marker: The marker to count (e.g., '*', '**', '`', '```')

    Returns:
        Count of unescaped marker occurrences
    """
    # Remove escaped markers first
    cleaned = text.replace(f'\\{marker}', '')
    return cleaned.count(marker)


def fix_unclosed_markers(text: str) -> str:
    """
    Fix unclosed Markdown markers by adding closing markers at the end.

    Handles:
    - ``` (code blocks)
    - ` (inline code)
    - ** (bold)
    - * (italic)
    - __ (underline - Telegram Markdown)
    - _ (italic alternative)

    Args:
        text: The text with potential unclosed markers

    Returns:
        Text with balanced markers
    """
    result = text

    # Fix code blocks (```) first - they're most likely to cause issues
    # Count triple backticks
    code_block_count = len(re.findall(r'(?<!`)```(?!`)', result))
    if code_block_count % 2 != 0:
        # Odd number - add closing triple backtick
        result = result.rstrip() + '\n```'
        logger.debug("Fixed unclosed ``` code block")

    # Fix inline code (`) - but not triple backticks
    # This is tricky because ` inside ``` should be ignored
    # Split by code blocks and only count single backticks outside them
    parts = re.split(r'(```[\s\S]*?```)', result)
    fixed_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Not a code block
            # Count single backticks (not part of triple)
            single_count = len(re.findall(r'(?<!`)`(?!`)', part))
            if single_count % 2 != 0:
                # Odd number - add closing backtick at end of this part
                part = part.rstrip() + '`'
                logger.debug("Fixed unclosed ` inline code")
        fixed_parts.append(part)
    result = ''.join(fixed_parts)

    # Fix bold (**) - count pairs
    # Split by code to avoid counting ** in code
    parts = re.split(r'(```[\s\S]*?```|`[^`]*`)', result)
    fixed_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Not inside code
            bold_count = len(re.findall(r'(?<!\*)\*\*(?!\*)', part))
            if bold_count % 2 != 0:
                part = part.rstrip() + '**'
                logger.debug("Fixed unclosed ** bold")
        fixed_parts.append(part)
    result = ''.join(fixed_parts)

    # Fix italic (*) - excluding **
    parts = re.split(r'(```[\s\S]*?```|`[^`]*`|\*\*[^*]*\*\*)', result)
    fixed_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # Not inside code or bold
            italic_count = len(re.findall(r'(?<!\*)\*(?!\*)', part))
            if italic_count % 2 != 0:
                part = part.rstrip() + '*'
                logger.debug("Fixed unclosed * italic")
        fixed_parts.append(part)
    result = ''.join(fixed_parts)

    # Fix underline (__) - Telegram Markdown specific
    parts = re.split(r'(```[\s\S]*?```|`[^`]*`)', result)
    fixed_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            underline_count = len(re.findall(r'(?<!_)__(?!_)', part))
            if underline_count % 2 != 0:
                part = part.rstrip() + '__'
                logger.debug("Fixed unclosed __ underline")
        fixed_parts.append(part)
    result = ''.join(fixed_parts)

    # Fix italic (_) - excluding __
    parts = re.split(r'(```[\s\S]*?```|`[^`]*`|__[^_]*__)', result)
    fixed_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            italic_underscore_count = len(re.findall(r'(?<!_)_(?!_)', part))
            if italic_underscore_count % 2 != 0:
                part = part.rstrip() + '_'
                logger.debug("Fixed unclosed _ italic")
        fixed_parts.append(part)
    result = ''.join(fixed_parts)

    return result


def sanitize_telegram_markdown(text: str) -> Tuple[str, bool]:
    """
    Sanitize text to be safe for Telegram Markdown parsing.

    This function:
    1. Fixes unclosed formatting markers (*, **, `, ```, _, __)
    2. Removes problematic nested formatting
    3. Returns whether sanitization was applied

    Args:
        text: Raw text that may contain malformed Markdown

    Returns:
        Tuple of (sanitized_text, was_modified)
    """
    if not text:
        return text, False

    original = text
    sanitized = fix_unclosed_markers(text)

    # Check if we had to make changes
    was_modified = sanitized != original

    if was_modified:
        logger.info(f"Markdown sanitized: fixed unclosed markers (original={len(original)} chars, sanitized={len(sanitized)} chars)")

    return sanitized, was_modified


def strip_markdown_formatting(text: str) -> str:
    """
    Remove all Markdown formatting from text, returning plain text.

    Used as a fallback when Markdown parsing fails even after sanitization.

    Args:
        text: Text with Markdown formatting

    Returns:
        Plain text without Markdown markers
    """
    if not text:
        return text

    result = text

    # Remove code blocks but preserve content
    result = re.sub(r'```(?:\w+)?\n?([\s\S]*?)```', r'\1', result)

    # Remove inline code markers but preserve content
    result = re.sub(r'`([^`]+)`', r'\1', result)

    # Remove bold markers
    result = re.sub(r'\*\*([^*]+)\*\*', r'\1', result)

    # Remove italic markers (*)
    result = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', result)

    # Remove underline markers (__)
    result = re.sub(r'__([^_]+)__', r'\1', result)

    # Remove italic markers (_)
    result = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', result)

    # Remove strikethrough (~)
    result = re.sub(r'~~([^~]+)~~', r'\1', result)
    result = re.sub(r'~([^~]+)~', r'\1', result)

    # Remove link formatting but keep text
    result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)

    # Remove any remaining single markers that might cause issues
    # (Be careful not to remove legitimate use in text)

    logger.info(f"Stripped Markdown formatting: {len(text)} -> {len(result)} chars")

    return result


def split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> List[str]:
    """
    Split a long message into multiple parts that fit Telegram's limit.

    The function attempts to split at natural break points (sentences, newlines, spaces)
    rather than cutting words in half.

    Args:
        text: The full message text to split
        max_length: Maximum length per message (default 4096)

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

        # Reserve space for part indicator (e.g., "[1/3] " = 8 chars max)
        content_max = max_length - 10

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


def build_inline_keyboard(buttons: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    """
    Build an inline keyboard markup for interactive responses.

    Args:
        buttons: 2D list of button definitions. Each button is a dict with:
            - text: Button label
            - callback_data: Data sent back when button is pressed (optional)
            - url: URL to open when button is pressed (optional)

    Returns:
        InlineKeyboardMarkup dict for Telegram API

    Example:
        buttons = [
            [{"text": "Option 1", "callback_data": "opt1"}, {"text": "Option 2", "callback_data": "opt2"}],
            [{"text": "Visit Website", "url": "https://example.com"}]
        ]
    """
    inline_keyboard = []

    for row in buttons:
        keyboard_row = []
        for btn in row:
            button = {"text": btn.get("text", "")}
            if "callback_data" in btn:
                button["callback_data"] = btn["callback_data"]
            elif "url" in btn:
                button["url"] = btn["url"]
            keyboard_row.append(button)
        inline_keyboard.append(keyboard_row)

    return {"inline_keyboard": inline_keyboard}


class TelegramSendService:
    """
    Service for sending messages to Telegram users via Bot API.

    Handles message sending, splitting long messages, retries, and error handling.
    Uses httpx.AsyncClient for efficient async HTTP requests.
    """

    def __init__(self):
        """Initialize the Telegram send service."""
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def token(self) -> Optional[str]:
        """Get Telegram bot token (lazy initialization)."""
        if self._token is None:
            self._token = get_telegram_bot_token()
        return self._token

    def refresh_token(self) -> None:
        """Refresh the bot token from settings (call after settings change)."""
        self._token = get_telegram_bot_token()

    @property
    def api_base_url(self) -> str:
        """Get the base URL for Telegram API calls."""
        return f"{TELEGRAM_API_BASE}{self.token}"

    def is_configured(self) -> bool:
        """Check if Telegram Bot is properly configured."""
        return self.token is not None and len(self.token) > 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _make_request(
        self,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a request to the Telegram Bot API.

        Args:
            method: Telegram API method name (e.g., 'sendMessage')
            data: Request data/parameters
            files: Files to upload (for sendDocument, etc.)

        Returns:
            API response result

        Raises:
            TelegramAPIError: If the API returns an error
        """
        if not self.is_configured():
            raise ValueError("Telegram Bot Token not configured")

        url = f"{self.api_base_url}/{method}"
        client = await self._get_client()

        try:
            if files:
                # Multipart form data for file uploads
                response = await client.post(url, data=data, files=files)
            else:
                # JSON request for regular API calls
                response = await client.post(url, json=data)

            result = response.json()

            if not result.get("ok", False):
                error_code = result.get("error_code", response.status_code)
                description = result.get("description", "Unknown error")
                logger.error(f"Telegram API error: {error_code} - {description}")
                raise TelegramAPIError(response.status_code, error_code, description)

            return result.get("result", {})

        except httpx.RequestError as e:
            logger.error(f"Network error calling Telegram API: {e}")
            raise

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        _fallback_attempt: bool = False
    ) -> Dict[str, Any]:
        """
        Send a text message to a Telegram chat.

        Feature #341: Added Markdown sanitization and plain text fallback.

        Args:
            chat_id: Unique identifier for the target chat or username
            text: Text of the message to be sent (1-4096 characters)
            parse_mode: 'Markdown', 'MarkdownV2', or 'HTML' (default: 'Markdown')
            reply_to_message_id: If set, the message will be sent as a reply
            reply_markup: InlineKeyboardMarkup or other reply markup
            disable_web_page_preview: Disables link previews for links in this message
            disable_notification: Sends the message silently
            _fallback_attempt: Internal flag to prevent infinite fallback loops

        Returns:
            Dict with:
                - success: Whether the message was sent successfully
                - message_id: Telegram message ID
                - chat_id: Target chat ID
                - date: Unix timestamp when message was sent
                - error: Error message if failed
                - markdown_sanitized: Whether Markdown was sanitized (Feature #341)
                - plain_text_fallback: Whether plain text fallback was used (Feature #341)
        """
        if not self.is_configured():
            logger.error("Cannot send Telegram message: Bot not configured")
            return {
                'success': False,
                'chat_id': chat_id,
                'error': 'Telegram Bot Token not configured'
            }

        # Feature #341: Sanitize Markdown before sending
        original_text = text
        markdown_sanitized = False
        plain_text_fallback = False

        if parse_mode and parse_mode.lower() in ('markdown', 'markdownv2') and not _fallback_attempt:
            text, markdown_sanitized = sanitize_telegram_markdown(text)
            if markdown_sanitized:
                logger.info(f"Markdown sanitized for chat_id={chat_id}")

        # Build request data
        data: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }

        if parse_mode:
            data["parse_mode"] = parse_mode

        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id

        if reply_markup:
            data["reply_markup"] = reply_markup

        if disable_web_page_preview:
            data["disable_web_page_preview"] = True

        if disable_notification:
            data["disable_notification"] = True

        try:
            # Use retry logic for transient failures
            @retry(
                stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
                wait=wait_exponential(
                    multiplier=1,
                    min=RETRY_MIN_WAIT,
                    max=RETRY_MAX_WAIT
                ),
                retry=retry_if_exception_type((httpx.RequestError,)),
                before_sleep=before_sleep_log(logger, logging.WARNING)
            )
            async def _send_with_retry():
                return await self._make_request("sendMessage", data)

            result = await _send_with_retry()

            logger.info(f"Telegram message sent: chat_id={chat_id}, message_id={result.get('message_id')}")

            return {
                'success': True,
                'message_id': result.get('message_id'),
                'chat_id': result.get('chat', {}).get('id', chat_id),
                'date': result.get('date'),
                'text_length': len(text),
                'markdown_sanitized': markdown_sanitized,
                'plain_text_fallback': plain_text_fallback
            }

        except TelegramAPIError as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {e}")

            # Feature #341: Check if this is a Markdown parsing error
            is_markdown_error = (
                e.error_code == TelegramErrorCodes.BAD_REQUEST and
                "can't parse entities" in e.description.lower()
            )

            # Feature #341: Fallback to plain text if Markdown parsing fails
            if is_markdown_error and parse_mode and not _fallback_attempt:
                logger.warning(f"Markdown parsing failed for chat_id={chat_id}, falling back to plain text")
                plain_text = strip_markdown_formatting(original_text)
                fallback_result = await self.send_message(
                    chat_id=chat_id,
                    text=plain_text,
                    parse_mode=None,  # No formatting - plain text
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview,
                    disable_notification=disable_notification,
                    _fallback_attempt=True
                )
                fallback_result['plain_text_fallback'] = True
                fallback_result['original_error'] = e.description
                return fallback_result

            # Categorize the error
            error_type = "unknown"
            if TelegramErrorCodes.CHAT_NOT_FOUND in e.description.lower():
                error_type = "chat_not_found"
            elif TelegramErrorCodes.BOT_BLOCKED in e.description.lower():
                error_type = "bot_blocked"
            elif TelegramErrorCodes.USER_DEACTIVATED in e.description.lower():
                error_type = "user_deactivated"
            elif TelegramErrorCodes.CHAT_WRITE_FORBIDDEN in e.description.lower():
                error_type = "no_write_permission"
            elif TelegramErrorCodes.MESSAGE_TOO_LONG in e.description.lower():
                error_type = "message_too_long"
            elif is_markdown_error:
                error_type = "markdown_parse_error"

            return {
                'success': False,
                'chat_id': chat_id,
                'error': e.description,
                'error_code': e.error_code,
                'error_type': error_type,
                'markdown_sanitized': markdown_sanitized
            }

        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {e}")
            return {
                'success': False,
                'chat_id': chat_id,
                'error': str(e),
                'error_type': 'network_error'
            }

    async def send_long_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send a message that may exceed Telegram's 4096 character limit.

        Automatically splits the message into multiple parts if needed.

        Args:
            chat_id: Target chat ID
            text: Full message text (any length)
            parse_mode: Formatting mode
            reply_to_message_id: Reply to this message (only for first part)
            **kwargs: Additional arguments passed to send_message

        Returns:
            Dict with:
                - success: Whether all parts sent successfully
                - parts_sent: Number of message parts sent
                - total_parts: Total number of parts
                - message_ids: List of Telegram message IDs
                - errors: List of any errors encountered
        """
        parts = split_message(text)
        total_parts = len(parts)
        results = []
        errors = []

        logger.info("=" * 60)
        logger.info("SENDING TELEGRAM MESSAGE")
        logger.info("=" * 60)
        logger.info(f"  To chat_id: {chat_id}")
        logger.info(f"  Original length: {len(text)} chars")
        logger.info(f"  Parts: {total_parts}")

        for i, part in enumerate(parts):
            logger.info(f"  Sending part {i+1}/{total_parts} ({len(part)} chars)")

            # Only reply to original message for the first part
            reply_id = reply_to_message_id if i == 0 else None

            result = await self.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=parse_mode,
                reply_to_message_id=reply_id,
                **kwargs
            )

            results.append(result)

            if not result['success']:
                error_msg = f"Part {i+1}: {result.get('error', 'Unknown error')}"
                errors.append(error_msg)
                logger.error(f"  Failed: {error_msg}")
            else:
                logger.info(f"  Sent: message_id={result.get('message_id')}")

            # Small delay between parts to maintain order
            if i < len(parts) - 1:
                await asyncio.sleep(0.3)

        parts_sent = sum(1 for r in results if r.get('success', False))
        all_success = parts_sent == total_parts

        # Feature #341: Track if any parts used sanitization or fallback
        any_markdown_sanitized = any(r.get('markdown_sanitized', False) for r in results)
        any_plain_text_fallback = any(r.get('plain_text_fallback', False) for r in results)

        logger.info("=" * 60)
        logger.info(f"TELEGRAM SEND COMPLETE: {parts_sent}/{total_parts} parts sent")
        if any_markdown_sanitized:
            logger.info("  (Markdown was sanitized)")
        if any_plain_text_fallback:
            logger.info("  (Plain text fallback was used)")
        logger.info("=" * 60)

        return {
            'success': all_success,
            'parts_sent': parts_sent,
            'total_parts': total_parts,
            'message_ids': [r.get('message_id') for r in results if r.get('message_id')],
            'errors': errors,
            'chat_id': chat_id,
            'original_length': len(text),
            'markdown_sanitized': any_markdown_sanitized,
            'plain_text_fallback': any_plain_text_fallback
        }

    async def send_document(
        self,
        chat_id: Union[int, str],
        document: Union[str, bytes],
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a document/file to a Telegram chat.

        Args:
            chat_id: Target chat ID
            document: File path (str) or file content (bytes)
            filename: Name for the file (required if document is bytes)
            caption: Document caption (0-1024 characters)
            parse_mode: Formatting mode for caption
            reply_to_message_id: Reply to this message
            reply_markup: Reply markup (inline keyboard, etc.)

        Returns:
            Dict with success status and document info
        """
        if not self.is_configured():
            logger.error("Cannot send Telegram document: Bot not configured")
            return {
                'success': False,
                'chat_id': chat_id,
                'error': 'Telegram Bot Token not configured'
            }

        try:
            # Prepare the document
            if isinstance(document, str):
                # It's a file path
                import os
                if not os.path.exists(document):
                    return {
                        'success': False,
                        'chat_id': chat_id,
                        'error': f'File not found: {document}'
                    }
                filename = filename or os.path.basename(document)
                with open(document, 'rb') as f:
                    file_content = f.read()
            else:
                # It's bytes
                file_content = document
                if not filename:
                    filename = "document"

            # Build form data
            data = {
                "chat_id": str(chat_id),
            }

            if caption:
                data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode

            if reply_to_message_id:
                data["reply_to_message_id"] = str(reply_to_message_id)

            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)

            # Prepare files
            files = {
                "document": (filename, file_content)
            }

            result = await self._make_request("sendDocument", data=data, files=files)

            document_info = result.get('document', {})
            logger.info(f"Telegram document sent: chat_id={chat_id}, file_id={document_info.get('file_id')}")

            return {
                'success': True,
                'message_id': result.get('message_id'),
                'chat_id': result.get('chat', {}).get('id', chat_id),
                'file_id': document_info.get('file_id'),
                'file_name': document_info.get('file_name'),
                'file_size': document_info.get('file_size'),
                'mime_type': document_info.get('mime_type')
            }

        except TelegramAPIError as e:
            logger.error(f"Failed to send Telegram document to {chat_id}: {e}")
            return {
                'success': False,
                'chat_id': chat_id,
                'error': e.description,
                'error_code': e.error_code
            }

        except Exception as e:
            logger.error(f"Unexpected error sending Telegram document: {e}")
            return {
                'success': False,
                'chat_id': chat_id,
                'error': str(e)
            }

    async def send_response(
        self,
        chat_id: Union[int, str],
        response: str,
        reply_to_message_id: Optional[int] = None,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a RAG response back to a Telegram user.

        This is the main method to be called after processing a message.
        It handles formatting, splitting, sending, and logging.

        Args:
            chat_id: User's Telegram chat ID
            response: The AI-generated response to send
            reply_to_message_id: Original message ID to reply to
            conversation_id: Optional conversation ID for logging

        Returns:
            Dict with send results
        """
        logger.info(f"Sending Telegram response to chat_id={chat_id} (conversation: {conversation_id})")

        result = await self.send_long_message(
            chat_id=chat_id,
            text=response,
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id
        )

        # Add conversation ID to result for tracking
        result['conversation_id'] = conversation_id

        # Log the send operation
        self._log_send_operation(
            chat_id=chat_id,
            response=response,
            result=result,
            conversation_id=conversation_id
        )

        return result

    def _log_send_operation(
        self,
        chat_id: Union[int, str],
        response: str,
        result: Dict[str, Any],
        conversation_id: Optional[str] = None
    ):
        """
        Log the send operation details for audit/debugging.

        Args:
            chat_id: Recipient chat ID
            response: Original response text
            result: Send result dict
            conversation_id: Optional conversation ID
        """
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'operation': 'telegram_send',
            'chat_id': chat_id,
            'conversation_id': conversation_id,
            'response_length': len(response),
            'parts_sent': result.get('parts_sent', 0),
            'total_parts': result.get('total_parts', 0),
            'success': result.get('success', False),
            'message_ids': result.get('message_ids', []),
            'errors': result.get('errors', [])
        }

        if result.get('success'):
            logger.info(f"Telegram send logged: {json.dumps(log_entry)}")
        else:
            logger.error(f"Telegram send failed: {json.dumps(log_entry)}")


# Singleton instance for convenience
_telegram_send_service: Optional[TelegramSendService] = None


def get_telegram_send_service() -> TelegramSendService:
    """Get the singleton TelegramSendService instance."""
    global _telegram_send_service
    if _telegram_send_service is None:
        _telegram_send_service = TelegramSendService()
    return _telegram_send_service
