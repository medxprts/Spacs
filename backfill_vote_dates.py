#!/usr/bin/env python3
"""
Backfill shareholder vote dates from DEF 14A filings for announced deals

Searches for DEF 14A, DEFM14A, PREM14A filings for all announced SPACs
and extracts vote dates using AI.
"""

import sys
import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

HEADERS = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}


def get_announced_spacs():
    """Get all announced SPACs without vote dates"""
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'ANNOUNCED',
            SPAC.shareholder_vote_date.is_(None)
        ).all()
        return [(s.ticker, s.cik, s.target, s.announced_date) for s in spacs]
    finally:
        db.close()


def search_def14a_filings(cik: str, since_date: datetime):
    """Search for DEF 14A filings since a given date"""

    # Try all proxy filing types
    filing_types = ['DEF 14A', 'DEFM14A', 'PREM14A']
    all_filings = []

    for filing_type in filing_types:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={filing_type.replace(' ', '+')}&dateb=&owner=exclude&count=10&output=atom"

        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()

            from xml.etree import ElementTree as ET
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}

            entries = root.findall('atom:entry', ns)

            for entry in entries:
                title_elem = entry.find('atom:title', ns)
                updated_elem = entry.find('atom:updated', ns)
                link_elem = entry.find('atom:link[@rel="alternate"]', ns)

                if all([title_elem, updated_elem, link_elem]):
                    filing_date = datetime.fromisoformat(updated_elem.text.replace('Z', '+00:00'))

                    # Only get filings after deal announcement
                    if filing_date.replace(tzinfo=None) >= since_date:
                        all_filings.append({
                            'type': filing_type,
                            'date': filing_date,
                            'url': link_elem.get('href'),
                            'title': title_elem.text
                        })
        except Exception as e:
            print(f"   ⚠️  Error searching {filing_type}: {e}")

    return all_filings


def fetch_filing_content(filing_url: str):
    """Fetch filing content"""

    try:
        # If index page, find primary document
        if '-index.htm' in filing_url:
            response = requests.get(filing_url, headers=HEADERS, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find first .htm document
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    link_cell = cells[2]
                    if link_cell:
                        link = link_cell.find('a', href=True)
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

        return text[:15000]  # First 15k chars

    except Exception as e:
        print(f"      ⚠️  Error fetching: {e}")
        return None


def extract_vote_date_with_ai(content: str, ticker: str):
    """Extract vote date using AI"""

    prompt = f"""Extract shareholder meeting information from this proxy filing for SPAC {ticker}.

Look for:
1. Meeting date (e.g., "special meeting will be held on November 15, 2025")
2. Record date (who can vote)
3. Meeting time

Return JSON:
{{
  "vote_date": "YYYY-MM-DD",
  "record_date": "YYYY-MM-DD" or null,
  "meeting_time": "HH:MM AM/PM" or null
}}

If no meeting date is found, return {{"vote_date": null}}

Proxy text:
{content}
"""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an SEC filing analyst. Extract dates precisely. Return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        data = json.loads(response.choices[0].message.content)

        if data.get('vote_date'):
            try:
                vote_date = datetime.strptime(data['vote_date'], '%Y-%m-%d').date()
                return {
                    'vote_date': vote_date,
                    'record_date': datetime.strptime(data['record_date'], '%Y-%m-%d').date() if data.get('record_date') else None,
                    'meeting_time': data.get('meeting_time')
                }
            except:
                return None

        return None

    except Exception as e:
        print(f"      ⚠️  AI extraction failed: {e}")
        return None


def update_vote_date(ticker: str, vote_data: dict):
    """Update database with vote date"""

    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            return False

        spac.shareholder_vote_date = vote_data['vote_date']

        if not spac.proxy_filed_date:
            spac.proxy_filed_date = datetime.now().date()

        db.commit()
        return True

    except Exception as e:
        print(f"      ⚠️  Database update failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    print("🗳️  SHAREHOLDER VOTE DATE BACKFILL")
    print("=" * 70)

    # Get announced SPACs without vote dates
    spacs = get_announced_spacs()
    print(f"\nFound {len(spacs)} announced SPACs without vote dates\n")

    updated = 0
    not_found = 0

    for ticker, cik, target, announced_date in spacs:
        print(f"📊 {ticker} → {target}")
        print(f"   Announced: {announced_date.strftime('%Y-%m-%d') if announced_date else 'Unknown'}")

        if not cik:
            print(f"   ⚠️  No CIK - skipping\n")
            continue

        # Search for DEF 14A filings since announcement
        search_date = announced_date if announced_date else datetime.now() - timedelta(days=180)
        filings = search_def14a_filings(cik, search_date)

        if not filings:
            print(f"   ℹ️  No proxy filings found yet\n")
            not_found += 1
            continue

        print(f"   📄 Found {len(filings)} proxy filing(s)")

        # Try most recent filing first
        for filing in filings:
            print(f"      {filing['type']} from {filing['date'].strftime('%Y-%m-%d')}")

            content = fetch_filing_content(filing['url'])
            if not content:
                continue

            vote_data = extract_vote_date_with_ai(content, ticker)

            if vote_data:
                print(f"      ✅ Vote date extracted: {vote_data['vote_date']}")

                if update_vote_date(ticker, vote_data):
                    print(f"      ✅ Database updated")
                    updated += 1
                    break
        else:
            print(f"   ⚠️  Could not extract vote date from filings")
            not_found += 1

        print()

    print("\n" + "=" * 70)
    print(f"📊 SUMMARY")
    print("=" * 70)
    print(f"Total SPACs processed: {len(spacs)}")
    print(f"✅ Vote dates found: {updated}")
    print(f"⚠️  No proxy filed yet: {not_found}")


if __name__ == "__main__":
    main()
