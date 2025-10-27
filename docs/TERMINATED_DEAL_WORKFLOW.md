# Terminated Deal Workflow

## Overview

When a SPAC deal is terminated, we preserve all historical data for analysis while marking the SPAC as back to searching.

## Database Approach

### Status Transition
```
ANNOUNCED → TERMINATED (deal fell through, SPAC back to searching)
ANNOUNCED → COMPLETED (deal closed successfully)
ANNOUNCED → LIQUIDATED (SPAC dissolved without completing deal)
```

### Data Preservation

When marking a deal as TERMINATED, **PRESERVE** these fields:

**Core Deal Information:**
- `target` - Target company name (KEEP)
- `announced_date` - Original announcement date (KEEP)
- `deal_value` - Transaction size (KEEP)
- `expected_close` - Originally expected closing date (KEEP)
- `merger_termination_date` - Date deal was terminated (SET)
- `sector` - Target's industry (KEEP)
- `deal_filing_url` - Link to original 8-K (KEEP)

**Financial Terms:**
- `pipe_size`, `pipe_price`, `has_pipe` - PIPE financing details (KEEP)
- `sponsor_promote` - Sponsor economics (KEEP)
- `redemption_percentage` - Final redemption rate (KEEP)
- `redemption_amount` - Total dollars redeemed (KEEP)

**Analysis Fields:**
- `price_at_announcement` - Price when deal announced (KEEP)
- `premium` - Current premium (will naturally update as price moves)
- `shareholder_vote_date` - If vote occurred (KEEP)

### Fields to RESET

When SPAC returns to searching status:
- `deal_status_detail` → NULL (clear rumor status)
- `rumored_target` → NULL
- `rumor_confidence` → NULL
- `accelerated_polling_until` → NULL (stop fast polling)

### Fields to KEEP UPDATING

Even after termination, continue updating:
- `price`, `volume`, `price_change_24h` - Current trading data
- `trust_value`, `trust_cash` - Trust account status
- `deadline_date` - Liquidation deadline (may be extended)
- `days_to_deadline` - Time remaining

## Detection Methods

### 1. SEC 8-K Filing Detection

**Keywords to detect termination:**
- "terminated the business combination agreement"
- "termination of merger agreement"
- "mutual termination agreement"
- "agreement has been terminated"
- "withdrawal of merger"
- Item 1.02 (Termination of Material Agreement)

**Example 8-K Items:**
```
Item 1.02 Termination of a Material Definitive Agreement
Item 8.01 Other Events (may mention termination)
Item 9.01 Financial Statements (removal of target financials)
```

### 2. Manual Detection via News

Sources to monitor:
- Seeking Alpha articles
- SEC filings RSS
- SPAC-focused Twitter/Reddit
- Press releases on company IR pages

### 3. Orchestrator Agent Detection

The `DealDetectorAgent` should also detect terminations:

```python
# In deal_detector_agent.py
if 'termination' in filing_content.lower():
    if spac.deal_status == 'ANNOUNCED':
        # Validate it's about the current deal
        if spac.target.lower() in filing_content.lower():
            return {
                'action': 'TERMINATE_DEAL',
                'termination_date': filing_date,
                'reason': extract_termination_reason(filing_content)
            }
```

## SQL Update Pattern

### Terminate a Deal
```sql
UPDATE spacs
SET
    deal_status = 'TERMINATED',
    merger_termination_date = '2025-10-23',
    deal_status_detail = NULL,
    rumored_target = NULL,
    accelerated_polling_until = NULL
WHERE ticker = 'XXXX' AND deal_status = 'ANNOUNCED';

-- DO NOT clear: target, announced_date, deal_value, sector, pipe_size, etc.
```

### Return to Searching (if not liquidating)
```sql
-- If SPAC gets extension and looks for new target
UPDATE spacs
SET
    deal_status = 'SEARCHING',
    -- Keep terminated deal history
    target = target || ' (TERMINATED)',  -- Append marker
    merger_termination_date = '2025-10-23'
WHERE ticker = 'XXXX';
```

## Analytics Value

Terminated deals provide valuable insights:

### Deal Risk Analysis
- **Sector patterns**: Which industries have high termination rates?
- **Sponsor quality**: Do certain sponsors have more failures?
- **Timing**: How long after announcement do deals typically fail?
- **Redemptions**: Did high redemptions kill the deal?

### Premium Analysis
- **Pre-termination premium**: How high was premium before termination?
- **Post-termination drop**: How much does price fall after termination?
- **Recovery time**: How long to return to NAV?

### Success Predictor Model
```python
# Example: Predict deal completion likelihood
features = [
    'premium',
    'redemption_percentage',
    'pipe_size',
    'sponsor_quality_score',
    'days_since_announcement',
    'sector'
]

# Training data includes:
# - 17 COMPLETED deals (label=1)
# - 1+ TERMINATED deals (label=0)
```

## Example: SVII Terminated Deal

```sql
SELECT
    ticker,
    deal_status,
    target,
    announced_date,
    deal_value,
    merger_termination_date,
    redemption_percentage
FROM spacs
WHERE ticker = 'SVII';

-- Result:
-- SVII | TERMINATED | Eagle Energy Metals Corp | 2025-07-31 | $312M | [date] | [%]
```

**Value of this data:**
- Shows SVII tried to merge with Eagle Energy Metals
- Deal announced July 31, 2025
- $312M transaction size
- Can analyze: What went wrong? Regulatory issues? Shareholder vote failed? Financing fell through?

## Data Quality Validation

### Check for Inconsistent Terminated Deals
```sql
-- Find deals marked SEARCHING but have termination date
SELECT ticker, deal_status, target, merger_termination_date
FROM spacs
WHERE merger_termination_date IS NOT NULL
  AND deal_status NOT IN ('TERMINATED', 'SEARCHING');

-- Find deals marked TERMINATED but missing termination date
SELECT ticker, deal_status, target, merger_termination_date
FROM spacs
WHERE deal_status = 'TERMINATED'
  AND merger_termination_date IS NULL;
```

### Data Validator Agent Check
```python
# In data_validator_agent.py
def validate_termination_consistency(spac):
    issues = []

    # Has termination date but not marked terminated
    if spac.merger_termination_date and spac.deal_status not in ['TERMINATED', 'SEARCHING']:
        issues.append({
            'severity': 'HIGH',
            'field': 'deal_status',
            'issue': f'Has merger_termination_date={spac.merger_termination_date} but deal_status={spac.deal_status}',
            'suggested_fix': 'Set deal_status = TERMINATED'
        })

    # Marked terminated but no termination date
    if spac.deal_status == 'TERMINATED' and not spac.merger_termination_date:
        issues.append({
            'severity': 'MEDIUM',
            'field': 'merger_termination_date',
            'issue': 'Deal status is TERMINATED but merger_termination_date is NULL',
            'suggested_fix': 'Set termination date from 8-K filing'
        })

    # Terminated but missing key deal data
    if spac.deal_status == 'TERMINATED':
        if not spac.target:
            issues.append({
                'severity': 'CRITICAL',
                'field': 'target',
                'issue': 'Terminated deal missing target company name',
                'suggested_fix': 'Extract from historical 8-K filings'
            })
        if not spac.announced_date:
            issues.append({
                'severity': 'HIGH',
                'field': 'announced_date',
                'issue': 'Terminated deal missing announcement date',
                'suggested_fix': 'Extract from historical 8-K filings'
            })

    return issues
```

## Common Termination Reasons

Track these in a future `termination_reason` field:

1. **Failed Shareholder Vote** - Majority voted against deal
2. **High Redemptions** - Too many shareholders redeemed, deal underfunded
3. **Regulatory Issues** - Government blocked transaction (antitrust, CFIUS, etc.)
4. **Financing Fell Through** - PIPE investors or debt financing pulled out
5. **Target Withdrew** - Target company terminated agreement
6. **Mutual Termination** - Both parties agreed to end deal
7. **Missed Deadline** - Failed to close by outside date
8. **Material Adverse Change** - Target's business deteriorated
9. **Better Offer** - Target received superior proposal
10. **Sponsor Withdrew** - SPAC sponsor terminated deal

## References

- **SVII Example**: First terminated deal in database (Eagle Energy Metals)
- **Deal Status Types**: SEARCHING, ANNOUNCED, TERMINATED, COMPLETED, LIQUIDATED
- **Key Table**: `spacs` (main table)
- **Related Columns**: 102 total columns tracking full SPAC lifecycle
