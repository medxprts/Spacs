#!/usr/bin/env python3
"""
Fix DTSQ trust_cash after redemptions

Issue: After Oct 24, 2025 redemption event, shares_outstanding was correctly
updated from 6.9M to 1.6M, but trust_cash was never updated. This caused
trust_value to be incorrectly calculated as $44.89 instead of ~$10.41.

Root Cause:
- 8-K filing from Oct 24 disclosed redemption count but not updated trust balance
- System correctly extracted shares redeemed: 5,297,491 (59.5%)
- System did NOT update trust_cash (remained at $71.9M)
- Trust value calculation: $71.9M / 1.6M = $44.89 (WRONG)

Correct Calculation (from DEF14A + 8-K):
- Trust cash as of Sept 17, 2025 (per DEF14A): $72,452,618
- NAV per share (disclosed): $10.50
- Original shares: 6,900,000
- Shares redeemed at vote: 5,297,491
- Cash paid to redeemers: 5,297,491 × $10.50 = $55,623,655.50
- Sponsor extension deposit (per 8-K): $75,000
- Remaining trust_cash: $72,452,618 - $55,623,655.50 + $75,000 = $16,903,962.50
- Remaining shares: 1,602,509
- Correct trust value: $16,903,962.50 / 1,602,509 = $10.55 per share

Data Sources:
- DEF14A filed before vote: Pre-redemption trust balance and NAV
- 8-K filed after vote: Redemption count and extension payment amount

Fix Applied:
- Updated trust_cash: $71,936,152 → $16,903,962.50
- Recalculated trust_value: $44.89 → $10.55
- Recalculated premium: -76.45% → +0.47%

Validation Rule Needed:
- When shares_outstanding decreases (redemptions), trust_cash must also decrease
- Flag critical anomaly if trust_cash doesn't decrease proportionally
- Add to data_validator_agent.py

Future Enhancement Needed:
- Parse DEF14A filings before shareholder votes to capture pre-redemption trust balance
- Parse 8-K post-vote to capture redemption count AND extension deposits
- Calculate post-redemption trust = pre_trust - (redeemed_shares × NAV) + extension_deposit
- Apply this pattern for ALL proxy votes (extensions, deal votes, liquidations)
"""

from database import SessionLocal, SPAC
from utils.trust_account_tracker import update_trust_cash, recalculate_premium
from datetime import datetime

def fix_dtsq_redemption():
    """Fix DTSQ trust_cash and trust_value after redemption event"""
    db = SessionLocal()

    try:
        spac = db.query(SPAC).filter(SPAC.ticker == 'DTSQ').first()

        if not spac:
            print("❌ DTSQ not found in database")
            return

        print(f"\n🔍 Current DTSQ values:")
        print(f"   trust_cash: ${spac.trust_cash:,.2f}")
        print(f"   shares_outstanding: {spac.shares_outstanding:,.0f}")
        print(f"   trust_value: ${spac.trust_value}")
        print(f"   premium: {spac.premium:.2f}%")

        # Calculate correct values based on DEF14A + 8-K
        pre_vote_trust_cash = 72452618  # From DEF14A filed Sept 17, 2025
        nav_per_share = 10.50  # Disclosed in DEF14A
        original_shares = 6900000
        shares_redeemed = 5297491
        remaining_shares = 1602509
        extension_deposit = 75000  # From 8-K - sponsor deposit for extension

        cash_paid_out = shares_redeemed * nav_per_share
        correct_trust_cash = pre_vote_trust_cash - cash_paid_out + extension_deposit
        correct_trust_value = correct_trust_cash / remaining_shares

        print(f"\n📊 Calculation (DEF14A + 8-K):")
        print(f"   Pre-vote trust (DEF14A Sept 17): ${pre_vote_trust_cash:,.2f}")
        print(f"   Original shares: {original_shares:,}")
        print(f"   NAV per share (disclosed): ${nav_per_share:.2f}")
        print(f"   Shares redeemed: {shares_redeemed:,}")
        print(f"   Cash paid out: ${cash_paid_out:,.2f}")
        print(f"   Extension deposit: ${extension_deposit:,.2f}")
        print(f"   Correct trust_cash: ${correct_trust_cash:,.2f}")
        print(f"   Correct trust_value: ${correct_trust_value:.2f}")

        # Update trust_cash using utility function
        update_trust_cash(
            db_session=db,
            ticker='DTSQ',
            new_value=correct_trust_cash,
            source='8-K',
            filing_date=datetime(2025, 10, 24).date()
        )

        # Recalculate trust_value and premium
        if spac.shares_outstanding and spac.shares_outstanding > 0:
            spac.trust_value = round(spac.trust_cash / spac.shares_outstanding, 2)

        recalculate_premium(db, 'DTSQ')

        db.commit()

        # Show updated values
        db.refresh(spac)
        print(f"\n✅ Updated DTSQ values:")
        print(f"   trust_cash: ${spac.trust_cash:,.2f}")
        print(f"   trust_value: ${spac.trust_value}")
        print(f"   premium: {spac.premium:.2f}%")

        print(f"\n✅ Fix applied successfully")
        print(f"   Changes logged to trust_account_history")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == '__main__':
    fix_dtsq_redemption()
