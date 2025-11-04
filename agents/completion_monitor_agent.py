"""
Completion Monitor Agent

Detects deal completion from 8-K Item 2.01 filings and updates SPAC status to COMPLETED.

Extracts:
- Closing date
- New ticker symbol
- Final redemption amounts
- Final shares outstanding
"""

import os
import sys
import json
import requests
from typing import Dict, Optional
from bs4 import BeautifulSoup
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC
from utils.number_parser import sanitize_ai_response, MONEY_FIELDS, SHARE_FIELDS

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


class CompletionMonitorAgent(BaseAgent):
    """Detects deal completion from 8-K Item 2.01 filings"""

    def __init__(self):
        super().__init__("CompletionMonitor")
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a completion 8-K"""
        filing_type = filing.get('type', '')

        # Only process 8-K filings
        if filing_type != '8-K':
            return False

        summary = filing.get('summary', '').lower()

        # Check for completion keywords
        completion_keywords = [
            'completion of business combination',
            'completion of merger',
            'consummation of business combination',
            'consummation of merger',
            'consummated merger',
            'business combination has closed',
            'business combination closed',
            'merger has closed',
            'item 2.01',  # Item 2.01 = Completion of Acquisition
            'completion of acquisition'
        ]

        return any(keyword in summary for keyword in completion_keywords)

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Extract completion data and update database"""

        print(f"\n   🎉 {self.name}: Analyzing completion filing from {filing['date'].strftime('%Y-%m-%d')}")

        # Use pre-fetched content if available, otherwise fetch
        content = filing.get('content')
        if not content:
            print(f"      📥 Fetching filing content...")
            content = self._fetch_filing_content(filing['url'])
        else:
            print(f"      ✓ Using pre-fetched content ({len(content):,} chars)")

        if not content:
            return None

        # Extract completion data with AI
        completion_data = self._extract_completion_with_ai(content, filing)

        if not completion_data:
            print(f"      ⚠️  Could not extract completion details")
            return None

        # Update database
        ticker = filing.get('ticker')
        if ticker:
            self._update_database(ticker, completion_data, filing)

        return completion_data

    def _extract_completion_with_ai(self, content: str, filing: Dict) -> Optional[Dict]:
        """Use AI to extract completion details from filing"""

        if not AI_AVAILABLE:
            print(f"      ⚠️  AI not available for extraction")
            return None

        ticker = filing.get('ticker', 'Unknown')

        # Truncate content to avoid token limits (use first 15000 chars)
        content = content[:15000]

        prompt = f"""You are analyzing an 8-K filing announcing the COMPLETION of a SPAC business combination.

Ticker: {ticker}
Filing Date: {filing.get('date', 'Unknown')}

Extract the following information:

1. **closing_date**: The date the merger/business combination closed (format: YYYY-MM-DD)
2. **new_ticker**: The new ticker symbol post-merger (if mentioned)
3. **shares_redeemed**: Number of shares redeemed by public shareholders
4. **redemption_amount**: Dollar amount paid for redemptions (total cash paid out)
5. **shares_outstanding**: Final number of shares outstanding after completion
6. **target**: The target company name (acquired company)

Look for phrases like:
- "On [DATE], the business combination was consummated"
- "The merger closed on [DATE]"
- "Effective [DATE]"
- "The combined company will trade under ticker [TICKER]"
- "[NUMBER] shares were redeemed"
- "Aggregate redemption amount of $[AMOUNT]"

IMPORTANT: Return all dollar amounts and share counts as NUMERIC VALUES (not formatted strings).
- Convert "$50M" to 50000000
- Convert "$1.2B" to 1200000000
- Convert "5M shares" to 5000000
- Convert "$10.00" to 10.0
- If a value is not found, return null (not "N/A" or "TBD")

Return ONLY valid JSON in this exact format:
{{
    "closing_date": "2025-10-20",
    "new_ticker": "IMSR",
    "shares_redeemed": 7390,
    "redemption_amount": 77889,
    "shares_outstanding": 50000000,
    "target": "IonQ Inc."
}}

Filing excerpt:
{content}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                temperature=0
            )

            # Parse AI response
            result_text = response.choices[0].message.content.strip()

            # Extract JSON from response (might have markdown code blocks)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            data = json.loads(result_text)

            # Sanitize numeric fields (AI sometimes returns "1.1M" instead of 1100000)
            numeric_fields = ['shares_redeemed', 'redemption_amount', 'shares_outstanding']
            data = sanitize_ai_response(data, numeric_fields)

            print(f"      ✅ Extracted completion data:")
            if data.get('closing_date'):
                print(f"         • Closing date: {data['closing_date']}")
            if data.get('new_ticker'):
                print(f"         • New ticker: {data['new_ticker']}")
            if data.get('shares_redeemed'):
                print(f"         • Shares redeemed: {data['shares_redeemed']:,}")
            if data.get('target'):
                print(f"         • Target: {data['target']}")

            return data

        except json.JSONDecodeError as e:
            print(f"      ❌ Failed to parse AI response as JSON: {e}")
            print(f"         Response: {result_text[:200]}...")
            return None
        except Exception as e:
            print(f"      ❌ AI extraction error: {e}")
            return None

    def _update_database(self, ticker: str, completion_data: Dict, filing: Dict):
        """Update SPAC to COMPLETED status"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

            if not spac:
                print(f"      ⚠️  SPAC {ticker} not found in database")
                return

            # Store previous status for logging
            previous_status = spac.deal_status

            # Update to COMPLETED status
            spac.deal_status = 'COMPLETED'

            # Update completion date
            if completion_data.get('closing_date'):
                try:
                    # Parse and store closing date
                    closing_date = datetime.strptime(completion_data['closing_date'], '%Y-%m-%d').date()
                    spac.completion_date = closing_date
                except (ValueError, TypeError):
                    # If date parsing fails, use filing date
                    spac.completion_date = filing.get('date')

            # Update new ticker
            if completion_data.get('new_ticker'):
                spac.new_ticker = completion_data['new_ticker']

            # Update redemption data
            if completion_data.get('shares_redeemed') is not None:
                spac.shares_redeemed = completion_data['shares_redeemed']

            if completion_data.get('redemption_amount') is not None:
                spac.redemption_amount = completion_data['redemption_amount']

            # Update shares outstanding
            if completion_data.get('shares_outstanding') is not None:
                spac.shares_outstanding = completion_data['shares_outstanding']

            # Update target if extracted (might have been missing before)
            if completion_data.get('target') and not spac.target:
                spac.target = completion_data['target']

            # Update last_updated timestamp
            spac.last_updated = datetime.utcnow()

            db.commit()

            print(f"      ✅ {ticker} updated: {previous_status} → COMPLETED")
            if completion_data.get('new_ticker'):
                print(f"         • New ticker: {completion_data['new_ticker']}")

            # Log to filing events (mark as processed)
            try:
                from database import FilingEvent
                filing_event = db.query(FilingEvent).filter(
                    FilingEvent.ticker == ticker,
                    FilingEvent.filing_date == filing.get('date')
                ).first()

                if filing_event and not filing_event.processed:
                    filing_event.processed = True
                    filing_event.processed_at = datetime.utcnow()
                    db.commit()
            except:
                pass  # FilingEvent table might not exist

        except Exception as e:
            print(f"      ❌ Database update error: {e}")
            db.rollback()
        finally:
            db.close()


# Standalone test function
async def test_completion_monitor(ticker: str, filing_url: str):
    """Test the completion monitor agent on a specific filing"""

    agent = CompletionMonitorAgent()

    # Create mock filing dict
    filing = {
        'ticker': ticker,
        'type': '8-K',
        'date': datetime.now(),
        'url': filing_url,
        'summary': 'Completion of business combination'
    }

    # Test can_process
    can_process = await agent.can_process(filing)
    print(f"Can process: {can_process}")

    if can_process:
        # Test process
        result = await agent.process(filing)
        print(f"Result: {result}")


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description='Test Completion Monitor Agent')
    parser.add_argument('--ticker', type=str, help='SPAC ticker to test')
    parser.add_argument('--url', type=str, help='8-K filing URL')

    args = parser.parse_args()

    if args.ticker and args.url:
        asyncio.run(test_completion_monitor(args.ticker, args.url))
    else:
        print("Usage: python3 completion_monitor_agent.py --ticker HOND --url [FILING_URL]")
