# Handling News-First Deal Announcements (SEC Filing Lag)

**Date:** October 9, 2025

---

## The Problem

**SEC filing lag:** News often breaks 15 minutes to 24 hours BEFORE the SEC 8-K is filed.

**Example Timeline:**
```
8:30 AM  - Company issues press release
8:31 AM  - PR Newswire RSS feed updates
8:32 AM  - WSJ publishes article
8:35 AM  - Our system detects via RSS
8:40 AM  - AI verifies it's a real deal
8:45 AM  - Telegram alert sent
...
4:00 PM  - SEC 8-K filed (7.5 hours later!)
4:05 PM  - SEC RSS feed updates
```

**Traditional problem:** System waits for SEC confirmation, misses early opportunity.

**Our solution:** Alert on news FIRST, verify via SEC LATER.

---

## Two-Phase Verification Strategy

### Phase 1: News Detection (Immediate Alert)

**When:** News RSS feed detects potential deal

**Process:**
1. RSS feed catches news article
2. Filter duplicates (signal_tracker.py)
3. AI verifies it's genuine deal announcement
4. Check source credibility (WSJ = tier 1)
5. Calculate confidence (AI + source tier)
6. **IF confidence >= 70%: Send Telegram alert**

**Alert says:**
```
🚨 UNVERIFIED - Awaiting SEC Confirmation

Source: WSJ (Tier 1)
Ticker: $CCCX
Deal: Merger with TechCorp for $3B

AI Verification: ✅ Definitive Agreement (95% confidence)
SEC Status: ⏳ Awaiting 8-K filing

Action: Monitoring SEC EDGAR for 8-K confirmation
```

**Key:** Alert sent IMMEDIATELY, don't wait for SEC

### Phase 2: SEC Verification (Follow-Up)

**When:** SEC 8-K filing detected (minutes to hours later)

**Process:**
1. SEC monitor detects new 8-K for this ticker
2. Orchestrator dispatches DealDetector agent
3. DealDetector parses 8-K for deal details
4. Extract: target, deal value, expected close, terms
5. Update database with confirmed details
6. **Send follow-up Telegram alert**

**Follow-up alert says:**
```
✅ CONFIRMED VIA SEC 8-K

Ticker: $CCCX
Deal: Business combination with TechCorp Inc.

SEC Filing: 8-K filed at 4:02 PM ET
Deal Value: $3.0 billion
Expected Close: Q2 2026
Pro Forma Equity: $450M

Database updated with full deal details.
```

**Key:** Confirmation sent when SEC validates

---

## Implementation

### signal_monitor_agent.py - News Detection

```python
def check_news_signals(self, ticker: str, days_back: int = 3) -> Optional[Dict]:
    """Check news for deal signals (IMMEDIATE ALERT PATH)"""

    # Get new articles
    articles = self.news_monitor.search_spac_news(ticker, days_back=days_back)
    new_articles = self.tracker.filter_new_news(articles, ticker)

    if not new_articles:
        return None

    # AI verification
    for article in new_articles:
        if 'definitive agreement' in text:
            verification = self.verify_deal_news_with_ai(ticker, article)

            # AI confirmed deal
            if verification['deal_stage'] == 'definitive_agreement':
                has_definitive_agreement = True
                target_mentioned = verification['target_name']

    # Calculate confidence
    confidence = 70 if has_definitive_agreement else 0
    confidence += 20 if target_mentioned else 0
    confidence += 20 if 'wsj' in source else 0  # Source bonus

    return {
        'confidence': confidence,
        'has_definitive_agreement': has_definitive_agreement,
        'target_mentioned': target_mentioned,
        'sec_verified': False,  # Not yet!
        'ai_verifications': [verification]
    }
```

### Trigger Logic - Send Alert Before SEC

```python
def should_trigger_orchestrator(self, ticker: str, reddit_signals: Dict, news_signals: Dict):
    """Trigger even WITHOUT SEC verification if confidence high enough"""

    news_conf = news_signals.get('confidence', 0) if news_signals else 0

    # CRITICAL: News with definitive agreement (AI-verified)
    if news_signals and news_signals.get('has_definitive_agreement'):
        # Don't wait for SEC - alert NOW
        return {
            'should_trigger': True,
            'priority': 'CRITICAL',
            'reason': 'News article mentions definitive agreement (AI-verified)',
            'actions': ['deal_detector'],  # Will verify via SEC later
            'sec_status': 'pending'  # Flag as not yet verified
        }

    # HIGH: Multiple credible sources
    elif news_conf >= 80:
        return {
            'should_trigger': True,
            'priority': 'HIGH',
            'reason': f'High confidence news ({news_conf}%) from credible source',
            'actions': ['deal_detector'],
            'sec_status': 'pending'
        }

    return {'should_trigger': False}
```

### Telegram Alert - Indicate SEC Status

```python
def _send_trigger_alert(self, ticker: str, trigger: Dict):
    """Send alert with SEC verification status"""

    sec_status = trigger.get('sec_status', 'unknown')

    if sec_status == 'pending':
        status_emoji = '⏳'
        status_text = 'UNVERIFIED - Awaiting SEC Confirmation'
    elif sec_status == 'confirmed':
        status_emoji = '✅'
        status_text = 'CONFIRMED VIA SEC 8-K'
    else:
        status_emoji = '🔍'
        status_text = 'VERIFICATION IN PROGRESS'

    message = f"{status_emoji} <b>{status_text}</b>\n\n"
    message += f"🚨 <b>{trigger['priority']} PRIORITY</b>\n\n"
    message += f"<b>Ticker:</b> ${ticker}\n"
    message += f"<b>Reason:</b> {trigger['reason']}\n"

    # News details
    if trigger.get('news_signals'):
        ns = trigger['news_signals']
        if ns.get('ai_verifications'):
            verification = ns['ai_verifications'][0]
            message += f"\n<b>AI Verification:</b>\n"
            message += f"  • Stage: {verification['deal_stage']}\n"
            message += f"  • Confidence: {verification['confidence']}%\n"
            if verification.get('target_name'):
                message += f"  • Target: {verification['target_name']}\n"

        if ns.get('sources'):
            message += f"\n<b>Sources:</b> {', '.join(ns['sources'])}\n"

    # Next steps
    if sec_status == 'pending':
        message += f"\n<b>Next Steps:</b>\n"
        message += f"  • Monitoring SEC EDGAR for 8-K filing\n"
        message += f"  • Will send confirmation when SEC files\n"

    send_telegram_alert(message)
```

---

## SEC Verification Follow-Up

### autonomous_monitor.py - SEC Filing Detection

```python
def run(self):
    """Main monitoring loop"""

    while True:
        # Every 15 minutes: Check SEC RSS feeds
        filings = self.sec_monitor.poll_all_spacs()

        for filing in filings:
            if filing['type'] == '8-K':
                # Check if this is a deal announcement
                classification = self.sec_monitor.classify_filing(filing)

                if 'deal_announcement' in classification:
                    # Verify if we already alerted on this deal via news
                    self._verify_and_update_news_alert(filing)

def _verify_and_update_news_alert(self, filing):
    """
    Check if we sent news-based alert earlier
    If yes, send confirmation update
    """

    ticker = filing['ticker']

    # Check signal tracker for recent news alerts
    tracker = SignalTracker()
    recent_alerts = tracker.data['last_alerts'].get(ticker)

    if recent_alerts:
        last_alert_time = datetime.fromisoformat(recent_alerts['timestamp'])
        hours_since = (datetime.now() - last_alert_time).total_seconds() / 3600

        # If alerted within last 24 hours, this is likely confirmation
        if hours_since < 24:
            logger.info(f"📋 SEC 8-K confirms earlier news alert for {ticker}")

            # Dispatch DealDetector to extract full details
            task = AgentTask(
                agent_name='deal_detector',
                task_type='filing_verification',
                priority=TaskPriority.HIGH,
                parameters={'filing': filing, 'is_confirmation': True}
            )

            result = self.orchestrator.agents['deal_detector'].execute(task)

            # Send confirmation alert
            self._send_sec_confirmation_alert(ticker, result)
```

### Deal Detector - Extract Full Details

```python
# deal_detector_agent.py

def execute(self, task: AgentTask):
    """Process 8-K filing"""

    filing = task.parameters['filing']
    is_confirmation = task.parameters.get('is_confirmation', False)

    # Parse 8-K for deal details
    deal_info = self.parse_8k_for_deal(filing)

    if deal_info:
        # Update database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        spac.deal_status = 'ANNOUNCED'
        spac.announced_date = deal_info['announced_date']
        spac.target = deal_info['target']
        spac.deal_value = deal_info['deal_value']
        spac.expected_close = deal_info['expected_close']

        self.db.commit()

        # Return results
        return {
            'deal_confirmed': True,
            'is_confirmation': is_confirmation,  # Was this a news follow-up?
            'deal_details': deal_info
        }
```

### Confirmation Alert

```python
def _send_sec_confirmation_alert(self, ticker: str, verification_result: Dict):
    """Send follow-up alert confirming earlier news"""

    deal_info = verification_result['deal_details']

    message = f"✅ <b>SEC CONFIRMATION</b>\n\n"
    message += f"<b>Ticker:</b> ${ticker}\n"
    message += f"<b>Status:</b> Earlier news alert now confirmed by SEC 8-K\n\n"

    message += f"<b>Deal Details (from 8-K):</b>\n"
    message += f"  • Target: {deal_info['target']}\n"
    message += f"  • Deal Value: ${deal_info['deal_value'] / 1e9:.1f}B\n"
    message += f"  • Announced: {deal_info['announced_date']}\n"
    message += f"  • Expected Close: {deal_info['expected_close']}\n"
    message += f"  • Pro Forma Equity: ${deal_info.get('pro_forma_equity', 0) / 1e6:.0f}M\n\n"

    message += f"<b>SEC Filing:</b>\n"
    message += f"  • Form: 8-K (Current Event)\n"
    message += f"  • Filed: {datetime.now().strftime('%Y-%m-%d %I:%M %p ET')}\n"
    message += f"  • Link: https://sec.gov/...\n\n"

    message += f"✅ Database updated with confirmed details"

    send_telegram_alert(message)
```

---

## Alert Flow Example

### Example: CCCX Deal Announcement

**8:30 AM - Press Release Issued**
```
TechCorp and CCCX announce definitive merger agreement
```

**8:32 AM - RSS Feed Catches News**
```
[RSS Monitor] WSJ article detected: "CCCX to Merge with TechCorp in $3B Deal"
```

**8:35 AM - AI Verification**
```
[AI] Analyzing article...
[AI] Deal Stage: definitive_agreement
[AI] Target: TechCorp Inc.
[AI] Confidence: 95%
```

**8:37 AM - Source Credibility Check**
```
[Signal Monitor] Source: WSJ (Tier 1)
[Signal Monitor] Base confidence: 95%
[Signal Monitor] Source bonus: +20%
[Signal Monitor] Final confidence: 100%
```

**8:38 AM - Trigger Decision**
```
[Orchestrator] should_trigger_orchestrator()
[Orchestrator] Priority: CRITICAL
[Orchestrator] Reason: News article mentions definitive agreement (AI-verified, WSJ)
[Orchestrator] SEC Status: pending
```

**8:39 AM - Telegram Alert Sent**
```
⏳ UNVERIFIED - Awaiting SEC Confirmation

🚨 CRITICAL PRIORITY

Ticker: $CCCX
Reason: News article mentions definitive agreement (AI-verified)

AI Verification:
  • Stage: definitive_agreement
  • Confidence: 95%
  • Target: TechCorp Inc.

Sources: WSJ (Tier 1)

Next Steps:
  • Monitoring SEC EDGAR for 8-K filing
  • Will send confirmation when SEC files
```

**4:02 PM - SEC 8-K Filed** (7.5 hours later)
```
[SEC Monitor] New 8-K filing detected: CCCX
[SEC Monitor] Filing type: Business Combination Agreement
[SEC Monitor] Checking for earlier news alert...
[SEC Monitor] Found news alert from 8:39 AM (7.5h ago)
[SEC Monitor] Dispatching DealDetector for full extraction
```

**4:05 PM - Database Updated**
```
[DealDetector] Parsing 8-K...
[DealDetector] Extracted:
  - Target: TechCorp Inc.
  - Deal Value: $3.0B
  - Expected Close: Q2 2026
  - Pro Forma Equity: $450M
[Database] CCCX updated: deal_status=ANNOUNCED
```

**4:06 PM - Confirmation Alert Sent**
```
✅ SEC CONFIRMATION

Ticker: $CCCX
Status: Earlier news alert now confirmed by SEC 8-K

Deal Details (from 8-K):
  • Target: TechCorp Inc.
  • Deal Value: $3.0B
  • Announced: 2025-10-09
  • Expected Close: Q2 2026
  • Pro Forma Equity: $450M

SEC Filing:
  • Form: 8-K (Current Event)
  • Filed: 2025-10-09 04:02 PM ET
  • Link: https://sec.gov/...

✅ Database updated with confirmed details
```

---

## Benefits

### 1. Early Detection (Hours Ahead)

**Traditional:** Wait for SEC 8-K → Miss 4-8 hours of price movement

**Our System:** Alert on news → Get 4-8 hour head start

**Value:** Can trade on announcement before market fully reacts

### 2. Risk Mitigation

**False Positive Protection:**
- AI verification (confidence scoring)
- Source credibility check (WSJ > random blog)
- Alert clearly marked as "UNVERIFIED" until SEC confirms

**Transparency:**
- User knows it's based on news, not SEC
- Follow-up confirmation when SEC files
- Can choose to wait for SEC or act on news

### 3. Full Audit Trail

**News → AI → Alert → SEC → Confirmation**

All logged:
1. When news detected
2. AI verification results
3. Initial alert sent
4. SEC filing detected
5. Confirmation sent
6. Database updated

Can review entire timeline for each deal.

---

## Configuration

### Monitoring Frequency

**RSS News Monitor:**
```
Poll interval: 15 minutes (continuous)
```

**SEC Filing Monitor:**
```
Poll interval: 15 minutes (continuous)
```

**Both run simultaneously:**
- News catches announcements FAST
- SEC provides CONFIRMATION

### Confidence Thresholds

**Immediate Alert:**
- AI-verified definitive agreement: 70% base
- Tier 1 source (WSJ): +20%
- Target mentioned: +20%
- **Total: 110% → Alert sent**

**Wait for SEC:**
- AI confidence <70%: Don't alert yet
- Speculation/rumor only: Monitor, wait for SEC
- Unverified source: Wait for tier 1 confirmation

---

## Summary

**Problem:** SEC filings lag behind news by hours

**Solution:** Two-phase verification

**Phase 1 (Immediate):**
1. RSS monitor detects news
2. AI verifies it's real deal
3. Source credibility check
4. **Send alert marked as "UNVERIFIED"**

**Phase 2 (Confirmation):**
1. SEC 8-K filed (hours later)
2. DealDetector extracts full details
3. Database updated
4. **Send confirmation alert**

**Result:**
- ✅ Early detection (4-8 hour advantage)
- ✅ Risk mitigation (AI + source verification)
- ✅ Full confirmation (SEC follow-up)
- ✅ Transparency (clearly marked as unverified until SEC confirms)

**User gets:** Best of both worlds - early notification + authoritative confirmation

---

**Deploy:**
```bash
# Start RSS monitor (15 min intervals)
sudo systemctl start spac-rss-monitor

# SEC monitor already running (via spac-monitor.service)

# Both run in parallel:
# - News = fast detection
# - SEC = authoritative confirmation
```
