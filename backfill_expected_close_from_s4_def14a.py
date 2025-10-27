#!/usr/bin/env python3
"""
Backfill Expected Close Dates from S-4 and DEF 14A Filings

Searches for S-4 registration statements and DEF 14A proxies for deals
missing expected_close dates. These filings almost always contain expected
close dates even if the initial 8-K didn't mention them.
"""

import sys
import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json
import time

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
SEC_BASE_URL = "https://www.sec.gov"


def get_cik_filings(cik: str, filing_type: str, after_date: datetime, limit: int = 5) -> list:
    """
    Get recent filings of a specific type from SEC API

    Args:
        cik: CIK number (with leading zeros)
        filing_type: 'S-4' or 'DEF 14A'
        after_date: Only get filings after this date
        limit: Max number of filings to return
    """

    # Ensure CIK is 10 digits with leading zeros
    cik_padded = cik.zfill(10)

    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json()

        # Extract filings
        recent_filings = data.get('filings', {}).get('recent', {})

        if not recent_filings:
            return []

        # Build list of filings
        filings = []
        forms = recent_filings.get('form', [])
        filing_dates = recent_filings.get('filingDate', [])
        accession_numbers = recent_filings.get('accessionNumber', [])

        for i in range(len(forms)):
            form = forms[i]
            filing_date_str = filing_dates[i]
            accession = accession_numbers[i]

            # Parse filing date
            try:
                filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d')
            except:
                continue

            # Filter by type and date
            if form == filing_type and filing_date >= after_date:
                # Remove hyphens from accession number for URL
                accession_clean = accession.replace('-', '')

                filing_url = f"{SEC_BASE_URL}/Archives/edgar/data/{int(cik)}/{accession_clean}/{accession}-index.htm"

                filings.append({
                    'type': form,
                    'date': filing_date,
                    'url': filing_url,
                    'accession': accession
                })

                if len(filings) >= limit:
                    break

        return filings

    except Exception as e:
        print(f"      ⚠️  Error fetching filings: {e}")
        return []


def fetch_filing_content(filing_url: str, filing_type: str) -> str:
    """Fetch and clean filing content"""

    try:
        # Get filing index page
        response = requests.get(filing_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find main document
        doc_url = None
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()

            if '.htm' in href and not '.xml' in href:
                if filing_type == 'S-4':
                    if any(term in href for term in ['s4', '424b3', 'form']):
                        doc_url = SEC_BASE_URL + link['href']
                        break
                elif filing_type == 'DEF 14A':
                    if any(term in href for term in ['def14a', 'formdef', '14a']):
                        doc_url = SEC_BASE_URL + link['href']
                        break

        # Fallback: first .htm file
        if not doc_url:
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                if '.htm' in href and not '.xml' in href and 'index' not in href:
                    doc_url = SEC_BASE_URL + link['href']
                    break

        if not doc_url:
            return None

        # Fetch document
        response = requests.get(doc_url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove scripts, styles
        for tag in soup(['script', 'style', 'meta', 'link']):
            tag.decompose()

        text = soup.get_text(separator=' ', strip=True)
        text = ' '.join(text.split())

        # Return first 25k chars for S-4, 15k for DEF 14A
        max_length = 25000 if filing_type == 'S-4' else 15000
        return text[:max_length]

    except Exception as e:
        print(f"      ⚠️  Error fetching content: {e}")
        return None


def extract_expected_close_with_ai(content: str, ticker: str, target: str, filing_type: str) -> dict:
    """Extract expected close date using AI"""

    prompt = f"""Extract the expected closing date from this SPAC {filing_type} filing.

SPAC: {ticker}
Target: {target}

Look for phrases like:
- "expected to close in Q1 2026"
- "anticipated closing in the second half of 2025"
- "transaction is expected to be completed by December 31, 2025"
- "closing expected in early 2026"
- "the business combination is currently expected to close"

Return JSON:
{{
    "expected_close": "Q1 2026" or "H2 2025" or "2025-12-31" or null
}}

If no closing date is mentioned, return {{"expected_close": null}}

Document excerpt:
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


def backfill_expected_close_from_s4_def14a(dry_run=True):
    """Backfill expected_close dates from S-4 and DEF 14A filings"""

    db = SessionLocal()

    try:
        # Get announced deals without expected_close that have CIK
        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'ANNOUNCED',
            SPAC.cik.isnot(None)
        ).filter(
            (SPAC.expected_close.is_(None)) |
            (SPAC.expected_close.in_(['-', 'TBD', 'N/A']))
        ).all()

        print(f"📅 Expected Close Date Extraction from S-4 and DEF 14A Filings")
        print(f"==" * 35)
        print(f"Found {len(spacs)} deals missing expected_close\\n")

        extracted = 0
        not_found = 0
        errors = 0

        for spac in spacs:
            print(f"📊 {spac.ticker:6s} → {spac.target}")
            print(f"   CIK: {spac.cik}")
            print(f"   Announced: {spac.announced_date.strftime('%Y-%m-%d')}")

            # Search for S-4 filed after announcement
            after_date = spac.announced_date - timedelta(days=7)  # Allow 7 days before announcement

            # Try S-4 first (most comprehensive)
            print(f"   🔍 Searching for S-4 filings...")
            s4_filings = get_cik_filings(spac.cik, 'S-4', after_date, limit=3)

            if s4_filings:
                print(f"   ✓ Found {len(s4_filings)} S-4 filing(s)")

                for filing in s4_filings:
                    print(f"      📄 S-4 from {filing['date'].strftime('%Y-%m-%d')}")

                    content = fetch_filing_content(filing['url'], 'S-4')
                    if not content:
                        continue

                    result = extract_expected_close_with_ai(content, spac.ticker, spac.target, 'S-4')

                    if result and result.get('expected_close'):
                        expected_close_text = result['expected_close']
                        expected_close_date = normalize_expected_close(expected_close_text)

                        if expected_close_date:
                            print(f"      ✅ Extracted: '{expected_close_text}' → {expected_close_date}")

                            if not dry_run:
                                spac.expected_close = expected_close_date
                                db.commit()

                            extracted += 1
                            break  # Found it, move to next SPAC
                        else:
                            print(f"      ⚠️  Could not normalize: '{expected_close_text}'")

                    time.sleep(0.2)  # Rate limit
                else:
                    # Tried all S-4s, try DEF 14A
                    print(f"   🔍 Searching for DEF 14A filings...")
                    def14a_filings = get_cik_filings(spac.cik, 'DEF 14A', after_date, limit=2)

                    if def14a_filings:
                        print(f"   ✓ Found {len(def14a_filings)} DEF 14A filing(s)")

                        for filing in def14a_filings:
                            print(f"      📄 DEF 14A from {filing['date'].strftime('%Y-%m-%d')}")

                            content = fetch_filing_content(filing['url'], 'DEF 14A')
                            if not content:
                                continue

                            result = extract_expected_close_with_ai(content, spac.ticker, spac.target, 'DEF 14A')

                            if result and result.get('expected_close'):
                                expected_close_text = result['expected_close']
                                expected_close_date = normalize_expected_close(expected_close_text)

                                if expected_close_date:
                                    print(f"      ✅ Extracted: '{expected_close_text}' → {expected_close_date}")

                                    if not dry_run:
                                        spac.expected_close = expected_close_date
                                        db.commit()

                                    extracted += 1
                                    break  # Found it
                                else:
                                    print(f"      ⚠️  Could not normalize: '{expected_close_text}'")

                            time.sleep(0.2)  # Rate limit
                        else:
                            print(f"   ℹ️  No expected close found in any filing")
                            not_found += 1
                    else:
                        print(f"   ℹ️  No DEF 14A filings found")
                        not_found += 1
            else:
                # No S-4, try DEF 14A
                print(f"   ℹ️  No S-4 filings found, trying DEF 14A...")
                def14a_filings = get_cik_filings(spac.cik, 'DEF 14A', after_date, limit=2)

                if def14a_filings:
                    print(f"   ✓ Found {len(def14a_filings)} DEF 14A filing(s)")

                    for filing in def14a_filings:
                        print(f"      📄 DEF 14A from {filing['date'].strftime('%Y-%m-%d')}")

                        content = fetch_filing_content(filing['url'], 'DEF 14A')
                        if not content:
                            continue

                        result = extract_expected_close_with_ai(content, spac.ticker, spac.target, 'DEF 14A')

                        if result and result.get('expected_close'):
                            expected_close_text = result['expected_close']
                            expected_close_date = normalize_expected_close(expected_close_text)

                            if expected_close_date:
                                print(f"      ✅ Extracted: '{expected_close_text}' → {expected_close_date}")

                                if not dry_run:
                                    spac.expected_close = expected_close_date
                                    db.commit()

                                extracted += 1
                                break  # Found it
                            else:
                                print(f"      ⚠️  Could not normalize: '{expected_close_text}'")

                        time.sleep(0.2)  # Rate limit
                    else:
                        print(f"   ℹ️  No expected close found in any filing")
                        not_found += 1
                else:
                    print(f"   ℹ️  No filings found")
                    not_found += 1

            print()
            time.sleep(0.3)  # SEC rate limiting

        if dry_run:
            print(f"\\n💡 DRY RUN - No changes made")
        else:
            print(f"\\n✅ Database updated")

        print(f"\\n" + "==" * 35)
        print(f"📊 SUMMARY")
        print(f"==" * 35)
        print(f"Total deals processed:  {len(spacs)}")
        print(f"✅ Extracted:            {extracted}")
        print(f"ℹ️  Not found in filings: {not_found}")
        print(f"❌ Errors:               {errors}")
        print(f"\\n📈 New hit rate: {extracted + 22}/{45} = {100.0 * (extracted + 22) / 45:.1f}% (22 already had dates)")

        return extracted

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Backfill expected close dates from S-4 and DEF 14A filings')
    parser.add_argument('--commit', action='store_true', help='Actually update database (default is dry-run)')
    args = parser.parse_args()

    backfill_expected_close_from_s4_def14a(dry_run=not args.commit)
