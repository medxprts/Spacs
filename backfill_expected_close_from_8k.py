#!/usr/bin/env python3
"""
Backfill Expected Close Dates from 8-K Press Releases

Re-scrapes all announced deal 8-Ks to extract expected_close dates using AI.
Uses the same extraction logic as deal_detector_agent.py.
"""

import sys
import os
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import json

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from utils.expected_close_normalizer import normalize_expected_close

# AI for extraction
try:
    from openai import OpenAI
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False
    print("⚠️  AI not available - cannot extract expected_close")
    sys.exit(1)

HEADERS = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}


def fetch_filing_content(filing_url: str) -> str:
    """Fetch and clean filing content"""
    try:
        # Handle index pages
        if '-index.htm' in filing_url:
            response = requests.get(filing_url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find first .htm document (usually the press release)
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    link = cells[2].find('a', href=True)
                    if link and link['href'].endswith('.htm') and not link['href'].endswith('-index.htm'):
                        filing_url = 'https://www.sec.gov' + link['href']
                        break

        # Fetch document
        response = requests.get(filing_url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove scripts, styles
        for tag in soup(['script', 'style', 'meta', 'link']):
            tag.decompose()

        text = soup.get_text(separator=' ', strip=True)
        text = ' '.join(text.split())

        return text[:20000]  # First 20k chars

    except Exception as e:
        print(f"      ⚠️  Error fetching: {e}")
        return None


def extract_expected_close_with_ai(content: str, ticker: str, target: str) -> dict:
    """Extract expected close date using AI"""

    prompt = f"""Extract the expected closing date from this SPAC merger press release.

SPAC: {ticker}
Target: {target}

Look for phrases like:
- "expected to close in Q1 2026"
- "anticipated closing in the second half of 2025"
- "transaction is expected to be completed by December 31, 2025"
- "closing expected in early 2026"

Return JSON:
{{
    "expected_close": "Q1 2026" or "H2 2025" or "2025-12-31" or null
}}

If no closing date is mentioned, return {{"expected_close": null}}

Press release text:
{content}
"""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an SEC filing analyst. Extract expected closing dates precisely. Return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        data = json.loads(response.choices[0].message.content)
        return data

    except Exception as e:
        print(f"      ⚠️  AI extraction failed: {e}")
        return None


def backfill_expected_close_from_8k(dry_run=True):
    """Backfill expected_close dates from 8-K filings"""

    db = SessionLocal()

    try:
        # Get announced deals without expected_close
        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'ANNOUNCED',
            SPAC.deal_filing_url.isnot(None)
        ).filter(
            (SPAC.expected_close.is_(None)) |
            (SPAC.expected_close.in_(['-', 'TBD', 'N/A']))
        ).all()

        print(f"📅 Expected Close Date Extraction from 8-Ks")
        print(f"=" * 70)
        print(f"Found {len(spacs)} deals with 8-K URLs but no expected_close\n")

        extracted = 0
        not_found = 0
        errors = 0

        for spac in spacs:
            print(f"📊 {spac.ticker:6s} → {spac.target}")
            print(f"   Announced: {spac.announced_date.strftime('%Y-%m-%d')}")
            print(f"   8-K URL: {spac.deal_filing_url[:80]}...")

            # Fetch filing content
            content = fetch_filing_content(spac.deal_filing_url)
            if not content:
                print(f"   ❌ Could not fetch filing\n")
                errors += 1
                continue

            # Extract with AI
            result = extract_expected_close_with_ai(content, spac.ticker, spac.target)

            if result and result.get('expected_close'):
                expected_close_text = result['expected_close']

                # Normalize to proper date
                expected_close_date = normalize_expected_close(expected_close_text)

                if expected_close_date:
                    print(f"   ✅ Extracted: '{expected_close_text}' → {expected_close_date}")

                    if not dry_run:
                        spac.expected_close = expected_close_date
                        db.commit()

                    extracted += 1
                else:
                    print(f"   ⚠️  Extracted '{expected_close_text}' but could not normalize")
                    not_found += 1
            else:
                print(f"   ℹ️  No expected close date found in filing")
                not_found += 1

            print()

        if dry_run:
            print(f"\n💡 DRY RUN - No changes made")
        else:
            print(f"\n✅ Database updated")

        print(f"\n" + "=" * 70)
        print(f"📊 SUMMARY")
        print(f"=" * 70)
        print(f"Total deals processed:  {len(spacs)}")
        print(f"✅ Extracted:            {extracted}")
        print(f"ℹ️  Not found in filing:  {not_found}")
        print(f"❌ Errors:               {errors}")
        print(f"\n📈 New hit rate: {extracted}/{len(spacs) + 8} = {100.0 * extracted / (len(spacs) + 8):.1f}% (8 already had dates)")

        return extracted

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Backfill expected close dates from 8-K filings')
    parser.add_argument('--commit', action='store_true', help='Actually update database (default is dry-run)')
    args = parser.parse_args()

    backfill_expected_close_from_8k(dry_run=not args.commit)
