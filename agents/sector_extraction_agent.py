#!/usr/bin/env python3
"""
Enhanced Sector Extraction Agent

Extracts detailed sector/industry focus from SPAC prospectus (424B4/S-1).
Categorizes into 2025-relevant investment themes for Deal Spec screening.

Key Features:
- Primary sector classification (Technology, Healthcare, Energy, etc.)
- 2025 hot theme tagging (AI, Quantum, Space, Crypto, Nuclear)
- Deal size target range
- Geographic focus
- Investment criteria extraction
"""

import os
import sys
import json
import requests
from typing import Dict, Optional, List
from bs4 import BeautifulSoup
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC

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


class SectorExtractionAgent(BaseAgent):
    """
    Extracts detailed sector/industry focus from SPAC prospectus

    2025 Hot Themes (for Deal Spec screening):
    - AI/ML Infrastructure
    - Quantum Computing
    - Space/Aerospace
    - Crypto/Blockchain/Fintech
    - Nuclear/Advanced Energy
    - EV/Battery Technology
    - Cybersecurity
    - Healthcare Tech
    """

    def __init__(self):
        super().__init__("SectorExtraction")
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }

        # 2025 hot themes for Deal Spec Candidates
        self.hot_themes_2025 = {
            'AI/ML': ['artificial intelligence', 'machine learning', 'deep learning', 'neural network',
                      'generative ai', 'large language model', 'computer vision', 'ai infrastructure'],
            'Quantum': ['quantum computing', 'quantum', 'quantum technology', 'quantum information'],
            'Space': ['space', 'aerospace', 'satellite', 'launch', 'space technology', 'orbital'],
            'Crypto/Fintech': ['cryptocurrency', 'blockchain', 'digital asset', 'decentralized finance',
                               'defi', 'web3', 'fintech', 'payment', 'financial technology'],
            'Nuclear': ['nuclear', 'nuclear energy', 'small modular reactor', 'smr', 'fusion',
                        'advanced nuclear', 'nuclear power'],
            'EV/Battery': ['electric vehicle', 'ev', 'battery', 'energy storage', 'charging infrastructure',
                           'battery technology', 'lithium', 'solid state battery'],
            'Cybersecurity': ['cybersecurity', 'cyber security', 'information security', 'data protection',
                             'threat detection', 'security software'],
            'Healthcare Tech': ['digital health', 'health tech', 'medical technology', 'biotech',
                               'life sciences', 'genomics', 'precision medicine']
        }

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a prospectus filing"""
        return filing.get('type') in ['424B4', 'S-1', 'S-1/A']

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Extract sector data from prospectus"""

        ticker = filing.get('ticker')
        filing_url = filing.get('url')

        print(f"\n🎯 {self.name}: Extracting sector for {ticker}")

        # Fetch prospectus
        content = self._fetch_prospectus(filing_url)
        if not content:
            print(f"   ❌ Could not fetch prospectus")
            return None

        # Extract "Business" section
        business_section = self._extract_business_section(content)
        if not business_section:
            print(f"   ⚠️  Could not find Business section")
            return None

        print(f"   ✓ Found Business section ({len(business_section):,} chars)")

        # AI extraction
        sector_data = self._extract_with_ai(business_section, ticker)
        if not sector_data:
            print(f"   ⚠️  AI extraction failed")
            return None

        # Detect hot themes
        themes = self._detect_themes(business_section)
        if themes:
            sector_data['themes_2025'] = themes
            print(f"   🔥 Hot themes detected: {', '.join(themes)}")

        # Update database
        self._update_database(ticker, sector_data)

        return sector_data

    def _fetch_prospectus(self, filing_url: str) -> Optional[str]:
        """Fetch prospectus content"""
        try:
            # Get filing index page
            response = requests.get(filing_url, headers=self.headers, timeout=30)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find 424B4 or S-1 document
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.htm' in href and ('424b4' in href.lower() or 'd' in href.lower()):
                    doc_url = f"https://www.sec.gov{href}" if href.startswith('/') else href
                    doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
                    doc_soup = BeautifulSoup(doc_response.text, 'html.parser')
                    return doc_soup.get_text()

            return soup.get_text()

        except Exception as e:
            print(f"   ⚠️  Error fetching prospectus: {e}")
            return None

    def _extract_business_section(self, content: str) -> Optional[str]:
        """Extract 'Business' section from prospectus"""
        content_lower = content.lower()

        # Try various section headers
        headers = [
            'business\n',
            'our business',
            'business strategy',
            'acquisition strategy',
            'target business',
            'industry focus'
        ]

        for header in headers:
            idx = content_lower.find(header)
            if idx != -1:
                # Extract 5000 characters from this section
                section = content[idx:idx+5000]
                return section

        # Fallback: look for "we intend to" or "our strategy"
        intent_idx = content_lower.find('we intend to')
        if intent_idx != -1:
            return content[intent_idx:intent_idx+5000]

        return None

    def _extract_with_ai(self, business_section: str, ticker: str) -> Optional[Dict]:
        """Use AI to extract sector details"""

        if not AI_AVAILABLE:
            return None

        prompt = f"""
Extract the SPAC's target sector and investment strategy from this prospectus excerpt for {ticker}.

Business Section:
{business_section[:4000]}

Extract the following information:

1. **sector**: Primary sector (choose ONE best fit):
   - Technology
   - Healthcare
   - Energy
   - Financial Services
   - Consumer
   - Industrial
   - Real Estate
   - Space/Aerospace
   - General (only if truly sector-agnostic)

2. **sector_details**: Detailed description of subsectors, specific areas of focus (2-3 sentences max)

3. **deal_size_target**: Target deal size or enterprise value range if mentioned (e.g., "$500M-$2B", "$1B+")
   Set to null if not mentioned.

4. **geographic_focus**: Geographic focus if mentioned (e.g., "United States", "Asia", "Global")
   Set to null if not limited.

5. **investment_criteria**: Key investment criteria or characteristics they're looking for
   (e.g., "profitable, high-growth", "pre-revenue with strong IP", "founder-led")
   Set to null if not mentioned.

Return JSON:
{{
    "sector": "Technology",
    "sector_details": "Focus on enterprise SaaS, cloud infrastructure, and AI-powered software companies with recurring revenue models",
    "deal_size_target": "$500M-$2B",
    "geographic_focus": "United States and Europe",
    "investment_criteria": "High-growth companies with >$50M ARR, strong unit economics, and path to profitability"
}}

If the SPAC states they have NO specific industry or sector focus, return:
{{
    "sector": "General",
    "sector_details": "No specific industry or geographic focus; opportunistic across all sectors",
    "deal_size_target": null,
    "geographic_focus": null,
    "investment_criteria": null
}}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing extraction expert. Extract SPAC investment strategy details precisely."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)

            # Print extracted data
            print(f"   ✅ Sector: {data.get('sector')}")
            if data.get('sector_details'):
                print(f"      {data['sector_details'][:80]}...")
            if data.get('deal_size_target'):
                print(f"   💰 Deal size target: {data['deal_size_target']}")

            return data

        except Exception as e:
            print(f"   ⚠️  AI extraction error: {e}")
            return None

    def _detect_themes(self, text: str) -> List[str]:
        """
        Detect 2025 hot themes in prospectus text

        Returns list of matching themes (e.g., ['AI/ML', 'Cybersecurity'])
        """
        text_lower = text.lower()
        detected_themes = []

        for theme, keywords in self.hot_themes_2025.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected_themes.append(theme)
                    break  # Only add theme once

        return detected_themes

    def _update_database(self, ticker: str, sector_data: Dict):
        """Update SPAC database with sector information"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found in database")
                return

            # Update sector fields
            if sector_data.get('sector'):
                spac.sector = sector_data['sector']

            if sector_data.get('sector_details'):
                spac.sector_details = sector_data['sector_details']

            # Store additional fields in sector_details JSON if not null
            # TODO: Add dedicated columns for these in future migration
            additional_data = {}
            if sector_data.get('deal_size_target'):
                additional_data['deal_size_target'] = sector_data['deal_size_target']
            if sector_data.get('geographic_focus'):
                additional_data['geographic_focus'] = sector_data['geographic_focus']
            if sector_data.get('investment_criteria'):
                additional_data['investment_criteria'] = sector_data['investment_criteria']
            if sector_data.get('themes_2025'):
                additional_data['themes_2025'] = sector_data['themes_2025']

            # Append to sector_details if we have additional data
            if additional_data:
                current_details = spac.sector_details or ""
                # Add separator if sector_details already has content
                if current_details:
                    current_details += "\n\n"
                # Add structured data
                if additional_data.get('themes_2025'):
                    current_details += f"🔥 2025 Hot Themes: {', '.join(additional_data['themes_2025'])}\n"
                if additional_data.get('deal_size_target'):
                    current_details += f"💰 Deal Size Target: {additional_data['deal_size_target']}\n"
                if additional_data.get('geographic_focus'):
                    current_details += f"🌍 Geographic Focus: {additional_data['geographic_focus']}\n"
                if additional_data.get('investment_criteria'):
                    current_details += f"🎯 Investment Criteria: {additional_data['investment_criteria']}"

                spac.sector_details = current_details.strip()

            db.commit()
            print(f"   ✓ Database updated for {ticker}")

        except Exception as e:
            db.rollback()
            print(f"   ❌ Database update failed: {e}")
        finally:
            db.close()


# Standalone execution for testing
async def main():
    """Test the agent"""
    agent = SectorExtractionAgent()

    # Test filing
    test_filing = {
        'type': '424B4',
        'ticker': 'HSPT',  # Horizon Space - should detect Space theme
        'url': 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001993072&type=424B4&dateb=&owner=exclude&count=1'
    }

    result = await agent.process(test_filing)
    print(f"\n📊 Result: {json.dumps(result, indent=2)}")


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
