#!/usr/bin/env python3
"""
Deal Data Validation Agent
Validates data consistency and completeness for announced SPAC deals
Similar to pre-IPO quality agent
"""

import sys
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC
from utils.target_validator import validate_target


class DealDataValidator:
    """Validates deal data quality and completeness"""

    def __init__(self):
        self.db = SessionLocal()
        self.issues = {
            'high': [],     # Critical issues
            'medium': [],   # Important but not blocking
            'low': []       # Minor issues / suggestions
        }

    def close(self):
        self.db.close()

    def validate_timeline_logic(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check that timeline makes logical sense"""
        issues = []

        # announced_date → latest_s4_date → proxy_filed_date → shareholder_vote_date → closing

        if spac.latest_s4_date and spac.announced_date:
            if spac.latest_s4_date < spac.announced_date:
                issues.append(('high', f"S-4 filed ({spac.latest_s4_date}) before announcement ({spac.announced_date})"))

        if spac.proxy_filed_date and spac.latest_s4_date:
            if spac.proxy_filed_date < spac.latest_s4_date:
                issues.append(('medium', f"Proxy filed ({spac.proxy_filed_date}) before S-4 ({spac.latest_s4_date})"))

        if spac.shareholder_vote_date and spac.proxy_filed_date:
            if spac.shareholder_vote_date < spac.proxy_filed_date:
                issues.append(('high', f"Vote date ({spac.shareholder_vote_date}) before proxy filed ({spac.proxy_filed_date})"))

        if spac.redemption_deadline and spac.shareholder_vote_date:
            if spac.redemption_deadline > spac.shareholder_vote_date:
                issues.append(('medium', f"Redemption deadline ({spac.redemption_deadline}) after vote date ({spac.shareholder_vote_date})"))

        return issues

    def validate_deal_value_consistency(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check for unusual changes in deal value"""
        issues = []

        # Deal value shouldn't change dramatically between filings
        # This would require tracking historical values - for now just check if present

        if not spac.deal_value:
            issues.append(('high', "Deal value missing"))

        return issues

    def validate_required_fields(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check that announced deals have required fields"""
        issues = []

        # Critical fields for announced deals
        required_critical = {
            'target': 'Target company name',
            'announced_date': 'Announcement date',
            'deal_value': 'Deal value'
        }

        for field, description in required_critical.items():
            if not getattr(spac, field):
                issues.append(('high', f"Missing {description}"))

        # Important fields (should have after certain milestones)
        if spac.announced_date:
            announced = spac.announced_date.date() if isinstance(spac.announced_date, datetime) else spac.announced_date
            days_since_announcement = (datetime.now().date() - announced).days

            # Should have S-4 within 90 days
            if days_since_announcement > 90 and not spac.latest_s4_date:
                issues.append(('medium', f"No S-4 filed {days_since_announcement} days after announcement (possible termination?)"))

            # Should have proxy within 120 days of S-4
            if spac.latest_s4_date:
                # Normalize date for comparison
                s4_date = spac.latest_s4_date.date() if isinstance(spac.latest_s4_date, datetime) else spac.latest_s4_date
                days_since_s4 = (datetime.now().date() - s4_date).days
                if days_since_s4 > 120 and not spac.proxy_filed_date:
                    issues.append(('medium', f"No proxy filed {days_since_s4} days after S-4"))

        # Nice-to-have fields
        if not spac.sector or spac.sector == 'General':
            issues.append(('low', "Sector not specified"))

        if not spac.sponsor:
            issues.append(('low', "Sponsor missing"))

        return issues

    def validate_pipe_min_cash_logic(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check PIPE + trust cash vs minimum cash requirement"""
        issues = []

        if spac.min_cash and spac.trust_cash and spac.shares_outstanding:
            # Calculate worst-case scenario (100% redemptions)
            pipe_contribution = spac.pipe_size if spac.pipe_size else 0

            # Minimum possible cash = PIPE only (if everyone redeems)
            min_possible_cash = pipe_contribution

            if min_possible_cash < spac.min_cash:
                shortfall = spac.min_cash - min_possible_cash
                issues.append(('high', f"PIPE (${pipe_contribution}M) insufficient to meet min cash (${spac.min_cash}M) if 100% redeem. Shortfall: ${shortfall:.0f}M"))

        return issues

    def validate_redemption_data(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check redemption data consistency"""
        issues = []

        # If vote happened, should have redemption data
        if spac.shareholder_vote_date:
            vote_date = spac.shareholder_vote_date if isinstance(spac.shareholder_vote_date, datetime) else spac.shareholder_vote_date
            # Normalize to date for comparison
            vote_date_normalized = vote_date.date() if isinstance(vote_date, datetime) else vote_date
            days_since_vote = (datetime.now().date() - vote_date_normalized).days if vote_date_normalized else None

            if days_since_vote and days_since_vote > 7 and not spac.shares_redeemed:
                issues.append(('medium', f"Vote was {days_since_vote} days ago but no redemption data"))

        # Redemption percentage should match shares redeemed
        if spac.shares_redeemed and spac.shares_outstanding and spac.redemption_percentage:
            # Calculate expected percentage
            original_shares = spac.shares_outstanding + spac.shares_redeemed
            calculated_pct = (spac.shares_redeemed / original_shares) * 100

            # Allow 1% margin of error
            if abs(calculated_pct - spac.redemption_percentage) > 1.0:
                issues.append(('low', f"Redemption % mismatch: reported {spac.redemption_percentage}%, calculated {calculated_pct:.1f}%"))

        return issues

    def validate_target_name(self, spac: SPAC) -> List[Tuple[str, str]]:
        """Check that target name is valid (not sponsor/trustee entity)"""
        issues = []

        if spac.target:
            is_valid, reason = validate_target(spac.target, spac.ticker)

            if not is_valid:
                issues.append(('high', f"Invalid target name: '{spac.target}' - {reason}"))

        return issues

    def validate_spac(self, spac: SPAC) -> Dict:
        """Run all validations on a single SPAC"""
        all_issues = []

        all_issues.extend(self.validate_target_name(spac))  # Check target validity first
        all_issues.extend(self.validate_timeline_logic(spac))
        all_issues.extend(self.validate_deal_value_consistency(spac))
        all_issues.extend(self.validate_required_fields(spac))
        all_issues.extend(self.validate_pipe_min_cash_logic(spac))
        all_issues.extend(self.validate_redemption_data(spac))

        # Categorize issues
        categorized = {
            'high': [msg for severity, msg in all_issues if severity == 'high'],
            'medium': [msg for severity, msg in all_issues if severity == 'medium'],
            'low': [msg for severity, msg in all_issues if severity == 'low']
        }

        return categorized

    def validate_all_deals(self) -> Dict:
        """Validate all announced deals"""

        print("="*70)
        print("DEAL DATA VALIDATION REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70 + "\n")

        # Get all announced deals
        announced_spacs = self.db.query(SPAC).filter(
            SPAC.deal_status == 'ANNOUNCED'
        ).all()

        print(f"Validating {len(announced_spacs)} announced deals...\n")

        results = {}

        for spac in announced_spacs:
            issues = self.validate_spac(spac)

            # Only store if has issues
            if any(issues.values()):
                results[spac.ticker] = {
                    'company': spac.company,
                    'target': spac.target or 'Unknown',
                    'issues': issues
                }

        # Print report
        self._print_validation_report(results)

        self.close()
        return results

    def _print_validation_report(self, results: Dict):
        """Print formatted validation report"""

        # Count issues by severity
        high_count = sum(len(r['issues']['high']) for r in results.values())
        medium_count = sum(len(r['issues']['medium']) for r in results.values())
        low_count = sum(len(r['issues']['low']) for r in results.values())

        # HIGH PRIORITY
        if high_count > 0:
            print(f"🔴 HIGH PRIORITY ({high_count} issues):")
            print("-" * 70)
            for ticker, data in results.items():
                if data['issues']['high']:
                    print(f"\n{ticker} ({data['target']})")
                    for issue in data['issues']['high']:
                        print(f"  ⚠️  {issue}")

        # MEDIUM PRIORITY
        if medium_count > 0:
            print(f"\n🟡 MEDIUM PRIORITY ({medium_count} issues):")
            print("-" * 70)
            for ticker, data in results.items():
                if data['issues']['medium']:
                    print(f"\n{ticker} ({data['target']})")
                    for issue in data['issues']['medium']:
                        print(f"  ⚠️  {issue}")

        # LOW PRIORITY
        if low_count > 0:
            print(f"\n🟢 LOW PRIORITY ({low_count} issues):")
            print("-" * 70)
            for ticker, data in results.items():
                if data['issues']['low']:
                    print(f"\n{ticker} ({data['target']})")
                    for issue in data['issues']['low']:
                        print(f"  ℹ️  {issue}")

        # Summary
        print(f"\n" + "="*70)
        if high_count + medium_count + low_count == 0:
            print("✅ All deals validated successfully - no issues found!")
        else:
            print(f"SUMMARY:")
            print(f"  🔴 High Priority: {high_count}")
            print(f"  🟡 Medium Priority: {medium_count}")
            print(f"  🟢 Low Priority: {low_count}")
            print(f"  Total SPACs with issues: {len(results)}/{self.db.query(SPAC).filter(SPAC.deal_status == 'ANNOUNCED').count()}")
        print("="*70)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Validate deal data quality')
    parser.add_argument('--ticker', type=str, help='Validate specific ticker only')
    parser.add_argument('--report', action='store_true', help='Generate validation report')
    args = parser.parse_args()

    validator = DealDataValidator()

    if args.ticker:
        # Single SPAC
        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == args.ticker).first()
        if not spac:
            print(f"SPAC {args.ticker} not found")
            db.close()
            return

        print(f"Validating {spac.ticker} ({spac.target or 'Unknown'})...\n")

        issues = validator.validate_spac(spac)

        if any(issues.values()):
            if issues['high']:
                print("🔴 HIGH PRIORITY:")
                for issue in issues['high']:
                    print(f"  ⚠️  {issue}")

            if issues['medium']:
                print("\n🟡 MEDIUM PRIORITY:")
                for issue in issues['medium']:
                    print(f"  ⚠️  {issue}")

            if issues['low']:
                print("\n🟢 LOW PRIORITY:")
                for issue in issues['low']:
                    print(f"  ℹ️  {issue}")
        else:
            print("✅ No issues found")

        validator.close()
        db.close()
    else:
        # All deals
        validator.validate_all_deals()


if __name__ == "__main__":
    main()
