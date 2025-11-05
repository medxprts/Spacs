#!/usr/bin/env python3
"""
Sector Classifier - Extract and classify SPAC target sectors

Purpose: Fix terrible sector data ("General", "TMT", multiple sectors)
         Extract SPECIFIC target sector from S-1 filing
         Map to hot narrative sectors for opportunity agent

Usage:
    from utils.sector_classifier import SectorClassifier

    classifier = SectorClassifier()
    result = classifier.classify_spac('BLUW')
    # Returns: {'sector_classified': 'AI', 'confidence': 95, 'reasoning': '...'}
"""

import os
import sys
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional
import re

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC
from pre_ipo_database import SessionLocal as PreIPOSessionLocal, PreIPOSPAC

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


# Hot Narrative Sectors (for opportunity agent)
HOT_SECTORS = {
    'AI': {
        'keywords': ['artificial intelligence', 'ai', 'machine learning', 'deep learning',
                     'neural network', 'computer vision', 'nlp', 'generative ai', 'llm'],
        'score': 10,
        'description': 'Artificial Intelligence / Machine Learning'
    },
    'Cybersecurity': {
        'keywords': ['cybersecurity', 'cyber security', 'infosec', 'information security',
                     'threat detection', 'zero trust', 'endpoint security'],
        'score': 10,
        'description': 'Cybersecurity'
    },
    'Digital Assets': {
        'keywords': ['crypto', 'blockchain', 'digital assets', 'web3', 'defi',
                     'nft', 'cryptocurrency', 'bitcoin', 'ethereum'],
        'score': 10,
        'description': 'Digital Assets / Crypto / Blockchain'
    },
    'Next-Gen Energy': {
        'keywords': ['electric vehicle', 'ev', 'battery', 'clean energy', 'renewable',
                     'solar', 'wind', 'energy storage', 'charging', 'sustainability'],
        'score': 10,
        'description': 'Next-Gen Energy (EV, Battery, Renewable)'
    },
    'FinTech': {
        'keywords': ['fintech', 'financial technology', 'payments', 'digital banking',
                     'insurtech', 'lending', 'payment processing', 'proptech'],
        'score': 10,
        'description': 'FinTech'
    },
    'Space': {
        'keywords': ['space', 'aerospace', 'satellite', 'launch', 'orbital',
                     'space exploration', 'spacetech'],
        'score': 10,
        'description': 'Space / Aerospace'
    },
    'BioTech': {
        'keywords': ['biotech', 'gene therapy', 'crispr', 'genomics', 'precision medicine',
                     'cell therapy', 'rare disease', 'oncology'],
        'score': 10,
        'description': 'BioTech / Gene Therapy'
    }
}

BORING_SECTORS = {
    'Industrials': {
        'keywords': ['manufacturing', 'industrial', 'machinery', 'construction',
                     'building materials', 'engineering'],
        'score': 0,
        'description': 'Industrials / Manufacturing'
    },
    'Consumer Goods': {
        'keywords': ['consumer goods', 'retail', 'consumer products', 'apparel',
                     'food', 'beverage', 'restaurants'],
        'score': 0,
        'description': 'Consumer Goods / Retail'
    },
    'Real Estate': {
        'keywords': ['real estate', 'property', 'reit', 'commercial real estate',
                     'residential', 'hospitality', 'hotels'],
        'score': 0,
        'description': 'Real Estate'
    },
    'Traditional Finance': {
        'keywords': ['banking', 'insurance', 'asset management', 'private equity',
                     'investment management'],
        'score': 0,
        'description': 'Traditional Finance'
    }
}


class SectorClassifier:
    """Classifies SPACs into hot narrative sectors vs boring sectors"""

    def __init__(self):
        self.db = SessionLocal()
        self.pre_ipo_db = PreIPOSessionLocal()
        self.headers = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}

    def classify_spac(self, ticker: str) -> Dict:
        """
        Classify a SPAC's target sector

        Returns:
            {
                'sector_classified': 'AI' | 'Cybersecurity' | 'Boring' | None,
                'confidence': 0-100,
                'reasoning': 'explanation',
                'keywords_matched': ['ai', 'machine learning'],
                'is_hot_sector': True/False
            }
        """
        print(f"\n🔍 Classifying sector for {ticker}...")

        # Get SPAC from database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            # Try pre-IPO database
            spac = self.pre_ipo_db.query(PreIPOSPAC).filter(
                PreIPOSPAC.expected_ticker == ticker
            ).first()

        if not spac:
            return {'error': f'SPAC {ticker} not found'}

        # Get S-1 filing URL
        s1_url = spac.s1_filing_url if hasattr(spac, 's1_filing_url') else None
        if not s1_url and hasattr(spac, 's1_url'):
            s1_url = spac.s1_url

        if not s1_url:
            print(f"   ⚠️  No S-1 URL found - using existing sector data")
            return self._classify_from_existing_data(spac)

        # Extract business strategy from S-1
        print(f"   📄 Fetching S-1 filing...")
        business_text = self._extract_business_section(s1_url)

        if not business_text:
            print(f"   ⚠️  Could not extract business section - using existing data")
            return self._classify_from_existing_data(spac)

        # Classify with AI
        print(f"   🤖 Classifying with AI...")
        result = self._classify_with_ai(business_text, spac.company)

        return result

    def _extract_business_section(self, s1_url: str) -> Optional[str]:
        """Extract 'Business Strategy' or 'Target Industry' section from S-1"""
        try:
            response = requests.get(s1_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()

            # Look for key sections
            patterns = [
                r'BUSINESS STRATEGY.*?(?=RISK FACTORS|MANAGEMENT|CAPITALIZATION)',
                r'TARGET BUSINESS.*?(?=RISK FACTORS|MANAGEMENT|CAPITALIZATION)',
                r'INVESTMENT CRITERIA.*?(?=RISK FACTORS|MANAGEMENT)',
                r'INDUSTRY FOCUS.*?(?=RISK FACTORS|MANAGEMENT)'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    section_text = match.group(0)
                    # Limit to first 5000 chars
                    return section_text[:5000]

            # Fallback: First 5000 chars
            return text[:5000]

        except Exception as e:
            print(f"   ❌ Error extracting S-1: {e}")
            return None

    def _classify_with_ai(self, business_text: str, company_name: str) -> Dict:
        """Use AI to classify sector"""
        if not AI_AVAILABLE:
            return {'error': 'AI not available'}

        try:
            prompt = f"""Classify the PRIMARY target sector for this SPAC based on their business strategy.

Company: {company_name}

Business Strategy Excerpt:
{business_text[:3000]}

Hot Narrative Sectors (return ONE of these if match):
- AI: Artificial Intelligence, Machine Learning, Computer Vision, NLP, Generative AI
- Cybersecurity: Cybersecurity, InfoSec, Threat Detection, Security
- Digital Assets: Crypto, Blockchain, Web3, DeFi, NFT
- Next-Gen Energy: EV, Battery, Clean Energy, Renewable, Solar, Wind
- FinTech: Financial Technology, Payments, Digital Banking, InsurTech
- Space: Space, Aerospace, Satellite, Launch
- BioTech: Gene Therapy, CRISPR, Genomics, Precision Medicine

Boring Sectors (return ONE of these if match):
- Industrials: Manufacturing, Construction, Machinery
- Consumer Goods: Retail, Consumer Products, Food & Beverage
- Real Estate: Property, REITs, Hospitality
- Traditional Finance: Banking, Insurance, Asset Management

General Sectors (if no specific match):
- Technology: Broad tech (software, SaaS, enterprise)
- Healthcare: General healthcare (not biotech)
- Consumer: General consumer (not retail)

Return ONLY valid JSON:
{{
    "sector_classified": "AI" | "Cybersecurity" | "Digital Assets" | "Next-Gen Energy" | "FinTech" | "Space" | "BioTech" | "Industrials" | "Consumer Goods" | "Real Estate" | "Traditional Finance" | "Technology" | "Healthcare" | "Consumer" | "General",
    "confidence": 0-100,
    "reasoning": "1-2 sentence explanation",
    "keywords_matched": ["keyword1", "keyword2"]
}}

IMPORTANT: Return the MOST SPECIFIC sector. If they mention AI, don't return "Technology", return "AI"."""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=300
            )

            result_text = response.choices[0].message.content.strip()
            result_text = re.sub(r'```json\s*|\s*```', '', result_text)

            import json
            result = json.loads(result_text)

            # Add is_hot_sector flag
            result['is_hot_sector'] = result['sector_classified'] in HOT_SECTORS

            print(f"   ✓ Classified as: {result['sector_classified']} ({result['confidence']}% confidence)")
            print(f"   Keywords: {', '.join(result['keywords_matched'])}")

            return result

        except Exception as e:
            print(f"   ❌ AI classification error: {e}")
            return {'error': str(e)}

    def _classify_from_existing_data(self, spac) -> Dict:
        """Fallback: Classify from existing sector field"""
        sector = spac.sector if hasattr(spac, 'sector') else None
        if not sector:
            sector = spac.target_sector if hasattr(spac, 'target_sector') else 'General'

        sector_lower = sector.lower() if sector else 'general'

        # Check hot sectors
        for hot_name, hot_data in HOT_SECTORS.items():
            for keyword in hot_data['keywords']:
                if keyword in sector_lower:
                    return {
                        'sector_classified': hot_name,
                        'confidence': 70,  # Lower confidence (keyword match only)
                        'reasoning': f'Matched keyword "{keyword}" in sector "{sector}"',
                        'keywords_matched': [keyword],
                        'is_hot_sector': True
                    }

        # Check boring sectors
        for boring_name, boring_data in BORING_SECTORS.items():
            for keyword in boring_data['keywords']:
                if keyword in sector_lower:
                    return {
                        'sector_classified': boring_name,
                        'confidence': 70,
                        'reasoning': f'Matched keyword "{keyword}" in sector "{sector}"',
                        'keywords_matched': [keyword],
                        'is_hot_sector': False
                    }

        # Default: General or Technology
        if 'tech' in sector_lower:
            return {
                'sector_classified': 'Technology',
                'confidence': 50,
                'reasoning': 'Generic technology sector',
                'keywords_matched': ['tech'],
                'is_hot_sector': False
            }

        return {
            'sector_classified': 'General',
            'confidence': 30,
            'reasoning': f'Could not classify sector "{sector}"',
            'keywords_matched': [],
            'is_hot_sector': False
        }

    def update_spac_sector(self, ticker: str, commit: bool = False) -> bool:
        """Classify and update SPAC sector in database"""
        result = self.classify_spac(ticker)

        if 'error' in result:
            print(f"   ❌ {result['error']}")
            return False

        # Update database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"   ⚠️  SPAC not in main database")
            return False

        # Add new columns if they don't exist
        from sqlalchemy import text
        try:
            self.db.execute(text("""
                ALTER TABLE spacs ADD COLUMN IF NOT EXISTS sector_classified VARCHAR(50);
                ALTER TABLE spacs ADD COLUMN IF NOT EXISTS sector_confidence INT;
                ALTER TABLE spacs ADD COLUMN IF NOT EXISTS is_hot_sector BOOLEAN DEFAULT FALSE;
            """))
            self.db.commit()
        except:
            pass

        # Update SPAC
        spac.sector_classified = result['sector_classified']
        spac.sector_confidence = result['confidence']
        spac.is_hot_sector = result['is_hot_sector']

        if commit:
            self.db.commit()
            print(f"   ✅ Updated {ticker} → {result['sector_classified']}")
        else:
            print(f"   ℹ️  Would update {ticker} → {result['sector_classified']} (dry run)")

        return True

    def classify_all_searching_spacs(self, commit: bool = False):
        """Classify all SPACs with deal_status='SEARCHING'"""
        spacs = self.db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').all()

        print(f"\n{'='*60}")
        print(f"Classifying {len(spacs)} SEARCHING SPACs")
        print(f"{'='*60}\n")

        success_count = 0
        hot_count = 0

        for i, spac in enumerate(spacs, 1):
            print(f"[{i}/{len(spacs)}] {spac.ticker} ({spac.company})")

            success = self.update_spac_sector(spac.ticker, commit=commit)
            if success:
                success_count += 1
                if spac.is_hot_sector:
                    hot_count += 1

            # Rate limiting
            import time
            time.sleep(2)

        print(f"\n{'='*60}")
        print(f"Classification Complete")
        print(f"{'='*60}")
        print(f"Total: {len(spacs)}")
        print(f"Successful: {success_count}")
        print(f"Hot Sectors: {hot_count}")
        print(f"Boring/General: {success_count - hot_count}")

    def close(self):
        """Close database connections"""
        self.db.close()
        self.pre_ipo_db.close()


# CLI interface
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Classify SPAC target sectors')
    parser.add_argument('--ticker', help='Classify single SPAC')
    parser.add_argument('--all', action='store_true', help='Classify all SEARCHING SPACs')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database')

    args = parser.parse_args()

    classifier = SectorClassifier()

    try:
        if args.ticker:
            result = classifier.classify_spac(args.ticker)
            print(f"\nResult: {result}")
            if not result.get('error'):
                classifier.update_spac_sector(args.ticker, commit=args.commit)

        elif args.all:
            classifier.classify_all_searching_spacs(commit=args.commit)

        else:
            parser.print_help()
            print("\nExample usage:")
            print("  python3 sector_classifier.py --ticker BLUW")
            print("  python3 sector_classifier.py --all --commit")

    finally:
        classifier.close()
