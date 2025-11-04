"""
RAG Learning Mixin for Agents

Uses vector database (ChromaDB) for semantic similarity search over past corrections.
Better than Few-Shot SQL matching - finds semantically similar corrections, not just exact matches.
"""

from typing import List, Dict, Optional
import chromadb
from chromadb.utils import embedding_functions
import json
import logging

logger = logging.getLogger(__name__)


class RAGLearningMixin:
    """
    Mixin that adds RAG (Retrieval-Augmented Generation) learning to agents.

    Uses ChromaDB vector database for semantic search over 369 corrections.

    Usage:
        class MyAgent(OrchestratorAgentBase, RAGLearningMixin):
            def execute(self, task):
                # Initialize RAG
                self.init_rag()

                # Get semantically similar examples
                examples = self.get_similar_corrections_rag(
                    query="Extracting trust_value for SPAC",
                    n_results=3
                )

                # Build prompt with examples
                prompt = self.build_prompt_with_rag(
                    field='trust_value',
                    filing_text=filing_text,
                    examples=examples
                )
    """

    def __init__(self):
        self.rag_client = None
        self.rag_collection = None
        self.embedding_function = None

    def init_rag(self, db_path: str = "./correction_vector_db"):
        """
        Initialize RAG vector database connection.

        Args:
            db_path: Path to ChromaDB database (default: ./correction_vector_db)

        Call this once in your agent's __init__ or execute method.
        """
        if self.rag_client is not None:
            return  # Already initialized

        try:
            logger.info(f"[RAG] Initializing ChromaDB from {db_path}")

            # Connect to persistent database
            self.rag_client = chromadb.PersistentClient(path=db_path)

            # Use same embedding model as indexing
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            # Get collection
            self.rag_collection = self.rag_client.get_collection(
                name="spac_corrections",
                embedding_function=self.embedding_function
            )

            logger.info(f"[RAG] Connected to vector DB ({self.rag_collection.count()} corrections)")

        except Exception as e:
            logger.error(f"[RAG] Failed to initialize: {e}")
            logger.warning(f"[RAG] Falling back to no learning (database not indexed?)")
            self.rag_client = None
            self.rag_collection = None

    def get_similar_corrections_rag(
        self,
        query: str,
        n_results: int = 3,
        filter_ticker: Optional[str] = None,
        filter_issue_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get semantically similar corrections using RAG.

        Args:
            query: Search query (e.g., "Extracting trust_value for SPAC filing")
            n_results: Number of similar corrections to return
            filter_ticker: Optionally filter by ticker
            filter_issue_type: Optionally filter by issue type

        Returns:
            List of similar corrections with metadata
        """
        if not self.rag_collection:
            logger.warning("[RAG] Vector DB not initialized, returning empty list")
            return []

        try:
            # Build metadata filter
            where_filter = None
            if filter_ticker or filter_issue_type:
                where_filter = {}
                if filter_ticker:
                    where_filter['ticker'] = filter_ticker
                if filter_issue_type:
                    where_filter['issue_type'] = filter_issue_type

            # Semantic search
            results = self.rag_collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter if where_filter else None
            )

            # Format results
            corrections = []
            for i, (doc, metadata, distance) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            )):
                # Parse fields_corrected back to list
                fields = json.loads(metadata.get('fields_corrected', '[]'))

                corrections.append({
                    'document': doc,
                    'ticker': metadata.get('ticker', ''),
                    'issue_type': metadata.get('issue_type', ''),
                    'fields_corrected': fields,
                    'created_at': metadata.get('created_at', ''),
                    'similarity': 1 - distance,  # Convert distance to similarity (0-1)
                    'distance': distance
                })

            logger.info(f"[RAG] Found {len(corrections)} similar corrections (avg similarity: {sum(c['similarity'] for c in corrections) / len(corrections):.2%})")

            return corrections

        except Exception as e:
            logger.error(f"[RAG] Search failed: {e}")
            return []

    def format_rag_corrections_for_prompt(
        self,
        corrections: List[Dict]
    ) -> str:
        """
        Format RAG corrections as examples for LLM prompt.

        Args:
            corrections: List of correction dicts from get_similar_corrections_rag()

        Returns:
            Formatted string to include in prompt
        """
        if not corrections:
            return ""

        examples_text = "IMPORTANT: Learn from these similar past corrections (semantic search):\n\n"

        for i, correction in enumerate(corrections, 1):
            similarity_pct = correction['similarity'] * 100

            examples_text += f"""Example {i} (Similarity: {similarity_pct:.1f}%, Ticker: {correction['ticker']}):
Fields corrected: {', '.join(correction['fields_corrected'])}
Issue type: {correction['issue_type']}

Correction details:
{correction['document']}

---

"""

        return examples_text

    def build_prompt_with_rag(
        self,
        field: str,
        filing_text: str,
        base_instructions: str = "",
        ticker: Optional[str] = None,
        max_examples: int = 3
    ) -> str:
        """
        Build extraction prompt with RAG-retrieved examples.

        Args:
            field: Field to extract (e.g., 'target', 'ipo_date')
            filing_text: SEC filing text to extract from
            base_instructions: Additional extraction instructions
            ticker: Optional ticker (for filtering examples)
            max_examples: Max number of examples to include

        Returns:
            Complete prompt with RAG examples
        """
        # Initialize RAG if not already
        if not self.rag_collection:
            self.init_rag()

        # Build semantic search query
        query = f"Extracting {field} field from SPAC SEC filing"

        # Add ticker context if available
        if ticker:
            query = f"{query} for {ticker}"

        # Get similar corrections
        corrections = self.get_similar_corrections_rag(
            query=query,
            n_results=max_examples,
            filter_ticker=ticker  # Try ticker-specific first
        )

        # If no ticker-specific results, try general search
        if not corrections and ticker:
            corrections = self.get_similar_corrections_rag(
                query=query,
                n_results=max_examples
            )

        # Format examples
        examples = self.format_rag_corrections_for_prompt(corrections)

        # Build complete prompt
        prompt = f"""Extract '{field}' from the SEC filing below.

{examples}

{base_instructions}

SEC Filing Text:
{filing_text}

Extract '{field}' following the patterns from the similar corrections above.
Output ONLY the value (no explanations).
"""

        return prompt

    def get_rag_stats(self) -> Dict:
        """
        Get statistics about RAG vector database.

        Returns:
            Dict with stats (total corrections, average similarity, etc.)
        """
        if not self.rag_collection:
            return {'initialized': False, 'error': 'RAG not initialized'}

        try:
            total = self.rag_collection.count()

            # Get sample to check quality
            sample = self.rag_collection.peek(limit=5)

            return {
                'initialized': True,
                'total_corrections': total,
                'embedding_model': 'all-MiniLM-L6-v2',
                'embedding_dimension': 384,
                'sample_tickers': [m.get('ticker', '') for m in sample.get('metadatas', [])][:5]
            }

        except Exception as e:
            logger.error(f"[RAG] Failed to get stats: {e}")
            return {'initialized': False, 'error': str(e)}
