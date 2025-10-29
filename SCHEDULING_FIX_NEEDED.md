# Scheduling Fix Needed

## Issue: Daily SEC Filing Report Running at Wrong Time

**Current:** Report runs at ~3:58 AM EDT (12am EST)
**Problem:** SEC filings for Oct 29 won't be filed yet at midnight
**Desired:** Run after market open at 9:30 AM EST (6:30 AM PST)

### Files Involved
- `daily_filing_report.py` - Says "default 11:59 PM EDT" but running at 3:58 AM

### Root Cause
Likely a cron job or scheduler running the script at wrong time.

### Recommended Schedule
```bash
# Best times for SEC filing report:
# 1. Morning report: 10:00 AM EST (after market open, catch overnight filings)
# 2. Evening report: 6:00 PM EST (after market close, catch all day's filings)

# Cron format (runs at 10:00 AM EST):
0 10 * * * cd /home/ubuntu/spac-research && python3 daily_filing_report.py >> logs/daily_reports.log 2>&1

# Or for evening report (6:00 PM EST):
0 18 * * * cd /home/ubuntu/spac-research && python3 daily_filing_report.py >> logs/daily_reports.log 2>&1
```

### Fix Steps
1. Find current scheduler:
   ```bash
   # Check crontab
   crontab -l

   # Check systemd timers
   systemctl list-timers

   # Check for background scheduler scripts
   ps aux | grep daily_filing_report
   ```

2. Update schedule to 10:00 AM EST:
   ```bash
   crontab -e
   # Change time to: 0 10 * * *
   ```

3. Test new time:
   ```bash
   # Run manually to test
   python3 daily_filing_report.py
   ```

### Alternative: Make Schedule Configurable
Add environment variable:
```python
# In daily_filing_report.py
REPORT_TIME = os.getenv('DAILY_REPORT_TIME', '10:00')  # Default 10:00 AM
```

Then in `.env`:
```
DAILY_REPORT_TIME=10:00
```

### Priority
**Medium** - Not critical but annoying to get empty reports at midnight

### Estimate
**10 minutes** to find and fix scheduler
