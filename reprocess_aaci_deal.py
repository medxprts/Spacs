#!/usr/bin/env python3
"""
Re-process AACI deal announcement to extract missing PIPE and deal structure data
"""

import os
import sys
import json
import requests
from bs4 import BeautifulSoup

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from utils.deal_structure_tracker import update_deal_structure
from openai import OpenAI

# AI client
AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

HEADERS = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}

def fetch_filing_content(url: str) -> str:
    """Fetch and extract text from filing"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove script and style tags
        for tag in soup(['script', 'style', 'meta', 'link']):
            tag.decompose()

        text = soup.get_text(separator=' ', strip=True)

        # Clean up whitespace
        text = ' '.join(text.split())

        return text

    except Exception as e:
        print(f"Error fetching content: {e}")
        return None


def extract_deal_details(content: str) -> dict:
    """Use AI to extract complete deal details"""

    # Limit to first 100k chars
    excerpt = content[:100000]

    prompt = f"""
Extract ALL business combination deal details from this AACI SEC filing announcing the Ripple/Pathfinder Digital Assets deal:

Extract:
1. **target** - Target company name
2. **deal_value** - Enterprise or equity value in millions (numeric only, e.g., 1400 for $1.4B)
3. **expected_close** - Expected closing date (convert "Q1 2026" to "2026-03-31", "Q2 2026" to "2026-06-30", etc.)
4. **target_sector** - Industry/sector of target (e.g., "Cryptocurrency", "Digital Assets")

Deal Structure:
5. **min_cash** - Minimum cash condition in millions (numeric, e.g., 200 for "$200M")
6. **min_cash_percentage** - Minimum cash as percentage (numeric, e.g., 25.0 for "25%")
7. **pipe_size** - PIPE investment amount in millions (numeric, e.g., 100 for "$100M")
8. **pipe_price** - PIPE share price (numeric, e.g., 10.0 for "$10.00")
9. **earnout_shares** - Earnout/contingent shares in millions (numeric, e.g., 5.0 for "5M shares")
10. **forward_purchase** - Forward purchase agreement amount in millions (numeric)

Return JSON with NUMERIC values only (no dollar signs, no "M" or "B"):
{{
    "target": "Pathfinder Digital Assets",
    "deal_value": 1400,
    "expected_close": "2026-03-31",
    "target_sector": "Digital Assets",
    "min_cash": 200,
    "min_cash_percentage": 25.0,
    "pipe_size": 100,
    "pipe_price": 10.0,
    "earnout_shares": 5.0,
    "forward_purchase": 50
}}

If any field is not found, return null for that field.

Text:
{excerpt}
"""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an SEC filing extraction expert. Extract ALL deal announcement data precisely. Return NUMERIC values only (no dollar signs, no M/B suffixes)."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        data = json.loads(response.choices[0].message.content)
        return data

    except Exception as e:
        print(f"AI extraction failed: {e}")
        return None


def main():
    print("🔄 Re-processing AACI deal announcement...")

    # AACI's recent 8-K
    filing_url = "https://www.sec.gov/Archives/edgar/data/2044009/000119312525243103/0001193125-25-243103-index.htm"

    print(f"\n📥 Fetching filing content from SEC...")
    content = fetch_filing_content(filing_url)

    if not content:
        print("❌ Failed to fetch content")
        return

    print(f"✓ Fetched {len(content):,} characters")

    print(f"\n🤖 Extracting deal details with AI...")
    deal_data = extract_deal_details(content)

    if not deal_data:
        print("❌ AI extraction failed")
        return

    print(f"\n📊 Extracted data:")
    print(json.dumps(deal_data, indent=2))

    # Update database
    print(f"\n💾 Updating database...")
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == 'AACI').first()

        if not spac:
            print("❌ AACI not found in database")
            return

        # Update expected_close if better than current
        if deal_data.get('expected_close') and not spac.expected_close:
            spac.expected_close = deal_data['expected_close']
            print(f"✓ Set expected_close: {deal_data['expected_close']}")

        # Update target_sector if available
        if deal_data.get('target_sector') and not spac.sector:
            spac.sector = deal_data['target_sector']
            print(f"✓ Set sector: {deal_data['target_sector']}")

        # Update deal_value if better
        if deal_data.get('deal_value') and deal_data['deal_value'] > 0:
            spac.deal_value = float(deal_data['deal_value'])
            print(f"✓ Set deal_value: ${deal_data['deal_value']}M")

        # Update deal structure fields
        structure_fields = {}

        if deal_data.get('min_cash'):
            structure_fields['min_cash'] = float(deal_data['min_cash'])
        if deal_data.get('min_cash_percentage'):
            structure_fields['min_cash_percentage'] = float(deal_data['min_cash_percentage'])
        if deal_data.get('pipe_size'):
            structure_fields['pipe_size'] = float(deal_data['pipe_size'])
        if deal_data.get('pipe_price'):
            structure_fields['pipe_price'] = float(deal_data['pipe_price'])
        if deal_data.get('earnout_shares'):
            structure_fields['earnout_shares'] = float(deal_data['earnout_shares'])
        if deal_data.get('forward_purchase'):
            structure_fields['forward_purchase'] = float(deal_data['forward_purchase'])

        if structure_fields:
            update_deal_structure(
                db_session=db,
                ticker='AACI',
                structure_data=structure_fields,
                source='8-K re-extraction',
                filing_date='2025-10-20'
            )
            print(f"✓ Updated deal structure fields: {list(structure_fields.keys())}")

        # Mark has_pipe if PIPE detected
        if deal_data.get('pipe_size') and deal_data['pipe_size'] > 0:
            spac.has_pipe = True
            print(f"✓ Set has_pipe: True")

        db.commit()
        print(f"\n✅ Database updated successfully")

        # Show final state
        print(f"\n📋 Final AACI data:")
        print(f"   Target: {spac.target}")
        print(f"   Deal Value: ${spac.deal_value}M")
        print(f"   Expected Close: {spac.expected_close}")
        print(f"   Sector: {spac.sector}")
        print(f"   Has PIPE: {spac.has_pipe}")
        print(f"   PIPE Size: ${spac.pipe_size}M" if spac.pipe_size else "   PIPE Size: N/A")
        print(f"   PIPE Price: ${spac.pipe_price}" if spac.pipe_price else "   PIPE Price: N/A")
        print(f"   Min Cash: ${spac.min_cash}M" if spac.min_cash else "   Min Cash: N/A")
        print(f"   Earnout Shares: {spac.earnout_shares}M" if spac.earnout_shares else "   Earnout Shares: N/A")

    finally:
        db.close()


if __name__ == "__main__":
    main()
