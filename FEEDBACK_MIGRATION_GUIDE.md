# Feedback System Migration Guide
## From: Old System (3,771 lines, JSON state files)
## To: New System (YAML configs, database state, ~1,250 lines)

**Date:** 2025-10-29
**Status:** Ready for testing
**Breaking Changes:** Minimal (uses same telegram_agent.py)

---

## What Changed?

### ✅ **Keeps Working (No Changes Needed)**
- `telegram_agent.py` (260 lines) - **STILL USED**
- `data_quality_conversations` table - **STILL USED**
- `code_improvements` table - **STILL USED**
- Telegram bot token and chat ID - **STILL USED**
- All existing conversation history - **PRESERVED**

### 🔄 **Replaced (Old → New)**

| Old File | Lines | New File | Lines | Change |
|----------|-------|----------|-------|--------|
| `telegram_approval_listener.py` | 1,130 | `feedback/telegram_interface.py` | 300 | Simplified logic |
| `validation_issue_queue.py` | 395 | `feedback/validation_queue.py` | 350 | Database-backed |
| `investigation_agent.py` | 1,353 | `feedback/investigation_engine.py` | 400 | Core extraction |
| `data_quality_logger.py` | 452 | `feedback/learning_log.py` | 150 | Focused logging |
| **TOTAL** | **3,771** | **TOTAL** | **~1,250** | **66% reduction** |

### 🆕 **Added (New Features)**

| File | Purpose |
|------|---------|
| `config/validation_rules.yaml` | All 13 validation rules (no more Python edits!) |
| `config/fix_templates.yaml` | 9 standard fix templates (reusable) |
| `config/self_improvement_rules.yaml` | Code fix proposals (3+ errors → propose fix) |
| `feedback/self_improvement.py` | Detects patterns & proposes code fixes |
| `feedback/fix_applier.py` | Centralized fix execution |
| `migrations/consolidate_feedback_state.sql` | Database tables (no more JSON files!) |

---

## Migration Steps

### **Phase 1: Preparation (30 minutes)**

#### 1. Backup Current System
```bash
cd /home/ubuntu/spac-research

# Backup JSON state files
cp .validation_issue_queue.json backups/validation_queue_backup_$(date +%Y%m%d).json
cp .telegram_listener_state.json backups/telegram_state_backup_$(date +%Y%m%d).json

# Backup Python files
mkdir -p backups/old_feedback_system
cp telegram_approval_listener.py backups/old_feedback_system/
cp validation_issue_queue.py backups/old_feedback_system/
cp investigation_agent.py backups/old_feedback_system/
cp data_quality_logger.py backups/old_feedback_system/
```

#### 2. Run Database Migration
```bash
# Apply new tables
psql $DATABASE_URL -f migrations/consolidate_feedback_state.sql

# Verify tables created
psql $DATABASE_URL -c "\dt validation_*"
# Should show: validation_queue, validation_queue_items
```

#### 3. Migrate Existing State (Optional)
```bash
# If you have an active queue, migrate it to database
python3 scripts/migrate_queue_to_database.py

# If you want to preserve telegram state
python3 scripts/migrate_telegram_state.py
```

---

### **Phase 2: Testing (1-2 hours)**

#### 1. Test Validation Queue
```bash
cd /home/ubuntu/spac-research

# Test queue creation and management
python3 -c "
from feedback import ValidationQueue

with ValidationQueue() as queue:
    # Create test queue
    test_issues = [
        {
            'ticker': 'TEST',
            'field': 'trust_cash',
            'rule': 'RULE-001',
            'severity': 'CRITICAL',
            'message': 'Test issue',
            'actual': '100M',
            'expected': '50M'
        }
    ]

    queue_id = queue.create_queue(test_issues)
    print(f'Created queue: {queue_id}')

    # Get current issue
    issue = queue.get_current_issue()
    print(f'Current issue: {issue}')

    # Test approval
    queue.mark_current_approved()
    print('✓ Marked as approved')

    # Check stats
    stats = queue.get_queue_stats()
    print(f'Stats: {stats}')
"
```

#### 2. Test Telegram Interface
```bash
# Test sending issue to Telegram
python3 -c "
from feedback import TelegramInterface

interface = TelegramInterface()

# Send test issue
success = interface.send_current_issue()
print(f'Sent to Telegram: {success}')
"
```

Check your Telegram - you should receive the test issue!

#### 3. Test YAML Rule Loading
```bash
# Test validation rules
python3 -c "
from feedback.rule_loader import load_validation_rules

rules = load_validation_rules('config/validation_rules.yaml')
print(f'Loaded {len(rules)} validation rules')

for rule_id, rule in list(rules.items())[:3]:
    print(f'  - {rule_id}: {rule[\"name\"]}')
"
```

---

### **Phase 3: Cutover (Seamless)**

#### Option A: Side-by-Side (Recommended)
Run both systems in parallel for 7 days:

```bash
# Keep old listener running
screen -S old_telegram_listener
python3 telegram_approval_listener.py --daemon
# Ctrl+A, D to detach

# Start new interface
screen -S new_telegram_interface
python3 feedback/telegram_interface.py --daemon
# Ctrl+A, D to detach
```

Monitor both. After 7 days, stop old listener.

#### Option B: Full Cutover (Faster)
Replace immediately:

```bash
# Stop old listener
pkill -f telegram_approval_listener.py

# Start new interface
nohup python3 feedback/telegram_interface.py --daemon > logs/telegram_interface.log 2>&1 &

# Verify running
ps aux | grep telegram_interface
```

---

### **Phase 4: Cleanup (After 7 days)**

Once new system proven stable:

```bash
# Move old files to archive
mkdir -p archive/feedback_v1
mv telegram_approval_listener.py archive/feedback_v1/
mv validation_issue_queue.py archive/feedback_v1/
mv investigation_agent.py archive/feedback_v1/

# Remove JSON state files
rm .validation_issue_queue.json
rm .telegram_listener_state.json

# Update imports in other files
# (Search for old imports and replace with new)
grep -r "from validation_issue_queue import" .
grep -r "from telegram_approval_listener import" .
```

---

## Key Differences

### **Old System (JSON Files)**
```python
# Old approach
from validation_issue_queue import ValidationIssueQueue

queue = ValidationIssueQueue()  # Loads from .validation_issue_queue.json
queue.send_current_issue()
```

**Problems:**
- ❌ JSON file can get corrupted
- ❌ No ACID transactions
- ❌ Can't query "show me all approved trust_cash fixes"
- ❌ Race conditions if multiple processes

### **New System (Database)**
```python
# New approach
from feedback import ValidationQueue

with ValidationQueue() as queue:  # Database session
    queue.send_current_issue()
```

**Benefits:**
- ✅ ACID transactions
- ✅ Can query: `SELECT * FROM validation_queue_items WHERE status='approved'`
- ✅ No file corruption possible
- ✅ Thread-safe, multi-process safe

---

## Adding New Validation Rules

### **Old Way (Python Code)**
```python
# Had to edit data_validation_rules.py
class NewRule(ValidationRule):
    def __init__(self):
        super().__init__("New Rule", "critical")

    def validate(self, spac: SPAC) -> Optional[Dict]:
        # 30+ lines of Python logic...
        pass

# Then redeploy code
```

**Problems:**
- ❌ Requires code changes
- ❌ Requires redeployment
- ❌ Non-developers can't add rules

### **New Way (YAML Config)**
```yaml
# Edit config/validation_rules.yaml
rules:
  my_new_rule:
    id: "RULE-050"
    name: "My New Rule"
    severity: CRITICAL
    validation:
      condition: "field > threshold"
    message_template: "Field {field} is {value}"
    auto_fix:
      enabled: true
```

**Benefits:**
- ✅ No code changes
- ✅ Just restart service
- ✅ Non-developers can add rules
- ✅ Version control friendly

---

## Self-Improvement Feature

### **How It Works**

1. **Detection**: System monitors `data_quality_conversations` table
2. **Threshold**: If same error occurs 3+ times in 30 days → trigger
3. **Analysis**: AI analyzes pattern and proposes code fix
4. **Proposal**: Sends to you via Telegram with exact diff
5. **Approval**: You review and type `APPROVE CODE FIX {id}`
6. **Apply**: System applies fix, creates backup, tracks effectiveness
7. **Verification**: Monitors for 7 days - did error stop?

### **Example Workflow**

```
Day 1: "shares_outstanding not found in 424B4" (SPAC: AACT)
Day 5: "shares_outstanding not found in 424B4" (SPAC: BLUW)
Day 9: "shares_outstanding not found in 424B4" (SPAC: CCCX)

🔧 THRESHOLD CROSSED (3 errors in 30 days)

AI Analysis:
- Root cause: AI extraction prompt missing unit offering details
- Proposed fix: Add "shares outstanding" extraction to 424B4 parser
- Files: sec_data_scraper.py (line 245-260)
- Confidence: 90%

Telegram Message:
🔧 CODE IMPROVEMENT PROPOSAL
Error: shares_outstanding_not_found_424B4
Occurrences: 3 times (last 30 days)

Proposed Fix:
Add exhibit search for unit offering details in 424B4 parser

Files to Modify: sec_data_scraper.py

Reply REVIEW to see git diff
Reply APPROVE CODE FIX 123 to apply
```

You reply: `REVIEW`

```
System shows:
--- a/sec_data_scraper.py
+++ b/sec_data_scraper.py
@@ -250,6 +250,12 @@ def extract_ipo_data(filing_text):
+    # Check for shares outstanding in unit offering table
+    if not shares_outstanding:
+        match = re.search(r'(\d+,\d+,\d+)\s+[uU]nits', filing_text)
+        if match:
+            shares_outstanding = int(match.group(1).replace(',', ''))
+

Reply APPROVE CODE FIX 123 to apply this change
```

You reply: `APPROVE CODE FIX 123`

```
✅ Fix applied successfully
✓ Backup created: backups/sec_data_scraper.py.bak_20251029
✓ Logged to code_improvements table (id=123)
✓ Monitoring error rate for 7 days

Rollback command (if needed):
python3 feedback/rollback_code_fix.py --fix-id 123
```

---

## Rollback Plan

If new system has issues:

```bash
# Stop new system
pkill -f telegram_interface.py

# Restore old system
cp backups/old_feedback_system/* .

# Start old listener
python3 telegram_approval_listener.py --daemon

# Restore JSON state files
cp backups/validation_queue_backup_*.json .validation_issue_queue.json
cp backups/telegram_state_backup_*.json .telegram_listener_state.json
```

---

## FAQ

**Q: Will my existing conversation history be lost?**
A: No! It's preserved in `data_quality_conversations` table. New system reads from same table.

**Q: Do I need to reconfigure Telegram?**
A: No! Same bot token, same chat ID. Uses existing `telegram_agent.py`.

**Q: Can I run both systems simultaneously?**
A: Yes! Recommended for testing. They won't conflict (different queue management).

**Q: What if a code fix breaks something?**
A:
1. Backup is created automatically
2. Use rollback command: `python3 feedback/rollback_code_fix.py --fix-id {id}`
3. Monitor for 7 days before next fix

**Q: How do I know if new system is working?**
A: Check Telegram - you should receive issues same as before, but with better formatting.

---

## Testing Checklist

Before cutover, verify:

- [ ] Database tables created successfully
- [ ] Can create validation queue
- [ ] Can get current issue
- [ ] Telegram messages send successfully
- [ ] Can approve/skip issues
- [ ] Batch approval works
- [ ] YAML rules load correctly
- [ ] Fix templates load correctly
- [ ] Self-improvement detection works (test with 3 mock errors)
- [ ] Code fix proposals send to Telegram
- [ ] Rollback works

---

## Support

If issues occur:
1. Check logs: `tail -f logs/telegram_interface.log`
2. Check database: `SELECT * FROM current_queue_status;`
3. Check Telegram state: `SELECT * FROM telegram_state;`
4. Rollback if needed (see above)

---

## Timeline

**Week 1:** Side-by-side testing
**Week 2:** Monitor both systems
**Week 3:** Full cutover to new system
**Week 4:** Remove old system files

**Total: 4 weeks** for safe migration
