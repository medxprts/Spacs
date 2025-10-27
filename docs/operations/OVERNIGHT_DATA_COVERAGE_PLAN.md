# Overnight Data Coverage Improvement Plan

**Date:** October 10, 2025
**Goal:** Maximize data coverage while system runs overnight
**Estimated Runtime:** 6-8 hours (safe for overnight)

---

## Current Data Coverage Analysis

### ✅ Excellent Coverage (95%+)
- `ipo_date`: 185/185 (100%)
- `deadline_date`: 185/185 (100%)
- `price` (common): 185/185 (100%)
- `target` (for ANNOUNCED): 50/50 (100%)

### 🟡 Good Coverage (85-94%)
- `trust_cash`: 172/185 (93%)
- `unit_structure`: 174/185 (94%)
- `overallotment_units`: 161/185 (87%)

### 🟠 Moderate Coverage (60-84%)
- `extension_available`: 165/185 (89%)
- `unit_price`: 151/185 (82%)
- `warrant_price`: 83/185 (45%)
- `rights_price`: 58/185 (31%)

### 🔴 Poor Coverage (<60%)
- `warrant_exercise_price`: 113/185 (61%)
- `management_team`: 101/185 (55%)
- `founder_shares_cost`: 165/185 (89% - actually good!)

### 🔴 Critical Gap: Deal Data for ANNOUNCED SPACs
- `deal_value`: 20/50 (40%) - **CRITICAL**
- `pipe_size`: 10/50 (20%)
- `min_cash`: 3/50 (6%)
- `earnout_shares`: 0/50 (0%)

---

## Overnight Improvement Strategy

### Phase 1: Deal Data Enrichment (HIGH PRIORITY) 🔥
**Target:** ANNOUNCED SPACs missing deal data
**Runtime:** 2-3 hours
**Impact:** 30 SPACs improved

#### Script to Run
```bash
cd /home/ubuntu/spac-research
/home/ubuntu/spac-research/venv/bin/python3 -c "
from database import SessionLocal, SPAC
from s4_scraper import S4Scraper

db = SessionLocal()
announced_spacs = db.query(SPAC).filter(
    SPAC.deal_status == 'ANNOUNCED',
    SPAC.deal_value.is_(None)
).all()

print(f'Found {len(announced_spacs)} ANNOUNCED SPACs without deal_value')

scraper = S4Scraper(use_ai=True)

for spac in announced_spacs:
    print(f'\\nEnriching {spac.ticker} ({spac.target})...')
    try:
        scraper.scrape_s4_for_spac(spac.cik, spac.ticker, commit=True)
    except Exception as e:
        print(f'  Error: {e}')

print('\\nDeal enrichment complete!')
db.close()
" 2>&1 | tee logs/overnight_deal_enrichment.log
```

**Expected Improvements:**
- `deal_value`: 20 → 45 (+25 SPACs, 90% coverage)
- `pipe_size`: 10 → 35 (+25 SPACs, 70% coverage)
- `min_cash`: 3 → 30 (+27 SPACs, 60% coverage)
- `earnout_shares`: 0 → 20 (+20 SPACs, 40% coverage)

---

### Phase 2: Component Price Discovery (MEDIUM PRIORITY)
**Target:** Missing component prices
**Runtime:** 1-2 hours
**Impact:** 20-30 SPACs improved

#### Script to Run
```bash
cd /home/ubuntu/spac-research
/home/ubuntu/spac-research/venv/bin/python3 -c "
from price_updater import PriceUpdater
from database import SessionLocal, SPAC

db = SessionLocal()
updater = PriceUpdater(source='yfinance')

# Get SPACs missing component prices
missing_components = db.query(SPAC).filter(
    (SPAC.unit_price.is_(None)) |
    (SPAC.warrant_price.is_(None) & SPAC.rights_price.is_(None))
).all()

print(f'Found {len(missing_components)} SPACs with missing components')

for spac in missing_components:
    print(f'\\nUpdating {spac.ticker}...')
    try:
        components = updater.get_all_component_prices(spac)
        if components:
            updater.update_spac_prices(spac, components)
    except Exception as e:
        print(f'  Error: {e}')

db.commit()
print('\\nComponent price discovery complete!')
db.close()
" 2>&1 | tee logs/overnight_component_prices.log
```

**Expected Improvements:**
- `unit_price`: 151 → 165 (+14 SPACs, 89% coverage)
- `warrant_price`: 83 → 100 (+17 SPACs, 54% coverage)
- `rights_price`: 58 → 70 (+12 SPACs, 38% coverage)

---

### Phase 3: 424B4 Enhanced Extraction (MEDIUM PRIORITY)
**Target:** SPACs missing advanced 424B4 fields
**Runtime:** 2-3 hours
**Impact:** 60-80 SPACs improved

#### Script to Run
```bash
cd /home/ubuntu/spac-research
/home/ubuntu/spac-research/venv/bin/python3 -c "
from sec_data_scraper import SPACDataEnricher
from database import SessionLocal, SPAC

db = SessionLocal()

# Get SPACs missing advanced 424B4 fields
missing_424b4_data = db.query(SPAC).filter(
    (SPAC.management_team.is_(None)) |
    (SPAC.warrant_exercise_price.is_(None)) |
    (SPAC.overallotment_units.is_(None))
).all()

print(f'Found {len(missing_424b4_data)} SPACs needing 424B4 extraction')

enricher = SPACDataEnricher()

for spac in missing_424b4_data[:80]:  # Limit to 80 to stay within overnight window
    print(f'\\nExtracting 424B4 data for {spac.ticker}...')
    try:
        enricher.extract_424b4_enhanced(spac.ticker, spac.cik)
    except Exception as e:
        print(f'  Error: {e}')

print('\\n424B4 extraction complete!')
db.close()
" 2>&1 | tee logs/overnight_424b4_extraction.log
```

**Expected Improvements:**
- `warrant_exercise_price`: 113 → 160 (+47 SPACs, 86% coverage)
- `management_team`: 101 → 160 (+59 SPACs, 86% coverage)
- `overallotment_units`: 161 → 180 (+19 SPACs, 97% coverage)
- `extension_available`: 165 → 180 (+15 SPACs, 97% coverage)
- `founder_shares_cost`: 165 → 180 (+15 SPACs, 97% coverage)

---

### Phase 4: Trust Account Updates (LOW PRIORITY - Already Good)
**Target:** 13 SPACs missing trust_cash
**Runtime:** 30 minutes
**Impact:** 13 SPACs improved

#### Script to Run
```bash
cd /home/ubuntu/spac-research
/home/ubuntu/spac-research/venv/bin/python3 -c "
from agents.quarterly_report_extractor import QuarterlyReportExtractor
from database import SessionLocal, SPAC

db = SessionLocal()

# Get SPACs missing trust_cash
missing_trust = db.query(SPAC).filter(SPAC.trust_cash.is_(None)).all()

print(f'Found {len(missing_trust)} SPACs without trust_cash')

extractor = QuarterlyReportExtractor()

for spac in missing_trust:
    print(f'\\nExtracting trust cash for {spac.ticker}...')
    try:
        extractor.extract_from_latest_filing(spac.cik, spac.ticker, commit=True)
    except Exception as e:
        print(f'  Error: {e}')

print('\\nTrust account extraction complete!')
db.close()
" 2>&1 | tee logs/overnight_trust_extraction.log
```

**Expected Improvements:**
- `trust_cash`: 172 → 185 (+13 SPACs, 100% coverage)

---

## Complete Overnight Automation Script

Create and run this master script:

```bash
#!/bin/bash
# overnight_data_improvement.sh
# Run this before going to sleep!

cd /home/ubuntu/spac-research

echo "======================================================================"
echo "OVERNIGHT DATA COVERAGE IMPROVEMENT"
echo "Started: $(date)"
echo "======================================================================"

# Phase 1: Deal Data Enrichment (CRITICAL)
echo ""
echo "=== PHASE 1: Deal Data Enrichment ==="
/home/ubuntu/spac-research/venv/bin/python3 << 'EOF'
from database import SessionLocal, SPAC
from s4_scraper import S4Scraper

db = SessionLocal()
announced_spacs = db.query(SPAC).filter(
    SPAC.deal_status == 'ANNOUNCED',
    SPAC.deal_value.is_(None)
).all()

print(f'Found {len(announced_spacs)} ANNOUNCED SPACs without deal_value')

scraper = S4Scraper(use_ai=True)
success = 0
errors = 0

for spac in announced_spacs:
    print(f'\nEnriching {spac.ticker} ({spac.target})...')
    try:
        result = scraper.scrape_s4_for_spac(spac.cik, spac.ticker, commit=True)
        if result:
            success += 1
            print(f'  ✅ Success')
        else:
            print(f'  ⚠️  No S-4 found')
    except Exception as e:
        errors += 1
        print(f'  ❌ Error: {e}')

print(f'\nPhase 1 Complete: {success} success, {errors} errors')
db.close()
EOF

sleep 30

# Phase 2: Component Price Discovery
echo ""
echo "=== PHASE 2: Component Price Discovery ==="
/home/ubuntu/spac-research/venv/bin/python3 << 'EOF'
from price_updater import PriceUpdater
from database import SessionLocal, SPAC

db = SessionLocal()
updater = PriceUpdater(source='yfinance')

missing_components = db.query(SPAC).filter(
    (SPAC.unit_price.is_(None)) |
    (SPAC.warrant_price.is_(None) & SPAC.rights_price.is_(None))
).all()

print(f'Found {len(missing_components)} SPACs with missing components')

success = 0
errors = 0

for spac in missing_components:
    print(f'\nUpdating {spac.ticker}...')
    try:
        components = updater.get_all_component_prices(spac)
        if components:
            updater.update_spac_prices(spac, components)
            success += 1
            print(f'  ✅ Success')
    except Exception as e:
        errors += 1
        print(f'  ❌ Error: {e}')

db.commit()
print(f'\nPhase 2 Complete: {success} success, {errors} errors')
db.close()
EOF

sleep 30

# Phase 3: 424B4 Enhanced Extraction
echo ""
echo "=== PHASE 3: 424B4 Enhanced Extraction ==="
/home/ubuntu/spac-research/venv/bin/python3 << 'EOF'
from sec_data_scraper import SPACDataEnricher
from database import SessionLocal, SPAC

db = SessionLocal()

missing_424b4_data = db.query(SPAC).filter(
    (SPAC.management_team.is_(None)) |
    (SPAC.warrant_exercise_price.is_(None)) |
    (SPAC.overallotment_units.is_(None))
).all()

print(f'Found {len(missing_424b4_data)} SPACs needing 424B4 extraction')

enricher = SPACDataEnricher()
success = 0
errors = 0

for spac in missing_424b4_data[:80]:  # Limit to 80
    print(f'\nExtracting 424B4 for {spac.ticker}...')
    try:
        enricher.extract_424b4_enhanced(spac.ticker, spac.cik)
        success += 1
        print(f'  ✅ Success')
    except Exception as e:
        errors += 1
        print(f'  ❌ Error: {e}')

print(f'\nPhase 3 Complete: {success} success, {errors} errors')
db.close()
EOF

sleep 30

# Phase 4: Trust Account Updates
echo ""
echo "=== PHASE 4: Trust Account Updates ==="
/home/ubuntu/spac-research/venv/bin/python3 << 'EOF'
from agents.quarterly_report_extractor import QuarterlyReportExtractor
from database import SessionLocal, SPAC

db = SessionLocal()

missing_trust = db.query(SPAC).filter(SPAC.trust_cash.is_(None)).all()

print(f'Found {len(missing_trust)} SPACs without trust_cash')

extractor = QuarterlyReportExtractor()
success = 0
errors = 0

for spac in missing_trust:
    print(f'\nExtracting trust for {spac.ticker}...')
    try:
        extractor.extract_from_latest_filing(spac.cik, spac.ticker, commit=True)
        success += 1
        print(f'  ✅ Success')
    except Exception as e:
        errors += 1
        print(f'  ❌ Error: {e}')

print(f'\nPhase 4 Complete: {success} success, {errors} errors')
db.close()
EOF

echo ""
echo "======================================================================"
echo "OVERNIGHT DATA IMPROVEMENT COMPLETE"
echo "Finished: $(date)"
echo "======================================================================"
echo ""
echo "Check logs:"
echo "  - logs/overnight_deal_enrichment.log"
echo "  - logs/overnight_component_prices.log"
echo "  - logs/overnight_424b4_extraction.log"
echo "  - logs/overnight_trust_extraction.log"
```

---

## How to Run

### Option 1: One-Line Command (Recommended)
```bash
cd /home/ubuntu/spac-research
chmod +x overnight_data_improvement.sh
nohup ./overnight_data_improvement.sh > logs/overnight_full_$(date +%Y%m%d).log 2>&1 &
```

### Option 2: Screen Session (Monitor Progress)
```bash
screen -S overnight-improvement
cd /home/ubuntu/spac-research
./overnight_data_improvement.sh
# Ctrl+A, D to detach
```

### Option 3: Individual Phases (Debugging)
Run each phase separately if you want to monitor or debug:

```bash
# Phase 1 only (Deal Data - MOST IMPORTANT)
/home/ubuntu/spac-research/venv/bin/python3 -c "..."

# Phase 2 only (Component Prices)
/home/ubuntu/spac-research/venv/bin/python3 -c "..."
```

---

## Expected Total Improvements

### Before Overnight Run
- **Deal Data Coverage**: 40% (20/50 ANNOUNCED SPACs)
- **Component Prices**: 82% units, 45% warrants, 31% rights
- **Advanced 424B4 Fields**: 61% warrant terms, 55% management

### After Overnight Run (Projected)
- **Deal Data Coverage**: 90% (45/50) - **+125% improvement** 🔥
- **Component Prices**: 89% units, 54% warrants, 38% rights
- **Advanced 424B4 Fields**: 86% warrant terms, 86% management
- **Trust Cash**: 100% (185/185)

### Overall Data Completeness
- **Before**: ~75% average field coverage
- **After**: ~88% average field coverage
- **Improvement**: +13 percentage points

---

## Risk Mitigation

### API Rate Limits
- **SEC**: 10 requests/second (system already throttles)
- **DeepSeek AI**: No stated limit (monitor for errors)
- **Yahoo Finance**: No limit for free tier

### Error Handling
- Each phase has try/except blocks
- Errors logged but don't stop entire script
- Can resume failed SPACs manually

### Database Safety
- All updates use `commit=True` flag
- Tracker system auto-recalculates dependent fields
- No destructive operations

### Runtime Safety
- Estimated 6-8 hours total
- Safe for overnight run (will complete before morning)
- Can monitor via `tail -f logs/overnight_full_*.log`

---

## Morning Checklist

When you wake up:

1. **Check completion status:**
   ```bash
   tail -100 logs/overnight_full_$(date +%Y%m%d).log
   ```

2. **Verify data improvements:**
   ```bash
   PGPASSWORD=spacpass123 psql -U spac_user -d spac_db -c "
   SELECT
       COUNT(*) as total,
       COUNT(deal_value) FILTER (WHERE deal_status='ANNOUNCED') as deal_value,
       COUNT(unit_price) as unit_price,
       COUNT(warrant_exercise_price) as warrant_terms,
       COUNT(management_team) as management,
       COUNT(trust_cash) as trust_cash
   FROM spacs;
   "
   ```

3. **Check for errors:**
   ```bash
   grep -i "error" logs/overnight_full_*.log | wc -l
   ```

4. **Run data validator:**
   ```bash
   /home/ubuntu/spac-research/venv/bin/python3 data_validator_agent.py --report
   ```

---

## Alternative: Quick Win (Deal Data Only)

If you only have 2-3 hours, focus on **Phase 1** only (deal data enrichment):

```bash
cd /home/ubuntu/spac-research
/home/ubuntu/spac-research/venv/bin/python3 -c "
from database import SessionLocal, SPAC
from s4_scraper import S4Scraper

db = SessionLocal()
announced_spacs = db.query(SPAC).filter(
    SPAC.deal_status == 'ANNOUNCED',
    SPAC.deal_value.is_(None)
).all()

scraper = S4Scraper(use_ai=True)

for spac in announced_spacs:
    print(f'Enriching {spac.ticker}...')
    try:
        scraper.scrape_s4_for_spac(spac.cik, spac.ticker, commit=True)
        print(f'  ✅ Success')
    except Exception as e:
        print(f'  ❌ {e}')

db.close()
" 2>&1 | tee logs/quick_deal_enrichment.log
```

**Impact:** Improves MOST CRITICAL data gap (40% → 90% deal coverage)

---

**Ready to run!** 🚀

