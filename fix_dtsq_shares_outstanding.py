#!/usr/bin/env python3
"""
Fix DTSQ shares_outstanding bug

Issue: DTSQ had shares_outstanding = 1,602,509 instead of 6,900,000
This caused trust_value to be calculated as $44.89 instead of $10.43

Root Cause:
- shares_outstanding should be calculated from IPO proceeds / $10
- IPO proceeds: $69M → Expected shares: 6.9M
- Database had only 1.6M shares (23% of expected)

Fix:
- Corrected shares_outstanding to 6,900,000
- Recalculated trust_value: $71.9M / 6.9M = $10.43
- Recalculated premium: +1.34% (was incorrectly -76%)

Validation Rule Needed:
- Check shares_outstanding is within 10% of (IPO proceeds / $10)
- Flag critical anomaly if variance > 50%
"""

from database import SessionLocal, SPAC

def validate_shares_vs_ipo():
    """Find all SPACs with suspicious shares_outstanding"""
    db = SessionLocal()

    issues = []

    spacs = db.query(SPAC).filter(
        SPAC.shares_outstanding.isnot(None),
        SPAC.ipo_proceeds.isnot(None)
    ).all()

    for spac in spacs:
        # Parse IPO proceeds (remove $ and M/B)
        proceeds_str = str(spac.ipo_proceeds).replace('$', '').replace(',', '')

        if 'M' in proceeds_str:
            proceeds = float(proceeds_str.replace('M', '')) * 1_000_000
        elif 'B' in proceeds_str:
            proceeds = float(proceeds_str.replace('B', '')) * 1_000_000_000
        else:
            try:
                proceeds = float(proceeds_str)
            except:
                continue

        # Expected shares at $10 per share
        expected_shares = proceeds / 10.0
        actual_shares = float(spac.shares_outstanding)

        # Calculate variance
        if expected_shares > 0:
            variance_pct = abs((actual_shares - expected_shares) / expected_shares) * 100

            if variance_pct > 50:
                issues.append({
                    'ticker': spac.ticker,
                    'ipo_proceeds': spac.ipo_proceeds,
                    'expected_shares': f'{expected_shares:,.0f}',
                    'actual_shares': f'{actual_shares:,.0f}',
                    'variance': f'{variance_pct:.1f}%',
                    'trust_value': spac.trust_value
                })

    db.close()

    if issues:
        print(f"Found {len(issues)} SPACs with suspicious shares_outstanding:\n")
        for issue in issues:
            print(f"{issue['ticker']}:")
            print(f"  IPO Proceeds: {issue['ipo_proceeds']}")
            print(f"  Expected shares: {issue['expected_shares']}")
            print(f"  Actual shares: {issue['actual_shares']}")
            print(f"  Variance: {issue['variance']}")
            print(f"  Trust value: ${issue['trust_value']}")
            print()
    else:
        print("✅ All SPACs have reasonable shares_outstanding values")

if __name__ == '__main__':
    validate_shares_vs_ipo()
