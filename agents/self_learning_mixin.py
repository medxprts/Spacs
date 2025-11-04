"""
Self-Learning Mixin for Agents

Adds Few-Shot learning capability using your existing 414 corrections database.
Any agent can inherit this to automatically learn from past corrections.
"""

from typing import List, Dict, Optional
from database import SessionLocal
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class SelfLearningMixin:
    """
    Mixin that adds self-learning capability to any agent.

    Uses data_quality_conversations table to find relevant past corrections
    and include them as examples in prompts.

    Usage:
        class MyAgent(OrchestratorAgentBase, SelfLearningMixin):
            def execute(self, task):
                # Get relevant examples
                examples = self.get_relevant_corrections('target', task.parameters['ticker'])

                # Build prompt with examples
                prompt = self.build_prompt_with_learning(
                    field='target',
                    filing_text=filing_text,
                    examples=examples
                )
    """

    def get_relevant_corrections(
        self,
        field: str,
        ticker: Optional[str] = None,
        issue_type: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """
        Query database for relevant past corrections.

        Args:
            field: Field name to get examples for (e.g., 'target', 'ipo_date')
            ticker: Optionally filter by ticker (for SPAC-specific patterns)
            issue_type: Optionally filter by issue type (e.g., 'anomaly', 'data_corruption')
            limit: Max number of examples to return (default 3)

        Returns:
            List of correction examples with original_data, final_fix, learning_notes
        """
        db = SessionLocal()

        try:
            # Build query based on filters
            where_clauses = [
                "final_fix ? :field",  # Has the field we're looking for
                "learning_notes IS NOT NULL"  # Has learning notes
            ]

            params = {'field': field, 'limit': limit}

            if ticker:
                where_clauses.append("ticker = :ticker")
                params['ticker'] = ticker

            if issue_type:
                where_clauses.append("issue_type = :issue_type")
                params['issue_type'] = issue_type

            query = f"""
                SELECT
                    ticker,
                    issue_type,
                    original_data,
                    proposed_fix,
                    final_fix,
                    learning_notes,
                    created_at
                FROM data_quality_conversations
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT :limit
            """

            result = db.execute(text(query), params)
            rows = result.fetchall()

            corrections = []
            for row in rows:
                corrections.append({
                    'ticker': row[0],
                    'issue_type': row[1],
                    'original_data': row[2],
                    'proposed_fix': row[3],
                    'final_fix': row[4],
                    'learning_notes': row[5],
                    'created_at': row[6]
                })

            logger.info(f"[SelfLearning] Found {len(corrections)} relevant corrections for field '{field}'")

            return corrections

        except Exception as e:
            logger.error(f"[SelfLearning] Failed to get corrections: {e}")
            return []

        finally:
            db.close()

    def get_corrections_by_similarity(
        self,
        field: str,
        search_text: str,
        limit: int = 3
    ) -> List[Dict]:
        """
        Get corrections similar to search text (simple keyword matching).

        For semantic similarity, use RAG with vector search (Phase 2).
        This is a simple fallback using PostgreSQL text search.

        Args:
            field: Field name to get examples for
            search_text: Text to search for (e.g., filing excerpt)
            limit: Max number of examples

        Returns:
            List of similar corrections
        """
        db = SessionLocal()

        try:
            # Use PostgreSQL's text search for simple similarity
            query = """
                SELECT
                    ticker,
                    issue_type,
                    original_data,
                    final_fix,
                    learning_notes,
                    created_at
                FROM data_quality_conversations
                WHERE
                    final_fix ? :field
                    AND learning_notes IS NOT NULL
                    AND (
                        learning_notes ILIKE :search
                        OR original_data::text ILIKE :search
                    )
                ORDER BY created_at DESC
                LIMIT :limit
            """

            # Simple keyword search (extract key words from search_text)
            keywords = search_text.lower().split()[:5]  # First 5 words
            search_pattern = '%' + '%'.join(keywords) + '%'

            result = db.execute(
                text(query),
                {'field': field, 'search': search_pattern, 'limit': limit}
            )
            rows = result.fetchall()

            corrections = []
            for row in rows:
                corrections.append({
                    'ticker': row[0],
                    'issue_type': row[1],
                    'original_data': row[2],
                    'final_fix': row[3],
                    'learning_notes': row[4],
                    'created_at': row[5]
                })

            logger.info(f"[SelfLearning] Found {len(corrections)} similar corrections")

            return corrections

        except Exception as e:
            logger.error(f"[SelfLearning] Failed to get similar corrections: {e}")
            return []

        finally:
            db.close()

    def format_corrections_for_prompt(
        self,
        corrections: List[Dict],
        field: str
    ) -> str:
        """
        Format corrections as examples for LLM prompt.

        Args:
            corrections: List of correction dicts from get_relevant_corrections()
            field: Field being extracted

        Returns:
            Formatted string to include in prompt
        """
        if not corrections:
            return ""

        examples_text = "IMPORTANT: Learn from these past corrections:\n\n"

        for i, correction in enumerate(corrections, 1):
            # Extract the specific field value
            final_value = correction['final_fix'].get(field, 'N/A')

            # Get original context if available
            original_text = ""
            if correction['original_data']:
                original_text = str(correction['original_data'])[:200]  # First 200 chars

            examples_text += f"""Example {i} (Ticker: {correction['ticker']}, Issue: {correction['issue_type']}):
- Original data: {original_text}...
- Correct value for '{field}': {final_value}
- Learning note: {correction['learning_notes']}

"""

        return examples_text

    def build_prompt_with_learning(
        self,
        field: str,
        filing_text: str,
        base_instructions: str = "",
        ticker: Optional[str] = None,
        issue_type: Optional[str] = None,
        max_examples: int = 3
    ) -> str:
        """
        Build extraction prompt with few-shot learning examples.

        Args:
            field: Field to extract (e.g., 'target', 'ipo_date')
            filing_text: SEC filing text to extract from
            base_instructions: Additional extraction instructions
            ticker: Optional ticker for SPAC-specific examples
            issue_type: Optional issue type filter
            max_examples: Max number of examples to include

        Returns:
            Complete prompt with examples
        """
        # Get relevant corrections
        corrections = self.get_relevant_corrections(
            field=field,
            ticker=ticker,
            issue_type=issue_type,
            limit=max_examples
        )

        # Format examples
        examples = self.format_corrections_for_prompt(corrections, field)

        # Build complete prompt
        prompt = f"""Extract '{field}' from the SEC filing below.

{examples}

{base_instructions}

SEC Filing Text:
{filing_text}

Extract '{field}' following the patterns from the examples above.
Output ONLY the value (no explanations).
"""

        return prompt

    def get_learning_stats(self) -> Dict:
        """
        Get statistics about available learning data.

        Returns:
            Dict with stats (total corrections, corrections by field, etc.)
        """
        db = SessionLocal()

        try:
            # Total corrections
            total_result = db.execute(text("""
                SELECT COUNT(*)
                FROM data_quality_conversations
                WHERE learning_notes IS NOT NULL
            """))
            total = total_result.scalar()

            # Corrections by issue type
            issue_result = db.execute(text("""
                SELECT issue_type, COUNT(*)
                FROM data_quality_conversations
                WHERE learning_notes IS NOT NULL
                GROUP BY issue_type
                ORDER BY COUNT(*) DESC
            """))
            by_issue = {row[0]: row[1] for row in issue_result.fetchall()}

            # Top fields in corrections
            fields_result = db.execute(text("""
                SELECT
                    jsonb_object_keys(final_fix) as field,
                    COUNT(*) as count
                FROM data_quality_conversations
                WHERE final_fix IS NOT NULL
                GROUP BY field
                ORDER BY count DESC
                LIMIT 10
            """))
            top_fields = {row[0]: row[1] for row in fields_result.fetchall()}

            return {
                'total_corrections': total,
                'corrections_by_issue': by_issue,
                'top_corrected_fields': top_fields
            }

        except Exception as e:
            logger.error(f"[SelfLearning] Failed to get stats: {e}")
            return {}

        finally:
            db.close()
