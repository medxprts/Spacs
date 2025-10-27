# Redemption Trust Cash Calculation Pattern

## Overview

When shareholders vote on extensions or business combinations, redemptions can occur. The correct way to calculate post-redemption trust cash is:

**Post-redemption trust = Pre-vote trust - (Redeemed shares × NAV) + Extension deposits**

## Real-World Example: DTSQ Extension Vote (Oct 2025)

### Data Sources

**DEF14A (filed before vote - Sept 17, 2025)**:
- Pre-vote trust cash: $72,452,618
- NAV per share: $10.50
- Total shares: 6,900,000
- Quote: "As of September 17, 2025, there was approximately $72,452,618 in the trust account, representing a per share pro rata amount of approximately $10.50."

**8-K (filed after vote - Oct 24, 2025)**:
- Shares redeemed: 5,297,491 (59.5%)
- Extension deposit by sponsor: $75,000
- Remaining shares: 1,602,509

### Calculation

```python
pre_vote_trust = 72_452_618  # From DEF14A
nav_per_share = 10.50         # From DEF14A
shares_redeemed = 5_297_491   # From 8-K
extension_deposit = 75_000    # From 8-K

cash_paid_out = shares_redeemed * nav_per_share
# = 5,297,491 × $10.50
# = $55,623,655.50

post_redemption_trust = pre_vote_trust - cash_paid_out + extension_deposit
# = $72,452,618 - $55,623,655.50 + $75,000
# = $16,903,962.50

remaining_shares = 1_602_509
new_nav = post_redemption_trust / remaining_shares
# = $16,903,962.50 / 1,602,509
# = $10.55 per share
```

### Why This Matters

**WRONG approach** (what our system initially did):
- Only processed 8-K, which disclosed redemption count
- Updated shares_outstanding: 6.9M → 1.6M ✓
- Did NOT update trust_cash (stayed at $71.9M) ✗
- Result: trust_value = $71.9M / 1.6M = **$44.89** (WRONG!)

**CORRECT approach**:
- Parse DEF14A for pre-vote trust and NAV
- Parse 8-K for redemption count and extension deposits
- Calculate: trust_cash = $72.45M - $55.6M + $75K = **$16.9M**
- Result: trust_value = $16.9M / 1.6M = **$10.55** (CORRECT!)

## Implementation Requirements

### 1. DEF14A Parser Agent

**Filing Type**: DEF 14A (Definitive Proxy Statement)

**Trigger**: Filed before shareholder votes (typically 30-60 days before vote)

**Data to Extract**:
- Pre-vote trust cash balance (look for "trust account" + dollar amount)
- NAV per share (look for "per share" or "pro rata")
- Record date
- Shareholder vote date
- What's being voted on (extension, business combination, liquidation)

**Keywords to search**:
- "trust account"
- "per share pro rata amount"
- "approximately $X in the trust account"
- "record date"
- "shareholder meeting"

**Database fields to populate**:
- `pre_redemption_trust_cash` (new field needed)
- `pre_redemption_nav` (new field needed)
- `shareholder_vote_date`
- `record_date`

### 2. Post-Vote 8-K Parser Enhancement

**Filing Type**: 8-K Item 5.07 (Submission of Matters to Vote)

**Trigger**: Filed 0-4 days after shareholder vote

**Current extraction** (already working):
- Shares redeemed ✓
- Redemption percentage ✓

**Additional extraction needed**:
- Extension deposits by sponsor
- Trust account deposits (look for "deposited $X into trust")
- Cash withdrawn for expenses

**Keywords to search**:
- "deposited into trust"
- "sponsor deposit"
- "extension payment"
- "trust account deposit"

### 3. Calculation Logic

```python
def calculate_post_redemption_trust(spac: SPAC, db_session: Session):
    """
    Calculate post-redemption trust cash after shareholder vote

    Requires:
    - pre_redemption_trust_cash (from DEF14A)
    - pre_redemption_nav (from DEF14A)
    - shares_redeemed (from 8-K)
    - extension_deposits (from 8-K)
    """

    if not spac.pre_redemption_trust_cash or not spac.pre_redemption_nav:
        raise ValueError("Missing DEF14A data - cannot calculate post-redemption trust")

    # Calculate cash paid to redeemers
    cash_paid_out = spac.shares_redeemed * spac.pre_redemption_nav

    # Calculate remaining trust
    post_redemption_trust = (
        spac.pre_redemption_trust_cash
        - cash_paid_out
        + (spac.extension_deposit or 0)
        - (spac.expense_withdrawals or 0)
    )

    # Update trust_cash
    update_trust_cash(
        db_session=db_session,
        ticker=spac.ticker,
        new_value=post_redemption_trust,
        source='8-K',
        filing_date=spac.vote_filing_date,
        reason=f'Post-redemption calculation: ${spac.pre_redemption_trust_cash:,.0f} - {spac.shares_redeemed:,} shares @ ${spac.pre_redemption_nav} + ${spac.extension_deposit or 0:,} deposit'
    )

    # Recalculate NAV
    if spac.shares_outstanding > 0:
        spac.trust_value = round(post_redemption_trust / spac.shares_outstanding, 2)

    # Recalculate premium
    recalculate_premium(db_session, spac.ticker)

    return post_redemption_trust
```

### 4. Validation Rule

Add to `data_validator_agent.py`:

```python
def validate_redemption_trust_calculation(spac: SPAC) -> List[ValidationIssue]:
    """Validate trust cash decreased after redemptions"""
    issues = []

    # Check if shares_outstanding decreased (redemptions occurred)
    history = get_trust_account_history(db, spac.ticker, 'shares_outstanding')

    for change in history:
        if change.new_value < change.old_value:
            # Redemptions occurred - trust_cash should also decrease
            trust_history = get_trust_account_history(
                db, spac.ticker, 'trust_cash',
                changed_at=change.changed_at
            )

            if not trust_history or trust_history[0].new_value >= trust_history[0].old_value:
                issues.append({
                    'severity': 'CRITICAL',
                    'field': 'trust_cash',
                    'issue': f'Shares decreased by {change.old_value - change.new_value:,.0f} due to redemptions, but trust_cash did not decrease',
                    'date': change.changed_at,
                    'suggested_fix': 'Parse DEF14A for pre-redemption trust, calculate cash paid out, update trust_cash'
                })

    return issues
```

## Vote Types That Trigger Redemptions

### 1. Extension Votes
- **Purpose**: Extend business combination deadline
- **Redemption right**: Shareholders can redeem at NAV
- **Sponsor deposit**: Often required ($0.03-$0.10 per share per month)
- **Example**: DTSQ extended to Oct 2026, 59.5% redeemed, $75K deposit

### 2. Business Combination Votes
- **Purpose**: Approve merger/SPAC deal
- **Redemption right**: Shareholders can redeem even if voting "yes"
- **Sponsor deposit**: None typically
- **Example**: SRSA merger with Swiftly, 90% redemptions

### 3. Charter Amendment Votes
- **Purpose**: Change SPAC charter (e.g., remove warrant adjustment)
- **Redemption right**: Often included
- **Sponsor deposit**: Varies

### 4. Liquidation Votes
- **Purpose**: Dissolve SPAC, return cash to shareholders
- **Redemption right**: N/A (all shares redeemed)
- **Sponsor deposit**: None

## Database Schema Changes Needed

```sql
-- Add new columns to spacs table
ALTER TABLE spacs ADD COLUMN pre_redemption_trust_cash NUMERIC;
ALTER TABLE spacs ADD COLUMN pre_redemption_nav NUMERIC(10, 2);
ALTER TABLE spacs ADD COLUMN extension_deposit NUMERIC;
ALTER TABLE spacs ADD COLUMN expense_withdrawals NUMERIC;
ALTER TABLE spacs ADD COLUMN def14a_filing_date DATE;
ALTER TABLE spacs ADD COLUMN def14a_url TEXT;

-- Add comments
COMMENT ON COLUMN spacs.pre_redemption_trust_cash IS 'Trust cash before redemption vote (from DEF14A)';
COMMENT ON COLUMN spacs.pre_redemption_nav IS 'NAV per share before redemption (from DEF14A)';
COMMENT ON COLUMN spacs.extension_deposit IS 'Sponsor deposit for extension (from 8-K)';
COMMENT ON COLUMN spacs.expense_withdrawals IS 'Cash withdrawn from trust for expenses';
```

## Implementation Checklist

- [ ] Create `def14a_parser_agent.py`
  - [ ] Extract pre-vote trust cash
  - [ ] Extract NAV per share
  - [ ] Extract shareholder vote date
  - [ ] Extract record date

- [ ] Enhance `redemption_extractor_agent.py`
  - [ ] Extract extension deposits
  - [ ] Extract expense withdrawals
  - [ ] Call `calculate_post_redemption_trust()`

- [ ] Add database migrations
  - [ ] Add new columns listed above

- [ ] Update `data_validator_agent.py`
  - [ ] Add redemption trust validation rule

- [ ] Update orchestrator routing
  - [ ] Route DEF14A filings to `def14a_parser_agent`

- [ ] Test on historical redemptions
  - [ ] DTSQ (Oct 2025) - 59.5% redemption
  - [ ] SRSA (if applicable)
  - [ ] Any other recent extension votes

## Key Learnings

1. **Trust cash ≠ constant**: Trust grows with interest, shrinks with redemptions and expenses
2. **NAV can change**: $10.00 at IPO, but can be $10.50+ after interest accrual
3. **DEF14A is authoritative**: Most recent pre-vote trust balance
4. **8-K discloses transactions**: Redemptions, deposits, withdrawals
5. **Always verify sources**: Don't assume trust cash from IPO proceeds

## References

- **DTSQ Case Study**: `fix_dtsq_trust_cash_redemption.py`
- **Trust Account Tracker**: `utils/trust_account_tracker.py`
- **Data Validator**: `agents/data_validator_agent.py`
- **Orchestrator Routing**: `agent_orchestrator.py`
