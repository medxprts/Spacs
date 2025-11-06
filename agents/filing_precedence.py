"""
Filing Precedence Manager

Determines whether a field should be updated based on:
1. Filing type precedence (8-K > 10-Q for events, 10-Q > 424B4 for periodic data)
2. Filing date recency (newer filing wins for same type)
3. Data source tracking (stores which filing last updated each field)

Usage:
    manager = FilingPrecedenceManager()
    
    # Check if we should update a field
    should_update = manager.should_update_field(
        spac=spac_obj,
        field_name='shares_outstanding',
        new_value=17_500_000,
        new_source='10-Q',
        new_filing_date=date(2025, 5, 15)
    )
    
    if should_update:
        spac.shares_outstanding = 17_500_000
        spac.shares_source = '10-Q'
        spac.shares_filing_date = date(2025, 5, 15)
"""

from typing import Dict, Optional, Any
from datetime import date
from agents.data_source_reference import get_data_source


# Filed type hierarchy for different data categories
FILING_TYPE_PRECEDENCE = {
    # Event-based data: Most recent filing of highest precedence wins
    'event_based': {
        'filing_order': ['8-K', '425', 'DEFM14A', 'S-4', '10-Q', '10-K'],  # Left = highest precedence
        'recency_matters': True,  # Newer filing can override older higher-precedence filing
        'recency_window_days': 90,  # Within 90 days, recency overrides type precedence
    },
    
    # Periodic data: Most recent filing wins, regardless of type
    'periodic': {
        'filing_order': ['10-Q', '10-K', '8-K', 'DEFM14A'],
        'recency_matters': True,
        'recency_window_days': None,  # Always use most recent
    },
    
    # IPO data: Set once at IPO, rarely changes
    'ipo_static': {
        'filing_order': ['424B4', 'S-1/A', 'S-1'],
        'recency_matters': False,  # Don't override with newer filings (IPO data is static)
        'recency_window_days': None,
    },
    
    # IPO data that CAN change: Overallotment, founder shares (forfeiture)
    'ipo_mutable': {
        'filing_order': ['10-Q', '10-K', '8-K', '424B4'],
        'recency_matters': True,
        'recency_window_days': None,
    },
}


# Map fields to data categories
FIELD_CATEGORIES = {
    # Event-based (8-K primary, but DEFM14A/S-4 can update)
    'event_based': [
        'target', 'deal_value', 'announced_date', 'sector', 'expected_close',
        'pipe_size', 'pipe_price', 'earnout_shares', 'min_cash',
        'completion_date', 'new_ticker', 'merger_termination_date',
        'extension_date', 'extension_count', 'is_extended',
    ],
    
    # Periodic (most recent 10-Q/10-K wins)
    'periodic': [
        'trust_cash', 'trust_value',
        'shares_outstanding',  # Changes with redemptions
        'shares_redeemed', 'redemption_amount', 'redemption_percentage',
    ],
    
    # IPO static (set at IPO, don't override)
    'ipo_static': [
        'ipo_date', 'ipo_price', 'ipo_proceeds',
        'warrant_exercise_price', 'warrant_ratio', 'warrant_expiration_years',
        'warrant_redemption_price', 'extension_available', 'extension_months_available',
        'original_deadline_date', 'deadline_months',
    ],
    
    # IPO mutable (set at IPO, but can change)
    'ipo_mutable': [
        'founder_shares',  # Can change if forfeited
        'shares_outstanding_base', 'shares_outstanding_with_overallotment',
        'overallotment_exercised',  # Determined post-IPO
        'promote_vesting_type', 'promote_vesting_prices',  # Can change if amended
    ],
}


class FilingPrecedenceManager:
    """Manages filing precedence rules for field updates"""
    
    def should_update_field(
        self,
        spac,
        field_name: str,
        new_value: Any,
        new_source: str,
        new_filing_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Determine if a field should be updated
        
        Args:
            spac: SPAC database object
            field_name: Name of field to update (e.g., 'shares_outstanding')
            new_value: New value to set
            new_source: Filing type of new data (e.g., '10-Q', '8-K')
            new_filing_date: Date of new filing
            
        Returns:
            {
                'should_update': bool,
                'reason': str,
                'current_source': str,
                'current_date': date,
                'precedence_category': str
            }
        """
        # Get current value and source
        current_value = getattr(spac, field_name, None)
        current_source = getattr(spac, f'{field_name}_source', None)
        current_date = getattr(spac, f'{field_name}_filing_date', None)
        
        # If field is empty, always update
        if current_value is None:
            return {
                'should_update': True,
                'reason': 'Field is empty',
                'current_source': None,
                'current_date': None,
                'precedence_category': self._get_field_category(field_name)
            }
        
        # If new value is same as current, skip
        if new_value == current_value:
            return {
                'should_update': False,
                'reason': 'Value unchanged',
                'current_source': current_source,
                'current_date': current_date,
                'precedence_category': self._get_field_category(field_name)
            }
        
        # Get precedence category
        category = self._get_field_category(field_name)
        precedence_rules = FILING_TYPE_PRECEDENCE[category]
        
        # If no current source tracked, update
        if not current_source:
            return {
                'should_update': True,
                'reason': 'No source tracked for current value',
                'current_source': None,
                'current_date': None,
                'precedence_category': category
            }
        
        # Check filing type precedence
        new_precedence = self._get_filing_precedence(new_source, precedence_rules['filing_order'])
        current_precedence = self._get_filing_precedence(current_source, precedence_rules['filing_order'])
        
        # For IPO static data, don't override unless from higher precedence source
        if category == 'ipo_static':
            if new_precedence < current_precedence:  # Lower index = higher precedence
                return {
                    'should_update': True,
                    'reason': f'{new_source} has higher precedence than {current_source} for IPO data',
                    'current_source': current_source,
                    'current_date': current_date,
                    'precedence_category': category
                }
            else:
                return {
                    'should_update': False,
                    'reason': f'{current_source} has equal/higher precedence than {new_source} for IPO static data',
                    'current_source': current_source,
                    'current_date': current_date,
                    'precedence_category': category
                }
        
        # For periodic and mutable data, check recency
        if precedence_rules['recency_matters'] and new_filing_date and current_date:
            days_diff = (new_filing_date - current_date).days
            
            # If new filing is newer, update
            if days_diff > 0:
                return {
                    'should_update': True,
                    'reason': f'{new_source} ({new_filing_date}) is more recent than {current_source} ({current_date})',
                    'current_source': current_source,
                    'current_date': current_date,
                    'precedence_category': category
                }
            
            # If new filing is older
            elif days_diff < 0:
                # Only update if new source has significantly higher precedence
                if new_precedence < current_precedence - 1:  # At least 2 levels higher
                    return {
                        'should_update': True,
                        'reason': f'{new_source} has much higher precedence than {current_source} (overrides recency)',
                        'current_source': current_source,
                        'current_date': current_date,
                        'precedence_category': category
                    }
                else:
                    return {
                        'should_update': False,
                        'reason': f'{current_source} ({current_date}) is more recent than {new_source} ({new_filing_date})',
                        'current_source': current_source,
                        'current_date': current_date,
                        'precedence_category': category
                    }
        
        # If no filing dates available, use type precedence only
        if new_precedence < current_precedence:
            return {
                'should_update': True,
                'reason': f'{new_source} has higher precedence than {current_source}',
                'current_source': current_source,
                'current_date': current_date,
                'precedence_category': category
            }
        else:
            return {
                'should_update': False,
                'reason': f'{current_source} has equal/higher precedence than {new_source}',
                'current_source': current_source,
                'current_date': current_date,
                'precedence_category': category
            }
    
    def _get_field_category(self, field_name: str) -> str:
        """Get precedence category for a field"""
        for category, fields in FIELD_CATEGORIES.items():
            if field_name in fields:
                return category
        
        # Default to periodic for unknown fields
        return 'periodic'
    
    def _get_filing_precedence(self, filing_type: str, filing_order: list) -> int:
        """Get precedence index for filing type (lower = higher precedence)"""
        try:
            return filing_order.index(filing_type)
        except ValueError:
            # Unknown filing type gets lowest precedence
            return len(filing_order)
    
    def update_field_with_precedence(
        self,
        spac,
        field_name: str,
        new_value: Any,
        new_source: str,
        new_filing_date: Optional[date] = None
    ) -> bool:
        """
        Update field if precedence rules allow
        
        Returns:
            bool: True if field was updated, False otherwise
        """
        decision = self.should_update_field(
            spac, field_name, new_value, new_source, new_filing_date
        )
        
        if decision['should_update']:
            # Update field
            setattr(spac, field_name, new_value)
            
            # Update source tracking fields
            source_field = f'{field_name}_source'
            date_field = f'{field_name}_filing_date'
            
            if hasattr(spac, source_field):
                setattr(spac, source_field, new_source)
            
            if hasattr(spac, date_field) and new_filing_date:
                setattr(spac, date_field, new_filing_date)
            
            return True
        
        return False
