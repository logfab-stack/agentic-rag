"""
Agentic Splitter - LLM-based intelligent text chunking.

This module implements the "Agentic Splitter" algorithm from the project specification:
1. Take a chunk of text
2. Ask the LLM "Where does the topic change in this text?"
3. Split at the semantic transition point identified by the LLM
4. Repeat recursively until all chunks are within size limits

This produces semantically coherent chunks that preserve meaning,
dramatically improving vector search quality compared to fixed-size chunking.

Fallback: If the LLM is unavailable or too slow, falls back to
paragraph/sentence-based splitting.

Feature #331: Timeout and fallback mechanism
- Configurable timeout (default 300 seconds / 5 minutes)
- If chunking takes too long, falls back to RecursiveCharacterTextSplitter
- Document metadata indicates when fallback was used
"""

import re
import logging
import asyncio
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import httpx
from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# Default constraints
DEFAULT_MIN_CHUNK_SIZE = 200
DEFAULT_MAX_CHUNK_SIZE = 2000
DEFAULT_IDEAL_CHUNK_SIZE = 1000
LLM_TIMEOUT_SECONDS = 90
# Feature #331: Default timeout for the entire agentic splitting process
DEFAULT_AGENTIC_TIMEOUT_SECONDS = 300  # 5 minutes


@dataclass
class AgenticChunk:
    """A chunk produced by the Agentic Splitter with rich metadata."""
    text: str
    section_title: Optional[str] = None
    chunk_type: str = "agentic"
    position_in_doc: int = 0
    total_chunks: int = 0
    split_reason: str = "initial"  # "llm_split", "sentence_fallback", "size_limit", "timeout_fallback"
    context_prefix: Optional[str] = None
    llm_split_count: int = 0  # How many times LLM was used to split this lineage
    # Feature #331: Track if timeout fallback was used
    used_timeout_fallback: bool = False

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "metadata": {
                "section_title": self.section_title,
                "chunk_type": self.chunk_type,
                "position_in_doc": self.position_in_doc,
                "total_chunks": self.total_chunks,
                "char_count": len(self.text),
                "split_reason": self.split_reason,
                "context_prefix": self.context_prefix,
                "has_context": self.context_prefix is not None,
                "llm_split_count": self.llm_split_count,
                # Feature #331: Include timeout fallback info in metadata
                "used_timeout_fallback": self.used_timeout_fallback,
            }
        }

    def get_full_text(self) -> str:
        """Get text including context prefix for embedding."""
        if self.context_prefix:
            return f"[Previous context: {self.context_prefix}]\n\n{self.text}"
        return self.text


class AgenticSplitter:
    """
    LLM-powered text splitter that finds semantic transition points.

    Algorithm:
    1. Given a text block, ask the LLM to identify where the topic changes
    2. Split at that point into two parts
    3. Recursively process each part if still too large
    4. Merge fragments that are too small

    Fallback chain:
    - Primary: LLM-based semantic splitting
    - Secondary: Paragraph/section boundary splitting
    - Tertiary: Sentence boundary splitting
    - Last resort: Fixed-size word-boundary splitting
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        ollama_base_url: str = "http://localhost:11434",
        min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
        max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
        ideal_chunk_size: int = DEFAULT_IDEAL_CHUNK_SIZE,
        timeout_seconds: int = DEFAULT_AGENTIC_TIMEOUT_SECONDS,  # Feature #331
    ):
        self.api_key = api_key
        self.llm_model = llm_model
        self.ollama_base_url = ollama_base_url
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.ideal_chunk_size = ideal_chunk_size
        self.timeout_seconds = timeout_seconds  # Feature #331: Configurable timeout
        self.openai_client: Optional[OpenAI] = None
        self._llm_call_count = 0
        self._llm_success_count = 0
        self._used_timeout_fallback = False  # Feature #331: Track if fallback was used

        # Initialize LLM client based on model type
        # FEATURE #144: Support separate chunking LLM via OpenRouter
        if api_key and llm_model.startswith("openrouter:"):
            # OpenRouter model: use OpenRouter API endpoint
            try:
                self.openai_client = OpenAI(
                    api_key=api_key,
                    base_url="https://openrouter.ai/api/v1"
                )
                logger.info(f"AgenticSplitter initialized with OpenRouter model: {llm_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenRouter client for AgenticSplitter: {e}")
        elif api_key and api_key.startswith('sk-') and len(api_key) > 20:
            # OpenAI model: use standard OpenAI API
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info(f"AgenticSplitter initialized with OpenAI model: {llm_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client for AgenticSplitter: {e}")

    @property
    def has_llm(self) -> bool:
        """Check if LLM is available for splitting."""
        return self.openai_client is not None or self.llm_model.startswith("ollama:")

    def _fallback_recursive_character_split(
        self,
        text: str,
        document_title: Optional[str] = None,
    ) -> List[AgenticChunk]:
        """
        Feature #331: Fallback to RecursiveCharacterTextSplitter when timeout is reached.

        Uses LangChain's RecursiveCharacterTextSplitter which splits on:
        1. Paragraph breaks (\\n\\n)
        2. Line breaks (\\n)
        3. Sentence separators (. ! ?)
        4. Word boundaries (space)

        Args:
            text: Document text to split
            document_title: Optional document title for metadata

        Returns:
            List of AgenticChunk objects with timeout_fallback metadata
        """
        logger.warning(
            f"[Feature #331] Using RecursiveCharacterTextSplitter fallback "
            f"(timeout exceeded or error during agentic splitting)"
        )

        self._used_timeout_fallback = True

        # Create the recursive character splitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.max_chunk_size,
            chunk_overlap=int(self.max_chunk_size * 0.1),  # 10% overlap
            length_function=len,
            separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""],
        )

        # Split the text
        chunks = splitter.split_text(text)

        logger.info(
            f"[Feature #331] RecursiveCharacterTextSplitter produced {len(chunks)} chunks "
            f"(max_size={self.max_chunk_size})"
        )

        # Convert to AgenticChunk objects with fallback metadata
        result: List[AgenticChunk] = []
        for i, chunk_text in enumerate(chunks):
            chunk = AgenticChunk(
                text=chunk_text,
                section_title=document_title,
                chunk_type="recursive_fallback",  # Mark as fallback type
                position_in_doc=i,
                total_chunks=len(chunks),
                split_reason="timeout_fallback",  # Indicate fallback reason
                llm_split_count=0,
                used_timeout_fallback=True,  # Feature #331: Mark fallback
            )
            result.append(chunk)

        # Add context overlap (same as agentic approach)
        for i in range(1, len(result)):
            context = self._extract_context(result[i - 1].text)
            if context:
                result[i].context_prefix = context

        context_count = sum(1 for c in result if c.context_prefix)
        logger.info(
            f"[Feature #331] Fallback chunks: {len(result)} total, "
            f"{context_count} with context overlap"
        )

        return result

    async def _ask_llm_for_split(self, text: str) -> Optional[int]:
        """
        Ask the LLM to find the semantic transition point in the text.

        The LLM analyzes the text and returns the character position where
        the topic or subject matter changes most significantly.

        Args:
            text: Text to analyze (truncated to ~3000 chars for efficiency)

        Returns:
            Character position for the split, or None if no good split found
        """
        # Truncate very long text to save tokens
        analysis_text = text[:3000]

        prompt = (
            "You are a document analysis expert. Analyze the following text and find "
            "the position where the TOPIC or SUBJECT changes most significantly.\n\n"
            "Look for:\n"
            "- A shift from one topic to a different topic\n"
            "- A transition from introduction to detail, or from one concept to another\n"
            "- A paragraph break where new subject matter begins\n"
            "- A heading or section transition\n\n"
            f"TEXT:\n---\n{analysis_text}\n---\n\n"
            "Respond with ONLY a single integer: the character position (0-based) "
            f"where the split should occur (between 0 and {len(analysis_text)}).\n"
            "If the text is about one single topic with no clear transition, respond with: NONE\n\n"
            "Important: The split position should be at a sentence or paragraph boundary, "
            "not in the middle of a word or sentence."
        )

        self._llm_call_count += 1

        try:
            use_ollama = self.llm_model.startswith("ollama:")

            if use_ollama:
                model_name = self.llm_model.replace("ollama:", "")
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.ollama_base_url}/api/generate",
                        json={
                            "model": model_name,
                            "prompt": prompt,
                            "stream": False,
                        }
                    )
                    if response.status_code != 200:
                        logger.warning(f"Ollama API error: {response.status_code}")
                        return None
                    answer = response.json().get("response", "").strip()
            else:
                if not self.openai_client:
                    return None

                # Use the actual model name (strip openrouter: prefix if present)
                model_name = self.llm_model
                if model_name.startswith("openrouter:"):
                    model_name = model_name.replace("openrouter:", "")

                response = self.openai_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a text analysis assistant. Respond with only a number or 'NONE'."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=50,
                )
                answer = response.choices[0].message.content.strip()

            # Parse the response
            if answer.upper() == "NONE":
                logger.debug("LLM found no semantic transition in text")
                return None

            # Extract the number
            numbers = re.findall(r'\d+', answer)
            if not numbers:
                logger.debug(f"LLM response not parseable: {answer[:100]}")
                return None

            position = int(numbers[0])

            # Validate position
            if position < self.min_chunk_size or position > len(analysis_text) - self.min_chunk_size:
                logger.debug(f"LLM position {position} too close to edge, ignoring")
                return None

            # Snap to nearest sentence/paragraph boundary
            snapped = self._snap_to_boundary(text, position)
            if snapped is not None:
                self._llm_success_count += 1
                logger.info(f"LLM found semantic split at position {snapped} (raw: {position})")
                return snapped

            # Use raw position if snapping failed but position is valid
            self._llm_success_count += 1
            logger.info(f"LLM found semantic split at raw position {position}")
            return position

        except asyncio.TimeoutError:
            logger.warning(f"LLM call timed out after {LLM_TIMEOUT_SECONDS}s for agentic splitting")
            return None
        except Exception as e:
            logger.error(f"Error during LLM split analysis: {type(e).__name__}: {e}")
            return None

    def _snap_to_boundary(self, text: str, position: int, search_radius: int = 150) -> Optional[int]:
        """
        Snap a raw character position to the nearest sentence or paragraph boundary.

        Args:
            text: Full text
            position: Raw position from LLM
            search_radius: How far to look for a boundary

        Returns:
            Adjusted position at a sentence/paragraph boundary, or None
        """
        search_start = max(0, position - search_radius)
        search_end = min(len(text), position + search_radius)
        search_region = text[search_start:search_end]

        # Look for boundaries in priority order
        boundary_patterns = [
            r'\n\n',       # Paragraph break (strongest)
            r'\.\s+',      # Period + space
            r'\?\s+',      # Question mark + space
            r'!\s+',       # Exclamation + space
            r';\s+',       # Semicolon + space
            r'\n',         # Single newline
        ]

        best_pos = None
        best_distance = float('inf')

        for pattern in boundary_patterns:
            for match in re.finditer(pattern, search_region):
                abs_pos = search_start + match.end()
                distance = abs(abs_pos - position)
                # Prefer paragraph breaks even if slightly further away
                weight = 0.5 if pattern == r'\n\n' else 1.0
                weighted_distance = distance * weight
                if weighted_distance < best_distance and abs_pos > self.min_chunk_size:
                    best_distance = weighted_distance
                    best_pos = abs_pos

        return best_pos

    def _fallback_split_at_boundary(self, text: str) -> Optional[int]:
        """
        Fallback: find a split point using structural/sentence boundaries.

        Used when LLM is unavailable or returns no result.
        """
        # Try paragraph boundary first (double newline)
        search_start = max(self.min_chunk_size, self.ideal_chunk_size - 300)
        search_end = min(len(text), self.ideal_chunk_size + 300)

        # Paragraph break
        pos = text.rfind('\n\n', search_start, search_end)
        if pos > self.min_chunk_size:
            return pos + 2

        # Sentence boundaries
        for sep in ['. ', '? ', '! ', ';\n', '.\n']:
            pos = text.rfind(sep, search_start, search_end)
            if pos > self.min_chunk_size:
                return pos + len(sep)

        # Single newline
        pos = text.rfind('\n', search_start, search_end)
        if pos > self.min_chunk_size:
            return pos + 1

        # Word boundary
        pos = text.rfind(' ', search_start, search_end)
        if pos > self.min_chunk_size:
            return pos + 1

        # Hard split at ideal size
        return self.ideal_chunk_size if self.ideal_chunk_size < len(text) else None

    async def _recursive_split(
        self,
        text: str,
        depth: int = 0,
        max_depth: int = 5,
        section_title: Optional[str] = None,
    ) -> List[str]:
        """
        Recursively split text using LLM-identified semantic transitions.

        Args:
            text: Text to split
            depth: Current recursion depth
            max_depth: Maximum recursion depth to prevent infinite loops
            section_title: Optional heading context

        Returns:
            List of text chunks
        """
        # Base case: text is within size limits
        if len(text) <= self.max_chunk_size:
            return [text] if text.strip() else []

        # Safety: prevent infinite recursion
        if depth >= max_depth:
            logger.warning(f"Max recursion depth reached, using fallback split")
            return self._force_split(text)

        # Try LLM-based split
        split_pos = None
        if self.has_llm:
            split_pos = await self._ask_llm_for_split(text)

        # Fallback to structural/sentence boundary
        if split_pos is None:
            split_pos = self._fallback_split_at_boundary(text)

        if split_pos is None or split_pos <= 0 or split_pos >= len(text):
            # Cannot split further, force it
            return self._force_split(text)

        # Split into two parts
        left = text[:split_pos].strip()
        right = text[split_pos:].strip()

        # Recursively split each part if needed
        left_chunks = await self._recursive_split(left, depth + 1, max_depth, section_title)
        right_chunks = await self._recursive_split(right, depth + 1, max_depth, section_title)

        return left_chunks + right_chunks

    def _force_split(self, text: str) -> List[str]:
        """Force-split text when no semantic boundary is found."""
        chunks = []
        remaining = text

        while len(remaining) > self.max_chunk_size:
            pos = self._fallback_split_at_boundary(remaining)
            if pos and pos > 0 and pos < len(remaining):
                chunks.append(remaining[:pos].strip())
                remaining = remaining[pos:].strip()
            else:
                # Absolute last resort
                chunks.append(remaining[:self.ideal_chunk_size].strip())
                remaining = remaining[self.ideal_chunk_size:].strip()

        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks

    def _extract_context(self, text: str, max_length: int = 300) -> str:
        """Extract last 1-2 sentences for context overlap."""
        if not text or len(text) < 50:
            return ""

        text = text.strip()

        # Find sentence boundaries
        endings = list(re.finditer(r'[.!?]\s+', text))
        if not endings:
            return text[-150:].strip() if len(text) > 150 else text

        # Get last 2 sentences
        if len(endings) >= 2:
            start = endings[-2].end()
        else:
            start = endings[-1].start()
            # Go back to find start of this sentence
            prev = text.rfind('.', 0, start - 1)
            start = prev + 2 if prev > 0 else 0

        context = text[start:].strip()
        if len(context) > max_length:
            context = context[:max_length] + "..."

        return context

    def _merge_small_chunks(self, chunks: List[str]) -> List[str]:
        """Merge consecutive small chunks that are below minimum size."""
        if not chunks:
            return []

        merged = []
        buffer = ""

        for chunk in chunks:
            if not chunk.strip():
                continue

            if buffer:
                combined = buffer + "\n\n" + chunk
                if len(combined) <= self.max_chunk_size:
                    buffer = combined
                else:
                    merged.append(buffer)
                    buffer = chunk
            else:
                buffer = chunk

            # Flush if buffer is large enough
            if len(buffer) >= self.min_chunk_size and len(buffer) <= self.max_chunk_size:
                if not chunks[chunks.index(chunk):]:  # last chunk
                    merged.append(buffer)
                    buffer = ""

        # Flush remaining buffer
        if buffer:
            if merged and len(buffer) < self.min_chunk_size and len(merged[-1]) + len(buffer) + 2 <= self.max_chunk_size:
                merged[-1] = merged[-1] + "\n\n" + buffer
            else:
                merged.append(buffer)

        return merged

    async def _agentic_split_core(
        self,
        text: str,
        document_title: Optional[str] = None,
    ) -> List[AgenticChunk]:
        """
        Core agentic splitting logic (without timeout wrapper).

        This method contains the actual LLM-based splitting algorithm.
        Called by split() with a timeout wrapper.
        """
        self._llm_call_count = 0
        self._llm_success_count = 0

        # Step 1: Recursively split using LLM
        raw_chunks = await self._recursive_split(text, section_title=document_title)

        # Step 2: Merge small fragments
        merged_chunks = self._merge_small_chunks(raw_chunks)

        logger.info(f"AgenticSplitter: {len(raw_chunks)} raw chunks → "
                     f"{len(merged_chunks)} after merging "
                     f"(LLM calls: {self._llm_call_count}, "
                     f"successful: {self._llm_success_count})")

        # Step 3: Create AgenticChunk objects with metadata
        result: List[AgenticChunk] = []
        for i, chunk_text in enumerate(merged_chunks):
            chunk = AgenticChunk(
                text=chunk_text,
                section_title=document_title,
                chunk_type="agentic",
                position_in_doc=i,
                total_chunks=len(merged_chunks),
                split_reason="llm_split" if self._llm_success_count > 0 else "sentence_fallback",
                llm_split_count=self._llm_success_count,
                used_timeout_fallback=False,
            )
            result.append(chunk)

        # Step 4: Add context overlap
        for i in range(1, len(result)):
            context = self._extract_context(result[i - 1].text)
            if context:
                result[i].context_prefix = context

        context_count = sum(1 for c in result if c.context_prefix)
        logger.info(f"AgenticSplitter: Added context overlap to {context_count}/{len(result)} chunks")

        # Log chunk size statistics
        if result:
            sizes = [len(c.text) for c in result]
            logger.info(f"AgenticSplitter: Chunk sizes - min={min(sizes)}, max={max(sizes)}, "
                         f"avg={sum(sizes)//len(sizes)}")

        return result

    async def split(
        self,
        text: str,
        document_title: Optional[str] = None,
    ) -> List[AgenticChunk]:
        """
        Main entry point: Split text into semantically coherent chunks using LLM.

        This implements the Agentic Splitter algorithm:
        1. Recursively ask LLM where topics change
        2. Split at those points
        3. Merge fragments that are too small
        4. Add context overlap between chunks

        Feature #331: Timeout protection
        If chunking takes longer than timeout_seconds, automatically falls back
        to RecursiveCharacterTextSplitter to ensure documents always get processed.

        Args:
            text: Document text to split
            document_title: Optional document title for metadata

        Returns:
            List of AgenticChunk objects
        """
        if not text or not text.strip():
            return []

        logger.info(f"AgenticSplitter: Processing {len(text)} characters"
                     f" (LLM available: {self.has_llm}, timeout: {self.timeout_seconds}s)")

        self._used_timeout_fallback = False
        start_time = time.time()

        try:
            # Feature #331: Wrap the agentic splitting with a timeout
            result = await asyncio.wait_for(
                self._agentic_split_core(text, document_title),
                timeout=self.timeout_seconds
            )

            elapsed = time.time() - start_time
            logger.info(f"AgenticSplitter: Completed in {elapsed:.2f}s (no timeout)")
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(
                f"[Feature #331] AgenticSplitter TIMEOUT after {elapsed:.2f}s "
                f"(limit: {self.timeout_seconds}s). Falling back to RecursiveCharacterTextSplitter."
            )
            return self._fallback_recursive_character_split(text, document_title)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[Feature #331] AgenticSplitter ERROR after {elapsed:.2f}s: {e}. "
                f"Falling back to RecursiveCharacterTextSplitter."
            )
            return self._fallback_recursive_character_split(text, document_title)

    def _split_list_at_items(self, text: str) -> List[str]:
        """
        Feature #351: Split an oversized list at item boundaries.
        Never splits in the middle of a list item.
        """
        # Detect list item patterns: "- ", "* ", "1. ", "  - " etc.
        item_pattern = re.compile(r'\n(?=\s*[-*]\s|\s*\d+[.)]\s)')
        items = item_pattern.split(text)

        if len(items) <= 1:
            return [text]  # Can't split further

        chunks = []
        current = ""
        for item in items:
            candidate = (current + "\n" + item).strip() if current else item.strip()
            if len(candidate) > self.max_chunk_size * 2 and current:
                chunks.append(current.strip())
                current = item.strip()
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text]

    async def _flush_text_buffer(
        self,
        text_parts: List[str],
        heading: Optional[str],
        document_title: Optional[str],
        all_chunks: List[AgenticChunk],
    ) -> None:
        """
        Feature #351: Flush accumulated paragraph text through LLM-based splitting.
        """
        if not text_parts:
            return

        combined = '\n\n'.join(text_parts)
        if not combined.strip():
            return

        if len(combined) <= self.max_chunk_size:
            all_chunks.append(AgenticChunk(
                text=combined,
                section_title=heading or document_title,
                chunk_type="text",
                split_reason="within_size",
                used_timeout_fallback=False,
            ))
        else:
            sub_chunks = await self._recursive_split(
                combined,
                section_title=heading or document_title,
            )
            merged = self._merge_small_chunks(sub_chunks)
            for chunk_text in merged:
                all_chunks.append(AgenticChunk(
                    text=chunk_text,
                    section_title=heading or document_title,
                    chunk_type="text",
                    split_reason="llm_split" if self._llm_success_count > 0 else "sentence_fallback",
                    llm_split_count=self._llm_success_count,
                    used_timeout_fallback=False,
                ))

    async def _split_elements_core(
        self,
        elements: List,
        document_title: Optional[str] = None,
    ) -> List[AgenticChunk]:
        """
        Core element splitting logic (without timeout wrapper).

        Feature #351: Structure-aware chunking.
        - Tables, lists, and code blocks are kept as atomic chunks (never split mid-element)
        - Paragraphs are split using LLM-based semantic splitting
        - Each chunk carries its element type as chunk_type metadata
        - section_title propagates from the nearest preceding heading
        """
        all_chunks: List[AgenticChunk] = []
        current_heading: Optional[str] = None
        text_buffer: List[str] = []

        # Count element types for logging
        type_counts: Dict[str, int] = {}

        for elem in elements:
            elem_type = elem.type.value if hasattr(elem.type, 'value') else str(elem.type)
            type_counts[elem_type] = type_counts.get(elem_type, 0) + 1

            if elem_type == 'heading':
                # Flush accumulated paragraph text before starting new section
                await self._flush_text_buffer(text_buffer, current_heading, document_title, all_chunks)
                text_buffer = []
                current_heading = elem.content[:100]
                # Include heading text in next text buffer so it's part of the chunk
                text_buffer.append(elem.content)

            elif elem_type in ('table', 'code'):
                # Flush any accumulated text first
                await self._flush_text_buffer(text_buffer, current_heading, document_title, all_chunks)
                text_buffer = []

                # Emit as a single atomic chunk - NEVER split tables or code
                content = elem.content.strip()
                if content:
                    all_chunks.append(AgenticChunk(
                        text=content,
                        section_title=current_heading or document_title,
                        chunk_type=elem_type,  # "table" or "code"
                        split_reason="atomic_element",
                        used_timeout_fallback=False,
                    ))

            elif elem_type == 'list':
                # Flush any accumulated text first
                await self._flush_text_buffer(text_buffer, current_heading, document_title, all_chunks)
                text_buffer = []

                content = elem.content.strip()
                if not content:
                    continue

                # Lists: keep as single chunk, but split at item boundaries if very large
                if len(content) <= self.max_chunk_size * 2:
                    all_chunks.append(AgenticChunk(
                        text=content,
                        section_title=current_heading or document_title,
                        chunk_type="list",
                        split_reason="atomic_element",
                        used_timeout_fallback=False,
                    ))
                else:
                    # Split at list item boundaries for very large lists
                    list_parts = self._split_list_at_items(content)
                    for part in list_parts:
                        all_chunks.append(AgenticChunk(
                            text=part,
                            section_title=current_heading or document_title,
                            chunk_type="list",
                            split_reason="list_item_split",
                            used_timeout_fallback=False,
                        ))

            else:
                # Paragraph or unknown type: accumulate for LLM-based splitting
                text_buffer.append(elem.content)

        # Flush remaining text buffer
        await self._flush_text_buffer(text_buffer, current_heading, document_title, all_chunks)

        type_str = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
        logger.info(f"AgenticSplitter: {len(elements)} elements ({type_str}) → {len(all_chunks)} chunks")

        # Update positions
        for i, chunk in enumerate(all_chunks):
            chunk.position_in_doc = i
            chunk.total_chunks = len(all_chunks)

        # Add context overlap
        for i in range(1, len(all_chunks)):
            context = self._extract_context(all_chunks[i - 1].text)
            if context:
                all_chunks[i].context_prefix = context

        context_count = sum(1 for c in all_chunks if c.context_prefix)
        chunk_types = {}
        for c in all_chunks:
            chunk_types[c.chunk_type] = chunk_types.get(c.chunk_type, 0) + 1
        types_str = ", ".join(f"{k}={v}" for k, v in sorted(chunk_types.items()))

        logger.info(f"AgenticSplitter: Created {len(all_chunks)} chunks from structured elements "
                     f"(types: {types_str}, context overlap: {context_count})")

        return all_chunks

    async def split_elements(
        self,
        elements: List,
        document_title: Optional[str] = None,
    ) -> List[AgenticChunk]:
        """
        Split pre-extracted document structure elements using the agentic approach.

        Feature #331: Timeout protection
        If chunking takes longer than timeout_seconds, automatically falls back
        to RecursiveCharacterTextSplitter to ensure documents always get processed.

        Args:
            elements: List of DocumentElement objects from structure extractor
            document_title: Optional document title

        Returns:
            List of AgenticChunk objects
        """
        if not elements:
            return []

        self._used_timeout_fallback = False
        self._llm_call_count = 0
        self._llm_success_count = 0
        start_time = time.time()

        # Combine all elements to get full text for potential fallback
        full_text = '\n\n'.join(elem.content for elem in elements if elem.content)

        logger.info(
            f"AgenticSplitter: Processing {len(elements)} elements, "
            f"{len(full_text)} total chars (LLM available: {self.has_llm}, "
            f"timeout: {self.timeout_seconds}s)"
        )

        try:
            # Feature #331: Wrap the agentic splitting with a timeout
            result = await asyncio.wait_for(
                self._split_elements_core(elements, document_title),
                timeout=self.timeout_seconds
            )

            elapsed = time.time() - start_time
            logger.info(f"AgenticSplitter: Completed elements splitting in {elapsed:.2f}s (no timeout)")
            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(
                f"[Feature #331] AgenticSplitter TIMEOUT after {elapsed:.2f}s for elements "
                f"(limit: {self.timeout_seconds}s). Falling back to RecursiveCharacterTextSplitter."
            )
            return self._fallback_recursive_character_split(full_text, document_title)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[Feature #331] AgenticSplitter ERROR after {elapsed:.2f}s for elements: {e}. "
                f"Falling back to RecursiveCharacterTextSplitter."
            )
            return self._fallback_recursive_character_split(full_text, document_title)
