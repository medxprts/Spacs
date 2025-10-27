# Founder Shares & Warrants Implementation Plan

## Simplified Scope (Pre-Deal SPACs Only)

Since we don't care about post-deal completion SPACs, we can ignore PIPE and focus on:

1. ✅ **Founder shares** (from S-1)
2. ✅ **Warrant terms** (from S-1)
3. ❌ ~~PIPE~~ (only matters post-deal)
4. ❌ ~~Earnout shares~~ (only matters post-deal)

---

## What We Need to Extract

### From S-1 Registration Statement:

| Field | Location | Example Value | Database Column |
|-------|----------|---------------|-----------------|
| **Founder shares** | Capitalization section | 5,750,000 | `founder_shares` |
| **Warrant ratio** | Unit structure | "1/3" or "0.333" | `warrant_ratio` |
| **Warrant exercise price** | Warrant terms | $11.50 | Add: `warrant_exercise_price` |
| **Warrant expiration** | Warrant terms | "5 years from closing" | Add: `warrant_expiration_years` |

---

## Market Cap Formula

### Basic (Current - Wrong):
```python
market_cap = price × shares_outstanding
```

### With Founder Shares (Better):
```python
market_cap = price × (shares_outstanding + founder_shares) / 1_000_000
```

### Fully Diluted (Best):
```python
def calculate_fully_diluted_mcap(spac):
    base_shares = spac.shares_outstanding + (spac.founder_shares or 0)

    # Add warrant dilution if in-the-money
    if spac.warrant_ratio and spac.warrant_exercise_price:
        if spac.price > spac.warrant_exercise_price:
            warrants_outstanding = spac.shares_outstanding * spac.warrant_ratio
            # Treasury method
            warrant_dilution = (warrants_outstanding * (spac.price - spac.warrant_exercise_price)) / spac.price
            base_shares += warrant_dilution

    return spac.price * base_shares / 1_000_000
```

---

## Implementation Steps

### Step 1: Add Database Column
```python
# In database.py, add new column:
warrant_exercise_price = Column(Float)  # Typically $11.50
```

**Run migration**:
```bash
psql spac_db -c "ALTER TABLE spacs ADD COLUMN IF NOT EXISTS warrant_exercise_price FLOAT;"
```

### Step 2: Add Extraction Methods to sec_data_scraper.py

```python
def extract_founder_shares(self, s1_html: str) -> Dict:
    """
    Extract founder share data from S-1 registration statement

    Returns:
        {
            'founder_shares': 5750000,
            'founder_percentage': 0.20,
            'purchase_price': 0.004,
            'confidence': 0.95
        }
    """
    # Extract relevant section (avoid full 300-page document)
    section = self._extract_section(s1_html, [
        "Capitalization",
        "Principal Stockholders",
        "Description of Securities"
    ])

    if not section:
        return {'founder_shares': None, 'confidence': 0.0}

    # Try regex patterns first (free, fast, 70% success rate)
    patterns = [
        r'([0-9,]+)\s+(?:founder|Class B)\s+shares',
        r'Sponsor\s+purchased\s+([0-9,]+)\s+shares',
        r'([0-9,]+)\s+shares.*issued.*Sponsor',
        r'aggregate\s+of\s+([0-9,]+)\s+(?:founder|Class B)',
    ]

    for pattern in patterns:
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            founder_shares = int(match.group(1).replace(',', ''))
            return {
                'founder_shares': founder_shares,
                'confidence': 0.90,
                'extraction_method': 'regex'
            }

    # Fallback to AI extraction (costs $0.01-0.02)
    prompt = f"""
    From this S-1 registration statement excerpt, extract the founder share information.

    Look for:
    - "founder shares" or "Class B shares"
    - Number of shares purchased by Sponsor
    - Typical language: "The Sponsor purchased X shares for $25,000"

    Return JSON with:
    {{
        "founder_shares": <number>,
        "purchase_price_per_share": <price>,
        "notes": "<any relevant context>"
    }}

    If not found, return {{"founder_shares": null}}
    """

    try:
        response = self.ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a financial document parser. Extract exact numbers."},
                {"role": "user", "content": prompt + "\n\nDocument excerpt:\n" + section[:5000]}
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        return {
            'founder_shares': result.get('founder_shares'),
            'confidence': 0.85 if result.get('founder_shares') else 0.0,
            'extraction_method': 'ai',
            'notes': result.get('notes')
        }
    except Exception as e:
        print(f"AI extraction failed: {e}")
        return {'founder_shares': None, 'confidence': 0.0}


def extract_warrant_terms(self, s1_html: str) -> Dict:
    """
    Extract warrant structure from S-1

    Returns:
        {
            'warrant_ratio': 0.333,  # 1/3 warrant per share
            'exercise_price': 11.50,
            'expiration_years': 5,
            'confidence': 0.95
        }
    """
    section = self._extract_section(s1_html, [
        "Description of Warrants",
        "Description of Securities",
        "Units"
    ])

    if not section:
        return {'warrant_ratio': None, 'confidence': 0.0}

    result = {
        'warrant_ratio': None,
        'exercise_price': None,
        'expiration_years': None,
        'confidence': 0.0
    }

    # Extract warrant ratio from unit structure
    # Pattern: "one share and one-third of one warrant" or "1 share and 1/3 warrant"
    ratio_patterns = [
        r'one[- ]third',  # → 0.333
        r'1/3',           # → 0.333
        r'one[- ]half',   # → 0.5
        r'1/2',           # → 0.5
        r'one[- ]fourth', # → 0.25
        r'1/4',           # → 0.25
        r'one\s+warrant', # → 1.0
    ]

    ratio_map = {
        'one-third': 0.333, '1/3': 0.333,
        'one-half': 0.5, '1/2': 0.5,
        'one-fourth': 0.25, '1/4': 0.25,
        'one warrant': 1.0
    }

    for pattern in ratio_patterns:
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            matched_text = match.group(0).lower().replace(' ', '-')
            for key, value in ratio_map.items():
                if key in matched_text:
                    result['warrant_ratio'] = value
                    result['confidence'] = 0.90
                    break
            if result['warrant_ratio']:
                break

    # Extract exercise price
    # Pattern: "$11.50 per share" or "exercise price of $11.50"
    price_match = re.search(r'\$([0-9]+\.?[0-9]*)\s+per\s+(?:whole\s+)?(?:public\s+)?warrant', section, re.IGNORECASE)
    if not price_match:
        price_match = re.search(r'exercise\s+price\s+of\s+\$([0-9]+\.?[0-9]*)', section, re.IGNORECASE)

    if price_match:
        result['exercise_price'] = float(price_match.group(1))
        result['confidence'] = max(result['confidence'], 0.85)

    # Extract expiration
    # Pattern: "five years" or "5 years"
    exp_match = re.search(r'(five|5)\s+years?\s+(?:from|after)', section, re.IGNORECASE)
    if exp_match:
        result['expiration_years'] = 5

    # If regex failed, use AI as fallback
    if result['warrant_ratio'] is None or result['exercise_price'] is None:
        prompt = f"""
        From this warrant description, extract:
        1. Warrant ratio (how many warrants per share in the unit?)
        2. Exercise price (price to exercise warrant, typically $11.50)
        3. Expiration period (typically 5 years)

        Return JSON:
        {{
            "warrant_ratio": <decimal like 0.333 for 1/3>,
            "exercise_price": <price like 11.50>,
            "expiration_years": <number like 5>
        }}
        """

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "Extract exact financial terms. Be precise with fractions."},
                    {"role": "user", "content": prompt + "\n\n" + section[:3000]}
                ],
                response_format={"type": "json_object"}
            )

            ai_result = json.loads(response.choices[0].message.content)
            if ai_result.get('warrant_ratio'):
                result.update(ai_result)
                result['confidence'] = 0.80
                result['extraction_method'] = 'ai'
        except Exception as e:
            print(f"AI warrant extraction failed: {e}")

    return result


def _extract_section(self, html: str, section_names: List[str]) -> str:
    """
    Extract specific section from S-1 HTML

    Reduces LLM input from 300 pages → 5-10 pages
    Reduces cost by 95%
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text()

    # Find section by heading
    for section_name in section_names:
        # Look for section heading
        pattern = rf'(?:^|\n)\s*{re.escape(section_name)}\s*(?:\n|$)'
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)

        if match:
            start_pos = match.start()
            # Get next 20,000 characters (roughly 5-10 pages)
            section_text = text[start_pos:start_pos + 20000]
            return section_text

    return ""
```

### Step 3: Integrate into enrich_spac_from_sec()

```python
def enrich_spac_from_sec(self, ticker: str):
    """Enhanced version with founder share extraction"""

    # ... existing code to get S-1 ...

    if s1_filing:
        print(f"  Found S-1, extracting founder shares and warrant terms...")

        # Extract founder shares
        founder_data = self.extract_founder_shares(s1_html)
        if founder_data['founder_shares']:
            spac.founder_shares = founder_data['founder_shares']
            print(f"    ✓ Founder shares: {founder_data['founder_shares']:,} ({founder_data['confidence']:.0%} confidence)")

            # Log to data quality
            quality_logger.log_extraction_success(
                ticker=ticker,
                field='founder_shares',
                value=founder_data['founder_shares'],
                source='S-1',
                extraction_method=founder_data.get('extraction_method', 'regex'),
                confidence=founder_data['confidence']
            )
        else:
            quality_logger.log_missing_field(
                ticker=ticker,
                field='founder_shares',
                source='S-1',
                reason='Not found in Capitalization section',
                severity='WARNING'
            )

        # Extract warrant terms
        warrant_data = self.extract_warrant_terms(s1_html)
        if warrant_data['warrant_ratio']:
            spac.warrant_ratio = str(warrant_data['warrant_ratio'])  # Store as string "0.333"
            spac.warrant_exercise_price = warrant_data['exercise_price']
            print(f"    ✓ Warrant ratio: {warrant_data['warrant_ratio']} ({warrant_data['confidence']:.0%} confidence)")
            print(f"    ✓ Exercise price: ${warrant_data['exercise_price']}")

        db.commit()
```

### Step 4: Update price_updater.py

```python
def update_prices(self, ticker: str) -> Dict:
    """Enhanced version with fully diluted market cap"""

    # ... existing price fetching code ...

    # Calculate fully diluted market cap
    market_cap = None
    if spac.shares_outstanding:
        base_shares = spac.shares_outstanding

        # Add founder shares
        if spac.founder_shares:
            base_shares += spac.founder_shares
            print(f"  + Founder shares: {spac.founder_shares:,}")
        else:
            # Fallback to 25% assumption
            founder_estimate = spac.shares_outstanding * 0.25
            base_shares += founder_estimate
            print(f"  + Founder shares (estimated 25%): {founder_estimate:,.0f}")

        # Add warrant dilution if in-the-money
        if spac.warrant_ratio and spac.warrant_exercise_price:
            warrant_ratio = float(spac.warrant_ratio)
            warrants_out = spac.shares_outstanding * warrant_ratio

            if price_data['price'] > spac.warrant_exercise_price:
                # Treasury method
                warrant_dilution = (warrants_out * (price_data['price'] - spac.warrant_exercise_price)) / price_data['price']
                base_shares += warrant_dilution
                print(f"  + Warrant dilution (ITM): {warrant_dilution:,.0f}")
            else:
                print(f"  - Warrants OTM (${price_data['price']:.2f} < ${spac.warrant_exercise_price:.2f})")

        market_cap = round((price_data['price'] * base_shares) / 1_000_000, 2)

    update_data['market_cap'] = market_cap
```

### Step 5: Update data_validator.py

```python
# Rule 20: market_cap calculation (with founder shares + warrant dilution)
if spac.price and spac.shares_outstanding:
    base_shares = spac.shares_outstanding

    # Add founder shares
    if spac.founder_shares:
        base_shares += spac.founder_shares
    else:
        # Fallback to 25% assumption
        base_shares += spac.shares_outstanding * 0.25

    # Add warrant dilution
    if spac.warrant_ratio and spac.warrant_exercise_price:
        warrant_ratio = float(spac.warrant_ratio)
        if spac.price > spac.warrant_exercise_price:
            warrants_out = spac.shares_outstanding * warrant_ratio
            warrant_dilution = (warrants_out * (spac.price - spac.warrant_exercise_price)) / spac.price
            base_shares += warrant_dilution

    calculated_mcap = (float(spac.price) * base_shares) / 1_000_000

    if spac.market_cap is not None:
        diff_pct = abs(float(spac.market_cap) - calculated_mcap) / calculated_mcap * 100
        if diff_pct > 1.0:
            issues.append(ValidationIssue(
                rule_number=20,
                rule_name="market_cap_calculation",
                severity="ERROR",
                ticker=spac.ticker,
                field="market_cap",
                current_value=f"${spac.market_cap:.2f}M",
                expected_value=f"${calculated_mcap:.2f}M",
                message=f"Market cap should include founder shares + warrant dilution",
                auto_fixable=True
            ))
```

---

## Testing Plan

### Step 1: Test on 3 SPACs
```bash
# Pick 3 SPACs with different structures
python3 sec_data_scraper.py --ticker MLAC  # Standard 1/3 warrant
python3 sec_data_scraper.py --ticker HCMA  # Check if different ratio
python3 sec_data_scraper.py --ticker BCAR  # Verify consistency
```

### Step 2: Verify Extraction
```sql
SELECT
    ticker,
    shares_outstanding,
    founder_shares,
    warrant_ratio,
    warrant_exercise_price,
    price,
    market_cap
FROM spacs
WHERE ticker IN ('MLAC', 'HCMA', 'BCAR');
```

**Expected**:
```
MLAC: 23M shares, ~5.75M founder, 0.333 ratio, $11.50 exercise
HCMA: 25.3M shares, ~6.3M founder, 0.333 ratio, $11.50 exercise
BCAR: 25M shares, ~6.25M founder, 0.333 ratio, $11.50 exercise
```

### Step 3: Run on All SPACs
```bash
python3 sec_data_scraper.py  # Run full enrichment
```

### Step 4: Check Capture Rate
```sql
SELECT
    COUNT(*) as total_spacs,
    COUNT(founder_shares) as has_founder_shares,
    COUNT(warrant_ratio) as has_warrant_ratio,
    ROUND(COUNT(founder_shares)::numeric / COUNT(*) * 100, 1) as founder_capture_pct,
    ROUND(COUNT(warrant_ratio)::numeric / COUNT(*) * 100, 1) as warrant_capture_pct
FROM spacs;
```

**Target**: 90%+ capture rate

### Step 5: Validate Market Cap
```bash
python3 data_validator.py --validate-all
# Should see much fewer market_cap_calculation errors
```

---

## Cost & Time Estimates

### Extraction Phase:
- **Regex success rate**: 70% (free, instant)
- **AI fallback**: 30% × 186 SPACs = ~56 SPACs
- **AI cost**: 56 × $0.015 = **$0.84 total**
- **Time**: 5-10 seconds per SPAC = **15-30 minutes**

### Validation:
- **Free** (just recalculates with new formula)

---

## Expected Improvements

### Before (Current):
```
market_cap = price × shares_outstanding
142 SPACs have incorrect market_cap (missing founder shares)
```

### After:
```
market_cap = price × (shares_outstanding + founder_shares + warrant_dilution)
Expected: 5-10 SPACs with market_cap errors (missing data only)
```

### Example (MLAC at current price $11.07):
- **Current (wrong)**: $254.61M
- **With founder shares**: $318.26M (+25%)
- **With warrant dilution**: $318.26M (warrants OTM, no dilution)

### Example (MLAC if price rises to $15):
- **With founder shares**: $431.25M
- **With warrant dilution**: $458.08M (+6.2% from warrants)

---

## Summary

**Scope**: Founder shares + warrant dilution only (no PIPE/earnout)

**Implementation**: 3 new methods in sec_data_scraper.py + 1 new database column

**Cost**: $0.84 for all 186 SPACs

**Time**: 15-30 minutes

**Expected capture rate**: 90%+

**Ready to implement?**
