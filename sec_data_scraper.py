#!/usr/bin/env python3
"""
Complete SEC Data Scraper for LEVP SPAC Platform
Extracts: IPO Date, Proceeds, Tickers, Structure, Deadline, Trust Cash
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup
from typing import Dict, Optional

from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, SPAC
from auto_log_data_changes import init_logger, log_data_change
from enhance_extraction_logger import get_enhanced_logger
from utils.deal_value_tracker import update_deal_value
from utils.trust_account_tracker import update_trust_cash, update_trust_value, update_shares_outstanding
from utils.redemption_tracker import add_redemption_event
from sec_text_extractor import extract_filing_text
from prompt_manager import get_prompt, log_prompt_result

# Import dateutil for date calculations
try:
    from dateutil.relativedelta import relativedelta
except:
    print("⚠️  Installing python-dateutil...")
    import subprocess
    subprocess.run(['pip', 'install', 'python-dateutil'], check=True)
    from dateutil.relativedelta import relativedelta

# DeepSeek AI setup
try:
    from openai import OpenAI
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
        print("✅ AI Agent initialized")
    else:
        AI_AVAILABLE = False
        print("⚠️  AI unavailable (no DEEPSEEK_API_KEY)")
except Exception as e:
    AI_AVAILABLE = False
    print(f"⚠️  AI unavailable: {e}")


class SPACDataEnricher:

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {
            'User-Agent': 'Legacy EVP Spac Platform fenil@legacyevp.com'
        }
        self.db = SessionLocal()
        self.logger = get_enhanced_logger()
        init_logger()  # Initialize data quality logging

    def get_cik(self, company_name: str) -> Optional[str]:
        """Get CIK number for a company (tries variations if needed)"""
        try:
            # Try exact name first
            variations = [company_name]

            # Add common variations
            if company_name.endswith('.'):
                variations.append(company_name[:-1])  # Remove trailing period
            else:
                variations.append(company_name + '.')  # Add trailing period

            # Try without suffixes like "Inc.", "Corp.", "LLC"
            for suffix in [' Inc.', ' Corp.', ' Corporation', ' LLC', ' Co.']:
                if company_name.endswith(suffix):
                    variations.append(company_name.replace(suffix, ''))

            # Try with/without "The" prefix
            if company_name.startswith('The '):
                variations.append(company_name[4:])
            else:
                variations.append('The ' + company_name)

            for variation in variations:
                url = f"{self.base_url}/cgi-bin/browse-edgar"
                params = {
                    'company': variation,
                    'owner': 'exclude',
                    'action': 'getcompany',
                    'count': 1
                }

                response = requests.get(url, params=params, headers=self.headers, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')

                cik_elem = soup.find('span', {'class': 'companyName'})
                if cik_elem:
                    text = cik_elem.get_text()
                    match = re.search(r'CIK#:\s*(\d+)', text)
                    if match:
                        cik = match.group(1).lstrip('0') or '0'
                        if variation != company_name:
                            print(f"   ℹ️  Found with variation: '{variation}'")
                        return cik

                time.sleep(0.15)  # Rate limiting between attempts

            return None
        except Exception as e:
            print(f"Error getting CIK: {e}")
            return None

    def _validate_ipo_press_release(self, url: str, debug=False) -> bool:
        """Check if document is IPO CLOSING press release (not pricing announcement)"""
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            text = response.text[:12000].lower()

            # Check for closing indicators (more permissive)
            closing_indicators = [
                'announced today the closing of',
                'announces the closing of',
                'closing of its initial public offering',
                'closed its initial public offering',
                'completed its initial public offering',
                'consummated its initial public offering',
                'consummated the initial public offering',
                'consummated an initial public offering',
                'announced the closing',
                'today closed its',
                'has closed its',
                'exercise of the over-allotment',
                'over-allotment option',
                'underwriters have exercised',
                'underwriters exercised',
                'underwriters fully exercised',
                'exercise in full',
                'full exercise of',
                'closing of the offering',
                'closing of the ipo'
            ]
            has_closing = any(phrase in text for phrase in closing_indicators)

            # Check for pricing-only indicators (these are BAD if closing not mentioned)
            pricing_only_phrases = [
                'prices initial public offering',
                'priced its initial public offering',
                'announces pricing of',
                'announces the pricing of',
                'announced the pricing of',
                'pricing of its initial public offering',
                'pricing of upsized'
            ]
            is_pricing_mention = any(phrase in text for phrase in pricing_only_phrases)

            # If it mentions pricing but NOT closing, it's likely a pricing announcement
            if is_pricing_mention and not has_closing:
                if debug:
                    print(f" [REJECTED: pricing-only]")
                return False

            # Check for key content
            has_proceeds = (
                'gross proceeds' in text or
                'aggregate gross' in text or
                'total gross proceeds' in text or
                'proceeds of $' in text or
                'proceeds of approximately' in text or
                'raised $' in text
            )
            has_units = 'units' in text or 'unit' in text

            # Check for underwriter/banker mentions (strong IPO indicator)
            has_underwriters = (
                'book-running' in text or
                'underwriter' in text or
                'book runner' in text or
                'acted as' in text
            )

            # Deal announcements are bad
            deal_indicators = [
                'business combination agreement',
                'merger agreement',
                'definitive agreement',
                'entered into a business combination'
            ]
            is_deal = any(x in text for x in deal_indicators)

            # Debug output
            if debug:
                print(f" [closing:{has_closing}, proceeds:{has_proceeds}, units:{has_units}, underwriters:{has_underwriters}, deal:{is_deal}]", end='')

            # Accept if any of these conditions:
            # 1. Has closing AND proceeds/units AND not a deal
            # 2. Has proceeds AND units AND underwriters AND not deal (likely closing PR)
            # 3. Has closing AND underwriters (even without proceeds mention)
            # 4. Has units AND underwriters AND NOT pricing-only (more permissive)
            if is_deal:
                return False

            if has_closing and (has_proceeds or has_units):
                return True
            elif has_proceeds and has_units and has_underwriters:
                return True
            elif has_closing and has_underwriters:
                return True
            elif has_units and has_underwriters and not is_pricing_mention:
                # Allow 8-Ks with units + underwriters even without explicit "closing" word
                return True

            return False

        except Exception as e:
            if debug:
                print(f" [ERROR: {e}]", end='')
            return False

    def get_ipo_press_release(self, cik: str) -> tuple[Optional[str], Optional[str]]:
        """Find IPO CLOSING press release (not pricing announcement)

        Returns:
            (press_release_url, earliest_8k_main_url): tuple of URLs
            - press_release_url: Exhibit 99.1 press release if found
            - earliest_8k_main_url: Main 8-K document URL (fallback for body parsing)
        """
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': '8-K',
                'dateb': '',
                'owner': 'exclude',
                'count': 40
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None, None

            # Get all filings
            filings = []
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date = cols[3].get_text().strip()
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filings.append({
                            'date': filing_date,
                            'url': self.base_url + doc_link['href']
                        })

            # Sort by date descending (newest first) but we'll check oldest IPO-related ones
            filings.sort(key=lambda x: x['date'], reverse=False)
            print(f"   Found {len(filings)} 8-Ks, checking for closing PR...")

            earliest_8k_main_url = None

            # Check each filing, prioritizing older ones first (IPO closing is usually early)
            for i, filing in enumerate(filings[:15]):
                print(f"   [{i+1}] {filing['date']}", end='')

                try:
                    filing_page = requests.get(filing['url'], headers=self.headers, timeout=30)
                    filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                    # Store the first (earliest) 8-K main document URL as fallback
                    if earliest_8k_main_url is None:
                        # Find main 8-K document (usually first HTML file)
                        exhibit_table = filing_soup.find('table', {'class': 'tableFile'})
                        if exhibit_table:
                            for row in exhibit_table.find_all('tr'):
                                cells = row.find_all('td')
                                if len(cells) >= 4:
                                    desc = cells[3].get_text().lower()
                                    link = cells[2].find('a', href=True)
                                    # Look for main 8-K document (not exhibits)
                                    if link and '8-k' in desc and 'ex' not in desc:
                                        main_url = self.base_url + link['href']
                                        # Handle iXBRL viewer URLs
                                        if '/ix?doc=' in main_url:
                                            main_url = self.base_url + main_url.split('/ix?doc=')[1]
                                        earliest_8k_main_url = main_url
                                        break

                    # Method 1: Exhibit table
                    exhibit_table = filing_soup.find('table', {'class': 'tableFile'})
                    if exhibit_table:
                        for row in exhibit_table.find_all('tr'):
                            cells = row.find_all('td')
                            if len(cells) >= 4:
                                desc = cells[3].get_text().lower()
                                if any(k in desc for k in ['press release', 'news release', 'closing', 'ex-99']):
                                    link = cells[2].find('a', href=True)
                                    if link:
                                        doc_url = self.base_url + link['href']
                                        if self._validate_ipo_press_release(doc_url, debug=True):
                                            print(f" ✓ Found closing PR!")
                                            return doc_url, earliest_8k_main_url

                    # Method 2: All EX-99.x exhibits
                    for link in filing_soup.find_all('a', href=True):
                        href = link['href'].lower()
                        if '.htm' in href and 'ex99' in href:
                            doc_url = self.base_url + link['href']
                            if self._validate_ipo_press_release(doc_url, debug=True):
                                print(f" ✓ Found closing PR!")
                                return doc_url, earliest_8k_main_url

                    print("")  # New line if nothing found
                except Exception as e:
                    print(f" ✗ ({str(e)[:30]})")
                    continue

            return None, earliest_8k_main_url
        except Exception as e:
            print(f"Error finding press release: {e}")
            return None, None

    def get_prospectus(self, cik: str) -> Optional[str]:
        """Find IPO prospectus (424B4)"""
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': '424B4',
                'dateb': '',
                'owner': 'exclude',
                'count': 5
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None

            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']
                        filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                        filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                        # Look for the primary document table
                        doc_table = filing_soup.find('table', {'class': 'tableFile', 'summary': 'Document Format Files'})
                        if doc_table:
                            # Get first row (primary document)
                            rows = doc_table.find_all('tr')
                            if len(rows) > 1:  # Skip header
                                first_row = rows[1]
                                first_link = first_row.find('a', href=True)
                                if first_link and '.htm' in first_link['href']:
                                    return self.base_url + first_link['href']

                        # Fallback: Look for any .htm file (excluding index/ix files)
                        for link in filing_soup.find_all('a', href=True):
                            href = link['href']
                            if '.htm' in href and 'index' not in href.lower() and 'ix?doc=' not in href:
                                # Skip common non-document files
                                if not any(skip in href.lower() for skip in ['/index.htm', 'companysearch', '.xml']):
                                    return self.base_url + href

            return None
        except Exception as e:
            print(f"   ⚠️  Error finding prospectus: {e}")
            return None

    def get_s1_filing(self, cik: str) -> Optional[str]:
        """Find S-1 registration statement"""
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': 'S-1',
                'dateb': '',
                'owner': 'exclude',
                'count': 5
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None

            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']
                        filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                        filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                        # Look for main S-1 document (not amendments)
                        for link in filing_soup.find_all('a', href=True):
                            href = link['href']
                            if '.htm' in href and 's-1.htm' in href.lower():
                                return self.base_url + href
                            elif '.htm' in href and 's1.htm' in href.lower():
                                return self.base_url + href

                        # Fallback: any HTML file in the S-1 filing
                        for link in filing_soup.find_all('a', href=True):
                            if '.htm' in link['href'] and 'ex' not in link['href'].lower():
                                return self.base_url + link['href']

            return None
        except Exception as e:
            print(f"Error finding S-1: {e}")
            return None

    def get_s4_filing(self, cik: str) -> Optional[tuple]:
        """Find S-4 merger registration statement (filed after deal announcement)

        Returns:
            Tuple of (filing_url, filing_date) or None if not found
        """
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': 'S-4',
                'dateb': '',
                'owner': 'exclude',
                'count': 5
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None

            # Get the most recent S-4 filing
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date = cols[3].get_text().strip()  # Extract filing date
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']
                        filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                        filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                        # Look for main S-4 document (not amendments or exhibits)
                        for link in filing_soup.find_all('a', href=True):
                            href = link['href']
                            if '.htm' in href and 's-4.htm' in href.lower():
                                return (self.base_url + href, filing_date)
                            elif '.htm' in href and 's4.htm' in href.lower():
                                return (self.base_url + href, filing_date)

                        # Fallback: any HTML file in the S-4 filing (excluding exhibits)
                        for link in filing_soup.find_all('a', href=True):
                            if '.htm' in link['href'] and 'ex' not in link['href'].lower() and 'index' not in link['href'].lower():
                                return (self.base_url + link['href'], filing_date)

            return None
        except Exception as e:
            print(f"   ⚠️  Error finding S-4: {e}")
            return None

    def check_for_deal_announcement(self, cik: str, ipo_date: Optional[str] = None) -> Optional[Dict]:
        """
        Check for deal announcements in BOTH 8-K and Form 425 filings

        Primary signals:
        1. 8-K Item 1.01 - Entry into Material Definitive Agreement
        2. Form 425 - Communications about business combinations

        Returns: EARLIEST announcement across both filing types
        """
        all_deals = []

        # Check 8-K filings (existing logic)
        print(f"   🔍 Checking 8-K filings for deal announcement...")
        deals_8k = self._check_filings_for_deals('8-K', cik, ipo_date, count=40)
        if deals_8k:
            all_deals.extend(deals_8k)
            print(f"   ✓ Found {len(deals_8k)} potential deal(s) in 8-K filings")

        # Check Form 425 filings (new)
        print(f"   🔍 Checking Form 425 filings for deal announcement...")
        deals_425 = self._check_filings_for_deals('425', cik, ipo_date, count=20)
        if deals_425:
            all_deals.extend(deals_425)
            print(f"   ✓ Found {len(deals_425)} potential deal(s) in Form 425 filings")

        # Return EARLIEST across all filing types
        if all_deals:
            # Sort by date (oldest first)
            all_deals.sort(key=lambda x: x['date'])
            earliest = all_deals[0]

            print(f"   ✓ Found {len(all_deals)} total filing(s), using earliest: {earliest['date']}")

            # Extract deal details from earliest announcement
            deal_data = self._extract_deal_details(earliest['text'], earliest['date'])

            # Validate: If no target extracted, likely a false positive
            if not deal_data.get('target'):
                print(f"   ⚠️  Deal keywords found but no target extracted - likely false positive")
                return None

            return deal_data

        return None

    def _check_filings_for_deals(self, filing_type: str, cik: str, ipo_date: Optional[str] = None, count: int = 40) -> list:
        """
        Check specific filing type (8-K or 425) for deal announcements

        Args:
            filing_type: '8-K' or '425'
            cik: Company CIK
            ipo_date: IPO date to filter out IPO-related filings
            count: Number of filings to check

        Returns:
            List of dicts with 'date' and 'text' for each potential deal found
        """
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': filing_type,
                'dateb': '',
                'owner': 'exclude',
                'count': count
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return []

            # Calculate cutoff date (60 days after IPO to skip IPO-related filings)
            ipo_cutoff = None
            if ipo_date:
                try:
                    from dateutil.relativedelta import relativedelta
                    ipo_dt = datetime.strptime(str(ipo_date), '%Y-%m-%d')
                    ipo_cutoff = ipo_dt + relativedelta(days=60)
                except:
                    pass

            # Collect ALL deal announcements from this filing type
            all_deals = []

            # Get all filings (newest first)
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date = cols[3].get_text().strip()

                    # Skip filings within 60 days of IPO (likely IPO-related)
                    if ipo_cutoff:
                        try:
                            filing_dt = datetime.strptime(filing_date, '%Y-%m-%d')
                            if filing_dt < ipo_cutoff:
                                continue
                        except:
                            pass

                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})

                    if doc_link:
                        filing_url = self.base_url + doc_link['href']

                        try:
                            # Get the filing page
                            filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                            filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                            # Look for press release (Exhibit 99.1) first, then other exhibits
                            # Exhibit 99.1 has brand names, legal docs have entity names
                            exhibits_to_check = []

                            for link in filing_soup.find_all('a', href=True):
                                href = link['href'].lower()
                                if '.htm' in href and 'ex' in href:
                                    # Prioritize press release (99.1)
                                    if 'ex99' in href or 'ex-99' in href:
                                        exhibits_to_check.insert(0, self.base_url + link['href'])  # Add to front
                                    else:
                                        exhibits_to_check.append(self.base_url + link['href'])  # Add to end

                            # Check exhibits in priority order (press release first)
                            for doc_url in exhibits_to_check:
                                try:
                                    # Fetch the document
                                    doc_response = requests.get(doc_url, headers=self.headers, timeout=15)
                                    doc_text = doc_response.text.lower()

                                    # Check for deal announcement keywords
                                    deal_keywords = [
                                        'business combination agreement',
                                        'definitive agreement',
                                        'merger agreement',
                                        'entered into a business combination',
                                        'executed a business combination',
                                        'announce the proposed business combination'
                                    ]

                                    # Exclude IPO-related filings (false positives)
                                    ipo_keywords = [
                                        'initial public offering',
                                        'closing of its ipo',
                                        'ipo proceeds',
                                        'units commenced trading',
                                        'underwriters have exercised'
                                    ]

                                    has_deal = any(keyword in doc_text for keyword in deal_keywords)
                                    has_ipo = any(keyword in doc_text for keyword in ipo_keywords)

                                    # Check for past tense (real deal) vs future tense (intent statement)
                                    past_tense_indicators = [
                                        'entered into',
                                        'has entered',
                                        'announced',
                                        'has announced',
                                        'signed',
                                        'executed',
                                        'completed the execution'
                                    ]
                                    future_tense_indicators = [
                                        'intend to',
                                        'will pursue',
                                        'plans to',
                                        'seeking to',
                                        'focused on',
                                        'purpose is to'
                                    ]

                                    has_past_tense = any(indicator in doc_text for indicator in past_tense_indicators)
                                    has_future_tense = any(indicator in doc_text for indicator in future_tense_indicators)

                                    # Check if within 30 days of IPO (if we have IPO date)
                                    likely_ipo_filing = False
                                    if ipo_date:
                                        try:
                                            from datetime import datetime, timedelta
                                            ipo_dt = datetime.strptime(ipo_date, '%Y-%m-%d')
                                            filing_dt = datetime.strptime(filing_date, '%Y-%m-%d')
                                            days_since_ipo = (filing_dt - ipo_dt).days
                                            if 0 <= days_since_ipo <= 30:
                                                likely_ipo_filing = True
                                        except:
                                            pass

                                    # Only consider it a deal if:
                                    # 1. Has deal keywords AND NOT IPO keywords
                                    # 2. Has past tense (not future intent)
                                    # 3. NOT within 30 days of IPO
                                    if has_deal and not has_ipo and has_past_tense and not has_future_tense and not likely_ipo_filing:
                                        # Found a deal announcement - add to list
                                        all_deals.append({
                                            'date': filing_date,
                                            'text': doc_text
                                        })
                                        break  # Move to next filing once we found deal in this one

                                except Exception as e:
                                    # Error fetching this exhibit, try next one
                                    continue

                        except Exception as e:
                            continue

            # Return all deals found from this filing type
            return all_deals

        except Exception as e:
            print(f"   ⚠️  Error checking {filing_type} filings: {e}")
            return []

    def _extract_deal_details(self, text: str, filing_date: str) -> Dict:
        """Extract target, deal value, and dates from deal announcement"""
        deal_data = {
            'deal_status': 'ANNOUNCED',
            'announced_date': filing_date,
            'target': None,
            'deal_value': None,
            'expected_close': None
        }

        try:
            # Use AI if available
            if AI_AVAILABLE:
                # Load managed prompt from YAML
                prompt_data = get_prompt('deal_target_extraction_v2', filing_text=text[:8000])

                try:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": prompt_data['system_prompt']},
                            {"role": "user", "content": prompt_data['user_prompt']}
                        ],
                        temperature=0,
                        max_tokens=300
                    )

                    result = response.choices[0].message.content.strip()
                    result = re.sub(r'```json\s*|\s*```', '', result)

                    import json
                    ai_data = json.loads(result)

                    if ai_data.get('target'):
                        deal_data['target'] = ai_data['target']
                    if ai_data.get('deal_value'):
                        deal_data['deal_value'] = ai_data['deal_value']
                    if ai_data.get('expected_close'):
                        deal_data['expected_close'] = ai_data['expected_close']

                    # Log extraction result for prompt performance tracking
                    log_prompt_result(
                        'deal_target_extraction_v2',
                        success=ai_data.get('target') is not None,
                        extracted_data=ai_data,
                        spac_ticker=ticker
                    )

                except:
                    pass

            # Regex fallback for target company
            if not deal_data['target']:
                target_patterns = [
                    r'business combination (?:agreement )?with ([A-Z][A-Za-z\s&,\.]+(?:Inc\.|LLC|Corp\.|Corporation|Ltd\.))',
                    r'merge with ([A-Z][A-Za-z\s&,\.]+(?:Inc\.|LLC|Corp\.|Corporation|Ltd\.))',
                    r'acquire ([A-Z][A-Za-z\s&,\.]+(?:Inc\.|LLC|Corp\.|Corporation|Ltd\.))'
                ]

                for pattern in target_patterns:
                    match = re.search(pattern, text[:15000], re.IGNORECASE)
                    if match:
                        deal_data['target'] = match.group(1).strip()
                        break

            # Regex for deal value
            if not deal_data['deal_value']:
                value_patterns = [
                    r'enterprise value of (?:approximately )?\$([0-9,\.]+)\s*(billion|million)',
                    r'valuation of (?:approximately )?\$([0-9,\.]+)\s*(billion|million)',
                    r'transaction values? (?:the combined company )?at (?:approximately )?\$([0-9,\.]+)\s*(billion|million)'
                ]

                for pattern in value_patterns:
                    match = re.search(pattern, text[:15000], re.IGNORECASE)
                    if match:
                        amount = match.group(1).replace(',', '')
                        unit = match.group(2)[0].upper()  # B or M
                        deal_data['deal_value'] = f"${amount}{unit}"
                        break

        except Exception as e:
            print(f"   ⚠️  Error extracting deal details: {e}")

        return deal_data

    def get_latest_10q_or_10k(self, cik: str) -> Optional[tuple]:
        """Get latest 10-Q or 10-K filing URL and date

        Returns the NEWEST filing between 10-Q and 10-K by comparing dates.

        Returns:
            Tuple of (filing_url, filing_date, filing_type) or None if not found
        """
        try:
            cik_padded = cik.zfill(10)

            latest_filing = None
            latest_date = None

            # Check both 10-Q and 10-K, return whichever is newer
            for filing_type in ['10-Q', '10-K']:
                url = f"{self.base_url}/cgi-bin/browse-edgar"
                params = {
                    'action': 'getcompany',
                    'CIK': cik_padded,
                    'type': filing_type,
                    'dateb': '',
                    'owner': 'exclude',
                    'count': 3
                }

                response = requests.get(url, params=params, headers=self.headers, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')

                table = soup.find('table', {'class': 'tableFile2'})
                if not table:
                    continue

                # Check if we found any filings
                rows = table.find_all('tr')[1:]
                if not rows:
                    continue

                print(f"   Checking {filing_type} filings...", end='')

                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        filing_date = cols[3].get_text().strip()  # Extract filing date
                        doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                        if doc_link:
                            filing_url = self.base_url + doc_link['href']

                            # Get the filing page
                            filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                            filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                            # Get the document table
                            doc_table = filing_soup.find('table', {'class': 'tableFile', 'summary': 'Document Format Files'})
                            if not doc_table:
                                continue

                            # Try to find the main document
                            for doc_row in doc_table.find_all('tr')[1:]:
                                cells = doc_row.find_all('td')
                                if len(cells) >= 4:
                                    doc_type = cells[3].get_text().strip()
                                    link = cells[2].find('a', href=True)
                                    
                                    if link and '.htm' in link['href'].lower():
                                        # Look for main document (usually first HTML file or labeled as filing type)
                                        href_lower = link['href'].lower()
                                        
                                        # Check if this looks like the main document
                                        is_main = (
                                            filing_type.lower().replace('-', '') in href_lower or
                                            filing_type.lower() in doc_type.lower() or
                                            'htm' in doc_type.lower() and 'ex' not in doc_type.lower()
                                        )
                                        
                                        if is_main:
                                            doc_url = self.base_url + link['href']

                                            # Handle iXBRL viewer URLs - extract raw document URL
                                            # Format: https://www.sec.gov/ix?doc=/Archives/...
                                            if '/ix?doc=' in doc_url:
                                                doc_url = self.base_url + doc_url.split('/ix?doc=')[1]

                                            # Parse filing date
                                            from dateutil import parser
                                            try:
                                                filing_date_obj = parser.parse(filing_date).date()
                                            except:
                                                filing_date_obj = None

                                            # Compare with latest filing found
                                            if not latest_date or (filing_date_obj and filing_date_obj > latest_date):
                                                latest_filing = (doc_url, filing_date, filing_type)
                                                latest_date = filing_date_obj
                                                print(f" ✓ {filing_date}")
                                            else:
                                                print(f" (older)")
                                            break

                if not latest_filing:
                    print(f" ✗")

            return latest_filing
        except Exception as e:
            print(f"   Error finding 10-Q/10-K: {e}")
            return None

    def extract_trust_cash(self, url: str) -> Optional[Dict]:
        """Extract trust account value from 10-Q/10-K balance sheet (most recent period only)"""
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            text = response.text

            # Remove HTML tags for cleaner parsing
            soup = BeautifulSoup(text, 'html.parser')
            clean_text = soup.get_text()

            # Lightweight check for business combination mention (for deal confirmation)
            self._check_deal_mention_in_10q(clean_text)

            # Method 1: Extract per-share redemption value directly from balance sheet
            # Pattern: "subject to possible redemption at $10.07 per share" or "at redemption value of $10.52"
            redemption_patterns = [
                r'subject to (?:possible )?redemption at \$([0-9,]+\.?[0-9]*) per share',
                r'at redemption value of \$([0-9,]+\.?[0-9]*)',
                r'redemption price of \$([0-9,]+\.?[0-9]*) per share'
            ]

            match = None
            for pattern in redemption_patterns:
                match = re.search(pattern, clean_text, re.IGNORECASE)
                if match:
                    break

            if match:
                trust_value = float(match.group(1).replace(',', ''))
                print(f"   ℹ️  Found explicit per-share value: ${trust_value:.2f}")

                # Try to extract trust cash and shares from same period
                trust_cash, shares_outstanding = self._extract_from_same_period(clean_text)

                # Validate: only use if they match the explicit trust_value
                result = {'trust_value': round(trust_value, 2)}

                if trust_cash and shares_outstanding:
                    calculated_value = trust_cash / shares_outstanding
                    # Allow 5% tolerance for rounding differences
                    if abs(calculated_value - trust_value) / trust_value < 0.05:
                        result['trust_cash'] = trust_cash
                        result['shares_outstanding'] = shares_outstanding

                        # Extract founder shares
                        founder_shares = self._extract_founder_shares(clean_text)
                        if founder_shares:
                            result['founder_shares'] = founder_shares
                            total_shares = shares_outstanding + founder_shares
                            result['founder_ownership'] = round((founder_shares / total_shares) * 100, 2)
                    else:
                        print(f"   ⚠️  Trust cash/shares don't match NAV (${calculated_value:.2f} vs ${trust_value:.2f}), skipping")

                return result

            # Method 2: Try AI-based balance sheet extraction (more accurate)
            if AI_AVAILABLE:
                print(f"   Attempting AI balance sheet extraction...")
                ai_result = self._extract_trust_with_ai(clean_text)

                if ai_result and ai_result.get('trust_cash') and ai_result.get('shares_outstanding'):
                    trust_per_share = ai_result['trust_cash'] / ai_result['shares_outstanding']

                    # Validate AI result
                    if 8 <= trust_per_share <= 15:
                        print(f"   ✓ AI extracted trust NAV: ${trust_per_share:.2f}")
                        result = {
                            'trust_cash': ai_result['trust_cash'],
                            'shares_outstanding': ai_result['shares_outstanding'],
                            'trust_value': round(trust_per_share, 2)
                        }

                        # Extract founder shares
                        founder_shares = self._extract_founder_shares(clean_text)
                        if founder_shares:
                            result['founder_shares'] = founder_shares
                            total_shares = ai_result['shares_outstanding'] + founder_shares
                            result['founder_ownership'] = round((founder_shares / total_shares) * 100, 2)

                        return result
                    else:
                        print(f"   ⚠️  AI result outside valid range: ${trust_per_share:.2f}")

            # Method 3: Fallback to regex-based extraction
            trust_cash, shares_outstanding = self._extract_from_same_period(clean_text)

            if not trust_cash or not shares_outstanding:
                return None

            trust_per_share = trust_cash / shares_outstanding

            # Validate: trust NAV should be reasonable for SPACs ($8-$15 typically)
            if trust_per_share < 8 or trust_per_share > 15:
                print(f"   ⚠️  Calculated trust NAV ${trust_per_share:.2f} is outside normal range ($8-$15)")
                print(f"      Trust extraction likely failed - skipping trust data")
                return None

            # Extract founder shares (non-redeemable shares)
            founder_shares = self._extract_founder_shares(clean_text)

            # Calculate founder ownership
            founder_ownership = None
            if founder_shares and shares_outstanding:
                total_shares = shares_outstanding + founder_shares
                founder_ownership = round((founder_shares / total_shares) * 100, 2)

            result = {
                'trust_cash': trust_cash,
                'shares_outstanding': shares_outstanding,
                'trust_value': round(trust_per_share, 2)
            }
            if founder_shares:
                result['founder_shares'] = founder_shares
            if founder_ownership:
                result['founder_ownership'] = founder_ownership

            return result

        except Exception as e:
            print(f"   Error extracting trust cash: {e}")
            return None

    def extract_ipo_from_8k_body(self, filing_url: str) -> Dict:
        """Extract IPO data from 8-K main document (Items 8.01, 9.01) when no press release exists"""
        data = {}
        try:
            # Get the main 8-K document
            response = requests.get(filing_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the main 8-K document link
            main_doc_link = None
            for link in soup.find_all('a', href=True):
                href = link['href']
                text = link.get_text().strip()
                # Look for the main 8-K document (not exhibits)
                if '8-k.htm' in href.lower() or ('8-k' in text.lower() and 'ex' not in href.lower()):
                    main_doc_link = 'https://www.sec.gov' + href if href.startswith('/') else href
                    break

            if not main_doc_link:
                return data

            # Fetch the main document
            time.sleep(0.15)
            doc_response = requests.get(main_doc_link, headers=self.headers, timeout=30)
            doc_soup = BeautifulSoup(doc_response.text, 'html.parser')
            text = doc_soup.get_text()

            # Look for Item 8.01 or Item 9.01 sections
            item_patterns = [
                r'Item 8\.01[.\s\-]+[A-Za-z\s]+\n+(.*?)(?=Item \d|SIGNATURE|$)',
                r'Item 9\.01[.\s\-]+[A-Za-z\s]+\n+(.*?)(?=Item \d|SIGNATURE|$)'
            ]

            item_text = None
            for pattern in item_patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    item_text = match.group(1)[:5000]  # Take first 5000 chars
                    break

            if not item_text:
                # Fallback: search for "consummated" or "closing of" in full document
                consummated_idx = text.lower().find('consummated')
                closing_idx = text.lower().find('closing of the')

                if consummated_idx > 0:
                    item_text = text[max(0, consummated_idx-500):consummated_idx+2000]
                elif closing_idx > 0:
                    item_text = text[max(0, closing_idx-500):closing_idx+2000]

            if not item_text:
                return data

            # Use AI to extract IPO data
            if AI_AVAILABLE:
                print(f"   🤖 Extracting IPO data from 8-K main document...")

                prompt = f"""Extract IPO information from this 8-K text:

{item_text[:3000]}

Return ONLY a JSON object with these fields (use null if not found):
{{
  "ipo_date": "YYYY-MM-DD",
  "ipo_proceeds": "$XXM",
  "shares_sold": number,
  "overallotment_exercised": true/false,
  "overallotment_shares": number (how many overallotment shares),
  "sponsor_shares_issued": number (shares issued to sponsor/founder),
  "trust_cash_deposited": number (actual dollars deposited in trust account)
}}

Look for phrases like:
- "consummated", "initial public offering", "gross proceeds"
- "overallotment", "over-allotment", "greenshoe", "underwriters exercised"
- "sponsor", "founder", "175,000", "Class A shares"
- "trust account", "deposited", "held in trust"

IMPORTANT: Return the ACTUAL numbers from the filing text, not calculated values."""

                try:
                    response_ai = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1
                    )

                    result_text = response_ai.choices[0].message.content.strip()

                    # Extract JSON
                    json_match = re.search(r'\{[^{}]*\}', result_text, re.DOTALL)
                    if json_match:
                        import json
                        ai_data = json.loads(json_match.group(0))

                        # Original fields
                        if ai_data.get('ipo_date'):
                            data['ipo_date'] = ai_data['ipo_date']
                        if ai_data.get('ipo_proceeds'):
                            data['ipo_proceeds'] = ai_data['ipo_proceeds']

                        # New fields for body text extraction
                        if ai_data.get('overallotment_exercised') is not None:
                            data['overallotment_exercised'] = ai_data['overallotment_exercised']
                        if ai_data.get('overallotment_shares'):
                            data['overallotment_shares'] = ai_data['overallotment_shares']
                        if ai_data.get('sponsor_shares_issued'):
                            data['sponsor_shares_issued'] = ai_data['sponsor_shares_issued']
                        if ai_data.get('trust_cash_deposited'):
                            data['trust_cash'] = ai_data['trust_cash_deposited']

                        extracted_count = sum(1 for v in data.values() if v)
                        if extracted_count > 0:
                            print(f"   ✓ Extracted {extracted_count} IPO fields from 8-K body")
                            if data.get('overallotment_exercised'):
                                print(f"      → Overallotment: {'Exercised' if data['overallotment_exercised'] else 'Not exercised'}")
                            if data.get('sponsor_shares_issued'):
                                print(f"      → Sponsor shares: {data['sponsor_shares_issued']:,}")
                            if data.get('trust_cash'):
                                print(f"      → Trust cash: ${data['trust_cash']:,}")

                except Exception as e:
                    print(f"   ⚠️  AI extraction from 8-K body failed: {e}")

            return data

        except Exception as e:
            print(f"   ❌ Error extracting from 8-K body: {e}")
            return data

    def extract_ipo_from_10q(self, url: str) -> Dict:
        """Extract IPO data from 10-Q Note 1 (Organization and Business Description)"""
        data = {}
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()

            # Find Note 1 section
            note1_patterns = [
                r'NOTE 1[\.\s\-]+(?:DESCRIPTION OF )?ORGANIZATION',
                r'1[\.\s]+ORGANIZATION AND BUSINESS',
                r'NOTE 1[\.\s\-]+BUSINESS OPERATIONS'
            ]

            note1_start = -1
            for pattern in note1_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    note1_start = match.start()
                    break

            if note1_start < 0:
                return data

            # Extract a reasonable chunk of Note 1 (typically 3000-5000 chars)
            note1_text = text[note1_start:note1_start + 5000]

            # Use AI to extract structured IPO data from Note 1
            if AI_AVAILABLE:
                print(f"   🤖 Extracting IPO data from 10-Q Note 1...")

                prompt = f"""Extract the IPO information from this 10-Q Note 1:

{note1_text[:4000]}

Return ONLY a JSON object with these fields (use null if not found):
{{
  "ipo_date": "YYYY-MM-DD",
  "ipo_proceeds": "$XXM",
  "unit_ticker": "TICKER",
  "shares_sold": number
}}

Look for phrases like "consummated the Initial Public Offering", "generating gross proceeds", etc."""

                try:
                    response_ai = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1
                    )

                    result_text = response_ai.choices[0].message.content.strip()

                    # Extract JSON from response
                    json_match = re.search(r'\{[^{}]*\}', result_text, re.DOTALL)
                    if json_match:
                        import json
                        ai_data = json.loads(json_match.group(0))

                        # Process extracted data
                        if ai_data.get('ipo_date'):
                            data['ipo_date'] = ai_data['ipo_date']
                        if ai_data.get('ipo_proceeds'):
                            data['ipo_proceeds'] = ai_data['ipo_proceeds']
                        if ai_data.get('unit_ticker'):
                            data['unit_ticker'] = ai_data['unit_ticker']

                        extracted_count = sum(1 for v in data.values() if v)
                        if extracted_count > 0:
                            print(f"   ✓ Extracted {extracted_count} IPO fields from 10-Q Note 1")

                except Exception as e:
                    print(f"   ⚠️  AI extraction from 10-Q failed: {e}")

            return data

        except Exception as e:
            print(f"   ❌ Error extracting from 10-Q: {e}")
            return data

    def _extract_from_same_period(self, text: str) -> tuple:
        """Extract trust cash and shares from the SAME (most recent) period"""
        try:
            lines = text.split('\n')
            trust_cash = None
            shares_outstanding = None

            # Find trust account line and extract FIRST number (current period)
            for i, line in enumerate(lines):
                line_lower = line.lower()

                # Look for trust account cash line
                if ('trust account' in line_lower or 'trust acct' in line_lower) and \
                   ('cash' in line_lower or 'investment' in line_lower or 'asset' in line_lower):
                    # Extract first number after this line (within next 5 lines for table structure)
                    for j in range(i, min(i+5, len(lines))):
                        # Match numbers in this line (looking for first substantial number)
                        numbers = re.findall(r'\$?\s*([0-9]{1,3}(?:,[0-9]{3})+|\d+)', lines[j])
                        if numbers:
                            # Take the first number that looks like a dollar amount (6+ digits or has commas)
                            for num in numbers:
                                cleaned = num.replace(',', '')
                                if len(cleaned) >= 6:  # At least 1 million
                                    trust_cash = float(cleaned)
                                    break
                            if trust_cash:
                                break

                # Look for shares subject to redemption line
                if 'shares subject to' in line_lower and 'redemption' in line_lower and not trust_cash:
                    # This might be the line item - look for first number
                    # Pattern: "ordinary shares subject to possible redemption, XXX and YYY shares"
                    # We want XXX (first number = current period)
                    numbers_match = re.search(r'redemption[,\s]+([0-9,]+)\s+and\s+([0-9,]+)', line_lower)
                    if numbers_match:
                        # First number is current period
                        shares_outstanding = float(numbers_match.group(1).replace(',', ''))
                    else:
                        # Try simpler pattern - just first big number near "redemption"
                        numbers = re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+|\d{4,})', line)
                        if numbers:
                            shares_outstanding = float(numbers[0].replace(',', ''))

            # If shares not found yet, try alternative approach
            if not shares_outstanding:
                # Look for table row with shares subject to redemption
                pattern = r'ordinary shares subject to (?:possible )?redemption[,\s]+([0-9,]+)'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    shares_outstanding = float(match.group(1).replace(',', ''))

            return (trust_cash, shares_outstanding)

        except Exception as e:
            print(f"   Error in _extract_from_same_period: {e}")
            return (None, None)

    def _extract_trust_with_ai(self, text: str) -> Optional[Dict]:
        """Use AI to extract trust account data from balance sheet - more accurate than regex"""
        if not AI_AVAILABLE:
            return None

        try:
            # Find balance sheet section (limit to relevant portion to save tokens)
            balance_sheet_start = text.find('BALANCE SHEET')
            if balance_sheet_start == -1:
                balance_sheet_start = text.find('Balance Sheet')
            if balance_sheet_start == -1:
                balance_sheet_start = text.find('CONDENSED BALANCE SHEET')

            # Extract balance sheet section (up to 15000 chars)
            if balance_sheet_start != -1:
                balance_text = text[balance_sheet_start:balance_sheet_start + 15000]
            else:
                # If balance sheet header not found, use first 15000 chars
                balance_text = text[:15000]

            prompt = f"""Extract trust account data from this SPAC balance sheet. Return ONLY valid JSON:

CRITICAL INSTRUCTIONS:
1. Find these TWO values:
   a) Trust account assets: Look for "Cash held in Trust Account" OR "Marketable securities held in Trust Account" OR "Investments held in Trust Account" (under ASSETS section)
   b) Redemption shares: Look for "Class A ordinary shares subject to possible redemption" OR "Ordinary shares subject to possible redemption"

2. Extract the MOST RECENT period (usually first column, not the comparative period)

3. For trust_cash, use the ASSETS value (actual cash/securities in trust), NOT the liability value
   - Some balance sheets show both an asset ($56M) and liability ($48M) - use the ASSET value

4. Extract share count from the redemption shares line (e.g., "5,595,000 shares subject to possible redemption")

5. Sanity check: trust_cash / shares should be around $10-12 per share for most SPACs

Return JSON format:
{{
  "trust_cash": <dollar amount from trust account ASSETS>,
  "shares_outstanding": <share count from redemption shares line>
}}

Example 1 - Trust shown as asset:
"Marketable securities held in Trust Account    56,293,697"
"Ordinary shares subject to possible redemption, 5,595,000 shares    48,848,764"
Correct: {{"trust_cash": 56293697, "shares_outstanding": 5595000}}  (use ASSET value, not liability)

Example 2 - Trust shown in equity section:
"Class A ordinary shares subject to possible redemption, 2,930,233 shares issued and outstanding   30,497,934"
Correct: {{"trust_cash": 30497934, "shares_outstanding": 2930233}}

If you cannot find these values confidently, return null.

Balance sheet text:
{balance_text}

JSON only:"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200
            )

            result = response.choices[0].message.content.strip()
            # Remove markdown code blocks if present
            result = re.sub(r'```json\s*|\s*```', '', result)

            import json
            ai_data = json.loads(result)

            # Validate we got both values
            if ai_data.get('trust_cash') and ai_data.get('shares_outstanding'):
                trust_cash = float(ai_data['trust_cash'])
                shares = float(ai_data['shares_outstanding'])
                print(f"   AI extracted: trust_cash=${trust_cash:,.0f}, shares={shares:,.0f}")
                return {
                    'trust_cash': trust_cash,
                    'shares_outstanding': shares
                }

            return None

        except Exception as e:
            print(f"   ⚠️  AI extraction failed: {e}")
            return None

    def _extract_trust_from_8k_closing(self, ticker: str, ipo_date: Optional[date] = None) -> Optional[Dict]:
        """
        Extract actual trust cash deposited from 8-K IPO closing announcement

        Implements overallotment-aware extraction:
        1. Find 8-K filed around IPO date
        2. Check if it's IPO closing announcement
        3. Extract actual trust cash deposited (includes overallotment if exercised)
        4. Detect if overallotment option was exercised

        Args:
            ticker: SPAC ticker symbol
            ipo_date: IPO date to search around (or datetime object)

        Returns:
            Dict with keys: trust_cash, shares_outstanding, overallotment_exercised, trust_value_per_share
            None if extraction fails
        """
        try:
            # Convert datetime to date if needed
            if isinstance(ipo_date, datetime):
                ipo_date = ipo_date.date()

            if not ipo_date:
                print(f"      ⚠️  No IPO date provided - cannot search for 8-K")
                return None

            # Get SPAC record for CIK
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac or not spac.cik:
                print(f"      ⚠️  No CIK found for {ticker}")
                return None

            cik = spac.cik.zfill(10)

            # Search for 8-K filings filed within 10 days after IPO date
            # (IPO closing 8-K is typically filed within 4 business days)
            from datetime import timedelta
            search_start = ipo_date
            search_end = ipo_date + timedelta(days=10)

            print(f"      Searching for 8-K between {search_start} and {search_end}...")

            # Fetch recent 8-Ks
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik,
                'type': '8-K',
                'dateb': search_end.strftime('%Y%m%d'),  # Search up to this date
                'owner': 'exclude',
                'count': 10  # Check last 10 8-Ks
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                print(f"      ⚠️  No 8-K filings found")
                return None

            rows = table.find_all('tr')[1:]  # Skip header
            if not rows:
                print(f"      ⚠️  No 8-K filings found")
                return None

            # Find 8-K filed around IPO date
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date_str = cols[3].get_text().strip()

                    # Parse filing date
                    from dateutil import parser as date_parser
                    try:
                        filing_date = date_parser.parse(filing_date_str).date()
                    except:
                        continue

                    # Check if filing is within our search window
                    if search_start <= filing_date <= search_end:
                        # Get document link
                        doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                        if not doc_link:
                            continue

                        filing_url = self.base_url + doc_link['href']
                        print(f"      Found 8-K filed {filing_date} - checking if it's IPO closing...")

                        # Get the filing page to find the main 8-K document
                        filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                        filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                        # Get the document table
                        doc_table = filing_soup.find('table', {'class': 'tableFile', 'summary': 'Document Format Files'})
                        if not doc_table:
                            continue

                        # Find the main 8-K HTML document
                        for doc_row in doc_table.find_all('tr')[1:]:
                            cells = doc_row.find_all('td')
                            if len(cells) >= 4:
                                doc_type = cells[3].get_text().strip()
                                link = cells[2].find('a', href=True)

                                if link and '.htm' in link['href'].lower():
                                    # Look for main document
                                    href_lower = link['href'].lower()

                                    # Check if this looks like the main 8-K document
                                    doc_type_lower = doc_type.lower()
                                    is_main = (
                                        '8-k' in href_lower or
                                        '8k' in href_lower or  # Check href too
                                        '8-k' == doc_type_lower or  # Exact match for doc type
                                        '8k' == doc_type_lower or
                                        ('htm' in doc_type_lower and 'ex' not in doc_type_lower and 'graphic' not in doc_type_lower)
                                    )

                                    if is_main:
                                        doc_url = self.base_url + link['href']

                                        # Handle iXBRL viewer URLs
                                        if '/ix?doc=' in doc_url:
                                            doc_url = self.base_url + doc_url.split('/ix?doc=')[1]

                                        # Fetch the 8-K document
                                        doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
                                        doc_html = doc_response.text

                                        # Extract text from HTML
                                        doc_soup = BeautifulSoup(doc_html, 'html.parser')

                                        # Remove script and style tags
                                        for script in doc_soup(['script', 'style']):
                                            script.decompose()

                                        text = doc_soup.get_text()

                                        # Check if this is IPO closing announcement
                                        # Look for keywords indicating IPO completion
                                        ipo_keywords = [
                                            'consummated', 'initial public offering', 'trust account', 'deposited into',
                                            'completed.*ipo', 'completed.*initial public', 'closed.*ipo',
                                            'ipo.*closed', 'ipo.*completed', 'public offering.*units'
                                        ]
                                        # Check keywords (some are regex patterns, some are literal)
                                        text_lower = text.lower()
                                        has_ipo_keywords = any(
                                            re.search(keyword.lower(), text_lower) if '.*' in keyword else keyword.lower() in text_lower
                                            for keyword in ipo_keywords
                                        )
                                        if has_ipo_keywords:
                                            print(f"      ✓ Found IPO closing 8-K - extracting trust data...")

                                            # Use managed prompt to extract trust data
                                            prompt_data = get_prompt('trust_from_8k_closing', filing_text=text[:15000])

                                            response = AI_CLIENT.chat.completions.create(
                                                model="deepseek-chat",
                                                messages=[
                                                    {"role": "system", "content": prompt_data['system_prompt']},
                                                    {"role": "user", "content": prompt_data['user_prompt']}
                                                ],
                                                temperature=0
                                            )

                                            result = response.choices[0].message.content.strip()

                                            # Clean markdown formatting if present
                                            if result.startswith('```'):
                                                result = result.split('```')[1]
                                                if result.startswith('json'):
                                                    result = result[4:]
                                                result = result.strip()

                                            ai_data = json.loads(result)

                                            # Log extraction result
                                            log_prompt_result(
                                                'trust_from_8k_closing',
                                                success=ai_data.get('trust_cash') is not None,
                                                extracted_data=ai_data,
                                                spac_ticker=ticker
                                            )

                                            # Validate we got trust cash
                                            if ai_data.get('trust_cash'):
                                                return {
                                                    'trust_cash': float(ai_data['trust_cash']),
                                                    'shares_outstanding': int(ai_data.get('shares_outstanding', 0)) if ai_data.get('shares_outstanding') else None,
                                                    'overallotment_exercised': ai_data.get('overallotment_exercised', False),
                                                    'trust_value_per_share': float(ai_data.get('trust_value_per_share', 10.0))
                                                }
                                            else:
                                                print(f"      ⚠️  AI could not extract trust cash from 8-K")

                                        break  # Only check first main document

            print(f"      ⚠️  No IPO closing 8-K found in date range")
            return None

        except Exception as e:
            print(f"      ⚠️  Error extracting trust from 8-K: {e}")
            return None

    def _extract_section(self, html: str, section_names: list) -> str:
        """Extract specific sections from S-1 HTML to reduce LLM input

        Args:
            html: Full HTML document
            section_names: List of section names to search for (e.g., ['Capitalization', 'Description of Securities'])

        Returns:
            str: Extracted section text (~20,000 chars / 5-10 pages)
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            full_text = soup.get_text()

            # Try to find section by name
            for section_name in section_names:
                # Case-insensitive search for section heading
                pattern = re.compile(rf'(?:^|\n)\s*{re.escape(section_name)}\s*(?:\n|$)', re.IGNORECASE | re.MULTILINE)
                match = pattern.search(full_text)

                if match:
                    start_idx = match.start()
                    # Extract 20,000 characters from this point (about 5-10 pages)
                    section_text = full_text[start_idx:start_idx + 20000]
                    print(f"   ℹ️  Extracted {len(section_text):,} chars from '{section_name}' section")
                    return section_text

            # If no specific section found, return first 20,000 chars
            print(f"   ⚠️  Section not found, using first 20k chars")
            return full_text[:20000]

        except Exception as e:
            print(f"   ⚠️  Section extraction error: {e}")
            return html[:20000]

    def extract_founder_shares(self, s1_html: str) -> Dict:
        """Extract founder share count from S-1 Capitalization section

        Args:
            s1_html: S-1 filing HTML content

        Returns:
            Dict with keys: founder_shares (int), confidence (float), extraction_method (str)
        """
        result = {
            'founder_shares': None,
            'confidence': 0.0,
            'extraction_method': None
        }

        try:
            # Extract relevant section
            section_text = self._extract_section(s1_html, [
                'Capitalization',
                'Capital Stock',
                'Description of Securities',
                'Summary',
                'The Offering'
            ])

            # Method 1: Try regex patterns first (free, ~70% success rate)
            regex_patterns = [
                # Pattern 1: "X founder/Class B shares"
                r'([0-9,]+)\s+(?:founder|Class B|class B)\s+(?:ordinary\s+)?shares',
                # Pattern 2: "Sponsor purchased X shares"
                r'[Ss]ponsor\s+(?:has\s+)?purchased\s+([0-9,]+)\s+(?:founder\s+)?shares',
                # Pattern 3: "X shares issued to sponsor/founders"
                r'([0-9,]+)\s+shares\s+(?:were\s+)?issued\s+to\s+(?:the\s+)?(?:sponsor|founders?)',
                # Pattern 4: "founders hold X shares"
                r'founders?\s+(?:collectively\s+)?hold\s+([0-9,]+)\s+shares',
                # Pattern 5: Non-redeemable shares count
                r'([0-9,]+)\s+(?:non-redeemable|Class\s+B)\s+ordinary\s+shares',
                # Pattern 6: From capitalization table
                r'(?:Founder|Class\s+B|Sponsor)\s+shares.*?([0-9,]+)',
            ]

            for pattern in regex_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    founder_shares = float(match.group(1).replace(',', ''))
                    # Validate: founder shares typically 2M-10M (20-25% of total)
                    if 1_000_000 <= founder_shares <= 15_000_000:
                        result['founder_shares'] = int(founder_shares)
                        result['confidence'] = 0.85
                        result['extraction_method'] = 'regex'
                        print(f"   ✓ Regex found founder shares: {int(founder_shares):,}")
                        log_data_change(
                            ticker='',
                            field='founder_shares',
                            old_value=None,
                            new_value=int(founder_shares),
                            source='sec_data_scraper.extract_founder_shares',
                            confidence='high'
                        )
                        return result

            # Method 2: AI fallback (if regex failed)
            if AI_AVAILABLE and not result['founder_shares']:
                print(f"   🤖 Using AI to extract founder shares (regex failed)...")

                prompt = f"""Extract the founder share count from this SPAC S-1 filing section.

CRITICAL INSTRUCTIONS:
1. Look for "founder shares", "Class B shares", "sponsor shares", or "non-redeemable shares"
2. These are typically 20-25% of total shares (e.g., 2-10 million shares)
3. Do NOT confuse with public shares (which are redeemable)
4. Return ONLY a JSON object

Excerpt from S-1:
{section_text[:8000]}

Return JSON format:
{{
  "founder_shares": <integer count or null>,
  "confidence": <0.0-1.0>
}}

If not found confidently, return null."""

                try:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        max_tokens=150
                    )

                    ai_result = response.choices[0].message.content.strip()
                    ai_result = re.sub(r'```json\s*|\s*```', '', ai_result)

                    import json
                    ai_data = json.loads(ai_result)

                    if ai_data.get('founder_shares'):
                        founder_shares = int(ai_data['founder_shares'])
                        confidence = float(ai_data.get('confidence', 0.7))

                        # Validate range
                        if 1_000_000 <= founder_shares <= 15_000_000:
                            result['founder_shares'] = founder_shares
                            result['confidence'] = confidence
                            result['extraction_method'] = 'ai'
                            print(f"   ✓ AI extracted: {founder_shares:,} shares (confidence: {confidence:.2f})")
                            log_data_change(
                                ticker='',
                                field='founder_shares',
                                old_value=None,
                                new_value=founder_shares,
                                source='sec_data_scraper.extract_founder_shares',
                                confidence='medium'
                            )
                            return result
                        else:
                            print(f"   ⚠️  AI result outside valid range: {founder_shares:,}")

                except Exception as e:
                    print(f"   ⚠️  AI extraction failed: {e}")

            if not result['founder_shares']:
                print(f"   ❌ Could not extract founder shares")

            return result

        except Exception as e:
            print(f"   ❌ Error in extract_founder_shares: {e}")
            return result

    def extract_warrant_terms(self, s1_html: str) -> Dict:
        """Extract warrant terms from S-1 filing

        Args:
            s1_html: S-1 filing HTML content

        Returns:
            Dict with keys: warrant_ratio (float), exercise_price (float),
                          expiration_years (int), confidence (float)
        """
        result = {
            'warrant_ratio': None,
            'exercise_price': None,
            'expiration_years': None,
            'confidence': 0.0,
            'extraction_method': None
        }

        try:
            # Extract relevant section
            section_text = self._extract_section(s1_html, [
                'Description of Securities',
                'Warrants',
                'Units',
                'The Offering',
                'Summary'
            ])

            # Method 1: Regex patterns for warrant ratio
            ratio_patterns = [
                # Pattern 1: "one-third warrant" or "1/3 warrant"
                r'(?:one[- ]third|1/3)\s+(?:of\s+one\s+)?(?:redeemable\s+)?warrant',
                # Pattern 2: "one-quarter warrant" or "1/4 warrant"
                r'(?:one[- ]quarter|1/4)\s+(?:of\s+one\s+)?(?:redeemable\s+)?warrant',
                # Pattern 3: "one-half warrant" or "1/2 warrant"
                r'(?:one[- ]half|1/2)\s+(?:of\s+one\s+)?(?:redeemable\s+)?warrant',
                # Pattern 4: "one warrant" or "1 warrant"
                r'(?:^|[\s,])(?:one|1)\s+(?:redeemable\s+)?warrant(?:s)?(?:\s|,|$)',
            ]

            ratio_map = {
                'one-third': 0.333, '1/3': 0.333,
                'one-quarter': 0.25, '1/4': 0.25,
                'one-half': 0.5, '1/2': 0.5,
                'one': 1.0, '1': 1.0
            }

            for pattern in ratio_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    # Determine ratio from matched text
                    matched_text = match.group(0).lower()
                    for key, value in ratio_map.items():
                        if key in matched_text:
                            result['warrant_ratio'] = value
                            result['confidence'] = 0.9
                            result['extraction_method'] = 'regex'
                            print(f"   ✓ Regex found warrant ratio: {value}")
                            break
                    if result['warrant_ratio']:
                        break

            # Method 2: Regex for exercise price (typically $11.50)
            exercise_patterns = [
                r'exercise\s+price\s+of\s+\$([0-9]+\.?[0-9]*)',
                r'exercisable\s+at\s+\$([0-9]+\.?[0-9]*)',
                r'warrant.*?exercise.*?\$([0-9]+\.?[0-9]*)',
            ]

            for pattern in exercise_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    exercise_price = float(match.group(1))
                    # Validate: typically $11.50 (range $10-$15)
                    if 10.0 <= exercise_price <= 15.0:
                        result['exercise_price'] = exercise_price
                        print(f"   ✓ Regex found exercise price: ${exercise_price}")
                        break

            # Method 3: Regex for expiration (typically 5 years)
            expiration_patterns = [
                r'warrants?\s+will\s+expire\s+(?:in\s+)?([0-9]+)\s+years?',
                r'([0-9]+)[- ]year\s+term',
                r'warrants?\s+expire.*?([0-9]+)\s+years?',
            ]

            for pattern in expiration_patterns:
                match = re.search(pattern, section_text, re.IGNORECASE)
                if match:
                    expiration_years = int(match.group(1))
                    # Validate: typically 5 years (range 3-7)
                    if 3 <= expiration_years <= 10:
                        result['expiration_years'] = expiration_years
                        print(f"   ✓ Regex found expiration: {expiration_years} years")
                        break

            # Method 4: AI fallback if any key data is missing
            if AI_AVAILABLE and (not result['warrant_ratio'] or not result['exercise_price']):
                print(f"   🤖 Using AI to extract warrant terms (regex incomplete)...")

                prompt = f"""Extract warrant terms from this SPAC S-1 filing section.

CRITICAL INSTRUCTIONS:
1. Warrant ratio: How many warrants per share? Common values: 0.25 (1/4), 0.333 (1/3), 0.5 (1/2), 1.0 (whole)
2. Exercise price: Typically $11.50 (range $10-$15)
3. Expiration: Typically 5 years (range 3-7 years)

Excerpt from S-1:
{section_text[:8000]}

Return ONLY JSON:
{{
  "warrant_ratio": <float like 0.333 or null>,
  "exercise_price": <float like 11.50 or null>,
  "expiration_years": <int like 5 or null>,
  "confidence": <0.0-1.0>
}}"""

                try:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        max_tokens=200
                    )

                    ai_result = response.choices[0].message.content.strip()
                    ai_result = re.sub(r'```json\s*|\s*```', '', ai_result)

                    import json
                    ai_data = json.loads(ai_result)

                    # Merge AI results (prioritize regex if already found)
                    if not result['warrant_ratio'] and ai_data.get('warrant_ratio'):
                        ratio = float(ai_data['warrant_ratio'])
                        if 0.1 <= ratio <= 1.5:  # Validate range
                            result['warrant_ratio'] = ratio
                            result['extraction_method'] = 'ai'
                            print(f"   ✓ AI extracted ratio: {ratio}")

                    if not result['exercise_price'] and ai_data.get('exercise_price'):
                        price = float(ai_data['exercise_price'])
                        if 10.0 <= price <= 15.0:
                            result['exercise_price'] = price
                            print(f"   ✓ AI extracted exercise price: ${price}")

                    if not result['expiration_years'] and ai_data.get('expiration_years'):
                        years = int(ai_data['expiration_years'])
                        if 3 <= years <= 10:
                            result['expiration_years'] = years
                            print(f"   ✓ AI extracted expiration: {years} years")

                    if ai_data.get('confidence'):
                        result['confidence'] = max(result['confidence'], float(ai_data['confidence']))

                except Exception as e:
                    print(f"   ⚠️  AI extraction failed: {e}")

            # Summary
            extracted_fields = sum([
                1 if result['warrant_ratio'] else 0,
                1 if result['exercise_price'] else 0,
                1 if result['expiration_years'] else 0
            ])

            if extracted_fields == 0:
                print(f"   ❌ Could not extract warrant terms")
            else:
                print(f"   ✓ Extracted {extracted_fields}/3 warrant fields")

            return result

        except Exception as e:
            print(f"   ❌ Error in extract_warrant_terms: {e}")
            return result

    def _extract_founder_shares(self, text: str) -> Optional[float]:
        """DEPRECATED: Use extract_founder_shares() instead
        Extract founder shares (non-redeemable shares) from MOST RECENT period"""
        try:
            lines = text.split('\n')

            for i, line in enumerate(lines):
                line_lower = line.lower()

                # Look for non-redeemable shares
                if 'non-redeemable' in line_lower or 'not subject to redemption' in line_lower:
                    # Extract first substantial number
                    numbers = re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+|\d{4,})', line)
                    if numbers:
                        return float(numbers[0].replace(',', ''))

                    # Check next line if number is on following line
                    if i + 1 < len(lines):
                        numbers = re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+|\d{4,})', lines[i+1])
                        if numbers:
                            return float(numbers[0].replace(',', ''))

            return None

        except Exception as e:
            return None

    def _check_deal_mention_in_10q(self, text: str) -> None:
        """Lightweight check for business combination mention in 10-Q/10-K (informational only)"""
        try:
            text_lower = text.lower()

            # Specific keywords that indicate a PENDING/ANNOUNCED deal (not just the SPAC's purpose)
            specific_deal_keywords = [
                'entered into a business combination agreement',
                'entered into a definitive agreement',
                'proposed business combination with',
                'pending business combination with',
                'merger agreement with',
                'announced a business combination',
                'definitive merger agreement'
            ]

            # Generic phrases that all SPACs have (filter these out)
            generic_phrases = [
                'formed for the purpose of effecting a business combination',
                'organized for the purpose of',
                'initial business combination',
                'consummate a business combination'
            ]

            # Check if there are specific deal mentions
            has_specific_deal = any(keyword in text_lower for keyword in specific_deal_keywords)

            # Make sure it's not just generic boilerplate
            is_just_generic = all(generic in text_lower for generic in generic_phrases) and not has_specific_deal

            if has_specific_deal:
                print(f"      ℹ️  10-Q/10-K confirms pending business combination")

            # Don't return anything - this is just for informational logging
            # Actual deal detection happens via 8-K filings

        except Exception as e:
            pass  # Silent fail - this is just a bonus check

    def extract_with_ai(self, text: str) -> Dict:
        """Use AI to extract structured data"""
        if not AI_AVAILABLE:
            return {}

        try:
            # Store for logging purposes
            self.last_prompt = None
            self.last_source_text = text

            prompt = f"""Extract SPAC IPO data from this press release. Return ONLY valid JSON:
- ipo_date (YYYY-MM-DD or null)
- ipo_proceeds (e.g. "$414M" or null)
- shares_outstanding (public shares sold in IPO, e.g. 30000000 or null)
- unit_ticker (e.g. "CCCXU" or null)
- common_ticker (e.g. "CCCX" or null)
- warrant_ticker (e.g. "CCCXW" or null, if units include warrants)
- right_ticker (e.g. "CCCXR" or null, if units include rights instead of warrants)
- unit_structure (e.g. "1 share + 1/4 warrant" or "1 share + 1 right" or null)
- banker (ONLY the LEAD/FIRST banker listed, e.g. "BTIG, LLC" or null)
- co_bankers (comma-separated list of OTHER co-managers/underwriters AFTER the lead, e.g. "Cantor Fitzgerald, EarlyBirdCapital" or null)

Look for phrases like:
- "sold X,XXX,XXX units" (this is shares_outstanding)
- "offering of X million units"
- "X,XXX,XXX public units"
- "X units at $10.00 per unit"

Text:
{text[:6000]}

JSON only:"""

            # Store for enhanced logging
            self.last_prompt = prompt

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=500
            )

            result = response.choices[0].message.content.strip()
            result = re.sub(r'```json\s*|\s*```', '', result)

            import json
            return json.loads(result)

        except Exception as e:
            print(f"   AI failed: {e}")
            return {}

    def _extract_deadline_with_ai(self, text: str) -> Optional[int]:
        """Use AI to extract deadline months from prospectus when regex fails"""
        if not AI_AVAILABLE:
            return None

        try:
            prompt = f"""Extract the business combination deadline from this SPAC prospectus.

Look for phrases like:
- "We will have [X] months from the closing"
- "within [X] months of the completion"
- "must complete a business combination within [X] months"
- "[X]-month period to complete"
- "deadline of [X] months"

Common SPAC deadlines: 15, 18, 20, 21, 24, 30, or 36 months.

Text excerpt:
{text}

Return ONLY the number of months as an integer (e.g., "24").
If not found, return "NOT_FOUND"."""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10
            )

            result = response.choices[0].message.content.strip()

            if result.isdigit():
                months = int(result)
                # Validate it's a reasonable SPAC deadline
                if months in [12, 15, 18, 20, 21, 24, 30, 36]:
                    return months

            return None
        except Exception as e:
            print(f"   AI deadline extraction error: {e}")
            return None

    def extract_from_press_release(self, url: str, ticker: str = None) -> Dict:
        """Extract data from IPO press release"""
        data = {
            'ipo_date': None,
            'ipo_proceeds': None,
            'unit_ticker': None,
            'common_ticker': None,
            'warrant_ticker': None,
            'right_ticker': None,
            'unit_structure': None,
            'banker': None,
            'co_bankers': None
        }

        ai_data = None  # Track AI result for logging

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            text = response.text

            # Try AI first
            if AI_AVAILABLE:
                print(f"   🤖 Using AI...")
                ai_data = self.extract_with_ai(text)
                if ai_data:
                    # Normalize IPO proceeds if AI returned dollar amount instead of millions
                    if ai_data.get('ipo_proceeds'):
                        proceeds_str = ai_data['ipo_proceeds']
                        # Remove $ and commas, check if it's a large number
                        cleaned = proceeds_str.replace('$', '').replace(',', '').replace('M', '')
                        try:
                            amount = float(cleaned)
                            # If amount > 1000, it's likely in dollars not millions
                            if amount > 1000:
                                ai_data['ipo_proceeds'] = f"${amount / 1_000_000:.0f}M"
                            elif not proceeds_str.endswith('M'):
                                ai_data['ipo_proceeds'] = f"${amount:.0f}M"
                        except:
                            pass

                    data.update({k: v for k, v in ai_data.items() if v})
                    ai_count = sum(1 for v in ai_data.values() if v)
                    print(f"   ✓ AI found {ai_count}/8 fields")

            # Regex fallback
            missing = [k for k, v in data.items() if not v]
            if missing:
                print(f"   📝 Regex for {len(missing)} fields...")

                # IPO Date
                if not data['ipo_date']:
                    date_match = re.search(r'([A-Z][a-z]+\s+\d{1,2},\s+\d{4})', text)
                    if date_match:
                        try:
                            data['ipo_date'] = datetime.strptime(date_match.group(1), '%B %d, %Y').strftime('%Y-%m-%d')
                        except:
                            pass

                # IPO Proceeds
                if not data['ipo_proceeds']:
                    proceeds_match = re.search(r'gross proceeds of (?:approximately )?\$([0-9,\.]+)\s*(?:million)?', text, re.IGNORECASE)
                    if proceeds_match:
                        amount = float(proceeds_match.group(1).replace(',', ''))
                        # If amount > 1000, it's likely in dollars not millions
                        if amount > 1000:
                            data['ipo_proceeds'] = f"${amount / 1_000_000:.0f}M"
                        else:
                            data['ipo_proceeds'] = f"${amount:.0f}M"

                # Unit Structure
                if not data['unit_structure']:
                    struct_match = re.search(
                        r'Each unit consists of one.*?and (one-quarter|one-half|one-third|one) of one redeemable warrant',
                        text, re.IGNORECASE
                    )
                    if struct_match:
                        ratio_map = {'one-quarter': '1/4', 'one-half': '1/2', 'one-third': '1/3', 'one': '1'}
                        ratio = ratio_map.get(struct_match.group(1).lower(), '1')
                        data['unit_structure'] = f"1 share + {ratio} warrant"

                # Tickers
                if not data['unit_ticker']:
                    unit_match = re.search(r'ticker symbol ["\']([A-Z]+U)["\']', text)
                    if unit_match:
                        data['unit_ticker'] = unit_match.group(1)

                if not data['common_ticker'] or not data['warrant_ticker']:
                    symbols_match = re.search(r'symbols ["\']([A-Z]+)["\'] and ["\']([A-Z]+W)["\']', text)
                    if symbols_match:
                        data['common_ticker'] = symbols_match.group(1)
                        data['warrant_ticker'] = symbols_match.group(2)

                # Right ticker (if units include rights instead of warrants)
                if not data['right_ticker']:
                    # Pattern 1: symbols "TICKER" and "TICKERR"
                    right_symbols_match = re.search(r'symbols ["\']([A-Z]+)["\'] and ["\']([A-Z]+R)["\']', text)
                    if right_symbols_match:
                        data['right_ticker'] = right_symbols_match.group(2)
                    else:
                        # Pattern 2: listed under "TICKERR" or similar mentions
                        right_ticker_match = re.search(r'rights.*?ticker.*?["\']([A-Z]+R)["\']', text, re.IGNORECASE)
                        if right_ticker_match:
                            data['right_ticker'] = right_ticker_match.group(1)

                # Banker (lead and co-managers)
                if not data['banker']:
                    # Pattern 1: "Banker1 and Banker2 acted as joint book-running managers"
                    multi_banker_pattern = r'([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities))(?:,\s+([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities)))*?\s+and\s+([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities))\s+(?:acted|are acting)\s+as\s+(?:joint\s+)?book-running'
                    match = re.search(multi_banker_pattern, text[:8000], re.IGNORECASE)
                    if match:
                        # First banker is lead
                        data['banker'] = match.group(1).strip()
                        # Collect remaining bankers
                        co_bankers = []
                        if match.group(2):
                            co_bankers.append(match.group(2).strip())
                        if match.group(3):
                            co_bankers.append(match.group(3).strip())
                        if co_bankers:
                            data['co_bankers'] = ', '.join(co_bankers)
                    else:
                        # Pattern 2: Single lead banker
                        single_pattern = r'([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities))\s+acted\s+as.*?book.*?manager'
                        match = re.search(single_pattern, text[:8000], re.IGNORECASE)
                        if match:
                            data['banker'] = match.group(1).strip()

            total = sum(1 for v in data.values() if v)
            print(f"   ✓ Extracted {total}/9 fields")

            # Log extraction results (enhanced with prompt & source text for training)
            if ticker:
                self.logger.log_extraction(
                    ticker=ticker,
                    extraction_type='ipo_press_release',
                    prompt=getattr(self, 'last_prompt', ''),
                    source_text=getattr(self, 'last_source_text', text),
                    ai_result=ai_data if ai_data else {},
                    final_result=data,
                    filing_url=url,
                    error=None
                )

            return data

        except Exception as e:
            print(f"Error: {e}")

            # Log failed extraction (with error details for debugging)
            if ticker:
                self.logger.log_extraction(
                    ticker=ticker,
                    extraction_type='ipo_press_release',
                    prompt=getattr(self, 'last_prompt', ''),
                    source_text=getattr(self, 'last_source_text', ''),
                    ai_result=ai_data if ai_data else {},
                    final_result=data,
                    filing_url=url,
                    error=str(e)
                )

            return data

    def extract_from_prospectus(self, url: str, ticker: str = None) -> Dict:
        """Extract IPO data and deadline from prospectus (424B4)"""
        data = {
            'deadline_months': None,
            'ipo_date': None,
            'ipo_proceeds': None,
            'unit_ticker': None,
            'warrant_ticker': None,
            'unit_structure': None,
            'banker': None,
            'co_bankers': None
        }

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            text = response.text

            # Extract deadline months - try multiple patterns
            deadline_patterns = [
                r'We will have (\d+) months from the closing',
                r'(\d+) months from the closing of this offering',
                r'within (\d+) months of the completion of',
                r'must complete.*?business combination within (\d+) months',
                r'(\d+)-month period to complete.*?business combination',
                r'deadline to consummate.*?is (\d+) months',
                r'initial business combination within (\d+) months',
                r'(\d+) months? from the date of the prospectus',
                r'by.*?(\d+) months after.*?IPO',
                # Handle spelled out numbers
                r'(eighteen|twenty|twenty-one|twenty-four|thirty|thirty-six) months'
            ]

            deadline_months = None
            matched_pattern = None

            for pattern in deadline_patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    month_str = match.group(1)
                    # Convert spelled numbers to digits
                    word_to_num = {
                        'eighteen': 18, 'twenty': 20, 'twenty-one': 21,
                        'twenty-four': 24, 'thirty': 30, 'thirty-six': 36
                    }
                    deadline_months = word_to_num.get(month_str.lower(), int(month_str) if month_str.isdigit() else None)
                    if deadline_months:
                        data['deadline_months'] = deadline_months
                        matched_pattern = pattern[:50]
                        print(f"   ✓ Deadline: {deadline_months} months (pattern matched)")
                        break

            # If no pattern matched, try AI fallback
            if not deadline_months and AI_AVAILABLE:
                print(f"   🤖 Using AI to extract deadline (regex failed)...")
                ai_deadline = self._extract_deadline_with_ai(text[:10000])
                if ai_deadline:
                    data['deadline_months'] = ai_deadline
                    print(f"   ✓ Deadline: {ai_deadline} months (AI extracted)")

            # Extract banker/underwriter (try regex first)
            # Pattern 1: Advisory engagement (often in 424B4 underwriting section)
            # Example: "we have engaged Santander US Capital Markets LLC to provide advisory services"
            advisory_pattern = r'we have engaged\s+([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities|Capital Markets))\s+to provide advisory services'
            match = re.search(advisory_pattern, text[:50000], re.IGNORECASE)
            if match:
                data['banker'] = match.group(1).strip()
                print(f"   ✓ Banker (advisory): {data['banker']}")

            # Pattern 2: Underwriting discounts section
            # Example: "In addition to the underwriting discounts and commissions, we have engaged Goldman Sachs..."
            if not data['banker']:
                underwriting_pattern = r'(?:underwriting discounts and commissions|In addition to.*?underwriting).*?we have engaged\s+([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities|Capital Markets))'
                match = re.search(underwriting_pattern, text[:50000], re.IGNORECASE | re.DOTALL)
                if match:
                    data['banker'] = match.group(1).strip()
                    print(f"   ✓ Banker (underwriting section): {data['banker']}")

            # Pattern 3: Standard "acted as" pattern (same as press release extraction)
            if not data['banker']:
                acted_pattern = r'([A-Z][A-Za-z\s&,\.]+(?:LLC|Inc\.|Securities))\s+(?:acted|are acting)\s+as.*?book.*?manager'
                match = re.search(acted_pattern, text[:50000], re.IGNORECASE)
                if match:
                    data['banker'] = match.group(1).strip()
                    print(f"   ✓ Banker (book-running): {data['banker']}")

            # Try to extract IPO data using AI if available
            if AI_AVAILABLE and ticker:
                print(f"   🤖 Using AI to extract IPO data from prospectus...")

                # Get a relevant snippet (prospectus cover page usually has the data)
                soup = BeautifulSoup(text, 'html.parser')

                # Try to find the prospectus summary or cover page
                snippet = text[:50000]  # First 50K chars usually have cover page

                try:
                    ai_data = self.extract_with_ai(snippet)
                    if ai_data:
                        # Merge AI extracted data
                        for key in ['ipo_date', 'ipo_proceeds', 'unit_ticker', 'warrant_ticker', 'unit_structure', 'banker', 'co_bankers']:
                            if ai_data.get(key):
                                data[key] = ai_data[key]

                        extracted_count = sum(1 for v in [data.get('ipo_date'), data.get('ipo_proceeds'),
                                                          data.get('unit_ticker'), data.get('warrant_ticker'),
                                                          data.get('banker')] if v)
                        if extracted_count > 0:
                            print(f"   ✓ AI extracted {extracted_count} fields from prospectus")

                except Exception as e:
                    print(f"   ⚠️  AI extraction failed: {e}")

            return data

        except Exception as e:
            print(f"   ❌ Error extracting from prospectus: {e}")
            return data

    def extract_from_s4(self, url: str) -> Dict:
        """
        Extract deal terms from S-4 merger registration statement

        S-4 contains definitive deal terms filed 30-60 days after announcement:
        - Deal value (equity vs enterprise value)
        - Minimum cash condition
        - PIPE financing details
        - Updated target information

        Data precedence: S-4 > 8-K (S-4 is more recent and authoritative)
        """
        data = {
            'deal_value': None,
            'min_cash': None,
            'pipe_size': None,
            'target': None,  # May refine target company name
            's4_filing_url': url
        }

        if not AI_AVAILABLE:
            print("   ⚠️  AI not available, skipping S-4 extraction")
            return data

        try:
            print(f"   📄 Fetching S-4 from: {url}")
            response = requests.get(url, headers=self.headers, timeout=30)
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            full_text = soup.get_text()

            # S-4 is typically very large (500K+ tokens), extract relevant sections
            # Key sections: "Transaction Structure", "Closing Conditions", "PIPE Financing"

            # Extract deal value
            print(f"   🤖 Extracting deal value from S-4...")
            deal_value_prompt = """
From this S-4 merger registration statement, extract the transaction valuation:

Look for sections like:
- "Transaction Structure"
- "The Business Combination"
- "Summary of the Transaction"
- "Merger Consideration"

Extract:
1. **deal_value**: Enterprise value or equity value (e.g., "$1.5B", "$500M")
   - Look for phrases like "enterprise value of", "equity value of", "transaction values the company at"
   - Prefer enterprise value over equity value if both are mentioned

Return JSON format:
{
    "deal_value": "$1.5B"
}

If not found, return null.
"""

            try:
                # Search for "Transaction" or "Business Combination" section (first 100K chars)
                transaction_section = full_text[:100000]

                # Find transaction structure section
                trans_idx = transaction_section.lower().find('transaction structure')
                if trans_idx == -1:
                    trans_idx = transaction_section.lower().find('business combination')
                if trans_idx == -1:
                    trans_idx = transaction_section.lower().find('merger consideration')

                if trans_idx != -1:
                    # Extract 15K chars from that section
                    section_text = transaction_section[trans_idx:trans_idx+15000]

                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": deal_value_prompt + "\n\n" + section_text}
                        ],
                        response_format={"type": "json_object"}
                    )
                    value_data = json.loads(response.choices[0].message.content)
                    if value_data.get('deal_value'):
                        data['deal_value'] = value_data['deal_value']
                        print(f"   ✓ Deal value: {data['deal_value']}")
            except Exception as e:
                print(f"   ⚠️  Deal value extraction failed: {e}")

            # Extract minimum cash condition
            print(f"   🤖 Extracting minimum cash condition...")
            min_cash_prompt = """
From this S-4, extract the minimum cash condition required for closing:

Look for sections like:
- "Closing Conditions"
- "Conditions to Closing"
- "Conditions Precedent"

Extract:
1. **min_cash**: Minimum cash balance required in trust at closing (e.g., "$50M", "$100M")
   - Look for "minimum cash condition", "minimum available cash", "minimum cash balance"

Return JSON format:
{
    "min_cash": "$50M"
}

If not found, return null.
"""

            try:
                # Search for closing conditions (scan first 150K chars)
                conditions_text = full_text[:150000]

                closing_idx = conditions_text.lower().find('closing condition')
                if closing_idx == -1:
                    closing_idx = conditions_text.lower().find('conditions to closing')
                if closing_idx == -1:
                    closing_idx = conditions_text.lower().find('conditions precedent')

                if closing_idx != -1:
                    section_text = conditions_text[closing_idx:closing_idx+10000]

                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": min_cash_prompt + "\n\n" + section_text}
                        ],
                        response_format={"type": "json_object"}
                    )
                    cash_data = json.loads(response.choices[0].message.content)
                    if cash_data.get('min_cash'):
                        data['min_cash'] = cash_data['min_cash']
                        print(f"   ✓ Min cash: {data['min_cash']}")
            except Exception as e:
                print(f"   ⚠️  Min cash extraction failed: {e}")

            # Extract PIPE financing
            print(f"   🤖 Extracting PIPE financing...")
            pipe_prompt = """
From this S-4, extract PIPE (Private Investment in Public Equity) financing details:

Look for sections like:
- "PIPE Financing"
- "Private Placement"
- "Committed Financing"

Extract:
1. **pipe_size**: Total PIPE financing amount (e.g., "$100M", "$250M")
   - Look for "PIPE financing of", "private placement of", "committed equity financing"

Return JSON format:
{
    "pipe_size": "$100M"
}

If not found, return null.
"""

            try:
                # Search for PIPE section
                pipe_text = full_text[:150000]

                pipe_idx = pipe_text.lower().find('pipe financing')
                if pipe_idx == -1:
                    pipe_idx = pipe_text.lower().find('private placement')
                if pipe_idx == -1:
                    pipe_idx = pipe_text.lower().find('committed financing')

                if pipe_idx != -1:
                    section_text = pipe_text[pipe_idx:pipe_idx+8000]

                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": pipe_prompt + "\n\n" + section_text}
                        ],
                        response_format={"type": "json_object"}
                    )
                    pipe_data = json.loads(response.choices[0].message.content)
                    if pipe_data.get('pipe_size'):
                        data['pipe_size'] = pipe_data['pipe_size']
                        print(f"   ✓ PIPE size: {data['pipe_size']}")
            except Exception as e:
                print(f"   ⚠️  PIPE extraction failed: {e}")

            return data

        except Exception as e:
            print(f"   ❌ Error extracting from S-4: {e}")
            return data

    def get_8k_item_503_filings(self, cik: str, after_date: Optional[date] = None) -> list:
        """
        Get all 8-K Item 5.03 filings (deadline extensions)

        Item 5.03 = "Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year"
        Filed when SPAC extends deadline

        Returns list of {date, url} for each extension filing
        """
        try:
            cik_padded = cik.zfill(10)
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik_padded,
                'type': '8-K',
                'dateb': '',
                'owner': 'exclude',
                'count': 100  # Check up to 100 8-Ks
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return []

            extension_filings = []

            # Iterate through all 8-K filings
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date_str = cols[3].text.strip()
                    filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d').date()

                    # Skip if before after_date
                    if after_date and filing_date < after_date:
                        continue

                    # Get documents link
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']

                        # Fetch the filing index page
                        time.sleep(0.15)  # Rate limiting
                        filing_page = requests.get(filing_url, headers=self.headers, timeout=30)
                        filing_soup = BeautifulSoup(filing_page.text, 'html.parser')

                        # Look for the main 8-K document (not exhibits)
                        for link in filing_soup.find_all('a', href=True):
                            href = link['href']
                            if '.htm' in href and 'd8k' in href.lower():
                                doc_url = self.base_url + href

                                # Fetch the document and check for Item 5.03
                                time.sleep(0.15)
                                doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
                                doc_text = doc_response.text.lower()

                                # Check if this is an Item 5.03 filing
                                if 'item 5.03' in doc_text or 'item 5.3' in doc_text:
                                    extension_filings.append({
                                        'date': filing_date,
                                        'url': doc_url
                                    })
                                    print(f"   ✓ Found Item 5.03 filing on {filing_date}")
                                    break  # Move to next 8-K

            return extension_filings

        except Exception as e:
            print(f"   ⚠️  Error finding Item 5.03 filings: {e}")
            return []

    def extract_extension_from_8k(self, url: str) -> Dict:
        """
        Extract deadline extension details from 8-K Item 5.03

        Returns:
            {
                'new_deadline': date,
                'extension_months': int,
                'deposit_per_share': float,
                'total_deposit': float,
                'shares_redeemed': int (bonus if mentioned)
            }
        """
        data = {
            'new_deadline': None,
            'extension_months': None,
            'deposit_per_share': None,
            'total_deposit': None,
            'shares_redeemed': None
        }

        if not AI_AVAILABLE:
            print("   ⚠️  AI not available, skipping extension extraction")
            return data

        try:
            print(f"   📄 Extracting extension from: {url}")
            response = requests.get(url, headers=self.headers, timeout=30)
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            full_text = soup.get_text()

            # Look for Item 5.03 section
            item_503_idx = full_text.lower().find('item 5.03')
            if item_503_idx == -1:
                item_503_idx = full_text.lower().find('item 5.3')

            if item_503_idx == -1:
                print("   ⚠️  Item 5.03 not found in document")
                return data

            # Extract relevant section (Item 5.03 + next 5000 chars)
            section_text = full_text[item_503_idx:item_503_idx+5000]

            # AI extraction
            prompt = """
Extract deadline extension details from this 8-K Item 5.03 filing:

Look for:
1. New deadline/termination date (phrases: "extended the date", "new termination date", "until [DATE]")
2. Number of months extended (3, 6, 9, or 12 months)
3. Deposit paid by sponsor (e.g., "$0.03 per share" or "aggregate of $X")
4. Shares redeemed (if mentioned)

Return JSON format:
{
    "new_deadline": "YYYY-MM-DD",
    "extension_months": 6,
    "deposit_per_share": 0.03,
    "total_deposit": 500000,
    "shares_redeemed": 1250000
}

If any field is not found, return null for that field.
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a SEC filing extraction expert. Extract deadline extension data from 8-K filings."},
                    {"role": "user", "content": prompt + "\n\n" + section_text}
                ],
                response_format={"type": "json_object"}
            )

            extension_data = json.loads(response.choices[0].message.content)

            # Parse new_deadline
            if extension_data.get('new_deadline'):
                try:
                    data['new_deadline'] = datetime.strptime(extension_data['new_deadline'], '%Y-%m-%d').date()
                    print(f"   ✓ New deadline: {data['new_deadline']}")
                except:
                    print(f"   ⚠️  Could not parse deadline: {extension_data.get('new_deadline')}")

            # Extension months
            if extension_data.get('extension_months'):
                data['extension_months'] = extension_data['extension_months']
                print(f"   ✓ Extended by: {data['extension_months']} months")

            # Deposit per share
            if extension_data.get('deposit_per_share'):
                data['deposit_per_share'] = float(extension_data['deposit_per_share'])
                print(f"   ✓ Deposit: ${data['deposit_per_share']}/share")

            # Total deposit
            if extension_data.get('total_deposit'):
                data['total_deposit'] = float(extension_data['total_deposit'])
                print(f"   ✓ Total deposit: ${data['total_deposit']:,.0f}")

            # Shares redeemed (bonus)
            if extension_data.get('shares_redeemed'):
                data['shares_redeemed'] = int(extension_data['shares_redeemed'])
                print(f"   ✓ Shares redeemed: {data['shares_redeemed']:,}")

            return data

        except Exception as e:
            print(f"   ❌ Error extracting extension: {e}")
            return data

    def check_for_deadline_extensions(self, cik: str, original_deadline: date, ticker: str = None) -> Dict:
        """
        Check for deadline extensions by monitoring 8-K Item 5.03 filings

        Returns:
            {
                'current_deadline': date,
                'extension_count': int,
                'extension_history': [
                    {
                        'date': date,
                        'new_deadline': date,
                        'extension_months': int,
                        'filing_url': str,
                        'deposit_per_share': float
                    }
                ]
            }
        """
        result = {
            'current_deadline': original_deadline,
            'extension_count': 0,
            'extension_history': []
        }

        try:
            print(f"\n🔍 Checking for deadline extensions...")
            print(f"   Original deadline: {original_deadline}")

            # Get all Item 5.03 filings (extensions)
            extension_filings = self.get_8k_item_503_filings(cik)

            if not extension_filings:
                print(f"   ℹ️  No Item 5.03 filings found - no extensions")
                return result

            print(f"   ✓ Found {len(extension_filings)} Item 5.03 filing(s)")

            # Extract details from each extension
            for filing in extension_filings:
                time.sleep(0.15)  # Rate limiting
                extension_data = self.extract_extension_from_8k(filing['url'])

                if extension_data.get('new_deadline'):
                    result['extension_history'].append({
                        'date': filing['date'],
                        'new_deadline': extension_data['new_deadline'],
                        'extension_months': extension_data.get('extension_months'),
                        'filing_url': filing['url'],
                        'deposit_per_share': extension_data.get('deposit_per_share'),
                        'total_deposit': extension_data.get('total_deposit'),
                        'shares_redeemed': extension_data.get('shares_redeemed')
                    })

            # Sort by date
            result['extension_history'].sort(key=lambda x: x['date'])

            # Update current deadline to most recent extension
            if result['extension_history']:
                result['current_deadline'] = result['extension_history'][-1]['new_deadline']
                result['extension_count'] = len(result['extension_history'])

                print(f"\n   ✓ {result['extension_count']} extension(s) detected")
                print(f"   Original deadline: {original_deadline}")
                print(f"   Current deadline:  {result['current_deadline']}")
                for i, ext in enumerate(result['extension_history'], 1):
                    print(f"   Extension {i}: {ext['date']} → {ext['new_deadline']} ({ext.get('extension_months')}mo)")

            return result

        except Exception as e:
            print(f"   ❌ Error checking extensions: {e}")
            return result

    def extract_424b4_enhanced(self, url: str, ticker: str = None) -> Dict:
        """
        Enhanced 424B4 extraction with targeted sections and AI
        Extracts: overallotment, extensions, warrant terms, management, sponsor economics
        Uses Filing424B4Extractor for 91.7% token reduction

        Args:
            url: URL to 424B4 filing
            ticker: SPAC ticker (needed for calculated fields)
        """
        data = {
            # Overallotment (8 fields - added trust_value_per_share_with_overallotment)
            'overallotment_units': None,
            'overallotment_percentage': None,
            'overallotment_days': None,
            'overallotment_exercised': None,
            'shares_outstanding_base': None,
            'shares_outstanding_with_overallotment': None,
            'overallotment_finalized_date': None,
            'trust_value_per_share_with_overallotment': None,  # Trust cash per share when overallotment exercised
            # Extension terms (7 fields)
            'extension_available': None,
            'extension_months_available': None,
            'extension_requires_loi': None,
            'extension_requires_vote': None,
            'extension_deposit_per_share': None,
            'extension_automatic': None,
            'max_deadline_with_extensions': None,
            # Enhanced warrant terms (7 fields) - ALL from 424B4 (not S-1)
            'warrant_ratio': None,
            'warrant_exercise_price': None,
            'warrant_expiration_years': None,
            'warrant_expiration_trigger': None,
            'warrant_cashless_exercise': None,
            'warrant_redemption_price': None,
            'warrant_redemption_days': None,
            # Management team (3 fields)
            'management_team': None,
            'management_summary': None,
            'key_executives': None,
            # Sponsor name
            'sponsor': None,
            # Sponsor economics (5 fields)
            'founder_shares_cost': None,
            'private_placement_units': None,
            'private_placement_cost': None,
            'sponsor_total_at_risk': None,
            'sponsor_at_risk_percentage': None,
            # Metadata
            'prospectus_424b4_url': url
        }

        if not AI_AVAILABLE:
            print("   ⚠️  AI not available, skipping enhanced 424B4 extraction")
            return data

        try:
            print(f"   📄 Fetching 424B4 from: {url}")
            response = requests.get(url, headers=self.headers, timeout=30)
            html_content = response.text

            # Use Filing424B4Extractor for targeted extraction
            extractor = Filing424B4Extractor(html_content)
            targeted_text = extractor.get_targeted_extraction()

            # Also get individual sections for specific extractions
            offering_section = extractor.extract_the_offering_section()
            cover_page = extractor.extract_cover_page()
            description_of_securities = extractor.extract_description_of_securities_section()

            # Extract overallotment terms
            print(f"   🤖 Extracting overallotment terms...")
            overallotment_prompt = """
From this 424B4 prospectus section, extract the overallotment (green shoe) option details:

1. **shares_outstanding_base**: Base offering size in units (before overallotment). Look on cover page for "36,000,000 Units" or similar.
2. **overallotment_units**: How many additional units can be purchased? (e.g., 5,400,000)
3. **overallotment_percentage**: What percentage of base offering? (typically 15%)
4. **overallotment_days**: How many days do underwriters have to exercise? (typically 45)

Look for phrases like:
- Cover page: "36,000,000 Units" or "$360,000,000" divided by $10
- "granted the underwriters a 45-day option to purchase up to an additional"
- "option to purchase up to 5,400,000 additional units"
- "15% over-allotment option"

Return JSON format:
{
    "shares_outstanding_base": 36000000,
    "overallotment_units": 5400000,
    "overallotment_percentage": 15.0,
    "overallotment_days": 45
}

If not found, return null for that field.
"""
            try:
                # Use cover page + offering section for overallotment terms
                overallotment_text = cover_page + "\n\n" + offering_section
                response = AI_CLIENT.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                        {"role": "user", "content": overallotment_prompt + "\n\n" + overallotment_text}
                    ],
                    response_format={"type": "json_object"}
                )
                import json
                overallotment_data = json.loads(response.choices[0].message.content)
                for key in ['shares_outstanding_base', 'overallotment_units', 'overallotment_percentage', 'overallotment_days']:
                    if key in overallotment_data:
                        data[key] = overallotment_data[key]

                # Calculate shares_outstanding_with_overallotment if we have base + overallotment
                if data.get('shares_outstanding_base') and data.get('overallotment_units'):
                    data['shares_outstanding_with_overallotment'] = data['shares_outstanding_base'] + data['overallotment_units']

                print(f"   ✓ Overallotment: {data['overallotment_units']} units ({data['overallotment_percentage']}%), Base: {data.get('shares_outstanding_base', 'N/A')}")
            except Exception as e:
                print(f"   ⚠️  Overallotment extraction failed: {e}")

            # Extract trust value per share (especially important when overallotment exercised)
            print(f"   🤖 Extracting trust value per share...")
            trust_value_prompt = get_prompt('trust_value_per_share_424b4',
                                           filing_text=cover_page + "\n\n" + offering_section)

            try:
                response = AI_CLIENT.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": trust_value_prompt['system_prompt']},
                        {"role": "user", "content": trust_value_prompt['user_prompt']}
                    ],
                    temperature=0
                )

                result = response.choices[0].message.content.strip()

                # Clean markdown formatting if present
                if result.startswith('```'):
                    result = result.split('```')[1]
                    if result.startswith('json'):
                        result = result[4:]
                    result = result.strip()

                trust_value_data = json.loads(result)

                # Log extraction result
                log_prompt_result(
                    'trust_value_per_share_424b4',
                    success=trust_value_data.get('trust_value_per_share') is not None,
                    extracted_data=trust_value_data,
                    spac_ticker=ticker
                )

                if trust_value_data.get('trust_value_per_share'):
                    data['trust_value_per_share_with_overallotment'] = float(trust_value_data['trust_value_per_share'])
                    print(f"   ✓ Trust value per share: ${data['trust_value_per_share_with_overallotment']:.2f}")
                else:
                    print(f"   ⚠️  Trust value per share not found - will use default $10.00")
            except Exception as e:
                print(f"   ⚠️  Trust value extraction failed: {e}")

            # Extract extension terms
            print(f"   🤖 Extracting extension terms...")
            extension_prompt = """
From this 424B4 prospectus section, extract the deadline extension terms:

1. **extension_available**: Can the SPAC extend its deadline? (true/false)
2. **extension_months_available**: How many months can be added? (e.g., 3, 6, 12)
3. **extension_requires_loi**: Does extension require a signed LOI/agreement? (true/false)
4. **extension_requires_vote**: Does extension require shareholder vote? (true/false)
5. **extension_deposit_per_share**: How much must sponsor deposit per share? (e.g., 0.03, 0.10)
6. **extension_automatic**: Is extension automatic if conditions met? (true/false)
7. **max_deadline_with_extensions**: Maximum total months including extensions? (e.g., 27, 30, 36)

Look for phrases like:
- "24 months to consummate... or 27 months if we have executed a letter of intent"
- "may extend the period of time to consummate a business combination"
- "sponsor will deposit into the trust account"
- "no redemption rights shall be offered in connection with such extension"

Return JSON format with all fields.
"""
            try:
                # Use offering section for extension terms
                response = AI_CLIENT.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                        {"role": "user", "content": extension_prompt + "\n\n" + offering_section}
                    ],
                    response_format={"type": "json_object"}
                )
                extension_data = json.loads(response.choices[0].message.content)
                for key in ['extension_available', 'extension_months_available', 'extension_requires_loi',
                           'extension_requires_vote', 'extension_deposit_per_share', 'extension_automatic',
                           'max_deadline_with_extensions']:
                    if key in extension_data:
                        data[key] = extension_data[key]
                print(f"   ✓ Extensions: {data['extension_months_available']} months available, max {data['max_deadline_with_extensions']} months")
            except Exception as e:
                print(f"   ⚠️  Extension extraction failed: {e}")

            # Extract warrant terms
            # First check if this SPAC has warrants at all (vs. rights)
            # Query database to get current unit_structure if available
            has_warrants = True  # Default to trying extraction
            unit_structure_check = None

            if ticker:
                try:
                    from database import SessionLocal, SPAC
                    db = SessionLocal()
                    spac_record = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                    if spac_record and spac_record.unit_structure:
                        unit_structure_check = spac_record.unit_structure.lower()
                        if 'right' in unit_structure_check and 'warrant' not in unit_structure_check:
                            has_warrants = False
                            print(f"   ℹ️  SPAC has rights only (unit: {spac_record.unit_structure}) - skipping warrant extraction")
                        elif 'warrant' in unit_structure_check:
                            has_warrants = True
                            print(f"   ✓ SPAC has warrants (unit: {spac_record.unit_structure})")
                    db.close()
                except Exception as e:
                    print(f"   ⚠️  Could not check unit structure from DB: {e}")

            # Fallback: check cover page if DB check didn't work
            if not unit_structure_check:
                if 'right' in cover_page.lower() and 'warrant' not in cover_page.lower():
                    has_warrants = False
                    print(f"   ℹ️  Cover page indicates rights only - skipping warrant extraction")

            if has_warrants:
                print(f"   🤖 Extracting enhanced warrant terms...")
                warrant_prompt = """
From this 424B4 prospectus section, extract ALL warrant terms.

This SPAC has warrants (confirmed from cover page).

Extract these 7 fields (only if the SPAC has actual warrants, not just rights):

1. **warrant_ratio**: How many warrants per unit? (e.g., 0.5 for "one-half warrant" or "1/2 warrant", 0.333 for "one-third", 1.0 for "one whole warrant")
   - Look for: "Each Unit consists of one Class A ordinary share and one-half of one redeemable warrant"
   - Common values: 0.25 (1/4), 0.333 (1/3), 0.5 (1/2), 0.75 (3/4), 1.0 (whole warrant)

2. **warrant_exercise_price**: Price per share to exercise warrant (typically $11.50)
   - Look for: "at an exercise price of $11.50 per share" or "exercise price of $11.50"
   - Common values: $11.50, $12.00, $15.00

3. **warrant_expiration_years**: How many years until warrants expire? (typically 5)
   - Look for: "will expire five years after" or "five-year term"

4. **warrant_expiration_trigger**: What triggers expiration period? (e.g., "Business combination" or "IPO date")
   - Look for: "five years after the completion of our initial business combination"

5. **warrant_cashless_exercise**: Can warrants be exercised without cash? (true/false)
   - Look for: "cashless exercise" or "net share settlement" or "cashless basis"

6. **warrant_redemption_price**: At what stock price can company redeem warrants? (e.g., 18.00)
   - Look for: "equals or exceeds $18.00" or "$18.00 trigger price"

7. **warrant_redemption_days**: How many trading days within what period? (e.g., "20 out of 30")
   - Look for: "20 trading days within a 30-trading day period" or "any 20 trading days within 30"

Key phrases to search for:
- "Each Unit consists of" (gives warrant ratio)
- "Each warrant entitles the holder to purchase" (confirms warrants exist)
- "at an exercise price of $" (exercise price)
- "Redemption of warrants" section heading
- "equals or exceeds $18.00 per share" (redemption price)
- "20 trading days within a 30-trading day period" (redemption days)
- "warrants will expire five years after" (expiration)
- "cashless exercise" or "net exercise"

CRITICAL: DO NOT guess or assume standard values. Only extract what is EXPLICITLY stated. If not found, return null for that field.

Return JSON format with all 7 fields (null if not found):
{
    "warrant_ratio": 0.5,
    "warrant_exercise_price": 11.50,
    "warrant_expiration_years": 5,
    "warrant_expiration_trigger": "Business combination",
    "warrant_cashless_exercise": true,
    "warrant_redemption_price": 18.00,
    "warrant_redemption_days": "20 out of 30"
}
"""
                try:
                    # Use Cover + Offering + Description of Securities for warrant terms
                    # Some SPACs have warrant details in Offering, others in Description of Securities
                    warrant_text = cover_page + "\n\n" + offering_section
                    if description_of_securities:
                        warrant_text += "\n\n===== DESCRIPTION OF SECURITIES =====\n\n" + description_of_securities

                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings. DO NOT guess or assume values - only extract what is explicitly stated."},
                            {"role": "user", "content": warrant_prompt + "\n\n" + warrant_text}
                        ],
                        response_format={"type": "json_object"}
                    )
                    warrant_data = json.loads(response.choices[0].message.content)
                    for key in ['warrant_ratio', 'warrant_exercise_price', 'warrant_expiration_years',
                               'warrant_expiration_trigger', 'warrant_cashless_exercise',
                               'warrant_redemption_price', 'warrant_redemption_days']:
                        if key in warrant_data and warrant_data[key] is not None:
                            data[key] = warrant_data[key]

                    # Print summary of extracted warrant terms
                    extracted = []
                    if data.get('warrant_ratio'): extracted.append(f"ratio={data['warrant_ratio']}")
                    if data.get('warrant_exercise_price'): extracted.append(f"exercise=${data['warrant_exercise_price']}")
                    if data.get('warrant_redemption_price'): extracted.append(f"redeem=${data['warrant_redemption_price']}")
                    if data.get('warrant_expiration_years'): extracted.append(f"{data['warrant_expiration_years']}y")

                    if extracted:
                        print(f"   ✓ Warrants: {', '.join(extracted)}")
                    else:
                        print(f"   ⚠️  Warrant terms not found")
                except Exception as e:
                    print(f"   ⚠️  Warrant extraction failed: {e}")

            # Extract sponsor name
            print(f"   🤖 Extracting sponsor...")
            sponsor_name_prompt = """
From this prospectus summary, extract the sponsor's name.

The sponsor is the entity that formed the SPAC. Look for phrases like:
- "We were formed as a ... company by [Sponsor Name]"
- "Our sponsor is [Sponsor Name]"
- "[Sponsor Name] (the "Sponsor") purchased..."
- "Sponsor: [Sponsor Name]"

Return JSON format:
{
    "sponsor": "Klein Sponsor LLC"
}

Return just the sponsor entity name (e.g., "Churchill Sponsor LLC", "Hennessy Capital Partners", "Social Capital Suvretta Holdings Corp.").
If the sponsor is an individual, use their full name.
"""
            try:
                # Extract first 30% of document where sponsor is usually mentioned
                summary_section = extractor.extract_prospectus_summary()
                if summary_section:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": sponsor_name_prompt + "\n\n" + summary_section[:15000]}
                        ],
                        response_format={"type": "json_object"}
                    )
                    sponsor_data = json.loads(response.choices[0].message.content)
                    if 'sponsor' in sponsor_data and sponsor_data['sponsor']:
                        data['sponsor'] = sponsor_data['sponsor']
                        print(f"   ✓ Sponsor: {data['sponsor']}")
            except Exception as e:
                print(f"   ⚠️  Sponsor extraction failed: {e}")

            # Extract target sector/industry
            print(f"   🤖 Extracting target sector...")
            sector_prompt = """
From this prospectus, extract the SPAC's target sector/industry focus.

Look for sections like:
- "Business Combination Strategy"
- "Investment Criteria"
- "Target Business"
- Introduction paragraphs describing focus areas

Extract:
1. **sector**: Primary sector/industry focus (single value from list below)
2. **sector_details**: Specific subsectors or details mentioned (1-2 sentences)

Sector values (choose ONE that best fits):
- Technology
- Healthcare
- Financial Services
- Consumer
- Industrial
- Energy
- Real Estate
- Media & Entertainment
- Telecom
- General (only if truly sector-agnostic)

Return JSON format:
{
    "sector": "Technology",
    "sector_details": "Focus on enterprise software, cloud infrastructure, and fintech companies with $500M+ revenue"
}
"""
            try:
                summary_section = extractor.extract_prospectus_summary()
                if summary_section:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": sector_prompt + "\n\n" + summary_section[:15000]}
                        ],
                        response_format={"type": "json_object"}
                    )
                    sector_data = json.loads(response.choices[0].message.content)
                    if 'sector' in sector_data and sector_data['sector']:
                        data['sector'] = sector_data['sector']
                        print(f"   ✓ Sector: {data['sector']}")
                        if 'sector_details' in sector_data and sector_data['sector_details']:
                            data['sector_details'] = sector_data['sector_details']
                            print(f"   ✓ Sector details: {data['sector_details'][:60]}...")
            except Exception as e:
                print(f"   ⚠️  Sector extraction failed: {e}")

            # Extract management team
            print(f"   🤖 Extracting management team...")
            management_prompt = """
From this Management section, extract key executive information:

1. **key_executives**: List CEO, CFO, President, and other key officers with titles (comma-separated string)
2. **management_summary**: Brief 2-3 sentence summary of management team's overall experience and credentials
3. **management_team**: For each executive (CEO, CFO, President, key directors), provide:
   - Name and title
   - 1-2 sentence bio highlighting: previous companies, notable achievements, relevant SPAC experience, education

Keep each bio concise but informative. Focus on credentials most relevant to SPAC investing.

Return JSON format:
{
    "key_executives": "Michael Klein (Chairman & CEO), Steve Blechman (President & CFO)",
    "management_summary": "Led by Michael Klein, founder of M. Klein and Associates with 30+ years investment banking experience at Citigroup. Team has successfully completed 10+ prior SPACs.",
    "management_team": "Michael Klein - Chairman & CEO - Founded M. Klein and Associates, former Vice Chairman of Citigroup Investment Banking. Led Churchill Capital SPACs I-IV with successful business combinations. MBA from Harvard Business School. | Steve Blechman - President & CFO - Managing Director at M. Klein and Associates. 20+ years in investment banking and capital markets at Citigroup and UBS."
}

Separate each executive's bio with a pipe | symbol.
"""
            try:
                # Extract management section specifically
                mgmt_section = extractor.extract_management_section()
                if mgmt_section:
                    response = AI_CLIENT.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                            {"role": "user", "content": management_prompt + "\n\n" + mgmt_section}
                        ],
                        response_format={"type": "json_object"}
                    )
                    mgmt_data = json.loads(response.choices[0].message.content)
                    for key in ['key_executives', 'management_summary', 'management_team']:
                        if key in mgmt_data:
                            data[key] = mgmt_data[key]
                    print(f"   ✓ Management: {data['key_executives']}")
            except Exception as e:
                print(f"   ⚠️  Management extraction failed: {e}")

            # Extract sponsor economics
            print(f"   🤖 Extracting sponsor economics...")
            sponsor_prompt = """
From this 424B4 prospectus, extract sponsor economics data:

1. **founder_shares_cost**: How much did sponsor pay for founder shares? (typically $25,000)
2. **private_placement_units**: How many private placement units committed? (e.g., 300,000)
3. **private_placement_cost**: Total cost of private placement? (typically units × $10)

Look for phrases like:
- "Sponsor purchased 7,187,500 founder shares for an aggregate purchase price of $25,000"
- "Sponsor has agreed to purchase 300,000 units at $10.00 per unit in a private placement"
- "private placement units" or "sponsor units"

Return JSON format with all fields. Calculate sponsor_total_at_risk = founder_shares_cost + private_placement_cost.
"""
            try:
                # Use offering section for sponsor economics (contains private placement and founder shares info)
                response = AI_CLIENT.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "You are a financial document extraction expert. Extract data precisely from SEC filings."},
                        {"role": "user", "content": sponsor_prompt + "\n\n" + offering_section}
                    ],
                    response_format={"type": "json_object"}
                )
                sponsor_data = json.loads(response.choices[0].message.content)
                for key in ['founder_shares_cost', 'private_placement_units', 'private_placement_cost']:
                    if key in sponsor_data:
                        data[key] = sponsor_data[key]

                # Calculate total at risk
                if data['founder_shares_cost'] and data['private_placement_cost']:
                    data['sponsor_total_at_risk'] = data['founder_shares_cost'] + data['private_placement_cost']
                    print(f"   ✓ Sponsor at-risk: ${data['sponsor_total_at_risk']:,.0f} (${data['founder_shares_cost']:,.0f} founders + ${data['private_placement_cost']:,.0f} PIPE)")
            except Exception as e:
                print(f"   ⚠️  Sponsor economics extraction failed: {e}")

            # Post-extraction calculations
            print(f"   🧮 Calculating sponsor at-risk percentage...")

            # Calculate sponsor_at_risk_percentage
            if data['sponsor_total_at_risk'] and data.get('shares_outstanding_with_overallotment'):
                # Calculate as % of total IPO proceeds (shares × $10 per unit)
                ipo_size = data['shares_outstanding_with_overallotment'] * 10  # Assuming $10 per unit
                data['sponsor_at_risk_percentage'] = (data['sponsor_total_at_risk'] / ipo_size) * 100
                print(f"   ✓ Sponsor at-risk %: {data['sponsor_at_risk_percentage']:.2f}% of ${ipo_size:,.0f} IPO")
            elif data['sponsor_total_at_risk'] and data.get('shares_outstanding_base'):
                # Fallback to base shares if with_overallotment not available
                ipo_size = data['shares_outstanding_base'] * 10
                data['sponsor_at_risk_percentage'] = (data['sponsor_total_at_risk'] / ipo_size) * 100
                print(f"   ✓ Sponsor at-risk %: {data['sponsor_at_risk_percentage']:.2f}% of ${ipo_size:,.0f} IPO (base)")

            return data

        except Exception as e:
            print(f"   ❌ Error in enhanced 424B4 extraction: {e}")
            return data

    def save_to_database(self, ticker: str, pr_data: Dict, prosp_data: Dict, trust_data: Dict = None, deal_data: Dict = None, s1_data: Dict = None, b4_data: Dict = None, s4_data: Dict = None, s4_filing_date: str = None, tenq_filing_date: str = None, tenq_filing_type: str = None):
        """Save extracted data to database (includes 424B4 enhanced data and S-4 deal terms)"""
        try:
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ❌ {ticker} not found")
                return False

            print(f"\n   💾 Saving to database...")
            print(f"      ℹ️  Save order: S-1 → 424B4 → 8-K → S-4 → 10-Q/10-K (oldest to newest)")

            # IPO data - use press release data first, fall back to prospectus data
            ipo_date = pr_data.get('ipo_date') or prosp_data.get('ipo_date')
            if ipo_date:
                spac.ipo_date = datetime.strptime(ipo_date, '%Y-%m-%d').date()
                print(f"      ✓ ipo_date: {ipo_date}")

            ipo_proceeds = pr_data.get('ipo_proceeds') or prosp_data.get('ipo_proceeds')
            if ipo_proceeds:
                spac.ipo_proceeds = ipo_proceeds
                print(f"      ✓ ipo_proceeds: {ipo_proceeds}")

            # Shares outstanding from IPO press release (most accurate)
            shares_from_pr = pr_data.get('shares_outstanding')
            if shares_from_pr:
                try:
                    shares_float = float(shares_from_pr)
                    # Get IPO date for filing_date
                    ipo_date_obj = None
                    if ipo_date:
                        try:
                            ipo_date_obj = datetime.strptime(ipo_date, '%Y-%m-%d').date()
                        except:
                            ipo_date_obj = date.today()
                    else:
                        ipo_date_obj = date.today()

                    # Use tracker for shares_outstanding
                    update_shares_outstanding(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=shares_float,
                        source='Press Release',
                        filing_date=ipo_date_obj,
                        reason='IPO closing - shares outstanding from press release'
                    )

                    log_data_change(
                        ticker=ticker,
                        field='shares_outstanding',
                        old_value=None,
                        new_value=shares_float,
                        source='IPO Press Release',
                        confidence='high'
                    )
                except:
                    pass

            unit_ticker = pr_data.get('unit_ticker') or prosp_data.get('unit_ticker')
            if unit_ticker:
                spac.unit_ticker = unit_ticker
                print(f"      ✓ unit_ticker: {unit_ticker}")

            warrant_ticker = pr_data.get('warrant_ticker') or prosp_data.get('warrant_ticker')
            if warrant_ticker:
                spac.warrant_ticker = warrant_ticker
                print(f"      ✓ warrant_ticker: {warrant_ticker}")

            right_ticker = pr_data.get('right_ticker') or prosp_data.get('right_ticker')
            if right_ticker:
                spac.right_ticker = right_ticker
                print(f"      ✓ right_ticker: {right_ticker}")

            unit_structure = pr_data.get('unit_structure') or prosp_data.get('unit_structure')
            if unit_structure:
                spac.unit_structure = unit_structure
                print(f"      ✓ unit_structure: {unit_structure}")

            # Banker - press release (primary) or prospectus (fallback)
            banker = pr_data.get('banker') or prosp_data.get('banker')
            if banker:
                spac.banker = banker
                source = "press release" if pr_data.get('banker') else "prospectus (424B4)"
                print(f"      ✓ banker: {banker} (from {source})")

            co_bankers = pr_data.get('co_bankers') or prosp_data.get('co_bankers')
            if co_bankers:
                spac.co_bankers = co_bankers
                source = "press release" if pr_data.get('co_bankers') else "prospectus (424B4)"
                print(f"      ✓ co_bankers: {co_bankers} (from {source})")

            # Deadline data
            if prosp_data.get('deadline_months'):
                spac.deadline_months = prosp_data['deadline_months']
                print(f"      ✓ deadline_months: {prosp_data['deadline_months']}")

                if spac.ipo_date:
                    # Calculate deadline from charter
                    calculated_deadline = spac.ipo_date + relativedelta(months=prosp_data['deadline_months'])

                    # Set original deadline using tracker (ONE TIME ONLY)
                    from utils.date_trackers import set_original_deadline, update_deadline_date
                    set_original_deadline(
                        db_session=self.db,
                        ticker=ticker,
                        deadline_date=calculated_deadline,
                        source='S-1/424B4',
                        reason=f'Original deadline from IPO charter ({prosp_data["deadline_months"]} months)'
                    )

                    # Set current deadline ONLY if not already set
                    if not spac.deadline_date:
                        update_deadline_date(
                            db_session=self.db,
                            ticker=ticker,
                            new_date=calculated_deadline,
                            source='S-1/424B4',
                            reason=f'Initial deadline ({prosp_data["deadline_months"]} months from IPO)',
                            is_extension=False
                        )

            # Trust cash data - use trackers for date-based precedence
            if trust_data and tenq_filing_date:
                # Convert filing date string to date object
                try:
                    filing_date_obj = datetime.strptime(tenq_filing_date, '%Y-%m-%d').date()
                except:
                    filing_date_obj = date.today()

                # Extract quarter from filing type and date
                quarter = None
                if tenq_filing_type == '10-Q' and tenq_filing_date:
                    month = int(tenq_filing_date.split('-')[1])
                    year = tenq_filing_date.split('-')[0]
                    if month <= 3:
                        quarter = f"Q1 {year}"
                    elif month <= 6:
                        quarter = f"Q2 {year}"
                    elif month <= 9:
                        quarter = f"Q3 {year}"
                    else:
                        quarter = f"Q4 {year}"

                # Update trust_cash with tracker
                if trust_data.get('trust_cash'):
                    update_trust_cash(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=trust_data['trust_cash'],
                        source=tenq_filing_type,
                        filing_date=filing_date_obj,
                        quarter=quarter
                    )

                # Update shares_outstanding with tracker
                if trust_data.get('shares_outstanding'):
                    update_shares_outstanding(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=trust_data['shares_outstanding'],
                        source=tenq_filing_type,
                        filing_date=filing_date_obj,
                        reason=f'From {tenq_filing_type} quarterly report' + (f' ({quarter})' if quarter else '')
                    )

                # Founder shares (direct assignment OK - doesn't change)
                if trust_data.get('founder_shares'):
                    spac.founder_shares = trust_data['founder_shares']
                    print(f"      ✓ founder_shares: {trust_data['founder_shares']:,.0f}")

                # Founder ownership (calculated - direct assignment OK)
                if trust_data.get('founder_ownership'):
                    spac.founder_ownership = trust_data['founder_ownership']
                    print(f"      ✓ founder_ownership: {trust_data['founder_ownership']:.1f}%")

                # Update trust_value with tracker
                if trust_data.get('trust_value'):
                    update_trust_value(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=trust_data['trust_value'],
                        source=tenq_filing_type,
                        filing_date=filing_date_obj,
                        quarter=quarter
                    )

            # S-1 extracted data (founder shares and warrant terms)
            if s1_data:
                if s1_data.get('founder_shares'):
                    old_founder_shares = spac.founder_shares
                    spac.founder_shares = s1_data['founder_shares']
                    print(f"      ✓ founder_shares (S-1): {s1_data['founder_shares']:,}")
                    log_data_change(
                        ticker=ticker,
                        field='founder_shares',
                        old_value=old_founder_shares,
                        new_value=s1_data['founder_shares'],
                        source='S-1 filing',
                        confidence='high' if s1_data.get('founder_confidence', 0) > 0.8 else 'medium'
                    )

                # Warrant terms from S-1 (only used when NO 424B4 exists)
                # If we got here, it means no 424B4 was available, so use S-1 data directly
                if s1_data.get('warrant_ratio'):
                    # Convert warrant_ratio to string format for database (e.g., "0.333" or "1/3")
                    ratio = s1_data['warrant_ratio']
                    if ratio == 0.333:
                        ratio_str = "1/3"
                    elif ratio == 0.25:
                        ratio_str = "1/4"
                    elif ratio == 0.5:
                        ratio_str = "1/2"
                    elif ratio == 1.0:
                        ratio_str = "1"
                    else:
                        ratio_str = str(ratio)

                    spac.warrant_ratio = ratio_str
                    print(f"      ✓ warrant_ratio (S-1): {ratio_str}")

                if s1_data.get('warrant_exercise_price'):
                    spac.warrant_exercise_price = s1_data['warrant_exercise_price']
                    print(f"      ✓ warrant_exercise_price (S-1): ${s1_data['warrant_exercise_price']}")

            # Calculate founder_ownership if we have both shares and founder_shares
            if spac.shares_outstanding and spac.founder_shares and not spac.founder_ownership:
                total_shares = spac.shares_outstanding + spac.founder_shares
                spac.founder_ownership = round((spac.founder_shares / total_shares) * 100, 2)
                print(f"      ✓ founder_ownership (calculated): {spac.founder_ownership:.1f}%")

            # Deal data (only update if found - don't overwrite existing deals)
            if deal_data:
                if deal_data.get('deal_status'):
                    spac.deal_status = deal_data['deal_status']
                    print(f"      ✓ deal_status: {deal_data['deal_status']}")

                if deal_data.get('target'):
                    spac.target = deal_data['target']
                    print(f"      ✓ target: {deal_data['target']}")

                if deal_data.get('announced_date'):
                    # Convert string date to datetime.date
                    try:
                        spac.announced_date = datetime.strptime(deal_data['announced_date'], '%Y-%m-%d').date()
                        print(f"      ✓ announced_date: {deal_data['announced_date']}")
                    except:
                        pass

                if deal_data.get('deal_value'):
                    # Use date-based precedence for deal_value
                    filing_date = None
                    if deal_data.get('announced_date'):
                        try:
                            filing_date = datetime.strptime(deal_data['announced_date'], '%Y-%m-%d').date()
                        except:
                            filing_date = date.today()
                    else:
                        filing_date = date.today()

                    update_deal_value(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=deal_data['deal_value'],
                        source='8-K',
                        filing_date=filing_date,
                        reason='Initial deal announcement'
                    )

                if deal_data.get('expected_close'):
                    spac.expected_close = deal_data['expected_close']
                    print(f"      ✓ expected_close: {deal_data['expected_close']}")
            else:
                # If no deal found and deal_status not already set, mark as SEARCHING
                if not spac.deal_status:
                    spac.deal_status = 'SEARCHING'
                    print(f"      ✓ deal_status: SEARCHING (default)")

            # S-4 data (uses date-based precedence - may override 8-K if later date)
            # Precedence: Latest filing date wins (S-4 > 8-K for deal_value, min_cash, pipe_size)
            if s4_data:
                print(f"      ℹ️  Applying S-4 data")

                # Deal value from S-4 (uses date-based precedence)
                if s4_data.get('deal_value'):
                    # Convert s4_filing_date string to date object
                    s4_date = None
                    if s4_filing_date:
                        try:
                            s4_date = datetime.strptime(s4_filing_date, '%Y-%m-%d').date()
                        except:
                            s4_date = date.today()
                    else:
                        s4_date = date.today()

                    update_deal_value(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=s4_data['deal_value'],
                        source='S-4',
                        filing_date=s4_date,
                        reason='Final valuation from S-4 merger registration'
                    )

                # Minimum cash condition from S-4
                if s4_data.get('min_cash'):
                    # Convert string like "$50M" to float (50.0)
                    try:
                        min_cash_str = s4_data['min_cash']
                        # Extract number and unit (e.g., "$50M" → 50, "M")
                        import re
                        match = re.search(r'\$?([0-9.]+)\s*([MB])', min_cash_str, re.IGNORECASE)
                        if match:
                            num = float(match.group(1))
                            unit = match.group(2).upper()
                            min_cash_float = num if unit == 'M' else num * 1000
                            spac.min_cash = min_cash_float
                            print(f"      ✓ min_cash (S-4): ${min_cash_float}M")
                    except:
                        # If parsing fails, store as-is in deal_value field for manual review
                        print(f"      ⚠️  Could not parse min_cash: {s4_data['min_cash']}")

                # PIPE size from S-4
                if s4_data.get('pipe_size'):
                    try:
                        pipe_str = s4_data['pipe_size']
                        # Extract number and unit
                        import re
                        match = re.search(r'\$?([0-9.]+)\s*([MB])', pipe_str, re.IGNORECASE)
                        if match:
                            num = float(match.group(1))
                            unit = match.group(2).upper()
                            pipe_float = num if unit == 'M' else num * 1000
                            spac.pipe_size = pipe_float
                            spac.has_pipe = True
                            print(f"      ✓ pipe_size (S-4): ${pipe_float}M")
                    except:
                        print(f"      ⚠️  Could not parse pipe_size: {s4_data['pipe_size']}")

                # Store S-4 URL
                if s4_data.get('s4_filing_url'):
                    spac.s4_filing_url = s4_data['s4_filing_url']
                    print(f"      ✓ s4_filing_url stored")

                # Target name refinement from S-4 (optional - only if more specific than 8-K)
                if s4_data.get('target') and s4_data['target'] != spac.target:
                    old_target = spac.target
                    # Only update if S-4 target seems more specific (not a legal entity like "LLC")
                    if 'LLC' not in s4_data['target'] and 'Newco' not in s4_data['target']:
                        spac.target = s4_data['target']
                        print(f"      ✓ target (S-4): {s4_data['target']} (refined from: {old_target})")

            # 424B4 enhanced data (overallotment, extensions, warrants, management, sponsor economics)
            if b4_data:
                # Overallotment fields
                for field in ['overallotment_units', 'overallotment_percentage', 'overallotment_days',
                             'overallotment_exercised', 'shares_outstanding_base',
                             'shares_outstanding_with_overallotment']:
                    if b4_data.get(field) is not None:
                        setattr(spac, field, b4_data[field])
                        print(f"      ✓ {field}: {b4_data[field]}")

                # Extension fields
                for field in ['extension_available', 'extension_months_available', 'extension_requires_loi',
                             'extension_requires_vote', 'extension_deposit_per_share', 'extension_automatic',
                             'max_deadline_with_extensions']:
                    if b4_data.get(field) is not None:
                        setattr(spac, field, b4_data[field])
                        print(f"      ✓ {field}: {b4_data[field]}")

                # Enhanced warrant fields (ALL from 424B4, not S-1)
                for field in ['warrant_ratio', 'warrant_exercise_price', 'warrant_expiration_years',
                             'warrant_expiration_trigger', 'warrant_cashless_exercise',
                             'warrant_redemption_price', 'warrant_redemption_days']:
                    if b4_data.get(field) is not None:
                        setattr(spac, field, b4_data[field])
                        print(f"      ✓ {field} (424B4): {b4_data[field]}")

                # Management team fields, sponsor, and sector
                for field in ['management_team', 'management_summary', 'key_executives', 'sponsor', 'sector', 'sector_details']:
                    if b4_data.get(field):
                        setattr(spac, field, b4_data[field])
                        # Truncate for display
                        display = b4_data[field][:80] + "..." if len(b4_data[field]) > 80 else b4_data[field]
                        print(f"      ✓ {field}: {display}")

                # Sponsor economics fields
                for field in ['founder_shares_cost', 'private_placement_units', 'private_placement_cost',
                             'sponsor_total_at_risk', 'sponsor_at_risk_percentage']:
                    if b4_data.get(field) is not None:
                        setattr(spac, field, b4_data[field])
                        if 'cost' in field or 'at_risk' in field:
                            print(f"      ✓ {field}: ${b4_data[field]:,.0f}")
                        else:
                            print(f"      ✓ {field}: {b4_data[field]}")

                # Trust value per share from 424B4 (overallotment-aware)
                if b4_data.get('trust_value_per_share_with_overallotment'):
                    # Use tracker with IPO date as filing date (424B4 is filed at IPO)
                    # Tracker will respect date-based precedence (10-Q/10-K wins over 424B4)
                    filing_date_424b4 = spac.ipo_date if spac.ipo_date else date.today()

                    update_trust_value(
                        db_session=self.db,
                        ticker=ticker,
                        new_value=b4_data['trust_value_per_share_with_overallotment'],
                        source='424B4',
                        filing_date=filing_date_424b4,
                        quarter=None
                    )

                # 424B4 URL
                if b4_data.get('prospectus_424b4_url'):
                    spac.prospectus_424b4_url = b4_data['prospectus_424b4_url']
                    print(f"      ✓ prospectus_424b4_url: {b4_data['prospectus_424b4_url'][:60]}...")

            # CRITICAL CHECK: Alert if trust_value could not be found in ANY filing
            if not spac.trust_value:
                print(f"\n   ⚠️  WARNING: Could not find trust_value in 10-Q, 10-K, or 424B4 filings!")
                print(f"      This SPAC needs manual review to determine per-share NAV")

                # Send Telegram alert if configured
                try:
                    from utils.telegram_notifier import send_telegram_alert
                    alert_text = f"""⚠️ <b>MISSING TRUST VALUE</b>

<b>Ticker:</b> {ticker}
<b>Company:</b> {spac.company}

Could not extract trust_value (per-share NAV) from:
• 10-Q/10-K filings
• 424B4 prospectus

<b>Action Required:</b> Manual review needed to determine NAV
Default $10.00 was NOT applied - field left blank for accuracy"""

                    send_telegram_alert(alert_text)
                    print(f"      ✅ Telegram alert sent")
                except Exception as e:
                    print(f"      ⚠️  Could not send Telegram alert: {e}")

            # Set last scraped timestamp
            spac.last_scraped_at = datetime.now()
            print(f"      ✓ last_scraped_at: {spac.last_scraped_at.strftime('%Y-%m-%d %H:%M:%S')}")

            self.db.commit()
            print(f"\n   ✅ Saved successfully!")
            return True

        except Exception as e:
            print(f"   ❌ Error saving: {e}")
            self.db.rollback()
            return False

    def verify_cik_ticker_match(self, ticker: str, expected_cik: str) -> bool:
        """
        Verify that ticker currently maps to expected CIK in SEC database

        Prevents ticker reuse data corruption (ATMV lesson - Oct 11, 2025)

        Returns True if CIK matches, False if mismatch detected
        """
        try:
            search_url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'company': ticker,
                'owner': 'exclude',
                'count': 1
            }

            response = requests.get(search_url, params=params, headers=self.headers, timeout=10)

            if response.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')

                cik_element = soup.find('span', {'class': 'companyName'})
                if cik_element:
                    cik_text = cik_element.get_text()
                    cik_match = re.search(r'CIK#:\s*(\d+)', cik_text)

                    if cik_match:
                        sec_cik = cik_match.group(1).zfill(10)
                        expected_cik_padded = expected_cik.zfill(10)

                        if sec_cik != expected_cik_padded:
                            print(f"   ⚠️  CIK MISMATCH DETECTED!")
                            print(f"      Database CIK: {expected_cik_padded}")
                            print(f"      SEC API CIK:  {sec_cik}")
                            print(f"      Likely cause: Ticker reuse - different SPAC now owns ticker {ticker}")
                            return False
                        else:
                            print(f"   ✓ CIK verification passed ({expected_cik_padded})")
                            return True

            # If we can't verify (SEC API issue), assume OK but warn
            print(f"   ⚠️  Could not verify CIK (SEC API unavailable)")
            return True

        except Exception as e:
            print(f"   ⚠️  CIK verification failed: {e}")
            return True  # Don't block on verification failure

    def enrich_spac(self, ticker: str, save=True) -> bool:
        """Enrich a single SPAC with all data"""
        print(f"\n{'='*60}")
        print(f"Enriching {ticker}")
        print(f"{'='*60}")

        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"❌ {ticker} not found")
            return False

        print(f"1. Getting CIK for {spac.company}...")
        # Check if CIK already exists in database
        if spac.cik and spac.cik.strip():
            cik = spac.cik
            print(f"   ✓ Using existing CIK: {cik}")

            # ATMV Lesson (Oct 11, 2025): Verify CIK matches ticker ownership
            print(f"   🔍 Verifying CIK matches current ticker ownership...")
            if not self.verify_cik_ticker_match(ticker, cik):
                print(f"   ⚠️  SKIPPING ENRICHMENT - CIK mismatch detected")
                print(f"   Action required: Verify which SPAC this record should represent")
                return False
        else:
            cik = self.get_cik(spac.company)
            if not cik:
                print(f"   ❌ CIK not found")
                return False
            print(f"   ✓ CIK: {cik}")

        # IPO Press Release
        print(f"\n2. Finding IPO press release...")
        pr_url, earliest_8k_url = self.get_ipo_press_release(cik)
        pr_data = {}
        if pr_url:
            print(f"\n3. Extracting from press release...")
            pr_data = self.extract_from_press_release(pr_url, ticker=ticker)
        else:
            print(f"   ❌ Press release not found")
            # Try extracting from 8-K main document body (Items 8.01/9.01)
            if earliest_8k_url:
                print(f"\n   🔍 Trying to extract from 8-K main document...")
                pr_data = self.extract_ipo_from_8k_body(earliest_8k_url)
                if pr_data and pr_data.get('ipo_date'):
                    print(f"   ✓ Found IPO data in 8-K body!")
                else:
                    print(f"   ⚠️  Could not extract from 8-K body")

        # Prospectus
        print(f"\n4. Finding prospectus...")
        prosp_url = self.get_prospectus(cik)
        prosp_data = {}
        b4_data = {}
        if prosp_url:
            print(f"   ✓ Found prospectus")
            prosp_data = self.extract_from_prospectus(prosp_url, ticker=ticker)

            # Enhanced 424B4 extraction (overallotment, extensions, warrants, management, sponsor economics)
            print(f"\n4b. Enhanced 424B4 extraction (overallotment, extensions, management, sponsor economics)...")
            if AI_AVAILABLE:
                b4_data = self.extract_424b4_enhanced(prosp_url, ticker=ticker)
                if b4_data:
                    extracted_fields = sum(1 for v in b4_data.values() if v is not None and v != prosp_url)
                    print(f"   ✓ Extracted {extracted_fields} enhanced fields from 424B4")
            else:
                print(f"   ⚠️  AI not available, skipping enhanced 424B4 extraction")
        else:
            print(f"   ⚠️  Prospectus not found")

        # Trust Cash from 10-Q/10-K
        print(f"\n5. Finding latest 10-Q/10-K for trust cash...")
        tenq_result = self.get_latest_10q_or_10k(cik)
        trust_data = None
        tenq_filing_date = None
        tenq_filing_type = None
        tenq_ipo_data = {}
        use_424b4_fallback = False

        if tenq_result:
            tenq_url, tenq_filing_date, tenq_filing_type = tenq_result
            print(f"   ✓ Found {tenq_filing_type} (filed: {tenq_filing_date})")
            trust_data = self.extract_trust_cash(tenq_url)
            if trust_data:
                print(f"   ✓ Trust: ${trust_data['trust_value']:.2f}/share")
                if 'trust_cash' in trust_data:
                    print(f"      Total: ${trust_data['trust_cash']:,.0f}")
                if 'shares_outstanding' in trust_data:
                    print(f"      Shares: {trust_data['shares_outstanding']:,.0f}")
            else:
                print(f"   ⚠️  Could not extract trust cash from 10-Q/10-K")
                # If we have a 10-Q but couldn't extract trust data, use 424B4 fallback
                use_424b4_fallback = True

            # If we don't have IPO data from press release or prospectus, try 10-Q Note 1
            if not pr_data.get('ipo_date') or not pr_data.get('ipo_proceeds'):
                tenq_ipo_data = self.extract_ipo_from_10q(tenq_url)
                if tenq_ipo_data:
                    # Merge with pr_data (pr_data takes precedence)
                    for key in ['ipo_date', 'ipo_proceeds', 'unit_ticker']:
                        if not pr_data.get(key) and tenq_ipo_data.get(key):
                            pr_data[key] = tenq_ipo_data[key]
        else:
            print(f"   ℹ️  No 10-Q/10-K yet (will use 424B4 IPO data as fallback)")
            use_424b4_fallback = True

        # 424B4 Fallback: For new SPACs without 10-Q/10-K, or if extraction failed
        if use_424b4_fallback and prosp_data and spac.ipo_date:
            # Check how recent the IPO is
            ipo_date = spac.ipo_date.date() if isinstance(spac.ipo_date, datetime) else spac.ipo_date
            days_since_ipo = (datetime.now().date() - ipo_date).days

            # Use fallback for SPACs < 180 days old (before first 10-Q with trust data)
            if days_since_ipo < 180:
                print(f"   📊 New SPAC ({days_since_ipo} days since IPO) - using 424B4 fallback...")

                # Get shares outstanding (with overallotment if exercised)
                if spac.shares_outstanding_with_overallotment:
                    shares = spac.shares_outstanding_with_overallotment
                    print(f"      Shares (with overallotment): {shares:,.0f}")
                elif spac.shares_outstanding_base:
                    shares = spac.shares_outstanding_base
                    print(f"      Shares (base only): {shares:,.0f}")
                else:
                    shares = None

                # Get IPO proceeds
                if spac.ipo_proceeds:
                    ipo_proceeds_str = spac.ipo_proceeds.replace('$', '').replace(',', '')
                    ipo_proceeds = float(ipo_proceeds_str)
                    print(f"      IPO proceeds: ${ipo_proceeds/1e6:.1f}M")

                    # IMPROVED: Check 8-K closing announcement for actual trust cash
                    # (accounts for overallotment exercise, not just base offering)
                    actual_trust_data = self._extract_trust_from_8k_closing(ticker, spac.ipo_date)

                    if actual_trust_data:
                        # Use actual numbers from 8-K (includes overallotment if exercised)
                        trust_cash = actual_trust_data['trust_cash']
                        actual_shares = actual_trust_data.get('shares_outstanding', shares)
                        print(f"      ✓ Extracted from 8-K closing: ${trust_cash/1e6:.1f}M in trust")
                        if actual_trust_data.get('overallotment_exercised'):
                            print(f"      ✓ Overallotment WAS exercised (included in trust)")
                    else:
                        # Fallback: Simple calculation (may be inaccurate if overallotment exercised)
                        trust_cash = ipo_proceeds * 0.98
                        actual_shares = shares
                        print(f"      ⚠️  No 8-K data - estimating: ${trust_cash/1e6:.1f}M (may be low if overallotment exercised)")

                    # Update using tracker (will respect date precedence)
                    if actual_shares:
                        from utils.trust_account_tracker import update_trust_cash, update_shares_outstanding

                        # Update shares first
                        update_shares_outstanding(
                            db_session=self.db,
                            ticker=ticker,
                            new_value=actual_shares,
                            source='8-K/424B4',
                            filing_date=spac.ipo_date,
                            reason='Shares from 8-K closing or 424B4 (includes overallotment if exercised)'
                        )

                        # Update trust cash
                        update_trust_cash(
                            db_session=self.db,
                            ticker=ticker,
                            new_value=trust_cash,
                            source='8-K/424B4',
                            filing_date=spac.ipo_date,
                            quarter='IPO'
                        )

                        print(f"      ✅ Trust account updated from 8-K/424B4")
                    else:
                        print(f"      ⚠️  Cannot calculate trust - shares outstanding not available")
                else:
                    print(f"      ⚠️  Cannot calculate trust - IPO proceeds not available")
            else:
                print(f"   ℹ️  SPAC is {days_since_ipo} days old - should have 10-Q by now")
                print(f"      Consider manual review if trust data is missing")

        # Check for deal announcement
        print(f"\n6. Checking for business combination announcement...")
        deal_data = None
        # Only check if not already marked as having a deal
        if not spac.deal_status or spac.deal_status == 'SEARCHING':
            # Use extracted IPO date or existing one (whichever is available)
            ipo_date = pr_data.get('ipo_date') or spac.ipo_date
            # Pass IPO date to avoid false positives from IPO-related filings
            deal_data = self.check_for_deal_announcement(cik, ipo_date)
            if deal_data:
                print(f"   🎯 Deal found: {deal_data.get('target', 'Unknown target')}")
            else:
                print(f"   ℹ️  No deal announcement found (SPAC still searching)")
        else:
            print(f"   ℹ️  Already classified as {spac.deal_status}")

        # Check for S-4 filing if deal was announced
        # S-4 contains definitive deal terms (filed 30-60 days after announcement)
        print(f"\n6b. Checking for S-4 filing (deal terms)...")
        s4_data = {}
        s4_filing_date = None
        if deal_data or (spac.deal_status == 'ANNOUNCED'):
            s4_result = self.get_s4_filing(cik)
            if s4_result:
                s4_url, s4_filing_date = s4_result
                print(f"   ✓ Found S-4 filing (filed: {s4_filing_date})")
                time.sleep(0.15)  # Rate limiting
                s4_data = self.extract_from_s4(s4_url)
                if s4_data:
                    extracted_fields = [k for k, v in s4_data.items() if v is not None and k != 's4_filing_url']
                    if extracted_fields:
                        print(f"   ✓ Extracted from S-4: {', '.join(extracted_fields)}")
            else:
                print(f"   ℹ️  No S-4 filed yet (typically filed 30-60 days after deal announcement)")
        else:
            print(f"   ℹ️  No deal announced - skipping S-4 check")

        # Extract from S-1 filing ONLY if no 424B4/424B3 available
        # S-1 is preliminary - 424B4 is final and authoritative
        print(f"\n7. Checking for S-1 fallback (only if no 424B4)...")
        s1_data = {}

        # Only use S-1 if we don't have a prospectus at all
        if not spac.prospectus_424b4_url:
            print(f"   ⚠️  No 424B4/424B3 found - falling back to S-1")
            s1_url = self.get_s1_filing(cik)

            if s1_url:
                print(f"   ✓ Found S-1 filing")
                time.sleep(0.15)  # Rate limiting

                try:
                    response = requests.get(s1_url, headers=self.headers, timeout=30)
                    s1_html = response.text

                    # Extract founder shares
                    founder_result = self.extract_founder_shares(s1_html)
                    if founder_result.get('founder_shares'):
                        s1_data['founder_shares'] = founder_result['founder_shares']
                        s1_data['founder_confidence'] = founder_result.get('confidence', 0.0)
                        s1_data['founder_method'] = founder_result.get('extraction_method', 'unknown')

                    # Extract warrant terms
                    warrant_result = self.extract_warrant_terms(s1_html)
                    if warrant_result.get('warrant_ratio'):
                        s1_data['warrant_ratio'] = warrant_result['warrant_ratio']
                    if warrant_result.get('exercise_price'):
                        s1_data['warrant_exercise_price'] = warrant_result['exercise_price']
                    if warrant_result.get('expiration_years'):
                        s1_data['warrant_expiration_years'] = warrant_result['expiration_years']

                    if s1_data:
                        fields_count = len(s1_data)
                        print(f"   ✓ Extracted {fields_count} fields from S-1 (fallback)")
                    else:
                        print(f"   ⚠️  Could not extract data from S-1")

                except Exception as e:
                    print(f"   ❌ Error processing S-1: {e}")
            else:
                print(f"   ⚠️  S-1 filing not found")
        else:
            print(f"   ℹ️  424B4 available - skipping S-1 (S-1 is preliminary, 424B4 is final)")

        # Save
        if save:
            self.save_to_database(ticker, pr_data, prosp_data, trust_data, deal_data, s1_data, b4_data, s4_data, s4_filing_date, tenq_filing_date, tenq_filing_type)

            # Check for deadline extensions (must happen AFTER save, so deadline_date is set)
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if spac and spac.original_deadline_date and spac.cik:
                extension_data = self.check_for_deadline_extensions(
                    spac.cik,
                    spac.original_deadline_date,
                    ticker
                )

                if extension_data['extension_count'] > 0:
                    spac.deadline_date = extension_data['current_deadline']
                    spac.extension_count = extension_data['extension_count']
                    spac.is_extended = True

                    # Get most recent extension date
                    if extension_data['extension_history']:
                        latest_ext = extension_data['extension_history'][-1]
                        spac.extension_date = latest_ext['date']

                        # If redemption data available, add as redemption event
                        if latest_ext.get('shares_redeemed'):
                            # Use redemption tracker (incremental)
                            add_redemption_event(
                                db_session=self.db,
                                ticker=ticker,
                                shares_redeemed=latest_ext['shares_redeemed'],
                                redemption_amount=0.0,  # Amount not available from extension filing
                                filing_date=latest_ext['date'],
                                source='8-K',
                                reason='Redemptions related to deadline extension'
                            )

                    self.db.commit()
                    print(f"\n   ✓ Updated {ticker} with {extension_data['extension_count']} extension(s)")

        return True

    def enrich_all(self, limit=None):
        """Enrich all SPACs"""
        spacs = self.db.query(SPAC).all()
        if limit:
            spacs = spacs[:limit]

        print(f"\n{'='*60}")
        print(f"Enriching {len(spacs)} SPACs...")
        print(f"{'='*60}")

        success_count = 0
        for i, spac in enumerate(spacs, 1):
            print(f"\n[{i}/{len(spacs)}]")
            if self.enrich_spac(spac.ticker):
                success_count += 1
            time.sleep(0.3)

        print(f"\n{'='*60}")
        print(f"✅ Complete: {success_count}/{len(spacs)} enriched")
        print(f"{'='*60}")

        # Print extraction quality summary
        self.logger.print_session_summary()

    def close(self):
        self.db.close()


class Filing424B4Extractor:
    """
    Extracts targeted sections from 424B4 final prospectus
    Reduces token usage from 460K to 38K (91.7% reduction)
    """

    def __init__(self, html_content: str):
        """
        Initialize with 424B4 HTML content

        Args:
            html_content: Full HTML of 424B4 filing
        """
        self.html = html_content
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.text = self.soup.get_text()

    def extract_cover_page(self) -> str:
        """
        Extract cover page (first 15,000 chars)
        Contains: units, price, underwriter, basic structure
        """
        return self.text[:15000]

    def extract_the_offering_section(self) -> str:
        """
        Extract "The Offering" or "Summary" section
        Contains: overallotment, warrants, extensions, trust terms

        Different 424B4s structure this differently:
        - Some have "THE OFFERING" as a standalone section
        - Some have "The Offering" as subsections within "SUMMARY" section

        We extract the SUMMARY section if it exists, otherwise THE OFFERING
        """
        # First try to find SUMMARY section (CCCX and similar)
        summary_patterns = [
            r"\n\s*SUMMARY\s*\n",
            r"\n\s*Summary\s*\n",
            r"\n\s*PROSPECTUS SUMMARY\s*\n",
        ]

        start_idx = None
        for pattern in summary_patterns:
            match = re.search(pattern, self.text)
            if match:
                start_idx = match.start()
                print(f"   ✓ Found SUMMARY section at {start_idx:,}")
                break

        # Fallback to THE OFFERING if no SUMMARY found
        if not start_idx:
            offering_patterns = [
                r"\n\s*THE OFFERING\s*\n",
                r"\n\s*The Offering\s*\n",
            ]
            for pattern in offering_patterns:
                match = re.search(pattern, self.text)
                if match:
                    start_idx = match.start()
                    print(f"   ✓ Found THE OFFERING section at {start_idx:,}")
                    break

        if not start_idx:
            print("   ⚠️  Could not find 'The Offering' or 'Summary' section in 424B4")
            return ""

        # Find the end of this section (look for next major section)
        end_patterns = [
            r"\n\s*RISK FACTORS\s*\n",
            r"\n\s*Risk Factors\s*\n",
            r"\n\s*USE OF PROCEEDS\s*\n",
        ]

        end_idx = start_idx + 150000  # Take up to 150K chars to ensure we get all warrant details
        for pattern in end_patterns:
            match = re.search(pattern, self.text[start_idx + 1000:start_idx + 150000])
            if match:
                end_idx = start_idx + 1000 + match.start()
                break

        # Extract the full section
        section_text = self.text[start_idx:end_idx]
        print(f"   ✓ The Offering/Summary section: {len(section_text):,} chars extracted")
        return section_text

    def extract_prospectus_summary(self) -> str:
        """
        Extract "Prospectus Summary" section
        Contains: deadline, extensions, business model, target sector

        Typical location: 174,000 - 255,000 chars in document
        """
        patterns = [
            r"PROSPECTUS SUMMARY",
            r"Prospectus Summary",
            r"SUMMARY",
        ]

        start_idx = None
        for pattern in patterns:
            match = re.search(pattern, self.text)
            if match:
                start_idx = match.start()
                break

        if not start_idx:
            print("   ⚠️  Could not find 'Prospectus Summary' section in 424B4")
            return ""

        # Extract ~80K chars from start of section
        return self.text[start_idx:start_idx + 80000]

    def extract_management_section(self) -> str:
        """
        Extract "Management" section
        Contains: names, backgrounds, previous SPAC experience, education

        Typical location: After prospectus summary
        """
        # Look for "MANAGEMENT" followed by "Officers" and actual bios (has names/ages)
        # This is more reliable than looking for "DIRECTORS AND EXECUTIVE OFFICERS" which appears in many contexts
        start_idx = None
        for match in re.finditer(r"\bMANAGEMENT\b", self.text):
            # Check if followed by Officers AND has actual executive info (Name/Age table or specific patterns)
            following_text = self.text[match.start():match.start()+2000]
            if "Officers" in following_text and "DISCUSSION" not in following_text and "Discussion" not in following_text:
                # Check for signs of actual bios: Name/Age table or biographical content
                if any(marker in following_text for marker in ["Name\n", "Age\n", "\nTitle\n", "served as our Chief", "has served as"]):
                    start_idx = match.start()
                    break

        # Fallback: Look for "MANAGEMENT" followed by bios (has "Officers" and actual names like "Name", "Age", or specific names)
        if not start_idx:
            for match in re.finditer(r"\bMANAGEMENT\b", self.text):
                # Check if followed by Officers AND has actual executive info (Name/Age table or specific names)
                following_text = self.text[match.start():match.start()+2000]
                if "Officers" in following_text and "DISCUSSION" not in following_text:
                    # Check for signs of actual bios: Name/Age table or common executive names
                    if any(marker in following_text for marker in ["Name", "Age", "Title", "Michael", "John", "David", "James"]):
                        start_idx = match.start()
                        break

        if not start_idx:
            print("   ⚠️  Could not find 'Management' section in 424B4")
            return ""

        # Extract ~30K chars from start of section (management bios can be long)
        return self.text[start_idx:start_idx + 30000]

    def extract_description_of_securities_section(self) -> str:
        """
        Extract "Description of Securities" section
        Contains: detailed warrant terms (redemption, expiration, cashless exercise)

        This section contains the definitive warrant terms that may not be in "The Offering"
        Usually appears after Management section in the 424B4
        """
        patterns = [
            r"\n\s*DESCRIPTION OF SECURITIES\s*\n",
            r"\n\s*Description of Securities\s*\n",
            r"\n\s*DESCRIPTION OF CAPITAL STOCK\s*\n",
            r"\n\s*Description of Capital Stock\s*\n",
        ]

        start_idx = None
        for pattern in patterns:
            match = re.search(pattern, self.text)
            if match:
                start_idx = match.start()
                print(f"   ✓ Found Description of Securities at position {start_idx:,}")
                break

        if not start_idx:
            print("   ⚠️  Could not find 'Description of Securities' section in 424B4")
            return ""

        # Find the end of this section (look for next major section)
        end_patterns = [
            r"\n\s*CERTAIN RELATIONSHIPS",
            r"\n\s*SECURITIES ACT RESTRICTIONS",
            r"\n\s*MATERIAL U\.S\. FEDERAL INCOME TAX",
            r"\n\s*PLAN OF DISTRIBUTION",
        ]

        end_idx = start_idx + 100000  # Default: take 100K chars
        for pattern in end_patterns:
            match = re.search(pattern, self.text[start_idx + 1000:start_idx + 100000])
            if match:
                end_idx = start_idx + 1000 + match.start()
                break

        # Extract the full section
        section_text = self.text[start_idx:end_idx]
        print(f"   ✓ Description of Securities section: {len(section_text):,} chars extracted")
        return section_text

    def get_targeted_extraction(self) -> str:
        """
        Get all targeted sections concatenated
        Total: ~153K chars (38K tokens) vs 1.8M chars (460K tokens) = 91.7% reduction

        Returns:
            Concatenated text from: Cover + The Offering + Prospectus Summary + Management
        """
        sections = {
            "COVER PAGE": self.extract_cover_page(),
            "THE OFFERING": self.extract_the_offering_section(),
            "PROSPECTUS SUMMARY": self.extract_prospectus_summary(),
            "MANAGEMENT": self.extract_management_section(),
        }

        # Concatenate with section markers
        result = []
        for section_name, content in sections.items():
            if content:
                result.append(f"\n\n===== {section_name} =====\n\n")
                result.append(content)

        full_text = "".join(result)
        print(f"   📊 424B4 extraction: {len(full_text):,} chars from {len(self.text):,} chars ({len(full_text)/len(self.text)*100:.1f}% of original)")

        return full_text


if __name__ == "__main__":
    import sys

    enricher = SPACDataEnricher()

    try:
        if len(sys.argv) > 1:
            ticker = sys.argv[1].upper()

            if ticker == '--ALL':
                limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
                enricher.enrich_all(limit=limit)
            else:
                enricher.enrich_spac(ticker)
        else:
            print("Usage:")
            print("  python sec_data_scraper.py TICKER")
            print("  python sec_data_scraper.py --ALL")
            print("  python sec_data_scraper.py --ALL 10")
    finally:
        enricher.close()
