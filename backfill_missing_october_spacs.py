#!/usr/bin/env python3
"""
Backfill Missing October 2025 SPACs

Adds 10 missing October 2025 SPACs that weren't captured by pre-IPO monitoring.
Searches SEC for 424B4 filings and extracts all key data.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
import time
import os
from openai import OpenAI
from dotenv import load_dotenv
import json

load_dotenv()

# AI Setup
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if DEEPSEEK_API_KEY:
    AI_CLIENT = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
else:
    AI_AVAILABLE = False
    print("⚠️  DeepSeek API key not found - AI extraction disabled")

HEADERS = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}
BASE_URL = "https://www.sec.gov"

# Missing October 2025 SPACs from SPAC Insider
MISSING_SPACS = [
    ('GIWW', 'GigCapital8 Corp.', '2025-10-03', 220, 'GIWWU'),
    ('LKSP', 'Lake Superior Acquisition Corp.', '2025-10-06', 100, 'LKSPU'),
    ('ALIS', 'Calisa Acquisition Corp.', '2025-10-21', 60, 'ALISU'),
    ('HAVA', 'Harvard Ave Acquisition Corp.', '2025-10-22', 145, 'HAVAU'),
    ('MMTX', 'Miluna Acquisition Corp.', '2025-10-22', 60, 'MMTXU'),
    ('LAFA', 'LaFayette Acquisition Corp.', '2025-10-23', 100, 'LAFAU'),
    ('APXT', 'Apex Treasury Corporation', '2025-10-27', 300, 'APXTU'),
    ('DYOR', 'Insight Digital Partners II', '2025-10-28', 150, 'DYORU'),
    ('DNMX', 'Dynamix Corporation III', '2025-10-29', 175, 'DNMXU'),
    ('VACI', 'Viking Acquisition Corp. I', '2025-10-31', 200, 'VACI.U'),
]


def find_424b4_filing(company_name):
    """Search SEC EDGAR for 424B4 filing"""
    try:
        # Search for recent 424B4
        search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={company_name}&type=424B4&dateb=&owner=exclude&count=10&search_text="

        response = requests.get(search_url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find first 424B4 filing link
        for row in soup.find_all('tr'):
            if '424B4' in row.text and '2025' in row.text:
                # Get the filing detail page
                links = row.find_all('a', href=True)
                for link in links:
                    if 'Archives' in link['href']:
                        filing_url = BASE_URL + link['href']

                        # Extract CIK from URL or page
                        cik_match = re.search(r'/data/(\d+)/', filing_url)
                        if cik_match:
                            cik = cik_match.group(1)
                            return filing_url, cik

        return None, None

    except Exception as e:
        print(f"  ❌ Error searching SEC: {e}")
        return None, None


def get_424b4_document(filing_url):
    """Get the actual 424B4 document content"""
    try:
        response = requests.get(filing_url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the .htm document
        doc_url = None
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '.htm' in href and not href.endswith('.xml') and 'ix?doc=' not in href:
                doc_url = BASE_URL + href
                break

        if not doc_url:
            return None

        doc_response = requests.get(doc_url, headers=HEADERS, timeout=30)
        return doc_response.text

    except Exception as e:
        print(f"  ❌ Error fetching document: {e}")
        return None


def extract_with_ai(text, ticker, company):
    """Use AI to extract comprehensive SPAC data from 424B4"""
    if not AI_AVAILABLE:
        return {}

    try:
        text_excerpt = text[:50000]

        prompt = f"""Extract SPAC IPO data from this 424B4 prospectus for {ticker} ({company}). Return ONLY valid JSON with NO markdown.

Extract these fields (use null if not found):

{{
  "sponsor": "<string>",  // Sponsor/founder name
  "banker": "<string>",  // Lead underwriter/representative
  "target_sector": "<string>",  // Target business sector/focus
  "founder_shares": <number>,  // Count of founder/sponsor shares
  "shares_outstanding_base": <number>,  // Total shares before overallotment
  "shares_outstanding_with_overallotment": <number>,  // Total shares after overallotment
  "overallotment_units": <number>,  // Overallotment option size
  "overallotment_percentage": <number>,  // Overallotment as percentage (usually 15)
  "unit_structure": "<string>",  // Unit composition (e.g. "1 share + 1/3 warrant")
  "warrant_exercise_price": <number>,  // Warrant strike price (usually 11.50)
  "warrant_ratio": "<string>",  // Warrants per share (e.g. "1/2" or "1")
  "trust_per_unit": <number>,  // Cash per unit in trust (typically 10.00)
  "deadline_months": <number>,  // Months until business combination deadline (18-24)
  "extension_months_available": <number>,  // Months of extensions available (3, 6, or 12)
  "extension_deposit_per_share": <number>,  // Deposit per share for extension (e.g. 0.03)
  "max_deadline_with_extensions": <number>  // Total months to deadline with extensions
}}

Text excerpt:
{text_excerpt}

Return ONLY the JSON object, no explanation."""

        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )

        content = response.choices[0].message.content.strip()

        # Remove markdown if present
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()

        data = json.loads(content)
        return data

    except Exception as e:
        print(f"  ❌ AI extraction error: {e}")
        return {}


def add_spac_to_database(ticker, company, ipo_date, proceeds, unit_ticker, filing_data):
    """Add SPAC to main database"""

    db = SessionLocal()
    try:
        # Check if already exists
        existing = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if existing:
            print(f"  ℹ️  {ticker} already in database")
            return False

        # Parse IPO date
        ipo_date_obj = datetime.strptime(ipo_date, '%Y-%m-%d').date()

        # Create new SPAC
        new_spac = SPAC(
            ticker=ticker,
            company=company,
            cik=filing_data.get('cik'),

            # Deal status
            deal_status='SEARCHING',
            target='-',

            # IPO data
            ipo_date=ipo_date_obj,
            ipo_proceeds=f"${proceeds}M",
            unit_ticker=unit_ticker,

            # From AI extraction
            sponsor=filing_data.get('sponsor'),
            banker=filing_data.get('banker'),
            sector=filing_data.get('target_sector'),

            founder_shares=filing_data.get('founder_shares'),
            shares_outstanding_base=filing_data.get('shares_outstanding_base'),
            shares_outstanding_with_overallotment=filing_data.get('shares_outstanding_with_overallotment'),
            overallotment_units=filing_data.get('overallotment_units'),
            overallotment_percentage=filing_data.get('overallotment_percentage'),

            unit_structure=filing_data.get('unit_structure'),
            trust_value=filing_data.get('trust_per_unit', 10.00),
            warrant_exercise_price=filing_data.get('warrant_exercise_price', 11.50),

            deadline_months=filing_data.get('deadline_months'),
            extension_months_available=filing_data.get('extension_months_available'),
            extension_deposit_per_share=filing_data.get('extension_deposit_per_share'),
            max_deadline_with_extensions=filing_data.get('max_deadline_with_extensions'),

            prospectus_424b4_url=filing_data.get('filing_url'),
            last_scraped_at=datetime.utcnow()
        )

        # Calculate deadline
        if new_spac.deadline_months:
            new_spac.deadline_date = ipo_date_obj + relativedelta(months=new_spac.deadline_months)

        # Convert warrant ratio to decimal
        if filing_data.get('warrant_ratio'):
            ratio_str = filing_data['warrant_ratio']
            if '/' in str(ratio_str):
                parts = str(ratio_str).split('/')
                ratio = float(parts[0]) / float(parts[1])
            else:
                ratio = float(ratio_str)
            new_spac.warrant_ratio = ratio

        # Save to database
        db.add(new_spac)
        db.commit()

        print(f"  ✅ Added {ticker} to database")
        return True

    except Exception as e:
        print(f"  ❌ Database error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    """Backfill all missing October 2025 SPACs"""

    print(f"\n📊 Backfilling {len(MISSING_SPACS)} Missing October 2025 SPACs\n")
    print(f"Total missing proceeds: ${sum(s[3] for s in MISSING_SPACS)}M\n")

    success_count = 0

    for ticker, company, ipo_date, proceeds, unit_ticker in MISSING_SPACS:
        print(f"\n🔍 Processing {ticker}: {company}")
        print(f"   IPO: {ipo_date} | Proceeds: ${proceeds}M")

        # Find 424B4 filing
        filing_url, cik = find_424b4_filing(company)

        if not filing_url:
            print(f"  ❌ Could not find 424B4 filing")
            time.sleep(1)
            continue

        print(f"  ✓ Found 424B4: {filing_url[:80]}...")
        print(f"  ✓ CIK: {cik}")

        # Get document content
        content = get_424b4_document(filing_url)

        if not content:
            print(f"  ❌ Could not fetch document content")
            time.sleep(1)
            continue

        # Extract data with AI
        print(f"  🤖 Extracting data with AI...")
        extracted_data = extract_with_ai(content, ticker, company)

        if not extracted_data:
            print(f"  ❌ AI extraction failed")
            time.sleep(1)
            continue

        # Add metadata
        extracted_data['cik'] = cik
        extracted_data['filing_url'] = filing_url

        # Add to database
        if add_spac_to_database(ticker, company, ipo_date, proceeds, unit_ticker, extracted_data):
            success_count += 1

        time.sleep(1)  # Rate limiting

    print(f"\n\n✅ Backfill complete:")
    print(f"   Added: {success_count}/{len(MISSING_SPACS)} SPACs")
    print(f"   Failed: {len(MISSING_SPACS) - success_count}")


if __name__ == '__main__':
    main()
