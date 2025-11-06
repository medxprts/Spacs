"""
Banker Tier Classification

Tier 1 (Bulge Bracket): 10 points
- Major global investment banks
- Top-tier SPAC track record
- High deal completion rates

Tier 2 (Mid-Market): 7 points  
- Established mid-market banks
- Strong SPAC presence
- Good track record

Tier 3 (Boutique): 4 points
- Smaller boutique firms
- SPAC specialists
- Mixed track record
"""

BANKER_TIERS = {
    # TIER 1: Top Performers + Bulge Bracket (10 points)
    # Data-driven: Best historical performance or premier brand
    'Tier 1': [
        # Proven top performers (data-driven)
        'Cohen & Company Capital Markets',  # +3.3% avg pop, 9 deals
        'Cohen & Company',
        'BTIG',  # +0.9% avg pop, +235% current premium
        'BTIG, LLC',
        'Cantor Fitzgerald',  # +0.2% avg pop, 10 deals (most active)
        'Cantor Fitzgerald & Co.',
        # Bulge bracket banks (premier brand)
        'Goldman Sachs',
        'Morgan Stanley',
        'J.P. Morgan',
        'JPMorgan',
        'JPMorgan Chase',
        'Citigroup',
        'Citigroup Global Markets Inc.',
        'UBS',
        'UBS Investment Bank',
        'Bank of America',
        'BofA Securities',
        'Jefferies',
        'Jefferies LLC',
        'Credit Suisse',
        'Deutsche Bank',
        'Barclays',
    ],
    
    # TIER 2: Mid-Market (7 points)
    'Tier 2': [
        'Maxim Group',  # 0.0% avg pop, 3 deals (neutral)
        'Maxim Group LLC',
        'Oppenheimer',
        'Oppenheimer & Co.',
        'Stifel',
        'Stifel, Nicolaus & Company, Incorporated',
        'Cowen',
        'Piper Sandler',
        'William Blair',
        'RBC Capital Markets',
        'BMO Capital Markets',
        'BTIG',
        'BTIG, LLC',
        'Roth Capital Partners',
        'Roth Capital Partners, LLC',
        'B. Riley Securities',
        'B. Riley',
        'Stephens Inc.',
        'Stephens',
        'Benchmark Company',
        'Benchmark',
        'Santander',
        'Santander US Capital Markets LLC',
        'Santander US Capital Markets',
        'Needham & Company',
        'Needham & Company, LLC',
        'Craig-Hallum',
        'Leerink Partners',
        'Lazard',
        'Lazard Capital Markets',
        'Lazard Capital Markets LLC',
    ],
    
    # TIER 3: Boutique / Poor Track Record (4 points)
    'Tier 3': [
        # Poor performers (data-driven)
        'EF Hutton',  # -5.1% avg pop (POOR)
        'EF Hutton LLC',
        'EF Hutton, division of Benchmark Investment',
        'EarlyBirdCapital',  # -4.6% avg pop (POOR despite SPAC specialist)
        'EarlyBirdCapital, Inc.',
        'Chardan Capital Markets',  # -3.5% avg pop (POOR)
        'Chardan Capital Markets, LLC',
        # Unknown performance
        'I-Bankers Securities',
        'I-Bankers Securities, Inc.',
        'ThinkEquity',
        'A.G.P./Alliance Global Partners',
        'Alliance Global Partners',
        'D. Boral Capital',
        'D. Boral Capital LLC',
        'Network 1 Financial',
        'Clear Street',
        'Clear Street LLC',
        'SPAC Advisory Partners',
        'SPAC Advisory Partners LLC',
        'SPAC Advisory Partners, a division of Kingswood',
        'Kingswood Capital Partners',
        'Kingswood Capital Partners, LLC',
        'Spartan Capital Securities',
        'LifeSci Capital',
        'LifeSci Capital LLC',
        'Brookline Capital Markets',
        'Lucid Capital Markets',
        'Polaris Advisory Partners',
        'Polaris Advisory Partners LLC',
    ],
}


def get_banker_tier(banker_name: str) -> tuple[str, int]:
    """
    Get tier and points for a banker
    
    Args:
        banker_name: Banker name from database
        
    Returns:
        (tier_name, points): e.g., ('Tier 1', 10)
    """
    if not banker_name:
        return (None, 0)
    
    # Normalize name for matching
    banker_lower = banker_name.lower().strip()
    
    # Check Tier 1
    for tier1_banker in BANKER_TIERS['Tier 1']:
        if tier1_banker.lower() in banker_lower:
            return ('Tier 1', 10)
    
    # Check Tier 2
    for tier2_banker in BANKER_TIERS['Tier 2']:
        if tier2_banker.lower() in banker_lower:
            return ('Tier 2', 7)
    
    # Check Tier 3
    for tier3_banker in BANKER_TIERS['Tier 3']:
        if tier3_banker.lower() in banker_lower:
            return ('Tier 3', 4)
    
    # Unknown banker
    return (None, 0)
