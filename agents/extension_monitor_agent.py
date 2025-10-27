"""
Extension Monitor Agent

Detects deadline extensions and redemptions from:
- 8-K Item 5.03 (Amendments to Articles of Incorporation)
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
from utils.redemption_tracker import add_redemption_event, mark_no_redemptions_found
from utils.sec_filing_fetcher import SECFilingFetcher

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


class ExtensionMonitorAgent(BaseAgent):
    """Monitors for deadline extensions in 8-K Item 5.03 filings"""

    def __init__(self):
        super().__init__("ExtensionMonitor")
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }
        self.sec_fetcher = SECFilingFetcher()

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a potential extension filing"""
        # Only process 8-K filings
        return filing.get('type') == '8-K'

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Extract extension data from 8-K Item 5.03"""

        print(f"\n   🔍 {self.name}: Analyzing 8-K from {filing['date'].strftime('%Y-%m-%d')}")

        # Use pre-fetched content if available (from SEC monitor), otherwise fetch
        content = filing.get('content')
        if not content:
            print(f"      📥 Fetching filing content...")
            content = self._fetch_filing_content(filing['url'])
        else:
            print(f"      ✓ Using pre-fetched content ({len(content):,} chars)")

        if not content:
            return None

        # Check if this is Item 5.03
        if not self._is_item_503(content):
            print(f"      ℹ️  Not an Item 5.03 filing")
            return None

        # Extract extension details with AI
        extension_data = self._extract_extension_with_ai(content, filing)

        if not extension_data or not extension_data.get('new_deadline'):
            print(f"      ⚠️  Could not extract extension details")
            return None

        # Update database
        updated = self._update_database(filing['cik'], extension_data, filing)

        if updated:
            print(f"      ✅ Extension detected: {extension_data['new_deadline']}")
            return {
                **extension_data,
                'filing_url': filing['url'],
                'filing_date': filing['date']
            }

        return None

    def _fetch_filing_content(self, url: str) -> Optional[str]:
        """Fetch and parse filing content using centralized SEC fetcher"""
        try:
            # Use the centralized SEC fetcher to extract the actual document URL
            # This handles index pages and inline XBRL viewer formats
            doc_url = self.sec_fetcher.extract_document_url(url)
            if not doc_url:
                print(f"      ⚠️  Could not extract document URL from index page")
                return None

            # Fetch the actual document content
            html_content = self.sec_fetcher.fetch_document(doc_url)
            if not html_content:
                return None

            # Parse HTML and extract text
            soup = BeautifulSoup(html_content, 'html.parser')
            return soup.get_text()

        except Exception as e:
            print(f"      ⚠️  Error fetching content: {e}")
            return None

    def _is_item_503(self, content: str) -> bool:
        """Check if filing is Item 5.03"""
        content_lower = content.lower()
        return 'item 5.03' in content_lower or 'item 5.3' in content_lower

    def _extract_extension_with_ai(self, content: str, filing: Dict) -> Optional[Dict]:
        """Use AI to extract extension details"""

        if not AI_AVAILABLE:
            return None

        try:
            # Find Item 5.03 section
            content_lower = content.lower()
            item_idx = content_lower.find('item 5.03')
            if item_idx == -1:
                item_idx = content_lower.find('item 5.3')

            if item_idx != -1:
                excerpt = content[item_idx:item_idx+5000]
            else:
                excerpt = content[:5000]

            prompt = f"""
Extract deadline extension AND redemption details from this 8-K Item 5.03 filing:

Filing Date: {filing['date'].strftime('%Y-%m-%d')}

PRIORITY 1: REDEMPTIONS (most important!)
Look for:
- "X shares redeemed" or "X shares elected to redeem"
- "shareholders holding X shares elected not to extend"
- "no redemptions" or "zero redemptions" or "no shareholders redeemed"
- Redemption price per share (typically $10.00-$10.50)

PRIORITY 2: Extension details
- New deadline/termination date (e.g., "extended until [DATE]")
- Number of months extended (3, 6, 9, or 12)
- Sponsor deposit per share (e.g., "$0.03 per share")

CRITICAL: Set redemptions_checked=true even if zero redemptions!

Return JSON:
{{
    "redemptions_checked": true,
    "redemptions_found": true/false,
    "shares_redeemed": <number or 0>,
    "redemption_amount": <dollars or 0>,
    "redemption_price": <price per share>,
    "new_deadline": "YYYY-MM-DD",
    "extension_months": 6,
    "deposit_per_share": 0.03
}}

Text:
{excerpt}
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing extraction expert. Extract deadline extension data precisely."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)
            return data

        except Exception as e:
            print(f"      ⚠️  AI extraction failed: {e}")
            return None

    def _update_database(self, cik: str, extension_data: Dict, filing: Dict) -> bool:
        """Update SPAC database with extension data"""

        db = SessionLocal()
        try:
            # Find SPAC by CIK
            spac = db.query(SPAC).filter(SPAC.cik == cik).first()

            if not spac:
                print(f"      ⚠️  SPAC not found for CIK {cik}")
                return False

            # Parse new deadline
            try:
                new_deadline = datetime.strptime(extension_data['new_deadline'], '%Y-%m-%d').date()
            except:
                print(f"      ⚠️  Could not parse deadline: {extension_data.get('new_deadline')}")
                return False

            # Update deadline fields
            old_deadline = spac.deadline_date
            spac.deadline_date = new_deadline
            spac.is_extended = True
            spac.extension_date = filing['date'].date()

            # Increment extension count
            if spac.extension_count:
                spac.extension_count += 1
            else:
                spac.extension_count = 1

            db.commit()

            # Handle redemption data using tracker (AFTER commit for extension data)
            if extension_data.get('redemptions_checked'):
                if extension_data.get('redemptions_found') and extension_data.get('shares_redeemed', 0) > 0:
                    # Add redemption event (incremental)
                    redemption_amount = extension_data.get('redemption_amount', 0)
                    if redemption_amount == 0 and extension_data.get('redemption_price'):
                        # Calculate amount if not provided
                        redemption_amount = extension_data['shares_redeemed'] * extension_data['redemption_price']

                    add_redemption_event(
                        db_session=db,
                        ticker=spac.ticker,
                        shares_redeemed=extension_data['shares_redeemed'],
                        redemption_amount=redemption_amount,
                        filing_date=filing['date'].date(),
                        source='8-K Item 5.03 (Extension)',
                        reason=f"Extension to {new_deadline}"
                    )
                    print(f"      ✓ Redemption: {extension_data['shares_redeemed']:,.0f} shares redeemed")
                else:
                    # Mark that we checked and found no redemptions
                    mark_no_redemptions_found(
                        db_session=db,
                        ticker=spac.ticker,
                        filing_date=filing['date'].date(),
                        source='8-K Item 5.03 (Extension)'
                    )
                    print(f"      ✓ No redemptions in this extension")

            print(f"      ✓ Updated {spac.ticker}: deadline {old_deadline} → {new_deadline}")
            return True

        except Exception as e:
            db.rollback()
            print(f"      ❌ Database update failed: {e}")
            return False

        finally:
            db.close()

    def check_extension(self, cik: str, filing: Dict) -> Optional[Dict]:
        """
        Legacy method for backward compatibility with orchestrator

        Args:
            cik: CIK number of SPAC
            filing: Filing dict with 'type', 'date', 'url'

        Returns:
            Dict with success status and extension data
        """
        # Convert to format expected by process()
        filing_dict = {
            'cik': cik,
            'type': filing['type'],
            'date': filing['date'],
            'url': filing['url']
        }

        # Call the standard process method
        import asyncio
        result = asyncio.run(self.process(filing_dict))

        if result:
            return {
                'success': True,
                'findings': result
            }
        else:
            return {
                'success': False,
                'findings': 'No extension detected'
            }
