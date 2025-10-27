#!/usr/bin/env python3
"""
SPAC Data Validation Rules Engine

Business logic validation rules:
1. Market cap vs IPO proceeds sanity check
2. IPO to deadline timeframe validation (should be 18-24 months)
3. Ticker relationships (common → unit/warrant/rights)
4. Trust value validation
5. Deal status consistency
"""

import sys
import re
import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC

# Try to import AI
try:
    from openai import OpenAI
    import os
    from dotenv import load_dotenv
    load_dotenv()
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
except:
    AI_AVAILABLE = False


class ValidationRule:
    """Base class for validation rules"""
    def __init__(self, name: str, severity: str):
        self.name = name
        self.severity = severity  # 'critical', 'warning', 'info'

    def validate(self, spac: SPAC) -> Optional[Dict]:
        """Return issue dict if validation fails, None if passes"""
        raise NotImplementedError


class MarketCapVsIPOProceedsRule(ValidationRule):
    """Rule: Market cap shouldn't be significantly less than IPO proceeds"""

    def __init__(self):
        super().__init__("Market Cap vs IPO Proceeds", "warning")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        if not spac.market_cap or not spac.ipo_proceeds:
            return None

        # Parse IPO proceeds (handle $XM format)
        proceeds_str = spac.ipo_proceeds.replace('$', '').replace('M', '').replace(',', '')
        try:
            proceeds_millions = float(proceeds_str)
        except:
            return None

        # Market cap is already in millions
        market_cap = spac.market_cap

        # If market cap is less than 50% of IPO proceeds, flag it
        if market_cap < (proceeds_millions * 0.5):
            return {
                'rule': self.name,
                'severity': self.severity,
                'ticker': spac.ticker,
                'issue': f'Market cap (${market_cap:.0f}M) is significantly lower than IPO proceeds (${proceeds_millions:.0f}M)',
                'action': 'Verify both market cap and IPO proceeds accuracy',
                'current_values': {
                    'market_cap': f'${market_cap:.0f}M',
                    'ipo_proceeds': spac.ipo_proceeds
                }
            }

        return None


class IPOToDeadlineTimeframeRule(ValidationRule):
    """Rule: IPO to deadline should be 18-24 months, not <12 months"""

    def __init__(self):
        super().__init__("IPO to Deadline Timeframe", "critical")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        if not spac.ipo_date or not spac.deadline_date:
            return None

        # Calculate months between IPO and deadline
        ipo_date = spac.ipo_date.date() if isinstance(spac.ipo_date, datetime) else spac.ipo_date
        deadline_date = spac.deadline_date.date() if isinstance(spac.deadline_date, datetime) else spac.deadline_date

        delta = relativedelta(deadline_date, ipo_date)
        months = delta.years * 12 + delta.months

        # Flag if less than 12 months or more than 30 months
        if months < 12:
            return {
                'rule': self.name,
                'severity': self.severity,
                'ticker': spac.ticker,
                'issue': f'Only {months} months between IPO ({ipo_date}) and deadline ({deadline_date})',
                'action': 'Verify deadline date from latest 10-Q/10-K or charter amendment',
                'current_values': {
                    'ipo_date': str(ipo_date),
                    'deadline_date': str(deadline_date),
                    'months': months
                }
            }
        elif months > 30:
            return {
                'rule': self.name,
                'severity': 'warning',
                'ticker': spac.ticker,
                'issue': f'{months} months between IPO and deadline (unusually long)',
                'action': 'Verify if deadline has been extended',
                'current_values': {
                    'ipo_date': str(ipo_date),
                    'deadline_date': str(deadline_date),
                    'months': months
                }
            }

        return None


class TickerRelationshipRule(ValidationRule):
    """Rule: Common ticker should have unit ticker, possibly warrant/rights"""

    def __init__(self):
        super().__init__("Ticker Relationships", "info")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        if not spac.ticker:
            return None

        missing = []

        # Should have unit ticker
        if not spac.unit_ticker:
            missing.append('unit ticker')

        # Many SPACs have warrants or rights (not all, so just info level)
        if not spac.warrant_ticker and not spac.right_ticker:
            missing.append('warrant/rights ticker')

        if missing:
            return {
                'rule': self.name,
                'severity': self.severity,
                'ticker': spac.ticker,
                'issue': f'Missing: {", ".join(missing)}',
                'action': 'Check SEC filings for unit structure and warrant/rights tickers',
                'current_values': {
                    'ticker': spac.ticker,
                    'unit_ticker': spac.unit_ticker or 'MISSING',
                    'warrant_ticker': spac.warrant_ticker or 'None',
                    'right_ticker': spac.right_ticker or 'None'
                }
            }

        return None


class TrustValueRule(ValidationRule):
    """Rule: Trust value should be ~$10.00 (some variation allowed)"""

    def __init__(self):
        super().__init__("Trust Value Validation", "warning")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        if not spac.trust_value:
            return None

        # Most SPACs have $10.00 trust value, some have $10.10 or $9.95
        if spac.trust_value < 9.50 or spac.trust_value > 10.50:
            return {
                'rule': self.name,
                'severity': self.severity,
                'ticker': spac.ticker,
                'issue': f'Trust value ${spac.trust_value:.2f} is unusual (expected ~$10.00)',
                'action': 'Verify trust value from latest 10-Q/10-K',
                'current_values': {
                    'trust_value': f'${spac.trust_value:.2f}'
                }
            }

        return None


class DealStatusConsistencyRule(ValidationRule):
    """Rule: Deal status should be consistent with target/dates"""

    def __init__(self):
        super().__init__("Deal Status Consistency", "warning")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        # If has target but status is SEARCHING
        if spac.target and spac.target != '-' and spac.deal_status == 'SEARCHING':
            return {
                'rule': self.name,
                'severity': self.severity,
                'ticker': spac.ticker,
                'issue': f'Has target ({spac.target}) but status is SEARCHING',
                'action': 'Update deal_status to ANNOUNCED',
                'current_values': {
                    'target': spac.target,
                    'deal_status': spac.deal_status,
                    'announced_date': str(spac.announced_date) if spac.announced_date else 'None'
                }
            }

        # If status is ANNOUNCED but no target
        if spac.deal_status == 'ANNOUNCED' and (not spac.target or spac.target == '-'):
            return {
                'rule': self.name,
                'severity': 'critical',
                'ticker': spac.ticker,
                'issue': 'Status is ANNOUNCED but no target company listed',
                'action': 'Find target from latest 8-K or update status to SEARCHING',
                'current_values': {
                    'target': spac.target or 'MISSING',
                    'deal_status': spac.deal_status
                }
            }

        return None


class ValidationRulesEngine:
    """Main validation rules engine"""

    def __init__(self):
        self.db = SessionLocal()
        self.base_url = "https://www.sec.gov"
        self.headers = {'User-Agent': 'Legacy EVP Spac Platform fenil@legacyevp.com'}

        # Register all rules
        self.rules = [
            MarketCapVsIPOProceedsRule(),
            IPOToDeadlineTimeframeRule(),
            TickerRelationshipRule(),
            TrustValueRule(),
            DealStatusConsistencyRule()
        ]

    def close(self):
        self.db.close()

    def run_all_validations(self) -> Dict[str, List]:
        """Run all validation rules on all SPACs"""
        issues = {
            'critical': [],
            'warning': [],
            'info': []
        }

        spacs = self.db.query(SPAC).all()

        for spac in spacs:
            for rule in self.rules:
                issue = rule.validate(spac)
                if issue:
                    issues[issue['severity']].append(issue)

        return issues

    def print_report(self, issues: Dict[str, List]):
        """Print validation report"""
        print("=" * 70)
        print("SPAC BUSINESS LOGIC VALIDATION REPORT")
        print("=" * 70)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        total_issues = sum(len(v) for v in issues.values())

        if total_issues == 0:
            print("✅ NO ISSUES FOUND - All business logic rules passed!")
            return

        print(f"⚠️  TOTAL ISSUES: {total_issues}\n")

        # Critical issues
        if issues['critical']:
            print(f"🔴 CRITICAL ISSUES: {len(issues['critical'])}")
            print("-" * 70)
            for issue in issues['critical']:
                print(f"\n[{issue['ticker']}] {issue['rule']}")
                print(f"  Issue: {issue['issue']}")
                print(f"  Action: {issue['action']}")
                if 'current_values' in issue:
                    print(f"  Current: {issue['current_values']}")
            print()

        # Warnings
        if issues['warning']:
            print(f"🟡 WARNINGS: {len(issues['warning'])}")
            print("-" * 70)
            for issue in issues['warning'][:10]:  # Show first 10
                print(f"\n[{issue['ticker']}] {issue['rule']}")
                print(f"  Issue: {issue['issue']}")
                print(f"  Action: {issue['action']}")
            if len(issues['warning']) > 10:
                print(f"\n  ... and {len(issues['warning']) - 10} more warnings")
            print()

        # Info
        if issues['info']:
            print(f"ℹ️  INFO: {len(issues['info'])}")
            print(f"  {len(issues['info'])} items need attention (low priority)")
            print()

    # ========================================================================
    # AUTO-FIX FUNCTIONS
    # ========================================================================

    def fix_deadline_from_10q(self, spac: SPAC) -> Optional[str]:
        """Extract deadline from 10-Q/10-K using AI if available"""
        if not spac.cik or not AI_AVAILABLE:
            return None

        try:
            # Get latest 10-Q/10-K
            filing_text = self._get_10q_text(spac.cik)
            if not filing_text:
                return None

            # Use AI to extract deadline
            prompt = f"""Extract the business combination deadline date from this 10-Q/10-K excerpt:

{filing_text[:6000]}

Look for phrases like:
- "business combination by [DATE]"
- "deadline to complete an initial business combination is [DATE]"
- "must complete a business combination by [DATE]"
- "liquidate if not completed by [DATE]"

Return ONLY the date in format: YYYY-MM-DD
If not found, return: NOT_FOUND"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100
            )

            result = response.choices[0].message.content.strip()

            # Parse date
            if result != "NOT_FOUND" and re.match(r'\d{4}-\d{2}-\d{2}', result):
                return result

            return None

        except Exception as e:
            print(f"  AI extraction error: {e}")
            return None

    def _get_10q_text(self, cik: str) -> Optional[str]:
        """Get text from latest 10-Q or 10-K"""
        try:
            for filing_type in ['10-Q', '10-K']:
                url = f"{self.base_url}/cgi-bin/browse-edgar"
                response = requests.get(url, params={
                    'action': 'getcompany',
                    'CIK': cik.zfill(10),
                    'type': filing_type,
                    'count': 1
                }, headers=self.headers, timeout=30)

                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', {'class': 'tableFile2'})

                if table and len(table.find_all('tr')) > 1:
                    row = table.find_all('tr')[1]
                    doc_link = row.find('a', {'id': 'documentsbutton'})

                    if doc_link:
                        # Get filing documents page
                        filing_page_url = self.base_url + doc_link['href']
                        page_response = requests.get(filing_page_url, headers=self.headers, timeout=30)
                        page_soup = BeautifulSoup(page_response.text, 'html.parser')

                        # Find main document
                        doc_table = page_soup.find('table', {'class': 'tableFile'})
                        if doc_table:
                            for tr in doc_table.find_all('tr'):
                                tds = tr.find_all('td')
                                if len(tds) >= 3:
                                    link = tds[2].find('a', href=True)
                                    if link and '.htm' in link['href']:
                                        doc_url = self.base_url + link['href']
                                        doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
                                        doc_soup = BeautifulSoup(doc_response.text, 'html.parser')
                                        return doc_soup.get_text()

            return None
        except:
            return None

    def auto_fix_issues(self, issues: Dict[str, List], dry_run=True):
        """Attempt to auto-fix issues"""
        print(f"\n{'=' * 70}")
        print("AUTO-FIX ATTEMPT")
        print(f"{'=' * 70}\n")

        fixed = 0

        # Fix deadline timeframe issues
        deadline_issues = [i for i in issues['critical'] + issues['warning']
                          if 'Deadline' in i['rule'] and 'months' in i.get('current_values', {})]

        if deadline_issues:
            print(f"Attempting to fix {len(deadline_issues)} deadline issues...\n")

            for issue in deadline_issues:
                spac = self.db.query(SPAC).filter(SPAC.ticker == issue['ticker']).first()
                if not spac:
                    continue

                print(f"[{spac.ticker}] Checking latest 10-Q/10-K for deadline...")

                new_deadline = self.fix_deadline_from_10q(spac)

                if new_deadline:
                    old_deadline = spac.deadline_date
                    spac.deadline_date = datetime.strptime(new_deadline, '%Y-%m-%d')
                    print(f"  ✓ Found deadline: {new_deadline}")
                    print(f"    Old: {old_deadline.date() if old_deadline else 'None'}")
                    print(f"    New: {new_deadline}")
                    fixed += 1
                else:
                    print(f"  ✗ Could not extract deadline from 10-Q/10-K")

        # Fix deal status inconsistencies
        deal_issues = [i for i in issues['warning'] + issues['critical']
                      if 'Deal Status' in i['rule']]

        if deal_issues:
            print(f"\nFound {len(deal_issues)} deal status inconsistencies (requires manual review)")

        print(f"\n{'=' * 70}")
        if dry_run:
            print(f"DRY RUN: Would fix {fixed} issues")
            print("Run with --commit to apply changes")
        else:
            if fixed > 0:
                self.db.commit()
            print(f"✅ FIXED {fixed} ISSUES")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='SPAC Business Logic Validation')
    parser.add_argument('--commit', action='store_true', help='Commit fixes to database')
    parser.add_argument('--report-only', action='store_true', help='Only show report')
    parser.add_argument('--auto-fix', action='store_true', help='Attempt auto-fixes')
    args = parser.parse_args()

    engine = ValidationRulesEngine()

    try:
        issues = engine.run_all_validations()
        engine.print_report(issues)

        if args.auto_fix and not args.report_only:
            engine.auto_fix_issues(issues, dry_run=not args.commit)

    finally:
        engine.close()


if __name__ == "__main__":
    main()
