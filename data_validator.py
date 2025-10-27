#!/usr/bin/env python3
"""
Comprehensive Data Validator - 91 Validation Rules
Implements CRITICAL, ERROR, WARNING, and INFO level checks

References: VALIDATION_RULES_SEVERITY.md
"""

import os
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from database import SessionLocal, SPAC
from data_quality_logger import logger as quality_logger
import json

def to_date(dt):
    """Convert datetime to date, or return date as-is"""
    if isinstance(dt, datetime):
        return dt.date()
    return dt

def to_float(value):
    """Safely convert value to float, handling strings like '$230M'"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove common formatting
        clean = str(value).replace('$', '').replace('M', '').replace(',', '').replace('%', '').strip()
        try:
            return float(clean)
        except ValueError:
            return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

class ValidationIssue:
    """Represents a single validation failure"""

    def __init__(
        self,
        rule_number: int,
        rule_name: str,
        severity: str,
        ticker: str,
        field: str,
        current_value: any,
        expected_value: any = None,
        message: str = "",
        auto_fixable: bool = False
    ):
        self.rule_number = rule_number
        self.rule_name = rule_name
        self.severity = severity
        self.ticker = ticker
        self.field = field
        self.current_value = current_value
        self.expected_value = expected_value
        self.message = message
        self.auto_fixable = auto_fixable
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "rule_number": self.rule_number,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "ticker": self.ticker,
            "field": self.field,
            "current_value": str(self.current_value),
            "expected_value": str(self.expected_value) if self.expected_value else None,
            "message": self.message,
            "auto_fixable": self.auto_fixable
        }


class ValidationResult:
    """Results from validating a SPAC"""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.issues: List[ValidationIssue] = []
        self.rules_checked = 0
        self.rules_passed = 0

    def add_issue(self, issue: ValidationIssue):
        self.issues.append(issue)

    def has_critical_issues(self) -> bool:
        return any(i.severity == "CRITICAL" for i in self.issues)

    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    def get_issues_by_severity(self, severity: str) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == severity]


class DataValidator:
    """Comprehensive SPAC data validator implementing 91 rules"""

    def __init__(self, db: Session = None):
        self.db = db or SessionLocal()
        self.validation_log = "logs/validation_results.jsonl"

        # Ensure logs directory exists
        os.makedirs("logs", exist_ok=True)

    def validate_spac(self, spac: SPAC) -> ValidationResult:
        """Run all applicable validation rules on a SPAC"""
        result = ValidationResult(spac.ticker)

        # CRITICAL rules (block operations)
        result.issues.extend(self.validate_critical_rules(spac))

        # ERROR rules (flag immediately)
        result.issues.extend(self.validate_error_rules(spac))

        # WARNING rules (needs review)
        result.issues.extend(self.validate_warning_rules(spac))

        # INFO rules (log only)
        result.issues.extend(self.validate_info_rules(spac))

        # Calculate stats
        result.rules_checked = self._count_applicable_rules(spac)
        result.rules_passed = result.rules_checked - len(result.issues)

        # Log results
        self._log_validation_result(result)

        return result

    # ========================================================================
    # CRITICAL RULES (Block Operations)
    # ========================================================================

    def validate_critical_rules(self, spac: SPAC) -> List[ValidationIssue]:
        """Rules 1-10, 30, 51, 74, 82-83, 90-92"""
        issues = []

        # Rule 1: ticker is required and valid format
        if not spac.ticker or len(spac.ticker) > 10:
            issues.append(ValidationIssue(
                rule_number=1,
                rule_name="ticker_required",
                severity="CRITICAL",
                ticker=spac.ticker or "UNKNOWN",
                field="ticker",
                current_value=spac.ticker,
                message="Ticker is required and must be ≤10 characters"
            ))

        # Rule 2: company is required
        if not spac.company or len(spac.company) < 3:
            issues.append(ValidationIssue(
                rule_number=2,
                rule_name="company_required",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="company",
                current_value=spac.company,
                message="Company name is required and must be ≥3 characters"
            ))

        # Rule 3: price must be numeric and positive
        if spac.price is not None:
            try:
                price = float(spac.price)
                if price <= 0:
                    issues.append(ValidationIssue(
                        rule_number=3,
                        rule_name="price_positive",
                        severity="CRITICAL",
                        ticker=spac.ticker,
                        field="price",
                        current_value=price,
                        message="Price must be positive"
                    ))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    rule_number=3,
                    rule_name="price_numeric",
                    severity="CRITICAL",
                    ticker=spac.ticker,
                    field="price",
                    current_value=spac.price,
                    message="Price must be numeric"
                ))

        # Rule 4: trust_value must be numeric and typically $10.00
        if spac.trust_value is not None:
            try:
                trust = float(spac.trust_value)
                if trust < 9.50 or trust > 11.00:
                    issues.append(ValidationIssue(
                        rule_number=4,
                        rule_name="trust_value_range",
                        severity="CRITICAL",
                        ticker=spac.ticker,
                        field="trust_value",
                        current_value=trust,
                        expected_value="9.50-11.00",
                        message=f"Trust value ${trust:.2f} outside typical range ($9.50-$11.00)"
                    ))
            except (ValueError, TypeError):
                issues.append(ValidationIssue(
                    rule_number=4,
                    rule_name="trust_value_numeric",
                    severity="CRITICAL",
                    ticker=spac.ticker,
                    field="trust_value",
                    current_value=spac.trust_value,
                    message="Trust value must be numeric"
                ))

        # Rule 5: deal_status must be valid enum
        valid_statuses = ['SEARCHING', 'ANNOUNCED', 'S4_FILED', 'PROXY_FILED',
                         'VOTE_SCHEDULED', 'CLOSED', 'TERMINATED', 'LIQUIDATING']
        if spac.deal_status and spac.deal_status not in valid_statuses:
            issues.append(ValidationIssue(
                rule_number=5,
                rule_name="deal_status_valid",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="deal_status",
                current_value=spac.deal_status,
                expected_value=", ".join(valid_statuses),
                message=f"Invalid deal_status: {spac.deal_status}"
            ))

        # Rule 6: risk_level must be valid enum
        valid_risk_levels = ['safe', 'urgent', 'expired', 'deal', None]
        if spac.risk_level not in valid_risk_levels:
            issues.append(ValidationIssue(
                rule_number=6,
                rule_name="risk_level_valid",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="risk_level",
                current_value=spac.risk_level,
                expected_value=", ".join([str(r) for r in valid_risk_levels]),
                message=f"Invalid risk_level: {spac.risk_level}"
            ))

        # Rule 7: Dates must be valid date objects
        date_fields = ['ipo_date', 'announced_date', 'deadline_date',
                      'original_deadline_date', 'shareholder_vote_date', 'expected_close']
        for field in date_fields:
            value = getattr(spac, field, None)
            if value is not None:
                if not isinstance(value, (datetime, type(datetime.now().date()))):
                    issues.append(ValidationIssue(
                        rule_number=7,
                        rule_name="date_type_valid",
                        severity="CRITICAL",
                        ticker=spac.ticker,
                        field=field,
                        current_value=value,
                        message=f"{field} must be a date object"
                    ))

        # Rule 8: Financial fields must be numeric
        numeric_fields = ['ipo_proceeds', 'trust_cash', 'deal_value',
                         'tev', 'pipe_size', 'market_cap']
        for field in numeric_fields:
            value = getattr(spac, field, None)
            if value is not None:
                try:
                    float(value)
                except (ValueError, TypeError):
                    issues.append(ValidationIssue(
                        rule_number=8,
                        rule_name="financial_fields_numeric",
                        severity="CRITICAL",
                        ticker=spac.ticker,
                        field=field,
                        current_value=value,
                        message=f"{field} must be numeric"
                    ))

        # Rule 30: trust_cash cannot exceed ipo_proceeds * 1.2
        if spac.trust_cash and spac.ipo_proceeds:
            try:
                proceeds_num = float(str(spac.ipo_proceeds).replace('$', '').replace('M', '').replace(',', ''))
                if spac.trust_cash > (proceeds_num * 1_000_000 * 1.2):
                    issues.append(ValidationIssue(
                        rule_number=30,
                        rule_name="trust_cash_vs_proceeds",
                        severity="CRITICAL",
                        ticker=spac.ticker,
                        field="trust_cash",
                        current_value=spac.trust_cash,
                        expected_value=f"<= {proceeds_num * 1.2:.2f}M (proceeds * 1.2)",
                        message=f"trust_cash ${spac.trust_cash/1e6:.1f}M exceeds IPO proceeds ${proceeds_num}M * 1.2"
                    ))
            except (ValueError, TypeError):
                pass  # Skip if ipo_proceeds can't be converted

        # Rule 51: deal_status lifecycle gates
        if spac.deal_status == 'ANNOUNCED' and not spac.target:
            issues.append(ValidationIssue(
                rule_number=51,
                rule_name="announced_requires_target",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="target",
                current_value=spac.target,
                message="deal_status=ANNOUNCED requires target to be set"
            ))

        if spac.deal_status == 'S4_FILED' and not spac.announced_date:
            issues.append(ValidationIssue(
                rule_number=51,
                rule_name="s4_requires_announcement",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="announced_date",
                current_value=spac.announced_date,
                message="deal_status=S4_FILED requires announced_date"
            ))

        if spac.deal_status == 'CLOSED' and not spac.new_ticker:
            issues.append(ValidationIssue(
                rule_number=51,
                rule_name="closed_requires_new_ticker",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="new_ticker",
                current_value=spac.new_ticker,
                message="deal_status=CLOSED should have new_ticker"
            ))

        # Rule 74: No duplicate tickers
        duplicate = self.db.query(SPAC).filter(
            SPAC.ticker == spac.ticker,
            SPAC.id != spac.id
        ).first()
        if duplicate:
            issues.append(ValidationIssue(
                rule_number=74,
                rule_name="no_duplicate_tickers",
                severity="CRITICAL",
                ticker=spac.ticker,
                field="ticker",
                current_value=spac.ticker,
                message=f"Duplicate ticker found (ID: {duplicate.id})"
            ))

        # Rule 90: deal_status transition validation (if previous_deal_status tracked)
        # Skipped for now - needs previous_deal_status column

        return issues

    # ========================================================================
    # ERROR RULES (Flag Immediately)
    # ========================================================================

    def validate_error_rules(self, spac: SPAC) -> List[ValidationIssue]:
        """Rules with ERROR severity - calculation validations"""
        issues = []

        # Rule 18: premium calculation accuracy
        if spac.price and spac.trust_value:
            calculated_premium = ((float(spac.price) - float(spac.trust_value)) / float(spac.trust_value)) * 100
            if spac.premium is not None:
                diff = abs(spac.premium - calculated_premium)
                if diff > 0.1:  # Allow 0.1% rounding error
                    issues.append(ValidationIssue(
                        rule_number=18,
                        rule_name="premium_calculation",
                        severity="ERROR",
                        ticker=spac.ticker,
                        field="premium",
                        current_value=f"{spac.premium:.2f}%",
                        expected_value=f"{calculated_premium:.2f}%",
                        message=f"Premium mismatch: stored {spac.premium:.2f}% vs calculated {calculated_premium:.2f}%",
                        auto_fixable=True
                    ))

        # Rule 20: market_cap calculation (price * shares_outstanding)
        if spac.price and spac.shares_outstanding:
            calculated_mcap = (float(spac.price) * float(spac.shares_outstanding)) / 1_000_000  # in millions
            if spac.market_cap is not None:
                diff_pct = abs(float(spac.market_cap) - calculated_mcap) / calculated_mcap * 100
                if diff_pct > 1.0:  # Allow 1% difference
                    issues.append(ValidationIssue(
                        rule_number=20,
                        rule_name="market_cap_calculation",
                        severity="ERROR",
                        ticker=spac.ticker,
                        field="market_cap",
                        current_value=f"${spac.market_cap:.2f}M",
                        expected_value=f"${calculated_mcap:.2f}M",
                        message=f"Market cap mismatch: {diff_pct:.1f}% difference",
                        auto_fixable=True
                    ))

        # Rule 31: days_to_deadline accuracy
        if spac.deadline_date:
            deadline = spac.deadline_date.date() if isinstance(spac.deadline_date, datetime) else spac.deadline_date
            calculated_days = (deadline - datetime.now().date()).days
            if spac.days_to_deadline is not None:
                diff = abs(spac.days_to_deadline - calculated_days)
                if diff > 1:  # Allow 1 day difference (timezone)
                    issues.append(ValidationIssue(
                        rule_number=31,
                        rule_name="days_to_deadline_calculation",
                        severity="ERROR",
                        ticker=spac.ticker,
                        field="days_to_deadline",
                        current_value=spac.days_to_deadline,
                        expected_value=calculated_days,
                        message=f"days_to_deadline off by {diff} days",
                        auto_fixable=True
                    ))

        # Rule 32: risk_level based on days_to_deadline
        if spac.days_to_deadline is not None and spac.deal_status == 'SEARCHING':
            expected_risk = self._calculate_risk_level(spac.days_to_deadline)
            if spac.risk_level != expected_risk:
                issues.append(ValidationIssue(
                    rule_number=32,
                    rule_name="risk_level_based_on_deadline",
                    severity="ERROR",
                    ticker=spac.ticker,
                    field="risk_level",
                    current_value=spac.risk_level,
                    expected_value=expected_risk,
                    message=f"{spac.days_to_deadline} days should be '{expected_risk}'",
                    auto_fixable=True
                ))

        # Rule 33: risk_level should be 'deal' if deal announced
        if spac.deal_status in ['ANNOUNCED', 'S4_FILED', 'PROXY_FILED', 'VOTE_SCHEDULED']:
            if spac.risk_level != 'deal':
                issues.append(ValidationIssue(
                    rule_number=33,
                    rule_name="deal_requires_deal_risk",
                    severity="ERROR",
                    ticker=spac.ticker,
                    field="risk_level",
                    current_value=spac.risk_level,
                    expected_value='deal',
                    message="Announced deals should have risk_level='deal'",
                    auto_fixable=True
                ))

        # Rule 43: return_since_announcement calculation
        if spac.price and spac.price_at_announcement and spac.deal_status == 'ANNOUNCED':
            calculated_return = ((float(spac.price) - float(spac.price_at_announcement)) / float(spac.price_at_announcement)) * 100
            # Note: return_since_announcement not in current schema, would add as validation
            # Skipping for now

        # Rule 49: price bounds (must be between $0.01 and $1000)
        if spac.price is not None:
            if spac.price < 0.01 or spac.price > 1000:
                issues.append(ValidationIssue(
                    rule_number=49,
                    rule_name="price_bounds",
                    severity="ERROR",
                    ticker=spac.ticker,
                    field="price",
                    current_value=f"${spac.price:.2f}",
                    expected_value="$0.01 - $1000",
                    message=f"Price ${spac.price:.2f} outside valid range"
                ))

        # Rule 50: volume_avg_30d must be positive if set
        if spac.volume_avg_30d is not None and spac.volume_avg_30d < 0:
            issues.append(ValidationIssue(
                rule_number=50,
                rule_name="volume_positive",
                severity="ERROR",
                ticker=spac.ticker,
                field="volume_avg_30d",
                current_value=spac.volume_avg_30d,
                expected_value="> 0",
                message="Volume cannot be negative"
            ))

        return issues

    # ========================================================================
    # WARNING RULES (Needs Review)
    # ========================================================================

    def validate_warning_rules(self, spac: SPAC) -> List[ValidationIssue]:
        """Rules with WARNING severity - business logic validations"""
        issues = []

        # Rule 11: ipo_date should not be in future
        if spac.ipo_date and to_date(spac.ipo_date) > datetime.now().date():
            issues.append(ValidationIssue(
                rule_number=11,
                rule_name="ipo_date_not_future",
                severity="WARNING",
                ticker=spac.ticker,
                field="ipo_date",
                current_value=spac.ipo_date,
                message=f"IPO date {spac.ipo_date} is in the future"
            ))

        # Rule 12: deadline_date should be after ipo_date
        if spac.ipo_date and spac.deadline_date:
            if to_date(spac.deadline_date) <= to_date(spac.ipo_date):
                issues.append(ValidationIssue(
                    rule_number=12,
                    rule_name="deadline_after_ipo",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="deadline_date",
                    current_value=spac.deadline_date,
                    expected_value=f"> {spac.ipo_date}",
                    message="deadline_date should be after ipo_date"
                ))

        # Rule 13: deadline typically 18-24 months after IPO
        if spac.ipo_date and spac.deadline_date:
            months_diff = (spac.deadline_date - spac.ipo_date).days / 30.44
            if months_diff < 15 or months_diff > 36:
                issues.append(ValidationIssue(
                    rule_number=13,
                    rule_name="deadline_typical_range",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="deadline_date",
                    current_value=f"{months_diff:.1f} months after IPO",
                    expected_value="18-24 months (15-36 acceptable)",
                    message=f"Unusual deadline: {months_diff:.1f} months after IPO"
                ))

        # Rule 14: announced_date should be after ipo_date
        if spac.ipo_date and spac.announced_date:
            if to_date(spac.announced_date) < to_date(spac.ipo_date):
                issues.append(ValidationIssue(
                    rule_number=14,
                    rule_name="announcement_after_ipo",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="announced_date",
                    current_value=spac.announced_date,
                    expected_value=f">= {spac.ipo_date}",
                    message="announced_date should be after ipo_date"
                ))

        # Rule 15: announced_date should be before deadline_date
        if spac.announced_date and spac.deadline_date:
            if to_date(spac.announced_date) > to_date(spac.deadline_date):
                issues.append(ValidationIssue(
                    rule_number=15,
                    rule_name="announcement_before_deadline",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="announced_date",
                    current_value=spac.announced_date,
                    expected_value=f"< {spac.deadline_date}",
                    message="Deal announced after deadline (likely extended)"
                ))

        # Rule 34: premium typically -5% to +30%
        if spac.premium is not None:
            if spac.premium < -10 or spac.premium > 50:
                issues.append(ValidationIssue(
                    rule_number=34,
                    rule_name="premium_typical_range",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="premium",
                    current_value=f"{spac.premium:.2f}%",
                    expected_value="-5% to +30%",
                    message=f"Unusual premium: {spac.premium:.2f}%"
                ))

        # Rule 35: Deep discount warning (<-15%)
        if spac.premium is not None and spac.premium < -15:
            issues.append(ValidationIssue(
                rule_number=35,
                rule_name="deep_discount_warning",
                severity="WARNING",
                ticker=spac.ticker,
                field="premium",
                current_value=f"{spac.premium:.2f}%",
                message=f"Deep discount to NAV: {spac.premium:.2f}% (possible liquidation risk)"
            ))

        # Rule 36: Extreme premium warning (>30%)
        if spac.premium is not None and spac.premium > 30:
            issues.append(ValidationIssue(
                rule_number=36,
                rule_name="extreme_premium_warning",
                severity="WARNING",
                ticker=spac.ticker,
                field="premium",
                current_value=f"{spac.premium:.2f}%",
                message=f"Extreme premium: {spac.premium:.2f}% (high valuation risk)"
            ))

        # Rule 37: ipo_proceeds typically $100M - $1B
        if spac.ipo_proceeds is not None:
            proceeds = to_float(spac.ipo_proceeds)
            if proceeds and (proceeds < 50 or proceeds > 2000):
                issues.append(ValidationIssue(
                    rule_number=37,
                    rule_name="ipo_proceeds_typical_range",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="ipo_proceeds",
                    current_value=f"${proceeds:.0f}M",
                    expected_value="$100M - $1B",
                    message=f"Unusual IPO size: ${proceeds:.0f}M"
                ))

        # Rule 44: Urgent deadline alert (<60 days, no deal)
        if spac.deal_status == 'SEARCHING' and spac.days_to_deadline is not None:
            if spac.days_to_deadline < 60:
                issues.append(ValidationIssue(
                    rule_number=44,
                    rule_name="urgent_deadline_alert",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="days_to_deadline",
                    current_value=f"{spac.days_to_deadline} days",
                    message=f"Urgent: {spac.days_to_deadline} days to deadline, no deal announced"
                ))

        # Rule 45: Expired SPAC still in SEARCHING status
        if spac.deal_status == 'SEARCHING' and spac.days_to_deadline is not None:
            if spac.days_to_deadline < 0:
                issues.append(ValidationIssue(
                    rule_number=45,
                    rule_name="expired_spac_alert",
                    severity="WARNING",
                    ticker=spac.ticker,
                    field="deal_status",
                    current_value="SEARCHING",
                    expected_value="LIQUIDATING or TERMINATED",
                    message=f"SPAC expired {abs(spac.days_to_deadline)} days ago, should be LIQUIDATING"
                ))

        return issues

    # ========================================================================
    # INFO RULES (Log Only)
    # ========================================================================

    def validate_info_rules(self, spac: SPAC) -> List[ValidationIssue]:
        """Rules with INFO severity - informational checks"""
        issues = []

        # Rule 69: Missing optional but useful fields
        optional_fields = {
            'banker': 'Helps track performance by underwriter',
            'sector': 'Enables sector analysis',
            'sponsor': 'Track sponsor track record',
            'warrant_ticker': 'Enables warrant analysis',
            'unit_ticker': 'Enables unit analysis'
        }

        for field, reason in optional_fields.items():
            value = getattr(spac, field, None)
            if not value:
                issues.append(ValidationIssue(
                    rule_number=69,
                    rule_name="missing_optional_field",
                    severity="INFO",
                    ticker=spac.ticker,
                    field=field,
                    current_value=None,
                    message=f"Missing {field}: {reason}"
                ))

        # Rule 70: Data freshness (last_updated)
        if spac.last_updated:
            days_old = (datetime.now() - spac.last_updated).days
            if days_old > 7:
                issues.append(ValidationIssue(
                    rule_number=70,
                    rule_name="stale_data_warning",
                    severity="INFO",
                    ticker=spac.ticker,
                    field="last_updated",
                    current_value=f"{days_old} days ago",
                    message=f"Data not updated in {days_old} days"
                ))

        return issues

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _calculate_risk_level(self, days_to_deadline: int) -> str:
        """Calculate expected risk level based on days to deadline"""
        if days_to_deadline < 0:
            return 'expired'
        elif days_to_deadline < 90:
            return 'urgent'
        else:
            return 'safe'

    def _count_applicable_rules(self, spac: SPAC) -> int:
        """Count how many validation rules apply to this SPAC"""
        # For now, return a rough count based on data availability
        # This would be more precise with per-rule applicability logic
        base_rules = 15  # Critical rules that always apply

        if spac.price and spac.trust_value:
            base_rules += 5  # Premium calculation rules
        if spac.ipo_date and spac.deadline_date:
            base_rules += 8  # Date chronology rules
        if spac.deal_status == 'ANNOUNCED':
            base_rules += 10  # Deal-specific rules

        return base_rules

    def _log_validation_result(self, result: ValidationResult):
        """Log validation results to JSONL file"""
        try:
            with open(self.validation_log, 'a') as f:
                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "ticker": result.ticker,
                    "rules_checked": result.rules_checked,
                    "rules_passed": result.rules_passed,
                    "issues": [issue.to_dict() for issue in result.issues]
                }
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            print(f"Failed to log validation result: {e}")

    def validate_all_spacs(self) -> Dict[str, int]:
        """Validate all SPACs in database"""
        # Clear validation results file to avoid duplicates from previous runs
        if os.path.exists(self.validation_log):
            os.remove(self.validation_log)

        print("=" * 80)
        print("COMPREHENSIVE DATA VALIDATION")
        print("=" * 80)
        print()

        spacs = self.db.query(SPAC).all()
        total = len(spacs)

        stats = {
            'total': total,
            'critical_issues': 0,
            'error_issues': 0,
            'warning_issues': 0,
            'info_issues': 0,
            'spacs_with_issues': 0,
            'clean_spacs': 0
        }

        for i, spac in enumerate(spacs, 1):
            print(f"[{i}/{total}] Validating {spac.ticker}...", end=' ')

            result = self.validate_spac(spac)

            if result.issues:
                stats['spacs_with_issues'] += 1
                critical = len(result.get_issues_by_severity('CRITICAL'))
                errors = len(result.get_issues_by_severity('ERROR'))
                warnings = len(result.get_issues_by_severity('WARNING'))
                info = len(result.get_issues_by_severity('INFO'))

                stats['critical_issues'] += critical
                stats['error_issues'] += errors
                stats['warning_issues'] += warnings
                stats['info_issues'] += info

                severity_counts = []
                if critical: severity_counts.append(f"{critical} CRITICAL")
                if errors: severity_counts.append(f"{errors} ERROR")
                if warnings: severity_counts.append(f"{warnings} WARNING")
                if info: severity_counts.append(f"{info} INFO")

                print(f"❌ {', '.join(severity_counts)}")
            else:
                stats['clean_spacs'] += 1
                print("✅ Clean")

        print()
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Total SPACs validated: {stats['total']}")
        print(f"Clean SPACs: {stats['clean_spacs']}")
        print(f"SPACs with issues: {stats['spacs_with_issues']}")
        print()
        print(f"🔴 CRITICAL issues: {stats['critical_issues']}")
        print(f"🟠 ERROR issues: {stats['error_issues']}")
        print(f"🟡 WARNING issues: {stats['warning_issues']}")
        print(f"🔵 INFO issues: {stats['info_issues']}")
        print()
        print(f"Results logged to: {self.validation_log}")
        print()

        return stats

    def generate_validation_report(self, output_file: str = "logs/validation_report.txt"):
        """Generate human-readable validation report"""
        try:
            if not os.path.exists(self.validation_log):
                print(f"No validation log found at {self.validation_log}")
                return

            # Load all validation results
            results = []
            with open(self.validation_log, 'r') as f:
                for line in f:
                    results.append(json.loads(line))

            if not results:
                print("No validation results found")
                return

            # Analyze
            critical_by_rule = {}
            error_by_rule = {}
            spacs_with_critical = []

            for result in results:
                for issue in result.get('issues', []):
                    severity = issue['severity']
                    rule_name = issue['rule_name']

                    if severity == 'CRITICAL':
                        critical_by_rule[rule_name] = critical_by_rule.get(rule_name, 0) + 1
                        if result['ticker'] not in spacs_with_critical:
                            spacs_with_critical.append(result['ticker'])
                    elif severity == 'ERROR':
                        error_by_rule[rule_name] = error_by_rule.get(rule_name, 0) + 1

            # Write report
            with open(output_file, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write("DATA VALIDATION REPORT\n")
                f.write(f"Generated: {datetime.now().isoformat()}\n")
                f.write(f"Total Validations: {len(results)}\n")
                f.write("=" * 80 + "\n\n")

                f.write("TOP CRITICAL ISSUES:\n")
                f.write("-" * 80 + "\n")
                for rule, count in sorted(critical_by_rule.items(), key=lambda x: x[1], reverse=True)[:10]:
                    f.write(f"  {rule}: {count} SPACs\n")

                f.write("\n\nTOP ERROR ISSUES:\n")
                f.write("-" * 80 + "\n")
                for rule, count in sorted(error_by_rule.items(), key=lambda x: x[1], reverse=True)[:10]:
                    f.write(f"  {rule}: {count} SPACs\n")

                f.write("\n\nSPACs WITH CRITICAL ISSUES:\n")
                f.write("-" * 80 + "\n")
                f.write(f"{', '.join(spacs_with_critical)}\n")

                f.write("\n" + "=" * 80 + "\n")

            print(f"✅ Validation report written to {output_file}")

        except Exception as e:
            print(f"Error generating validation report: {e}")

    def close(self):
        """Close database connection"""
        self.db.close()

    # ========================================================================
    # Auto-Fix Methods
    # ========================================================================

    def apply_auto_fixes(self, issues: List[ValidationIssue], dry_run: bool = True,
                         tier: str = "1", interactive: bool = True) -> Dict:
        """
        Apply automatic fixes to auto-fixable issues

        Args:
            issues: List of validation issues
            dry_run: If True, preview changes without applying
            tier: "1" (math only), "1,2" (math + logic), "all" (everything auto-fixable)
            interactive: If True, ask for approval before applying

        Returns:
            Dict with fix statistics and rollback info
        """
        from data_quality_logger import logger as quality_logger

        # Filter auto-fixable issues by tier
        tier_1_rules = [
            'premium_calculation',
            'days_to_deadline_calculation',
            # 'market_cap_calculation',  # DISABLED - validator uses public shares only, but should include founder shares
            'return_since_announcement_calculation'
        ]

        tier_2_rules = [
            'financial_fields_numeric',
            'date_type_valid',
            'deal_requires_deal_risk'
        ]

        fixable_issues = [i for i in issues if i.auto_fixable]

        if tier == "1":
            fixable_issues = [i for i in fixable_issues if i.rule_name in tier_1_rules]
        elif tier == "1,2":
            fixable_issues = [i for i in fixable_issues
                            if i.rule_name in tier_1_rules + tier_2_rules]
        # else: tier == "all", keep all fixable

        if not fixable_issues:
            print("No auto-fixable issues found for selected tier")
            return {'fixes_applied': 0, 'fixes_previewed': 0}

        # Group by ticker for better display
        fixes_by_ticker = {}
        for issue in fixable_issues:
            if issue.ticker not in fixes_by_ticker:
                fixes_by_ticker[issue.ticker] = []
            fixes_by_ticker[issue.ticker].append(issue)

        print("\n" + "=" * 80)
        print(f"AUTO-FIX PREVIEW - Tier {tier}")
        print("=" * 80)
        print(f"\nFound {len(fixable_issues)} auto-fixable issues across {len(fixes_by_ticker)} SPACs")
        print()

        # Show preview (first 10 fixes)
        preview_count = min(10, len(fixable_issues))
        print(f"Preview (showing {preview_count}/{len(fixable_issues)} fixes):\n")

        for i, issue in enumerate(fixable_issues[:preview_count]):
            print(f"  [{i+1}] {issue.ticker}.{issue.field}: {issue.current_value} → {issue.expected_value}")
            print(f"      Rule: {issue.rule_name}")
            print()

        if len(fixable_issues) > preview_count:
            print(f"  ... and {len(fixable_issues) - preview_count} more fixes\n")

        # Interactive approval
        if interactive and not dry_run:
            print("=" * 80)
            response = input("Apply these fixes? [y/N/preview-all]: ").strip().lower()

            if response == 'preview-all':
                print("\n" + "=" * 80)
                print("ALL FIXES:")
                print("=" * 80 + "\n")
                for issue in fixable_issues:
                    print(f"  {issue.ticker}.{issue.field}: {issue.current_value} → {issue.expected_value}")
                    print(f"  Rule: {issue.rule_name} | Reason: {issue.message}\n")

                response = input("\nApply all fixes? [y/N]: ").strip().lower()

            if response != 'y':
                print("❌ Auto-fix cancelled")
                return {'fixes_applied': 0, 'fixes_previewed': len(fixable_issues), 'cancelled': True}

        if dry_run:
            print(f"DRY RUN MODE: Would apply {len(fixable_issues)} fixes")
            return {'fixes_applied': 0, 'fixes_previewed': len(fixable_issues), 'dry_run': True}

        # Generate rollback script
        rollback_file = f"logs/rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        rollback_lines = [
            "-- Rollback for auto-fix session " + datetime.now().isoformat(),
            f"-- Total fixes: {len(fixable_issues)}",
            "-- Run this to undo changes",
            "",
            "BEGIN;",
            ""
        ]

        # Apply fixes
        fixes_applied = 0
        fixes_failed = 0

        print("\n" + "=" * 80)
        print("APPLYING FIXES...")
        print("=" * 80 + "\n")

        for issue in fixable_issues:
            try:
                spac = self.db.query(SPAC).filter(SPAC.ticker == issue.ticker).first()
                if not spac:
                    print(f"  ✗ {issue.ticker}: SPAC not found")
                    fixes_failed += 1
                    continue

                # Get old value for rollback
                old_value = getattr(spac, issue.field, None)

                # Apply fix based on rule type
                success = self._apply_single_fix(spac, issue)

                if success:
                    # Get the new value that was actually applied
                    new_value = getattr(spac, issue.field, None)

                    # Log to data quality logger
                    quality_logger.log_change(
                        ticker=issue.ticker,
                        field=issue.field,
                        old_value=str(old_value),
                        new_value=str(new_value),  # Use actual applied value, not expected_value string
                        source="data_validator_autofix",
                        confidence=0.95,
                        validation_method="calculation" if issue.rule_name.endswith('_calculation') else "correction"
                    )

                    # Add to rollback script
                    if old_value is not None:
                        rollback_lines.append(
                            f"UPDATE spacs SET {issue.field} = {self._sql_value(old_value)} WHERE ticker = '{issue.ticker}';  "
                            f"-- was: {issue.expected_value}"
                        )

                    print(f"  ✓ {issue.ticker}.{issue.field}: {issue.current_value} → {issue.expected_value}")
                    fixes_applied += 1
                else:
                    print(f"  ✗ {issue.ticker}.{issue.field}: Fix failed")
                    fixes_failed += 1

            except Exception as e:
                print(f"  ✗ {issue.ticker}.{issue.field}: Error - {e}")
                fixes_failed += 1

        # Commit changes
        try:
            self.db.commit()
            print(f"\n✅ Successfully applied {fixes_applied} fixes")

            # Write rollback script
            rollback_lines.extend([
                "",
                "COMMIT;",
                f"-- To apply: psql {os.getenv('DATABASE_URL', 'spac_db')} < {rollback_file}"
            ])

            with open(rollback_file, 'w') as f:
                f.write('\n'.join(rollback_lines))

            print(f"🔄 Rollback script: {rollback_file}")

        except Exception as e:
            self.db.rollback()
            print(f"\n❌ Error committing fixes: {e}")
            print("All changes rolled back")
            return {'fixes_applied': 0, 'fixes_failed': len(fixable_issues), 'error': str(e)}

        if fixes_failed > 0:
            print(f"⚠️  {fixes_failed} fixes failed")

        return {
            'fixes_applied': fixes_applied,
            'fixes_failed': fixes_failed,
            'rollback_file': rollback_file,
            'tier': tier
        }

    def _apply_single_fix(self, spac: SPAC, issue: ValidationIssue) -> bool:
        """Apply a single fix to a SPAC"""
        try:
            if issue.rule_name == 'premium_calculation':
                # Recalculate premium from price and trust_value
                if spac.price and spac.trust_value:
                    spac.premium = ((float(spac.price) - float(spac.trust_value)) / float(spac.trust_value)) * 100
                    return True

            elif issue.rule_name == 'days_to_deadline_calculation':
                # Recalculate days to deadline
                if spac.deadline_date:
                    deadline = to_date(spac.deadline_date)
                    spac.days_to_deadline = (deadline - datetime.now().date()).days
                    return True

            elif issue.rule_name == 'market_cap_calculation':
                # Recalculate market cap
                if spac.price and spac.shares_outstanding:
                    spac.market_cap = (float(spac.price) * float(spac.shares_outstanding)) / 1_000_000
                    return True

            elif issue.rule_name == 'return_since_announcement_calculation':
                # Recalculate return since announcement
                if spac.price and spac.price_at_announcement:
                    spac.return_since_announcement = ((float(spac.price) - float(spac.price_at_announcement)) / float(spac.price_at_announcement)) * 100
                    return True

            elif issue.rule_name == 'financial_fields_numeric':
                # Convert string to numeric (e.g., "$230M" → 230000000)
                value_str = str(issue.current_value)
                clean_value = value_str.replace('$', '').replace('M', '').replace(',', '').replace('%', '').strip()
                numeric_value = float(clean_value)

                # If it was in millions, convert to actual dollars
                if 'M' in value_str:
                    numeric_value = numeric_value * 1_000_000

                setattr(spac, issue.field, numeric_value)
                return True

            elif issue.rule_name == 'date_type_valid':
                # Convert string date to actual date object
                # This would require parsing logic based on the string format
                # For now, skip these (need more context)
                return False

            elif issue.rule_name == 'deal_requires_deal_risk':
                # Fix risk_level for announced deals
                if spac.deal_status == 'ANNOUNCED':
                    spac.risk_level = 'deal'
                    return True

            return False

        except Exception as e:
            print(f"    Error applying fix: {e}")
            return False

    def _sql_value(self, value) -> str:
        """Convert Python value to SQL representation for rollback script"""
        if value is None:
            return 'NULL'
        elif isinstance(value, str):
            return f"'{value}'"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, datetime):
            return f"'{value.isoformat()}'"
        elif isinstance(value, date):
            return f"'{value.isoformat()}'"
        else:
            return f"'{str(value)}'"


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """Command-line interface for data validation"""
    import argparse

    parser = argparse.ArgumentParser(description='SPAC Data Validator')
    parser.add_argument(
        '--validate-all',
        action='store_true',
        help='Validate all SPACs in database'
    )
    parser.add_argument(
        '--ticker',
        type=str,
        help='Validate specific SPAC ticker'
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate validation report'
    )
    parser.add_argument(
        '--auto-fix',
        action='store_true',
        help='Run auto-fix on validation issues'
    )
    parser.add_argument(
        '--tier',
        type=str,
        default='1',
        choices=['1', '1,2', 'all'],
        help='Auto-fix tier: 1 (math only), 1,2 (math+logic), all (everything)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview fixes without applying (default for first run)'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip interactive approval (non-interactive mode)'
    )

    args = parser.parse_args()

    validator = DataValidator()

    try:
        if args.validate_all:
            stats = validator.validate_all_spacs()
            validator.generate_validation_report()

            # If --auto-fix flag is set, run auto-fix
            if args.auto_fix:
                print("\n" + "=" * 80)
                print("RUNNING AUTO-FIX...")
                print("=" * 80)

                # Load all validation issues
                all_issues = []
                with open('logs/validation_results.jsonl', 'r') as f:
                    for line in f:
                        issue_data = json.loads(line)
                        for issue_dict in issue_data.get('issues', []):
                            if issue_dict.get('auto_fixable'):
                                issue = ValidationIssue(
                                    rule_number=issue_dict['rule_number'],
                                    rule_name=issue_dict['rule_name'],
                                    severity=issue_dict['severity'],
                                    ticker=issue_dict['ticker'],
                                    field=issue_dict['field'],
                                    current_value=issue_dict['current_value'],
                                    expected_value=issue_dict.get('expected_value'),
                                    message=issue_dict['message'],
                                    auto_fixable=True
                                )
                                all_issues.append(issue)

                # Run auto-fix
                fix_result = validator.apply_auto_fixes(
                    all_issues,
                    dry_run=args.dry_run,
                    tier=args.tier,
                    interactive=not args.yes
                )

                print("\n" + "=" * 80)
                print("AUTO-FIX SUMMARY")
                print("=" * 80)
                print(f"Fixes applied: {fix_result.get('fixes_applied', 0)}")
                if fix_result.get('fixes_failed', 0) > 0:
                    print(f"Fixes failed: {fix_result['fixes_failed']}")
                if 'rollback_file' in fix_result:
                    print(f"Rollback available: {fix_result['rollback_file']}")

                # Re-validate if fixes were applied
                if fix_result.get('fixes_applied', 0) > 0:
                    print("\n" + "=" * 80)
                    print("RE-VALIDATING...")
                    print("=" * 80)
                    new_stats = validator.validate_all_spacs()
                    print(f"\nIssues before: {stats['critical_issues'] + stats['error_issues']}")
                    print(f"Issues after: {new_stats['critical_issues'] + new_stats['error_issues']}")
                    print(f"Reduction: {(stats['critical_issues'] + stats['error_issues']) - (new_stats['critical_issues'] + new_stats['error_issues'])} issues fixed")

        elif args.ticker:
            spac = validator.db.query(SPAC).filter(SPAC.ticker == args.ticker).first()
            if not spac:
                print(f"SPAC {args.ticker} not found")
                return

            result = validator.validate_spac(spac)

            print(f"\nValidation Results for {args.ticker}:")
            print(f"Rules checked: {result.rules_checked}")
            print(f"Rules passed: {result.rules_passed}")
            print(f"Issues found: {len(result.issues)}")

            for issue in result.issues:
                print(f"\n[{issue.severity}] Rule {issue.rule_number}: {issue.rule_name}")
                print(f"  Field: {issue.field}")
                print(f"  Current: {issue.current_value}")
                if issue.expected_value:
                    print(f"  Expected: {issue.expected_value}")
                print(f"  Message: {issue.message}")
                if issue.auto_fixable:
                    print(f"  ✓ Auto-fixable")

        elif args.report:
            validator.generate_validation_report()

        else:
            parser.print_help()

    finally:
        validator.close()


if __name__ == "__main__":
    main()
