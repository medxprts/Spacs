#!/usr/bin/env python3
"""
Investor Presentation Extractor

Extracts financial projections and business metrics from investor presentations
filed with the SEC (typically in 8-K, DEFA14A, or 425 filings).

Key extractions:
- Financial projections (revenue, EBITDA for 3+ years)
- Valuation multiples (EV/Revenue, EV/EBITDA)
- Business metrics (TAM, growth rates, margins)
"""

import os
import sys
import requests
import time
from datetime import datetime, date
from typing import Dict, Optional, List
from bs4 import BeautifulSoup
import re

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, SPAC
from dotenv import load_dotenv
import openai

load_dotenv()

class PresentationExtractor:
    """Extract financial data from investor presentations"""

    def __init__(self):
        self.db = SessionLocal()
        self.deepseek_key = os.getenv('DEEPSEEK_API_KEY')

        # Initialize DeepSeek (OpenAI-compatible)
        if self.deepseek_key:
            openai.api_key = self.deepseek_key
            openai.api_base = "https://api.deepseek.com"

    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()

    def find_presentation_filings(self, ticker: str, cik: str) -> List[Dict]:
        """
        Find investor presentation filings for a SPAC

        Looks for:
        - 8-K with presentation exhibits
        - DEFA14A (additional proxy materials)
        - 425 filings (often contain presentations)
        """
        if not cik:
            print(f"⚠️  No CIK for {ticker}")
            return []

        # Clean CIK
        cik_clean = cik.lstrip('0') if cik else None

        filings = []

        # Search for 8-K filings (last 6 months)
        filing_types = ['8-K', 'DEFA14A', '425']

        for filing_type in filing_types:
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_clean}&type={filing_type}&dateb=&owner=exclude&count=20"

            headers = {
                'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
            }

            try:
                response = requests.get(url, headers=headers, timeout=10)
                time.sleep(0.15)  # Rate limiting

                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')

                    # Find filing rows
                    rows = soup.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 4:
                            # Check if this looks like a presentation filing
                            description = row.get_text().lower()

                            # Keywords that indicate investor presentation
                            if any(keyword in description for keyword in [
                                'investor presentation',
                                'presentation materials',
                                'business combination presentation',
                                'transaction overview',
                                'merger presentation'
                            ]):
                                filing_date = cells[3].get_text().strip()
                                filing_link = cells[1].find('a')

                                if filing_link:
                                    doc_url = "https://www.sec.gov" + filing_link.get('href')
                                    filings.append({
                                        'type': filing_type,
                                        'date': filing_date,
                                        'url': doc_url,
                                        'description': description
                                    })

            except Exception as e:
                print(f"⚠️  Error fetching {filing_type} filings: {e}")

        return filings

    def extract_presentation_text(self, filing_url: str) -> Optional[str]:
        """
        Extract text content from presentation filing

        Presentations are often PDF exhibits, so this extracts:
        1. HTML content from the filing page
        2. Looks for exhibit links
        3. Extracts text from exhibits
        """
        headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }

        try:
            response = requests.get(filing_url, headers=headers, timeout=15)
            time.sleep(0.15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')

                # Get text from the filing
                text = soup.get_text(separator='\n', strip=True)

                # Limit text size (DeepSeek has token limits)
                max_chars = 50000
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[TRUNCATED]"

                return text

        except Exception as e:
            print(f"⚠️  Error extracting filing text: {e}")
            return None

    def extract_with_ai(self, text: str, ticker: str) -> Optional[Dict]:
        """
        Use DeepSeek AI to extract financial projections from presentation

        Returns structured data:
        - Projected revenue (Y1, Y2, Y3)
        - Projected EBITDA (Y1, Y2, Y3)
        - Valuation multiples
        - Business metrics
        """
        if not self.deepseek_key:
            print("⚠️  No DEEPSEEK_API_KEY configured")
            return None

        prompt = f"""
You are a financial analyst extracting data from a SPAC investor presentation for {ticker}.

Extract the following information from the presentation text:

1. **Financial Projections** (in millions $):
   - Projected revenue for next 3 years
   - Projected EBITDA for next 3 years

2. **Valuation Multiples**:
   - EV/Revenue multiple
   - EV/EBITDA multiple

3. **Business Metrics**:
   - Total addressable market (TAM) in billions
   - Revenue growth rate (CAGR %)
   - Target EBITDA margin (%)

Return ONLY a JSON object with this structure:
{{
  "projected_revenue_y1": <number or null>,
  "projected_revenue_y2": <number or null>,
  "projected_revenue_y3": <number or null>,
  "projected_ebitda_y1": <number or null>,
  "projected_ebitda_y2": <number or null>,
  "projected_ebitda_y3": <number or null>,
  "ev_revenue_multiple": <number or null>,
  "ev_ebitda_multiple": <number or null>,
  "addressable_market_size": <number or null>,
  "revenue_growth_rate": <number or null>,
  "ebitda_margin_target": <number or null>
}}

IMPORTANT:
- Return numbers without units (just the value)
- Revenue/EBITDA should be in millions
- TAM should be in billions
- Percentages as decimals (e.g., 25% = 25.0)
- Use null if not found
- Return ONLY valid JSON, no additional text

Text to analyze:
{text}
"""

        try:
            # Call DeepSeek API
            response = openai.ChatCompletion.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a financial data extraction expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )

            # Parse response
            content = response.choices[0].message['content'].strip()

            # Remove markdown code blocks if present
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

            # Parse JSON
            import json
            data = json.loads(content)

            # Validate data types
            for key in data:
                if data[key] is not None and not isinstance(data[key], (int, float)):
                    data[key] = None

            return data

        except Exception as e:
            print(f"⚠️  AI extraction error: {e}")
            return None

    def process_presentation(self, ticker: str, filing: Dict) -> bool:
        """
        Process a single investor presentation filing

        Returns True if data was extracted and saved
        """
        print(f"\n📊 Processing presentation for {ticker}")
        print(f"   Filing: {filing['type']} on {filing['date']}")

        # Extract text from filing
        text = self.extract_presentation_text(filing['url'])
        if not text:
            print("   ⚠️  Could not extract text")
            return False

        print(f"   ✓ Extracted {len(text):,} characters")

        # Extract data with AI
        data = self.extract_with_ai(text, ticker)
        if not data:
            print("   ⚠️  AI extraction failed")
            return False

        # Check if we got any useful data
        if all(v is None for v in data.values()):
            print("   ⚠️  No financial data found")
            return False

        print("   ✓ Extracted financial projections:")
        if data.get('projected_revenue_y1'):
            print(f"     Revenue: ${data['projected_revenue_y1']:.1f}M (Y1)")
        if data.get('ev_revenue_multiple'):
            print(f"     EV/Revenue: {data['ev_revenue_multiple']:.1f}x")

        # Save to database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"   ⚠️  SPAC {ticker} not found in database")
            return False

        # Update SPAC record
        spac.investor_presentation_url = filing['url']
        spac.presentation_filing_date = datetime.strptime(filing['date'], '%Y-%m-%d').date()
        spac.presentation_filing_type = filing['type']

        # Set financial projections
        for key, value in data.items():
            if value is not None:
                setattr(spac, key, value)

        # Set source tracking
        spac.projections_source = filing['type']
        spac.projections_filing_date = datetime.strptime(filing['date'], '%Y-%m-%d').date()

        self.db.commit()
        print(f"   ✅ Saved to database")

        return True

    def extract_for_spac(self, ticker: str) -> bool:
        """
        Find and extract investor presentation data for a SPAC

        Returns True if presentation was found and processed
        """
        # Get SPAC from database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return False

        # Need CIK to search SEC
        if not spac.cik:
            print(f"⚠️  {ticker}: No CIK, cannot search SEC")
            return False

        print(f"\n🔍 Searching for investor presentations: {ticker}")

        # Find presentation filings
        filings = self.find_presentation_filings(ticker, spac.cik)

        if not filings:
            print(f"   No investor presentations found")
            return False

        print(f"   Found {len(filings)} potential presentation(s)")

        # Process most recent presentation
        for filing in filings[:1]:  # Process just the most recent
            if self.process_presentation(ticker, filing):
                return True

        return False


def main():
    """Test presentation extraction"""
    import sys

    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        extractor = PresentationExtractor()
        extractor.extract_for_spac(ticker)
    else:
        print("Usage: python presentation_extractor.py <TICKER>")
        print("\nExample: python presentation_extractor.py CEP")


if __name__ == "__main__":
    main()
