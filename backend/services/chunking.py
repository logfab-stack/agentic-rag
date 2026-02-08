"""
Semantic Chunking Service - Intelligent text splitting using LLM-based analysis.

Replaces naive fixed-size chunking with structure-aware semantic chunking that:
1. Preserves document structure (headings, paragraphs, lists, tables)
2. Uses LLM to identify semantic transition points
3. Keeps related information together
4. Adds structural metadata to each chunk for better retrieval

FEATURE #245: Recipe-aware chunking
- Detects recipe boundaries and keeps each recipe as a single chunk
- Prepends breadcrumb metadata (category, recipe #, title, page, seasonality)
- Allows up to 3000 chars per recipe chunk to keep ingredients + preparation together
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
from openai import OpenAI
import asyncio
import httpx
from enum import Enum

logger = logging.getLogger(__name__)

# Chunking constraints
MIN_CHUNK_SIZE = 200  # Minimum characters per chunk
MAX_CHUNK_SIZE = 2000  # Maximum characters per chunk
IDEAL_CHUNK_SIZE = 1000  # Target chunk size

# FEATURE #245: Recipe chunking constraints
RECIPE_MAX_CHUNK_SIZE = 3000  # Allow larger chunks for recipes (ingredients + preparation)


class DocumentType(str, Enum):
    """Document type classification for specialized chunking."""
    RECIPE_BOOK = "recipe_book"
    INDEX = "index"
    INTRO = "intro"
    GENERAL = "general"


# Recipe detection patterns (Italian and English)
RECIPE_PATTERNS = {
    # Numbered recipe titles: "1. RECIPE NAME" or "42. RECIPE NAME"
    # Recipe titles start with uppercase and contain uppercase words
    # Must start at beginning of line and have at least 2 uppercase words to distinguish from numbered steps
    'numbered_recipe': re.compile(
        r'^(\d{1,3})\.\s+([A-Z][A-ZÀ-Ÿ]+(?:\s+[A-ZÀ-Ÿa-zà-ÿ,\'\-]+)*)',
        re.MULTILINE
    ),

    # Ingredients section markers (Italian and English)
    'ingredients': re.compile(r'INGREDIENTI|INGREDIENTS|Ingredienti|Ingredients', re.IGNORECASE),

    # Preparation section markers (Italian and English)
    'preparation': re.compile(r'PREPARAZIONE|PREPARATION|PROCEDIMENTO|ISTRUZIONI|INSTRUCTIONS|Preparazione|Preparation', re.IGNORECASE),

    # Seasonality marker (Italian recipe specific)
    'seasonality': re.compile(r'Stagionalità|Stagionlità|Seasonality|Stagione', re.IGNORECASE),

    # Serving/portion markers
    'servings': re.compile(r'x\s*\d+\s*Person[ae]?|per\s*\d+\s*person[ae]?|Serves?\s*\d+|Porzioni?', re.IGNORECASE),

    # Recipe category headers (E MERENDE added based on PDF)
    'category_headers': re.compile(r'^(COLAZIONI\s*E\s*MERENDE|COLAZIONI|MERENDE|BREAKFAST|SNACKS|PIATTI UNICI|MAIN COURSES|SECONDI|CONTORNI|SIDE DISHES|PRIMI|FIRST COURSES|DOLCI|DESSERTS)\s*$', re.MULTILINE | re.IGNORECASE),
}


# =============================================================================
# FEATURE #246: Section Type Detection for Retrieval Priority
# =============================================================================

# Section types for retrieval boosting/penalizing
SECTION_TYPE_RECIPE = "recipe"    # Has ingredients + steps, most valuable for recipe queries
SECTION_TYPE_INDEX = "index"      # TOC, page numbers - less useful content
SECTION_TYPE_INTRO = "intro"      # Preface, author notes - background info
SECTION_TYPE_GENERAL = "general"  # Default for unclassified content

# Boost factors for section types (used in vector search)
SECTION_TYPE_BOOST = {
    SECTION_TYPE_RECIPE: 1.2,   # 20% boost for recipe chunks
    SECTION_TYPE_INDEX: 0.5,    # 50% penalty for index chunks
    SECTION_TYPE_INTRO: 0.8,    # 20% penalty for intro chunks
    SECTION_TYPE_GENERAL: 1.0,  # No change for general chunks
}

# Patterns to detect index content
INDEX_PATTERNS = [
    re.compile(r'(?:^|\n)\s*(?:indice|index|sommario|table\s+of\s+contents|contents)\s*(?:\n|$)', re.IGNORECASE),
    re.compile(r'(?:\.\s*){3,}(?:\d+)', re.MULTILINE),  # Dotted leaders to page numbers (... 12)
    re.compile(r'\b(?:pag|page|p\.)\s*\d+', re.IGNORECASE),  # Page references
    re.compile(r'(?:^\d+\s*[-–—]\s*)+.{0,50}\s*\d+\s*$', re.MULTILINE),  # "1 - Recipe Name    12" pattern
]

# Patterns to detect intro/preface content
INTRO_PATTERNS = [
    re.compile(r'(?:^|\n)\s*(?:introduzione|introduction|prefazione|preface|avviso|disclaimer|nota\s+dell\'?autore|author\'?s?\s+note)\s*(?:\n|$)', re.IGNORECASE),
    re.compile(r'(?:benvenuto|welcome|questo\s+libro|this\s+book|dear\s+reader|caro\s+lettore)', re.IGNORECASE),
]


def detect_chunk_section_type(text: str) -> str:
    """
    FEATURE #246: Detect section type of a chunk for retrieval priority.

    Returns one of: 'recipe', 'index', 'intro', 'general'

    - Recipe chunks have ingredients and preparation steps
    - Index chunks are tables of contents, page listings
    - Intro chunks are prefaces, author notes, disclaimers
    - General chunks are everything else
    """
    text_lower = text.lower()

    # Check for recipe indicators (highest priority)
    has_ingredients = bool(RECIPE_PATTERNS['ingredients'].search(text))
    has_preparation = bool(RECIPE_PATTERNS['preparation'].search(text))
    has_numbered_recipe = bool(RECIPE_PATTERNS['numbered_recipe'].search(text))

    if (has_ingredients and has_preparation) or (has_numbered_recipe and (has_ingredients or has_preparation)):
        return SECTION_TYPE_RECIPE

    # Check for index/TOC content
    for pattern in INDEX_PATTERNS:
        if pattern.search(text):
            # Additional check: lots of page numbers suggest index
            page_refs = re.findall(r'\b(?:pag|page|p\.)?\s*(\d+)\s*$', text, re.MULTILINE | re.IGNORECASE)
            if len(page_refs) >= 3:  # At least 3 page references
                logger.debug(f"[Feature #246] Detected index chunk: {len(page_refs)} page references")
                return SECTION_TYPE_INDEX

    # Check for dotted leaders pattern (common in TOC)
    dotted_leaders = re.findall(r'\.{3,}\s*\d+', text)
    if len(dotted_leaders) >= 2:
        logger.debug(f"[Feature #246] Detected index chunk: {len(dotted_leaders)} dotted leader lines")
        return SECTION_TYPE_INDEX

    # Check for intro/preface content
    for pattern in INTRO_PATTERNS:
        if pattern.search(text):
            logger.debug(f"[Feature #246] Detected intro chunk")
            return SECTION_TYPE_INTRO

    return SECTION_TYPE_GENERAL


# =============================================================================
# FEATURE #245: Recipe-aware Chunking
# =============================================================================

class RecipeChunker:
    """
    FEATURE #245: Specialized chunker for recipe documents.

    Detects recipe boundaries and keeps each recipe as a single chunk,
    preserving the relationship between ingredients and preparation steps.

    Features:
    - Detects numbered recipe titles (e.g., "1. HUMMUS DOLCE CON PESCHE")
    - Keeps INGREDIENTI and PREPARAZIONE sections together
    - Extracts metadata: recipe number, title, seasonality, category
    - Prepends breadcrumb to each chunk for better retrieval
    - Allows larger chunk size (3000 chars) to keep recipes intact
    """

    def __init__(self):
        self.current_category = None
        self.recipes: List[Dict] = []

    def detect_document_type(self, text: str) -> DocumentType:
        """
        Detect the type of document based on content patterns.

        Returns:
            DocumentType enum indicating the document classification
        """
        text_lower = text.lower()

        # Check for recipe book indicators
        recipe_indicators = [
            'ricett', 'recipe', 'ingredienti', 'ingredients',
            'preparazione', 'preparation', 'cucina', 'cooking',
            'dieta', 'diet', 'piatt', 'dish'
        ]
        recipe_score = sum(1 for ind in recipe_indicators if ind in text_lower)

        # Check for numbered recipes
        numbered_recipes = RECIPE_PATTERNS['numbered_recipe'].findall(text)

        # Check for ingredients sections
        has_ingredients = bool(RECIPE_PATTERNS['ingredients'].search(text))

        # Check for preparation sections
        has_preparation = bool(RECIPE_PATTERNS['preparation'].search(text))

        # Strong indicators of recipe book
        if len(numbered_recipes) >= 3 and (has_ingredients or has_preparation):
            logger.info(f"[Feature #245] Detected recipe_book: {len(numbered_recipes)} numbered recipes found")
            return DocumentType.RECIPE_BOOK

        if recipe_score >= 5 and (has_ingredients or has_preparation):
            logger.info(f"[Feature #245] Detected recipe_book: recipe indicators score={recipe_score}")
            return DocumentType.RECIPE_BOOK

        # Check for index/TOC
        index_indicators = ['indice', 'index', 'sommario', 'table of contents', 'contents']
        if any(ind in text_lower[:500] for ind in index_indicators):
            return DocumentType.INDEX

        # Check for intro/preface
        intro_indicators = ['introduzione', 'introduction', 'prefazione', 'preface', 'avviso', 'disclaimer']
        if any(ind in text_lower[:1000] for ind in intro_indicators):
            return DocumentType.INTRO

        return DocumentType.GENERAL

    def is_recipe_document(self, text: str) -> bool:
        """Check if document contains recipes that should use recipe-aware chunking."""
        return self.detect_document_type(text) == DocumentType.RECIPE_BOOK

    def extract_recipe_metadata(self, recipe_text: str, recipe_number: int = None) -> Dict:
        """
        Extract metadata from a recipe chunk.

        Args:
            recipe_text: The full text of the recipe
            recipe_number: The recipe number if already extracted

        Returns:
            Dict with recipe metadata (title, number, seasonality, category, page)
        """
        metadata = {
            'recipe_number': recipe_number,
            'title': None,
            'seasonality': None,
            'category': self.current_category,
            'page': None,
            'document_type': DocumentType.RECIPE_BOOK.value,
            'chunk_type': 'recipe'
        }

        # Extract recipe number if not provided
        if recipe_number is None:
            number_match = re.search(r'^(\d{1,3})\.\s+', recipe_text, re.MULTILINE)
            if number_match:
                metadata['recipe_number'] = int(number_match.group(1))

        # Extract seasonality FIRST - it's on its own line after "Stagionlità:" or "Stagionalità:"
        # Format: "Stagionlità:\nestate\n" or "Stagionlità:\nautunno, inverno,\nprimavera\n"
        # Use \w+ to match the word after the colon to avoid unicode character class issues
        season_words = r'(?:estate|autunno|inverno|primavera|tutte)'
        # Match either spelling explicitly to avoid unicode issues with character classes
        seasonality_match = re.search(
            r'(?:Stagionalità|Stagionlità):\n(' + season_words + r'(?:,?\s*\n?' + season_words + r')*)',
            recipe_text,
            re.IGNORECASE
        )
        if seasonality_match:
            seasonality = seasonality_match.group(1).strip()
            # Normalize: remove extra whitespace and newlines, join with comma
            seasonality = ', '.join(s.strip() for s in re.split(r'[,\n]+', seasonality) if s.strip())
            metadata['seasonality'] = seasonality

        # Extract full title - look for text between recipe number and INGREDIENTI
        title_match = re.search(
            r'^\d{1,3}\.\s+(.+?)(?=\n*INGREDIENTI)',
            recipe_text,
            re.MULTILINE | re.DOTALL
        )
        if title_match:
            raw_title = title_match.group(1)
            # Remove the Stagionlità/Stagionalità section from the title (including the season value line)
            cleaned_title = re.sub(
                r'\s*(?:Stagionalità|Stagionlità):\n' + season_words + r'(?:,?\s*\n?' + season_words + r')*\n?',
                ' ',
                raw_title,
                flags=re.IGNORECASE
            )
            # Normalize whitespace and newlines
            cleaned_title = ' '.join(cleaned_title.split())
            metadata['title'] = cleaned_title.strip()

        # Extract page number (look for copyright footer pattern)
        page_match = re.search(r'©.*?(\d+)\s*$', recipe_text)
        if page_match:
            metadata['page'] = int(page_match.group(1))

        return metadata

    def create_breadcrumb(self, metadata: Dict) -> str:
        """
        Create a breadcrumb string from recipe metadata.

        Format: [Categoria: Colazioni | Ricetta #1 | Titolo: Hummus dolce | Pagina: 11 | Stagionalità: estate]
        """
        parts = []

        if metadata.get('category'):
            parts.append(f"Categoria: {metadata['category']}")

        if metadata.get('recipe_number'):
            parts.append(f"Ricetta #{metadata['recipe_number']}")

        if metadata.get('title'):
            parts.append(f"Titolo: {metadata['title']}")

        if metadata.get('page'):
            parts.append(f"Pagina: {metadata['page']}")

        if metadata.get('seasonality'):
            parts.append(f"Stagionalità: {metadata['seasonality']}")

        if parts:
            return f"[{' | '.join(parts)}]"
        return ""

    def split_into_recipes(self, text: str) -> List[Dict]:
        """
        Split document text into individual recipes.

        Each recipe includes:
        - The full recipe text (title, ingredients, preparation)
        - Metadata extracted from the recipe
        - Breadcrumb prefix for better retrieval

        Args:
            text: Full document text

        Returns:
            List of dicts with 'text', 'metadata', 'breadcrumb' keys
        """
        recipes = []

        # Find all numbered recipe starts
        recipe_starts = []
        for match in RECIPE_PATTERNS['numbered_recipe'].finditer(text):
            recipe_starts.append({
                'position': match.start(),
                'number': int(match.group(1)),
                'title': match.group(2).strip()
            })

        if not recipe_starts:
            logger.warning("[Feature #245] No numbered recipes found in text")
            return []

        logger.info(f"[Feature #245] Found {len(recipe_starts)} recipe boundaries")

        # Track current category from category headers
        category_positions = []
        for match in RECIPE_PATTERNS['category_headers'].finditer(text):
            category_positions.append({
                'position': match.start(),
                'category': match.group(1).strip()
            })

        # Extract each recipe
        for i, start_info in enumerate(recipe_starts):
            # Determine end position (start of next recipe or end of text)
            if i + 1 < len(recipe_starts):
                end_pos = recipe_starts[i + 1]['position']
            else:
                end_pos = len(text)

            recipe_text = text[start_info['position']:end_pos].strip()

            # Update current category based on most recent category header before this recipe
            for cat in category_positions:
                if cat['position'] < start_info['position']:
                    # Normalize category: remove newlines and extra spaces
                    self.current_category = ' '.join(cat['category'].split())

            # Extract metadata
            metadata = self.extract_recipe_metadata(recipe_text, start_info['number'])

            # Create breadcrumb
            breadcrumb = self.create_breadcrumb(metadata)

            # Prepend breadcrumb to recipe text
            if breadcrumb:
                full_text = f"{breadcrumb}\n\n{recipe_text}"
            else:
                full_text = recipe_text

            # Clean up copyright footer noise
            full_text = re.sub(r'©\s*Prevenzione a Tavola.*$', '', full_text, flags=re.MULTILINE).strip()

            recipes.append({
                'text': full_text,
                'metadata': metadata,
                'breadcrumb': breadcrumb,
                'char_count': len(full_text)
            })

        logger.info(f"[Feature #245] Extracted {len(recipes)} recipes with breadcrumbs")
        return recipes

    def chunk_recipe_document(self, text: str) -> List['SemanticChunk']:
        """
        Chunk a recipe document, keeping each recipe as a single chunk.

        Args:
            text: Full document text

        Returns:
            List of SemanticChunk objects, one per recipe
        """
        # Extract recipes
        recipes = self.split_into_recipes(text)

        if not recipes:
            logger.warning("[Feature #245] No recipes extracted, falling back to general chunking")
            return []

        chunks = []
        total_recipes = len(recipes)

        for i, recipe in enumerate(recipes):
            # Create SemanticChunk with recipe metadata
            # FEATURE #246: Explicitly set section_type to 'recipe' for retrieval boost
            chunk = SemanticChunk(
                text=recipe['text'],
                section_title=recipe['metadata'].get('title'),
                chunk_type='recipe',
                position_in_doc=i,
                total_sections=total_recipes,
                context_prefix=None,  # Recipes are self-contained
                section_type=SECTION_TYPE_RECIPE  # FEATURE #246: Explicit recipe type
            )

            # Add extended metadata to chunk
            chunk_dict = chunk.to_dict()
            chunk_dict['metadata'].update({
                'recipe_number': recipe['metadata'].get('recipe_number'),
                'seasonality': recipe['metadata'].get('seasonality'),
                'category': recipe['metadata'].get('category'),
                'page': recipe['metadata'].get('page'),
                'document_type': DocumentType.RECIPE_BOOK.value,
                'breadcrumb': recipe['breadcrumb']
            })

            # Log if recipe exceeds normal chunk size but is within recipe limit
            if len(recipe['text']) > MAX_CHUNK_SIZE:
                if len(recipe['text']) <= RECIPE_MAX_CHUNK_SIZE:
                    logger.info(f"[Feature #245] Recipe #{recipe['metadata'].get('recipe_number')} "
                               f"exceeds MAX_CHUNK_SIZE ({len(recipe['text'])} chars) but within RECIPE_MAX_CHUNK_SIZE")
                else:
                    logger.warning(f"[Feature #245] Recipe #{recipe['metadata'].get('recipe_number')} "
                                  f"exceeds RECIPE_MAX_CHUNK_SIZE ({len(recipe['text'])} chars)")

            chunks.append(chunk)

        logger.info(f"[Feature #245] Created {len(chunks)} recipe chunks")
        return chunks


class SemanticChunk:
    """Represents a semantically coherent chunk of text with metadata."""

    def __init__(
        self,
        text: str,
        section_title: Optional[str] = None,
        chunk_type: str = "paragraph",
        position_in_doc: int = 0,
        total_sections: int = 0,
        context_prefix: Optional[str] = None,
        section_type: Optional[str] = None  # FEATURE #246: recipe, index, intro, general
    ):
        self.text = text
        self.section_title = section_title
        self.chunk_type = chunk_type  # paragraph, list, table, code, heading
        self.position_in_doc = position_in_doc
        self.total_sections = total_sections
        self.context_prefix = context_prefix  # Context from previous chunk
        # FEATURE #246: Auto-detect section_type if not provided
        self.section_type = section_type if section_type else detect_chunk_section_type(text)

    def to_dict(self) -> Dict:
        """Convert chunk to dictionary format."""
        return {
            "text": self.text,
            "metadata": {
                "section_title": self.section_title,
                "chunk_type": self.chunk_type,
                "position_in_doc": self.position_in_doc,
                "total_sections": self.total_sections,
                "char_count": len(self.text),
                "context_prefix": self.context_prefix,
                "has_context": self.context_prefix is not None,
                # FEATURE #246: Section type for retrieval priority
                "section_type": self.section_type
            }
        }

    def get_full_text(self) -> str:
        """Get the full text including context prefix for embedding."""
        if self.context_prefix:
            return f"[Previous context: {self.context_prefix}]\n\n{self.text}"
        return self.text


class DocumentStructure:
    """Detected structural elements in a document."""

    def __init__(self):
        self.sections: List[Dict] = []  # List of {type, text, title, start, end}
        self.headings: List[Dict] = []
        self.paragraphs: List[Dict] = []
        self.lists: List[Dict] = []
        self.tables: List[Dict] = []


class SemanticChunker:
    """
    Intelligent text chunking that preserves document structure and semantics.

    Features:
    - Detects headings (markdown, ALL CAPS, numbered sections)
    - Preserves paragraphs, lists, and tables
    - Uses LLM to find semantic transitions in long sections
    - Merges short sections when semantically related
    - Adds rich metadata for better retrieval
    - Falls back to fixed-size chunking if LLM unavailable
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        ollama_base_url: str = "http://localhost:11434",
        max_chunk_size: int = None,
        chunk_overlap: int = None
    ):
        self.api_key = api_key
        self.llm_model = llm_model
        self.ollama_base_url = ollama_base_url
        self.openai_client = None

        # Override global constants if provided
        if max_chunk_size is not None:
            global MAX_CHUNK_SIZE
            MAX_CHUNK_SIZE = max_chunk_size
            logger.info(f"Using custom MAX_CHUNK_SIZE: {max_chunk_size}")

        if chunk_overlap is not None:
            # Store for potential future use (currently context-based overlap is used)
            self.chunk_overlap = chunk_overlap
            logger.info(f"Chunk overlap set to: {chunk_overlap}")

        # Initialize OpenAI client if API key provided
        if api_key and api_key.startswith('sk-') and len(api_key) > 20:
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info(f"Initialized SemanticChunker with OpenAI model: {llm_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")

    def detect_structure(self, text: str) -> DocumentStructure:
        """
        Detect structural elements in the document.

        Identifies:
        - Markdown headings (# ## ###)
        - ALL CAPS headings
        - Numbered sections (1. 2. 3. or 1.1, 1.2)
        - Lists (bullets, numbered)
        - Paragraphs (text blocks separated by newlines)
        - Tables (markdown tables or aligned text)

        Returns:
            DocumentStructure object with detected elements
        """
        structure = DocumentStructure()
        lines = text.split('\n')
        current_pos = 0

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Skip empty lines
            if not line:
                current_pos += len(lines[i]) + 1  # +1 for newline
                i += 1
                continue

            # Detect markdown heading (# ## ###)
            if re.match(r'^#{1,6}\s+.+', line):
                level = len(re.match(r'^(#+)', line).group(1))
                title = re.sub(r'^#+\s+', '', line)
                structure.headings.append({
                    'type': 'markdown_heading',
                    'level': level,
                    'title': title,
                    'text': line,
                    'start': current_pos,
                    'end': current_pos + len(lines[i])
                })
                structure.sections.append(structure.headings[-1])
                current_pos += len(lines[i]) + 1
                i += 1
                continue

            # Detect ALL CAPS heading (3+ words, all caps, short line)
            if (len(line) < 80 and
                len(line.split()) >= 3 and
                line.isupper() and
                not line.endswith(('.', ',', ':', ';'))):
                structure.headings.append({
                    'type': 'caps_heading',
                    'title': line,
                    'text': line,
                    'start': current_pos,
                    'end': current_pos + len(lines[i])
                })
                structure.sections.append(structure.headings[-1])
                current_pos += len(lines[i]) + 1
                i += 1
                continue

            # Detect numbered section (1. Text or 1.1 Text)
            numbered_match = re.match(r'^(\d+\.(?:\d+\.)*)\s+(.+)', line)
            if numbered_match:
                section_num = numbered_match.group(1)
                title = numbered_match.group(2)
                structure.headings.append({
                    'type': 'numbered_heading',
                    'number': section_num,
                    'title': title,
                    'text': line,
                    'start': current_pos,
                    'end': current_pos + len(lines[i])
                })
                structure.sections.append(structure.headings[-1])
                current_pos += len(lines[i]) + 1
                i += 1
                continue

            # Detect bullet list (-, *, •, ◦)
            if re.match(r'^[-*•◦]\s+.+', line):
                # Collect all consecutive list items
                list_lines = [line]
                list_start = current_pos
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if re.match(r'^[-*•◦]\s+.+', next_line):
                        list_lines.append(next_line)
                        j += 1
                    elif not next_line:  # Empty line
                        j += 1
                        break
                    else:
                        break

                list_text = '\n'.join(lines[i:j])
                list_end = current_pos + len(list_text)
                structure.lists.append({
                    'type': 'bullet_list',
                    'text': list_text,
                    'start': list_start,
                    'end': list_end,
                    'items': list_lines
                })
                structure.sections.append(structure.lists[-1])

                # Update position and index
                for k in range(i, j):
                    current_pos += len(lines[k]) + 1
                i = j
                continue

            # Detect numbered list (1. 2. 3.)
            if re.match(r'^\d+\.\s+.+', line):
                list_lines = [line]
                list_start = current_pos
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if re.match(r'^\d+\.\s+.+', next_line):
                        list_lines.append(next_line)
                        j += 1
                    elif not next_line:
                        j += 1
                        break
                    else:
                        break

                list_text = '\n'.join(lines[i:j])
                list_end = current_pos + len(list_text)
                structure.lists.append({
                    'type': 'numbered_list',
                    'text': list_text,
                    'start': list_start,
                    'end': list_end,
                    'items': list_lines
                })
                structure.sections.append(structure.lists[-1])

                for k in range(i, j):
                    current_pos += len(lines[k]) + 1
                i = j
                continue

            # Detect markdown table (| col1 | col2 |)
            if '|' in line and line.count('|') >= 2:
                table_lines = [line]
                table_start = current_pos
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if '|' in next_line:
                        table_lines.append(next_line)
                        j += 1
                    elif not next_line:
                        j += 1
                        break
                    else:
                        break

                if len(table_lines) >= 2:  # At least header + separator or header + data
                    table_text = '\n'.join(lines[i:j])
                    table_end = current_pos + len(table_text)
                    structure.tables.append({
                        'type': 'markdown_table',
                        'text': table_text,
                        'start': table_start,
                        'end': table_end
                    })
                    structure.sections.append(structure.tables[-1])

                    for k in range(i, j):
                        current_pos += len(lines[k]) + 1
                    i = j
                    continue

            # Collect paragraph (consecutive non-empty lines without special formatting)
            para_lines = [line]
            para_start = current_pos
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:  # Empty line ends paragraph
                    break
                # Check if next line is a special element
                if (re.match(r'^#{1,6}\s+.+', next_line) or
                    re.match(r'^[-*•◦]\s+.+', next_line) or
                    re.match(r'^\d+\.\s+.+', next_line) or
                    '|' in next_line):
                    break
                para_lines.append(next_line)
                j += 1

            para_text = ' '.join(para_lines)  # Join with space for better readability
            para_end = current_pos + sum(len(lines[k]) + 1 for k in range(i, j))
            structure.paragraphs.append({
                'type': 'paragraph',
                'text': para_text,
                'start': para_start,
                'end': para_end
            })
            structure.sections.append(structure.paragraphs[-1])

            for k in range(i, j):
                current_pos += len(lines[k]) + 1
            i = j

        logger.info(f"Detected structure: {len(structure.headings)} headings, "
                   f"{len(structure.paragraphs)} paragraphs, {len(structure.lists)} lists, "
                   f"{len(structure.tables)} tables")

        return structure

    async def find_semantic_split_point(self, text: str, use_ollama: bool = False) -> Optional[int]:
        """
        Use LLM to find the best semantic transition point in a long section.

        Args:
            text: Text to analyze
            use_ollama: Whether to use Ollama instead of OpenAI

        Returns:
            Character position where to split, or None if no good split point
        """
        # Prepare prompt
        prompt = f"""You are analyzing a text chunk to find the best place to split it into two semantically coherent parts.

TEXT TO ANALYZE:
{text[:1500]}

TASK: Find the position where the topic or subject changes most significantly.
This should be a natural breakpoint where the previous content ends and new content begins.

Look for:
- Topic transitions
- New subtopics
- Context shifts
- End of one concept and start of another

Respond with ONLY a number indicating the character position (0 to {len(text[:1500])}) where the split should occur.
If there's no good split point, respond with "NONE".

Example response: "450" or "NONE"
"""

        try:
            if use_ollama:
                # Use Ollama API
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.ollama_base_url}/api/generate",
                        json={
                            "model": self.llm_model.replace("ollama:", ""),
                            "prompt": prompt,
                            "stream": False
                        }
                    )

                    if response.status_code == 200:
                        data = response.json()
                        answer = data.get("response", "").strip()
                    else:
                        logger.warning(f"Ollama API error: {response.status_code}")
                        return None
            else:
                # Use OpenAI API
                if not self.openai_client:
                    logger.warning("OpenAI client not initialized")
                    return None

                response = self.openai_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": "You are a text analysis assistant. Respond only with numbers or 'NONE'."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=50
                )
                answer = response.choices[0].message.content.strip()

            # Parse response
            if answer.upper() == "NONE":
                return None

            # Extract number from response
            numbers = re.findall(r'\d+', answer)
            if numbers:
                position = int(numbers[0])
                # Validate position is reasonable
                if 0 < position < len(text[:1500]) and position > MIN_CHUNK_SIZE:
                    logger.info(f"LLM suggested split point at position {position}")
                    return position

            return None

        except Exception as e:
            logger.error(f"Error finding semantic split point: {e}")
            return None

    async def split_long_section(
        self,
        text: str,
        section_title: Optional[str] = None,
        use_llm: bool = True
    ) -> List[str]:
        """
        Split a long section (>MAX_CHUNK_SIZE) into smaller semantic chunks.

        Uses LLM to find semantic transition points if available,
        otherwise falls back to sentence boundary splitting.

        Args:
            text: Text to split
            section_title: Optional section title for context
            use_llm: Whether to use LLM for semantic splitting

        Returns:
            List of text chunks
        """
        if len(text) <= MAX_CHUNK_SIZE:
            return [text]

        chunks = []
        remaining = text

        while len(remaining) > MAX_CHUNK_SIZE:
            # Try to find semantic split point with LLM
            split_point = None

            if use_llm and (self.openai_client or self.ollama_base_url):
                # Use Ollama if OpenAI not available
                use_ollama = not self.openai_client
                split_point = await self.find_semantic_split_point(remaining, use_ollama)

            if split_point and split_point > MIN_CHUNK_SIZE:
                # Use LLM-suggested split point
                chunk = remaining[:split_point].strip()
                remaining = remaining[split_point:].strip()
                chunks.append(chunk)
                logger.info(f"Split section at LLM-suggested point: {split_point}")
            else:
                # Fall back to sentence boundary splitting
                # Find sentence break around IDEAL_CHUNK_SIZE
                search_start = max(MIN_CHUNK_SIZE, IDEAL_CHUNK_SIZE - 200)
                search_end = min(len(remaining), IDEAL_CHUNK_SIZE + 200)

                # Look for sentence boundaries
                best_break = None
                for sep in ['. ', '! ', '? ', '\n\n', '\n', '; ']:
                    pos = remaining.rfind(sep, search_start, search_end)
                    if pos > MIN_CHUNK_SIZE:
                        best_break = pos + len(sep)
                        break

                if best_break:
                    chunk = remaining[:best_break].strip()
                    remaining = remaining[best_break:].strip()
                    chunks.append(chunk)
                else:
                    # No good break found, force split at word boundary
                    pos = remaining.rfind(' ', search_start, search_end)
                    if pos > MIN_CHUNK_SIZE:
                        chunk = remaining[:pos].strip()
                        remaining = remaining[pos:].strip()
                        chunks.append(chunk)
                    else:
                        # Last resort: take IDEAL_CHUNK_SIZE
                        chunk = remaining[:IDEAL_CHUNK_SIZE].strip()
                        remaining = remaining[IDEAL_CHUNK_SIZE:].strip()
                        chunks.append(chunk)

        # Add remaining text as final chunk
        if remaining.strip():
            chunks.append(remaining.strip())

        logger.info(f"Split long section into {len(chunks)} chunks")
        return chunks

    def extract_context_summary(self, text: str, max_sentences: int = 2) -> str:
        """
        Extract the last 1-2 sentences from a chunk to use as context for the next chunk.

        Args:
            text: The text to extract context from
            max_sentences: Maximum number of sentences to extract (default 2)

        Returns:
            String containing the last 1-2 sentences, or empty string if text is too short
        """
        if not text or len(text.strip()) < 50:
            return ""

        text = text.strip()

        # Find sentence boundaries (., !, ?)
        sentence_endings = []
        for match in re.finditer(r'[.!?]\s+', text):
            sentence_endings.append(match.end())

        # If no sentence endings found, take last 150 characters as context
        if not sentence_endings:
            return text[-150:].strip() if len(text) > 150 else text

        # Get the last 1-2 sentences
        if len(sentence_endings) >= max_sentences:
            # Find the position of the (max_sentences)th-to-last sentence
            start_pos = sentence_endings[-max_sentences]
            context = text[start_pos:].strip()
        else:
            # Take all sentences if fewer than max_sentences
            context = text[sentence_endings[0]:].strip() if sentence_endings else text

        # Limit context length to 300 characters max
        if len(context) > 300:
            # Find a good breakpoint
            last_space = context.rfind(' ', 250, 300)
            if last_space > 0:
                context = context[:last_space] + "..."
            else:
                context = context[:300] + "..."

        return context

    def merge_short_sections(self, sections: List[Dict]) -> List[Dict]:
        """
        Merge consecutive short sections (<MIN_CHUNK_SIZE) into larger chunks.

        Args:
            sections: List of section dictionaries

        Returns:
            List of merged section dictionaries
        """
        if not sections:
            return []

        merged = []
        buffer = []
        buffer_size = 0

        for section in sections:
            text = section.get('text', '')
            text_len = len(text)

            # If adding this section would exceed MAX_CHUNK_SIZE, flush buffer
            if buffer and buffer_size + text_len > MAX_CHUNK_SIZE:
                # Merge buffer into one section
                merged_text = '\n\n'.join(s.get('text', '') for s in buffer)
                merged_section = {
                    'type': 'merged',
                    'text': merged_text,
                    'start': buffer[0]['start'],
                    'end': buffer[-1]['end'],
                    'original_sections': len(buffer)
                }
                merged.append(merged_section)
                buffer = []
                buffer_size = 0

            # Add section to buffer if it's short
            if text_len < MIN_CHUNK_SIZE:
                buffer.append(section)
                buffer_size += text_len
            else:
                # Flush buffer first if it exists
                if buffer:
                    merged_text = '\n\n'.join(s.get('text', '') for s in buffer)
                    merged_section = {
                        'type': 'merged',
                        'text': merged_text,
                        'start': buffer[0]['start'],
                        'end': buffer[-1]['end'],
                        'original_sections': len(buffer)
                    }
                    merged.append(merged_section)
                    buffer = []
                    buffer_size = 0

                # Add current section as-is
                merged.append(section)

        # Flush remaining buffer
        if buffer:
            merged_text = '\n\n'.join(s.get('text', '') for s in buffer)
            merged_section = {
                'type': 'merged',
                'text': merged_text,
                'start': buffer[0]['start'],
                'end': buffer[-1]['end'],
                'original_sections': len(buffer)
            }
            merged.append(merged_section)

        logger.info(f"Merged {len(sections)} sections into {len(merged)} chunks")
        return merged

    async def chunk_structured_elements(
        self,
        elements: List,  # List of DocumentElement from document_structure_extractor
        use_llm: bool = True
    ) -> List[SemanticChunk]:
        """
        Chunk pre-extracted structured elements from document.

        FEATURE #134: This method accepts structured elements (with type, content, level)
        directly from the document structure extractor, preserving heading hierarchy
        and document organization.

        FEATURE #245: Now includes recipe-aware chunking for recipe documents.

        Process:
        1. FEATURE #245: Check if document is a recipe book (use recipe-aware chunking)
        2. Convert structured elements to internal section format
        3. Split at major section boundaries (headings)
        4. Split long sections using LLM semantic analysis
        5. Merge short sections to meet minimum size
        6. Add metadata to each chunk

        Args:
            elements: List of DocumentElement objects from structure extractor
            use_llm: Whether to use LLM for semantic splitting (default True)

        Returns:
            List of SemanticChunk objects with text and metadata
        """
        if not elements:
            logger.warning("No structured elements provided to chunker")
            return []

        logger.info(f"Starting semantic chunking for {len(elements)} structured elements")

        # FEATURE #245: Combine all element content to check for recipe document
        full_text = '\n\n'.join(elem.content for elem in elements if elem.content)
        recipe_chunker = RecipeChunker()
        if recipe_chunker.is_recipe_document(full_text):
            logger.info("[Feature #245] Detected recipe document from structured elements, using recipe-aware chunking")
            recipe_chunks = recipe_chunker.chunk_recipe_document(full_text)
            if recipe_chunks:
                logger.info(f"[Feature #245] Created {len(recipe_chunks)} recipe chunks from structured elements")
                return recipe_chunks
            logger.warning("[Feature #245] Recipe chunking returned no results, falling back to general chunking")

        # Step 1: Convert structured elements to internal format
        sections = []
        for i, elem in enumerate(elements):
            # Convert DocumentElement to dict format expected by chunker
            elem_type = elem.type.value if hasattr(elem.type, 'value') else str(elem.type)
            section = {
                'type': elem_type,
                'text': elem.content,
                'title': elem.content[:100] if elem_type == 'heading' else None,
                'level': elem.level,
                'start': i * 100,  # Placeholder positions
                'end': i * 100 + len(elem.content),
                'metadata': elem.metadata
            }
            sections.append(section)

        logger.info(f"Converted {len(elements)} elements to {len(sections)} sections")

        # Step 2: Merge short sections
        merged_sections = self.merge_short_sections(sections)

        # Step 3: Split long sections and create semantic chunks
        chunks = []
        current_heading = None

        for i, section in enumerate(merged_sections):
            section_type = section.get('type', 'paragraph')
            text_content = section.get('text', '').strip()

            if not text_content:
                continue

            # Track current heading for context
            if 'heading' in section_type:
                current_heading = section.get('title', text_content[:100])

            # Split long sections
            if len(text_content) > MAX_CHUNK_SIZE:
                logger.info(f"Splitting long section ({len(text_content)} chars)")
                split_texts = await self.split_long_section(
                    text_content,
                    section_title=current_heading,
                    use_llm=use_llm
                )

                for split_text in split_texts:
                    chunk = SemanticChunk(
                        text=split_text,
                        section_title=current_heading,
                        chunk_type=section_type,
                        position_in_doc=i,
                        total_sections=len(merged_sections)
                    )
                    chunks.append(chunk)
            else:
                # Section is within size limits
                chunk = SemanticChunk(
                    text=text_content,
                    section_title=current_heading,
                    chunk_type=section_type,
                    position_in_doc=i,
                    total_sections=len(merged_sections)
                )
                chunks.append(chunk)

        logger.info(f"Created {len(chunks)} semantic chunks from {len(merged_sections)} sections")

        # Step 4: Add intelligent context overlap between chunks
        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            context = self.extract_context_summary(prev_chunk.text)
            if context:
                chunks[i].context_prefix = context

        # Validate chunk sizes
        for i, chunk in enumerate(chunks):
            if len(chunk.text) < MIN_CHUNK_SIZE:
                logger.warning(f"Chunk {i} is below minimum size: {len(chunk.text)} chars")
            if len(chunk.text) > MAX_CHUNK_SIZE:
                logger.warning(f"Chunk {i} exceeds maximum size: {len(chunk.text)} chars")

        return chunks

    async def chunk_text(self, text: str, use_llm: bool = True) -> List[SemanticChunk]:
        """
        Main entry point for semantic chunking.

        Process:
        1. FEATURE #245: Check if document is a recipe book (use recipe-aware chunking)
        2. Detect document structure (headings, paragraphs, lists, tables)
        3. Split at major section boundaries
        4. Split long sections using LLM semantic analysis
        5. Merge short sections to meet minimum size
        6. Add metadata to each chunk

        Args:
            text: Text to chunk
            use_llm: Whether to use LLM for semantic splitting (default True)

        Returns:
            List of SemanticChunk objects with text and metadata
        """
        if not text or len(text.strip()) == 0:
            logger.warning("Empty text provided to chunker")
            return []

        logger.info(f"Starting semantic chunking for {len(text)} characters")

        # FEATURE #245: Check if this is a recipe document
        recipe_chunker = RecipeChunker()
        if recipe_chunker.is_recipe_document(text):
            logger.info("[Feature #245] Detected recipe document, using recipe-aware chunking")
            recipe_chunks = recipe_chunker.chunk_recipe_document(text)
            if recipe_chunks:
                logger.info(f"[Feature #245] Created {len(recipe_chunks)} recipe chunks")
                return recipe_chunks
            logger.warning("[Feature #245] Recipe chunking returned no results, falling back to general chunking")

        # Step 1: Detect document structure
        structure = self.detect_structure(text)

        if not structure.sections:
            # No structure detected, fall back to simple paragraph splitting
            logger.warning("No structure detected, falling back to paragraph splitting")
            paragraphs = text.split('\n\n')
            structure.sections = [
                {'type': 'paragraph', 'text': p.strip(), 'start': 0, 'end': len(p)}
                for p in paragraphs if p.strip()
            ]

        # Step 2: Merge short sections
        sections = self.merge_short_sections(structure.sections)

        # Step 3: Split long sections and create semantic chunks
        chunks = []
        current_heading = None

        for i, section in enumerate(sections):
            section_type = section.get('type', 'paragraph')
            text_content = section.get('text', '').strip()

            if not text_content:
                continue

            # Track current heading for context
            if 'heading' in section_type:
                current_heading = section.get('title', text_content[:100])

            # Split long sections
            if len(text_content) > MAX_CHUNK_SIZE:
                logger.info(f"Splitting long section ({len(text_content)} chars)")
                split_texts = await self.split_long_section(
                    text_content,
                    section_title=current_heading,
                    use_llm=use_llm
                )

                for split_text in split_texts:
                    chunk = SemanticChunk(
                        text=split_text,
                        section_title=current_heading,
                        chunk_type=section_type,
                        position_in_doc=i,
                        total_sections=len(sections)
                    )
                    chunks.append(chunk)
            else:
                # Section is within size limits
                chunk = SemanticChunk(
                    text=text_content,
                    section_title=current_heading,
                    chunk_type=section_type,
                    position_in_doc=i,
                    total_sections=len(sections)
                )
                chunks.append(chunk)

        logger.info(f"Created {len(chunks)} semantic chunks from {len(sections)} sections")

        # Step 4: Add intelligent context overlap between chunks
        for i in range(1, len(chunks)):
            # Get context from previous chunk
            prev_chunk = chunks[i - 1]
            context = self.extract_context_summary(prev_chunk.text)

            if context:
                chunks[i].context_prefix = context
                logger.debug(f"Added context overlap to chunk {i}: '{context[:50]}...'")

        chunks_with_context = sum(1 for c in chunks if c.context_prefix)
        logger.info(f"Added context overlap to {chunks_with_context}/{len(chunks)} chunks")

        # Validate chunk sizes
        for i, chunk in enumerate(chunks):
            if len(chunk.text) < MIN_CHUNK_SIZE:
                logger.warning(f"Chunk {i} is below minimum size: {len(chunk.text)} chars")
            if len(chunk.text) > MAX_CHUNK_SIZE:
                logger.warning(f"Chunk {i} exceeds maximum size: {len(chunk.text)} chars")

        return chunks

    def chunk_text_sync(self, text: str) -> List[str]:
        """
        Synchronous fallback chunking method.

        Uses structure detection but no LLM splitting.
        Suitable for use when async is not available.

        Args:
            text: Text to chunk

        Returns:
            List of text strings
        """
        if not text or len(text.strip()) == 0:
            return []

        # Detect structure
        structure = self.detect_structure(text)

        if not structure.sections:
            # Fall back to naive chunking
            return self._naive_chunking(text)

        # Merge short sections
        sections = self.merge_short_sections(structure.sections)

        # Simple splitting for long sections (no LLM)
        chunks = []
        for section in sections:
            text_content = section.get('text', '').strip()
            if not text_content:
                continue

            if len(text_content) > MAX_CHUNK_SIZE:
                # Split at sentence boundaries
                split_chunks = self._split_at_sentences(text_content)
                chunks.extend(split_chunks)
            else:
                chunks.append(text_content)

        return chunks

    def _split_at_sentences(self, text: str) -> List[str]:
        """Split text at sentence boundaries to meet size constraints."""
        chunks = []
        remaining = text

        while len(remaining) > MAX_CHUNK_SIZE:
            # Find sentence break around IDEAL_CHUNK_SIZE
            search_start = max(MIN_CHUNK_SIZE, IDEAL_CHUNK_SIZE - 200)
            search_end = min(len(remaining), IDEAL_CHUNK_SIZE + 200)

            best_break = None
            for sep in ['. ', '! ', '? ', '\n\n', '\n']:
                pos = remaining.rfind(sep, search_start, search_end)
                if pos > MIN_CHUNK_SIZE:
                    best_break = pos + len(sep)
                    break

            if best_break:
                chunks.append(remaining[:best_break].strip())
                remaining = remaining[best_break:].strip()
            else:
                # Force split at word boundary
                pos = remaining.rfind(' ', search_start, search_end)
                if pos > MIN_CHUNK_SIZE:
                    chunks.append(remaining[:pos].strip())
                    remaining = remaining[pos:].strip()
                else:
                    chunks.append(remaining[:IDEAL_CHUNK_SIZE].strip())
                    remaining = remaining[IDEAL_CHUNK_SIZE:].strip()

        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks

    def _naive_chunking(self, text: str) -> List[str]:
        """Naive fixed-size chunking as ultimate fallback."""
        chunks = []
        text = ' '.join(text.split())  # Normalize whitespace
        start = 0

        while start < len(text):
            end = start + IDEAL_CHUNK_SIZE

            if end < len(text):
                # Try to break at sentence
                for sep in ['. ', '! ', '? ', '\n']:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + MIN_CHUNK_SIZE:
                        end = last_sep + len(sep)
                        break
                else:
                    # Fall back to word boundary
                    last_space = text.rfind(' ', start, end)
                    if last_space > start + MIN_CHUNK_SIZE:
                        end = last_space + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - 200 if end < len(text) else end  # 200 char overlap

        return chunks
