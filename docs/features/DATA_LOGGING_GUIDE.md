# Data Quality Logging Guide

## Overview

All data quality changes should be automatically logged to `/home/ubuntu/spac-research/logs/data_validation.jsonl` for future AI agent training.

## Quick Start

Add these 2 lines to any script that modifies SPAC data:

```python
from auto_log_data_changes import log_data_change, init_logger

init_logger()  # Call once at start of script
```

Then whenever you change data:

```python
log_data_change(
    ticker='APAD',
    field='ipo_proceeds',
    old_value='$200000000M',
    new_value='$200M',
    reason='Fixed formatting - AI returned dollars instead of millions',
    source='sec_data_scraper'  # Optional - auto-detected from script name
)
```

## Common Patterns

### 1. Filling Missing Data

```python
from auto_log_data_changes import log_missing_data

log_missing_data('CEP', 'ipo_date', '2024-03-15', source='sec_edgar')
```

### 2. Correcting Incorrect Values

```python
from auto_log_data_changes import log_incorrect_value

log_incorrect_value(
    ticker='GSRT',
    field='deadline_date',
    old_value='2024-01-01',
    new_value='2025-06-15',
    reason='Deadline was before IPO date - recalculated from S-1',
    source='deadline_extension_monitor'
)
```

### 3. Handling Delisted Tickers

```python
from auto_log_data_changes import log_delisted

log_delisted(
    ticker='AIIA',
    last_trade_date='2024-12-01',
    sec_last_filing='2024-11-15',
    source='price_updater'
)
```

### 4. Batch Changes (Context Manager)

```python
from auto_log_data_changes import DataChangeSession

with DataChangeSession(source='deal_announcement_scraper') as session:
    for spac in announced_spacs:
        if spac.target != new_target:
            session.log(spac.ticker, 'target', spac.target, new_target,
                       'Updated from 8-K filing')
```

## Scripts That Should Use Logging

### ✅ Already Updated
- (none yet)

### 🔄 Need to Add Logging

1. **sec_data_scraper.py**
   - Log all IPO data enrichments
   - Log trust value calculations
   - Log deadline corrections

2. **price_updater.py**
   - Log delisted tickers
   - Log price updates that trigger premium recalculations

3. **deal_announcement_scraper.py**
   - Log deal data extractions from 8-Ks
   - Log target company corrections

4. **s4_scraper.py**
   - Log S-4 data enrichments
   - Log deal value corrections

5. **proxy_scraper.py**
   - Log shareholder vote data
   - Log redemption data

6. **redemption_scraper.py**
   - Log redemption results

7. **deal_closing_detector.py**
   - Log deal closings
   - Log ticker changes

8. **deadline_extension_monitor.py**
   - Log deadline extensions

9. **market_snapshot.py**
   - Log if outliers are detected and excluded

10. **Manual fixes** (database.py, manual scripts)
    - Log all manual corrections

## Viewing Logs

### Recent Issues
```bash
python3 data_validation_log.py --recent 20
```

### Statistics
```bash
python3 data_validation_log.py --stats
```

### Export Training Data
```bash
python3 data_validation_log.py --export training_data.json
```

## Log Format

Each log entry is a JSON object with:

```json
{
  "timestamp": "2025-10-07T14:30:00",
  "issue_type": "incorrect_value",
  "ticker": "APAD",
  "field": "ipo_proceeds",
  "old_value": "$200000000M",
  "new_value": "$200M",
  "reason": "Fixed formatting - divided by 1M",
  "validation_method": "sec_data_scraper",
  "confidence": 1.0,
  "metadata": {}
}
```

## Issue Types

- `missing_data` - Field was null, now filled
- `incorrect_value` - Field had wrong value, now corrected
- `wrong_ticker` - Ticker itself was wrong
- `delisted` - Ticker no longer trades
- `duplicate` - Duplicate record removed
- `update` - General update (use sparingly)

## Benefits for AI Training

This log will be used to train an AI agent to:

1. **Detect patterns** - Learn what kinds of data errors occur frequently
2. **Auto-fix issues** - Recognize and correct similar issues automatically
3. **Validate data** - Check new data against learned patterns
4. **Alert on anomalies** - Flag suspicious data for human review

## Example: Training Data Export

```json
{
  "input": {
    "ticker": "APAD",
    "field": "ipo_proceeds",
    "value": "$200000000M"
  },
  "expected_output": {
    "issue_detected": true,
    "issue_type": "incorrect_value",
    "corrected_value": "$200M",
    "confidence": 1.0
  },
  "explanation": "Fixed formatting - AI returned dollars instead of millions",
  "validation_method": "sec_data_scraper"
}
```

## Implementation Checklist

For each script that modifies data:

- [ ] Import `auto_log_data_changes`
- [ ] Call `init_logger()` at start
- [ ] Add `log_data_change()` calls before database commits
- [ ] Test that logs are being written
- [ ] Add script to daily automation if not already included

## Future: Automated Data Quality Agent

Once we have sufficient training data (500+ examples), we can:

1. Fine-tune a small language model on the logs
2. Build an agent that runs before commits
3. Auto-detect and fix common issues
4. Flag suspicious changes for human review
5. Continuously learn from new corrections
