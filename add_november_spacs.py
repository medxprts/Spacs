#!/usr/bin/env python3
"""Add 2 November 2025 SPACs with verified 424B4 URLs"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
import requests
from bs4 import BeautifulSoup
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
AI_CLIENT = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

HEADERS = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}
BASE_URL = "https://www.sec.gov"

# 2 November 2025 SPACs with verified 424B4 URLs
SPACS_TO_ADD = [
    {
        'ticker': 'WSTN',
        'company': 'Westin Acquisition Corp.',
        'cik': '2076192',
        'ipo_date': '2025-11-05',
        'proceeds': 50,
        'unit_ticker': 'WSTNU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2076192/000121390025106546/0001213900-25-106546-index.htm'
    },
    {
        'ticker': 'CEPV',
        'company': 'Cantor Equity Partners V, Inc.',
        'cik': '2034266',
        'ipo_date': '2025-11-04',
        'proceeds': 220,
        'unit_ticker': 'CEPV',  # No separate unit ticker - shares only
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2034266/000121390025106079/0001213900-25-106079-index.htm'
    }
]


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
    try:
        # Look for warrant redemption section specifically
        warrant_section_start = text.lower().find('redemption of warrants')
        if warrant_section_start == -1:
            warrant_section_start = text.lower().find('warrant redemption')

        # Take first 40k + warrant section if found
        if warrant_section_start > 40000:
            # Include warrant section with surrounding context (2k before, 12k after)
            section_start = max(0, warrant_section_start - 2000)
            section_end = min(len(text), warrant_section_start + 12000)
            text_excerpt = text[:40000] + "\n\n[WARRANT REDEMPTION SECTION]:\n" + text[section_start:section_end]
        else:
            # Standard 50k excerpt
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
  "warrant_redemption_price": <number>,  // Price at which company can CALL/REDEEM warrants (typically 18.00)
  "warrant_redemption_days": "<string>",  // Full redemption condition e.g. "20 trading days within a 30-trading day period"
  "warrant_cashless_exercise": <boolean>,  // Whether cashless exercise is allowed
  "warrant_expiration_years": <number>,  // Years until warrant expiration (usually 5)
  "warrant_expiration_trigger": "<string>",  // What triggers expiration
  "trust_per_unit": <number>,  // Cash per unit in trust (typically 10.00)
  "deadline_months": <number>,  // Months until business combination deadline (18-24)
  "extension_months_available": <number>,  // Months of extensions available
  "extension_deposit_per_share": <number>,  // Deposit per share for extension
  "max_deadline_with_extensions": <number>,  // Total months to deadline with extensions
  "management_team": "<string>",  // Names and titles of key management
  "management_summary": "<string>",  // 2-3 sentence summary of team background
  "key_executives": "<string>"  // CEO, President, CFO with brief background
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


def add_spac(spac_info):
    """Add SPAC to database"""
    db = SessionLocal()
    try:
        # Check if already exists
        existing = db.query(SPAC).filter(SPAC.ticker == spac_info['ticker']).first()
        if existing:
            print(f"  ℹ️  {spac_info['ticker']} already in database")
            return False

        print(f"\n🔍 Processing {spac_info['ticker']}: {spac_info['company']}")
        print(f"   IPO: {spac_info['ipo_date']} | ${spac_info['proceeds']}M")

        # Get document content
        content = get_424b4_document(spac_info['filing_url'])
        if not content:
            print(f"  ❌ Could not fetch 424B4 content")
            return False

        # Extract data with AI
        print(f"  🤖 Extracting data with AI...")
        extracted = extract_with_ai(content, spac_info['ticker'], spac_info['company'])

        if not extracted:
            print(f"  ❌ AI extraction failed")
            return False

        # Parse IPO date
        ipo_date_obj = datetime.strptime(spac_info['ipo_date'], '%Y-%m-%d').date()

        # Create SPAC
        new_spac = SPAC(
            ticker=spac_info['ticker'],
            company=spac_info['company'],
            cik=spac_info['cik'],
            deal_status='SEARCHING',
            target='-',
            ipo_date=ipo_date_obj,
            ipo_proceeds=f"${spac_info['proceeds']}M",
            unit_ticker=spac_info['unit_ticker'],

            sponsor=extracted.get('sponsor'),
            banker=extracted.get('banker'),
            sector=extracted.get('target_sector'),

            founder_shares=extracted.get('founder_shares'),
            shares_outstanding_base=extracted.get('shares_outstanding_base'),
            shares_outstanding_with_overallotment=extracted.get('shares_outstanding_with_overallotment'),
            overallotment_units=extracted.get('overallotment_units'),
            overallotment_percentage=extracted.get('overallotment_percentage'),

            unit_structure=extracted.get('unit_structure'),
            trust_value=extracted.get('trust_per_unit', 10.00),
            warrant_exercise_price=extracted.get('warrant_exercise_price'),
            warrant_redemption_price=extracted.get('warrant_redemption_price'),
            warrant_redemption_days=extracted.get('warrant_redemption_days'),
            warrant_cashless_exercise=extracted.get('warrant_cashless_exercise'),
            warrant_expiration_years=extracted.get('warrant_expiration_years'),
            warrant_expiration_trigger=extracted.get('warrant_expiration_trigger'),

            deadline_months=extracted.get('deadline_months'),
            extension_months_available=extracted.get('extension_months_available'),
            extension_deposit_per_share=extracted.get('extension_deposit_per_share'),
            max_deadline_with_extensions=extracted.get('max_deadline_with_extensions'),

            management_team=extracted.get('management_team'),
            management_summary=extracted.get('management_summary'),
            key_executives=extracted.get('key_executives'),

            prospectus_424b4_url=spac_info['filing_url'],
            last_scraped_at=datetime.utcnow()
        )

        # Calculate deadline
        if new_spac.deadline_months:
            new_spac.deadline_date = ipo_date_obj + relativedelta(months=new_spac.deadline_months)

        # Convert warrant ratio to decimal (handle both "1/3" and "1:3" formats)
        if extracted.get('warrant_ratio'):
            ratio_str = str(extracted['warrant_ratio'])
            if '/' in ratio_str:
                parts = ratio_str.split('/')
                ratio = float(parts[0]) / float(parts[1])
            elif ':' in ratio_str:
                parts = ratio_str.split(':')
                ratio = float(parts[0]) / float(parts[1])
            else:
                ratio = float(ratio_str)
            new_spac.warrant_ratio = ratio

        db.add(new_spac)
        db.commit()

        print(f"  ✅ Added {spac_info['ticker']} to database")

        # Show extracted fields
        print(f"\n  📊 Extracted Data:")
        if extracted.get('sponsor'):
            print(f"     Sponsor: {extracted['sponsor']}")
        if extracted.get('banker'):
            print(f"     Banker: {extracted['banker']}")
        if extracted.get('founder_shares'):
            print(f"     Founder Shares: {extracted['founder_shares']:,}")
        if extracted.get('shares_outstanding_base'):
            print(f"     Shares Outstanding: {extracted['shares_outstanding_base']:,}")
        if extracted.get('unit_structure'):
            print(f"     Unit Structure: {extracted['unit_structure']}")
        if extracted.get('deadline_months'):
            print(f"     Deadline: {extracted['deadline_months']} months")

        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    print(f"\n📊 Adding 2 November 2025 SPACs")
    print(f"Total proceeds: ${sum(s['proceeds'] for s in SPACS_TO_ADD)}M\n")

    success_count = 0

    for spac_info in SPACS_TO_ADD:
        if add_spac(spac_info):
            success_count += 1
        time.sleep(1)  # Rate limiting

    print(f"\n\n✅ Addition complete:")
    print(f"   Added: {success_count}/{len(SPACS_TO_ADD)} SPACs")
    print(f"   Failed: {len(SPACS_TO_ADD) - success_count}")


if __name__ == '__main__':
    main()
