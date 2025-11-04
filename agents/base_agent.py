"""
Base Agent Class

All specialist agents inherit from this base class

Agents should consult data_source_reference.py for:
- Which filing types to process for each field
- Data precedence rules (8-K for events, 10-Q for periodic data)
- Exhibit priority (EX-2.1, EX-99.1, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime

# Import data source reference for all agents
from agents.data_source_reference import (
    get_data_source,
    should_process_filing_for_field,
    is_primary_source,
    get_exhibit_location,
    get_timeliness_guidance,
)


class BaseAgent(ABC):
    """Base class for all specialist agents"""

    def __init__(self, name: str):
        self.name = name
        self.processed_count = 0
        self.error_count = 0
        self.last_run = None

    @abstractmethod
    async def can_process(self, filing: Dict) -> bool:
        """
        Determine if this agent can process the given filing

        Args:
            filing: Filing metadata dict

        Returns:
            bool: True if agent can process this filing
        """
        pass

    @abstractmethod
    async def process(self, filing: Dict) -> Optional[Dict]:
        """
        Process the filing and extract relevant data

        Args:
            filing: Filing metadata and content

        Returns:
            Dict with extracted data, or None if processing failed
        """
        pass

    async def execute(self, filing: Dict) -> Optional[Dict]:
        """
        Execute agent processing with error handling and logging

        Returns:
            Processing result or None
        """
        try:
            self.last_run = datetime.now()

            # Check if agent can process this filing
            if not await self.can_process(filing):
                return None

            # Process filing
            result = await self.process(filing)

            if result:
                self.processed_count += 1
                print(f"   ✓ {self.name}: Processed successfully")
            else:
                print(f"   ℹ️  {self.name}: No data extracted")

            return result

        except Exception as e:
            self.error_count += 1
            print(f"   ❌ {self.name}: Error - {e}")
            return None

    def get_stats(self) -> Dict:
        """Get agent statistics"""
        return {
            'name': self.name,
            'processed_count': self.processed_count,
            'error_count': self.error_count,
            'last_run': self.last_run.isoformat() if self.last_run else None
        }

    def check_data_source(self, field_name: str, filing_type: str) -> Dict:
        """
        Check if this filing is an appropriate source for a field

        Args:
            field_name: Database field (e.g., 'target', 'trust_cash')
            filing_type: SEC filing type (e.g., '8-K', '10-Q')

        Returns:
            Dict with source validation info
        """
        source = get_data_source(field_name)
        if not source:
            return {
                'valid_source': False,
                'reason': f"No source information for field '{field_name}'"
            }

        is_valid = should_process_filing_for_field(field_name, filing_type)
        is_primary = is_primary_source(field_name, filing_type)

        return {
            'valid_source': is_valid,
            'is_primary_source': is_primary,
            'primary_source': source.primary_source,
            'precedence_rule': source.precedence_rule,
            'location': source.location,
            'timeliness': source.timeliness,
        }

    def get_timeliness_guidance(self) -> str:
        """Get comprehensive timeliness guidance for this agent"""
        return get_timeliness_guidance()

    # ===== PROACTIVE EXTRACTION LEARNING METHODS =====

    def get_lessons_for_field(self, field: str) -> Dict:
        """
        Get past learnings for a field (wrapper for easy access)

        Queries centralized learning database for:
        - Past format errors to avoid
        - Filing hints from successful extractions
        - Common mistakes and validation errors
        - Success patterns to follow

        Args:
            field: Database field name ('earnout_shares', 'trust_value', etc.)

        Returns:
            Dict with format_warnings, filing_hints, common_mistakes, success_patterns

        Example:
            # Before extracting earnout_shares
            lessons = self.get_lessons_for_field('earnout_shares')

            if lessons['format_warnings']:
                print(f"   📚 Found {len(lessons['format_warnings'])} past format errors")
                # Include in AI prompt

        Usage:
            lessons = self.get_lessons_for_field('earnout_shares')
            prompt += format_lessons_for_prompt(lessons)
        """
        from utils.extraction_learner import get_extraction_lessons

        return get_extraction_lessons(
            field=field,
            issue_types=['format_error', 'extraction_success', 'validation_error'],
            limit=10
        )

    def search_for_missing_data(
        self,
        ticker: str,
        field: str,
        db_session
    ) -> Optional[any]:
        """
        Proactive search for missing data in SEC filings

        When a field is missing, this method:
        1. Checks if SPAC is still active (not completed)
        2. Gets filing search strategy from past successes
        3. Searches filings in priority order
        4. Extracts using AI with past learnings
        5. Logs success for future learning

        Args:
            ticker: SPAC ticker symbol
            field: Database field name
            db_session: Active database session

        Returns:
            Extracted value or None if not found

        Example:
            # If target is missing from current filing
            db = SessionLocal()
            try:
                target = self.search_for_missing_data(
                    ticker='BLUW',
                    field='target',
                    db_session=db
                )
                if target:
                    print(f"   ✅ Found missing target: {target}")
            finally:
                db.close()

        User Insight (Nov 4, 2025):
            "I think the right solution is first confirm it's still a SPAC
             that isn't completed, and then to try to find it in filings"
        """
        from database import SPAC
        from utils.extraction_learner import get_filing_search_strategy

        # 1. Check if SPAC is active
        spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"   ⚠️  {ticker} not found in database")
            return None

        if spac.deal_status == 'COMPLETED':
            print(f"   ⚠️  {ticker} is completed, skipping search for {field}")
            return None

        # 2. Get search strategy from past successes
        strategy = get_filing_search_strategy(field, ticker)
        print(f"   🔍 Searching for {field} using strategy: {strategy['primary_source']} (confidence: {strategy['confidence']})")

        # 3. Search filings in priority order
        from utils.sec_filing_fetcher import SECFilingFetcher
        fetcher = SECFilingFetcher()

        filing_types = [strategy['primary_source']] + strategy['fallback_sources']

        for filing_type in filing_types:
            print(f"   📄 Checking {filing_type} filings...")

            try:
                filings = fetcher.get_filings(
                    cik=spac.cik if hasattr(spac, 'cik') else None,
                    ticker=ticker,
                    filing_type=filing_type,
                    lookback_days=strategy['lookback_days'],
                    limit=3
                )

                for filing in filings[:3]:  # Check up to 3 most recent
                    # 4. Extract with AI + past learnings
                    lessons = self.get_lessons_for_field(field)

                    value = self._extract_field_with_lessons(
                        filing_content=filing.get('content', ''),
                        field=field,
                        lessons=lessons,
                        section_hints=strategy['section_hints']
                    )

                    if value is not None:
                        # 5. Log success for future learning
                        from utils.extraction_learner import log_extraction_success
                        log_extraction_success(
                            agent_name=self.name,
                            field=field,
                            value=value,
                            ticker=ticker,
                            filing_type=filing_type,
                            filing_section=strategy['section_hints'][0] if strategy['section_hints'] else None
                        )
                        return value

            except Exception as e:
                print(f"   ⚠️  Error searching {filing_type}: {e}")
                continue

        print(f"   ⚠️  Could not find {field} in recent filings")
        return None

    def _extract_field_with_lessons(
        self,
        filing_content: str,
        field: str,
        lessons: Dict,
        section_hints: list = None
    ) -> Optional[any]:
        """
        Extract field using AI enhanced with past learnings

        Includes past format warnings and success patterns in prompt.

        Args:
            filing_content: Filing text content
            field: Database field to extract
            lessons: Output from get_lessons_for_field()
            section_hints: Where to look (optional)

        Returns:
            Extracted value or None

        Note:
            Subclasses can override this for custom extraction logic,
            but should still incorporate lessons into prompts.
        """
        from utils.extraction_learner import format_lessons_for_prompt
        from utils.number_parser import sanitize_ai_response

        # Build enhanced prompt with learnings
        lessons_text = format_lessons_for_prompt(lessons)

        section_guidance = ""
        if section_hints:
            section_guidance = f"\n**Where to look**: {', '.join(section_hints)}\n"

        prompt = f"""Extract {field} from this SEC filing.

{lessons_text}{section_guidance}
**Instructions**:
- Return NUMERIC values (not formatted strings like '1.1M')
- If not found, return null (not "N/A" or "TBD")
- Validate before returning

Filing excerpt (first 5000 chars):
{filing_content[:5000]}

Return ONLY the value in JSON format: {{"value": ...}}
"""

        # Subclasses should implement AI extraction
        # For now, return None (base implementation)
        print(f"   ℹ️  _extract_field_with_lessons: Base implementation (no AI)")
        return None
