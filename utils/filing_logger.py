#!/usr/bin/env python3
"""
Filing Logger - Saves SEC filings to database for News Feed

Called by sec_filing_monitor.py to persist all detected filings.
Generates human-readable tags and AI-powered summaries.
"""

import sys
import os
from datetime import datetime, date
from typing import Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, FilingEvent
from sqlalchemy.exc import IntegrityError

# AI for summary generation
try:
    from openai import OpenAI
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False


# Filing type to human-readable tag mapping
FILING_TAGS = {
    # Deal-related
    '425': 'Deal Communication',
    'S-4': 'Deal Registration',
    'S-4/A': 'Deal Registration (Amended)',
    'F-4': 'Deal Registration (Foreign)',
    'F-4/A': 'Deal Registration (Foreign, Amended)',
    'DEFM14A': 'Deal Proxy',
    'DEFR14A': 'Deal Proxy (Revised)',
    'PREM14A': 'Deal Proxy (Preliminary)',
    'DEFA14A': 'Additional Deal Proxy Materials',
    'DEF 14A': 'Shareholder Vote',
    'SC TO': 'Tender Offer',
    'SC 13D': 'Large Shareholder Filing',
    'SC 13G': 'Passive Investment Filing',
    'SCHEDULE 13G': 'Passive Investment Filing',
    'SCHEDULE 13D': 'Large Shareholder Filing',

    # IPO-related
    'S-1': 'IPO Registration',
    'S-1/A': 'IPO Registration (Amended)',
    '424B4': 'IPO Pricing',
    '424B3': 'IPO Prospectus Supplement',
    '8-A12B': 'IPO Securities Registration',
    '8-A12G': 'IPO Securities Registration (OTC)',
    'CERT': 'Exchange Listing Certification',
    'POS AM': 'Post-Effective Amendment',

    # Financial reports
    '10-Q': 'Quarterly Report',
    '10-K': 'Annual Report',
    '10-Q/A': 'Quarterly Report (Amended)',
    '10-K/A': 'Annual Report (Amended)',
    '10-QT': 'Quarterly Report (Transition)',
    '10-KT': 'Annual Report (Transition)',

    # Events
    '8-K': '8-K Current Report',  # Will be refined by item number or AI
    '8-K/A': '8-K Current Report (Amended)',

    # Other
    'EFFECT': 'S-4 Effectiveness',
    '  EFFECT': 'S-4 Effectiveness',
    'Form 25': 'Delisting Notice',
    'NT 10-Q': 'Late Filing Notice (10-Q)',
    'NT 10-K': 'Late Filing Notice (10-K)',
    'FWP': 'Free Writing Prospectus',
    '424B2': 'IPO Prospectus Supplement',
    '424B5': 'IPO Prospectus Supplement',
    'CORRESP': 'SEC Correspondence'
}

# 8-K Item number to specific tag
EIGHT_K_TAGS = {
    '1.01': 'Deal Announcement',
    '1.02': 'Deal Termination',
    '1.03': 'Bankruptcy',
    '2.01': 'Deal Completion',
    '2.03': 'Obligation Creation',
    '3.01': 'Delisting Notice',
    '3.02': 'Unregistered Securities Sale',
    '3.03': 'Material Modification',
    '4.01': 'Changes in Accountants',
    '4.02': 'Financial Statement Non-Reliance',
    '5.01': 'Bankruptcy',
    '5.02': 'Officer Departure/Appointment',
    '5.03': 'Timeline Change',  # Extensions
    '5.05': 'Significant Listing Changes',
    '5.06': 'Charter Amendment',
    '5.07': 'Vote Results',
    '5.08': 'Unregistered Sales',
    '7.01': 'Regulation FD Disclosure',
    '8.01': 'Other Events',  # Often used for redemptions, extensions, misc
    '9.01': 'Financial Statements',
    'Item 3.01': 'Delisting Notice',
    'Item 5.03': 'Timeline Change'
}


def log_filing(filing: Dict) -> bool:
    """
    Log SEC filing to database for news feed

    Args:
        filing: Dictionary with keys:
            - ticker: SPAC ticker
            - type: Filing type (8-K, 424B4, etc.)
            - date: Filing date
            - url: SEC filing URL
            - title: Filing title (optional)
            - item_number: 8-K item number (optional)
            - classification: Classification dict from monitor (optional)

    Returns:
        True if successfully logged, False otherwise
    """

    db = SessionLocal()
    try:
        # Determine tag
        tag = _determine_tag(filing)

        # Determine priority
        priority = filing.get('classification', {}).get('priority', 'MEDIUM')

        # Get summary - prefer orchestrator's AI analysis over re-generation
        classification = filing.get('classification', {})
        orchestrator_summary = classification.get('reason', '')

        # Use orchestrator summary if it's detailed (not just the filing type)
        if orchestrator_summary and len(orchestrator_summary) > 20 and orchestrator_summary != filing['type']:
            summary = orchestrator_summary
        else:
            # Generate summary (AI-powered)
            summary = _generate_summary(filing)

        # Convert filing_date to date object if it's datetime
        filing_date = filing['date']
        if isinstance(filing_date, datetime):
            filing_date = filing_date.date()

        # Create filing event
        filing_event = FilingEvent(
            ticker=filing['ticker'],
            filing_type=filing['type'],
            filing_date=filing_date,
            filing_url=filing['url'],
            filing_title=filing.get('title'),
            tag=tag,
            priority=priority,
            item_number=filing.get('item_number'),
            summary=summary,
            detected_at=datetime.now(),
            processed=False
        )

        db.add(filing_event)
        db.commit()

        print(f"   ✅ Logged to news feed: {filing['ticker']} - {tag}")
        return True

    except IntegrityError:
        # Duplicate filing (already logged)
        db.rollback()
        return False

    except Exception as e:
        db.rollback()
        print(f"   ⚠️  Failed to log filing: {e}")
        return False

    finally:
        db.close()


def _determine_tag(filing: Dict) -> str:
    """Determine human-readable tag for filing"""

    filing_type = filing['type']

    # 8-K: Use item number for specific tag
    if filing_type in ['8-K', '8-K/A']:
        item_number = filing.get('item_number')
        if item_number:
            # Clean item number (remove "Item " prefix if present)
            item_clean = item_number.replace('Item ', '').strip()
            tag = EIGHT_K_TAGS.get(item_clean)
            if tag:
                return tag

        # Fallback: generic 8-K
        return '8-K Current Report'

    # Use predefined tag or filing type as fallback
    return FILING_TAGS.get(filing_type, filing_type)


def _extract_8k_item_section(full_text: str, item_number: str = None) -> str:
    """
    Extract specific Item section from 8-K filing

    Returns the content of the specified Item, or attempts to find
    the most relevant Item if not specified
    """
    import re

    if not full_text:
        return ''

    # Common Item patterns in 8-K filings
    item_patterns = [
        r'Item\s+(\d+\.\d+)[.\s]+([^\n]+)',  # "Item 1.01. Entry into Agreement"
        r'ITEM\s+(\d+\.\d+)[.\s]+([^\n]+)',  # Uppercase variant
        r'Item\s+(\d+\.\d+)\s*[\u2013\u2014-]\s*([^\n]+)',  # With dash
    ]

    # Find all Items in the document
    items_found = {}
    for pattern in item_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            item_num = match.group(1)
            item_title = match.group(2).strip()
            item_start = match.start()

            # Extract content until next Item or end
            next_item_match = re.search(
                r'Item\s+\d+\.\d+',
                full_text[item_start + 50:],  # Start search after current Item
                re.IGNORECASE
            )

            if next_item_match:
                item_end = item_start + 50 + next_item_match.start()
                item_content = full_text[item_start:item_end]
            else:
                # Last Item - grab next 3000 chars
                item_content = full_text[item_start:item_start + 3000]

            items_found[item_num] = {
                'title': item_title,
                'content': item_content
            }

    # If specific item_number requested, return that
    if item_number:
        item_clean = item_number.replace('Item ', '').strip()
        if item_clean in items_found:
            return items_found[item_clean]['content']

    # Otherwise, return the first non-signature Item found (usually most important)
    # Skip Item 9.01 (signatures) and common boilerplate items
    skip_items = ['9.01', '9.02', '5.02', '5.05']  # Signatures, listings
    for item_num, item_data in items_found.items():
        if item_num not in skip_items:
            return item_data['content']

    # Fallback: return beginning of doc
    return full_text[:3000]


def _generate_fallback_summary(filing: Dict) -> str:
    """
    Generate structured fallback summary when AI content fetch fails
    Uses classification context and filing metadata to create informative summary
    """
    filing_type = filing['type']
    ticker = filing['ticker']
    classification = filing.get('classification', {})
    reason = classification.get('reason', '')
    item_number = filing.get('item_number', '')

    # Use classification context if available
    if reason and reason != filing_type:
        # Classification provides useful context
        if filing_type == '425':
            return f"{ticker} filed Form 425 regarding business combination: {reason}"
        elif filing_type == '8-K':
            if item_number:
                return f"{ticker} filed 8-K (Item {item_number}): {reason}"
            else:
                return f"{ticker} filed 8-K: {reason}"
        elif filing_type == 'S-4':
            return f"{ticker} filed S-4 registration: {reason}"
        elif filing_type in ['DEFM14A', 'DEF 14A']:
            return f"{ticker} filed proxy statement: {reason}"
        else:
            return f"{ticker} filed {filing_type}: {reason}"

    # No useful classification context - use structured template
    if filing_type == '425':
        return f"{ticker} filed Form 425 communication regarding business combination (content pending analysis)"
    elif filing_type == '8-K':
        if item_number:
            item_desc = EIGHT_K_TAGS.get(item_number.replace('Item ', '').strip(), 'event')
            return f"{ticker} filed 8-K reporting {item_desc}"
        return f"{ticker} filed 8-K current report"
    elif filing_type == 'S-4':
        return f"{ticker} filed S-4 registration statement for business combination"
    elif filing_type in ['DEFM14A', 'DEF 14A']:
        return f"{ticker} filed definitive proxy statement for shareholder meeting"
    elif filing_type in ['PREM14A']:
        return f"{ticker} filed preliminary proxy statement"
    elif filing_type in ['10-Q', '10-K']:
        return f"{ticker} filed {filing_type} financial report"
    else:
        return f"{ticker} filed {filing_type}"


def _generate_summary(filing: Dict) -> Optional[str]:
    """Generate AI-powered summary of filing with intelligent classification"""

    if not AI_AVAILABLE:
        return None

    filing_type = filing['type']
    ticker = filing['ticker']
    item_number = filing.get('item_number', '')

    # Try to get classification reason (from SEC monitor)
    classification = filing.get('classification', {})
    reason = classification.get('reason', '')

    # Get filing content - NEVER use generic SEC summary
    content = filing.get('content', '')

    # For important filings, ALWAYS try to fetch content if not provided
    important_filings = ['425', 'S-4', 'DEFM14A', '8-K', '8-K/A', 'PREM14A', 'DEF 14A']

    if not content and filing_type in important_filings and filing.get('url'):
        try:
            from sec_text_extractor import extract_filing_text
            print(f"      📄 Fetching content for {filing_type} summary generation...")
            full_text = extract_filing_text(filing['url'])

            # For 8-Ks, extract specific Item section
            if filing_type in ['8-K', '8-K/A']:
                content = _extract_8k_item_section(full_text, item_number)
            else:
                content = full_text[:5000]
        except Exception as e:
            print(f"      ⚠️  Could not fetch filing content for summary: {e}")
            content = ''

    # If still no content, skip AI and use structured fallback
    if not content:
        return _generate_fallback_summary(filing)

    # Build comprehensive prompt for AI classification
    if filing_type == '8-K':
        prompt = f"""Analyze this 8-K filing for {ticker} and provide a brief one-sentence summary.

IMPORTANT: Identify the SPECIFIC event type:
- Name change (company renaming)
- Redemption (shareholders redeeming shares)
- Extension (deadline extension)
- Deal announcement/termination
- Vote results
- Officer changes
- Trust account changes
- Liquidation
- Other

Item Number: {item_number if item_number else 'Not specified'}
Context: {reason}

Filing excerpt:
{content[:3000]}

Format: "[Event Type]: [One sentence description]"
Example: "Name Change: Company changed name from X to Y effective [date]"
Example: "Redemption: Shareholders redeemed X shares for $Y following vote"
"""

    elif filing_type in ['424B4', '8-A12B', 'CERT']:
        prompt = f"""This is an IPO-related filing ({filing_type}) for {ticker}.

Provide a one-sentence summary focusing on:
- IPO pricing details (if 424B4)
- Number of units/shares offered
- Offering price
- Exchange listing (if CERT)

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type in ['S-4', 'DEFM14A', '425']:
        prompt = f"""This is a deal-related filing ({filing_type}) for {ticker}.

Provide a one-sentence summary including:
- Target company name
- Deal structure
- Deal value (if mentioned)
- Key terms

Filing excerpt:
{content[:3000]}

One sentence summary:"""

    elif filing_type in ['10-Q', '10-K']:
        prompt = f"""This is a {filing_type} financial report for {ticker}.

Provide a one-sentence summary mentioning:
- Reporting period
- Any notable events or changes mentioned
- Trust account status (if discussed)

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type in ['S-1', 'S-1/A']:
        prompt = f"""This is an IPO registration filing ({filing_type}) for {ticker}.

Provide a one-sentence summary including:
- Purpose (initial registration or amendment)
- Key details about the offering
- Any significant changes (if amendment)

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type in ['SC 13D', 'SC 13G', 'SCHEDULE 13D', 'SCHEDULE 13G']:
        prompt = f"""This is a large shareholder filing ({filing_type}) for {ticker}.

Provide a one-sentence summary including:
- Who is filing (investor/entity name)
- Percentage ownership
- Purpose (passive investment vs. activist)

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type in ['DEF 14A', 'DEFR14A', 'PREM14A', 'DEFA14A']:
        prompt = f"""This is a proxy statement ({filing_type}) for {ticker}.

Provide a one-sentence summary including:
- Type of shareholder meeting
- Key proposals being voted on
- Important dates

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type == 'Form 25':
        prompt = f"""This is a delisting notice for {ticker}.

Provide a one-sentence summary including:
- Exchange being delisted from
- Reason for delisting
- Effective date

Filing excerpt:
{content[:1000]}

One sentence summary:"""

    elif filing_type in ['FWP', '424B2', '424B3', '424B5']:
        prompt = f"""This is a prospectus supplement ({filing_type}) for {ticker}.

Provide a one-sentence summary of the key information or changes.

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    elif filing_type in ['POS AM', '  EFFECT', 'EFFECT']:
        prompt = f"""This is a post-effective amendment or effectiveness notice ({filing_type}) for {ticker}.

Provide a one-sentence summary of what became effective or was amended.

Filing excerpt:
{content[:1500]}

One sentence summary:"""

    else:
        # Generic intelligent prompt for all other filing types
        prompt = f"""Analyze this {filing_type} filing for {ticker}.

Identify the main purpose and provide a one-sentence summary of the key event or information.

Filing excerpt:
{content[:2000]}

One sentence summary:"""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a financial filing analyzer. Provide concise, accurate summaries that identify the SPECIFIC event type (name change, redemption, extension, etc.)."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.1
        )

        summary = response.choices[0].message.content.strip()

        # Clean up summary (remove quotes, extra whitespace)
        summary = summary.strip('"').strip("'").strip()

        return summary if len(summary) > 10 else None

    except Exception as e:
        print(f"   ⚠️  AI summary generation failed: {e}")
        return None


def get_recent_filings(days: int = 30, ticker: Optional[str] = None, limit: int = 100) -> list:
    """
    Get recent filings for news feed

    Args:
        days: Number of days to look back
        ticker: Filter by specific ticker (optional)
        limit: Maximum number of results

    Returns:
        List of filing events (as dicts)
    """

    db = SessionLocal()
    try:
        from datetime import timedelta

        cutoff_date = date.today() - timedelta(days=days)

        query = db.query(FilingEvent).filter(FilingEvent.filing_date >= cutoff_date)

        if ticker:
            query = query.filter(FilingEvent.ticker == ticker)

        query = query.order_by(FilingEvent.filing_date.desc(), FilingEvent.detected_at.desc())
        query = query.limit(limit)

        filings = query.all()

        # Convert to dicts
        return [
            {
                'id': f.id,
                'ticker': f.ticker,
                'filing_type': f.filing_type,
                'filing_date': f.filing_date,
                'filing_url': f.filing_url,
                'filing_title': f.filing_title,
                'tag': f.tag,
                'priority': f.priority,
                'item_number': f.item_number,
                'summary': f.summary,
                'detected_at': f.detected_at
            }
            for f in filings
        ]

    finally:
        db.close()


# Test the logger
if __name__ == '__main__':
    # Test filing
    test_filing = {
        'ticker': 'TEST',
        'type': '8-K',
        'date': date.today(),
        'url': 'https://www.sec.gov/test',
        'title': 'Test 8-K Filing',
        'item_number': '1.01',
        'classification': {
            'priority': 'HIGH',
            'reason': 'Deal announcement detected'
        }
    }

    print("Testing filing logger...")
    success = log_filing(test_filing)
    print(f"Result: {'✅ Success' if success else '❌ Failed'}")

    # Get recent filings
    print("\nRecent filings:")
    recent = get_recent_filings(days=7, limit=5)
    for filing in recent:
        print(f"  {filing['filing_date']} - {filing['ticker']}: {filing['tag']}")
