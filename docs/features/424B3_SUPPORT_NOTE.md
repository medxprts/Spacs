# 424B3 Support for RANG and Similar SPACs

## Issue Discovered
RANG (Range Capital Acquisition Corp.) filed a **424B3** instead of the standard **424B4**:
- URL: https://www.sec.gov/Archives/edgar/data/2035644/000119312524282708/d831685d424b3.htm
- Filed: December 26, 2024
- IPO Date: December 23, 2024

## What is 424B3?
**424B4**: Final prospectus (standard for IPOs)
**424B3**: Prospectus filed pursuant to Rule 424(b)(3)
- Often used for post-effective amendments
- Can be used for shelf offerings or follow-on offerings
- Contains similar information to 424B4 but different context

## Current Behavior
Our code specifically looks for 424B4 filings:
```python
def get_prospectus(self, cik):
    # Searches for form_type "424B4"
```

When RANG is enriched:
```
4. Finding prospectus...
   ⚠️  Prospectus not found
```

Result: No enhanced 424B4 extraction performed (no overallotment, extensions, management, sponsor data)

## Should We Add 424B3 Support?

### Pros:
- ✅ Captures edge cases like RANG
- ✅ Same document structure as 424B4 (sections, tables, etc.)
- ✅ Contains all the same information we need
- ✅ Easy to implement (just add "424B3" to search)

### Cons:
- ❌ 424B3 is rare for IPOs (most use 424B4)
- ❌ May have different context (amendments vs original)
- ❌ Could introduce edge cases we haven't tested

## Recommendation

**Add 424B3 support as a fallback:**

```python
def get_prospectus(self, cik):
    """
    Get prospectus URL (424B4 or 424B3)
    424B4 = Final prospectus (standard)
    424B3 = Prospectus supplement (rare but valid)
    """
    # Try 424B4 first
    url = self._find_filing(cik, "424B4")
    if url:
        return url

    # Fallback to 424B3
    url = self._find_filing(cik, "424B3")
    if url:
        print("   ℹ️  Using 424B3 (no 424B4 found)")
        return url

    return None
```

## Implementation Priority

**Medium-Low Priority:**
- Only affects edge cases like RANG
- Most SPACs (95%+) use standard 424B4
- RANG already extracted basic data from press release
- Can add later if we see more 424B3 filings

## Alternative Approach

For RANG specifically, we could:
1. Manually verify the 424B3 has the same structure
2. Test extraction on RANG's 424B3
3. If successful, add 424B3 support

## Current Status

**No action needed immediately** - RANG is functional without 424B4 data:
- ✅ IPO date, proceeds, tickers extracted from press release
- ✅ Trust cash extracted from 10-Q
- ❌ Missing: overallotment, extensions, management, sponsor economics

**If we see more 424B3 filings**, implement fallback support.

---

**Date:** October 8, 2025
**Decision:** Monitor for additional 424B3 cases before implementing
