#!/usr/bin/env python3
"""
Pre-IPO SPAC Finder
Searches SEC EDGAR for new S-1 filings with SIC code 6770 (Blank Checks/SPACs)
"""

import os
import re
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from pre_ipo_database import SessionLocal, PreIPOSPAC
from database import SessionLocal as MainSessionLocal, SPAC

# Import AI for S-1 parsing
try:
    from openai import OpenAI
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


class PreIPOSPACFinder:
    """Finds and tracks pre-IPO SPACs from SEC filings"""

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {
            'User-Agent': 'Legacy EVP Spac Platform fenil@legacyevp.com'
        }
        self.db = SessionLocal()  # Pre-IPO database
        self.main_db = MainSessionLocal()  # Main SPAC database (for checking already IPO'd)

    def search_recent_s1_filings(self, days_back: int = 7) -> List[Dict]:
        """
        Search SEC EDGAR for S-1 filings using daily index files
        Filters for SPAC keywords in company names

        Args:
            days_back: How many days to look back for filings (default: 7)

        Returns:
            List of filing metadata dicts
        """
        print(f"\n🔍 Searching for S-1 filings (last {days_back} days)...")
        print(f"   Strategy: SEC daily index + SPAC keyword filter\n")

        filings = []
        cutoff_date = datetime.now() - timedelta(days=days_back)

        requests_attempted = 0
        requests_successful = 0

        # Check each day's index
        for days_ago in range(days_back):
            requests_attempted += 1
            check_date = datetime.now() - timedelta(days=days_ago)

            # SEC daily index format: /Archives/edgar/daily-index/2025/QTR4/master.20251007.idx
            year = check_date.year
            quarter = f"QTR{(check_date.month-1)//3 + 1}"
            date_str = check_date.strftime('%Y%m%d')

            index_url = f"{self.base_url}/Archives/edgar/daily-index/{year}/{quarter}/master.{date_str}.idx"

            try:
                response = requests.get(index_url, headers=self.headers, timeout=10)

                if response.status_code != 200:
                    if days_ago % 5 == 0:  # Debug: show some failures
                        print(f"   [{date_str}: {response.status_code}]", end='')
                    continue

                requests_successful += 1

                # Parse the index file (pipe-delimited)
                lines = response.text.split('\n')

                s1_count = 0
                matched_count = 0
                total_lines = len(lines) - 11  # Subtract header

                if days_ago == 1:  # Debug Oct 6
                    print(f"\n   [DEBUG {date_str}: {total_lines} data lines]")
                    # Count S-1s
                    s1_test = sum(1 for l in lines if '|S-1|' in l or '|S-1/A|' in l)
                    print(f"   [DEBUG: {s1_test} lines contain 'S-1' or 'S-1/A']")

                # Skip header lines (first ~11 lines)
                for line in lines[11:]:
                    if not line.strip():
                        continue

                    parts = line.split('|')
                    if len(parts) >= 5:
                        cik = parts[0].strip()
                        company_name = parts[1].strip()
                        form_type = parts[2].strip()
                        filing_date_str = parts[3].strip()
                        filing_path = parts[4].strip()

                        # Only S-1 and S-1/A forms
                        if form_type not in ['S-1', 'S-1/A']:
                            if days_ago == 1 and s1_count < 3:  # Debug first few misses
                                pass  # print(f"   [Skip: {form_type}]")
                            continue

                        s1_count += 1

                        if days_ago == 1:  # Debug all S-1s on Oct 6
                            print(f"   [S-1 #{s1_count}: {company_name[:60]}]")

                        # Filter for SPAC keywords in company name
                        company_lower = company_name.lower()
                        spac_keywords = [
                            'acquisition',  # Broader match - most SPACs have "acquisition" in name
                            'spac',
                            'special purpose',
                            'blank check'
                        ]

                        is_spac = any(keyword in company_lower for keyword in spac_keywords)

                        # Additional filter: must have "corp" or "company" to avoid false positives
                        if is_spac and 'acquisition' in company_lower:
                            is_spac = 'corp' in company_lower or 'company' in company_lower or 'ltd' in company_lower

                        if days_ago == 1 and 'iron horse' in company_lower:  # Debug Iron Horse specifically
                            print(f"   [DEBUG Iron Horse: has_acq={('acquisition' in company_lower)}, has_corp={('corp' in company_lower)}, is_spac={is_spac}]")

                        if not is_spac:
                            continue

                        matched_count += 1

                        try:
                            # Build direct documents URL from accession number
                            # filing_path format: edgar/data/1234567/0001234567-25-000001.txt
                            # Convert to archive path: /Archives/edgar/data/1234567/0001234567-25-000001/
                            acc_no = filing_path.split('/')[-1].replace('.txt', '')
                            acc_no_no_dashes = acc_no.replace('-', '')  # Remove dashes for directory path

                            # Use direct archive path instead of viewer (viewer doesn't work for non-XBRL)
                            # Format: /Archives/edgar/data/CIK/ACCESSION-NO-DASHES/
                            filing_url = f"{self.base_url}/Archives/{filing_path.replace('.txt', '').replace(acc_no, acc_no_no_dashes)}/"

                            filings.append({
                                'company': company_name,
                                'cik': cik.zfill(10),
                                'filing_type': form_type,
                                'filing_date': datetime.strptime(filing_date_str, '%Y%m%d').date(),  # Fixed: YYYYMMDD format
                                'filing_url': filing_url,
                                'accession_no': acc_no
                            })

                            print(f"   ✓ {check_date.strftime('%Y-%m-%d')}: {company_name[:60]}")
                        except Exception as append_err:
                            print(f"   ✗ Error appending {company_name[:40]}: {append_err}")

                if days_ago % 5 == 0 and s1_count > 0:  # Debug output every 5 days
                    print(f"   [{date_str}: {s1_count} S-1s, {matched_count} matched]")

                time.sleep(0.15)  # Rate limiting

            except Exception as e:
                # Daily index may not exist for today/weekends
                if days_ago < 3:  # Only show error for very recent dates
                    pass  # print(f"   ⚠️  {date_str}: {str(e)[:50]}")
                continue

        print(f"\n   📊 Requests: {requests_attempted} attempted, {requests_successful} successful")
        print(f"   📊 Total S-1 filings found: {len(filings)}\n")

        return filings

    def get_s1_document_url(self, filing_url: str) -> Optional[str]:
        """Extract the actual S-1 document URL from filing archive directory

        Checks both main documents and exhibits (S-1s often in exhibits for amendments)
        """
        try:
            response = requests.get(filing_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Check if this is a directory listing (archive path) or document page
            is_directory = '<table' in response.text and '.htm' in response.text

            if not is_directory:
                # Try the old viewer approach
                table = soup.find('table', {'class': 'tableFile'})
                if not table:
                    table = soup.find('table', {'summary': 'Document Format Files'})
            else:
                # This is a directory listing - find any table
                table = soup.find('table')

            if not table:
                return None

            # Strategy: Look for S-1 in this priority order:
            # 1. Main S-1 document (non-exhibit)
            # 2. S-1 in exhibits (common for amendments)
            # 3. 424B4 prospectus (has similar info)
            # 4. Any .htm file (likely the main document)

            candidates = []  # Store (priority, url, filename) tuples

            for row in table.find_all('tr')[1:]:
                # Handle both directory listing and document table formats
                cells = row.find_all('td')

                # Find the link - could be in various cells
                link = row.find('a', href=True)
                if not link or '.htm' not in link['href']:
                    continue

                href = link['href']
                filename = link.get_text().strip().lower()

                # Skip parent directory link
                if filename == 'parent directory' or href == '../':
                    continue

                # Build full URL
                if href.startswith('http'):
                    doc_url = href
                elif filing_url.endswith('/'):
                    doc_url = filing_url + href
                else:
                    doc_url = filing_url + '/' + href

                # Get document type from filename or cell text
                doc_type = ''
                if len(cells) >= 4:
                    doc_type = cells[3].get_text().strip().lower()

                # Priority 1: Main S-1 document (not exhibit, not xml)
                # Look for s1.htm, s-1.htm, or similar
                if ('.htm' in filename and
                    ('s1' in filename or 's-1' in filename) and
                    'ex' not in filename and
                    '.xml' not in filename):
                    candidates.append((1, doc_url, filename))

                # Priority 2: S-1 in exhibits (user said "sometimes the S-1s are in exhibits")
                elif ('s-1' in filename or 's1' in filename) and 'ex' in filename:
                    candidates.append((2, doc_url, filename))

                # Priority 3: 424B4 prospectus (has similar info)
                elif '424b' in filename:
                    candidates.append((3, doc_url, filename))

                # Priority 4: Any .htm file (not xml, not graphic)
                elif ('.htm' in filename and
                      '.xml' not in filename and
                      'graphic' not in filename and
                      'img' not in filename):
                    candidates.append((4, doc_url, filename))

            # Return highest priority match
            if candidates:
                candidates.sort(key=lambda x: x[0])  # Sort by priority (1 is best)
                return candidates[0][1]

            return None

        except Exception as e:
            print(f"   ⚠️  Error getting S-1 URL: {e}")
            return None

    def parse_s1_with_ai(self, s1_url: str, company: str) -> Dict:
        """Use AI to extract CORE fields from S-1 (Phase 1: 8 critical fields)

        Phase 1 Strategy: Get minimal viable data with ~60% accuracy
        - expected_ticker, target_proceeds, units_offered
        - sponsor, lead_banker
        - charter_deadline_months, target_sector

        Phase 2 (later): Enhanced extraction with more fields
        """
        if not AI_AVAILABLE:
            print("   ⚠️  AI not available - will save basic metadata only")
            return {}

        try:
            # Fetch S-1 document
            response = requests.get(s1_url, headers=self.headers, timeout=60)
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()

            # Limit to first 50,000 characters (S-1s are huge, cover page usually has what we need)
            text_excerpt = text[:50000]

            # PHASE 1+: Extract 8 critical + 8 additional fields for future validation
            prompt = f"""Extract SPAC IPO information from S-1 cover page and first sections. Return ONLY valid JSON.

Company: {company}

**CRITICAL FIELDS (Priority 1):**
- expected_ticker: Proposed ticker symbol (e.g., "PACE", "PACEU" for units)
- target_proceeds_millions: Gross proceeds in millions as NUMERIC (e.g., 300 for $300M, 150 for $150M, 500 for $500M)
- units_offered: Number of units (integer only, e.g., 30000000)
- sponsor: Sponsor entity name (usually in first paragraph)
- lead_banker: Lead underwriter (look for "Representative of Underwriters" or "book-running manager")
- charter_deadline_months: Months to find target (18, 21, or 24 - look for "within [X] months")
- target_sector: Industry focus (e.g., "Technology", "Healthcare", "Consumer")
- trust_per_unit: Price per unit (usually "$10.00")

**ADDITIONAL FIELDS (Priority 2 - extract if found):**
- ipo_price_range: Price range or fixed price (e.g., "$10.00" or "$9.75-$10.25")
- unit_structure: Unit composition (e.g., "1 share + 1/3 warrant" or "1 share + 1 right")
- warrant_ratio: Just the ratio (e.g., "1/3", "1/2", "1")
- warrant_strike: Exercise price (e.g., 11.50)
- sponsor_promote: Founder shares percentage (e.g., 20.0 for 20%)
- underwriter_discount: Underwriting fee % (e.g., 5.5 for 5.5%)
- co_bankers: Other underwriters (comma-separated)
- min_target_valuation: Minimum target size (e.g., "$500M enterprise value")

Cover page keywords:
- "Maximum Aggregate Offering Price" = target_proceeds_millions (convert $300,000,000 → 300, convert $150M → 150)
- "Units, each consisting of" = units_offered AND unit_structure
- "Ticker Symbol:" = expected_ticker
- "Price to Public" = ipo_price_range
- "Underwriting Discount" = underwriter_discount
- "we will have X months from the closing of this offering" = charter_deadline_months
- "intend to focus on businesses with enterprise values of at least" = min_target_valuation
- "warrants exercisable at $" = warrant_strike
- "founder shares" or "20% of outstanding shares" = sponsor_promote

IMPORTANT: For target_proceeds_millions, convert any dollar amount to numeric millions:
- "$300,000,000" → 300
- "$150,000,000" → 150
- "$500M" → 500
- "$60M" → 60

Return JSON only (use null for missing fields, ~60% accuracy acceptable for Priority 1, ~40% for Priority 2):"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": text_excerpt[:8000]}, {"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=400  # Reduced - only extracting 8 fields
            )

            result = response.choices[0].message.content.strip()
            result = re.sub(r'```json\s*|\s*```', '', result)

            import json
            data = json.loads(result)

            extracted_count = len([v for v in data.values() if v])
            print(f"   🤖 AI extracted {extracted_count}/8 critical fields")

            return data

        except Exception as e:
            print(f"   ❌ AI parsing failed: {e}")
            return {}

    def clean_ai_data(self, s1_data: Dict) -> Dict:
        """Clean AI-extracted data for database insertion"""
        cleaned = {}

        for key, value in s1_data.items():
            if value is None or value == '' or value == 'null':
                cleaned[key] = None
                continue

            # Clean specific fields
            if key == 'target_proceeds_millions':
                # Convert to numeric millions (should already be numeric from AI)
                # Handle edge cases: "$300M" → 300, "$300,000,000" → 300, or just 300
                if isinstance(value, str):
                    # Remove $, commas, M
                    value_str = value.replace('$', '').replace(',', '').upper()
                    if 'M' in value_str:
                        # Already in millions: "300M" → 300
                        value_str = value_str.replace('M', '')
                        try:
                            cleaned[key] = float(value_str)
                        except:
                            cleaned[key] = None
                    else:
                        # Could be full amount: "300000000" → 300
                        try:
                            full_amount = float(value_str)
                            if full_amount > 1000000:
                                cleaned[key] = full_amount / 1000000
                            else:
                                cleaned[key] = full_amount
                        except:
                            cleaned[key] = None
                elif isinstance(value, (int, float)):
                    # Already numeric - check if it needs conversion
                    if value > 1000000:
                        cleaned[key] = value / 1000000
                    else:
                        cleaned[key] = float(value)
                else:
                    cleaned[key] = None

            elif key == 'trust_per_unit':
                # Convert "$10.00" → 10.00
                if isinstance(value, str):
                    value = value.replace('$', '').replace(',', '')
                    try:
                        cleaned[key] = float(value)
                    except:
                        cleaned[key] = None
                else:
                    cleaned[key] = value

            elif key == 'units_offered':
                # Ensure integer
                if isinstance(value, str):
                    value = value.replace(',', '')
                try:
                    cleaned[key] = int(value)
                except:
                    cleaned[key] = None

            elif key == 'charter_deadline_months':
                # Ensure integer
                try:
                    cleaned[key] = int(value)
                except:
                    cleaned[key] = None

            elif key == 'warrant_strike':
                # Convert "$11.50" → 11.50
                if isinstance(value, str):
                    value = value.replace('$', '').replace(',', '')
                try:
                    cleaned[key] = float(value)
                except:
                    cleaned[key] = None

            elif key in ['sponsor_promote', 'underwriter_discount']:
                # Ensure float (percentage)
                try:
                    cleaned[key] = float(value)
                except:
                    cleaned[key] = None

            else:
                cleaned[key] = value

        return cleaned

    def save_pre_ipo_spac(self, filing_data: Dict, s1_data: Dict, s1_url: str) -> bool:
        """Save pre-IPO SPAC to database (skip if already IPO'd)"""
        try:
            # Check if already IPO'd (in main database)
            already_ipod = self.main_db.query(SPAC).filter(
                SPAC.cik == filing_data['cik']
            ).first()

            if already_ipod:
                print(f"   ⏭️  {filing_data['company']} already IPO'd (ticker: {already_ipod.ticker}) - skipping")
                return True

            # Check if already exists in pre-IPO database
            existing = self.db.query(PreIPOSPAC).filter(
                PreIPOSPAC.cik == filing_data['cik']
            ).first()

            if existing:
                print(f"   ℹ️  {filing_data['company']} already in pre-IPO database")
                # Update amendment count if this is S-1/A
                if filing_data['filing_type'] == 'S-1/A':
                    existing.amendment_count += 1
                    existing.latest_s1a_date = filing_data['filing_date']
                    existing.filing_status = 'S-1/A'
                    self.db.commit()
                    print(f"      Updated: Amendment #{existing.amendment_count}")
                return True

            # Clean AI data
            cleaned_data = self.clean_ai_data(s1_data)

            # Ensure target_proceeds string column matches numeric value (for backwards compatibility)
            if cleaned_data.get('target_proceeds_millions'):
                cleaned_data['target_proceeds'] = f"${int(cleaned_data['target_proceeds_millions'])}M"

            # Create new entry
            spac = PreIPOSPAC(
                company=filing_data['company'],
                cik=filing_data['cik'],
                s1_filing_date=filing_data['filing_date'],
                filing_status='S-1',
                s1_url=s1_url,
                latest_filing_url=s1_url,
                **cleaned_data  # Spread cleaned AI-extracted data
            )

            self.db.add(spac)
            self.db.commit()

            print(f"   ✅ Saved: {filing_data['company']}")
            if cleaned_data.get('expected_ticker'):
                print(f"      Ticker: {cleaned_data['expected_ticker']}")
            if cleaned_data.get('target_sector'):
                print(f"      Target: {cleaned_data['target_sector']}")
            if cleaned_data.get('target_proceeds_millions'):
                print(f"      Proceeds: ${cleaned_data['target_proceeds_millions']}M")

            return True

        except Exception as e:
            print(f"   ❌ Error saving to database: {e}")
            self.db.rollback()
            return False

    def run_search(self, days_back: int = 90):
        """Main method: Search for new SPACs and parse them (default: 90 days)"""
        print("="*60)
        print("PRE-IPO SPAC FINDER")
        print("="*60)

        # Step 1: Search SEC EDGAR
        filings = self.search_recent_s1_filings(days_back)

        if not filings:
            print("✅ No new filings found")
            return

        # Step 2: Process each filing
        for i, filing in enumerate(filings, 1):
            print(f"\n[{i}/{len(filings)}] Processing {filing['company']}...")

            # Get S-1 document URL
            s1_url = self.get_s1_document_url(filing['filing_url'])
            if not s1_url:
                print("   ⚠️  Could not find S-1 document")
                continue

            print(f"   📄 Found S-1 document")

            # Parse with AI
            s1_data = self.parse_s1_with_ai(s1_url, filing['company'])

            # Save to database
            self.save_pre_ipo_spac(filing, s1_data, s1_url)

            # Rate limiting
            time.sleep(1)

        print("\n" + "="*60)
        print("✅ SEARCH COMPLETE")
        print("="*60)

        # Print summary
        total = self.db.query(PreIPOSPAC).count()
        recent = self.db.query(PreIPOSPAC).filter(
            PreIPOSPAC.moved_to_main_pipeline == False
        ).count()

        print(f"\n📊 Pre-IPO SPACs in pipeline: {recent}")
        print(f"📊 Total tracked (all time): {total}")

    def close(self):
        """Close database connections"""
        self.db.close()
        self.main_db.close()


if __name__ == "__main__":
    import sys

    # Get days_back from command line (default 7)
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 7

    finder = PreIPOSPACFinder()
    try:
        finder.run_search(days_back)
    finally:
        finder.close()
