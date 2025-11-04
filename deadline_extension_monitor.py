#!/usr/bin/env python3
"""
Deadline Extension Monitor - Tracks shareholder votes and 8-K filings to update deadlines
Runs daily to catch monthly extensions and charter amendments
"""

import re
import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import sys

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC
from utils.sec_filing_fetcher import SECFilingFetcher

class DeadlineExtensionMonitor:

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {'User-Agent': 'Legacy EVP Spac Platform fenil@legacyevp.com'}
        self.db = SessionLocal()
        self.sec_fetcher = SECFilingFetcher()

    def close(self):
        self.db.close()

    def check_for_extensions(self, cik: str, current_deadline: datetime = None) -> Dict:
        """Check recent 8-Ks and DEF 14As for deadline extensions"""

        extensions = []

        # Check multiple filing types
        for filing_type in ['8-K', 'DEF 14A', 'DEFA14A']:
            try:
                response = requests.get(
                    f"{self.base_url}/cgi-bin/browse-edgar",
                    params={
                        'action': 'getcompany',
                        'CIK': cik.zfill(10),
                        'type': filing_type,
                        'count': 15,  # Check last 15 filings
                        'dateb': ''
                    },
                    headers=self.headers,
                    timeout=30
                )

                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', {'class': 'tableFile2'})

                if not table:
                    continue

                # Only check filings from last 12 months
                cutoff = datetime.now() - timedelta(days=365)

                for row in table.find_all('tr')[1:16]:  # Check up to 15 filings
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        filing_date_str = cols[3].text.strip()
                        filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d')

                        if filing_date < cutoff:
                            continue

                        # Get filing text
                        doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                        if doc_link:
                            filing_url = self.base_url + doc_link['href']
                            filing_text = self._get_filing_text(filing_url)

                            if filing_text and self._is_extension_filing(filing_text):
                                extension_date = self._extract_extension_date(filing_text)
                                if extension_date:
                                    extensions.append({
                                        'filing_date': filing_date_str,
                                        'filing_type': filing_type,
                                        'new_deadline': extension_date,
                                        'filing_url': filing_url
                                    })

                time.sleep(0.3)  # Rate limiting

            except Exception as e:
                print(f"   Error checking {filing_type}: {e}")
                continue

        # Sort by filing date (newest first) and return latest
        if extensions:
            extensions.sort(key=lambda x: x['filing_date'], reverse=True)

        return {
            'has_extensions': len(extensions) > 0,
            'extensions': extensions,
            'latest_deadline': extensions[0]['new_deadline'] if extensions else None,
            'extension_count': len(extensions)
        }

    def _get_filing_text(self, filing_url: str) -> Optional[str]:
        """Get text content from SEC filing using centralized fetcher"""
        try:
            # Use the centralized SEC fetcher to extract the actual document URL
            # This handles index pages and inline XBRL viewer formats
            doc_url = self.sec_fetcher.extract_document_url(filing_url)
            if not doc_url:
                return None

            # Fetch the actual document content
            html_content = self.sec_fetcher.fetch_document(doc_url)
            if not html_content:
                return None

            # Parse HTML and extract text
            soup = BeautifulSoup(html_content, 'html.parser')
            return soup.get_text()

        except Exception as e:
            return None

    def _is_extension_filing(self, text: str) -> bool:
        """Check if filing is about deadline extension"""
        text_lower = text.lower()

        extension_keywords = [
            'extension of deadline',
            'extend the deadline',
            'amendment to extend',
            'extension of the termination date',
            'extend the time',
            'extension of business combination',
            'monthly extension',
            'deposit.*trust account.*extension',
            'stockholder approval.*extension',
            'amendment.*extend.*deadline',
            'approved.*extension',
            'vote.*extension',
            'amend.*termination date'
        ]

        return any(re.search(keyword, text_lower) for keyword in extension_keywords)

    def _extract_extension_date(self, text: str) -> Optional[str]:
        """Extract new deadline date from extension filing"""

        # Pattern 1: "extended to [DATE]"
        patterns = [
            r'extended to ([A-Z][a-z]+ \d{1,2}, \d{4})',
            r'extension.*to ([A-Z][a-z]+ \d{1,2}, \d{4})',
            r'deadline of ([A-Z][a-z]+ \d{1,2}, \d{4})',
            r'termination date.*([A-Z][a-z]+ \d{1,2}, \d{4})',
            r'extended.*until ([A-Z][a-z]+ \d{1,2}, \d{4})',
            r'deadline.*([A-Z][a-z]+ \d{1,2}, \d{4})',
            # Numeric dates
            r'extended to (\d{1,2}/\d{1,2}/\d{4})',
            r'deadline.*(\d{1,2}/\d{1,2}/\d{4})'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                try:
                    # Try Month Day, Year format
                    return datetime.strptime(date_str, '%B %d, %Y').strftime('%Y-%m-%d')
                except:
                    try:
                        # Try M/D/Y format
                        return datetime.strptime(date_str, '%m/%d/%Y').strftime('%Y-%m-%d')
                    except:
                        continue

        return None

    def update_all_deadlines(self, commit=False):
        """Check all active SPACs for deadline extensions"""

        spacs = self.db.query(SPAC).filter(
            SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
        ).all()

        print(f"Checking {len(spacs)} active SPACs for deadline extensions...")
        print("=" * 70)

        updated = 0
        checked = 0

        for spac in spacs:
            if not spac.cik:
                continue

            checked += 1
            if checked % 20 == 0:
                print(f"Progress: {checked}/{len(spacs)}")

            result = self.check_for_extensions(spac.cik, spac.deadline_date)

            if result['latest_deadline']:
                new_deadline = datetime.strptime(result['latest_deadline'], '%Y-%m-%d').date()
                current_deadline = spac.deadline_date.date() if hasattr(spac.deadline_date, 'date') else spac.deadline_date

                if current_deadline != new_deadline:
                    print(f"\n{spac.ticker}: Deadline extension found")
                    print(f"  Current:  {current_deadline}")
                    print(f"  New:      {new_deadline}")
                    print(f"  Source:   {result['extensions'][0]['filing_type']} on {result['extensions'][0]['filing_date']}")

                    if commit:
                        spac.deadline_date = datetime.combine(new_deadline, datetime.min.time())
                        updated += 1

        print(f"\n{'=' * 70}")
        if commit and updated > 0:
            self.db.commit()
            print(f"✅ Updated {updated} deadlines")
        elif updated > 0:
            print(f"DRY RUN: Would update {updated} deadlines (use --commit to save)")
        else:
            print(f"✅ No deadline changes found (all {checked} SPACs up to date)")

        self.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Monitor SPAC deadline extensions')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database')
    parser.add_argument('--ticker', type=str, help='Check specific SPAC ticker')
    args = parser.parse_args()

    monitor = DeadlineExtensionMonitor()

    if args.ticker:
        # Check single SPAC
        spac = monitor.db.query(SPAC).filter(SPAC.ticker == args.ticker).first()
        if not spac:
            print(f"SPAC {args.ticker} not found")
            return

        if not spac.cik:
            print(f"No CIK for {args.ticker}")
            return

        print(f"Checking deadline extensions for {spac.ticker}...")
        print(f"Current deadline: {spac.deadline_date}")

        result = monitor.check_for_extensions(spac.cik, spac.deadline_date)

        if result['has_extensions']:
            print(f"\nFound {result['extension_count']} extension(s):")
            for ext in result['extensions']:
                print(f"  - {ext['filing_date']}: Extended to {ext['new_deadline']} ({ext['filing_type']})")

            if result['latest_deadline']:
                print(f"\nLatest deadline: {result['latest_deadline']}")
        else:
            print("No extensions found")

        monitor.close()
    else:
        # Check all SPACs
        monitor.update_all_deadlines(commit=args.commit)


if __name__ == "__main__":
    main()
