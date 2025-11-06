#!/usr/bin/env python3
"""Add remaining 7 October 2025 SPACs with verified 424B4 URLs"""

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

# 7 remaining SPACs with verified 424B4 URLs
SPACS_TO_ADD = [
    {
        'ticker': 'DNMX',
        'company': 'Dynamix Corporation III',
        'cik': '2081125',
        'ipo_date': '2025-10-29',
        'proceeds': 175,
        'unit_ticker': 'DNMXU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2081125/000121390025104187/0001213900-25-104187-index.htm'
    },
    {
        'ticker': 'VACI',
        'company': 'Viking Acquisition Corp. I',
        'cik': '2080023',
        'ipo_date': '2025-10-31',
        'proceeds': 200,
        'unit_ticker': 'VACI.U',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2080023/000121390025104771/0001213900-25-104771-index.htm'
    },
    {
        'ticker': 'LKSP',
        'company': 'Lake Superior Acquisition Corp.',
        'cik': '2043508',
        'ipo_date': '2025-10-06',
        'proceeds': 100,
        'unit_ticker': 'LKSPU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2043508/000147793225007409/0001477932-25-007409-index.htm'
    },
    {
        'ticker': 'ALIS',
        'company': 'Calisa Acquisition Corp.',
        'cik': '2026767',
        'ipo_date': '2025-10-21',
        'proceeds': 60,
        'unit_ticker': 'ALISU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2026767/000149315225018879/0001493152-25-018879-index.htm'
    },
    {
        'ticker': 'MMTX',
        'company': 'Miluna Acquisition Corp.',
        'cik': '2077033',
        'ipo_date': '2025-10-22',
        'proceeds': 60,
        'unit_ticker': 'MMTXU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2077033/000149315225018946/0001493152-25-018946-index.htm'
    },
    {
        'ticker': 'HAVA',
        'company': 'Harvard Ave Acquisition Corp.',
        'cik': '2042460',
        'ipo_date': '2025-10-22',
        'proceeds': 145,
        'unit_ticker': 'HAVAU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2042460/000121390025101309/0001213900-25-101309-index.htm'
    },
    {
        'ticker': 'APXT',
        'company': 'Apex Treasury Corporation',
        'cik': '2079253',
        'ipo_date': '2025-10-27',
        'proceeds': 300,
        'unit_ticker': 'APXTU',
        'filing_url': 'https://www.sec.gov/Archives/edgar/data/2079253/000121390025103160/0001213900-25-103160-index.htm'
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
        text_excerpt = text[:50000]

        prompt = f"""Extract SPAC IPO data from this 424B4 prospectus for {ticker} ({company}). Return ONLY valid JSON with NO markdown.

Extract these fields (use null if not found):

{{
  "sponsor": "<string>",
  "banker": "<string>",
  "target_sector": "<string>",
  "founder_shares": <number>,
  "shares_outstanding_base": <number>,
  "shares_outstanding_with_overallotment": <number>,
  "overallotment_units": <number>,
  "overallotment_percentage": <number>,
  "unit_structure": "<string>",
  "warrant_exercise_price": <number>,
  "warrant_ratio": "<string>",
  "trust_per_unit": <number>,
  "deadline_months": <number>,
  "extension_months_available": <number>,
  "extension_deposit_per_share": <number>,
  "max_deadline_with_extensions": <number>
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
            warrant_exercise_price=extracted.get('warrant_exercise_price', 11.50),

            deadline_months=extracted.get('deadline_months'),
            extension_months_available=extracted.get('extension_months_available'),
            extension_deposit_per_share=extracted.get('extension_deposit_per_share'),
            max_deadline_with_extensions=extracted.get('max_deadline_with_extensions'),

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
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    print(f"\n📊 Adding 7 Remaining October 2025 SPACs")
    print(f"Total proceeds: ${sum(s['proceeds'] for s in SPACS_TO_ADD)}M\n")

    success_count = 0

    for spac_info in SPACS_TO_ADD:
        if add_spac(spac_info):
            success_count += 1
        time.sleep(1)  # Rate limiting

    print(f"\n\n✅ Backfill complete:")
    print(f"   Added: {success_count}/{len(SPACS_TO_ADD)} SPACs")
    print(f"   Failed: {len(SPACS_TO_ADD) - success_count}")


if __name__ == '__main__':
    main()
