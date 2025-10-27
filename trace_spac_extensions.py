#!/usr/bin/env python3
"""
Generic SPAC Extension & Redemption Tracer

Analyzes all 8-K filings for a SPAC to find:
- Deadline extensions
- Extension payments
- Redemptions
- Trust cash balances

Usage:
    python3 trace_spac_extensions.py TICKER [--months MONTHS]

Example:
    python3 trace_spac_extensions.py DMYY --months 24
"""

import sys
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import argparse

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from openai import OpenAI

# AI client for extraction
AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

HEADERS = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}


def get_spac_cik(ticker: str) -> tuple:
    """Get SPAC CIK from database"""
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            return None, None
        return spac.cik, spac.ipo_date
    finally:
        db.close()


def fetch_recent_8ks(cik: str, lookback_date: datetime):
    """Fetch all 8-K filings since lookback date"""
    print(f"📥 Fetching 8-K filings since {lookback_date.strftime('%Y-%m-%d')}...")

    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=exclude&count=100&output=atom"

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    from xml.etree import ElementTree as ET
    root = ET.fromstring(response.content)

    # Parse atom feed
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('atom:entry', ns)

    filings = []
    for entry in entries:
        title_elem = entry.find('atom:title', ns)
        updated_elem = entry.find('atom:updated', ns)
        link_elem = entry.find('atom:link[@rel="alternate"]', ns)

        if title_elem is not None and updated_elem is not None and link_elem is not None:
            filing_date = datetime.fromisoformat(updated_elem.text.replace('Z', '+00:00'))

            # Only get filings from lookback date onwards
            if filing_date >= lookback_date.replace(tzinfo=filing_date.tzinfo):
                filings.append({
                    'date': filing_date,
                    'url': link_elem.get('href'),
                    'title': title_elem.text
                })

    print(f"   Found {len(filings)} 8-K filings\n")
    return filings


def fetch_filing_content(url: str) -> str:
    """Fetch filing HTML content"""

    # If it's an index page, parse it to find the primary document
    if '-index.htm' in url:
        # Fetch the index page
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the table with filing documents
        # Look for the first .htm file (primary document) in the table
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 3:
                # Check if this is a document row (has Type, Description, Document columns)
                link_cell = cells[2] if len(cells) > 2 else None
                if link_cell:
                    link = link_cell.find('a', href=True)
                    if link and link['href'].endswith('.htm') and not link['href'].endswith('-index.htm'):
                        # Found the primary document
                        doc_url = 'https://www.sec.gov' + link['href']
                        break
        else:
            # Fallback: Try to construct URL from accession number
            # Extract accession number from index URL
            # e.g., /Archives/edgar/data/1915380/000119312523305669/0001193125-23-305669-index.htm
            import re
            match = re.search(r'/(\d{10})-(\d{2})-(\d{6})-index\.htm', url)
            if match:
                accession = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                # Try common primary document name
                doc_url = url.replace('-index.htm', '.htm')
            else:
                raise Exception("Could not find primary document in index page")
    else:
        doc_url = url

    # Fetch the actual document
    response = requests.get(doc_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')

    # For inline XBRL viewer, try to get the raw document instead
    if '/ix?doc=' in doc_url:
        # Extract the document path from inline viewer URL
        import re
        match = re.search(r'/ix\?doc=(.+)', doc_url)
        if match:
            raw_doc_url = 'https://www.sec.gov' + match.group(1)
            try:
                response = requests.get(raw_doc_url, headers=HEADERS, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
            except:
                pass  # Use the inline viewer version

    # Remove scripts, styles
    for tag in soup(['script', 'style', 'meta', 'link']):
        tag.decompose()

    text = soup.get_text(separator=' ', strip=True)
    text = ' '.join(text.split())  # Clean whitespace

    return text[:50000]  # Limit to first 50k chars


def check_for_extension(filing_date: datetime, content: str) -> dict:
    """Use AI to check if filing contains deadline extension"""

    excerpt = content[:30000]  # First 30k chars

    prompt = f"""
Analyze this SEC 8-K filing from {filing_date.strftime('%Y-%m-%d')} for deadline extensions and redemptions.

Look for:
1. Extension of combination period / deadline
2. New deadline date
3. Extension payment amount (deposit to trust)
4. Extension number (1st, 2nd, 3rd, etc.)
5. **Redemptions**: How many shares were redeemed?
6. **Redemption Price**: Price per share paid for redemptions
7. **Remaining Cash**: Trust account cash after redemptions

Return JSON:
{{
    "is_extension": true/false,
    "new_deadline": "YYYY-MM-DD" or null,
    "extension_payment": 100000 (numeric, no $ or commas) or null,
    "extension_number": 1 (integer) or null,
    "shares_redeemed": 1000000 (numeric shares redeemed) or null,
    "redemption_price": 10.00 (price per share) or null,
    "remaining_trust_cash": 50000000 (total cash in trust after redemptions) or null,
    "summary": "Brief description"
}}

If NOT an extension filing, return {{"is_extension": false, "summary": "Brief description of what this 8-K is about"}}

Filing text:
{excerpt}
"""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an SEC filing analyst. Extract deadline extension data precisely. Return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        data = json.loads(response.choices[0].message.content)
        return data

    except Exception as e:
        print(f"      ❌ AI extraction failed: {e}")
        return {"is_extension": False, "summary": "Error analyzing"}


def main():
    parser = argparse.ArgumentParser(description='Trace SPAC extensions and redemptions')
    parser.add_argument('ticker', help='SPAC ticker symbol')
    parser.add_argument('--months', type=int, default=12, help='Months to look back (default: 12)')
    args = parser.parse_args()

    ticker = args.ticker.upper()
    lookback_months = args.months

    print(f"🔍 {ticker} Extension & Redemption Tracer")
    print("=" * 60)

    # Get CIK
    cik, ipo_date = get_spac_cik(ticker)
    if not cik:
        print(f"❌ {ticker} not found in database")
        return

    print(f"CIK: {cik}")
    if ipo_date:
        print(f"IPO Date: {ipo_date.strftime('%Y-%m-%d')}")

    # Calculate lookback date
    lookback_date = datetime.now() - timedelta(days=lookback_months * 30)
    if ipo_date and ipo_date > lookback_date.date():
        lookback_date = datetime.combine(ipo_date, datetime.min.time())

    # Fetch all 8-Ks
    filings = fetch_recent_8ks(cik, lookback_date)

    extensions = []
    other_filings = []

    for i, filing in enumerate(filings, 1):
        print(f"\n[{i}/{len(filings)}] {filing['date'].strftime('%Y-%m-%d')} - Analyzing...")

        # Fetch content
        try:
            content = fetch_filing_content(filing['url'])
        except Exception as e:
            print(f"   ❌ Failed to fetch: {e}")
            continue

        # Check for extension
        result = check_for_extension(filing['date'], content)

        if result.get('is_extension'):
            print(f"   ✅ EXTENSION FOUND!")
            print(f"      New Deadline: {result.get('new_deadline')}")
            print(f"      Payment: ${result.get('extension_payment'):,}" if result.get('extension_payment') else "      Payment: N/A")
            print(f"      Extension #{result.get('extension_number')}" if result.get('extension_number') else "")

            # Redemption data
            if result.get('shares_redeemed'):
                print(f"      🔄 Redemptions: {result.get('shares_redeemed'):,} shares @ ${result.get('redemption_price', 'N/A')}")
            if result.get('remaining_trust_cash'):
                print(f"      💰 Trust Cash Remaining: ${result.get('remaining_trust_cash'):,}")

            print(f"      Summary: {result.get('summary')}")

            extensions.append({
                'date': filing['date'].strftime('%Y-%m-%d'),
                'url': filing['url'],
                **result
            })
        else:
            print(f"   ℹ️  Not an extension: {result.get('summary', 'Unknown')}")
            other_filings.append({
                'date': filing['date'].strftime('%Y-%m-%d'),
                'summary': result.get('summary', 'Unknown')
            })

    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 SUMMARY")
    print("=" * 60)
    print(f"Total Extensions Found: {len(extensions)}")

    if extensions:
        print("\n🗓️  Extension Timeline:")
        for ext in extensions:
            print(f"   {ext['date']}: Deadline extended to {ext.get('new_deadline', 'N/A')}")
            if ext.get('extension_payment'):
                print(f"              Payment: ${ext['extension_payment']:,}")
            if ext.get('shares_redeemed'):
                print(f"              Redemptions: {ext['shares_redeemed']:,} shares @ ${ext.get('redemption_price', 'N/A')}")
            if ext.get('remaining_trust_cash'):
                print(f"              Trust Cash: ${ext['remaining_trust_cash']:,}")

        # Find most recent extension
        latest = extensions[0]  # Already sorted by date desc
        print(f"\n✅ CURRENT DEADLINE: {latest.get('new_deadline')}")
        print(f"   (from {latest['date']} extension)")

        if latest.get('remaining_trust_cash'):
            print(f"\n💰 CURRENT TRUST CASH: ${latest.get('remaining_trust_cash'):,}")

        # Save to file
        output_file = f'/tmp/{ticker.lower()}_extensions.json'
        with open(output_file, 'w') as f:
            json.dump({'extensions': extensions, 'other_filings': other_filings}, f, indent=2)
        print(f"\n💾 Full results saved to {output_file}")
    else:
        print("\n⚠️  No extensions found in analyzed filings")


if __name__ == "__main__":
    main()
