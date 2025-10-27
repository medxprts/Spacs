# 424B4 Extraction Guide - Targeted Section Strategy

**Goal**: Extract key IPO data from 424B4 filings without sending 1.8M chars to AI

**Token Savings**: 91.7% reduction (from ~460K tokens to ~38K tokens per filing)

---

## Key Data Points Needed

| Data Point | Location | Found In Section |
|------------|----------|------------------|
| **Units offered** | Cover page, The Offering | ✅ Multiple |
| **Price per unit** | Cover page | ✅ Multiple |
| **Total proceeds** | Cover page, Prospectus Summary | ✅ Multiple |
| **Overallotment option** | The Offering (0.3% - 2%) | ✅ 119 mentions |
| **Warrant structure** | Cover page, The Offering | ✅ 11 mentions |
| **Warrant exercise price** | The Offering | ✅ Multiple |
| **Warrant expiration** | The Offering | ✅ Multiple |
| **Business combination deadline** | Prospectus Summary, The Offering | ✅ Multiple |
| **Extension terms** | Prospectus Summary, The Offering (0.2% - 2%) | ✅ 31 mentions |
| **Trust account terms** | The Offering | ✅ Multiple |
| **Underwriters** | Cover page | ✅ Multiple |
| **Sponsor name** | Prospectus Summary, Cover | ✅ 378 mentions |
| **Target sector/industry** | Prospectus Summary, Business | ✅ Multiple |
| **Founder shares** | Prospectus Summary, Capitalization | ✅ Multiple |

---

## Section Positions (CCCX Example)

| Section | Start Position | % of Document | Size | Priority |
|---------|---------------|---------------|------|----------|
| **Cover Page** | 0 | 0% | 15K chars | ✅ CRITICAL |
| Table of Contents | 254 | 0.01% | ~10K chars | ❌ Skip |
| **The Offering** | 6,400 | 0.3% | 50K chars | ✅ CRITICAL |
| Dilution | 10,747 | 0.6% | ~10K chars | ⚠️ Optional |
| Capitalization | 13,110 | 0.7% | ~10K chars | ⚠️ Optional (founder shares) |
| Risk Factors | 15,788 | 0.9% | ~30K chars | ❌ Skip |
| Use of Proceeds | 46,699 | 2.5% | ~20K chars | ❌ Skip |
| **Prospectus Summary** | 174,635 | 9.5% | 80K chars | ✅ HIGH VALUE |

---

## Extraction Strategy

### Tier 1: Essential Sections (Send to AI)
```python
sections_to_extract = {
    'cover_page': (0, 15000),                    # 15K chars
    'the_offering': (6400, 56400),               # 50K chars
    'prospectus_summary': (174635, 254635),      # 80K chars (or until RISK FACTORS)
}

# Total: ~145K chars vs 1.8M chars (92% reduction)
```

### Tier 2: Optional Sections (If needed)
```python
optional_sections = {
    'capitalization': (13110, 23110),  # For founder shares if not in summary
    'dilution': (10747, 20747),        # For founder share dilution details
}
```

### Tier 3: Skip Entirely
- Risk Factors (huge, no IPO data)
- Use of Proceeds (generic language)
- Management Bios (not needed for IPO metrics)
- Financial Statements (historical only, not relevant for new SPACs)

---

## Data Extraction by Section

### 1. Cover Page (0-15K chars)

**Contains:**
- ✅ Units offered: "36,000,000 Units"
- ✅ Price per unit: "$10.00 per unit"
- ✅ Underwriter: "BTIG, LLC"
- ✅ Unit structure: "one Class A ordinary share and one-fourth of one warrant"
- ⚠️ May not have overallotment details

**Strategy**: Always extract, quick scan for basic terms

### 2. The Offering Section (6.4K - ~50K)

**Contains (119 mentions of overallotment!):**
- ✅ Overallotment option: "45-day option to purchase up to an additional 5,400,000 units"
- ✅ Warrant structure: "Each unit consists of one Class A ordinary share and one-fourth of one warrant"
- ✅ Warrant exercise: "$11.50 per share"
- ✅ Warrant expiration: "five years"
- ✅ Trust account: "$10.00 per share"
- ✅ Extension terms: "24 months (or 27 months if LOI executed)"

**Strategy**: CRITICAL - Most structured IPO data here

**Example Extension Language Found:**
```
"We will have 24 months from the closing of this offering to consummate
an initial business combination (or 27 months from the closing of this
offering if we have executed a letter of intent, agreement in principle
or definitive agreement for an initial business combination within 24 months
from the closing of this offering; no redemption rights shall be offered
to our public shareholders in connection with any such extension from
24 months to 27 months if we have executed a letter of intent..."
```

### 3. Prospectus Summary (174K - ~255K)

**Contains:**
- ✅ Business combination deadline
- ✅ Extension terms (detailed)
- ✅ Trust account mechanics
- ✅ Sponsor economics
- ✅ Use of proceeds
- ✅ Founder shares (often here)

**Strategy**: High value for deadline/extension terms

### 4. Capitalization Section (13K - ~23K) - OPTIONAL

**Contains:**
- ✅ Founder shares: Exact count
- ✅ Public vs founder share breakdown
- ✅ Dilution impact

**Strategy**: Only if founder shares not in Prospectus Summary

---

## Extension Terms - What to Extract

SPACs vary, but typical structures:

**Pattern 1: Automatic Extension with LOI (CCCX example)**
- Base: 24 months
- Extension: +3 months if LOI/agreement executed
- No shareholder vote needed for automatic extension
- Further extensions require shareholder vote

**Pattern 2: Shareholder Vote Extensions**
- Base: 18 months
- Extensions: 3 or 6 months via shareholder vote
- May require sponsor deposit ($0.03-$0.10 per share)
- Redemption rights at each extension

**Pattern 3: Fixed Maximum**
- Base: 24 months
- No extensions allowed
- Hard deadline

**Data to Extract:**
1. Base deadline period (18, 24, or 36 months)
2. Extension availability (yes/no)
3. Extension length (3, 6, or 12 months)
4. Extension requirements:
   - LOI/agreement required?
   - Shareholder vote required?
   - Sponsor deposit required?
   - Amount of deposit per share
5. Maximum possible time (base + all extensions)
6. Redemption rights during extension

---

## Implementation Code

```python
class Filing424B4Extractor:
    """Extract key sections from 424B4"""

    def get_essential_sections(self) -> dict:
        """Extract only the essential sections for AI analysis"""

        # 1. Cover page - always start here
        cover = self.html[:15000]

        # 2. Find "The Offering" section (most critical)
        offering_start = self.find_section('THE OFFERING')
        offering_end = self.find_section('SUMMARY FINANCIAL') or offering_start + 50000
        offering = self.html[offering_start:offering_end]

        # 3. Find "Prospectus Summary"
        summary_start = self.find_section('PROSPECTUS SUMMARY')
        summary_end = self.find_section('RISK FACTORS') or summary_start + 80000
        summary = self.html[summary_start:summary_end]

        return {
            'cover_page': cover,
            'the_offering': offering,
            'prospectus_summary': summary
        }

    def extract_extension_terms(self, text: str) -> dict:
        """Extract deadline extension terms"""
        # Look for: "24 months" + "27 months" or "36 months"
        # Look for: "letter of intent", "shareholder vote", "deposit"

        pattern = r'.{0,400}(?:\d{1,2})\s*months.{0,100}(?:\d{1,2})\s*months.{0,400}'
        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            context = match.group(0)
            if any(kw in context.lower() for kw in ['extend', 'extension']):
                return self.parse_extension_clause(context)

        return {}
```

---

## Token Savings Calculation

**Per 424B4 Filing:**
- Full document: ~1,839,052 chars (459,763 tokens)
- Extracted sections: ~153,430 chars (38,357 tokens)
- **Savings: 421,406 tokens (91.7%)**

**For 186 SPACs:**
- Full extraction cost: 186 × 459,763 = 85.5M tokens
- Targeted extraction: 186 × 38,357 = 7.1M tokens
- **Total savings: 78.4M tokens**

**Cost Impact (DeepSeek pricing $0.14/1M input tokens):**
- Full: $11.97
- Targeted: $0.99
- **Savings: $10.98 per batch (92% cost reduction)**

---

## Validation Checklist

After extraction, verify these data points are captured:

```python
required_fields = {
    'units_offered': '36,000,000',
    'price_per_unit': '$10.00',
    'overallotment_units': '5,400,000',
    'warrant_ratio': '1/4' or '0.25',
    'warrant_exercise_price': '$11.50',
    'deadline_months': 24,
    'extension_available': True/False,
    'extension_months': 3 or 6,
    'extension_requires_loi': True/False,
    'trust_value_per_share': '$10.00',
    'underwriter': 'BTIG',
}
```

---

## Next Steps

1. ✅ Integrate `Filing424B4Extractor` into `sec_data_scraper.py`
2. ✅ Update `extract_from_prospectus()` to use targeted extraction
3. ✅ Add extension terms extraction to database schema
4. ✅ Test on 5-10 recent SPACs to verify data capture
5. ✅ Deploy and re-enrich all 186 SPACs with new method
