"""
Data Validator Agent
Validates data quality and flags issues for review
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class DataValidatorAgent(OrchestratorAgentBase):
    """Validates data quality and logical consistency"""

    def _determine_fix_parameters(self, anomaly_type: str) -> Dict:
        """Determine which fix parameters to use based on anomaly type"""
        fix_map = {
            'invalid_target': {
                'fix_type': 'invalid_targets',
                'auto_commit': True
            },
            'type_error': {
                'fix_type': 'type_errors',
                'fix_types': True,
                'auto_commit': True
            },
            'date_format_error': {
                'fix_type': 'date_errors',
                'fix_dates': True,
                'auto_commit': True
            },
            'trust_cash_error': {
                'fix_type': 'trust_errors',
                'fix_trust': True,
                'auto_commit': False  # Requires 424B4 re-scraping
            },
            'deal_status_inconsistency': {
                'fix_type': 'status_inconsistency',
                'auto_commit': False  # Requires research
            }
        }

        return fix_map.get(anomaly_type, {
            'fix_type': 'manual_review',
            'auto_commit': False
        })

    def execute(self, task):
        self._start_task(task)

        try:
            from data_validator_agent import DataValidatorAgent as Validator

            # Determine if we should auto-fix
            auto_fix = task.parameters.get('auto_fix', False)

            validator = Validator(auto_fix=auto_fix)

            # Set orchestrator delegate if available
            if hasattr(self, 'orchestrator_ref'):
                validator.set_orchestrator_delegate(self.orchestrator_ref)

            validator.validate_all_spacs()

            stats = validator.get_statistics()

            # If there are issues needing research, handle them
            if auto_fix and validator.needs_research and hasattr(self, 'orchestrator_ref'):
                print(f"\n[DATA VALIDATOR] {len(validator.needs_research)} issues need research")
                print(f"[DATA VALIDATOR] Requesting orchestrator to dispatch research agents...\n")

                researched_fixes = 0
                for research_req in validator.needs_research:
                    # Ask orchestrator to research this issue
                    research_result = self.orchestrator_ref.research_issue(research_req)

                    if research_result:
                        # Apply fix with research context
                        db = SessionLocal()
                        spac = db.query(SPAC).filter(SPAC.ticker == research_req['ticker']).first()

                        if spac:
                            fixed = validator.apply_fix_with_research(
                                spac,
                                research_req['fix_type'],
                                research_result
                            )

                            if fixed:
                                researched_fixes += 1

                        db.commit()
                        db.close()

                if researched_fixes > 0:
                    print(f"[DATA VALIDATOR] Applied {researched_fixes} research-based fixes")
                    stats['fixes_applied'] += researched_fixes

            validator.close()

            result = {
                'total_issues': stats['total_issues'],
                'critical_issues': stats['by_severity']['CRITICAL'],
                'high_issues': stats['by_severity']['HIGH'],
                'fixes_applied': stats['fixes_applied'],
                'needs_research': stats.get('needs_research', 0)
            }

            # NEW: If critical issues found, use Investigation Agent + Telegram approval workflow
            if stats['by_severity']['CRITICAL'] > 0 and hasattr(self, 'orchestrator_ref'):
                print(f"\n[DATA VALIDATOR] {stats['by_severity']['CRITICAL']} CRITICAL issues detected")
                print(f"[DATA VALIDATOR] Sending to Investigation Agent + Telegram approval workflow...\n")

                # Get detailed issue information from validator
                critical_issues = validator.get_critical_issues()  # Get full details

                # NEW: Enhance issues with web research before processing
                critical_issues = self.orchestrator_ref.research_and_enhance_issues(critical_issues)

                # Group issues by type
                issues_by_type = {}
                for issue in critical_issues:
                    issue_type = issue.get('type', 'unknown')
                    if issue_type not in issues_by_type:
                        issues_by_type[issue_type] = []
                    issues_by_type[issue_type].append(issue)

                # Process each anomaly type
                from investigation_agent import InvestigationAgent
                import uuid

                for anomaly_type, issues in issues_by_type.items():
                    # Check if any issues have auto_fix='investigate_deadline_extension'
                    deadline_investigations = [i for i in issues if i.get('auto_fix') == 'investigate_deadline_extension']

                    if deadline_investigations:
                        # Special handling: Automatically investigate deadline extensions
                        print(f"\n[ORCHESTRATOR] Triggering deadline extension investigations for {len(deadline_investigations)} SPAC(s)")

                        investigator = InvestigationAgent()

                        for issue in deadline_investigations:
                            ticker = issue['ticker']
                            cik = issue.get('metadata', {}).get('cik')
                            deadline_date = issue.get('metadata', {}).get('deadline_date')

                            if not cik:
                                # Try to fetch missing CIK
                                cik = self._ensure_cik(ticker)
                                if not cik:
                                    print(f"   ⚠️  {ticker}: No CIK available and could not fetch it, skipping")
                                    continue

                            print(f"\n   Investigating {ticker}...")

                            # Call investigation agent's deadline extension method with deadline_date for smart lookback
                            result = investigator.investigate_deadline_extension(ticker, cik, deadline_date=deadline_date)

                            if result.get('extension_found'):
                                # Update deadline in database
                                new_deadline = result['new_deadline']
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    old_deadline = spac.deadline_date
                                    spac.deadline_date = new_deadline
                                    spac.is_extended = True
                                    spac.extension_count = (spac.extension_count or 0) + 1
                                    self.orchestrator_ref.db.commit()

                                    print(f"   ✅ Updated {ticker} deadline: {old_deadline} → {new_deadline}")

                                    # Update the queue conversation's final_fix so "approve" works correctly
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'deadline_date': new_deadline.isoformat() if hasattr(new_deadline, 'isoformat') else str(new_deadline),
                                            'is_extended': True,
                                            'extension_count': spac.extension_count
                                        }
                                    )

                                    # Send Telegram notification
                                    from utils.alert_deduplication import should_send_alert, mark_alert_sent
                                    if should_send_alert('deadline_extension', ticker=ticker, dedup_hours=24):
                                        self.orchestrator_ref.agents['telegram'].execute(AgentTask(
                                            task_id=f"telegram_deadline_ext_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                            agent_name="telegram",
                                            task_type="send_alert",
                                            priority=TaskPriority.HIGH,
                                            status=TaskStatus.PENDING,
                                            created_at=datetime.now(),
                                            parameters={'alert_text': f"""✅ <b>Deadline Extension Found</b>

<b>Ticker:</b> {ticker}
<b>Old Deadline:</b> {old_deadline}
<b>New Deadline:</b> {new_deadline}
<b>Source:</b> {result['source_filing']}

Database automatically updated."""}
                                        ))
                                        mark_alert_sent('deadline_extension', ticker=ticker)

                            elif result.get('completion_found'):
                                # Update to COMPLETED
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    spac.deal_status = 'COMPLETED'
                                    self.orchestrator_ref.db.commit()
                                    print(f"   ✅ Updated {ticker} to COMPLETED")

                                    # Update queue conversation's final_fix
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={'deal_status': 'COMPLETED'}
                                    )

                            elif result.get('termination_found'):
                                # Update to TERMINATED
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    spac.deal_status = 'TERMINATED'
                                    self.orchestrator_ref.db.commit()
                                    print(f"   ✅ Updated {ticker} to TERMINATED")

                                    # Update queue conversation's final_fix
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={'deal_status': 'TERMINATED'}
                                    )

                        investigator.close()

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Check if any issues have auto_fix='verify_deal_filing'
                    deal_verifications = [i for i in issues if i.get('auto_fix') == 'verify_deal_filing']

                    if deal_verifications:
                        # Special handling: Automatically verify deal filings
                        print(f"\n[ORCHESTRATOR] Auto-verifying {len(deal_verifications)} deal filing(s)")

                        from utils.sec_filing_fetcher import SECFilingFetcher
                        sec_fetcher = SECFilingFetcher()

                        verified_count = 0
                        fake_deals_found = 0

                        for issue in deal_verifications:
                            ticker = issue['ticker']
                            context = issue.get('context', {})
                            filing_url = context.get('deal_filing_url')
                            target = context.get('target')

                            if not filing_url:
                                print(f"   ⚠️  {ticker}: No filing URL, skipping")
                                continue

                            print(f"\n   Verifying {ticker} → {target}...")
                            print(f"      Filing: {filing_url}")

                            # Fetch filing content
                            try:
                                filing_text = sec_fetcher.fetch_document(filing_url)
                                if not filing_text:
                                    print(f"      ⚠️  Could not fetch filing")
                                    continue

                                # Check for business combination keywords
                                is_real_deal = self._verify_deal_filing_content(filing_text, target)

                                if is_real_deal:
                                    print(f"      ✅ Verified: Real business combination")
                                    verified_count += 1

                                    # Update queue conversation to mark as verified
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={'verified': True, 'status': 'real_deal'}
                                    )

                                else:
                                    print(f"      ❌ FAKE DEAL DETECTED: Not a business combination")
                                    fake_deals_found += 1

                                    # Clear fake deal from database
                                    spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                    if spac:
                                        old_target = spac.target
                                        spac.deal_status = 'SEARCHING'
                                        spac.target = None
                                        spac.announced_date = None
                                        spac.deal_filing_url = None
                                        self.orchestrator_ref.db.commit()

                                        print(f"      ✓ Cleared fake deal: {old_target}")

                                        # Update queue conversation
                                        self._update_queue_conversation_final_fix(
                                            ticker=ticker,
                                            final_fix={
                                                'deal_status': 'SEARCHING',
                                                'target': None,
                                                'announced_date': None,
                                                'deal_filing_url': None
                                            }
                                        )

                                        # Send alert for fake deal
                                        from utils.alert_deduplication import should_send_alert, mark_alert_sent
                                        if should_send_alert('fake_deal', ticker=ticker, dedup_hours=168):
                                            self.orchestrator_ref.agents['telegram'].execute(AgentTask(
                                                task_id=f"telegram_fake_deal_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                                agent_name="telegram",
                                                task_type="send_alert",
                                                priority=TaskPriority.HIGH,
                                                status=TaskStatus.PENDING,
                                                created_at=datetime.now(),
                                                parameters={'alert_text': f"""❌ <b>FAKE DEAL DETECTED</b>

<b>Ticker:</b> {ticker}
<b>False Target:</b> {old_target}
<b>Filing:</b> Not a business combination

Database cleared - reverted to SEARCHING."""}
                                            ))
                                            mark_alert_sent('fake_deal', ticker=ticker)

                            except Exception as e:
                                print(f"      ⚠️  Error verifying filing: {e}")
                                import traceback
                                traceback.print_exc()

                        # SECFilingFetcher doesn't need cleanup

                        print(f"\n   📊 Verification Summary:")
                        print(f"      ✅ Verified: {verified_count}")
                        print(f"      ❌ Fake deals: {fake_deals_found}")

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Check if any issues have auto_fix='investigate_deal_status'
                    deal_status_checks = [i for i in issues if i.get('auto_fix') == 'investigate_deal_status']

                    if deal_status_checks:
                        # Special handling: Investigate deals with suspicious negative premiums
                        print(f"\n[ORCHESTRATOR] Investigating deal status for {len(deal_status_checks)} SPAC(s) with negative premiums")

                        investigator = InvestigationAgent()

                        for issue in deal_status_checks:
                            ticker = issue['ticker']
                            context = issue.get('context', {})
                            cik = issue.get('metadata', {}).get('cik')
                            premium = context.get('premium')

                            if not cik:
                                # Try to fetch missing CIK
                                cik = self._ensure_cik(ticker)
                                if not cik:
                                    print(f"   ⚠️  {ticker}: No CIK available and could not fetch it, skipping")
                                    continue

                            print(f"\n   Investigating {ticker} (trading at {premium:.1f}% below NAV)...")

                            # Check recent filings for termination, completion, or issues
                            result = investigator.investigate_deadline_extension(ticker, cik)

                            if result.get('termination_found'):
                                # Deal was terminated
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    old_target = spac.target
                                    spac.deal_status = 'SEARCHING'
                                    spac.target = None
                                    spac.announced_date = None
                                    self.orchestrator_ref.db.commit()
                                    print(f"   ✅ Deal terminated - cleared {ticker}")

                                    # Update queue conversation's final_fix
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'deal_status': 'SEARCHING',
                                            'target': None,
                                            'termination_reason': result.get('reason', 'Unknown')
                                        }
                                    )

                                    # Send Telegram notification
                                    from utils.alert_deduplication import should_send_alert, mark_alert_sent
                                    if should_send_alert('deal_termination', ticker=ticker, dedup_hours=168):
                                        self.orchestrator_ref.agents['telegram'].execute(AgentTask(
                                            task_id=f"telegram_deal_term_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                            agent_name="telegram",
                                            task_type="send_alert",
                                            priority=TaskPriority.HIGH,
                                            status=TaskStatus.PENDING,
                                            created_at=datetime.now(),
                                            parameters={'alert_text': f"""⚠️ <b>Deal Terminated</b>

<b>Ticker:</b> {ticker}
<b>Target:</b> {old_target}
<b>Premium:</b> {premium:.1f}% (below NAV)
<b>Reason:</b> {result.get('reason', 'See SEC filing')}

Database updated - reverted to SEARCHING."""}
                                        ))
                                        mark_alert_sent('deal_termination', ticker=ticker)

                            elif result.get('completion_found'):
                                # Deal completed
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    spac.deal_status = 'COMPLETED'
                                    self.orchestrator_ref.db.commit()
                                    print(f"   ✅ Deal completed - updated {ticker} to COMPLETED")

                                    # Update queue conversation's final_fix
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={'deal_status': 'COMPLETED'}
                                    )

                            else:
                                # No termination or completion found - negative premium may be market skepticism
                                print(f"   ℹ️  No termination/completion found - negative premium may reflect market concern about deal terms")

                                # Update queue conversation to indicate investigation complete but no action needed
                                self._update_queue_conversation_final_fix(
                                    ticker=ticker,
                                    final_fix={
                                        'status': 'investigated',
                                        'finding': 'Deal active, negative premium reflects market sentiment'
                                    }
                                )

                        investigator.close()

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Check if any issues have auto_fix='verify_old_deal_status'
                    old_deal_checks = [i for i in issues if i.get('auto_fix') == 'verify_old_deal_status']

                    if old_deal_checks:
                        # Special handling: Verify old deals (12+ months) haven't been terminated or replaced
                        print(f"\n[ORCHESTRATOR] Verifying {len(old_deal_checks)} old deal(s) (12+ months old)")

                        investigator = InvestigationAgent()
                        from utils.sec_filing_fetcher import SECFilingFetcher
                        sec_fetcher = SECFilingFetcher()

                        for issue in old_deal_checks:
                            ticker = issue['ticker']
                            context = issue.get('context', {})
                            cik = issue.get('metadata', {}).get('cik')
                            old_target = context.get('target')
                            days_old = context.get('days_since_announced', 0)

                            if not cik:
                                # Try to fetch missing CIK
                                cik = self._ensure_cik(ticker)
                                if not cik:
                                    print(f"   ⚠️  {ticker}: No CIK available and could not fetch it, skipping")
                                    continue

                            print(f"\n   Checking {ticker} → {old_target} ({int(days_old/30)} months old)...")

                            # Check last 12 months of filings for termination or new deal
                            result = investigator.investigate_deadline_extension(ticker, cik)

                            if result.get('termination_found'):
                                # Old deal was terminated
                                spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                if spac:
                                    # Archive old deal to history
                                    from database import DealHistory
                                    import json

                                    # Check if already in history
                                    existing = self.orchestrator_ref.db.query(DealHistory).filter(
                                        DealHistory.ticker == ticker,
                                        DealHistory.target_company == old_target
                                    ).first()

                                    if not existing:
                                        old_deal = DealHistory(
                                            ticker=ticker,
                                            cik=spac.cik,
                                            company_name=spac.company,
                                            target_company=old_target,
                                            announced_date=spac.announced_date,
                                            termination_date=datetime.now().date(),
                                            deal_status='TERMINATED',
                                            termination_reason=result.get('reason', 'Deal terminated - confirmed via SEC filing'),
                                            is_current=False,
                                            notes=f"Deal terminated after {int(days_old/30)} months without shareholder vote"
                                        )
                                        self.orchestrator_ref.db.add(old_deal)

                                    # Clear from main table
                                    spac.deal_status = 'SEARCHING'
                                    spac.target = None
                                    spac.announced_date = None
                                    self.orchestrator_ref.db.commit()

                                    print(f"   ✅ Archived terminated deal, cleared {ticker}")

                                    # Update queue conversation
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'deal_status': 'SEARCHING',
                                            'target': None,
                                            'archived_to_history': True
                                        }
                                    )

                            else:
                                # Check for NEW deal announcement in recent filings
                                print(f"   🔍 Checking for new deal announcements...")

                                # Get last 12 months of 8-K and 425 filings
                                recent_filings = []
                                for filing_type in ['8-K', '425']:
                                    filings = sec_fetcher.get_recent_filings(cik, filing_type, count=20)
                                    for filing in filings:
                                        # Check if filing is more recent than the old deal
                                        filing_date = filing.get('filing_date')
                                        if filing_date and filing_date > context.get('announced_date', '2000-01-01'):
                                            recent_filings.append(filing)

                                # Check each filing for new deal keywords
                                new_deal_found = False
                                for filing in recent_filings[:10]:  # Check most recent 10
                                    filing_url = filing.get('url')
                                    if filing_url:
                                        text = sec_fetcher.fetch_document(filing_url)
                                        if text:
                                            text_lower = text.lower()
                                            if any(kw in text_lower for kw in ['definitive agreement', 'merger agreement', 'business combination agreement']):
                                                # Extract new target (basic)
                                                if 'business combination' in text_lower and old_target.lower() not in text_lower:
                                                    print(f"   🎯 NEW DEAL FOUND in {filing.get('filing_date')} filing!")
                                                    print(f"      Filing: {filing_url}")
                                                    print(f"      ⚠️  Manual review needed - run deal detector on this filing")
                                                    new_deal_found = True

                                                    # Update queue conversation to flag for manual review
                                                    self._update_queue_conversation_final_fix(
                                                        ticker=ticker,
                                                        final_fix={
                                                            'status': 'new_deal_detected',
                                                            'filing_url': filing_url,
                                                            'action_needed': 'Run deal detector to extract new target'
                                                        }
                                                    )
                                                    break

                                if not new_deal_found:
                                    print(f"   ℹ️  No termination or new deal found - deal may still be active (slow progress)")

                                    # Update queue conversation
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'status': 'verified_active',
                                            'finding': 'Deal still active, no termination or replacement found'
                                        }
                                    )

                        investigator.close()
                        # SECFilingFetcher doesn't need cleanup

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Check if any issues have auto_fix='investigate_data_overwrite'
                    data_overwrite_checks = [i for i in issues if i.get('auto_fix') == 'investigate_data_overwrite']

                    if data_overwrite_checks:
                        # Special handling: Investigate suspicious data overwrites (stale data)
                        print(f"\n[ORCHESTRATOR] Investigating {len(data_overwrite_checks)} suspicious data overwrite(s)")

                        for issue in data_overwrite_checks:
                            ticker = issue['ticker']
                            context = issue.get('context', {})
                            red_flags = context.get('red_flags', [])
                            hours_after = context.get('hours_after_scrape', 0)

                            print(f"\n   Checking {ticker} (updated {hours_after:.1f}h after SEC scrape)...")
                            print(f"   Red flags: {', '.join(red_flags)}")

                            spac = self.orchestrator_ref.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                            if not spac:
                                continue

                            # Strategy: Check deal_history for correct data
                            from database import DealHistory

                            # Check if there's a recent deal in history that matches the filing URL
                            if spac.deal_filing_url:
                                correct_deal = self.orchestrator_ref.db.query(DealHistory).filter(
                                    DealHistory.ticker == ticker,
                                    DealHistory.is_current == True
                                ).first()

                                if correct_deal and correct_deal.target_company != spac.target:
                                    # Found correct target in history
                                    print(f"   ✅ Found correct target in deal_history: {correct_deal.target_company}")
                                    print(f"   🔄 Restoring from deal_history...")

                                    spac.target = correct_deal.target_company
                                    spac.deal_status = 'ANNOUNCED'
                                    spac.announced_date = correct_deal.announced_date
                                    self.orchestrator_ref.db.commit()

                                    print(f"   ✓ Restored {ticker} → {correct_deal.target_company}")

                                    # Update queue conversation
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'target': correct_deal.target_company,
                                            'deal_status': 'ANNOUNCED',
                                            'restored_from': 'deal_history'
                                        }
                                    )
                                else:
                                    # No history found - fetch from SEC filing
                                    print(f"   🔍 No deal_history found - checking SEC filing...")

                                    from utils.sec_filing_fetcher import SECFilingFetcher
                                    sec_fetcher = SECFilingFetcher()

                                    try:
                                        filing_text = sec_fetcher.fetch_document(spac.deal_filing_url)
                                        if filing_text:
                                            # Use AI to extract target name
                                            from investigation_agent import InvestigationAgent
                                            investigator = InvestigationAgent()

                                            # Simple extraction: look for "business combination with [Company]"
                                            import re
                                            pattern = r'(?:business combination|merger|acquisition)\s+(?:with|of)\s+([A-Z][A-Za-z\s&,\.]+?)(?:\s+\(|,|\.|;|$)'
                                            matches = re.findall(pattern, filing_text, re.IGNORECASE)

                                            if matches:
                                                extracted_target = matches[0].strip()
                                                print(f"   📋 Extracted target from filing: {extracted_target}")

                                                # Ask user to confirm
                                                print(f"   ⚠️  Manual review recommended")

                                                # Update queue conversation for manual review
                                                self._update_queue_conversation_final_fix(
                                                    ticker=ticker,
                                                    final_fix={
                                                        'status': 'needs_review',
                                                        'extracted_target': extracted_target,
                                                        'current_target': spac.target,
                                                        'action': 'Verify correct target and approve fix'
                                                    }
                                                )
                                            else:
                                                print(f"   ⚠️  Could not extract target from filing")

                                            investigator.close()
                                    except Exception as e:
                                        print(f"   ⚠️  Error fetching filing: {e}")

                            else:
                                # No filing URL - likely the deal was cleared incorrectly
                                print(f"   ℹ️  No deal_filing_url - data may have been legitimately cleared")

                                # Update queue conversation
                                self._update_queue_conversation_final_fix(
                                    ticker=ticker,
                                    final_fix={
                                        'status': 'investigated',
                                        'finding': 'No filing URL - overwrite may be legitimate clearing'
                                    }
                                )

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Check if any issues have auto_fix='investigate_trading_status'
                    trading_status_checks = [i for i in issues if i.get('auto_fix') == 'investigate_trading_status']

                    if trading_status_checks:
                        # Special handling: NULL price_change may indicate delisting/completion
                        print(f"\n[ORCHESTRATOR] Investigating {len(trading_status_checks)} trading status issue(s) (possible delisting/completion)")

                        investigator = InvestigationAgent()

                        for issue in trading_status_checks:
                            ticker = issue['ticker']
                            context = issue.get('context', {})
                            cik = issue.get('metadata', {}).get('cik')

                            if not cik:
                                # Try to fetch missing CIK
                                cik = self._ensure_cik(ticker)
                                if not cik:
                                    print(f"   ⚠️  {ticker}: No CIK available and could not fetch it, skipping")
                                    continue

                            print(f"\n   Checking {ticker} for delisting/completion...")

                            # Check for Form 25 (delisting notice) and completion indicators
                            from utils.sec_filing_fetcher import SECFilingFetcher
                            sec_fetcher = SECFilingFetcher()

                            try:
                                # Check for Form 25 in last 14 days
                                filings_25 = sec_fetcher.search_filings(cik, '25', count=5)

                                completion_found = False
                                form_25_date = None

                                for filing in filings_25:
                                    filing_date_obj = filing.get('date')
                                    if filing_date_obj:
                                        from datetime import datetime
                                        # Convert datetime to date if needed
                                        filing_date = filing_date_obj.date() if hasattr(filing_date_obj, 'date') else filing_date_obj
                                        days_ago = (datetime.now().date() - filing_date).days

                                        if days_ago <= 14:  # Filed in last 2 weeks
                                            print(f"   📋 Found Form 25 filed {days_ago} days ago ({filing_date})")
                                            completion_found = True
                                            form_25_date = filing_date
                                            break

                                if completion_found:
                                    # Update to COMPLETED
                                    from database import SessionLocal
                                    db = SessionLocal()
                                    spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                                    if spac:
                                        old_target = spac.target
                                        spac.deal_status = 'COMPLETED'
                                        spac.completion_date = form_25_date
                                        db.commit()
                                        db.close()

                                        print(f"   ✅ Updated {ticker} to COMPLETED (Form 25 filed {form_25_date})")

                                        # Update queue conversation
                                        self._update_queue_conversation_final_fix(
                                            ticker=ticker,
                                            final_fix={
                                                'deal_status': 'COMPLETED',
                                                'completion_date': form_25_date.isoformat() if hasattr(form_25_date, 'isoformat') else str(form_25_date),
                                                'detected_via': 'Form 25 delisting notice'
                                            }
                                        )

                                        # Send Telegram notification
                                        from utils.alert_deduplication import should_send_alert, mark_alert_sent
                                        if should_send_alert('deal_completion', ticker=ticker, dedup_hours=168):
                                            self.orchestrator_ref.agents['telegram'].execute(AgentTask(
                                                task_id=f"telegram_completion_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                                agent_name="telegram",
                                                task_type="send_alert",
                                                priority=TaskPriority.HIGH,
                                                status=TaskStatus.PENDING,
                                                created_at=datetime.now(),
                                                parameters={'alert_text': f"""🎉 <b>DEAL COMPLETED</b>

<b>Ticker:</b> {ticker}
<b>Target:</b> {old_target}
<b>Completion Date:</b> {form_25_date}

<b>Detection Method:</b> Form 25 delisting notice + NULL price_change_24h

Database updated to COMPLETED."""}
                                            ))
                                            mark_alert_sent('deal_completion', ticker=ticker)
                                else:
                                    # No Form 25 found - may be ticker change or other issue
                                    print(f"   ℹ️  No Form 25 found - may be ticker change, trading halt, or data issue")

                                    # Update queue conversation for manual investigation
                                    self._update_queue_conversation_final_fix(
                                        ticker=ticker,
                                        final_fix={
                                            'status': 'needs_investigation',
                                            'finding': 'NULL price_change but no Form 25 - check for ticker change or trading halt'
                                        }
                                    )

                            except Exception as e:
                                print(f"   ⚠️  Error checking Form 25: {e}")

                        investigator.close()

                        # Skip regular alert workflow for these - we handled them
                        continue

                    # Build anomaly data for regular issues
                    first_issue = issues[0]
                    anomaly = {
                        'type': anomaly_type,
                        'severity': 'CRITICAL',
                        'count': len(issues),
                        'description': f"{len(issues)} SPACs have {anomaly_type.replace('_', ' ')} issues",
                        'affected_spacs': [issue['ticker'] for issue in issues],  # All affected
                        'evidence': [
                            {
                                'ticker': issue['ticker'],
                                'field': issue.get('field'),
                                'current_value': str(issue.get('actual', ''))[:100],
                                'issue': issue.get('message', '')[:200]
                            }
                            for issue in issues  # All issues (chunking will split if needed)
                        ]
                    }

                    # Use Investigation Agent for AI analysis
                    investigator = InvestigationAgent()
                    context = {
                        'system': 'data_validator',
                        'total_spacs_affected': len(issues),
                        'issue_severity': 'CRITICAL'
                    }

                    hypotheses = investigator.generate_hypotheses(anomaly, context)
                    investigator.close()

                    # Build Telegram alert
                    top_hypothesis = hypotheses[0] if hypotheses else {}

                    message = f"""🔍 <b>DATA QUALITY ISSUE DETECTED</b>

<b>Issue Type:</b> {anomaly_type.replace('_', ' ').title()}
<b>Affected SPACs:</b> {len(issues)}
<b>Severity:</b> CRITICAL

📊 <b>AI Analysis</b> (Confidence: {top_hypothesis.get('likelihood', 0)}%)
<b>Root Cause:</b> {top_hypothesis.get('root_cause', 'Unknown')[:200]}

🔧 <b>Suggested Fix:</b>
{top_hypothesis.get('fix', 'Manual investigation required')[:300]}

📋 <b>Affected Tickers ({len(anomaly['evidence'])} total):</b>
{chr(10).join([f"• {ev['ticker']}: {ev['issue'][:80]}" for ev in anomaly['evidence']])}

✅ <b>Action Plan:</b>
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(top_hypothesis.get('prevention', ['Manual review required'])[:3])])}

Reply with: "APPROVE {anomaly_type}" to auto-fix, "SKIP" to ignore, "MANUAL" for manual review
"""

                    # Check if this alert was already sent recently (deduplication)
                    from utils.alert_deduplication import should_send_alert, mark_alert_sent

                    # Build alert key from affected tickers
                    alert_key = '_'.join(sorted([issue['ticker'] for issue in issues]))

                    if not should_send_alert(
                        alert_type='data_quality_issue',
                        ticker=None,  # Multi-ticker alert
                        alert_key=f"{anomaly_type}_{alert_key}",
                        dedup_hours=24
                    ):
                        print(f"   ⏭️  Skipping duplicate alert for {anomaly_type} (sent within 24h)")
                        continue

                    # Send Telegram alert via orchestrator's TelegramAgent
                    telegram_task = AgentTask(
                        task_id=f"telegram_dq_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="telegram",
                        task_type="send_alert",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'alert_text': message}
                    )

                    telegram_result = self.orchestrator_ref.agents['telegram'].execute(telegram_task)

                    if telegram_result.status == TaskStatus.COMPLETED:
                        print(f"   📱 Telegram alert sent for {anomaly_type}")
                        # Mark as sent to prevent duplicates
                        mark_alert_sent(
                            alert_type='data_quality_issue',
                            ticker=None,
                            alert_key=f"{anomaly_type}_{alert_key}",
                            message_preview=message[:100]
                        )
                    else:
                        print(f"   ⚠️  Telegram alert failed: {telegram_result.error}")

                    # Save pending approval state for telegram_approval_listener
                    import json
                    approval_state_file = '/home/ubuntu/spac-research/.data_quality_approvals.json'

                    approval_state = {}
                    if os.path.exists(approval_state_file):
                        with open(approval_state_file, 'r') as f:
                            approval_state = json.load(f)

                    approval_id = f"{anomaly_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    approval_state[approval_id] = {
                        'anomaly_type': anomaly_type,
                        'issue_count': len(issues),
                        'affected_spacs': [issue['ticker'] for issue in issues],
                        'timestamp': datetime.now().isoformat(),
                        'fix_parameters': self._determine_fix_parameters(anomaly_type),
                        'status': 'pending'
                    }

                    with open(approval_state_file, 'w') as f:
                        json.dump(approval_state, f, indent=2)

                result['telegram_alerts_sent'] = len(issues_by_type)
                result['approval_workflow_initiated'] = True

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task

    def _update_queue_conversation_final_fix(self, ticker: str, final_fix: Dict):
        """
        Update the queue conversation's final_fix field after investigation completes

        This prevents the "approved fix corruption" bug where the queue conversation
        has the wrong final_fix (e.g., the expected value text instead of actual fix)
        """
        from sqlalchemy import text
        import json

        try:
            # Find most recent active queue conversation for this ticker
            query = text("""
                UPDATE data_quality_conversations
                SET final_fix = :final_fix,
                    proposed_fix = :final_fix
                WHERE ticker = :ticker
                  AND status = 'active'
                  AND issue_id LIKE 'queue_issue_%'
                  AND completed_at IS NULL
            """)

            self.orchestrator_ref.db.execute(query, {
                'ticker': ticker,
                'final_fix': json.dumps(final_fix)
            })
            self.orchestrator_ref.db.commit()

            print(f"   ✓ Updated queue conversation final_fix for {ticker}")
        except Exception as e:
            print(f"   ⚠️  Could not update queue conversation final_fix: {e}")
            self.orchestrator_ref.db.rollback()

    def _verify_deal_filing_content(self, filing_text: str, target: str) -> bool:
        """
        Verify if SEC filing contains a real business combination announcement

        Returns:
            True if filing contains definitive agreement keywords (more lenient)
            False if filing is an extension, termination, or other non-deal event
        """
        filing_lower = filing_text.lower()

        # Red flags: NOT a business combination (immediate rejection)
        false_positive_keywords = [
            'extension of time to complete',
            'extend the date by which',
            'termination of the business combination',
            'terminated the merger agreement',
            'business combination agreement has been terminated',
            'withdraw the registration statement',
            'entered into liquidation',
            'intends to dissolve',
            'notice of redemption'
        ]

        for keyword in false_positive_keywords:
            if keyword in filing_lower:
                print(f"         ❌ Red flag: '{keyword}'")
                return False

        # Positive signals: Real business combination
        # More comprehensive list of deal keywords
        deal_keywords = [
            'definitive agreement',
            'business combination agreement',
            'merger agreement',
            'entered into a business combination',
            'executed a definitive',
            'agreement and plan of merger',
            'closing of the business combination',
            'combination has been approved',
            'announce the signing',
            'transaction agreement',
            'entered into an agreement and plan'
        ]

        keyword_matches = 0
        matched_keywords = []
        for keyword in deal_keywords:
            if keyword in filing_lower:
                keyword_matches += 1
                matched_keywords.append(keyword)

        # Check if target company is mentioned
        target_mentioned = False
        if target and len(target) > 3:  # Avoid false positives from short names
            # Check multiple variations of target name
            target_variations = [
                target.lower(),
                target.lower().replace(',', ''),
                target.lower().replace('.', ''),
                target.lower().split()[0] if ' ' in target else target.lower()  # First word
            ]
            target_mentioned = any(var in filing_lower for var in target_variations)

        # More lenient decision logic:
        # - If red flags found: False (already checked above)
        # - If 1+ deal keywords: True (assume real unless red flags)
        # - If 0 deal keywords but target mentioned prominently (3+ times): True (filing exists but keywords may vary)
        # - Otherwise: False

        if keyword_matches >= 1:
            print(f"         ✅ Found {keyword_matches} deal keyword(s): {matched_keywords[0]}")
            return True
        elif target_mentioned and filing_lower.count(target.lower()[:10]) >= 3:
            print(f"         ✅ Target mentioned 3+ times (likely real deal despite missing keywords)")
            return True
        else:
            print(f"         ⚠️  No deal keywords found, target mentioned: {target_mentioned}")
            # Be conservative: if no keywords and target not mentioned, it's probably not a real deal
            return False
