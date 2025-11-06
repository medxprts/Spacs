#!/usr/bin/env python3
"""
IPO Detector Agent

Detects 424B4 filings (IPO close) for pre-IPO SPACs and graduates them to main pipeline.
Triggered by SEC filing monitor when 424B4 is detected.
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Dict, Optional
import sys

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC
from pre_ipo_database import SessionLocal as PreIPOSessionLocal, PreIPOSPAC
from agents.base_agent import BaseAgent

# AI Setup
try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
except Exception as e:
    AI_AVAILABLE = False


class IPODetectorAgent(BaseAgent):
    """
    Detects 424B4 filings indicating IPO close and graduates pre-IPO SPACs to main pipeline

    Flow:
    1. Receives 424B4 filing from orchestrator
    2. Checks if this is a pre-IPO SPAC we're tracking
    3. Extracts IPO data using AI (proceeds, structure, deadline)
    4. Graduates SPAC to main pipeline with deal_status='SEARCHING'
    """

    def __init__(self):
        super().__init__(name="IPODetector")
        self.db = SessionLocal()
        self.pre_ipo_db = PreIPOSessionLocal()
        self.headers = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}
        self.base_url = "https://www.sec.gov"

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a 424B4 filing for a tracked pre-IPO SPAC"""

        # Must be 424B4
        if filing.get('type') != '424B4':
            return False

        # Check if CIK matches a pre-IPO SPAC we're tracking
        cik = filing.get('cik')
        if not cik:
            return False

        # Look for pre-IPO SPAC with this CIK (any status)
        # Note: 424B4 can only be filed if S-1 is effective, so we don't need to check status
        pre_ipo_spac = self.pre_ipo_db.query(PreIPOSPAC).filter(
            PreIPOSPAC.cik == cik
        ).first()

        if pre_ipo_spac:
            print(f"   ✓ Found pre-IPO SPAC: {pre_ipo_spac.expected_ticker} ({pre_ipo_spac.company})")
            return True

        return False

    async def process(self, filing: Dict) -> Optional[Dict]:
        """
        Process 424B4 filing and graduate pre-IPO SPAC to main pipeline

        Returns dict with graduation result or None if failed
        """
        cik = filing.get('cik')
        filing_url = filing.get('url')
        filing_date = filing.get('date')

        print(f"\n🎉 IPO CLOSING DETECTED!")
        print(f"   CIK: {cik}")
        print(f"   Filing date: {filing_date}")

        # Get pre-IPO SPAC record (any status)
        pre_ipo_spac = self.pre_ipo_db.query(PreIPOSPAC).filter(
            PreIPOSPAC.cik == cik
        ).first()

        if not pre_ipo_spac:
            print("   ❌ Pre-IPO SPAC not found or already graduated")
            return None

        # Auto-update status to EFFECTIVE if not already
        # Logic: 424B4 can only be filed if S-1 is effective, so this is safe
        if pre_ipo_spac.filing_status != 'EFFECTIVE':
            old_status = pre_ipo_spac.filing_status
            print(f"   🔄 Auto-updating status: {old_status} → EFFECTIVE")
            print(f"      (424B4 filing proves S-1 is effective)")

            pre_ipo_spac.filing_status = 'EFFECTIVE'
            pre_ipo_spac.effectiveness_date = filing_date

            try:
                self.pre_ipo_db.commit()
                print(f"   ✓ Status updated")
            except Exception as e:
                print(f"   ⚠️  Failed to update status: {e}")
                self.pre_ipo_db.rollback()

        # Extract IPO data from 424B4
        print(f"   📄 Extracting IPO data from 424B4...")
        ipo_data = self._extract_ipo_data_from_424b4(filing_url)

        if not ipo_data:
            print("   ❌ Failed to extract IPO data")
            return None

        ipo_data['ipo_date'] = filing_date
        ipo_data['filing_url'] = filing_url

        # Graduate to main pipeline
        result = self._graduate_to_main_pipeline(pre_ipo_spac, ipo_data)

        if result:
            print(f"   ✅ Graduated {pre_ipo_spac.expected_ticker} to main pipeline")
            print(f"      IPO: {result['ipo_date']}")
            print(f"      Proceeds: {result.get('ipo_proceeds', 'N/A')}")
            print(f"      Deadline: {result.get('deadline_date', 'N/A')}")

            # Run comprehensive 424B4 extraction for all key datapoints
            print(f"   🔍 Running comprehensive 424B4 extraction...")
            self._run_comprehensive_extraction(pre_ipo_spac.expected_ticker)

            return {
                'action': 'graduated',
                'ticker': pre_ipo_spac.expected_ticker,
                'ipo_date': filing_date,
                'ipo_data': ipo_data
            }

        return None

    def _extract_ipo_data_from_424b4(self, filing_url: str) -> Optional[Dict]:
        """Extract IPO data from 424B4 using hybrid regex + AI approach"""
        try:
            # Get the 424B4 document
            response = requests.get(filing_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the actual .htm document
            doc_url = None
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.htm' in href and not href.endswith('.xml') and 'ix?doc=' not in href:
                    doc_url = self.base_url + href
                    break

            if not doc_url:
                return None

            doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
            text = doc_response.text

            # Try regex first (fast)
            data = self._extract_with_regex(text)

            # Use AI for missing fields
            if AI_AVAILABLE:
                if not data.get('ipo_proceeds') or not data.get('unit_structure'):
                    print(f"      🤖 Using AI to extract IPO data...")
                    ai_data = self._extract_with_ai(text)

                    # Merge AI results
                    for key, value in ai_data.items():
                        if value and not data.get(key):
                            data[key] = value

            return data if data else None

        except Exception as e:
            print(f"      Error extracting from 424B4: {e}")
            return None

    def _extract_with_regex(self, text: str) -> Dict:
        """Extract IPO data using regex patterns"""
        data = {}

        # Extract IPO proceeds
        proceeds_patterns = [
            r'gross proceeds.*?\$([0-9,\.]+)\s*million',
            r'offering.*?\$([0-9,\.]+)\s*million',
            r'raised.*?\$([0-9,\.]+)\s*million'
        ]

        for pattern in proceeds_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                proceeds = match.group(1).replace(',', '')
                data['ipo_proceeds'] = f"${proceeds}M"
                break

        # Extract unit structure
        structure_patterns = [
            r'one.*?share.*?(\d+(?:/\d+)?)\s+warrant',
            r'(\d+)\s+shares?.*?(\d+(?:/\d+)?)\s+warrant'
        ]

        for pattern in structure_patterns:
            match = re.search(pattern, text)
            if match:
                if '/' in match.group(0):
                    data['unit_structure'] = f"1 share + {match.groups()[-1]} warrant"
                else:
                    data['unit_structure'] = "1 share + 1 warrant"
                break

        # Extract deadline months
        deadline_patterns = [
            r'(\d+)\s+months from.*?closing',
            r'within\s+(\d+)\s+months',
            r'(\d+)-month period'
        ]

        for pattern in deadline_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['deadline_months'] = int(match.group(1))
                break

        return data

    def _extract_with_ai(self, text: str) -> Dict:
        """Use AI to extract IPO data from 424B4"""
        if not AI_AVAILABLE:
            return {}

        try:
            text_excerpt = text[:30000]

            prompt = f"""Extract SPAC IPO data from this 424B4 prospectus. Return ONLY valid JSON.

Required fields:
- ipo_proceeds: Gross proceeds as string (e.g., "$200M")
- unit_structure: Unit composition (e.g., "1 share + 1/3 warrant")
- deadline_months: Months until business combination deadline (integer, typically 18-24)
- shares_issued: Number of units sold in millions (float)
- trust_per_unit: Cash per unit in trust (typically 10.00)
- warrant_exercise_price: Warrant exercise price (typically 11.50)

Text excerpt:
{text_excerpt}

Return JSON only (use null for missing fields):"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=400
            )

            result = response.choices[0].message.content.strip()
            result = re.sub(r'```json\s*|\s*```', '', result)

            import json
            data = json.loads(result)
            return data

        except Exception as e:
            print(f"      AI extraction error: {e}")
            return {}

    def _graduate_to_main_pipeline(self, pre_ipo_spac: PreIPOSPAC, ipo_data: Dict) -> Optional[Dict]:
        """Graduate pre-IPO SPAC to main pipeline"""

        # Check if already in main database
        existing = self.db.query(SPAC).filter(
            SPAC.ticker == pre_ipo_spac.expected_ticker
        ).first()

        if existing:
            print(f"      ℹ️  {pre_ipo_spac.expected_ticker} already in main database")
            return None

        # Create new SPAC in main database
        new_spac = SPAC(
            ticker=pre_ipo_spac.expected_ticker,
            company=pre_ipo_spac.company,
            cik=pre_ipo_spac.cik,
            sector=pre_ipo_spac.target_sector,
            banker=pre_ipo_spac.lead_banker,
            sponsor=pre_ipo_spac.sponsor,

            # IPO data from 424B4
            ipo_date=datetime.strptime(ipo_data['ipo_date'], '%Y-%m-%d').date(),
            ipo_proceeds=ipo_data.get('ipo_proceeds', pre_ipo_spac.target_proceeds),
            unit_structure=ipo_data.get('unit_structure'),
            deadline_months=ipo_data.get('deadline_months'),

            # Additional IPO data from AI
            shares_outstanding=int(ipo_data.get('shares_issued', 0) * 1_000_000) if ipo_data.get('shares_issued') else None,
            trust_value=ipo_data.get('trust_per_unit', 10.00),
            warrant_exercise_price=ipo_data.get('warrant_exercise_price', 11.50),

            # Default values
            deal_status='SEARCHING',  # Newly public, searching for target
            target='-',
            last_scraped_at=datetime.utcnow()
        )

        # Calculate deadline
        if new_spac.deadline_months and new_spac.ipo_date:
            new_spac.deadline_date = new_spac.ipo_date + relativedelta(months=new_spac.deadline_months)

        # Save to database
        try:
            self.db.add(new_spac)

            # Update pre-IPO record
            pre_ipo_spac.filing_status = 'Closed'
            pre_ipo_spac.ipo_close_date = ipo_data['ipo_date']
            pre_ipo_spac.moved_to_main_pipeline = True

            self.db.commit()
            self.pre_ipo_db.commit()

            return {
                'ticker': new_spac.ticker,
                'ipo_date': str(new_spac.ipo_date),
                'ipo_proceeds': new_spac.ipo_proceeds,
                'deadline_date': str(new_spac.deadline_date) if new_spac.deadline_date else None
            }

        except Exception as e:
            print(f"      ❌ Database error: {e}")
            self.db.rollback()
            self.pre_ipo_db.rollback()
            return None

    def _run_comprehensive_extraction(self, ticker: str):
        """
        Run comprehensive 424B4 extraction for newly graduated SPAC

        Extracts:
        - Founder shares
        - Shares outstanding (base + overallotment)
        - Banker + tier classification
        - Warrant terms
        - Extension terms
        - Overallotment details

        If extraction fails or is incomplete, marks SPAC for retry
        """
        try:
            # Import here to avoid circular dependency
            import subprocess
            from datetime import datetime

            # Run extractor as subprocess
            result = subprocess.run(
                ['python3', '/home/ubuntu/spac-research/agents/comprehensive_424b4_extractor.py', '--ticker', ticker],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Check if data is complete after extraction
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if spac:
                data_complete = (
                    spac.founder_shares is not None and
                    spac.shares_outstanding_base is not None and
                    spac.banker is not None
                )

                if result.returncode == 0 and data_complete:
                    print(f"      ✅ Comprehensive extraction complete")
                    # Show summary of updates
                    for line in result.stdout.split('\n'):
                        if 'Updated' in line or 'fields:' in line or line.strip().startswith('-'):
                            print(f"      {line}")

                    # Mark as complete
                    spac.comprehensive_extraction_needed = False
                    self.db.commit()
                else:
                    print(f"      ⚠️  Incomplete extraction - will retry")
                    print(f"         Missing: ", end="")
                    missing = []
                    if not spac.founder_shares: missing.append("founder_shares")
                    if not spac.shares_outstanding_base: missing.append("shares_outstanding")
                    if not spac.banker: missing.append("banker")
                    print(", ".join(missing) if missing else "unknown")

                    # Mark for retry (will retry for 7 days)
                    spac.comprehensive_extraction_needed = True
                    spac.comprehensive_extraction_attempts = (spac.comprehensive_extraction_attempts or 0) + 1
                    spac.last_extraction_attempt = datetime.now()
                    self.db.commit()

        except Exception as e:
            print(f"      ⚠️  Comprehensive extraction failed: {e}")
            print(f"         (Will retry automatically)")

            # Mark for retry
            try:
                spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if spac:
                    spac.comprehensive_extraction_needed = True
                    spac.comprehensive_extraction_attempts = (spac.comprehensive_extraction_attempts or 0) + 1
                    spac.last_extraction_attempt = datetime.now()
                    self.db.commit()
            except:
                pass

    def close(self):
        """Close database connections"""
        self.db.close()
        self.pre_ipo_db.close()


# For standalone testing
if __name__ == "__main__":
    import asyncio

    async def test_agent():
        """Test the IPO detector agent"""
        agent = IPODetectorAgent()

        # Test filing
        test_filing = {
            'type': '424B4',
            'cik': '0001234567',  # Replace with actual pre-IPO SPAC CIK
            'date': '2025-10-10',
            'url': 'https://www.sec.gov/...'  # Replace with actual URL
        }

        can_process = await agent.can_process(test_filing)
        print(f"Can process: {can_process}")

        if can_process:
            result = await agent.process(test_filing)
            print(f"Result: {result}")

        agent.close()

    asyncio.run(test_agent())
