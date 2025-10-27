#!/usr/bin/env python3
"""
Data Validator Agent
Comprehensive data quality validation with auto-correction and anomaly detection

Checks for:
1. Logical inconsistencies (deal_status vs target, announced_date vs deal_status)
2. Field validations (trust_value, premium calculations, date ranges)
3. Cross-field dependencies (price vs premium, deadline vs IPO date)
4. Historical patterns (learns from validation log)
5. Anomaly detection (unusual values, outliers)
"""

import sys
import os
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Optional, Tuple
import json

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from data_validation_rules import (
    ValidationRulesEngine,
    IPOToDeadlineTimeframeRule,
    DealStatusConsistencyRule,
    TrustValueRule
)
from data_validation_log import DataValidationLogger
from utils.telegram_notifier import send_telegram_alert
from utils.sec_filing_fetcher import SECFilingFetcher

# AI Setup
try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
except Exception as e:
    AI_AVAILABLE = False
    print(f"⚠️  AI not available: {e}")

# Note: send_telegram_alert() now imported from utils.telegram_notifier
# It automatically splits long messages into chunks (Telegram 4096 char limit)


class LogicalConsistencyValidator:
    """Validates logical consistency across related fields"""

    def __init__(self):
        self.issues = []
        self.db = SessionLocal()  # For historical price queries

    def close(self):
        self.db.close()

    def validate_data_types_and_formats(self, spac: SPAC) -> List[Dict]:
        """Rule 1-4, 7: Data type and format validation"""
        issues = []

        # Rule 1: ticker format - REMOVED per user request
        # Tickers can have various formats including periods (e.g., GTER.A)
        # No validation required

        # Rule 2: CIK format (exactly 10 digits)
        if spac.cik:
            cik_str = str(spac.cik).zfill(10)  # Pad with zeros
            if not cik_str.isdigit() or len(cik_str) != 10:
                issues.append({
                    'type': 'format_error',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'cik',
                    'rule': 'CIK Format (Rule 2)',
                    'message': f'CIK must be exactly 10 digits, got: {spac.cik}',
                    'auto_fix': None,
                    'expected': '10-digit number (zero-padded)',
                    'actual': spac.cik
                })

        # Rule 3: price fields (numeric, >= 0)
        price_fields = [
            ('price', spac.price),
            ('common_price', spac.common_price),
            ('warrant_price', spac.warrant_price),
            ('unit_price', spac.unit_price),
            ('trust_value', spac.trust_value)
        ]

        for field_name, field_value in price_fields:
            if field_value is not None:
                try:
                    val = float(field_value)
                    if val < 0:
                        issues.append({
                            'type': 'invalid_value',
                            'severity': 'CRITICAL',
                            'ticker': spac.ticker,
                            'field': field_name,
                            'rule': 'Price Non-Negative (Rule 3)',
                            'message': f'{field_name} cannot be negative: {val}',
                            'auto_fix': 'set_to_null',
                            'expected': '>= 0',
                            'actual': val
                        })
                except (ValueError, TypeError):
                    issues.append({
                        'type': 'type_error',
                        'severity': 'CRITICAL',
                        'ticker': spac.ticker,
                        'field': field_name,
                        'rule': 'Price Numeric (Rule 3)',
                        'message': f'{field_name} must be numeric, got: {field_value}',
                        'auto_fix': 'set_to_null',
                        'expected': 'numeric value',
                        'actual': type(field_value).__name__
                    })

        # Rule 4: date fields (valid ISO format)
        # NOTE: Date fields can be either datetime objects OR strings
        # The system handles both types (e.g., line 329 shows expected_close as datetime|string)
        # Only validate if they're NOT datetime or str
        date_fields = [
            ('ipo_date', spac.ipo_date),
            ('announced_date', spac.announced_date),
            ('deadline_date', spac.deadline_date),
            ('shareholder_vote_date', spac.shareholder_vote_date),
            ('redemption_deadline', spac.redemption_deadline),
            ('expected_close', spac.expected_close)
        ]

        for field_name, field_value in date_fields:
            # Accept both datetime objects AND strings (e.g., "Q4 2025")
            if field_value is not None and not isinstance(field_value, (datetime, str)):
                issues.append({
                    'type': 'type_error',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': field_name,
                    'rule': 'Date Format (Rule 4)',
                    'message': f'{field_name} must be datetime or string, got: {type(field_value).__name__}',
                    'auto_fix': None,
                    'expected': 'datetime object or string',
                    'actual': type(field_value).__name__
                })

        # Rule 4b: REMOVED - expected_close is now completely flexible
        # Can be string (e.g., "Q4 2025"), datetime, or NULL for any deal status
        # No validation required

        # Rule 7: volume/shares (integers >= 0)
        integer_fields = [
            ('shares_outstanding', spac.shares_outstanding),
            ('shares_redeemed', spac.shares_redeemed)
        ]

        for field_name, field_value in integer_fields:
            if field_value is not None:
                try:
                    val = int(field_value)
                    if val < 0:
                        issues.append({
                            'type': 'invalid_value',
                            'severity': 'CRITICAL',
                            'ticker': spac.ticker,
                            'field': field_name,
                            'rule': 'Shares Non-Negative (Rule 7)',
                            'message': f'{field_name} cannot be negative: {val}',
                            'auto_fix': 'set_to_null',
                            'expected': '>= 0',
                            'actual': val
                        })
                except (ValueError, TypeError):
                    issues.append({
                        'type': 'type_error',
                        'severity': 'CRITICAL',
                        'ticker': spac.ticker,
                        'field': field_name,
                        'rule': 'Shares Integer (Rule 7)',
                        'message': f'{field_name} must be integer, got: {field_value}',
                        'auto_fix': 'set_to_null',
                        'expected': 'integer value',
                        'actual': type(field_value).__name__
                    })

        return issues

    def validate_deal_status_consistency(self, spac: SPAC) -> List[Dict]:
        """Check if deal_status matches target and dates"""
        issues = []

        # ANNOUNCED status should have target
        if spac.deal_status == 'ANNOUNCED':
            if not spac.target or spac.target in ['-', '', 'Unknown', '[Unknown]', '[Unknown - requires validation]']:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'target',
                    'rule': 'Deal Status → Target Consistency',
                    'message': f'Status is ANNOUNCED but target is missing/invalid: {spac.target}',
                    'auto_fix': 'set_status_to_SEARCHING',
                    'expected': 'Valid target company name',
                    'actual': spac.target
                })

            if not spac.announced_date:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'announced_date',
                    'rule': 'Deal Status → Announced Date Consistency',
                    'message': 'Status is ANNOUNCED but no announced_date',
                    'auto_fix': 'extract_from_8k',
                    'expected': 'Date deal was announced',
                    'actual': None
                })

        # SEARCHING status should not have target
        if spac.deal_status == 'SEARCHING':
            if spac.target and spac.target not in ['-', '', 'Unknown', None]:
                # Check if target looks valid
                if len(spac.target) > 3 and not any(x in spac.target.lower() for x in ['unknown', 'tbd', 'n/a']):
                    issues.append({
                        'type': 'logical_inconsistency',
                        'severity': 'CRITICAL',
                        'ticker': spac.ticker,
                        'field': 'deal_status',
                        'rule': 'Target → Deal Status Consistency',
                        'message': f'Has target "{spac.target}" but status is SEARCHING',
                        'auto_fix': 'set_status_to_ANNOUNCED',
                        'expected': 'ANNOUNCED',
                        'actual': 'SEARCHING'
                    })

        return issues

    def validate_date_consistency(self, spac: SPAC) -> List[Dict]:
        """Check if dates are logically consistent"""
        issues = []

        # Rule 30: announced_date should be after ipo_date
        if spac.announced_date and spac.ipo_date:
            if spac.announced_date < spac.ipo_date:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'announced_date',
                    'rule': 'Announcement Date → IPO Date Ordering (Rule 30)',
                    'message': f'announced_date ({spac.announced_date.date()}) is before ipo_date ({spac.ipo_date.date()})',
                    'auto_fix': None,
                    'expected': 'announced_date >= ipo_date',
                    'actual': f'announced_date < ipo_date'
                })

        # shareholder_vote_date should be after announced_date
        if spac.shareholder_vote_date and spac.announced_date:
            if spac.shareholder_vote_date < spac.announced_date:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'shareholder_vote_date',
                    'rule': 'Vote Date → Announcement Date Ordering',
                    'message': f'shareholder_vote_date ({spac.shareholder_vote_date.date()}) is before announced_date ({spac.announced_date.date()})',
                    'auto_fix': None,
                    'expected': 'vote_date >= announced_date',
                    'actual': f'vote_date < announced_date'
                })

        # deadline_date should be after ipo_date
        if spac.deadline_date and spac.ipo_date:
            if spac.deadline_date < spac.ipo_date:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'deadline_date',
                    'rule': 'Deadline → IPO Date Ordering',
                    'message': f'deadline_date ({spac.deadline_date.date()}) is before ipo_date ({spac.ipo_date.date()})',
                    'auto_fix': 'recalculate_deadline',
                    'expected': 'deadline_date >= ipo_date',
                    'actual': f'deadline_date < ipo_date'
                })

        # Check IPO to deadline timeframe (should be 18-24 months typically)
        if spac.ipo_date and spac.deadline_date:
            delta = relativedelta(spac.deadline_date, spac.ipo_date)
            months = delta.years * 12 + delta.months

            if months < 12:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'deadline_date',
                    'rule': 'IPO → Deadline Timeframe',
                    'message': f'Only {months} months between IPO and deadline (expected 18-24)',
                    'auto_fix': 'recalculate_deadline',
                    'expected': '18-24 months',
                    'actual': f'{months} months'
                })

            # Rule 32: deadline_date > ipo_date + 36 months (too long, likely extended)
            if months > 36:
                issues.append({
                    'type': 'anomaly',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'deadline_date',
                    'rule': 'Deadline Extension Check (Rule 32)',
                    'message': f'{months} months between IPO and deadline (>36 months suggests multiple extensions)',
                    'auto_fix': None,
                    'expected': '18-36 months (with extensions)',
                    'actual': f'{months} months'
                })

        # Rule 33: shareholder_vote_date within deal timeline
        if spac.shareholder_vote_date and spac.announced_date and spac.expected_close:
            # expected_close might be datetime or string, handle both
            expected_close_dt = spac.expected_close if isinstance(spac.expected_close, datetime) else None
            if expected_close_dt and spac.shareholder_vote_date < spac.announced_date or (expected_close_dt and spac.shareholder_vote_date > expected_close_dt + timedelta(days=30)):
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'shareholder_vote_date',
                    'rule': 'Vote Date Within Deal Timeline (Rule 33)',
                    'message': f'Vote date {spac.shareholder_vote_date.date()} outside deal timeline ({spac.announced_date.date()} to {expected_close_dt.date() if expected_close_dt else "N/A"})',
                    'auto_fix': None,
                    'expected': 'Between announced_date and expected_close + 30 days',
                    'actual': f'{spac.shareholder_vote_date.date()}'
                })

        # Rule 34: redemption_deadline 2-10 days before vote
        if spac.redemption_deadline and spac.shareholder_vote_date:
            days_before_vote = (spac.shareholder_vote_date - spac.redemption_deadline).days
            if days_before_vote < 2 or days_before_vote > 10:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'redemption_deadline',
                    'rule': 'Redemption Deadline Timing (Rule 34)',
                    'message': f'Redemption deadline {days_before_vote} days before vote (expected 2-10 days)',
                    'auto_fix': None,
                    'expected': '2-10 days before shareholder vote',
                    'actual': f'{days_before_vote} days before'
                })

        # Rule 76: Filing dates not > 5 days in future
        now = datetime.now()
        future_date_fields = [
            ('ipo_date', spac.ipo_date),
            ('announced_date', spac.announced_date)
        ]

        for field_name, field_value in future_date_fields:
            if field_value and field_value > now + timedelta(days=5):
                issues.append({
                    'type': 'data_error',
                    'severity': 'ERROR',
                    'ticker': spac.ticker,
                    'field': field_name,
                    'rule': 'Future Date Validation (Rule 76)',
                    'message': f'{field_name} is >5 days in future: {field_value.date()} (likely data error)',
                    'auto_fix': None,
                    'expected': 'Date not >5 days in future',
                    'actual': f'{field_value.date()} ({(field_value - now).days} days ahead)'
                })

        return issues

    def validate_premium_calculation(self, spac: SPAC) -> List[Dict]:
        """Check if premium is calculated correctly"""
        issues = []

        if not spac.price or not spac.trust_value:
            return issues

        # Convert to float for calculation
        price = float(spac.price)
        trust_value = float(spac.trust_value)

        # Recalculate premium
        expected_premium = ((price - trust_value) / trust_value) * 100

        # Allow 0.5% tolerance for rounding
        if spac.premium is not None and abs(spac.premium - expected_premium) > 0.5:
            issues.append({
                'type': 'calculation_error',
                'severity': 'MEDIUM',
                'ticker': spac.ticker,
                'field': 'premium',
                'rule': 'Premium Calculation',
                'message': f'Premium calculation mismatch: stored={spac.premium:.2f}%, calculated={expected_premium:.2f}%',
                'auto_fix': 'recalculate_premium',
                'expected': f'{expected_premium:.2f}%',
                'actual': f'{spac.premium:.2f}%'
            })

        return issues

    def validate_trust_value(self, spac: SPAC) -> List[Dict]:
        """
        Validate trust value is reasonable with age-based interest accrual

        Logic:
        - Calculate expected trust value: $10.00 * (1.05 ^ years_since_ipo)
        - Only flag if actual is more than 5% off from expected
        - Older SPACs should have higher trust values due to interest
        """
        issues = []

        if not spac.trust_value:
            return issues

        trust_value = float(spac.trust_value)

        # Calculate expected trust value based on age
        if spac.ipo_date:
            from datetime import datetime

            # Calculate years since IPO
            ipo_date = spac.ipo_date.date() if hasattr(spac.ipo_date, 'date') else spac.ipo_date
            years_since_ipo = (datetime.now().date() - ipo_date).days / 365.25

            # Expected trust value with 5% compounding from $10.00
            expected_trust_value = 10.00 * (1.05 ** years_since_ipo)

            # Calculate 5% tolerance bands
            tolerance = 0.05  # 5%
            lower_bound = expected_trust_value * (1 - tolerance)
            upper_bound = expected_trust_value * (1 + tolerance)

            # Only flag if outside tolerance bands
            if trust_value < lower_bound or trust_value > upper_bound:
                deviation_pct = ((trust_value - expected_trust_value) / expected_trust_value) * 100

                issues.append({
                    'type': 'anomaly',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'trust_value',
                    'rule': 'Trust Value Range (Age-Adjusted)',
                    'message': f'Trust value ${trust_value:.2f} is {deviation_pct:+.1f}% off expected ${expected_trust_value:.2f} (SPAC age: {years_since_ipo:.1f}y, 5% interest)',
                    'auto_fix': None,
                    'expected': f'${lower_bound:.2f}-${upper_bound:.2f} (±5% of ${expected_trust_value:.2f})',
                    'actual': f'${trust_value:.2f}'
                })
        else:
            # No IPO date - use simple range check for new SPACs
            if trust_value < 9.50 or trust_value > 10.50:
                issues.append({
                    'type': 'anomaly',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'trust_value',
                    'rule': 'Trust Value Range',
                    'message': f'Trust value ${trust_value:.2f} is unusual (expected ~$10.00, no IPO date to adjust)',
                    'auto_fix': None,
                    'expected': '$9.50-$10.50',
                    'actual': f'${trust_value:.2f}'
                })

        return issues

    def validate_price_vs_nav(self, spac: SPAC) -> List[Dict]:
        """Check for unusual price vs NAV scenarios - Rules 14-16, 20, 43, 86"""
        issues = []

        if not spac.price or not spac.trust_value:
            return issues

        price = float(spac.price)
        trust_value = float(spac.trust_value)

        # Trading significantly below NAV (arbitrage opportunity or data error)
        if price < trust_value * 0.95:  # More than 5% below NAV
            issues.append({
                'type': 'anomaly',
                'severity': 'MEDIUM',
                'ticker': spac.ticker,
                'field': 'price',
                'rule': 'Price Below NAV',
                'message': f'Price ${price:.2f} is {((trust_value - price)/trust_value*100):.1f}% below NAV (arbitrage opportunity or data error)',
                'auto_fix': None,
                'expected': f'>= ${trust_value * 0.95:.2f}',
                'actual': f'${price:.2f}'
            })

        # Rule 14: ipo_price outside $9.50-$11.50
        if spac.ipo_price:
            try:
                ipo_price = float(spac.ipo_price)
                if ipo_price < 9.50 or ipo_price > 11.50:
                    issues.append({
                        'type': 'anomaly',
                        'severity': 'WARNING',
                        'ticker': spac.ticker,
                        'field': 'ipo_price',
                        'rule': 'IPO Price Range (Rule 14)',
                        'message': f'IPO price ${ipo_price:.2f} outside typical range ($9.50-$11.50)',
                        'auto_fix': None,
                        'expected': '$9.50-$11.50',
                        'actual': f'${ipo_price:.2f}'
                    })
            except (ValueError, TypeError):
                pass

        # Rule 15: common_price > $13 for SEARCHING (rumored deal trigger)
        if spac.deal_status == 'SEARCHING' and spac.common_price:
            try:
                common_price = float(spac.common_price)
                if common_price > 13.0:
                    issues.append({
                        'type': 'anomaly',
                        'severity': 'WARNING',
                        'ticker': spac.ticker,
                        'field': 'common_price',
                        'rule': 'High Price Without Deal (Rule 15)',
                        'message': f'Price ${common_price:.2f} >$13 for SEARCHING SPAC (rumored deal or data error)',
                        'auto_fix': 'check_for_unreported_deal',
                        'expected': '<$13 or deal_status=ANNOUNCED',
                        'actual': f'${common_price:.2f}, status=SEARCHING'
                    })
            except (ValueError, TypeError):
                pass

        # Rule 16: warrant_price > $5.00
        if spac.warrant_price:
            try:
                warrant_price = float(spac.warrant_price)
                if warrant_price > 5.0:
                    issues.append({
                        'type': 'anomaly',
                        'severity': 'WARNING',
                        'ticker': spac.ticker,
                        'field': 'warrant_price',
                        'rule': 'High Warrant Price (Rule 16)',
                        'message': f'Warrant price ${warrant_price:.2f} >$5.00 (unusual, verify deal excitement)',
                        'auto_fix': None,
                        'expected': '<$5.00',
                        'actual': f'${warrant_price:.2f}'
                    })
            except (ValueError, TypeError):
                pass

        # Rule 20: price_change_24h > 20% for pre-deal SPACs (using historical_prices)
        if spac.deal_status == 'SEARCHING':
            from sqlalchemy import text
            yesterday = datetime.now() - timedelta(days=1)
            query = text("""
                SELECT price
                FROM historical_prices
                WHERE ticker = :ticker
                AND date >= :yesterday
                ORDER BY date DESC
                LIMIT 1
            """)
            result = self.db.execute(query, {'ticker': spac.ticker, 'yesterday': yesterday.date()}).fetchone()

            if result and result[0]:
                prev_price = float(result[0])
                if prev_price > 0:
                    price_change_pct = ((price - prev_price) / prev_price) * 100
                    if abs(price_change_pct) > 20:
                        issues.append({
                            'type': 'anomaly',
                            'severity': 'WARNING',
                            'ticker': spac.ticker,
                            'field': 'price',
                            'rule': 'Large Price Move Pre-Deal (Rule 20)',
                            'message': f'Price moved {price_change_pct:+.1f}% in 24h for SEARCHING SPAC (check for deal rumors)',
                            'auto_fix': None,
                            'expected': '<20% daily move',
                            'actual': f'{price_change_pct:+.1f}%'
                        })

        # Rule 43: price_at_announcement outside $9.50-$15
        if spac.price_at_announcement:
            try:
                price_at_ann = float(spac.price_at_announcement)
                if price_at_ann < 9.50 or price_at_ann > 15.0:
                    issues.append({
                        'type': 'anomaly',
                        'severity': 'WARNING',
                        'ticker': spac.ticker,
                        'field': 'price_at_announcement',
                        'rule': 'Deal Announcement Price Range (Rule 43)',
                        'message': f'Price at announcement ${price_at_ann:.2f} outside typical range',
                        'auto_fix': None,
                        'expected': '$9.50-$15.00',
                        'actual': f'${price_at_ann:.2f}'
                    })
            except (ValueError, TypeError):
                pass

        # Rule 86: Price data stale (> 48 hours)
        if spac.last_updated:
            hours_since_update = (datetime.now() - spac.last_updated).total_seconds() / 3600
            if hours_since_update > 48:
                issues.append({
                    'type': 'data_staleness',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'last_updated',
                    'rule': 'Stale Price Data (Rule 86)',
                    'message': f'Price data is {hours_since_update:.1f} hours old (>48h)',
                    'auto_fix': 'update_prices',
                    'expected': '<48 hours old',
                    'actual': f'{hours_since_update:.1f} hours old'
                })

        # Trading at extreme premium (>50%) without deal
        if spac.deal_status == 'SEARCHING' and price > trust_value * 1.5:
            premium_calc = ((price - trust_value) / trust_value) * 100
            issues.append({
                'type': 'anomaly',
                'severity': 'HIGH',
                'ticker': spac.ticker,
                'field': 'price',
                'rule': 'Extreme Premium Without Deal',
                'message': f'Price ${price:.2f} is {premium_calc:.1f}% above NAV but no deal announced (verify deal_status)',
                'auto_fix': 'check_for_unreported_deal',
                'expected': 'Premium <50% or deal_status=ANNOUNCED',
                'actual': f'{premium_calc:.1f}% premium, status={spac.deal_status}'
            })

        return issues

    def validate_deal_status_lifecycle(self, spac: SPAC) -> List[Dict]:
        """Rules 41, 82, 83: Deal status lifecycle and liquidation"""
        issues = []

        # Rule 41: CLOSED/COMPLETED deal but required fields missing
        if spac.deal_status in ['CLOSED', 'COMPLETED']:
            if not spac.target:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'target',
                    'rule': 'Closed Deal Missing Target (Rule 41)',
                    'message': f'Deal status is {spac.deal_status} but target is missing',
                    'auto_fix': None,
                    'expected': 'Target company name',
                    'actual': None
                })

            # Note: We use expected_close since close_date field doesn't exist
            if not spac.expected_close:
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'WARNING',
                    'ticker': spac.ticker,
                    'field': 'expected_close',
                    'rule': 'Closed Deal Missing Expected Close (Rule 41)',
                    'message': f'Deal status is {spac.deal_status} but expected_close is missing',
                    'auto_fix': None,
                    'expected': 'Expected deal close date',
                    'actual': None
                })

        # Rule 82: is_liquidating consistency with deal_status
        if spac.is_liquidating and spac.deal_status not in ['LIQUIDATING', 'LIQUIDATED', 'CLOSED']:
            issues.append({
                'type': 'logical_inconsistency',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'is_liquidating',
                'rule': 'Liquidation Flag Consistency (Rule 82)',
                'message': f'is_liquidating=True but deal_status={spac.deal_status} (should be LIQUIDATING/LIQUIDATED)',
                'auto_fix': 'set_status_to_liquidating',
                'expected': 'deal_status in [LIQUIDATING, LIQUIDATED, CLOSED]',
                'actual': f'deal_status={spac.deal_status}'
            })

        # Rule 83: Deadline passed with no liquidation flag
        if spac.deadline_date and spac.deadline_date < datetime.now():
            if spac.deal_status == 'SEARCHING' and not spac.is_liquidating:
                days_overdue = (datetime.now() - spac.deadline_date).days
                issues.append({
                    'type': 'logical_inconsistency',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'deal_status',
                    'rule': 'Expired Deadline Without Liquidation (Rule 83)',
                    'message': f'Deadline passed {days_overdue} days ago but still SEARCHING (should be LIQUIDATING)',
                    'auto_fix': 'set_status_to_liquidating',
                    'expected': 'deal_status=LIQUIDATING or is_liquidating=True',
                    'actual': f'deal_status=SEARCHING, is_liquidating={spac.is_liquidating}'
                })

        return issues

    def validate_trust_cash_vs_ipo(self, spac: SPAC) -> List[Dict]:
        """
        Validate trust cash does not exceed IPO proceeds (with adjustments for age and overallotment)

        Lesson from AEXA data quality issue (Oct 9, 2025):
        - AEXA had trust_cash of $456.7M but IPO proceeds of only $345M
        - Caused by circular calculation error (bad trust_value used in calculation)
        - Rule: trust_cash should be ~98% of IPO proceeds (2% upfront fee deducted)

        UPDATED (Oct 10, 2025): Account for legitimate increases:
        - Interest accumulation: ~3-5% annual (older SPACs have more cash)
        - Overallotment (green shoe): +15% if exercised (424B4 may not capture this)
        - Combined: 2-year SPAC with overallotment could have +30% trust cash = VALID

        See: /home/ubuntu/spac-research/DATA_QUALITY_ISSUES.md
        """
        issues = []

        if not spac.trust_cash or not spac.ipo_proceeds:
            return issues

        # Parse IPO proceeds (format: "$300,000,000" or "$300M")
        ipo_str = spac.ipo_proceeds.replace('$', '').replace(',', '').strip()

        try:
            if 'M' in ipo_str or 'm' in ipo_str:
                ipo_value = float(ipo_str.replace('M', '').replace('m', '')) * 1_000_000
            elif 'B' in ipo_str or 'b' in ipo_str:
                ipo_value = float(ipo_str.replace('B', '').replace('b', '')) * 1_000_000_000
            else:
                ipo_value = float(ipo_str)
        except ValueError:
            # Can't parse IPO proceeds, skip validation
            return issues

        # Calculate SPAC age (for interest accumulation estimate)
        spac_age_years = 0
        if spac.ipo_date:
            from datetime import datetime
            age_days = (datetime.now() - spac.ipo_date).days
            spac_age_years = age_days / 365.25

        # Estimate reasonable maximum trust cash:
        # - Base IPO proceeds
        # - Plus 15% overallotment (if exercised, may not be in 424B4)
        # - Plus interest: ~4% annual average (conservative estimate)
        max_reasonable_trust = ipo_value * (
            1.15 +  # Overallotment
            (0.04 * spac_age_years)  # Interest accumulation
        )

        # Flag if trust cash exceeds reasonable maximum by >10% (safety margin)
        if spac.trust_cash > max_reasonable_trust * 1.10:
            # Calculate what the excess suggests
            excess_pct = (spac.trust_cash / ipo_value - 1) * 100
            expected_max_pct = (max_reasonable_trust / ipo_value - 1) * 100

            issues.append({
                'type': 'data_corruption',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'trust_cash',
                'rule': 'Trust Cash vs IPO Proceeds (AEXA Lesson, Updated Oct 10)',
                'message': f'Trust cash ${spac.trust_cash/1e6:.1f}M is {excess_pct:.1f}% above IPO ${ipo_value/1e6:.1f}M (age: {spac_age_years:.1f}y) - exceeds reasonable maximum',
                'auto_fix': 'recalculate_from_424b4',
                'expected': int(max_reasonable_trust),  # Raw numeric value (e.g., 138000000)
                'expected_display': f'<= ${max_reasonable_trust/1e6:.1f}M ({expected_max_pct:.1f}% above IPO: 15% overallotment + {spac_age_years*4:.1f}% interest)',  # Human-readable for messages
                'actual': f'${spac.trust_cash/1e6:.1f}M ({excess_pct:.1f}% above IPO)',
                'recommendation': 'Re-scrape 424B4 filing to verify IPO structure and check for overallotment exercise',
                'data_quality_lesson': 'Trust cash can legitimately exceed IPO proceeds due to interest and overallotment. Only flag excessive values likely from circular calculations.'
            })

        return issues

    def validate_false_positive_deals(self, spac: SPAC) -> List[Dict]:
        """
        Validate that ANNOUNCED deals are actually real deals
        Detects false positives where 8-K was for extension/termination/etc.

        Root cause: Deal detector may misclassify 8-K Item 1.01 filings
        """
        issues = []

        if spac.deal_status != 'ANNOUNCED':
            return issues

        # Check 1: ANNOUNCED but no target
        if not spac.target or spac.target in ['-', '', 'Unknown']:
            issues.append({
                'type': 'logical_inconsistency',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'deal_status',
                'rule': 'False Positive Deal Detection',
                'message': 'Marked as ANNOUNCED but no valid target',
                'auto_fix': 'investigate_deal_filing',
                'expected': 'SEARCHING (if no real deal)',
                'actual': 'ANNOUNCED',
                'context': {
                    'target': spac.target,
                    'deal_filing_url': spac.deal_filing_url,
                    'announced_date': str(spac.announced_date) if spac.announced_date else None
                }
            })

        # Check 2: ANNOUNCED but no announced_date AND no deal_filing_url
        if not spac.announced_date and not spac.deal_filing_url:
            issues.append({
                'type': 'logical_inconsistency',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'deal_status',
                'rule': 'False Positive Deal Detection',
                'message': 'Marked as ANNOUNCED but no announced_date or filing URL',
                'auto_fix': 'investigate_deal_filing',
                'expected': 'Valid deal with date or filing reference',
                'actual': 'Missing both date and filing URL',
                'context': {
                    'target': spac.target,
                    'deal_filing_url': spac.deal_filing_url,
                    'announced_date': None
                }
            })

        # Check 3: Only flag suspicious deals for verification (selective approach)
        # Only flag very old deals (>18 months) without a shareholder vote scheduled
        # This catches deals that may have terminated or been abandoned
        if spac.target and spac.announced_date and not spac.shareholder_vote_date:
            from datetime import datetime
            days_since_announced = (datetime.now().date() - spac.announced_date.date()).days if hasattr(spac.announced_date, 'date') else (datetime.now().date() - spac.announced_date).days

            if days_since_announced > 540:  # 18+ months without shareholder vote
                issues.append({
                    'type': 'verification_needed',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'deal_status',
                    'rule': 'Stale Deal - Verify Status',
                    'message': f'Deal announced {int(days_since_announced/30)} months ago without shareholder vote - may be terminated',
                    'auto_fix': 'verify_deal_filing',
                    'expected': 'Deal progressing to vote or completion',
                    'actual': f'No shareholder vote after {int(days_since_announced/30)} months',
                    'context': {
                        'target': spac.target,
                        'deal_filing_url': spac.deal_filing_url,
                        'announced_date': str(spac.announced_date) if spac.announced_date else None,
                        'days_since_announced': days_since_announced
                    }
                })

        # Check 4: Large negative premium on announced deal (suspicious)
        # Trading significantly below NAV suggests deal issues, termination, or poor terms
        if spac.deal_status == 'ANNOUNCED' and spac.premium is not None and spac.premium < -5.0:
            issues.append({
                'type': 'verification_needed',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'deal_status',
                'rule': 'Negative Premium Deal',
                'message': f'Deal trading at {spac.premium:.1f}% below NAV - verify deal has not terminated or is not in trouble',
                'auto_fix': 'investigate_deal_status',
                'expected': 'Announced deals typically trade at or above NAV',
                'actual': f'Trading at {spac.premium:.1f}% below NAV (${spac.price} vs ${spac.trust_value} trust)',
                'context': {
                    'target': spac.target,
                    'premium': spac.premium,
                    'price': spac.price,
                    'trust_value': spac.trust_value,
                    'announced_date': str(spac.announced_date) if spac.announced_date else None,
                    'deal_filing_url': spac.deal_filing_url,
                    'shareholder_vote_date': str(spac.shareholder_vote_date) if spac.shareholder_vote_date else None
                }
            })

        # Check 5: Deals older than 12 months - verify not terminated or replaced
        # ISRL lesson: 24-month pomvom deal was actually terminated and replaced with Gadfin
        if spac.target and spac.announced_date and not spac.shareholder_vote_date:
            from datetime import datetime
            days_since_announced = (datetime.now().date() - spac.announced_date.date()).days if hasattr(spac.announced_date, 'date') else (datetime.now().date() - spac.announced_date).days

            if days_since_announced > 365:  # 12+ months without shareholder vote
                issues.append({
                    'type': 'verification_needed',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'deal_status',
                    'rule': 'Old Deal - Verify Not Terminated/Replaced',
                    'message': f'Deal announced {int(days_since_announced/30)} months ago without shareholder vote - verify not terminated or replaced with new deal',
                    'auto_fix': 'verify_old_deal_status',
                    'expected': 'Recent deal or shareholder vote scheduled',
                    'actual': f'No shareholder vote after {int(days_since_announced/30)} months',
                    'context': {
                        'target': spac.target,
                        'announced_date': str(spac.announced_date) if spac.announced_date else None,
                        'deal_filing_url': spac.deal_filing_url,
                        'days_since_announced': days_since_announced
                    }
                })

        return issues

    def validate_price_trading_status(self, spac: SPAC) -> List[Dict]:
        """
        Validate that price_change_24h is not null during trading hours
        Null price_change indicates stock may be delisted or ticker changed

        Root cause: Stock stopped trading (delisting, ticker change, merger closed)

        GSRT lesson (Oct 17, 2025): Extended check to 7 days (was 2 days)
        - GSRT closed Oct 9, Form 25 filed Oct 10
        - Last price Oct 14, but NULL price_change not flagged (3 days old)
        - Need longer window to catch recent completions
        """
        issues = []

        # Only check if we have a recent price update
        if not spac.last_price_update:
            return issues

        # Check if price was updated recently (within last 7 days) - extended from 2 days
        days_since_update = (datetime.now() - spac.last_price_update).days

        if days_since_update <= 7:
            # If price was updated recently but price_change_24h is null, investigate
            if spac.price and spac.price_change_24h is None:
                # Count how many other SPACs have valid price_change_24h (market is open)
                market_active = self.db.query(SPAC).filter(
                    SPAC.price_change_24h.isnot(None),
                    SPAC.last_price_update >= datetime.now() - timedelta(days=1)
                ).count()

                # For ANNOUNCED deals, always flag NULL price_change (may indicate completion)
                # For other deals, only flag if market is active
                should_flag = (spac.deal_status == 'ANNOUNCED') or (market_active > 10)

                if should_flag:
                    issues.append({
                        'type': 'anomaly',
                        'severity': 'CRITICAL',
                        'ticker': spac.ticker,
                        'field': 'price_change_24h',
                        'rule': 'Price Trading Status',
                        'message': f'Price updated but no daily change (null) - possible delisting or ticker change',
                        'auto_fix': 'investigate_trading_status',
                        'expected': 'Non-null price_change_24h when market is active',
                        'actual': 'NULL',
                        'context': {
                            'price': spac.price,
                            'last_price_update': str(spac.last_price_update),
                            'deal_status': spac.deal_status,
                            'target': spac.target,
                            'market_active_spacs': market_active,
                            'investigation_needed': True
                        },
                        'metadata': {
                            'cik': spac.cik,
                            'announced_date': str(spac.announced_date) if spac.announced_date else None,
                            'target': spac.target
                        },
                        'investigation_hypothesis': [
                            'Stock delisted after merger closed',
                            'Ticker changed to new company symbol',
                            'Trading halted pending announcement',
                            'Wrong ticker in database',
                            'API data quality issue'
                        ]
                    })

        return issues

    def validate_price_component_consistency(self, spac: SPAC) -> List[Dict]:
        """
        Validate that price field matches common_price (not unit_price)

        Lesson from WLAC (Oct 20, 2025):
        - Units (WLACU) still traded but were illiquid
        - Main 'price' field had old unit price ($15) instead of common price ($13.40)
        - This caused incorrect premium calculations and display issues

        Rule: price should ALWAYS equal common_price when common_price is available
        Units trade separately and should only be in unit_price field
        """
        issues = []

        # Only validate if we have both price and common_price
        if spac.price and spac.common_price:
            price_diff = abs(spac.price - spac.common_price)

            # Allow tiny differences due to timing (different API calls)
            # but flag anything >$0.10 as likely being wrong ticker
            if price_diff > 0.10:
                # Calculate what premium WOULD be if we used wrong price field
                # vs what it SHOULD be using correct common_price
                if spac.trust_value:
                    wrong_premium = ((spac.price - float(spac.trust_value)) / float(spac.trust_value)) * 100
                    correct_premium = ((spac.common_price - float(spac.trust_value)) / float(spac.trust_value)) * 100
                    impact_msg = f"If price field is used: {wrong_premium:.1f}% premium (WRONG). Should be {correct_premium:.1f}% based on common price"
                else:
                    impact_msg = "Incorrect premium calculation - trust_value missing"

                issues.append({
                    'ticker': spac.ticker,
                    'severity': 'HIGH',
                    'category': 'PRICE_INTEGRITY',
                    'field': 'price',
                    'issue': f"Main 'price' field (${spac.price:.2f}) doesn't match common_price (${spac.common_price:.2f})",
                    'current_value': spac.price,
                    'expected_value': spac.common_price,
                    'impact': impact_msg,
                    'suggested_fixes': [
                        f'Set price = common_price (${spac.common_price:.2f})',
                        f'Recalculate premium using common price',
                        'price_updater.py should auto-fix on next run'
                    ],
                    'root_cause': 'Stale unit price in main price field (units separated but price not updated)',
                    'prevention': 'price_updater.py now enforces price = common_price (lines 388-391)'
                })

        return issues

    def validate_volume_float_calculation(self, spac: SPAC) -> List[Dict]:
        """
        Validate that Volume % Float can be calculated

        Lesson from APAD, VNME, OACC (Oct 20, 2025):
        - SPACs have volume data but missing shares_outstanding
        - Can't calculate Volume % Float without shares_outstanding
        - This breaks liquidity analysis and deal speculation detection

        Rule: If volume exists, shares_outstanding must exist
        """
        issues = []

        # Check if we have volume but no shares_outstanding
        if (spac.volume or spac.volume_avg_30d) and not spac.shares_outstanding:
            issues.append({
                'ticker': spac.ticker,
                'severity': 'HIGH',
                'category': 'VOLUME_FLOAT_CALCULATION',
                'field': 'shares_outstanding',
                'issue': f'Has volume data but missing shares_outstanding - cannot calculate Volume % Float',
                'current_value': {
                    'volume': spac.volume,
                    'volume_avg_30d': spac.volume_avg_30d,
                    'shares_outstanding': None
                },
                'impact': 'Volume % Float cannot be calculated - breaks liquidity analysis',
                'suggested_fixes': [
                    'Fetch shares_outstanding from Yahoo Finance (sharesOutstanding)',
                    'For $100M IPO at $10/share: shares_outstanding = 10,000,000',
                    'price_updater.py should auto-populate on next run'
                ],
                'root_cause': 'shares_outstanding not fetched from Yahoo or SEC filings',
                'prevention': 'price_updater.py should always fetch sharesOutstanding from Yahoo'
            })

        # Check if shares_outstanding exists but is suspiciously low/high
        elif spac.shares_outstanding:
            if spac.shares_outstanding < 1_000_000:
                issues.append({
                    'ticker': spac.ticker,
                    'severity': 'MEDIUM',
                    'category': 'VOLUME_FLOAT_CALCULATION',
                    'field': 'shares_outstanding',
                    'issue': f'shares_outstanding ({spac.shares_outstanding:,}) is suspiciously low (<1M)',
                    'current_value': spac.shares_outstanding,
                    'impact': 'Volume % Float will be vastly overstated',
                    'suggested_fixes': [
                        'Verify shares_outstanding with Yahoo Finance',
                        'Check if massive redemptions occurred',
                        'IPO proceeds can estimate: $100M IPO = ~10M shares'
                    ]
                })

            elif spac.shares_outstanding > 100_000_000:
                issues.append({
                    'ticker': spac.ticker,
                    'severity': 'MEDIUM',
                    'category': 'VOLUME_FLOAT_CALCULATION',
                    'field': 'shares_outstanding',
                    'issue': f'shares_outstanding ({spac.shares_outstanding:,}) is suspiciously high (>100M)',
                    'current_value': spac.shares_outstanding,
                    'impact': 'Volume % Float will be vastly understated',
                    'suggested_fixes': [
                        'Verify shares_outstanding with Yahoo Finance',
                        'Check if this is post-merger (not a SPAC anymore)',
                        'May have wrong ticker or duplicate data'
                    ]
                })

        return issues

    def validate_stale_announced_deals(self, spac: SPAC) -> List[Dict]:
        """
        Detect stale ANNOUNCED deals that might have completed without detection

        Lesson from ATMV (Oct 11, 2025):
        - ATMV merged with Nauticus Robotics in Sept 2022, new ticker KITT
        - Database still showed ANNOUNCED with wrong target "Wanshun Technology"
        - Deal was 3+ years old but never updated to COMPLETED
        - Form 25 delisting was filed but not detected

        Rules:
        1. ANNOUNCED deals > 18 months old: Flag for investigation (likely completed or terminated)
        2. ANNOUNCED deals > 12 months old: Check for Form 25 filing
        3. Failed price updates on ANNOUNCED deal: Check if ticker changed
        """
        issues = []

        if spac.deal_status != 'ANNOUNCED':
            return issues

        if not spac.announced_date:
            return issues

        # Calculate days since announcement
        days_since_announced = (datetime.now() - spac.announced_date).days

        # SMART CHECK: If deadline_date exists and is in the future, deal is still valid
        # (User learning from ISRL: Check deadline_date for extensions before flagging as stale)
        #
        # Logic:
        # - If deadline in future: Extensions granted, deal valid → DON'T FLAG
        # - If deadline passed: Deal should be completed → FLAG AS CRITICAL
        # - If no deadline: Use time-based heuristic (18 months)
        if spac.deadline_date:
            days_until_deadline = (spac.deadline_date - datetime.now()).days

            if days_until_deadline > 0:
                # Deadline in future - extensions granted, deal is valid
                print(f"  ✅ {spac.ticker}: Announced {days_since_announced} days ago, deadline in {days_until_deadline} days (extensions granted)")
                return issues  # Return empty - not stale
            else:
                # Deadline passed - CRITICAL regardless of time
                days_past_deadline = abs(days_until_deadline)
                print(f"  ⚠️  {spac.ticker}: Deadline passed {days_past_deadline} days ago")

                issues.append({
                    'type': 'stale_data',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'deal_status',
                    'rule': 'Deadline Passed (Deal Should Be Completed)',
                    'message': f'Deadline passed {days_past_deadline} days ago but still ANNOUNCED',
                    'auto_fix': 'investigate_deadline_extension',  # Use Investigation Agent
                    'expected': 'deal_status=COMPLETED or TERMINATED, or deadline_date updated if extension filed',
                    'actual': f'deal_status=ANNOUNCED, {days_past_deadline} days past deadline',
                    'metadata': {
                        'days_since_announced': days_since_announced,
                        'days_past_deadline': days_past_deadline,
                        'deadline_date': spac.deadline_date.isoformat(),
                        'cik': spac.cik,
                        'target': spac.target
                    }
                })
                return issues  # Skip time-based checks

        # Check if this issue is suppressed (user confirmed data is correct)
        def is_suppressed(rule_name: str) -> bool:
            """Check if validation rule is suppressed for this ticker"""
            try:
                from sqlalchemy import text
                result = self.db.execute(
                    text("""
                        SELECT COUNT(*) FROM validation_suppressions
                        WHERE ticker = :ticker
                          AND rule_name = :rule_name
                          AND (expires_at IS NULL OR expires_at > NOW())
                    """),
                    {'ticker': spac.ticker, 'rule_name': rule_name}
                )
                count = result.scalar()
                if count > 0:
                    print(f"  ⏭️  Skipping suppressed rule: {rule_name} for {spac.ticker}")
                return count > 0
            except Exception as e:
                print(f"  ⚠️  Error checking suppression for {spac.ticker}: {e}")
                return False

        # Rule 1: Very old announcements (>18 months = 540 days)
        if days_since_announced > 540 and not is_suppressed('Stale Announced Deal (18+ months)'):
            issues.append({
                'type': 'stale_data',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'deal_status',
                'rule': 'Stale Announced Deal (18+ months)',
                'message': f'Deal announced {days_since_announced} days ago ({int(days_since_announced/30)} months) but still ANNOUNCED - investigate completion',
                'auto_fix': 'investigate_deadline_extension',  # Same method checks completion/termination too
                'expected': 'deal_status=COMPLETED or TERMINATED',
                'actual': f'deal_status=ANNOUNCED for {days_since_announced} days',
                'metadata': {
                    'days_since_announced': days_since_announced,
                    'announced_date': spac.announced_date.isoformat() if spac.announced_date else None,
                    'deadline_date': spac.deadline_date.isoformat() if spac.deadline_date else None,
                    'target': spac.target,
                    'cik': spac.cik
                }
            })

        # Rule 2: Old announcements (>12 months = 365 days)
        elif days_since_announced > 365 and not is_suppressed('Stale Announced Deal (12+ months)'):
            issues.append({
                'type': 'stale_data',
                'severity': 'HIGH',
                'ticker': spac.ticker,
                'field': 'deal_status',
                'rule': 'Stale Announced Deal (12+ months)',
                'message': f'Deal announced {days_since_announced} days ago ({int(days_since_announced/30)} months) - check for Form 25 or completion',
                'auto_fix': 'check_form_25',
                'expected': 'deal_status updated or completion verified',
                'actual': f'deal_status=ANNOUNCED for {days_since_announced} days',
                'metadata': {
                    'days_since_announced': days_since_announced,
                    'announced_date': spac.announced_date.isoformat() if spac.announced_date else None,
                    'target': spac.target,
                    'cik': spac.cik
                }
            })

        # Rule 3: Price update failures (might indicate ticker changed)
        if spac.last_price_update:
            days_since_price_update = (datetime.now() - spac.last_price_update).days

            # If price hasn't updated in 7+ days AND deal is announced
            if days_since_price_update > 7 and days_since_announced > 180:
                issues.append({
                    'type': 'potential_ticker_change',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'ticker',
                    'rule': 'Potential Ticker Change',
                    'message': f'Price not updated for {days_since_price_update} days on ANNOUNCED deal - ticker may have changed after completion',
                    'auto_fix': 'check_ticker_change',
                    'expected': 'new_ticker populated if deal completed',
                    'actual': f'ticker={spac.ticker}, last_update={days_since_price_update} days ago',
                    'metadata': {
                        'days_since_price_update': days_since_price_update,
                        'days_since_announced': days_since_announced,
                        'target': spac.target,
                        'cik': spac.cik
                    }
                })

        return issues

    def validate_temporal_consistency(self, spac: SPAC) -> List[Dict]:
        """
        Validate temporal consistency: dates must respect causality

        Lesson from ATMV (Oct 11, 2025):
        - ATMV showed announced_date=2022-01-31 but ipo_date=2022-12-22
        - Impossible: Can't announce deal BEFORE the SPAC even exists
        - Root cause: Data from CleanTech ATMV attached to AlphaVest ATMV (ticker reuse)

        Rules:
        1. announced_date must be >= ipo_date (can't announce before IPO)
        2. completion_date must be >= announced_date (can't complete before announcing)
        3. completion_date must be >= ipo_date (can't complete before IPO)
        4. merger_termination_date must be >= announced_date (can't terminate before announcing)
        5. deadline_date should be >= ipo_date + 18 months (typical charter)
        """
        issues = []

        if not spac.ipo_date:
            return issues  # Can't validate without IPO date

        ipo_date = spac.ipo_date.date() if isinstance(spac.ipo_date, datetime) else spac.ipo_date

        # Rule 1: Announced date must be >= IPO date
        if spac.announced_date:
            announced_date = spac.announced_date.date() if isinstance(spac.announced_date, datetime) else spac.announced_date

            if announced_date < ipo_date:
                days_before = (ipo_date - announced_date).days
                issues.append({
                    'type': 'temporal_impossibility',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'announced_date',
                    'rule': 'Deal Announced Before IPO',
                    'message': f'Deal announced {days_before} days BEFORE IPO - impossible! Likely ticker reuse data corruption.',
                    'auto_fix': 'investigate_data_source',
                    'expected': f'announced_date >= ipo_date ({ipo_date})',
                    'actual': f'announced_date={announced_date}, ipo_date={ipo_date}',
                    'metadata': {
                        'ipo_date': str(ipo_date),
                        'announced_date': str(announced_date),
                        'days_before_ipo': days_before,
                        'likely_cause': 'Ticker reuse - data from different SPAC with same ticker'
                    }
                })

        # Rule 2: Completion date must be >= announced date
        if spac.completion_date and spac.announced_date:
            completion_date = spac.completion_date.date() if isinstance(spac.completion_date, datetime) else spac.completion_date
            announced_date = spac.announced_date.date() if isinstance(spac.announced_date, datetime) else spac.announced_date

            if completion_date < announced_date:
                days_before = (announced_date - completion_date).days
                issues.append({
                    'type': 'temporal_impossibility',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'completion_date',
                    'rule': 'Deal Completed Before Announced',
                    'message': f'Deal completed {days_before} days BEFORE announcement - impossible!',
                    'auto_fix': None,
                    'expected': f'completion_date >= announced_date ({announced_date})',
                    'actual': f'completion_date={completion_date}, announced_date={announced_date}'
                })

        # Rule 3: Completion date must be >= IPO date
        if spac.completion_date:
            completion_date = spac.completion_date.date() if isinstance(spac.completion_date, datetime) else spac.completion_date

            if completion_date < ipo_date:
                days_before = (ipo_date - completion_date).days
                issues.append({
                    'type': 'temporal_impossibility',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'completion_date',
                    'rule': 'Deal Completed Before IPO',
                    'message': f'Deal completed {days_before} days BEFORE IPO - impossible! Likely ticker reuse data corruption.',
                    'auto_fix': 'investigate_data_source',
                    'expected': f'completion_date >= ipo_date ({ipo_date})',
                    'actual': f'completion_date={completion_date}, ipo_date={ipo_date}',
                    'metadata': {
                        'ipo_date': str(ipo_date),
                        'completion_date': str(completion_date),
                        'days_before_ipo': days_before,
                        'likely_cause': 'Ticker reuse - data from different SPAC with same ticker'
                    }
                })

        # Rule 4: Merger termination date must be >= announced date
        if spac.merger_termination_date and spac.announced_date:
            termination_date = spac.merger_termination_date.date() if isinstance(spac.merger_termination_date, datetime) else spac.merger_termination_date
            announced_date = spac.announced_date.date() if isinstance(spac.announced_date, datetime) else spac.announced_date

            if termination_date < announced_date:
                days_before = (announced_date - termination_date).days
                issues.append({
                    'type': 'temporal_impossibility',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'merger_termination_date',
                    'rule': 'Deal Terminated Before Announced',
                    'message': f'Deal terminated {days_before} days BEFORE announcement - impossible!',
                    'auto_fix': None,
                    'expected': f'termination_date >= announced_date ({announced_date})',
                    'actual': f'termination_date={termination_date}, announced_date={announced_date}'
                })

        # Rule 5: Deadline date should be reasonable (IPO + 18-24 months typical)
        if spac.deadline_date:
            deadline_date = spac.deadline_date.date() if isinstance(spac.deadline_date, datetime) else spac.deadline_date

            if deadline_date < ipo_date:
                days_before = (ipo_date - deadline_date).days
                issues.append({
                    'type': 'temporal_impossibility',
                    'severity': 'CRITICAL',
                    'ticker': spac.ticker,
                    'field': 'deadline_date',
                    'rule': 'Deadline Before IPO',
                    'message': f'Deadline is {days_before} days BEFORE IPO - impossible!',
                    'auto_fix': None,
                    'expected': f'deadline_date >= ipo_date ({ipo_date})',
                    'actual': f'deadline_date={deadline_date}, ipo_date={ipo_date}'
                })

        return issues

    def validate_cik_consistency(self, spac: SPAC) -> List[Dict]:
        """
        Validate CIK matches ticker ownership in SEC database

        Lesson from ATMV (Oct 11, 2025):
        - Ticker "ATMV" was reused by two different SPACs
        - CleanTech ATMV (CIK 1849820) used ticker 2020-2022
        - AlphaVest ATMV (CIK 1937891) uses ticker 2022-present
        - Data from CleanTech leaked into AlphaVest record

        This validator queries SEC API to verify:
        "Does ticker X currently map to CIK Y?"

        If mismatch found, likely causes:
        - Ticker reuse (SPAC completed, ticker freed, new SPAC registered same ticker)
        - Database contains old/stale CIK for this ticker
        - Incorrect initial data load
        """
        issues = []

        if not spac.cik or not spac.ticker:
            return issues

        try:
            import requests
            import time

            # Query SEC company search API
            search_url = f"https://www.sec.gov/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'company': spac.ticker,  # Search by ticker
                'owner': 'exclude',
                'count': 1
            }
            headers = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}

            response = requests.get(search_url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                # Parse HTML response to extract CIK
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')

                # Look for CIK in the page
                cik_element = soup.find('span', {'class': 'companyName'})
                if cik_element:
                    # Extract CIK from "COMPANY NAME CIK#: 0001234567 (see all company filings)"
                    cik_text = cik_element.get_text()
                    import re
                    cik_match = re.search(r'CIK#:\s*(\d+)', cik_text)

                    if cik_match:
                        sec_cik = cik_match.group(1).zfill(10)  # Pad to 10 digits
                        db_cik = spac.cik.zfill(10)

                        if sec_cik != db_cik:
                            issues.append({
                                'type': 'cik_mismatch',
                                'severity': 'CRITICAL',
                                'ticker': spac.ticker,
                                'field': 'cik',
                                'rule': 'CIK Consistency Check',
                                'message': f'CIK mismatch! Database shows CIK {db_cik} but SEC shows ticker {spac.ticker} belongs to CIK {sec_cik}. Likely ticker reuse.',
                                'auto_fix': 'investigate_ticker_reuse',
                                'expected': f'CIK from SEC API: {sec_cik}',
                                'actual': f'CIK in database: {db_cik}',
                                'metadata': {
                                    'database_cik': db_cik,
                                    'sec_api_cik': sec_cik,
                                    'ticker': spac.ticker,
                                    'likely_cause': 'Ticker was reused by different SPAC after original completed/liquidated',
                                    'action_required': 'Verify which SPAC this record should represent. May need to update CIK or create new record.'
                                }
                            })

            # Rate limit SEC requests
            time.sleep(0.15)  # 150ms between requests (max 10/sec)

        except Exception as e:
            # Don't fail validation if SEC API is down
            # Just log the error
            print(f"      ⚠️  CIK validation skipped for {spac.ticker}: {e}")

        return issues

    def validate_data_freshness(self, spac: SPAC) -> List[Dict]:
        """
        Detect suspicious data overwrites - data updated AFTER SEC scraping

        ATMC/ISRL lesson (Oct 17, 2025): Stale loader files overwrote fresh SEC data
        - ATMC target changed from HCYC to wrong "AlphaVest Digital Holdings"
        - ISRL deal_status changed from ANNOUNCED to SEARCHING
        - Both had last_updated > last_scraped_at (data changed AFTER scraping)

        Root cause: load_all_155_spacs.py accidentally run, overwrote 32 SPACs
        """
        issues = []

        # Skip if no scrape timestamp
        if not spac.last_scraped_at or not spac.last_updated:
            return issues

        # Check if data was updated AFTER SEC scraping
        if spac.last_updated > spac.last_scraped_at:
            # Data was modified after scraping - could be legitimate (price update, manual fix)
            # or suspicious (stale data overwrite)

            # Calculate time difference
            time_diff = (spac.last_updated - spac.last_scraped_at).total_seconds() / 3600  # hours

            # Red flags for suspicious overwrites:
            suspicious = False
            red_flags = []

            # Red flag 1: Deal status changed from ANNOUNCED to SEARCHING (without termination)
            # This shouldn't happen unless there's a termination filing
            if spac.deal_status == 'SEARCHING' and not spac.target:
                # Check if this looks like it was recently announced (has deal_filing_url)
                if spac.deal_filing_url:
                    suspicious = True
                    red_flags.append('deal_status=SEARCHING but has deal_filing_url (may have been ANNOUNCED before)')

            # Red flag 2: Target name looks outdated/wrong
            # Check for common incorrect patterns from old data
            if spac.deal_status == 'ANNOUNCED' and spac.target:
                wrong_patterns = [
                    'AlphaVest Digital Holdings',  # Known wrong ATMC target
                    'pomvom ltd.',  # Known wrong ISRL target (old)
                    '[Target TBD]',  # Placeholder
                    'TBD',
                ]
                if any(pattern in spac.target for pattern in wrong_patterns):
                    suspicious = True
                    red_flags.append(f'Target "{spac.target}" matches known incorrect pattern')

            # Red flag 3: Multiple fields changed simultaneously (bulk update signature)
            # Check if last_updated matches exactly with many other SPACs (bulk update)
            if time_diff < 0.1:  # Updated within 6 minutes of scraping
                # Very recent update after scrape - likely manual fix or price update (OK)
                suspicious = False
                red_flags = []

            # Only flag if suspicious
            if suspicious and red_flags:
                issues.append({
                    'type': 'data_freshness',
                    'severity': 'HIGH',
                    'ticker': spac.ticker,
                    'field': 'last_updated',
                    'rule': 'Suspicious Data Overwrite',
                    'message': f'Data updated {time_diff:.1f}h after SEC scraping - possible stale data overwrite. {len(red_flags)} red flag(s) detected.',
                    'auto_fix': 'investigate_data_overwrite',
                    'expected': 'Data updated before or during SEC scraping',
                    'actual': f'Updated {time_diff:.1f}h after last scrape',
                    'context': {
                        'last_scraped_at': str(spac.last_scraped_at),
                        'last_updated': str(spac.last_updated),
                        'hours_after_scrape': round(time_diff, 1),
                        'red_flags': red_flags,
                        'deal_status': spac.deal_status,
                        'target': spac.target,
                        'deal_filing_url': spac.deal_filing_url
                    }
                })

        return issues

    def validate_redemption_data(self, spac: SPAC) -> List[Dict]:
        """
        Validate redemption data completeness and consistency

        Four types of triggers:
        1. Market cap variance >20% (likely unreported redemptions)
        2. Post-vote SPACs without redemption data
        3. Extended SPACs without redemption data
        4. Trust account math inconsistencies
        """
        issues = []

        # TRIGGER 1: Market cap variance >20%
        # Formula: market_cap_variance = |market_cap - (shares_outstanding × price)| / market_cap
        if spac.market_cap and spac.shares_outstanding and spac.price:
            expected_market_cap = (spac.shares_outstanding * spac.price) / 1_000_000  # Convert to millions
            if spac.market_cap > 0:
                variance_pct = abs(spac.market_cap - expected_market_cap) / spac.market_cap * 100

                if variance_pct > 20:
                    issues.append({
                        'type': 'missing_redemption_data',
                        'severity': 'CRITICAL',
                        'field': 'shares_redeemed',
                        'ticker': spac.ticker,
                        'issue': f'Market cap variance {variance_pct:.1f}% suggests unreported redemptions',
                        'current': {
                            'market_cap': spac.market_cap,
                            'expected_market_cap': round(expected_market_cap, 2),
                            'variance_pct': round(variance_pct, 1),
                            'shares_outstanding': spac.shares_outstanding,
                            'shares_redeemed': spac.shares_redeemed
                        },
                        'suggested_fix': 'Investigate recent 8-K Item 5.07 (vote results) or DEFM14A for actual redemptions',
                        'trigger_investigation': True,
                        'investigation_targets': ['8-K Item 5.07', 'DEFM14A', 'DEFR14A', '10-Q/10-K notes']
                    })

        # TRIGGER 2: Post-vote SPACs without redemption data
        # If shareholder_vote_date exists but no redemption data, likely missing
        if spac.shareholder_vote_date:
            if not spac.redemptions_occurred and not spac.shares_redeemed:
                # Ensure vote_date is a date object (not datetime)
                vote_date = spac.shareholder_vote_date.date() if isinstance(spac.shareholder_vote_date, datetime) else spac.shareholder_vote_date
                days_since_vote = (date.today() - vote_date).days

                # Only flag if vote was recent (within 90 days) - older votes might not have data
                if days_since_vote <= 90:
                    issues.append({
                        'type': 'missing_redemption_data',
                        'severity': 'HIGH',
                        'field': 'shares_redeemed',
                        'ticker': spac.ticker,
                        'issue': f'Shareholder vote {days_since_vote} days ago but no redemption data',
                        'current': {
                            'shareholder_vote_date': spac.shareholder_vote_date.isoformat(),
                            'days_since_vote': days_since_vote,
                            'redemptions_occurred': spac.redemptions_occurred,
                            'shares_redeemed': spac.shares_redeemed
                        },
                        'suggested_fix': 'Check 8-K Item 5.07 filed after vote date for redemption results',
                        'trigger_investigation': True,
                        'investigation_targets': ['8-K Item 5.07'],
                        'filing_date_after': spac.shareholder_vote_date.isoformat()
                    })

        # TRIGGER 3: Extended SPACs without redemption data
        # Extensions often trigger redemptions - if extended but no redemption data, likely missing
        if spac.is_extended and spac.extension_date:
            if not spac.redemptions_occurred and not spac.shares_redeemed:
                # Ensure extension_date is a date object (not datetime)
                ext_date = spac.extension_date.date() if isinstance(spac.extension_date, datetime) else spac.extension_date
                days_since_extension = (date.today() - ext_date).days

                # Only flag recent extensions (within 180 days)
                if days_since_extension <= 180:
                    issues.append({
                        'type': 'missing_redemption_data',
                        'severity': 'MEDIUM',
                        'field': 'shares_redeemed',
                        'ticker': spac.ticker,
                        'issue': f'Extension {days_since_extension} days ago but no redemption data',
                        'current': {
                            'extension_date': spac.extension_date.isoformat(),
                            'days_since_extension': days_since_extension,
                            'is_extended': spac.is_extended,
                            'redemptions_occurred': spac.redemptions_occurred,
                            'shares_redeemed': spac.shares_redeemed
                        },
                        'suggested_fix': 'Check 8-K Item 5.03 (extension filing) for redemption details',
                        'trigger_investigation': True,
                        'investigation_targets': ['8-K Item 5.03'],
                        'filing_date_after': spac.extension_date.isoformat()
                    })

        # TRIGGER 4: Trust account math inconsistencies
        # If trust_cash decreased significantly but no redemptions recorded
        if spac.trust_cash and spac.trust_value and spac.shares_outstanding:
            expected_trust_cash = float(spac.trust_value) * float(spac.shares_outstanding)

            # Allow 10% variance for interest accrual / fees
            if expected_trust_cash > 0:
                trust_variance_pct = abs(spac.trust_cash - expected_trust_cash) / expected_trust_cash * 100

                if trust_variance_pct > 15 and not spac.shares_redeemed:
                    issues.append({
                        'type': 'trust_account_inconsistency',
                        'severity': 'MEDIUM',
                        'field': 'trust_cash',
                        'ticker': spac.ticker,
                        'issue': f'Trust account math off by {trust_variance_pct:.1f}% but no redemptions recorded',
                        'current': {
                            'trust_cash': spac.trust_cash,
                            'expected_trust_cash': round(expected_trust_cash, 2),
                            'trust_value': spac.trust_value,
                            'shares_outstanding': spac.shares_outstanding,
                            'variance_pct': round(trust_variance_pct, 1),
                            'shares_redeemed': spac.shares_redeemed
                        },
                        'suggested_fix': 'Check 10-Q/10-K for trust account reconciliation and redemption notes',
                        'trigger_investigation': True,
                        'investigation_targets': ['10-Q', '10-K', '8-K Item 5.07']
                    })

        return issues

    def validate_all(self, spac: SPAC) -> List[Dict]:
        """Run all logical consistency checks - 40+ rules implemented"""
        issues = []

        # Data type & format validation (Rules 1-4, 7)
        issues.extend(self.validate_data_types_and_formats(spac))

        # Deal status consistency (Rule 10, 40)
        issues.extend(self.validate_deal_status_consistency(spac))

        # Date consistency (Rules 30, 32-34, 76)
        issues.extend(self.validate_date_consistency(spac))

        # Premium calculation (Rule 17)
        issues.extend(self.validate_premium_calculation(spac))

        # Trust value validation (Rule 21)
        issues.extend(self.validate_trust_value(spac))

        # Price anomaly detection (Rules 14-16, 20, 43, 86)
        issues.extend(self.validate_price_vs_nav(spac))

        # Deal status lifecycle (Rules 41, 82, 83)
        issues.extend(self.validate_deal_status_lifecycle(spac))

        # Trust cash vs IPO (AEXA lesson)
        issues.extend(self.validate_trust_cash_vs_ipo(spac))

        # False positive deal detection (MAYA/CAEP/GSHR lesson - Oct 11, 2025)
        issues.extend(self.validate_false_positive_deals(spac))

        # Price trading status validation (GSRT lesson - Oct 11, 2025)
        issues.extend(self.validate_price_trading_status(spac))

        # Stale announced deal detection (ATMV lesson - Oct 11, 2025)
        issues.extend(self.validate_stale_announced_deals(spac))

        # Temporal consistency validation (ATMV lesson - Oct 11, 2025)
        issues.extend(self.validate_temporal_consistency(spac))

        # CIK consistency validation (ATMV lesson - Oct 11, 2025)
        # NOTE: This makes HTTP requests to SEC API - expensive, use sparingly
        # Recommend: Run weekly or on-demand, not on every validation
        # issues.extend(self.validate_cik_consistency(spac))

        # Suspicious data overwrite detection (ATMC/ISRL lesson - Oct 17, 2025)
        issues.extend(self.validate_data_freshness(spac))

        # Redemption data validation (Oct 20, 2025)
        # Four triggers: market cap variance, post-vote, extensions, trust math
        issues.extend(self.validate_redemption_data(spac))

        # Price component consistency validation (WLAC lesson - Oct 20, 2025)
        # Ensures main 'price' field matches common_price, not stale unit price
        issues.extend(self.validate_price_component_consistency(spac))

        # Volume % Float calculation validation (APAD/VNME/OACC lesson - Oct 20, 2025)
        # Ensures shares_outstanding exists when volume data exists
        issues.extend(self.validate_volume_float_calculation(spac))

        return issues


class DataValidatorAgent:
    """
    Main Data Validator Agent
    Integrates all validation logic and handles auto-correction
    """

    def __init__(self, auto_fix: bool = False):
        self.db = SessionLocal()
        self.auto_fix = auto_fix
        self.logger = DataValidationLogger()
        self.consistency_validator = LogicalConsistencyValidator()
        self.rules_engine = ValidationRulesEngine()
        self.sec_fetcher = SECFilingFetcher()  # For basic SEC operations

        self.issues_found = {
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': [],
            'INFO': [],
            'WARNING': []  # For compatibility with business rules
        }

        self.fixes_applied = []
        self.needs_research = []  # Issues that need orchestrator to research
        self.orchestrator_delegate = None  # Set by orchestrator if available

    def set_orchestrator_delegate(self, orchestrator):
        """
        Set orchestrator delegate for research requests

        When validator is uncertain about a fix, it can ask orchestrator to:
        1. Dispatch to specialized agents (DealDetector, etc.)
        2. Get research results
        3. Make informed decision
        4. Tell validator what fix to apply
        """
        self.orchestrator_delegate = orchestrator

    def close(self):
        self.db.close()
        self.rules_engine.close()
        self.consistency_validator.close()  # Close the validator's DB session
        # SECFilingFetcher doesn't need cleanup

    def validate_spac(self, spac: SPAC) -> List[Dict]:
        """Run all validations on a SPAC"""
        all_issues = []

        # Logical consistency checks
        all_issues.extend(self.consistency_validator.validate_all(spac))

        # Business logic rules
        for rule in self.rules_engine.rules:
            issue = rule.validate(spac)
            if issue:
                # Convert to consistent format
                all_issues.append({
                    'type': 'business_rule',
                    'severity': issue['severity'].upper(),
                    'ticker': spac.ticker,
                    'field': issue.get('rule'),
                    'rule': issue['rule'],
                    'message': issue['issue'],
                    'auto_fix': None,
                    'current_values': issue.get('current_values', {})
                })

        return all_issues

    def _assess_fix_confidence(self, spac: SPAC, fix_type: str) -> Tuple[str, str]:
        """
        Assess confidence level for a proposed fix

        Returns:
            Tuple of (confidence_level, reason)
            confidence_level: 'HIGH', 'MEDIUM', 'LOW'
            reason: Why this confidence level
        """
        if fix_type == 'set_status_to_SEARCHING':
            # LOW confidence - need to verify if deal actually exists
            return ('LOW', 'Cannot determine if deal exists without checking 8-K filings')

        elif fix_type == 'set_status_to_ANNOUNCED':
            # MEDIUM confidence - target exists but need to verify announcement
            return ('MEDIUM', 'Target field exists but need to verify 8-K announcement')

        elif fix_type == 'recalculate_premium':
            # HIGH confidence - pure calculation
            return ('HIGH', 'Premium is a calculated field, no research needed')

        elif fix_type == 'recalculate_deadline':
            # LOW confidence - need actual charter/extension data
            return ('LOW', 'Deadline should be extracted from S-1 and extension 8-Ks')

        elif fix_type == 'recalculate_from_424b4':
            # LOW confidence - need to re-scrape SEC filing
            return ('LOW', 'Trust data corruption detected - need to re-scrape 424B4 filing for actual IPO structure')

        return ('LOW', 'Unknown fix type')

    def auto_fix_issue(self, spac: SPAC, issue: Dict) -> bool:
        """
        Attempt to automatically fix an issue with detailed WHY and HOW logging

        For low-confidence fixes, delegates to orchestrator for research.

        Logs are formatted for self-learning agent to understand:
        - WHY the issue occurred (root cause)
        - HOW it was fixed (remediation steps)
        - WHAT to check in the future (prevention)
        """
        fix_type = issue.get('auto_fix')

        if not fix_type:
            return False

        # Assess confidence
        confidence, confidence_reason = self._assess_fix_confidence(spac, fix_type)

        # If low confidence and orchestrator available, delegate for research
        if confidence == 'LOW' and self.orchestrator_delegate:
            research_request = {
                'ticker': spac.ticker,
                'cik': spac.cik,
                'issue': issue,
                'fix_type': fix_type,
                'confidence': confidence,
                'reason': confidence_reason
            }
            self.needs_research.append(research_request)
            print(f"  ⚠️  {spac.ticker}: Low confidence on {fix_type}, flagging for orchestrator research")
            return False  # Don't fix yet, wait for orchestrator

        # If low confidence but NO orchestrator, still flag but don't auto-fix
        if confidence == 'LOW':
            self.needs_research.append({
                'ticker': spac.ticker,
                'issue': issue,
                'fix_type': fix_type,
                'confidence': confidence,
                'reason': confidence_reason
            })
            print(f"  ⚠️  {spac.ticker}: Low confidence on {fix_type}, needs manual review")
            return False

        # HIGH/MEDIUM confidence - proceed with auto-fix
        try:
            if fix_type == 'set_status_to_SEARCHING':
                # NOTE: This path won't be hit anymore since it's LOW confidence
                # Kept for backward compatibility if confidence assessment changes
                old_value = spac.deal_status
                old_target = spac.target

                spac.deal_status = 'SEARCHING'
                spac.target = None
                spac.announced_date = None

                # Detailed WHY and HOW explanation
                why = (
                    f"WHY: SPAC {spac.ticker} had deal_status='{old_value}' (ANNOUNCED or other) "
                    f"but target field was invalid ('{old_target}' = {['Unknown', '', '-', None, '[Unknown]', '[Unknown - requires validation]']}). "
                    f"This is a logical inconsistency - ANNOUNCED status REQUIRES a valid target company name. "
                    f"Root cause: Verified via SEC 8-K research that no deal announcement exists."
                )

                how = (
                    f"HOW FIXED: Reset deal_status to 'SEARCHING' and cleared target/announced_date fields after "
                    f"researching SEC 8-K filings. Orchestrator confirmed no deal announcement found. "
                    f"Formula: deal_status='ANNOUNCED' + invalid_target + no_8k_deal → deal_status='SEARCHING' + target=NULL."
                )

                prevention = (
                    f"PREVENTION: When setting deal_status='ANNOUNCED', ALWAYS validate that target field contains "
                    f"a real company name (not empty/Unknown/-). Extract target from 8-K 'definitive agreement' announcements. "
                    f"Run DealDetector agent to find and extract target company names from SEC filings."
                )

                self.logger.log_incorrect_value(
                    spac.ticker, 'deal_status', old_value, 'SEARCHING',
                    f"{why}\n\n{how}\n\n{prevention}",
                    'data_validator_agent'
                )
                return True

            elif fix_type == 'set_status_to_ANNOUNCED':
                old_value = spac.deal_status

                spac.deal_status = 'ANNOUNCED'

                why = (
                    f"WHY: SPAC {spac.ticker} had deal_status='{old_value}' but target field contains "
                    f"a valid company name ('{spac.target}'). This is inconsistent - if there's a target, "
                    f"status should be 'ANNOUNCED'. Root cause: Status field was not updated when deal was announced, "
                    f"or status was incorrectly set to SEARCHING/COMPLETED."
                )

                how = (
                    f"HOW FIXED: Updated deal_status to 'ANNOUNCED' since valid target exists. "
                    f"Formula: valid_target_exists + deal_status!='ANNOUNCED' → deal_status='ANNOUNCED'."
                )

                prevention = (
                    f"PREVENTION: When DealDetector finds a target company, ALWAYS update deal_status='ANNOUNCED' "
                    f"in the same transaction. These two fields must stay in sync."
                )

                self.logger.log_incorrect_value(
                    spac.ticker, 'deal_status', old_value, 'ANNOUNCED',
                    f"{why}\n\n{how}\n\n{prevention}",
                    'data_validator_agent'
                )
                return True

            elif fix_type == 'recalculate_premium':
                if spac.price and spac.trust_value:
                    old_value = spac.premium
                    calculated_premium = ((spac.price - spac.trust_value) / spac.trust_value) * 100
                    spac.premium = calculated_premium

                    why = (
                        f"WHY: Premium stored in database ({old_value:.2f}%) doesn't match calculated value "
                        f"({calculated_premium:.2f}%). Difference: {abs(old_value - calculated_premium):.2f}% points. "
                        f"Root cause: (1) Premium not recalculated after price update, (2) Formula applied incorrectly, "
                        f"or (3) price/trust_value changed but premium wasn't updated."
                    )

                    how = (
                        f"HOW FIXED: Recalculated premium using formula: ((price - trust_value) / trust_value) × 100. "
                        f"Inputs: price=${spac.price}, trust_value=${spac.trust_value}. "
                        f"Calculation: (({spac.price} - {spac.trust_value}) / {spac.trust_value}) × 100 = {calculated_premium:.2f}%."
                    )

                    prevention = (
                        f"PREVENTION: Premium should be DERIVED field, not stored. Either: (1) Make premium a computed property "
                        f"that always calculates on-the-fly, OR (2) Add database trigger to recalculate premium whenever "
                        f"price or trust_value changes. Premium should NEVER be manually set."
                    )

                    self.logger.log_incorrect_value(
                        spac.ticker, 'premium', old_value, spac.premium,
                        f"{why}\n\n{how}\n\n{prevention}",
                        'data_validator_agent'
                    )
                    return True

            elif fix_type == 'recalculate_deadline':
                # Assume 18 months from IPO if not extended
                if spac.ipo_date:
                    old_value = spac.deadline_date
                    calculated_deadline = spac.ipo_date + relativedelta(months=18)
                    spac.deadline_date = calculated_deadline

                    why = (
                        f"WHY: Deadline date validation failed. Issue could be: (1) Deadline < IPO date (impossible), "
                        f"(2) Deadline too short (<12 months after IPO), or (3) Deadline appears incorrect. "
                        f"Root cause: Deadline was not extracted from SEC filings (S-1/424B4), or extension data is missing. "
                        f"Standard SPAC structure: 18-24 month initial deadline, with ability to extend."
                    )

                    how = (
                        f"HOW FIXED: Recalculated deadline as IPO date + 18 months (standard SPAC timeframe). "
                        f"IPO date: {spac.ipo_date}, Calculated deadline: {calculated_deadline}. "
                        f"⚠️  WARNING: This is an ESTIMATE - actual deadline may differ if SPAC charter specified "
                        f"different timeframe or if extensions were granted."
                    )

                    prevention = (
                        f"PREVENTION: Extract actual deadline from S-1/424B4 filings (IPO documents), not assumptions. "
                        f"Look for 'Business Combination Deadline' or 'Termination Date' in charter. Then run "
                        f"QuarterlyReportExtractor on all 10-Q/10-K and subsequent 8-Ks to find extensions. "
                        f"Formula: initial_deadline (from S-1) + extensions (from 8-K/10-Q) = current_deadline."
                    )

                    self.logger.log_incorrect_value(
                        spac.ticker, 'deadline_date', old_value, spac.deadline_date,
                        f"{why}\n\n{how}\n\n{prevention}",
                        'data_validator_agent'
                    )
                    return True

        except Exception as e:
            print(f"  Error auto-fixing {spac.ticker}: {e}")
            return False

        return False

    def apply_fix_with_research(self, spac: SPAC, fix_type: str, research_result: Dict) -> bool:
        """
        Apply a fix with research context provided by orchestrator

        This is called AFTER orchestrator has dispatched to specialized agents
        and gotten research results (e.g., from DealDetector checking 8-Ks)

        Args:
            spac: SPAC to fix
            fix_type: Type of fix to apply
            research_result: Dict with research findings, e.g.:
                {
                    'deal_found': True/False,
                    'target': 'Company Name' or None,
                    'announced_date': datetime or None,
                    'source_filing': '8-K URL',
                    'agent': 'deal_detector'
                }

        Returns:
            True if fix applied successfully
        """
        try:
            if fix_type == 'set_status_to_SEARCHING':
                # Research confirmed no deal exists
                if not research_result.get('deal_found'):
                    old_value = spac.deal_status
                    old_target = spac.target

                    spac.deal_status = 'SEARCHING'
                    spac.target = None
                    spac.announced_date = None

                    why = (
                        f"WHY: SPAC {spac.ticker} had deal_status='{old_value}' but target field was invalid ('{old_target}'). "
                        f"Orchestrator dispatched to {research_result.get('agent', 'SEC research agent')} to verify. "
                        f"Research confirmed: NO deal announcement found in recent 8-K filings. "
                        f"Root cause: Status was incorrectly set to ANNOUNCED, or deal was terminated but status not updated."
                    )

                    how = (
                        f"HOW FIXED: After researching {research_result.get('filings_checked', 'SEC filings')}, "
                        f"confirmed no definitive agreement exists. Reset deal_status to 'SEARCHING' and cleared target/announced_date. "
                        f"Formula: ANNOUNCED + no_target + SEC_research_confirms_no_deal → SEARCHING."
                    )

                    prevention = (
                        f"PREVENTION: Before setting deal_status='ANNOUNCED', ALWAYS extract target from 8-K filing. "
                        f"Use DealDetector agent to find 'definitive agreement' announcements and extract target company name. "
                        f"Never set ANNOUNCED status without valid target."
                    )

                    self.logger.log_incorrect_value(
                        spac.ticker, 'deal_status', old_value, 'SEARCHING',
                        f"{why}\n\n{how}\n\n{prevention}",
                        'data_validator_agent_with_research'
                    )

                    self.fixes_applied.append({
                        'ticker': spac.ticker,
                        'fix_type': fix_type,
                        'research_agent': research_result.get('agent'),
                        'confidence': 'HIGH (verified via research)'
                    })

                    return True

                else:
                    # Research found a deal! Extract target instead of changing status
                    old_target = spac.target

                    spac.target = research_result['target']
                    spac.announced_date = research_result.get('announced_date')
                    # Keep status as ANNOUNCED

                    why = (
                        f"WHY: SPAC {spac.ticker} had deal_status='ANNOUNCED' but target was missing. "
                        f"Orchestrator research found deal announcement in {research_result.get('source_filing', '8-K filing')}. "
                        f"Root cause: Target extraction failed during initial scraping."
                    )

                    how = (
                        f"HOW FIXED: Extracted target company '{research_result['target']}' from "
                        f"{research_result.get('source_filing', 'SEC filing')}. "
                        f"Kept deal_status='ANNOUNCED' (correct). "
                        f"Formula: ANNOUNCED + no_target + research_finds_target → ANNOUNCED + extracted_target."
                    )

                    prevention = (
                        f"PREVENTION: Improve DealDetector extraction patterns to catch target names on first pass. "
                        f"Run validation immediately after scraping to catch missing targets early."
                    )

                    self.logger.log_incorrect_value(
                        spac.ticker, 'target', old_target, spac.target,
                        f"{why}\n\n{how}\n\n{prevention}",
                        'data_validator_agent_with_research'
                    )

                    self.fixes_applied.append({
                        'ticker': spac.ticker,
                        'fix_type': 'extract_target',
                        'research_agent': research_result.get('agent'),
                        'confidence': 'HIGH (verified via research)'
                    })

                    return True

            elif fix_type == 'set_status_to_ANNOUNCED':
                # Research confirmed deal exists
                if research_result.get('deal_found'):
                    old_value = spac.deal_status

                    spac.deal_status = 'ANNOUNCED'
                    if research_result.get('announced_date'):
                        spac.announced_date = research_result['announced_date']

                    why = (
                        f"WHY: SPAC {spac.ticker} had valid target ('{spac.target}') but deal_status was '{old_value}'. "
                        f"Research confirmed deal announcement in {research_result.get('source_filing', '8-K filing')}. "
                        f"Root cause: Status field was not updated when deal was detected."
                    )

                    how = (
                        f"HOW FIXED: Updated deal_status to 'ANNOUNCED' based on verified 8-K filing. "
                        f"Formula: valid_target + research_confirms_8k → ANNOUNCED."
                    )

                    prevention = (
                        f"PREVENTION: When DealDetector finds target, ALWAYS update deal_status='ANNOUNCED' atomically. "
                        f"Use database transaction to ensure both fields update together."
                    )

                    self.logger.log_incorrect_value(
                        spac.ticker, 'deal_status', old_value, 'ANNOUNCED',
                        f"{why}\n\n{how}\n\n{prevention}",
                        'data_validator_agent_with_research'
                    )

                    self.fixes_applied.append({
                        'ticker': spac.ticker,
                        'fix_type': fix_type,
                        'research_agent': research_result.get('agent'),
                        'confidence': 'HIGH (verified via research)'
                    })

                    return True

            return False

        except Exception as e:
            print(f"  ❌ Error applying researched fix for {spac.ticker}: {e}")
            return False

    def validate_all_spacs(self):
        """Validate entire database"""
        print(f"\n{'='*80}")
        print(f"DATA VALIDATOR AGENT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")

        spacs = self.db.query(SPAC).all()

        print(f"Validating {len(spacs)} SPACs...")
        print(f"Auto-fix: {'ENABLED' if self.auto_fix else 'DISABLED'}\n")

        # Track seen issues to avoid duplicates
        seen_issues = set()

        for spac in spacs:
            issues = self.validate_spac(spac)

            for issue in issues:
                # Deduplicate: same ticker + field + auto_fix = duplicate
                issue_key = (issue['ticker'], issue.get('field'), issue.get('auto_fix'))

                if issue_key in seen_issues:
                    # Skip duplicate - already recorded this exact issue
                    continue

                seen_issues.add(issue_key)

                severity = issue['severity']
                self.issues_found[severity].append(issue)

                # Attempt auto-fix if enabled
                if self.auto_fix and issue.get('auto_fix'):
                    if self.auto_fix_issue(spac, issue):
                        self.fixes_applied.append({
                            'ticker': spac.ticker,
                            'issue': issue['message'],
                            'fix': issue['auto_fix']
                        })

        # Commit fixes
        if self.auto_fix and self.fixes_applied:
            self.db.commit()

        self.print_report()

        # Return all issues as a flat list
        all_issues = []
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            all_issues.extend(self.issues_found[severity])

        # AUTO-DETECT RECURRING PATTERNS (NEW!)
        # After validation completes, check if same errors keep occurring
        self._detect_recurring_patterns()

        return all_issues

    def _detect_recurring_patterns(self):
        """Detect if same error types are recurring and trigger code fix agent"""
        from collections import Counter

        # EXCLUDE intentional bulk validation checks (not bugs!)
        # These rules are DESIGNED to check many SPACs at once
        INTENTIONAL_BULK_CHECKS = [
            'Price Trading Status',  # Checks all SPACs with null price_change_24h
            'False Positive Deal Detection',  # Verifies all ANNOUNCED deals
            'Trust Value Range (Age-Adjusted)',  # Validates all trust values
            'Deal Status → Target Consistency',  # Bulk consistency check
        ]

        # Group issues by rule type
        issue_types = [issue.get('rule', 'unknown') for issue in self.issues_found['CRITICAL'] + self.issues_found['HIGH']]
        type_counts = Counter(issue_types)

        # Find patterns that occur 5+ times (threshold for auto-alert)
        # BUT EXCLUDE intentional bulk validation checks
        recurring_patterns = {
            itype: count
            for itype, count in type_counts.items()
            if count >= 5 and itype not in INTENTIONAL_BULK_CHECKS
        }

        if recurring_patterns:
            print(f"\n🔴 RECURRING PATTERNS DETECTED:")
            for pattern, count in recurring_patterns.items():
                print(f"   {pattern}: {count} occurrences")

            # Check if we should send alert (with cooldown tracking)
            should_alert = self._check_pattern_alert_needed(recurring_patterns)
            if should_alert:
                # Send Telegram alert about recurring pattern
                self._send_pattern_alert(recurring_patterns)
            else:
                print(f"   ⏭️  Pattern alert already sent recently (24h cooldown)")

    def _check_pattern_alert_needed(self, patterns: dict) -> bool:
        """Check if pattern alert should be sent (with 24h cooldown)"""
        import json
        from pathlib import Path

        tracking_file = Path('/home/ubuntu/spac-research/.recurring_pattern_alerts.json')

        # Load existing tracking data
        if tracking_file.exists():
            with open(tracking_file, 'r') as f:
                tracking_data = json.load(f)
        else:
            tracking_data = {}

        now = datetime.now()

        # Check if any pattern needs alerting
        needs_alert = False
        for pattern in patterns.keys():
            last_alert_str = tracking_data.get(pattern)

            if last_alert_str is None:
                # Never alerted for this pattern
                needs_alert = True
            else:
                # Check if 24 hours passed since last alert
                last_alert = datetime.fromisoformat(last_alert_str)
                hours_since_alert = (now - last_alert).total_seconds() / 3600

                if hours_since_alert >= 24:
                    needs_alert = True

        # Update tracking file if we're sending an alert
        if needs_alert:
            for pattern in patterns.keys():
                tracking_data[pattern] = now.isoformat()

            with open(tracking_file, 'w') as f:
                json.dump(tracking_data, f, indent=2)

        return needs_alert

    def _send_pattern_alert(self, patterns: dict):
        """Send Telegram alert about recurring error patterns"""
        from utils.telegram_notifier import send_telegram_alert

        message = f"""🔴 <b>RECURRING ERROR PATTERN DETECTED</b>

The system found errors repeating multiple times:

"""
        for pattern, count in patterns.items():
            message += f"• <b>{pattern}</b>: {count} occurrences\n"

        message += f"""

<b>🤖 SELF-HEALING SYSTEM RECOMMENDATION:</b>

This pattern suggests a systemic issue that should be fixed in the code or prompts.

<b>Action Required:</b>
Ask Claude Code: "<i>Fix the {list(patterns.keys())[0]} issue</i>"

Claude will:
1. Analyze the root cause
2. Propose a code or prompt fix
3. Apply the fix after your approval
4. Track effectiveness

<b>Why This Matters:</b>
Fixing the root cause prevents these errors from recurring,
rather than fixing them one-by-one in the data.
"""

        send_telegram_alert(message)
        print(f"   📱 Sent pattern alert to Telegram")

    def print_report(self):
        """Print validation report"""
        total_issues = sum(len(v) for v in self.issues_found.values())

        print(f"\n{'='*80}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*80}\n")

        print(f"Total issues found: {total_issues}")
        print(f"  CRITICAL: {len(self.issues_found['CRITICAL'])}")
        print(f"  HIGH: {len(self.issues_found['HIGH'])}")
        print(f"  MEDIUM: {len(self.issues_found['MEDIUM'])}")
        print(f"  LOW: {len(self.issues_found['LOW'])}\n")

        if self.fixes_applied:
            print(f"Auto-fixes applied: {len(self.fixes_applied)}\n")

        if self.needs_research:
            print(f"⚠️  Issues needing research: {len(self.needs_research)}")
            print("   (Flagged for orchestrator to dispatch specialized agents)\n")

        # Show critical issues
        if self.issues_found['CRITICAL']:
            print(f"{'='*80}")
            print(f"🔴 CRITICAL ISSUES ({len(self.issues_found['CRITICAL'])})")
            print(f"{'='*80}\n")

            for issue in self.issues_found['CRITICAL'][:20]:  # Show first 20
                print(f"[{issue['ticker']}] {issue['rule']}")
                print(f"  {issue['message']}")
                if issue.get('auto_fix'):
                    print(f"  Auto-fix: {issue['auto_fix']}")
                print()

        # Alert on critical issues - DISABLED
        # Issues are now handled by the validation queue system
        # Direct Telegram alerts would bypass the conversational queue
        # and spam the user with multiple messages
        #
        # if len(self.issues_found['CRITICAL']) > 0:
        #     critical_count = len(self.issues_found['CRITICAL'])
        #     high_count = len(self.issues_found['HIGH'])
        #
        #     alert_msg = f"⚠️ <b>DATA VALIDATION ALERT</b> ⚠️\n\n"
        #     alert_msg += f"<b>{critical_count}</b> CRITICAL data issues detected\n"
        #     alert_msg += f"<b>{high_count}</b> HIGH priority issues\n\n"
        #
        #     if self.fixes_applied:
        #         alert_msg += f"✅ Auto-fixed {len(self.fixes_applied)} issues\n\n"
        #
        #     alert_msg += "Top critical issues:\n"
        #     for issue in self.issues_found['CRITICAL'][:5]:
        #         alert_msg += f"• {issue['ticker']}: {issue['message'][:80]}\n"
        #
        #     send_telegram_alert(alert_msg)

    def get_statistics(self) -> Dict:
        """Get validation statistics"""
        return {
            'total_issues': sum(len(v) for v in self.issues_found.values()),
            'by_severity': {k: len(v) for k, v in self.issues_found.items()},
            'fixes_applied': len(self.fixes_applied),
            'needs_research': len(self.needs_research),
            'auto_fix_enabled': self.auto_fix
        }

    def get_critical_issues(self) -> List[Dict]:
        """
        Get all CRITICAL severity issues with full details

        Returns:
            List of issue dicts with ticker, field, issue_type, description, auto_fix_strategy
        """
        return self.issues_found.get('CRITICAL', [])

    def get_high_priority_issues(self) -> List[Dict]:
        """
        Get all HIGH severity issues with full details

        Returns:
            List of issue dicts with ticker, field, issue_type, description, auto_fix_strategy
        """
        return self.issues_found.get('HIGH', [])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Data Validator Agent')
    parser.add_argument('--auto-fix', action='store_true', help='Automatically fix issues where possible')
    parser.add_argument('--ticker', help='Validate specific ticker only')
    args = parser.parse_args()

    agent = DataValidatorAgent(auto_fix=args.auto_fix)

    try:
        if args.ticker:
            spac = agent.db.query(SPAC).filter(SPAC.ticker == args.ticker).first()
            if spac:
                print(f"Validating {args.ticker}...\n")
                issues = agent.validate_spac(spac)

                if not issues:
                    print("✅ No issues found")
                else:
                    print(f"Found {len(issues)} issues:\n")
                    for issue in issues:
                        print(f"[{issue['severity']}] {issue['rule']}")
                        print(f"  {issue['message']}\n")
            else:
                print(f"Ticker {args.ticker} not found")
        else:
            agent.validate_all_spacs()

    finally:
        agent.close()
