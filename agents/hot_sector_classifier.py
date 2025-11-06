#!/usr/bin/env python3
"""
Hot Sector Classifier
====================
Classifies SPAC sectors and identifies "hot" sectors for Phase 1 scoring.

Hot sectors are those with strong current market interest and potential for premium valuations.

Usage:
    python3 hot_sector_classifier.py --all          # Classify all pre-deal SPACs
    python3 hot_sector_classifier.py --ticker CEP   # Classify single SPAC
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
import argparse
import re

# Define hot sectors (2025 market trends)
HOT_SECTORS = {
    'AI & Machine Learning': [
        'ai', 'artificial intelligence', 'machine learning', 'deep learning',
        'neural network', 'large language model', 'llm', 'generative ai',
        'computer vision', 'natural language'
    ],
    'Cloud & Data Infrastructure': [
        'cloud', 'data center', 'infrastructure', 'saas', 'software as a service',
        'paas', 'iaas', 'edge computing', 'data storage'
    ],
    'Cybersecurity': [
        'cybersecurity', 'cyber security', 'information security', 'data security',
        'threat detection', 'endpoint security', 'network security'
    ],
    'FinTech': [
        'fintech', 'financial technology', 'digital payments', 'blockchain',
        'cryptocurrency', 'crypto', 'defi', 'digital banking', 'payment processing'
    ],
    'Healthcare Technology': [
        'healthtech', 'health tech', 'digital health', 'telemedicine',
        'medical technology', 'diagnostics', 'biotech', 'life sciences',
        'pharmaceutical', 'medical devices'
    ],
    'Electric Vehicles': [
        'electric vehicle', 'ev', 'battery', 'automotive', 'autonomous vehicle',
        'self-driving', 'charging infrastructure'
    ],
    'Clean Energy': [
        'clean energy', 'renewable energy', 'solar', 'wind energy',
        'hydrogen', 'energy storage', 'green energy', 'sustainable energy',
        'carbon capture'
    ],
    'Space & Defense': [
        'space', 'aerospace', 'satellite', 'defense', 'military',
        'national security', 'space exploration'
    ]
}


def classify_sector(sector_text: str) -> tuple[str, bool]:
    """
    Classify a sector and determine if it's hot.

    Args:
        sector_text: Text describing the sector (from sector or sector_details fields)

    Returns:
        (classified_sector, is_hot): Tuple of classified sector name and hot flag
    """
    if not sector_text:
        return ('General', False)

    # Normalize text
    text_lower = sector_text.lower()

    # Check each hot sector
    for sector_name, keywords in HOT_SECTORS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return (sector_name, True)

    # Not a hot sector - try to extract general category
    if any(word in text_lower for word in ['tech', 'software', 'digital', 'internet']):
        return ('Technology', False)
    elif any(word in text_lower for word in ['health', 'medical', 'pharma', 'bio']):
        return ('Healthcare', False)
    elif any(word in text_lower for word in ['energy', 'oil', 'gas', 'power']):
        return ('Energy', False)
    elif any(word in text_lower for word in ['financial', 'bank', 'insurance', 'capital']):
        return ('Financial Services', False)
    elif any(word in text_lower for word in ['industrial', 'manufacturing', 'infrastructure']):
        return ('Industrial', False)
    elif any(word in text_lower for word in ['consumer', 'retail', 'e-commerce']):
        return ('Consumer', False)
    elif any(word in text_lower for word in ['real estate', 'property', 'reits']):
        return ('Real Estate', False)
    else:
        return ('General', False)


def classify_spac(spac):
    """
    Classify a SPAC's sector based on available data.

    Priority:
    1. sector_details (most detailed)
    2. sector (general classification)
    3. company name (last resort)
    """
    # Try sector_details first (most detailed)
    if spac.sector_details:
        classified, is_hot = classify_sector(spac.sector_details)
        if classified != 'General' or is_hot:
            return classified, is_hot

    # Try sector field
    if spac.sector:
        classified, is_hot = classify_sector(spac.sector)
        if classified != 'General' or is_hot:
            return classified, is_hot

    # Try company name as last resort
    if spac.company:
        classified, is_hot = classify_sector(spac.company)
        return classified, is_hot

    # Default
    return ('General', False)


def classify_all():
    """Classify all pre-deal SPACs"""
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').all()

        print(f"\n📊 Classifying {len(spacs)} pre-deal SPACs...\n")

        hot_count = 0
        updates = []

        for spac in spacs:
            classified_sector, is_hot = classify_spac(spac)

            # Update database
            spac.sector_classified = classified_sector
            spac.is_hot_sector = is_hot

            if is_hot:
                hot_count += 1
                updates.append(f"✨ {spac.ticker}: {classified_sector} (HOT)")
            else:
                updates.append(f"   {spac.ticker}: {classified_sector}")

        db.commit()

        print("✅ Classification complete!\n")
        print(f"Results:")
        print(f"  Total classified: {len(spacs)}")
        print(f"  Hot sectors: {hot_count} ({hot_count/len(spacs)*100:.1f}%)")
        print(f"  General/Other: {len(spacs) - hot_count}\n")

        # Show hot sector breakdown
        if hot_count > 0:
            print("🔥 Hot Sectors:")
            hot_sectors = {}
            for spac in spacs:
                if spac.is_hot_sector:
                    sector = spac.sector_classified
                    if sector not in hot_sectors:
                        hot_sectors[sector] = []
                    hot_sectors[sector].append(spac.ticker)

            for sector, tickers in sorted(hot_sectors.items()):
                print(f"  {sector}: {len(tickers)} SPACs")
                print(f"    {', '.join(tickers)}")

    finally:
        db.close()


def classify_single(ticker):
    """Classify a single SPAC"""
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker.upper()).first()

        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return

        classified_sector, is_hot = classify_spac(spac)

        # Update database
        spac.sector_classified = classified_sector
        spac.is_hot_sector = is_hot
        db.commit()

        print(f"\n📊 Sector Classification for {ticker}\n")
        print(f"Company: {spac.company}")
        print(f"Original sector: {spac.sector or 'N/A'}")
        print(f"Classified as: {classified_sector}")
        print(f"Hot sector: {'Yes ✨' if is_hot else 'No'}")

        if spac.sector_details:
            print(f"\nDetails: {spac.sector_details[:200]}...")

    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hot Sector Classifier')
    parser.add_argument('--all', action='store_true', help='Classify all pre-deal SPACs')
    parser.add_argument('--ticker', type=str, help='Classify single SPAC')

    args = parser.parse_args()

    if args.all:
        classify_all()
    elif args.ticker:
        classify_single(args.ticker)
    else:
        print("Usage: python3 hot_sector_classifier.py --all OR --ticker <TICKER>")
        sys.exit(1)
