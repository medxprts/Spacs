# Extraction Agent Few-Shot Learning - Design Document

**Created**: 2025-11-04
**Status**: Design Phase (Not Implemented)
**Purpose**: Enable extraction agents to proactively learn from past errors during normal operation

---

## Problem Statement

**Current Reality**:
- Investigation Agent uses Few-Shot learning reactively (after anomalies detected) ✅
- Extraction agents do NOT use Few-Shot learning proactively ❌
- Same extraction errors repeat because agents don't learn from past mistakes
- Agents return `None` for missing data instead of searching filings

**Example Failures**:
1. **CHAC** (Nov 4, 2025): AI returned `"1.1M"` instead of `1100000` → Database write failed
2. **Missing Trust Data**: Agent finds `trust_value = None`, returns None instead of searching 10-Q
3. **Invalid Target Names**: Agent extracts sponsor entity as target instead of actual company

**User Insight**:
> "I think the right solution is first confirm it's still a SPAC that isn't completed, and then to try to find it in filings"

---

## Design Goals

1. **Proactive Learning**: Query learning database BEFORE extraction (not after failure)
2. **Action-Based Teaching**: Teach agents HOW to find data (not WHAT to return)
3. **Filing Search Hints**: Use past successes to guide where to search
4. **Format Prevention**: Include past format errors in prompts to prevent recurrence
5. **Progressive Improvement**: Each extraction learns from all past extractions

---

## Architecture

### 1. Learning Query Module

**File**: `utils/extraction_learner.py` (NEW)

**Purpose**: Centralized interface for extraction agents to query past learnings

**Key Functions**:

```python
def get_extraction_lessons(field: str, issue_types: List[str] = None, limit: int = 5) -> Dict:
    """
    Get past learnings for a specific field extraction

    Args:
        field: Database field being extracted ('trust_value', 'earnout_shares', etc.)
        issue_types: Types of issues to learn from ['format_error', 'missing_data']
        limit: Max number of past cases to retrieve

    Returns:
        {
            'format_warnings': [
                "AI returned '1.1M' instead of 1100000 → Use sanitize_ai_response()",
                "AI returned '$275M' instead of 275000000"
            ],
            'filing_hints': [
                "trust_value found in 10-Q Item 1 - Financial Statements (5 successes)",
                "trust_value found in S-1 Part II - Financial Data (2 successes)"
            ],
            'common_mistakes': [
                "Don't extract sponsor entities as target company",
                "Check if value is 'TBD' or 'N/A' before returning"
            ],
            'success_patterns': [
                "Look for '$X.XX per share' language in trust account section"
            ]
        }
    """
```

```python
def get_filing_search_strategy(field: str, ticker: str = None) -> Dict:
    """
    Get smart filing search strategy based on past successes

    Returns:
        {
            'primary_source': '10-Q',
            'section_hints': ['Item 1', 'Financial Statements', 'Balance Sheet'],
            'fallback_sources': ['S-1', '8-K'],
            'lookback_days': 90,
            'past_success_rate': 0.85
        }
    """
```

```python
def log_extraction_success(
    field: str,
    ticker: str,
    filing_type: str,
    filing_section: str,
    extraction_method: str,
    value_extracted: Any
):
    """
    Log successful extraction to build filing search hints

    This creates positive examples in learning database:
    - "Found trust_value in 10-Q Item 1" (builds filing_hints)
    - "Extracted using regex pattern: $\\d+\\.\\d+ per share"
    """
```

---

### 2. Enhanced Base Agent

**File**: `agents/base_agent.py` (MODIFY)

**Add Learning Methods**:

```python
from utils.extraction_learner import get_extraction_lessons, get_filing_search_strategy

class BaseAgent:
    """Base class for all filing agents"""

    def get_lessons_for_field(self, field: str) -> Dict:
        """
        Get past learnings for a field (wrapper for easy access)

        Usage:
            lessons = self.get_lessons_for_field('earnout_shares')
            print(lessons['format_warnings'])  # Include in AI prompt
        """
        return get_extraction_lessons(
            field=field,
            issue_types=['format_error', 'missing_data', 'validation_error'],
            limit=5
        )

    def search_for_missing_data(
        self,
        ticker: str,
        field: str,
        db_session
    ) -> Optional[Any]:
        """
        Proactive search for missing data in SEC filings

        Steps:
        1. Check if SPAC is still active (not completed)
        2. Get filing search strategy from past successes
        3. Search filings in priority order
        4. Extract using AI with past learnings
        5. Validate and return

        Returns:
            Extracted value or None if not found
        """
        from database import SPAC

        # 1. Check if SPAC is active
        spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac or spac.deal_status == 'COMPLETED':
            print(f"   ⚠️  {ticker} is completed or not found, skipping search")
            return None

        # 2. Get search strategy from past successes
        strategy = get_filing_search_strategy(field, ticker)
        print(f"   🔍 Searching for {field} using strategy: {strategy['primary_source']}")

        # 3. Search filings
        from utils.sec_filing_fetcher import SECFilingFetcher
        fetcher = SECFilingFetcher()

        filing_types = [strategy['primary_source']] + strategy['fallback_sources']

        for filing_type in filing_types:
            filings = fetcher.get_filings(
                ticker=ticker,
                filing_type=filing_type,
                limit=3
            )

            for filing in filings:
                # 4. Extract with AI + past learnings
                lessons = self.get_lessons_for_field(field)
                value = self._extract_field_with_lessons(
                    filing_content=filing['content'],
                    field=field,
                    lessons=lessons
                )

                if value is not None:
                    # 5. Log success for future learning
                    log_extraction_success(
                        field=field,
                        ticker=ticker,
                        filing_type=filing_type,
                        filing_section=strategy['section_hints'][0],
                        extraction_method='AI with learnings',
                        value_extracted=value
                    )
                    return value

        print(f"   ⚠️  Could not find {field} in recent filings")
        return None

    def _extract_field_with_lessons(
        self,
        filing_content: str,
        field: str,
        lessons: Dict
    ) -> Optional[Any]:
        """
        Extract field using AI enhanced with past learnings

        Includes past format warnings and success patterns in prompt
        """
        # Build enhanced prompt with learnings
        warnings = "\n".join([f"- {w}" for w in lessons['format_warnings']])
        patterns = "\n".join([f"- {p}" for p in lessons['success_patterns']])

        prompt = f"""Extract {field} from this SEC filing.

**CRITICAL - Learn from Past Errors**:
{warnings}

**Success Patterns**:
{patterns}

**Instructions**:
- Return NUMERIC values (not formatted strings)
- If not found, return null (not "N/A" or "TBD")
- Validate before returning

Filing excerpt:
{filing_content[:5000]}
"""

        # Call AI and sanitize response
        # ... (AI extraction logic)
```

---

### 3. Integration Pattern for Existing Agents

**Example**: `agents/deal_detector_agent.py`

**Before (Current)**:
```python
async def process(self, filing: Dict) -> Optional[Dict]:
    """Extract deal data from filing"""

    # Extract with AI
    deal_data = self._extract_deal_with_ai(filing_content)

    # Sanitize numeric fields (added after CHAC error)
    deal_data = sanitize_ai_response(deal_data, numeric_fields)

    # Update database
    self._update_database(ticker, deal_data)

    return deal_data
```

**After (With Learning)**:
```python
async def process(self, filing: Dict) -> Optional[Dict]:
    """Extract deal data from filing"""

    # Get past learnings for fields we're extracting
    lessons = {
        'earnout_shares': self.get_lessons_for_field('earnout_shares'),
        'pipe_size': self.get_lessons_for_field('pipe_size'),
        'target': self.get_lessons_for_field('target')
    }

    # Extract with AI + lessons
    deal_data = self._extract_deal_with_ai(filing_content, lessons)

    # Sanitize numeric fields
    deal_data = sanitize_ai_response(deal_data, numeric_fields)

    # Check for missing critical fields
    db = SessionLocal()
    try:
        if not deal_data.get('target'):
            print(f"   ⚠️  Target not found in filing, searching other sources...")
            deal_data['target'] = self.search_for_missing_data(
                ticker=filing['ticker'],
                field='target',
                db_session=db
            )

        # Update database
        self._update_database(ticker, deal_data)

        # Log successful extractions for learning
        for field, value in deal_data.items():
            if value is not None:
                log_extraction_success(
                    field=field,
                    ticker=filing['ticker'],
                    filing_type=filing['type'],
                    filing_section='Main document',
                    extraction_method='AI with learnings',
                    value_extracted=value
                )
    finally:
        db.close()

    return deal_data

def _extract_deal_with_ai(self, content: str, lessons: Dict) -> Dict:
    """Extract deal data with AI enhanced by past learnings"""

    # Build warnings section from all field lessons
    all_warnings = []
    for field, field_lessons in lessons.items():
        all_warnings.extend(field_lessons['format_warnings'])

    warnings_text = "\n".join([f"- {w}" for w in all_warnings[:10]])  # Top 10

    prompt = f"""Extract deal announcement data from this 8-K filing.

**CRITICAL - Learn from Past Extraction Errors**:
{warnings_text}

**Target Company Validation** (from past errors):
- DO NOT extract sponsor entities (e.g., "Acquisition Sponsor LLC")
- DO NOT extract trustee companies (e.g., "Continental Stock Transfer")
- Extract the actual operating company being acquired

**Numeric Fields**:
- Return as NUMERIC values (not "1.1M", "$275M")
- If not found, return null (not "TBD")

Extract these fields:
- target (company name)
- deal_value (total transaction value in dollars)
- pipe_size (PIPE financing amount in dollars)
- earnout_shares (earnout share count)
- announced_date (deal announcement date YYYY-MM-DD)

Filing text:
{content[:10000]}
"""

    # ... AI extraction logic with this enhanced prompt
```

---

### 4. Learning Database Schema Updates

**No schema changes needed** - existing `data_quality_conversations` table supports this.

**New Issue Types to Log**:

| Type | Description | Example |
|------|-------------|---------|
| `extraction_success` | Field successfully extracted | Found trust_value in 10-Q Item 1 |
| `filing_search_success` | Missing data found via search | Searched 3 filings, found in 2nd 10-Q |
| `format_prevention` | Format error prevented by learning | AI almost returned "1.1M", caught by lessons |

**New Fields to Populate**:

```python
{
    'issue_type': 'extraction_success',
    'field': 'trust_value',
    'ticker': 'BLUW',
    'original_data': {
        'filing_type': '10-Q',
        'filing_section': 'Item 1 - Financial Statements',
        'extraction_method': 'AI with past learnings'
    },
    'final_fix': {
        'value': 10.05,
        'confidence': 'high',
        'source': '10-Q filed 2025-10-15'
    },
    'learning_notes': 'Successfully found trust_value in 10-Q Item 1. This is the 5th success for this field/source combination. Update filing_hints priority.'
}
```

---

## Implementation Phases

### Phase 1: Infrastructure (Week 1)
- [ ] Create `utils/extraction_learner.py`
- [ ] Add learning methods to `agents/base_agent.py`
- [ ] Create test cases for learning query functions
- [ ] Document usage patterns

### Phase 2: Pilot Integration (Week 2)
- [ ] Integrate learning into `deal_detector_agent.py`
- [ ] Add filing search for missing target names
- [ ] Test with 10 recent deals
- [ ] Measure accuracy improvement

### Phase 3: Rollout (Week 3-4)
- [ ] Integrate into `redemption_extractor.py`
- [ ] Integrate into `quarterly_report_extractor.py` (trust data)
- [ ] Integrate into `completion_monitor_agent.py`
- [ ] Monitor and measure impact

### Phase 4: Automation (Month 2)
- [ ] Auto-update prompts based on recurring errors
- [ ] Auto-prioritize filing sources by success rate
- [ ] Auto-generate extraction code for new fields
- [ ] Dashboard showing learning effectiveness

---

## Success Metrics

**Measure These**:

1. **Extraction Accuracy**
   - Baseline: Current success rate per field
   - Target: +30% improvement (matching Investigation Agent results)

2. **Missing Data Reduction**
   - Baseline: % of NULL values per field
   - Target: -50% for searchable fields

3. **Format Error Elimination**
   - Baseline: Format errors per week
   - Target: 0 (should be prevented by lessons)

4. **Time to Data Completeness**
   - Baseline: Days until missing data is backfilled
   - Target: Same day (proactive search finds it immediately)

**Example Before/After**:

| Metric | Before Learning | After Learning | Improvement |
|--------|----------------|----------------|-------------|
| Earnout extraction accuracy | 60% | 90% | +30% |
| Missing trust_value count | 25 SPACs | 5 SPACs | -80% |
| Format errors per week | 3-5 | 0 | -100% |
| Days to backfill missing data | 7-14 days | <1 day | -93% |

---

## Example Workflow

**Scenario**: Deal detector processes new 8-K for BLUW deal announcement

```
1. Agent starts processing filing
   ↓
2. Queries learning database:
   GET lessons for: target, deal_value, pipe_size, earnout_shares

3. Learning database returns:
   {
     'earnout_shares': {
       'format_warnings': [
         "AI returned '1.1M' (CHAC 2025-11-04) → Use sanitize_ai_response()"
       ],
       'filing_hints': [
         "Found in EX-2.1 Business Combination Agreement (8 successes)"
       ],
       'common_mistakes': [
         "Don't confuse sponsor earnout with target earnout"
       ]
     },
     'target': {
       'validation_rules': [
         "Reject if contains 'Sponsor', 'Trustee', 'LLC' alone"
       ],
       'success_patterns': [
         "Look for 'acquire', 'target company', 'operating business'"
       ]
     }
   }

4. Agent builds enhanced AI prompt with warnings:
   """
   Extract deal data.

   **PAST ERRORS TO AVOID**:
   - Earnout: AI returned '1.1M' instead of 1100000 (return numeric!)
   - Target: Don't extract sponsor entities

   **WHERE TO LOOK**:
   - Earnout: Check EX-2.1 Business Combination Agreement

   Extract: target, deal_value, pipe_size, earnout_shares
   """

5. AI extracts with improved accuracy
   {
     'target': 'TechCorp Inc.',  ✅ (not "BLUW Sponsor LLC")
     'earnout_shares': 1100000    ✅ (not "1.1M")
   }

6. Agent validates and updates database ✅

7. Agent logs success for future learning:
   log_extraction_success(
     field='earnout_shares',
     filing_section='EX-2.1',
     value=1100000
   )
   → This becomes filing_hint for next extraction
```

---

## Key Differences from Investigation Agent

| Aspect | Investigation Agent | Extraction Agent Learning |
|--------|---------------------|---------------------------|
| **When** | After anomaly detected | Before/during extraction |
| **Purpose** | Diagnose and fix errors | Prevent errors |
| **Learning Used** | Past investigation outcomes | Past extraction errors |
| **Query Focus** | "How did we solve similar anomalies?" | "What mistakes should I avoid?" |
| **Action** | Search filings to investigate | Search filings to extract |
| **Success Metric** | % anomalies diagnosed | % extractions accurate first try |

**Both are valuable** - Investigation Agent reacts to problems, Extraction Learning prevents them.

---

## Next Steps

1. **Review this design** - Get user approval
2. **Create utils/extraction_learner.py** - Core learning query module
3. **Modify agents/base_agent.py** - Add learning methods
4. **Pilot with deal_detector_agent.py** - Test with real data
5. **Measure and iterate** - Track accuracy improvements

---

## References

- **Investigation Agent**: `investigation_agent.py` (lines 661-796)
- **Learning Database**: `docs/LEARNING_DATABASE.md`
- **Current Agents**: `agents/deal_detector_agent.py`, `agents/redemption_extractor.py`
- **Number Parser**: `utils/number_parser.py` (format error prevention)
