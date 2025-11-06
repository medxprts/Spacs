#!/usr/bin/env python3
"""
Comprehensive 424B4 Extractor
=============================
Extracts ALL key data points from 424B4 prospectus for newly public SPACs.

Should run automatically after IPO graduation (from ipo_detector_agent).

Extracts:
- Founder shares count
- Shares outstanding (base + with overallotment)
- Banker/underwriter (with tier classification)
- Promote vesting terms
- Warrant terms (exercise price, ratio, expiration)
- Extension terms (months available, deposit per share)
- Unit structure
- Overallotment details

Usage:
    python3 comprehensive_424b4_extractor.py --ticker AIIA    # Single SPAC
    python3 comprehensive_424b4_extractor.py --all-missing    # All SPACs missing data
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
import requests
from bs4 import BeautifulSoup
import re
import time
import argparse
from datetime import datetime
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


def fetch_424b4_content(url):
    """Fetch 424B4 document content"""
    headers = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        text = soup.get_text()

        return text
    except Exception as e:
        print(f"  ❌ Error fetching 424B4: {e}")
        return None


def extract_with_ai(text, ticker):
    """Use AI to extract comprehensive data from 424B4"""
    if not AI_AVAILABLE:
        return {}

    # Truncate to 50k chars for AI
    text_excerpt = text[:50000]

    prompt = f"""Extract SPAC IPO data from this 424B4 prospectus for {ticker}. Return ONLY valid JSON with NO markdown.

Extract these fields (use null if not found):

{{
  "founder_shares": <number>,  // Count of founder/sponsor shares
  "shares_outstanding_base": <number>,  // Total shares before overallotment (usually in millions)
  "shares_outstanding_with_overallotment": <number>,  // Total shares after overallotment
  "overallotment_units": <number>,  // Overallotment option size
  "overallotment_percentage": <number>,  // Overallotment as percentage (usually 15)
  "banker": "<string>",  // Lead underwriter/representative
  "warrant_exercise_price": <number>,  // Warrant strike price (usually 11.50)
  "warrant_ratio": "<string>",  // Warrants per share (e.g. "1/2" or "1")
  "extension_months_available": <number>,  // Months of extensions available (3, 6, or 12)
  "extension_deposit_per_share": <number>,  // Deposit per share for extension (e.g. 0.03)
  "max_deadline_with_extensions": <number>  // Total months to deadline with extensions (18, 24, 27, 30, 36)
}}

Text excerpt:
{text_excerpt}

Return ONLY the JSON object, no explanation."""

    try:
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


def classify_banker_tier(banker_name):
    """Classify banker tier"""
    if not banker_name:
        return None

    from data.banker_tiers import get_banker_tier
    tier, points = get_banker_tier(banker_name)
    return tier


def extract_all_data(spac):
    """Extract all data from 424B4 for a SPAC"""
    if not spac.prospectus_424b4_url:
        print(f"  ❌ No 424B4 URL for {spac.ticker}")
        return False

    print(f"\n🔍 Extracting comprehensive data for {spac.ticker}...")
    print(f"   URL: {spac.prospectus_424b4_url[:80]}...")

    # Fetch content
    content = fetch_424b4_content(spac.prospectus_424b4_url)
    if not content:
        print(f"  ❌ Could not fetch content")
        return False

    # Extract with AI
    ai_data = extract_with_ai(content, spac.ticker)
    if not ai_data:
        print(f"  ❌ No data extracted")
        return False

    # Update SPAC record
    updates = []

    if ai_data.get('founder_shares') and not spac.founder_shares:
        spac.founder_shares = ai_data['founder_shares']
        updates.append(f"founder_shares: {ai_data['founder_shares']:,}")

    if ai_data.get('shares_outstanding_base') and not spac.shares_outstanding_base:
        spac.shares_outstanding_base = ai_data['shares_outstanding_base']
        updates.append(f"shares_outstanding_base: {ai_data['shares_outstanding_base']:,}")

    if ai_data.get('shares_outstanding_with_overallotment') and not spac.shares_outstanding_with_overallotment:
        spac.shares_outstanding_with_overallotment = ai_data['shares_outstanding_with_overallotment']
        updates.append(f"shares_outstanding_with_overallotment: {ai_data['shares_outstanding_with_overallotment']:,}")

    if ai_data.get('overallotment_units') and not spac.overallotment_units:
        spac.overallotment_units = ai_data['overallotment_units']
        updates.append(f"overallotment_units: {ai_data['overallotment_units']:,}")

    if ai_data.get('overallotment_percentage') and not spac.overallotment_percentage:
        spac.overallotment_percentage = ai_data['overallotment_percentage']
        updates.append(f"overallotment_percentage: {ai_data['overallotment_percentage']}%")

    if ai_data.get('banker') and not spac.banker:
        spac.banker = ai_data['banker']
        tier = classify_banker_tier(ai_data['banker'])
        if tier:
            spac.banker_tier = tier
            updates.append(f"banker: {ai_data['banker']} ({tier})")
        else:
            updates.append(f"banker: {ai_data['banker']} (tier unknown)")

    if ai_data.get('warrant_exercise_price') and not spac.warrant_exercise_price:
        spac.warrant_exercise_price = ai_data['warrant_exercise_price']
        updates.append(f"warrant_exercise_price: ${ai_data['warrant_exercise_price']}")

    if ai_data.get('warrant_ratio') and not spac.warrant_ratio:
        ratio_str = ai_data['warrant_ratio']
        # Convert fraction to decimal (e.g. "1/2" -> 0.5)
        if '/' in str(ratio_str):
            parts = str(ratio_str).split('/')
            ratio = float(parts[0]) / float(parts[1])
        else:
            ratio = float(ratio_str)
        spac.warrant_ratio = ratio
        updates.append(f"warrant_ratio: {ai_data['warrant_ratio']} = {ratio}")

    if ai_data.get('extension_months_available') and not spac.extension_months_available:
        spac.extension_months_available = ai_data['extension_months_available']
        updates.append(f"extension_months: {ai_data['extension_months_available']}")

    if ai_data.get('extension_deposit_per_share') and not spac.extension_deposit_per_share:
        spac.extension_deposit_per_share = ai_data['extension_deposit_per_share']
        updates.append(f"extension_deposit: ${ai_data['extension_deposit_per_share']}")

    if ai_data.get('max_deadline_with_extensions') and not spac.max_deadline_with_extensions:
        spac.max_deadline_with_extensions = ai_data['max_deadline_with_extensions']
        updates.append(f"max_deadline: {ai_data['max_deadline_with_extensions']} months")

    if updates:
        print(f"   ✅ Updated {len(updates)} fields:")
        for update in updates:
            print(f"      - {update}")
        return True
    else:
        print(f"   ⚠️  No new data to update (fields already populated)")
        return False


def extract_single(ticker):
    """Extract data for a single SPAC"""
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker.upper()).first()
        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return

        success = extract_all_data(spac)
        if success:
            db.commit()
            print(f"\n✅ Committed updates to database")

    finally:
        db.close()


def extract_all_missing():
    """Extract data for all SPACs missing key fields"""
    db = SessionLocal()
    try:
        # Find SPACs missing critical fields
        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'SEARCHING',
            SPAC.prospectus_424b4_url != None,
            (SPAC.founder_shares == None) |
            (SPAC.shares_outstanding_base == None) |
            (SPAC.banker == None)
        ).all()

        print(f"\n📊 Found {len(spacs)} SPACs missing data\n")

        success_count = 0
        for spac in spacs:
            if extract_all_data(spac):
                success_count += 1
                db.commit()

            time.sleep(0.5)  # Rate limiting

        print(f"\n✅ Extraction complete:")
        print(f"   Updated: {success_count}/{len(spacs)} SPACs")

    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Comprehensive 424B4 Data Extractor')
    parser.add_argument('--ticker', type=str, help='Extract for single SPAC')
    parser.add_argument('--all-missing', action='store_true', help='Extract for all SPACs missing data')

    args = parser.parse_args()

    if args.ticker:
        extract_single(args.ticker)
    elif args.all_missing:
        extract_all_missing()
    else:
        print("Usage: python3 comprehensive_424b4_extractor.py --ticker <TICKER> OR --all-missing")
        sys.exit(1)
