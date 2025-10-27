#!/usr/bin/env python3
"""
Smart Trust Cash Sourcing Strategy

Priority Waterfall:
1. New SPACs (<3 months old): Extract from 424B4 prospectus (initial trust size)
2. Older SPACs (>3 months): Extract from latest 10-Q/K (current balance after redemptions)
3. Fallback: Calculate (shares_outstanding * trust_value)
4. Validation: Compare extracted vs calculated to flag discrepancies

This ensures we get the most accurate trust cash for each SPAC's lifecycle stage.
"""

from database import SessionLocal, SPAC
from datetime import datetime, timedelta
from sec_data_scraper import SPACDataEnricher
import time

def smart_trust_cash_sourcing():
    """Source trust cash using age-appropriate method"""
    
    db = SessionLocal()
    enricher = SPACDataEnricher()
    
    try:
        # Get all SPACs needing trust cash update
        spacs = db.query(SPAC).filter(
            SPAC.ipo_date.isnot(None)
        ).all()
        
        today = datetime.now().date()
        
        print("💰 SMART TRUST CASH SOURCING")
        print("=" * 80)
        print(f"Analyzing {len(spacs)} SPACs\n")
        
        new_spacs = []      # <3 months old
        mature_spacs = []   # >3 months old
        no_date = []        # Missing IPO date
        
        # Categorize by age
        for spac in spacs:
            if not spac.ipo_date:
                no_date.append(spac)
                continue
            
            ipo_date = spac.ipo_date.date() if isinstance(spac.ipo_date, datetime) else spac.ipo_date
            age_days = (today - ipo_date).days
            
            if age_days < 90:  # <3 months
                new_spacs.append((spac, age_days))
            else:
                mature_spacs.append((spac, age_days))
        
        print(f"📊 CATEGORIZATION")
        print("-" * 80)
        print(f"New SPACs (<3 months):     {len(new_spacs)}")
        print(f"Mature SPACs (>3 months):  {len(mature_spacs)}")
        print(f"No IPO date:               {len(no_date)}")
        
        # Strategy 1: New SPACs - Extract from 424B4
        print(f"\n📕 STRATEGY 1: New SPACs - Extract from 424B4 ({len(new_spacs)} SPACs)")
        print("-" * 80)
        
        new_extracted = 0
        for spac, age in sorted(new_spacs, key=lambda x: x[1])[:10]:  # Limit to 10 for testing
            if not spac.prospectus_424b4_url:
                print(f"  {spac.ticker} ({age}d old): No 424B4 URL, skipping")
                continue
            
            try:
                print(f"  {spac.ticker} ({age}d old): Extracting from 424B4...", end=" ", flush=True)
                
                # Extract trust cash from 424B4
                # Look for "gross proceeds" or "public offering" amount
                import requests
                response = requests.get(spac.prospectus_424b4_url, headers={'User-Agent': 'SPAC Research fenil@legacyevp.com'}, timeout=30)
                text = response.text
                
                # Parse for trust account size
                import re
                
                # Pattern 1: "gross proceeds of $XXX million"
                match = re.search(r'gross proceeds of (?:approximately )?\$([0-9,\.]+)\s*million', text, re.IGNORECASE)
                if match:
                    amount = float(match.group(1).replace(',', '')) * 1_000_000
                    spac.trust_cash = amount
                    spac.data_source = '424b4_extracted' if not spac.data_source else f"{spac.data_source},424b4_extracted"
                    print(f"✓ ${amount/1e6:.1f}M from 424B4")
                    new_extracted += 1
                else:
                    print("✗ Not found in 424B4")
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                print(f"✗ Error: {e}")
        
        db.commit()
        print(f"\n✅ Extracted trust cash for {new_extracted}/{min(10, len(new_spacs))} new SPACs from 424B4")
        
        # Strategy 2: Mature SPACs - Extract from 10-Q
        print(f"\n📊 STRATEGY 2: Mature SPACs - Extract from 10-Q ({len(mature_spacs)} SPACs)")
        print("-" * 80)
        print("Focus on SPACs with likely redemptions (>5% variance from calculated)")
        
        # Get SPACs with variance from validation
        variance_spacs = []
        for spac, age in mature_spacs:
            if spac.trust_cash and spac.shares_outstanding and spac.trust_value:
                calculated = float(spac.shares_outstanding) * float(spac.trust_value)
                actual = float(spac.trust_cash)
                variance_pct = ((actual - calculated) / calculated * 100) if calculated > 0 else 0
                
                if abs(variance_pct) > 5:
                    variance_spacs.append((spac, age, variance_pct))
        
        print(f"Found {len(variance_spacs)} SPACs with >5% variance (likely redemptions)")
        
        mature_extracted = 0
        for spac, age, variance in sorted(variance_spacs, key=lambda x: abs(x[2]), reverse=True)[:5]:
            try:
                print(f"  {spac.ticker} ({age}d old, {variance:+.1f}% variance): Extracting from 10-Q...", end=" ", flush=True)
                
                # This would call the 10-Q extraction method
                # enricher.extract_trust_cash_from_10q(spac.ticker)
                print("⏸️  Skipped (would extract from 10-Q)")
                
            except Exception as e:
                print(f"✗ {e}")
        
        # Strategy 3: Calculate for remaining
        print(f"\n🔢 STRATEGY 3: Calculate Missing Trust Cash")
        print("-" * 80)
        
        missing = db.query(SPAC).filter(
            SPAC.trust_cash.is_(None),
            SPAC.shares_outstanding.isnot(None),
            SPAC.trust_value.isnot(None)
        ).all()
        
        print(f"Found {len(missing)} SPACs with missing trust cash")
        
        calculated = 0
        for spac in missing:
            trust_cash = float(spac.shares_outstanding) * float(spac.trust_value)
            spac.trust_cash = trust_cash
            spac.data_source = 'calculated' if not spac.data_source else f"{spac.data_source},trust_cash_calc"
            calculated += 1
        
        db.commit()
        print(f"✅ Calculated trust cash for {calculated} SPACs")
        
        # Summary
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("-" * 80)
        print(f"424B4 Extracted (new SPACs):    {new_extracted}")
        print(f"10-Q Extracted (mature SPACs):  {mature_extracted}")
        print(f"Calculated (fallback):          {calculated}")
        print(f"\n✅ Total SPACs updated: {new_extracted + mature_extracted + calculated}")
        
        # Final coverage
        total_with_trust = db.query(SPAC).filter(SPAC.trust_cash.isnot(None)).count()
        total = db.query(SPAC).count()
        print(f"📈 Final trust cash coverage: {total_with_trust}/{total} ({total_with_trust/total*100:.1f}%)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    smart_trust_cash_sourcing()
