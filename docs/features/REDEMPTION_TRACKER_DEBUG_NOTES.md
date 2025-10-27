# Redemption Tracker - Debug Notes & Test Cases

## Known Test Cases (From BoardroomAlpha)

### 1. Eureka Acquisition Corp (EURK)
- **Date**: ~July 2, 2025
- **Shares Redeemed**: 3,038,722
- **Type**: Extension vote redemption
- **Source**: Daily SPAC Update – July 2, 2025

### 2. SLAM Corp (SLAM)
- **Date**: ~July 2, 2025
- **Shares Redeemed**: 1,885,947
- **Type**: Extension vote redemption
- **Source**: Daily SPAC Update – July 2, 2025

### 3. Integrated Rail & Resources Acquisition Corp (IRRX)
- **Date**: July 2025
- **Shares Redeemed**: 16,528
- **Redemption Amount**: $223,624
- **Price per Share**: $13.53
- **Type**: Deal approved redemption
- **Source**: Daily SPAC Update – July 2025

### 4. Breeze Holdings Acquisition Corp (BRZH)
- **Date**: ~August 18, 2025
- **Shares Redeemed**: 49,715
- **Type**: Deal approval (YD Biopharma merger)
- **Source**: Daily SPAC Update – August 18, 2025

### 5. Globalink Investment Inc (GLLI)
- **Date**: ~August 2025
- **Type**: Non-Reliance 8-K (incorrect redemption payments)
- **Note**: Indicates redemption mispayments occurred
- **Source**: Daily SPAC Update – August 18, 2025

### 6. Cohen Circle Acquisition I (KYIV)
- **Date**: Recent (2025)
- **Redemption Rate**: <40% (low for recent SPACs)
- **Type**: De-SPAC merger with Kyivstar
- **Source**: Renaissance Capital

## Known Issues

### Issue #1: iXBRL Document Format
**Problem**: Many 8-Ks are now filed as iXBRL (interactive data format)
- Example: EURK's 8-K uses `/ix?doc=/Archives/edgar/data/.../ea0254711-8k_eureka.htm`
- Our parser needs to handle iXBRL viewer URLs

**Solution**:
```python
# Handle iXBRL URLs
if '/ix?doc=' in doc_url:
    actual_url = self.base_url + doc_url.split('/ix?doc=')[1]
```

### Issue #2: Extension Vote Redemptions Not in 8-K Body
**Problem**: Extension vote redemptions may be disclosed in:
1. Press releases (exhibits)
2. Third-party trackers (BoardroomAlpha, Renaissance Capital)
3. Next 10-Q filing
4. Investor relations website

**Current Coverage**: Only checking main 8-K document

**Solution**:
- Also check Exhibit 99.1 (press releases)
- Fallback to 10-Q comparison (shares_outstanding change)

### Issue #3: Document Parsing Logic
**Problem**: Our find_super_8k() returns 0 8-Ks even though they exist

**Debug Steps**:
1. ✅ Verified 8-Ks exist (manual curl check shows 16 8-Ks for EURK)
2. ⏳ Need to check if document link extraction is working
3. ⏳ Need to verify HTTP requests aren't failing silently

**Likely Cause**:
- Document link selector not matching iXBRL format
- Or exception being caught and suppressed

### Issue #4: Keyword Filtering Too Narrow
**Previous Approach**: Filter 8-Ks by keywords before AI extraction
**Current Approach**: Fetch ALL recent 8-Ks, let AI decide (better)

**Learnings from Other Parsers**:
- S-4 parser: Uses section-based extraction (works well)
- Pre-IPO parser: Handles exhibits (S-1/A amendments)
- Deal monitor: Checks both main doc AND exhibits

## Recommended Fix Strategy

### Phase 1: Apply Lessons from Working Parsers

**From `s4_merger_parser_agent.py`**:
```python
# Extract specific sections, not entire document
def extract_relevant_sections(self, soup):
    # Find redemption-related sections
    # Strategy: Search for headings with "redemption", "voting", "results"
    # Extract just those sections (99% reduction)
```

**From `pre_ipo_spac_finder.py`**:
```python
# Check BOTH main document AND exhibits
def get_8k_documents(self, filing_url):
    # Priority 1: Main 8-K
    # Priority 2: Exhibit 99.1 (press release)
    # Priority 3: Exhibit 99.2 (voting results)
```

**From `sec_data_scraper.py`**:
```python
# Handle iXBRL viewer URLs
if '/ix?doc=' in main_url:
    main_url = self.base_url + main_url.split('/ix?doc=')[1]
```

### Phase 2: Enhanced Redemption Detection

**Strategy 1: Multi-Source Approach**
1. Check 8-K main document
2. Check 8-K exhibits (99.1, 99.2)
3. Check subsequent 10-Q for shares_outstanding change
4. Compare trust_cash change

**Strategy 2: Section-Based Extraction**
```python
# Instead of sending entire 8-K to AI, extract just relevant sections
redemption_sections = [
    "Item 5.07",  # Submission of Matters to Vote
    "voting results",
    "redemption",
    "shares tendered"
]
```

**Strategy 3: Comparative Analysis**
```python
# If no explicit redemption data, compare:
# - Previous shares_outstanding vs current
# - Previous trust_cash vs current
# - If significant decrease → redemptions likely occurred
```

## Testing Protocol

### Test SPACs (In Order):
1. **BRZH** (August 2025, 49K shares) - Most recent, should be easiest
2. **IRRX** (July 2025, 16K shares) - Small redemption
3. **SLAM** (July 2025, 1.8M shares) - Extension vote
4. **EURK** (July 2025, 3M shares) - Extension vote, larger
5. **KYIV** (<40% redemption rate) - De-SPAC merger
6. **GLLI** (Mispayment issue) - Edge case

### Success Criteria:
- Extract redemption data from at least 4/6 test cases
- Handle both deal-closing AND extension vote redemptions
- Correctly update shares_outstanding

## Next Steps

1. ✅ Document test cases
2. ⏳ Implement iXBRL handling
3. ⏳ Add exhibit checking (99.1, 99.2)
4. ⏳ Implement section-based extraction
5. ⏳ Add comparative analysis fallback
6. ⏳ Test on 6 known cases
7. ⏳ Integrate into orchestrator

## Related Files

- `redemption_tracker.py` - Main implementation
- `s4_merger_parser_agent.py` - Section extraction example
- `pre_ipo_spac_finder.py` - Exhibit handling example
- `sec_data_scraper.py` - iXBRL handling example

## Cost Optimization

**Current**: Fetch entire 8-K document (avg 200KB)
**Optimized**: Extract just relevant sections (20KB, 90% reduction)

**Estimated Savings**:
- 100 SPACs × 4 8-Ks/year × 90% reduction = 360KB → 36KB per SPAC/year
- AI cost: $0.0001 → $0.00001 per parse (10x reduction)
