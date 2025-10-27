#!/usr/bin/env python3
"""
Pre-IPO SPAC Graduation
Moves SPACs with closed IPOs from pre-IPO pipeline to main SPAC table
"""

from datetime import datetime
from pre_ipo_database import SessionLocal, PreIPOSPAC
from database import SessionLocal as MainSessionLocal, SPAC


class PreIPOGraduation:
    """Graduate closed pre-IPO SPACs to main pipeline"""

    def __init__(self):
        self.pre_ipo_db = SessionLocal()
        self.main_db = MainSessionLocal()

    def graduate_spac(self, pre_ipo_spac: PreIPOSPAC) -> bool:
        """Move a single pre-IPO SPAC to main table"""
        try:
            # SAFEGUARD: Check if already exists in main table (prevent duplicates)
            existing_by_ticker = self.main_db.query(SPAC).filter(
                SPAC.ticker == pre_ipo_spac.expected_ticker
            ).first()

            existing_by_cik = self.main_db.query(SPAC).filter(
                SPAC.cik == pre_ipo_spac.cik
            ).first()

            if existing_by_ticker or existing_by_cik:
                print(f"   ⚠️  {pre_ipo_spac.company} already exists in main table - skipping duplicate")
                print(f"      Ticker: {existing_by_ticker.ticker if existing_by_ticker else 'N/A'}")
                return False

            # Create new SPAC entry in main table
            spac = SPAC(
                ticker=pre_ipo_spac.expected_ticker or "TBD",
                company=pre_ipo_spac.company,

                # IPO data
                ipo_date=pre_ipo_spac.ipo_close_date,
                ipo_proceeds=pre_ipo_spac.target_proceeds,
                ipo_price=pre_ipo_spac.actual_ipo_price or 10.00,

                # Structure
                unit_ticker=pre_ipo_spac.expected_ticker + "U" if pre_ipo_spac.expected_ticker else None,
                warrant_ticker=pre_ipo_spac.expected_ticker + "W" if pre_ipo_spac.expected_ticker and not pre_ipo_spac.has_rights else None,
                right_ticker=pre_ipo_spac.expected_ticker + "R" if pre_ipo_spac.expected_ticker and pre_ipo_spac.has_rights else None,
                unit_structure=pre_ipo_spac.unit_structure,
                warrant_ratio=pre_ipo_spac.warrant_ratio,

                # Trust & Deadline
                trust_value=pre_ipo_spac.trust_per_unit or 10.00,
                deadline_months=pre_ipo_spac.charter_deadline_months,

                # Banking & Parties
                banker=pre_ipo_spac.lead_banker,
                co_bankers=pre_ipo_spac.co_bankers,
                sponsor=pre_ipo_spac.sponsor,
                sponsor_promote=pre_ipo_spac.sponsor_promote,

                # Classification
                sector=pre_ipo_spac.target_sector,
                geography=pre_ipo_spac.target_geography,
                banker_tier=pre_ipo_spac.banker_tier,
                sponsor_quality_score=pre_ipo_spac.sponsor_quality_score,

                # Deal status (newly public, searching for target)
                deal_status='SEARCHING',

                # SEC
                cik=pre_ipo_spac.cik,

                # Metadata
                created_at=datetime.now(),
                data_source='pre_ipo_pipeline',
                notes=f"Graduated from pre-IPO pipeline on {datetime.now().strftime('%Y-%m-%d')}. Original S-1 filed: {pre_ipo_spac.s1_filing_date}"
            )

            # Calculate deadline date
            if spac.ipo_date and spac.deadline_months:
                from dateutil.relativedelta import relativedelta
                spac.deadline_date = spac.ipo_date + relativedelta(months=spac.deadline_months)

            # Add to main database
            self.main_db.add(spac)
            self.main_db.commit()

            # Update pre-IPO record
            pre_ipo_spac.moved_to_main_pipeline = True
            pre_ipo_spac.main_spac_id = spac.id
            self.pre_ipo_db.commit()

            print(f"   ✅ Graduated {spac.company} ({spac.ticker}) to main pipeline")
            print(f"      IPO: {spac.ipo_date}, Deadline: {spac.deadline_date}")

            return True

        except Exception as e:
            print(f"   ❌ Error graduating {pre_ipo_spac.company}: {e}")
            self.main_db.rollback()
            self.pre_ipo_db.rollback()
            return False

    def run_graduation(self):
        """Find and graduate all closed SPACs"""
        print("="*60)
        print("PRE-IPO SPAC GRADUATION")
        print("="*60 + "\n")

        # Find closed SPACs not yet graduated
        ready_spacs = self.pre_ipo_db.query(PreIPOSPAC).filter(
            PreIPOSPAC.filing_status == 'Closed',
            PreIPOSPAC.moved_to_main_pipeline == False
        ).all()

        if not ready_spacs:
            print("✅ No SPACs ready to graduate")
            return

        print(f"🎓 Found {len(ready_spacs)} SPAC(s) ready to graduate\n")

        graduated_count = 0

        for i, spac in enumerate(ready_spacs, 1):
            print(f"[{i}/{len(ready_spacs)}] {spac.company}")
            print(f"   Ticker: {spac.expected_ticker or 'TBD'}")
            print(f"   IPO closed: {spac.ipo_close_date}")

            if self.graduate_spac(spac):
                graduated_count += 1

        print("\n" + "="*60)
        print(f"✅ Graduated {graduated_count}/{len(ready_spacs)} SPACs")
        print("="*60)

    def close(self):
        """Close database connections"""
        self.pre_ipo_db.close()
        self.main_db.close()


if __name__ == "__main__":
    graduator = PreIPOGraduation()
    try:
        graduator.run_graduation()
    finally:
        graduator.close()
