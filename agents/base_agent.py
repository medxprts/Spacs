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
