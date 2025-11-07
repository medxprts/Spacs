#!/usr/bin/env python3
"""
SPAC AI Agent Orchestrator
Coordinates multiple specialized agents to autonomously monitor and analyze SPACs

Architecture:
- Orchestrator: Decides what tasks to run and when
- Specialized Agents: Execute specific tasks (deal detection, vote tracking, etc)
- State Manager: Tracks agent execution history and decisions
"""

import os
import sys
import json
import time
import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# AI Setup
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise Exception("DEEPSEEK_API_KEY required for agent orchestration")

AI_CLIENT = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


class TaskPriority(Enum):
    CRITICAL = 1  # Votes in <7 days, new deals detected
    HIGH = 2      # Deadline approaching, price anomalies
    MEDIUM = 3    # Regular price updates, Reddit monitoring
    LOW = 4       # Data enrichment, backfills


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentTask:
    """Represents a task for an agent to execute"""
    task_id: str
    agent_name: str
    task_type: str
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    parameters: Dict[str, Any] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self):
        data = asdict(self)
        data['priority'] = self.priority.value
        data['status'] = self.status.value
        data['created_at'] = self.created_at.isoformat()
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data


class StateManager:
    """Manages agent execution state and history"""

    def __init__(self, state_file: str = "/home/ubuntu/spac-research/agent_state.json"):
        self.state_file = state_file
        self.state = self.load_state()

    def load_state(self) -> Dict:
        """Load state from disk"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {
            'last_run': {},
            'task_history': [],
            'agent_stats': {},
            'decisions': []
        }

    def save_state(self):
        """Save state to disk"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def record_task(self, task: AgentTask):
        """Record task execution"""
        self.state['task_history'].append(task.to_dict())

        # Update agent stats
        if task.agent_name not in self.state['agent_stats']:
            self.state['agent_stats'][task.agent_name] = {
                'total_runs': 0,
                'successes': 0,
                'failures': 0,
                'avg_duration': 0
            }

        stats = self.state['agent_stats'][task.agent_name]
        stats['total_runs'] += 1

        if task.status == TaskStatus.COMPLETED:
            stats['successes'] += 1
        elif task.status == TaskStatus.FAILED:
            stats['failures'] += 1

        self.save_state()

    def get_last_run(self, agent_name: str, task_type: str) -> Optional[datetime]:
        """Get timestamp of last successful run for agent/task"""
        key = f"{agent_name}:{task_type}"
        last_run_str = self.state['last_run'].get(key)
        if last_run_str:
            return datetime.fromisoformat(last_run_str)
        return None

    def set_last_run(self, agent_name: str, task_type: str, timestamp: datetime):
        """Update last run timestamp"""
        key = f"{agent_name}:{task_type}"
        self.state['last_run'][key] = timestamp.isoformat()
        self.save_state()

    def record_decision(self, decision: Dict):
        """Record orchestrator decision"""
        decision['timestamp'] = datetime.now().isoformat()
        self.state['decisions'].append(decision)
        self.save_state()


class BaseAgent:
    """Base class for specialized agents"""

    def __init__(self, name: str, state_manager: StateManager):
        self.name = name
        self.state_manager = state_manager

    def execute(self, task: AgentTask) -> AgentTask:
        """Execute a task - to be implemented by subclasses"""
        raise NotImplementedError

    def _start_task(self, task: AgentTask):
        """Mark task as started"""
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()
        print(f"[{self.name}] Starting: {task.task_type}")

    def _complete_task(self, task: AgentTask, result: Dict):
        """Mark task as completed"""
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result = result
        self.state_manager.record_task(task)
        self.state_manager.set_last_run(self.name, task.task_type, task.completed_at)

        duration = (task.completed_at - task.started_at).total_seconds()
        print(f"[{self.name}] ✓ Completed in {duration:.1f}s")

    def _fail_task(self, task: AgentTask, error: str):
        """Mark task as failed"""
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.error = error
        self.state_manager.record_task(task)
        print(f"[{self.name}] ✗ Failed: {error}")


class FilingProcessorWrapper(BaseAgent):
    """Unified wrapper for FilingProcessor - handles all SEC filing types"""

    def execute(self, task: AgentTask) -> AgentTask:
        self._start_task(task)

        try:
            import asyncio
            from agents.filing_processor import FilingProcessor

            filing = task.parameters['filing']

            # Get SPAC ticker from CIK
            db = SessionLocal()
            spac = db.query(SPAC).filter(SPAC.cik == filing['cik']).first()

            if not spac:
                self._fail_task(task, f"SPAC not found for CIK {filing['cik']}")
                db.close()
                return task

            # Add ticker to filing dict
            filing['ticker'] = spac.ticker

            # Process filing with unified processor
            processor = FilingProcessor()
            result = asyncio.run(processor.process(filing))

            db.close()

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task


class SignalMonitorAgentWrapper(BaseAgent):
    """Monitors Reddit and News for SPAC deal signals (DISABLED - deprecated)"""

    def execute(self, task: AgentTask) -> AgentTask:
        self._start_task(task)

        # DISABLED: signal_monitor_agent deprecated, will be replaced by opportunity identification agent
        self._fail_task(task, "SignalMonitorAgent deprecated - use opportunity identification agent")
        return task

        # try:
        #     from signal_monitor_agent import SignalMonitorAgent
        #
        #     agent = SignalMonitorAgent()
        #
        #     # Get parameters
        #     reddit_days = task.parameters.get('reddit_days', 7) if task.parameters else 7
        #     news_days = task.parameters.get('news_days', 3) if task.parameters else 3
        #
        #     # Monitor all SPACs
        #     triggers = agent.monitor_all_spacs(
        #         reddit_days=reddit_days,
        #         news_days=news_days
        #     )
        #
        #     agent.close()
        #
        #     result = {
        #         'triggers_found': len(triggers),
        #         'triggers': triggers
        #     }
        #
        #     # If triggers found, send orchestrator notification
        #     if triggers:
        #         print(f"\n[SIGNAL MONITOR] 🚨 {len(triggers)} signal trigger(s) detected")
        #         for trigger in triggers:
        #             print(f"  • {trigger['ticker']}: {trigger['reason']} ({trigger['priority']})")
        #
        #     self._complete_task(task, result)
        #
        # except Exception as e:
        #     self._fail_task(task, str(e))
        #
        # return task


class TelegramAgentWrapper(BaseAgent):
    """Handles all Telegram communication for the platform"""

    def __init__(self, name: str, state_manager):
        super().__init__(name, state_manager)
        from telegram_agent import TelegramAgent
        self.telegram = TelegramAgent()

    def execute(self, task: AgentTask) -> AgentTask:
        self._start_task(task)

        try:
            task_type = task.task_type
            params = task.parameters or {}

            # Route to appropriate handler
            if task_type == 'send_message':
                # Send a simple message
                text = params.get('text', '')
                success = self.telegram.send_message(text)
                result = {'sent': success, 'message_length': len(text)}

            elif task_type == 'queue_validation_issues':
                # Queue validation issues for review
                issues = params.get('issues', [])
                result = self.telegram.queue_validation_issues(issues)

            elif task_type == 'send_alert':
                # Send alert message
                alert_text = params.get('alert_text', '')
                success = self.telegram.send_message(alert_text)
                result = {'alert_sent': success}

            elif task_type == 'wait_for_response':
                # Wait for user response
                timeout_minutes = params.get('timeout_minutes', 60)
                response = self.telegram.wait_for_response(timeout_minutes)
                result = {
                    'response_received': response is not None,
                    'response_text': response
                }

            else:
                raise ValueError(f"Unknown task type: {task_type}")

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task


class FilingAgentWrapper(BaseAgent):
    """
    Generic wrapper for filing-triggered agents
    Uses dispatch function to route to appropriate processor
    """

    def __init__(self, name: str, state_manager, dispatch_func):
        super().__init__(name, state_manager)
        self.dispatch_func = dispatch_func

    def execute(self, task: AgentTask) -> AgentTask:
        self._start_task(task)

        try:
            filing = task.parameters.get('filing', {})
            classification = task.parameters.get('classification', {})

            # Call the dispatch function specific to this agent
            result = self.dispatch_func(filing, classification)

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task


# Wrapper classes for existing filing agents (for backward compatibility)
class VoteExtractorAgentWrapper(FilingAgentWrapper):
    def __init__(self, name: str, state_manager):
        super().__init__(name, state_manager, None)
        # Placeholder - original implementation

class MergerProxyExtractorWrapper(FilingAgentWrapper):
    def __init__(self, name: str, state_manager):
        super().__init__(name, state_manager, None)
        # Placeholder - original implementation

class TenderOfferProcessorWrapper(FilingAgentWrapper):
    def __init__(self, name: str, state_manager):
        super().__init__(name, state_manager, None)
        # Placeholder - original implementation


class Orchestrator:
    """
    Main orchestrator that decides what tasks to run and when
    Uses AI to make intelligent scheduling decisions
    """

    def __init__(self):
        self.state_manager = StateManager()

        # Scheduled agents (run on timer)
        # Import all agents from /agents/ folder
        from web_research_agent import WebResearchAgentWrapper
        from agents.price_monitor_agent import PriceMonitorAgent
        from agents.risk_analysis_agent import RiskAnalysisAgent
        from agents.deal_hunter_agent import DealHunterAgent
        from agents.vote_tracker_agent import VoteTrackerAgent
        from agents.deadline_extension_agent import DeadlineExtensionAgent
        from agents.data_validator_agent import DataValidatorAgent
        from agents.data_quality_fixer_agent import DataQualityFixerAgent
        from agents.pre_ipo_duplicate_checker_agent import PreIPODuplicateCheckerAgent
        from agents.premium_alert_agent import PremiumAlertAgent

        self.agents = {
            'deal_hunter': DealHunterAgent('deal_hunter', self.state_manager),
            'vote_tracker': VoteTrackerAgent('vote_tracker', self.state_manager),
            'price_monitor': PriceMonitorAgent('price_monitor', self.state_manager),
            'risk_analysis': RiskAnalysisAgent('risk_analysis', self.state_manager),
            'deadline_extension': DeadlineExtensionAgent('deadline_extension', self.state_manager),
            'data_validator': DataValidatorAgent('data_validator', self.state_manager),
            'data_quality_fixer': DataQualityFixerAgent('data_quality_fixer', self.state_manager),
            'pre_ipo_duplicate_checker': PreIPODuplicateCheckerAgent('pre_ipo_duplicate_checker', self.state_manager),
            'premium_alert': PremiumAlertAgent('premium_alert', self.state_manager),
            'web_research': WebResearchAgentWrapper('web_research', self.state_manager),
            'signal_monitor': SignalMonitorAgentWrapper('signal_monitor', self.state_manager),
            'telegram': TelegramAgentWrapper('telegram', self.state_manager)
        }

        # Set orchestrator reference for agents that need to send Telegram alerts
        self.agents['data_validator'].orchestrator_ref = self
        self.agents['pre_ipo_duplicate_checker'].orchestrator_ref = self
        self.agents['premium_alert'].orchestrator_ref = self

        # Filing processor agents (triggered by SEC filings)
        self.filing_agents = {
            # Existing agents
            'VoteExtractor': VoteExtractorAgentWrapper('VoteExtractor', self.state_manager),
            'MergerProxyExtractor': MergerProxyExtractorWrapper('MergerProxyExtractor', self.state_manager),
            'TenderOfferProcessor': TenderOfferProcessorWrapper('TenderOfferProcessor', self.state_manager),

            # Deal-related agents
            'DealDetector': FilingAgentWrapper('DealDetector', self.state_manager, self._dispatch_deal_detector),
            'PipeExtractor': FilingAgentWrapper('PipeExtractor', self.state_manager, self._dispatch_pipe_extractor),
            'FilingProcessor': FilingAgentWrapper('FilingProcessor', self.state_manager, self._dispatch_filing_processor),

            # Trust account agents
            'TrustAccountProcessor': FilingAgentWrapper('TrustAccountProcessor', self.state_manager, self._dispatch_trust_processor),

            # Extension/redemption agents
            'ExtensionMonitor': FilingAgentWrapper('ExtensionMonitor', self.state_manager, self._dispatch_extension_monitor),
            'RedemptionExtractor': FilingAgentWrapper('RedemptionExtractor', self.state_manager, self._dispatch_redemption_extractor),

            # S-4 and proxy agents
            'S4Processor': FilingAgentWrapper('S4Processor', self.state_manager, self._dispatch_s4_processor),
            'ProxyProcessor': FilingAgentWrapper('ProxyProcessor', self.state_manager, self._dispatch_proxy_processor),

            # Critical event agents
            'DelistingDetector': FilingAgentWrapper('DelistingDetector', self.state_manager, self._dispatch_delisting_detector),
            'CompletionMonitor': FilingAgentWrapper('CompletionMonitor', self.state_manager, self._dispatch_completion_monitor),

            # Other agents (placeholders for future implementation)
            'IPODetector': FilingAgentWrapper('IPODetector', self.state_manager, self._dispatch_ipo_detector),
            'EffectivenessMonitor': FilingAgentWrapper('EffectivenessMonitor', self.state_manager, self._dispatch_effectiveness_monitor),
            'ComplianceMonitor': FilingAgentWrapper('ComplianceMonitor', self.state_manager, self._dispatch_compliance_monitor),
        }

        self.task_queue: List[AgentTask] = []
        self.db = SessionLocal()

    def _ensure_cik(self, ticker: str, spac: Optional[SPAC] = None) -> Optional[str]:
        """
        Auto-fetch and save missing CIK for a SPAC

        Args:
            ticker: SPAC ticker
            spac: Optional SPAC object (avoids extra DB query)

        Returns:
            CIK string if found, None otherwise
        """
        if spac is None:
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            print(f"   ⚠️  {ticker}: SPAC not found in database")
            return None

        if spac.cik:
            return spac.cik

        # CIK missing - try to fetch it
        print(f"   🔍 {ticker}: CIK missing, fetching from SEC...")

        try:
            from sec_data_scraper import SPACDataEnricher
            scraper = SPACDataEnricher()
            cik = scraper.get_cik(spac.company)

            if cik:
                print(f"   ✅ {ticker}: Found CIK {cik}, saving to database")
                spac.cik = cik
                self.db.commit()
                return cik
            else:
                print(f"   ❌ {ticker}: Could not find CIK for '{spac.company}'")
                return None

        except Exception as e:
            print(f"   ❌ {ticker}: Error fetching CIK: {e}")
            return None

    def research_and_enhance_issues(self, issues: List[Dict]) -> List[Dict]:
        """
        Research validation issues using Web Research Agent and enhance with findings

        Args:
            issues: List of validation issues from Data Validator

        Returns:
            List of enhanced issues with research findings attached
        """
        print(f"\n[ORCHESTRATOR] 🔍 Researching {len(issues)} validation issues...")

        # Issues that should trigger web research
        RESEARCH_TRIGGERS = [
            'Suspicious Data Overwrite',
            'Deal Status → Target Consistency',
            'False Positive Deal Detection',
            'Missing Target'
        ]

        enhanced_issues = []
        research_count = 0

        for issue in issues:
            rule = issue.get('rule', '')

            # Check if this issue type needs web research
            if any(trigger in rule for trigger in RESEARCH_TRIGGERS):
                print(f"\n   🌐 Researching: {issue.get('ticker')} - {rule}")

                try:
                    # Call Web Research Agent
                    research_task = AgentTask(
                        task_id=f"web_research_{issue.get('ticker')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="web_research",
                        task_type="investigate_issue",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'issue': issue}
                    )

                    result_task = self.agents['web_research'].execute(research_task)

                    if result_task.status == TaskStatus.COMPLETED:
                        research_findings = result_task.result

                        # Enhance issue with research findings
                        issue['research_findings'] = research_findings.get('research_findings', '')
                        issue['suggested_fix'] = research_findings.get('suggested_fix', '')
                        issue['research_confidence'] = research_findings.get('confidence', 0)
                        issue['sec_verified'] = research_findings.get('sec_verified', False)
                        issue['sec_filing_url'] = research_findings.get('sec_filing_url')
                        issue['research_sources'] = research_findings.get('sources', [])
                        issue['research_reasoning'] = research_findings.get('reasoning', '')

                        research_count += 1
                        print(f"      ✅ Research complete ({research_findings.get('confidence', 0)}% confidence)")

                        if research_findings.get('sec_verified'):
                            print(f"      ✅ SEC verified")

                    else:
                        print(f"      ⚠️  Research failed: {result_task.error}")
                        issue['research_findings'] = 'Research failed - manual review needed'
                        issue['research_confidence'] = 0

                except Exception as e:
                    print(f"      ❌ Research error: {e}")
                    issue['research_findings'] = f'Research error: {e}'
                    issue['research_confidence'] = 0

            enhanced_issues.append(issue)

        print(f"\n[ORCHESTRATOR] ✅ Enhanced {research_count}/{len(issues)} issues with web research\n")

        return enhanced_issues

    def _detect_anomalies(self, research_result: Dict, research_request: Dict) -> List[Dict]:
        """
        Quick anomaly detection to decide if investigation needed

        Returns:
            List of anomalies (empty if none detected)
        """
        anomalies = []

        # Check temporal inconsistency
        if research_result.get('deal_found') and research_result.get('announced_date'):
            # Get SPAC IPO date
            db = SessionLocal()
            spac = db.query(SPAC).filter(SPAC.ticker == research_request['ticker']).first()

            if spac and spac.ipo_date:
                deal_date = research_result['announced_date']

                if isinstance(deal_date, datetime) and isinstance(spac.ipo_date, datetime):
                    years_gap = (spac.ipo_date - deal_date).days / 365.25

                    if years_gap > 2:
                        # Deal announced >2 years before IPO = anomaly!
                        anomalies.append({
                            'type': 'temporal_inconsistency',
                            'severity': 'CRITICAL',
                            'gap_years': years_gap
                        })

            db.close()

        return anomalies

    def _build_investigation_context(self, research_request: Dict) -> Dict:
        """Build context dict for investigation agent"""

        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == research_request['ticker']).first()

        context = {
            'ticker': research_request['ticker'],
            'cik': research_request.get('cik'),
            'company': spac.company if spac else None,
            'ipo_date': spac.ipo_date if spac else None,
            'deal_status': spac.deal_status if spac else None,
            'database_company_name': spac.company if spac else None
        }

        db.close()

        return context

    # ========================================================================
    # Filing Content Fetching (Optimization)
    # ========================================================================

    def _fetch_filing_content(self, url: str) -> Optional[str]:
        """
        Fetch filing content from SEC URL INCLUDING key exhibits

        OPTIMIZATION: Called once when multiple agents need same filing
        Prevents redundant downloads (e.g., 8-K with 3 agents = 3 downloads → 1 download)

        ENHANCEMENT: Also fetches key exhibits (99.1, 10.1, 2.1) which often contain
        the most important details:
        - Exhibit 99.1: Press releases (deal announcements, redemption results)
        - Exhibit 10.1: Material agreements (business combination agreements)
        - Exhibit 2.1: Merger agreements

        Returns combined content: main filing + key exhibits
        """
        if not url:
            return None

        try:
            import requests
            from utils.sec_filing_fetcher import SECFilingFetcher

            # Use SECFilingFetcher for consistent handling
            fetcher = SECFilingFetcher()

            # Extract document URL from index page
            doc_url = fetcher.extract_document_url(url)
            if not doc_url:
                print(f"      ⚠️  Could not extract document URL from {url}")
                return None

            # Fetch main document content
            content = fetcher.fetch_document(doc_url)
            if not content:
                return None

            # Extract exhibits from filing index
            exhibits = fetcher.extract_exhibits(url)

            # Key exhibits to fetch (these typically contain detailed information)
            key_exhibit_numbers = ['99.1', '10.1', '2.1', '99.2', '10.2']

            if exhibits:
                print(f"      📎 Found {len(exhibits)} exhibits")

                # Fetch key exhibits and append to content
                for exhibit in exhibits:
                    if exhibit['exhibit_number'] in key_exhibit_numbers:
                        print(f"         → Fetching Exhibit {exhibit['exhibit_number']}: {exhibit['description'][:60]}...")
                        exhibit_content = fetcher.fetch_document(exhibit['url'])

                        if exhibit_content:
                            # Append exhibit to combined content with clear delimiter
                            content += f"\n\n{'='*80}\n"
                            content += f"EXHIBIT {exhibit['exhibit_number']}: {exhibit['description']}\n"
                            content += f"{'='*80}\n\n"
                            content += exhibit_content
                            print(f"         ✓ Exhibit {exhibit['exhibit_number']} fetched ({len(exhibit_content):,} chars)")

            return content

        except Exception as e:
            print(f"      ⚠️  Error fetching filing content: {e}")
            return None

    def _retry_comprehensive_extraction(self, ticker: str):
        """
        Retry comprehensive 424B4 extraction for SPAC missing data

        Called opportunistically whenever we see ANY filing from a SPAC that needs extraction.
        This ensures data gets filled in within days rather than waiting for manual intervention.
        """
        try:
            import subprocess
            from datetime import datetime

            # Run extractor as subprocess (non-blocking)
            result = subprocess.run(
                ['python3', '/home/ubuntu/spac-research/agents/comprehensive_424b4_extractor.py', '--ticker', ticker],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Update database
            db = SessionLocal()
            try:
                spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if spac:
                    # Check if data is now complete
                    data_complete = (
                        spac.founder_shares is not None and
                        spac.shares_outstanding_base is not None and
                        spac.banker is not None
                    )

                    if data_complete:
                        print(f"   ✅ Extraction complete - {ticker} now has all data")
                        spac.comprehensive_extraction_needed = False
                    else:
                        print(f"   ⚠️  Still missing data - will retry on next filing")
                        spac.comprehensive_extraction_attempts = (spac.comprehensive_extraction_attempts or 0) + 1

                    spac.last_extraction_attempt = datetime.now()
                    db.commit()
            finally:
                db.close()

        except Exception as e:
            print(f"   ❌ Extraction retry failed: {e}")

    def _analyze_filing_relevance(self, content: str, agents_needed: List[str], classification: Dict, filing: Dict) -> Dict[str, bool]:
        """
        Use AI to analyze if filing contains pertinent information for each agent

        OPTIMIZATION: Prevents agents from processing irrelevant filings
        - Creates intelligent summary of filing
        - Determines which agents actually need to process it
        - Returns relevance map: {agent_name: bool}

        Example:
        - 8-K Item 5.03 (extension) → ExtensionMonitor: True, DealDetector: False
        - 8-K Item 1.01 (deal) → DealDetector: True, ExtensionMonitor: False
        """
        if not content or not agents_needed:
            # Default: all agents relevant (safe fallback)
            return {agent: True for agent in agents_needed}

        try:
            # Smart content sampling: Get beginning + exhibits if present
            # Strategy: First 5000 chars (main filing summary) + exhibit sections
            content_sample = ""

            # Check if content contains exhibits (appended by _fetch_filing_content)
            if "EXHIBIT " in content:
                # Split into main filing and exhibits
                parts = content.split("="*80)
                main_filing = parts[0][:5000] if len(parts[0]) > 5000 else parts[0]
                content_sample = main_filing

                # Add exhibit sections (these often have the key details)
                for part in parts[1:]:
                    if "EXHIBIT " in part:
                        # Add first 2000 chars of each exhibit
                        exhibit_sample = part[:2000] if len(part) > 2000 else part
                        content_sample += "\n" + "="*80 + "\n" + exhibit_sample

                # Limit total sample size
                if len(content_sample) > 15000:
                    content_sample = content_sample[:15000]
            else:
                # No exhibits, just use first 8000 chars
                content_sample = content[:8000] if len(content) > 8000 else content

            # Build agent descriptions for AI
            agent_descriptions = {
                'DealDetector': 'Detects deal announcements - looks for business combination agreements, merger terms, target companies, deal values',
                'PipeExtractor': 'Extracts PIPE financing data from deal announcements - institutional investment amounts, prices, lock-up terms',
                'TrustAccountProcessor': 'Extracts trust account financial data - balance sheets, trust cash, shares outstanding from 10-Q/10-K',
                'ExtensionMonitor': 'Detects deadline extensions - charter amendments, new termination dates, sponsor deposits',
                'RedemptionExtractor': 'Extracts redemption data from all filings - 8-K votes, DEFM14A proxies, 10-Q notes, extensions',
                'S4Processor': 'Analyzes S-4 merger registrations - detailed deal structure, pro forma financials',
                'ProxyProcessor': 'Processes proxy materials - shareholder vote dates, deal terms, management recommendations',
                'DelistingDetector': 'Detects delisting events - Form 25 filings indicating liquidation or completion',
                'CompletionMonitor': 'Detects deal closings - completion of acquisition, final share counts',
                'FilingProcessor': 'Processes proxy statements and tender offers - vote details, deal terms',
                'IPODetector': 'Detects IPO closings (424B4) for pre-IPO SPACs - graduates SPACs to main pipeline when IPO completes',
                'EffectivenessMonitor': 'Tracks S-4 effectiveness - when merger registration becomes effective',
                'ComplianceMonitor': 'Monitors compliance issues - late filing notices, accounting changes'
            }

            agents_list = '\n'.join([f"- {agent}: {agent_descriptions.get(agent, 'Specialized filing processor')}"
                                      for agent in agents_needed])

            prompt = f"""Analyze this SEC filing to determine which agents need to process it.

Filing Type: {filing.get('type', 'Unknown')}
Filing Summary: {filing.get('summary', 'N/A')}
Classification Priority: {classification.get('priority', 'MEDIUM')}
Classification Reason: {classification.get('reason', 'N/A')}

IMPORTANT: This content includes the main filing summary AND key exhibits (99.1, 10.1, 2.1).
8-K exhibits often contain the most detailed information:
- Exhibit 99.1: Press releases (deal announcements, redemption results)
- Exhibit 10.1: Material agreements (business combination terms)
- Exhibit 2.1: Merger agreements (detailed deal structure)

Filing Content (main filing + exhibits):
{content_sample}

Agents to evaluate:
{agents_list}

For EACH agent listed above, determine if this filing (including exhibits) contains pertinent information that the agent should process.

Respond with ONLY valid JSON in this exact format:
{{
    "summary": "Brief 1-2 sentence summary of filing content",
    "relevance": {{
        "AgentName1": true,
        "AgentName2": false,
        ...
    }},
    "reasoning": {{
        "AgentName1": "Why this agent should/shouldn't process",
        "AgentName2": "Why this agent should/shouldn't process",
        ...
    }}
}}

Be conservative - if unsure, mark as true (let agent process). Only mark false if clearly irrelevant."""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a SEC filing analysis expert. Analyze filings and determine agent relevance. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )

            response_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                # Remove ```json and ``` markers
                lines = response_text.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                response_text = '\n'.join(lines).strip()

            # Parse JSON response
            try:
                analysis = json.loads(response_text)
                relevance_map = analysis.get('relevance', {})

                print(f"   🤖 AI Filing Analysis:")
                print(f"      Summary: {analysis.get('summary', 'N/A')}")
                print(f"      Relevant agents: {[k for k, v in relevance_map.items() if v]}")

                # Show reasoning for agents marked as irrelevant (interesting insight)
                for agent, relevant in relevance_map.items():
                    if not relevant:
                        reason = analysis.get('reasoning', {}).get(agent, 'No reason provided')
                        print(f"      ⊘ Skipping {agent}: {reason}")

                return relevance_map

            except json.JSONDecodeError as e:
                print(f"      ⚠️  AI response parsing failed: {e}")
                print(f"      Raw response: {response_text[:200]}...")
                # Default: all relevant (safe fallback)
                return {agent: True for agent in agents_needed}

        except Exception as e:
            print(f"      ⚠️  Error analyzing filing relevance: {e}")
            # Default: all relevant (safe fallback)
            return {agent: True for agent in agents_needed}

    # ========================================================================
    # Filing Agent Dispatch Methods
    # ========================================================================

    def _dispatch_deal_detector(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to DealDetector agent"""
        import asyncio
        from agents.deal_detector_agent import DealDetectorAgent

        ticker = filing.get('ticker')
        if not ticker:
            return {'success': False, 'error': 'No ticker in filing'}

        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        db.close()

        if not spac:
            return {'success': False, 'error': f'SPAC {ticker} not found'}

        agent = DealDetectorAgent()
        result = asyncio.run(agent.process(filing))

        if result:
            return {'success': True, 'findings': result}
        else:
            return {'success': False, 'findings': 'No deal detected'}

    def _dispatch_filing_processor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to FilingProcessor (DEFM14A, PREM14A, etc.)"""
        import asyncio
        from agents.filing_processor import FilingProcessor

        ticker = filing.get('ticker')
        if not ticker:
            return {'success': False, 'error': 'No ticker in filing'}

        processor = FilingProcessor()
        result = asyncio.run(processor.process(filing))

        return result if result else {'success': False, 'findings': 'No data extracted'}

    def _dispatch_trust_processor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to TrustAccountProcessor (10-Q, 10-K)"""
        import asyncio
        from agents.quarterly_report_extractor import QuarterlyReportExtractor

        ticker = filing.get('ticker')
        if not ticker:
            return {'success': False, 'error': 'No ticker in filing'}

        processor = QuarterlyReportExtractor()
        result = asyncio.run(processor.process_filing(filing, ticker))

        return result if result else {'success': False, 'findings': 'No trust data extracted'}

    def _dispatch_extension_monitor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to ExtensionMonitor"""
        from agents.extension_monitor_agent import ExtensionMonitorAgent

        ticker = filing.get('ticker')
        if not ticker:
            return {'success': False, 'error': 'No ticker in filing'}

        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        db.close()

        if not spac:
            return {'success': False, 'error': f'SPAC {ticker} not found'}

        agent = ExtensionMonitorAgent()
        result = agent.check_extension(
            cik=spac.cik,
            filing={'type': filing['type'], 'date': filing['date'], 'url': filing['url']}
        )

        return result if result else {'success': False, 'findings': 'No extension detected'}

    def _dispatch_redemption_extractor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to RedemptionExtractor"""
        try:
            from agents.redemption_extractor import RedemptionExtractor

            ticker = filing.get('ticker')
            if not ticker:
                return {'success': False, 'error': 'No ticker in filing'}

            extractor = RedemptionExtractor()

            # Run async extraction using asyncio
            import asyncio
            if asyncio.get_event_loop().is_running():
                # If already in event loop, create task
                result = asyncio.ensure_future(extractor.process(filing))
            else:
                # Create new event loop
                result = asyncio.run(extractor.process(filing))

            return result if result else {'success': False, 'findings': 'No redemption data'}
        except ImportError as e:
            return {'success': False, 'error': f'RedemptionExtractor not available: {e}'}

    def _dispatch_pipe_extractor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to PipeExtractor"""
        try:
            from agents.pipe_extractor_agent import PIPEExtractorAgent
            import asyncio

            ticker = filing.get('ticker')
            if not ticker:
                return {'success': False, 'error': 'No ticker in filing'}

            extractor = PIPEExtractorAgent()

            # Run async extraction
            if asyncio.get_event_loop().is_running():
                result = asyncio.ensure_future(extractor.process_filing(filing, ticker))
            else:
                result = asyncio.run(extractor.process_filing(filing, ticker))

            return result if result else {'success': False, 'findings': 'No PIPE data'}
        except ImportError as e:
            return {'success': False, 'error': f'PipeExtractor not available: {e}'}

    def _dispatch_s4_processor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to S4Processor"""
        try:
            from s4_scraper import S4Scraper
            ticker = filing.get('ticker')
            if not ticker:
                return {'success': False, 'error': 'No ticker in filing'}

            scraper = S4Scraper()
            result = scraper.scrape_s4(ticker, filing['url'])

            return result if result else {'success': False, 'findings': 'No S-4 data extracted'}
        except ImportError:
            return {'success': False, 'error': 'S4Processor not available'}

    def _dispatch_proxy_processor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to ProxyProcessor"""
        try:
            from proxy_scraper import ProxyScraper
            ticker = filing.get('ticker')
            if not ticker:
                return {'success': False, 'error': 'No ticker in filing'}

            scraper = ProxyScraper()
            result = scraper.scrape_proxy(ticker, filing['url'])

            return result if result else {'success': False, 'findings': 'No proxy data extracted'}
        except ImportError:
            return {'success': False, 'error': 'ProxyProcessor not available'}

    def _dispatch_delisting_detector(self, filing: Dict, classification: Dict) -> Dict:
        """
        Detect delisting from Form 25

        Form 25 indicates:
        - Voluntary delisting
        - Liquidation
        - Merger completion
        """
        ticker = filing.get('ticker')
        if not ticker:
            return {'success': False, 'error': 'No ticker in filing'}

        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            db.close()
            return {'success': False, 'error': f'SPAC {ticker} not found'}

        # Determine delisting reason
        summary_lower = filing.get('summary', '').lower()
        title_lower = filing.get('title', '').lower()

        if 'merger' in summary_lower or 'combination' in summary_lower or 'acquisition' in summary_lower:
            reason = 'COMPLETED'
            message = f"✅ {ticker} - Deal completed (Form 25 filed)"
        elif 'liquidat' in summary_lower or 'dissolv' in summary_lower:
            reason = 'LIQUIDATED'
            message = f"⚠️  {ticker} - Liquidating (Form 25 filed)"
        else:
            reason = 'DELISTED'
            message = f"⚠️  {ticker} - Delisting (Form 25 filed)"

        old_status = spac.deal_status
        spac.deal_status = reason
        db.commit()
        db.close()

        # Send alert via orchestrator's TelegramAgent
        telegram_task = AgentTask(
            task_id=f"telegram_delist_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            agent_name="telegram",
            task_type="send_alert",
            priority=TaskPriority.HIGH,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            parameters={'alert_text': f"{message}\nPrevious status: {old_status}"}
        )

        self.agents['telegram'].execute(telegram_task)

        return {
            'success': True,
            'findings': f'Delisting detected: {reason}',
            'old_status': old_status,
            'new_status': reason
        }

    def _dispatch_completion_monitor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to CompletionMonitor (deal closing detector)"""
        import asyncio
        from agents.completion_monitor_agent import CompletionMonitorAgent

        try:
            agent = CompletionMonitorAgent()

            # Run async agent in sync context
            result = asyncio.run(agent.process(filing))

            if result:
                return {
                    'success': True,
                    'closing_date': result.get('closing_date'),
                    'new_ticker': result.get('new_ticker'),
                    'shares_redeemed': result.get('shares_redeemed'),
                    'findings': f"Deal completion detected - {result.get('target', 'Unknown target')}"
                }
            else:
                return {
                    'success': False,
                    'findings': 'No deal closing detected in this filing'
                }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _dispatch_ipo_detector(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to IPODetector agent for 424B4 filings (IPO close)"""
        import asyncio
        from agents.ipo_detector_agent import IPODetectorAgent

        try:
            agent = IPODetectorAgent()

            # Run async agent in sync context
            result = asyncio.run(agent.execute(filing))

            agent.close()

            if result:
                return {
                    'success': True,
                    'action': result.get('action'),
                    'ticker': result.get('ticker'),
                    'ipo_date': result.get('ipo_date'),
                    'agent': 'IPODetector'
                }
            else:
                return {
                    'success': False,
                    'error': 'No pre-IPO SPAC found for this CIK or already graduated'
                }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _dispatch_effectiveness_monitor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to EffectivenessMonitor (S-4 effectiveness)"""
        return {'success': False, 'error': 'EffectivenessMonitor not implemented yet'}

    def _dispatch_compliance_monitor(self, filing: Dict, classification: Dict) -> Dict:
        """Dispatch to ComplianceMonitor (late filings)"""
        return {'success': False, 'error': 'ComplianceMonitor not implemented yet'}

    # ========================================================================
    # End Filing Agent Dispatch Methods
    # ========================================================================

    def research_issue(self, research_request: Dict) -> Optional[Dict]:
        """
        Research a data validation issue by dispatching to specialized agents

        Called by DataValidatorAgent when it encounters low-confidence fixes.
        Orchestrator decides which agent to use for research, dispatches it,
        and returns the research results.

        Args:
            research_request: Dict with:
                - ticker: SPAC ticker
                - cik: CIK number
                - issue: Issue details
                - fix_type: Type of fix needed
                - confidence: Confidence level
                - reason: Why low confidence

        Returns:
            Research result dict with:
                - deal_found: True/False
                - target: Company name or None
                - announced_date: Date or None
                - source_filing: 8-K URL
                - agent: Which agent did the research
                - filings_checked: Number of filings reviewed
        """
        print(f"[ORCHESTRATOR] Researching {research_request['ticker']} - {research_request['fix_type']}")
        print(f"   Reason: {research_request['reason']}")

        fix_type = research_request['fix_type']

        try:
            if fix_type in ['set_status_to_SEARCHING', 'set_status_to_ANNOUNCED']:
                # Need to check for deal announcements in 8-Ks
                print(f"   → Dispatching DealDetector to check 8-K filings...")

                from deal_monitor_enhanced import EnhancedDealDetector

                detector = EnhancedDealDetector(use_ai_validation=True)

                # Search for deal announcements
                cik = research_request.get('cik')
                if not cik:
                    # Get CIK from database
                    db = SessionLocal()
                    spac = db.query(SPAC).filter(SPAC.ticker == research_request['ticker']).first()
                    cik = spac.cik if spac else None
                    db.close()

                if not cik:
                    print(f"   ⚠️  No CIK found for {research_request['ticker']}, cannot research")
                    return None

                # Check recent 8-Ks for deal announcements
                from utils.sec_filing_fetcher import SECFilingFetcher

                sec_fetcher = SECFilingFetcher()
                eight_ks = sec_fetcher.search_filings(
                    cik=cik,
                    filing_type='8-K',
                    count=20  # Check last 20 filings
                )

                filings_checked = len(eight_ks)
                deal_found = False
                target = None
                announced_date = None
                source_filing = None

                # Scan for deal announcement keywords
                for filing in eight_ks:
                    doc_url = sec_fetcher.extract_document_url(filing['url'])
                    if not doc_url:
                        continue

                    doc_content = sec_fetcher.fetch_document(doc_url)
                    if not doc_content:
                        continue

                    # Check for deal announcement keywords
                    content_lower = doc_content.lower()
                    if any(keyword in content_lower for keyword in [
                        'definitive agreement',
                        'business combination agreement',
                        'entered into an agreement and plan of merger',
                        'merger agreement'
                    ]):
                        # Found a deal announcement!
                        deal_found = True
                        announced_date = filing['date']
                        source_filing = filing['url']

                        # Try to extract target company name using AI
                        # DISABLED: signal_monitor_agent deprecated
                        # TODO: Replace with direct AI extraction
                        try:
                            # from signal_monitor_agent import SignalMonitorAgent
                            # signal_agent = SignalMonitorAgent()
                            #
                            # # Create article-like dict for AI verification
                            # article = {
                            #     'title': f"8-K Filing for {research_request['ticker']}",
                            #     'description': doc_content[:2000],  # First 2000 chars
                            #     'content': doc_content[:4000]  # First 4000 chars
                            # }
                            #
                            # verification = signal_agent.verify_deal_news_with_ai(
                            #     research_request['ticker'],
                            #     article
                            # )
                            #
                            # if verification.get('target_name'):

                            # Simplified extraction without SignalMonitorAgent
                            verification = {'target_name': None, 'confidence': 0}
                            target = None
                            if False:  # Disabled AI extraction
                                target = verification['target_name']
                                print(f"   🤖 AI extracted target: {target}")

                            # signal_agent.close()
                        except Exception as e:
                            print(f"   ⚠️  AI extraction failed: {e}")
                            target = None

                        if not target:
                            # Fallback to regex extraction
                            import re
                            # Look for common patterns like "merger with XYZ Inc."
                            patterns = [
                                r'business combination with ([A-Z][A-Za-z\s&,\.]+(?:Inc|Corp|LLC|Ltd))',
                                r'merge with ([A-Z][A-Za-z\s&,\.]+(?:Inc|Corp|LLC|Ltd))',
                                r'acquisition of ([A-Z][A-Za-z\s&,\.]+(?:Inc|Corp|LLC|Ltd))'
                            ]
                            for pattern in patterns:
                                match = re.search(pattern, doc_content)
                                if match:
                                    target = match.group(1).strip()
                                    break

                        print(f"   ✓ Deal found in 8-K filed {announced_date.date()}")
                        if target:
                            print(f"   ✓ Target: {target}")
                        break

                # SECFilingFetcher doesn't need cleanup
                detector.close()

                if deal_found:
                    print(f"   → Research complete: DEAL FOUND")
                else:
                    print(f"   → Research complete: NO DEAL (checked {filings_checked} 8-Ks)")

                research_result = {
                    'deal_found': deal_found,
                    'target': target,
                    'announced_date': announced_date,
                    'source_filing': source_filing,
                    'agent': 'deal_detector',
                    'filings_checked': filings_checked
                }

                # NEW: Check for anomalies and trigger investigation if needed
                if deal_found:
                    anomalies = self._detect_anomalies(research_result, research_request)

                    if anomalies:
                        print(f"\n   🔍 Anomaly detected - triggering Investigation Agent...")

                        from investigation_agent import InvestigationAgent

                        investigator = InvestigationAgent()

                        # Build context for investigation
                        context = self._build_investigation_context(research_request)

                        # Run investigation
                        investigation_report = investigator.investigate(
                            issue=research_request,
                            research_result=research_result,
                            context=context
                        )

                        investigator.close()

                        if investigation_report:
                            # Investigation succeeded and applied fix!
                            return investigation_report

                return research_result

            else:
                # Other fix types - not yet implemented
                print(f"   ⚠️  Research for {fix_type} not yet implemented")
                return None

        except Exception as e:
            print(f"   ❌ Research failed: {e}")
            return None

    def analyze_system_state(self) -> Dict:
        """Use AI to analyze current state and decide what to do"""

        db = SessionLocal()

        # Get current system state
        total_spacs = db.query(SPAC).count()
        searching_spacs = db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').count()
        announced_deals = db.query(SPAC).filter(SPAC.deal_status == 'ANNOUNCED').count()

        now = datetime.now()
        upcoming_votes = db.query(SPAC).filter(
            SPAC.shareholder_vote_date.isnot(None),
            SPAC.shareholder_vote_date >= now,
            SPAC.shareholder_vote_date <= now + timedelta(days=14)
        ).count()

        urgent_deadlines = db.query(SPAC).filter(
            SPAC.deadline_date.isnot(None),
            SPAC.deadline_date <= now + timedelta(days=30),
            SPAC.deal_status == 'SEARCHING'
        ).count()

        # CRITICAL: Expired SPACs with announced deals (likely missing extensions or closed deals)
        expired_with_deals = db.query(SPAC).filter(
            SPAC.deadline_date.isnot(None),
            SPAC.deadline_date < now,
            SPAC.deal_status == 'ANNOUNCED'
        ).count()

        db.close()

        # Get last run times
        last_runs = {}
        for agent_name, agent in self.agents.items():
            last_run = self.state_manager.get_last_run(agent_name, 'standard_run')
            if last_run:
                hours_since = (now - last_run).total_seconds() / 3600
                last_runs[agent_name] = hours_since
            else:
                last_runs[agent_name] = 999  # Never run

        state_summary = f"""
Current SPAC Database State:
- Total SPACs: {total_spacs}
- Searching for deals: {searching_spacs}
- Announced deals: {announced_deals}
- Upcoming votes (next 14 days): {upcoming_votes}
- Urgent deadlines (<30 days): {urgent_deadlines}
- ⚠️  EXPIRED with announced deals: {expired_with_deals} (CRITICAL - likely missing extensions or closed deals)

Last Agent Runs (hours ago):
- Deal Hunter: {last_runs['deal_hunter']:.1f}h
- Vote Tracker: {last_runs['vote_tracker']:.1f}h
- Price Monitor: {last_runs['price_monitor']:.1f}h
- Risk Analysis: {last_runs['risk_analysis']:.1f}h
- Deadline Extension: {last_runs['deadline_extension']:.1f}h
- Data Validator: {last_runs['data_validator']:.1f}h

Current time: {now.strftime('%Y-%m-%d %H:%M')}
"""

        # Ask AI to decide what to do
        prompt = f"""{state_summary}

You are the orchestrator for a SPAC monitoring system.

**IMPORTANT CONTEXT:**
The system has a REAL-TIME filing monitor running 24/7 that:
- Polls SEC EDGAR every 15 minutes
- Detects new filings within 15-20 minutes of publication
- Automatically routes filings to specialized agents (DealDetector, ExtensionMonitor, etc.)
- Updates database fields in real-time

**This periodic run is a SAFETY NET, not the primary system.** Only run agents when:
1. **Non-filing data needs updating** (prices, Reddit mentions)
2. **Data quality check needed** (validation)
3. **Backup check for missed filings** (rare edge cases)

Available agents:

1. **Deal Hunter** - BACKUP ONLY. Scans for missed deal announcements (filing monitor should catch these)
2. **Vote Tracker** - Monitors shareholder votes (mostly caught by filing monitor, but vote dates change)
3. **Price Monitor** - Updates stock prices (NOT from filings - run regularly during market hours)
4. **Risk Analysis** - Calculates risk levels (run after price updates)
5. **Deadline Extension** - BACKUP ONLY. Filing monitor catches extensions in real-time via 8-K/10-Q
6. **Data Validator** - Validates data quality (run daily as safety check)

**Decision criteria (be conservative):**

**Run regularly (non-filing data):**
- Price Monitor: Every 4-6 hours during market hours
- Data Validator: Once daily (quality check)

**Only run as backup (filing monitor handles these):**
- Deal Hunter: ONLY if >48 hours since last run (safety net)
- Deadline Extension: ONLY if expired SPACs detected (filing monitor may have missed extension)
- Vote Tracker: ONLY if upcoming votes in <7 days (verify dates haven't changed)

**CRITICAL exceptions (override normal schedule):**
- **EXPIRED with announced deals >0** = Deadline Extension CRITICAL (likely missed extension filing)
- Upcoming votes (<7 days) = Vote Tracker HIGH priority
- Price monitor hasn't run in >8 hours = HIGH priority
- Data quality issues = CRITICAL priority for Data Validator

**Be selective!** The filing monitor handles 80% of updates in real-time. This run should be LIGHT.

IMPORTANT: Use exact agent names (lowercase with underscores):
- deal_hunter
- vote_tracker
- price_monitor
- risk_analysis
- deadline_extension
- data_validator

Return JSON with tasks to run NOW (be selective - don't run everything):
{{
  "tasks": [
    {{
      "agent": "deal_hunter",
      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
      "reason": "why run this now"
    }}
  ],
  "reasoning": "overall decision logic"
}}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )

            result = response.choices[0].message.content.strip()

            # Clean JSON
            import re
            result = re.sub(r'```json\s*|\s*```', '', result)

            decision = json.loads(result)

            # Record decision
            self.state_manager.record_decision(decision)

            return decision

        except Exception as e:
            print(f"AI decision error: {e}")
            # Fallback to basic scheduling
            return {
                'tasks': [
                    {'agent': 'price_monitor', 'priority': 'MEDIUM', 'reason': 'Regular update'}
                ],
                'reasoning': 'Fallback to basic schedule'
            }

    def schedule_tasks(self, decision: Dict):
        """Schedule tasks based on AI decision"""

        for task_def in decision.get('tasks', []):
            agent_name = task_def['agent']

            if agent_name not in self.agents:
                continue

            priority_str = task_def.get('priority', 'MEDIUM')
            priority = TaskPriority[priority_str]

            task = AgentTask(
                task_id=f"{agent_name}_{int(time.time())}",
                agent_name=agent_name,
                task_type='standard_run',
                priority=priority,
                status=TaskStatus.PENDING,
                created_at=datetime.now(),
                parameters={'reason': task_def.get('reason')}
            )

            self.task_queue.append(task)

        # Sort by priority
        self.task_queue.sort(key=lambda t: t.priority.value)

    def execute_tasks(self):
        """Execute queued tasks"""

        print(f"\n{'='*80}")
        print(f"Task Queue: {len(self.task_queue)} tasks")
        print(f"{'='*80}\n")

        for task in self.task_queue:
            print(f"[ORCHESTRATOR] Executing {task.agent_name} (Priority: {task.priority.name})")
            print(f"  Reason: {task.parameters.get('reason')}")

            agent = self.agents[task.agent_name]
            agent.execute(task)

            print()

        self.task_queue.clear()

    def process_filing(self, filing: Dict, classification: Dict):
        """
        Process a new SEC filing by routing to appropriate agents

        Called by SEC filing monitor when new filing detected

        OPTIMIZATION: Downloads filing content ONCE, then passes to all agents

        Returns:
            True if filing was successfully logged to database, False otherwise
        """
        agents_needed = classification.get('agents_needed', [])

        if not agents_needed:
            return False  # No agents to process, skip logging

        # Get ticker from CIK (filing monitor provides CIK)
        cik = filing.get('cik')
        if cik and 'ticker' not in filing:
            db = SessionLocal()
            spac = db.query(SPAC).filter(SPAC.cik == cik).first()
            if spac:
                filing['ticker'] = spac.ticker

                # Check if SPAC needs comprehensive extraction retry
                if (spac.comprehensive_extraction_needed and
                    spac.deal_status == 'SEARCHING' and
                    (spac.comprehensive_extraction_attempts or 0) < 10):  # Max 10 attempts

                    print(f"\n🔄 [EXTRACTION RETRY] {spac.ticker} needs data extraction (attempt {(spac.comprehensive_extraction_attempts or 0) + 1})")
                    self._retry_comprehensive_extraction(spac.ticker)

            db.close()

        ticker = filing.get('ticker', 'UNKNOWN')

        # Suppress verbose logging for LOW priority filings (reduces log bloat)
        show_verbose_logs = classification['priority'] in ['MEDIUM', 'HIGH']

        if show_verbose_logs:
            print(f"\n[ORCHESTRATOR] Processing {filing['type']} filing for {ticker}")
            print(f"   Priority: {classification['priority']}")
            print(f"   Routing to: {', '.join(agents_needed)}")
        else:
            # Minimal logging for LOW priority filings
            agent_count = len(agents_needed)
            if agent_count == 0:
                print(f"[ORCHESTRATOR] {filing['type']} for {ticker} (LOW priority, 0 agents)")

        # Log to news feed database (track success for SEC monitor confirmation)
        logging_success = False
        try:
            from utils.filing_logger import log_filing
            filing['classification'] = classification
            logging_success = log_filing(filing)  # Returns True/False
            if show_verbose_logs:
                if logging_success:
                    print(f"   ✅ Logged to news feed")
                else:
                    print(f"   ℹ️  Filing already logged (duplicate)")
        except Exception as e:
            if show_verbose_logs:
                print(f"   ⚠️  Failed to log to news feed: {e}")
            logging_success = False

        # OPTIMIZATION 1: Download filing content once if multiple agents need it
        if len(agents_needed) > 1 and 'content' not in filing:
            if show_verbose_logs:
                print(f"   📥 Pre-fetching filing content (shared by {len(agents_needed)} agents)...")
            filing['content'] = self._fetch_filing_content(filing.get('url'))
            if show_verbose_logs:
                if filing['content']:
                    print(f"   ✓ Content fetched: {len(filing['content']):,} characters")
                else:
                    print(f"   ⚠️  Content fetch failed - agents will fetch individually")

        # OPTIMIZATION 2: AI-powered relevance analysis (skip irrelevant agents)
        relevance_map = {}
        if filing.get('content') and len(agents_needed) > 1:
            if show_verbose_logs:
                print(f"   🔍 Analyzing filing content for agent relevance...")
            relevance_map = self._analyze_filing_relevance(
                content=filing['content'],
                agents_needed=agents_needed,
                classification=classification,
                filing=filing
            )
        else:
            # Default: all agents relevant (single agent or no content)
            relevance_map = {agent: True for agent in agents_needed}

        # Filter to only relevant agents
        relevant_agents = [agent for agent in agents_needed if relevance_map.get(agent, True)]

        if len(relevant_agents) < len(agents_needed):
            skipped = set(agents_needed) - set(relevant_agents)
            if show_verbose_logs:
                print(f"   ⏭️  Skipping {len(skipped)} irrelevant agents: {', '.join(skipped)}")

        results = []

        for agent_name in relevant_agents:
            if agent_name in self.filing_agents:
                task = AgentTask(
                    task_id=f"{agent_name}_{ticker}_{int(time.time())}",
                    agent_name=agent_name,
                    task_type='filing_processing',
                    priority=TaskPriority[classification['priority']],
                    status=TaskStatus.PENDING,
                    created_at=datetime.now(),
                    parameters={
                        'filing': filing,
                        'classification': classification
                    }
                )

                # Execute immediately (filing processing is real-time)
                completed_task = self.filing_agents[agent_name].execute(task)
                results.append({
                    'agent': agent_name,
                    'status': completed_task.status.value,
                    'result': completed_task.result
                })

                if show_verbose_logs:
                    if completed_task.status == TaskStatus.COMPLETED:
                        print(f"   ✅ {agent_name} completed")
                    elif completed_task.status == TaskStatus.FAILED:
                        print(f"   ❌ {agent_name} failed: {completed_task.error}")

            else:
                if show_verbose_logs:
                    print(f"   ⚠️  Agent '{agent_name}' not found in filing_agents")
                results.append({
                    'agent': agent_name,
                    'status': 'NOT_FOUND',
                    'error': f'{agent_name} not registered'
                })

        # Summary with AI optimization stats (only for MEDIUM/HIGH priority)
        if show_verbose_logs:
            completed = sum(1 for r in results if r.get('status') == 'completed')
            skipped_count = len(agents_needed) - len(relevant_agents)

            if skipped_count > 0:
                print(f"   📊 Summary: {completed}/{len(relevant_agents)} relevant agents completed ({skipped_count} skipped by AI)\n")
            else:
                print(f"   📊 Summary: {completed}/{len(agents_needed)} agents completed\n")

        # Return logging success status (for SEC monitor to track which filings were successfully processed)
        return logging_success

    def process_approved_validation_issues(self):
        """Process approved validation issues automatically"""
        from validation_issue_queue import ValidationIssueQueue

        queue = ValidationIssueQueue()
        approved = [i for i in queue.data['issues'] if i.get('resolution') == 'approved']

        if not approved:
            return

        print(f"\n[ORCHESTRATOR] Found {len(approved)} approved validation issue(s)")
        print("[ORCHESTRATOR] Creating task to process approved issues...")

        # Create task to process approved issues
        task = AgentTask(
            task_id=f"process_validation_issues_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            agent_name="data_quality_fixer",
            task_type="process_approved_issues",
            priority=TaskPriority.HIGH,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            parameters={
                'issue_count': len(approved),
                'auto_commit': True
            }
        )

        self.task_queue.append(task)

        # Execute immediately (high priority)
        import subprocess
        try:
            print("[ORCHESTRATOR] Running approved issue processor...")
            result = subprocess.run(
                ['/home/ubuntu/spac-research/venv/bin/python3',
                 '/home/ubuntu/spac-research/process_approved_validation_issues.py'],
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                print(f"[ORCHESTRATOR] ✅ Successfully processed approved issues")
                task.status = TaskStatus.COMPLETED
                task.result = {'output': result.stdout}
            else:
                print(f"[ORCHESTRATOR] ⚠️  Some issues failed to process")
                task.status = TaskStatus.COMPLETED  # Still mark completed, just with failures
                task.result = {'output': result.stdout, 'errors': result.stderr}

        except Exception as e:
            print(f"[ORCHESTRATOR] ❌ Error processing approved issues: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)

    def check_service_health(self):
        """Check if critical monitoring services are running and restart if needed"""
        import subprocess

        # NOTE: reddit-monitor, news-monitor, sec-filing-monitor are now
        # handled by orchestrator's scheduled monitoring - no longer separate services

        services = [
            # All monitoring now handled by orchestrator's run_scheduled_monitoring()
            # No external services to check
        ]

        print("[ORCHESTRATOR] Service health check...")

        for service in services:
            try:
                # Check if service is active
                result = subprocess.run(
                    ['systemctl', 'is-active', service],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.stdout.strip() != 'active':
                    print(f"  ⚠️  {service} is NOT running - attempting restart...")

                    # Try to restart
                    restart_result = subprocess.run(
                        ['sudo', 'systemctl', 'restart', service],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if restart_result.returncode == 0:
                        print(f"  ✅ {service} restarted successfully")
                    else:
                        print(f"  ❌ Failed to restart {service}: {restart_result.stderr}")
                else:
                    print(f"  ✅ {service} is running")

            except subprocess.TimeoutExpired:
                print(f"  ❌ Timeout checking {service}")
            except Exception as e:
                print(f"  ❌ Error checking {service}: {e}")

        print()

    def _write_sec_monitor_health(self, status: str, filings_processed: int):
        """
        Write SEC monitor health status to file for monitoring

        Args:
            status: 'healthy', 'error', 'failed_import'
            filings_processed: Number of filings processed this run
        """
        import json
        health_file = '/home/ubuntu/spac-research/.sec_monitor_health.json'

        health_data = {
            'status': status,
            'last_check': datetime.now().isoformat(),
            'filings_processed': filings_processed,
            'timestamp': datetime.now().isoformat()
        }

        try:
            with open(health_file, 'w') as f:
                json.dump(health_data, f, indent=2)
        except Exception as e:
            print(f"[ORCHESTRATOR] Warning: Could not write health file: {e}")

    def check_sec_monitor_health(self) -> bool:
        """
        Check if SEC monitor is healthy
        Returns True if healthy, False if stale or missing
        """
        import json
        health_file = '/home/ubuntu/spac-research/.sec_monitor_health.json'

        if not os.path.exists(health_file):
            return True  # First run, no health file yet

        try:
            with open(health_file) as f:
                health = json.load(f)

            last_check = datetime.fromisoformat(health['timestamp'])
            age_minutes = (datetime.now() - last_check).total_seconds() / 60

            # Should update every 5-15 minutes
            if age_minutes > 20:
                alert_msg = f"⚠️ SEC MONITOR STALE\n\nLast check: {age_minutes:.0f} minutes ago\nExpected: <20 min\n\nMonitor may be stuck or failing silently"
                print(f"[ORCHESTRATOR] {alert_msg}")

                # Alert via Telegram
                try:
                    telegram_task = AgentTask(
                        task_id=f"telegram_warning_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="telegram",
                        task_type="send_alert",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'alert_text': alert_msg}
                    )
                    self.agents['telegram'].execute(telegram_task)
                except:
                    pass

                return False

            return health['status'] == 'healthy'

        except Exception as e:
            print(f"[ORCHESTRATOR] Warning: Could not read health file: {e}")
            return True  # Don't fail if health check fails

    def run_scheduled_monitoring(self):
        """
        Run scheduled monitoring tasks (time-based, not AI-decision based)

        These tasks run on fixed schedules:
        - Reddit monitoring: Every 30 minutes
        - News monitoring: Every 3 hours
        - Price updates: Every 5 minutes (during market hours 9 AM - 4 PM ET)
        """
        current_time = datetime.now()

        # ========================================================================
        # Reddit Monitoring (Every 30 minutes)
        # ========================================================================
        # Reddit Monitoring (DISABLED - deprecated signal_monitor_agent)
        # TODO: Re-enable as part of opportunity identification agent
        # ========================================================================
        # reddit_interval_minutes = 30
        # last_reddit_run = self.state_manager.state['last_run'].get('reddit_monitor')
        #
        # should_run_reddit = False
        # if last_reddit_run is None:
        #     should_run_reddit = True
        # else:
        #     last_run_dt = datetime.fromisoformat(last_reddit_run)
        #     minutes_since_last = (current_time - last_run_dt).total_seconds() / 60
        #
        #     if minutes_since_last >= reddit_interval_minutes:
        #         should_run_reddit = True
        #
        # if should_run_reddit:
        #     print(f"[ORCHESTRATOR] 🔍 Running scheduled Reddit monitoring...")
        #     try:
        #         from signal_monitor_agent import SignalMonitorAgent
        #
        #         agent = SignalMonitorAgent()
        #         result = agent.monitor_reddit(interval_name="30min")
        #         agent.close()
        #
        #         # Update last run time
        #         self.state_manager.state['last_run']['reddit_monitor'] = current_time.isoformat()
        #         self.state_manager.save_state()
        #
        #         if result['success']:
        #             print(f"[ORCHESTRATOR] ✓ Reddit monitoring complete: "
        #                   f"{result['spacs_scanned']} scanned, {result['leaks_detected']} leaks")
        #         else:
        #             print(f"[ORCHESTRATOR] ✗ Reddit monitoring failed: {result.get('error')}")
        #
        #     except Exception as e:
        #         print(f"[ORCHESTRATOR] ✗ Reddit monitoring error: {e}")
        # else:
        #     last_run_dt = datetime.fromisoformat(last_reddit_run)
        #     minutes_since_last = (current_time - last_run_dt).total_seconds() / 60
        #     minutes_until_next = reddit_interval_minutes - minutes_since_last
        #
        #     print(f"[ORCHESTRATOR] ⏭️  Reddit monitoring: Last run {minutes_since_last:.0f} min ago, "
        #           f"next in {minutes_until_next:.0f} min")

        # ========================================================================
        # News Monitoring (Every 3 hours)
        # ========================================================================
        news_interval_minutes = 180  # 3 hours
        last_news_run = self.state_manager.state['last_run'].get('news_monitor')

        should_run_news = False
        if last_news_run is None:
            should_run_news = True
        else:
            last_run_dt = datetime.fromisoformat(last_news_run)
            minutes_since_last = (current_time - last_run_dt).total_seconds() / 60

            if minutes_since_last >= news_interval_minutes:
                should_run_news = True

        if should_run_news:
            print(f"[ORCHESTRATOR] 📰 Running scheduled news monitoring...")
            try:
                import subprocess
                result = subprocess.run(
                    ['/home/ubuntu/spac-research/venv/bin/python3',
                     '/home/ubuntu/spac-research/news_api_monitor.py',
                     '--commit', '--max-spacs', '60', '--days', '3'],
                    cwd='/home/ubuntu/spac-research',
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                # Update last run time
                self.state_manager.state['last_run']['news_monitor'] = current_time.isoformat()
                self.state_manager.save_state()

                if result.returncode == 0:
                    print(f"[ORCHESTRATOR] ✓ News monitoring complete")
                else:
                    print(f"[ORCHESTRATOR] ✗ News monitoring failed: {result.stderr[:200]}")

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ News monitoring error: {e}")
        else:
            last_run_dt = datetime.fromisoformat(last_news_run)
            minutes_since_last = (current_time - last_run_dt).total_seconds() / 60
            minutes_until_next = news_interval_minutes - minutes_since_last

            print(f"[ORCHESTRATOR] ⏭️  News monitoring: Last run {minutes_since_last:.0f} min ago, "
                  f"next in {minutes_until_next:.0f} min")

        # ========================================================================
        # Price Monitoring (Every 5 minutes during market hours 9 AM - 4 PM ET)
        # ========================================================================
        import pytz
        eastern = pytz.timezone('US/Eastern')
        current_time_et = current_time.astimezone(eastern)
        current_hour_et = current_time_et.hour
        current_weekday = current_time_et.weekday()  # 0=Monday, 6=Sunday

        # Market hours: Mon-Fri, 9 AM - 4 PM ET
        is_market_hours = (current_weekday < 5 and 9 <= current_hour_et < 16)

        price_interval_minutes = 5  # Changed from 15 to 5 minutes (Oct 20, 2025)
        last_price_run = self.state_manager.state['last_run'].get('price_monitor_scheduled')

        should_run_price = False
        if is_market_hours:
            if last_price_run is None:
                should_run_price = True
            else:
                last_run_dt = datetime.fromisoformat(last_price_run)
                minutes_since_last = (current_time - last_run_dt).total_seconds() / 60

                if minutes_since_last >= price_interval_minutes:
                    should_run_price = True

        if should_run_price:
            print(f"[ORCHESTRATOR] 💰 Running scheduled price monitoring...")

            # Execute price_monitor agent task
            task = AgentTask(
                task_id=f"price_monitor_scheduled_{int(time.time())}",
                agent_name="price_monitor",
                task_type="standard_run",
                priority=TaskPriority.HIGH,
                status=TaskStatus.PENDING,
                created_at=current_time,
                parameters={'reason': 'Scheduled price update (every 5 min during market hours)'}
            )

            result = self.agents['price_monitor'].execute(task)

            # Update last run time
            self.state_manager.state['last_run']['price_monitor_scheduled'] = current_time.isoformat()
            self.state_manager.save_state()

            if result.status == TaskStatus.COMPLETED:
                print(f"[ORCHESTRATOR] ✓ Price monitoring complete")
            else:
                print(f"[ORCHESTRATOR] ✗ Price monitoring failed: {result.error}")

        elif is_market_hours and last_price_run:
            last_run_dt = datetime.fromisoformat(last_price_run)
            minutes_since_last = (current_time - last_run_dt).total_seconds() / 60
            minutes_until_next = price_interval_minutes - minutes_since_last

            print(f"[ORCHESTRATOR] ⏭️  Price monitoring: Last run {minutes_since_last:.0f} min ago, "
                  f"next in {minutes_until_next:.0f} min")
        else:
            print(f"[ORCHESTRATOR] 💤 Price monitoring: Market closed (current time ET: {current_time_et.strftime('%H:%M')})")

        # ========================================================================
        # After-Market Tasks (Daily at 4:30 PM ET after market closes)
        # ========================================================================
        # Run market snapshot and historical price backfill after market close
        is_after_market = (current_weekday < 5 and current_hour_et == 16 and current_time_et.minute >= 30) or \
                          (current_weekday < 5 and current_hour_et > 16)

        last_aftermarket_run = self.state_manager.state['last_run'].get('aftermarket_tasks')

        should_run_aftermarket = False
        if is_after_market:
            if last_aftermarket_run is None:
                should_run_aftermarket = True
            else:
                last_run_dt = datetime.fromisoformat(last_aftermarket_run)
                # Only run once per day
                if last_run_dt.date() < current_time.date():
                    should_run_aftermarket = True

        if should_run_aftermarket:
            print(f"[ORCHESTRATOR] 📊 Running after-market tasks...")

            try:
                import subprocess

                # 1. Market snapshot (aggregate market metrics)
                print(f"[ORCHESTRATOR]   → Taking market snapshot...")
                result = subprocess.run(
                    ['/home/ubuntu/spac-research/venv/bin/python3',
                     '/home/ubuntu/spac-research/market_snapshot.py'],
                    cwd='/home/ubuntu/spac-research',
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if result.returncode == 0:
                    print(f"[ORCHESTRATOR]   ✓ Market snapshot complete")
                else:
                    print(f"[ORCHESTRATOR]   ✗ Market snapshot failed: {result.stderr[:200]}")

                # 2. Backfill historical prices (yesterday's data from Yahoo)
                print(f"[ORCHESTRATOR]   → Backfilling historical prices...")
                from datetime import timedelta
                yesterday = (current_time - timedelta(days=1)).strftime('%Y-%m-%d')

                result = subprocess.run(
                    ['/home/ubuntu/spac-research/venv/bin/python3',
                     '/home/ubuntu/spac-research/backfill_historical_prices.py',
                     '--start-date', yesterday, '--end-date', yesterday],
                    cwd='/home/ubuntu/spac-research',
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode == 0:
                    print(f"[ORCHESTRATOR]   ✓ Historical prices backfilled")
                else:
                    print(f"[ORCHESTRATOR]   ✗ Backfill failed: {result.stderr[:200]}")

                # 3. Calculate 30-day volume baseline for all SPACs
                print(f"[ORCHESTRATOR]   → Calculating 30-day volume baselines...")
                try:
                    from agents.volume_tracker_agent import VolumeTrackerAgent

                    volume_agent = VolumeTrackerAgent()
                    # Only calculate baselines, don't send alerts (PriceMonitor handles alerts)
                    volume_agent.spike_threshold_extreme = 999  # Disable alerts

                    task_obj = AgentTask(
                        task_id=f"volume_baseline_{int(time.time())}",
                        agent_name="volume_baseline",
                        task_type="update_all",
                        priority=TaskPriority.LOW,
                        status=TaskStatus.PENDING,
                        created_at=current_time,
                        parameters={'task_type': 'update_all'}
                    )

                    volume_result = volume_agent.execute(task_obj)
                    if volume_result.get('success'):
                        updated = volume_result.get('spacs_updated', 0)
                        print(f"[ORCHESTRATOR]   ✓ Volume baselines updated for {updated} SPACs")
                    else:
                        print(f"[ORCHESTRATOR]   ✗ Volume baseline calculation failed")
                except Exception as vol_error:
                    print(f"[ORCHESTRATOR]   ✗ Volume baseline error: {vol_error}")

                # Update last run time
                self.state_manager.state['last_run']['aftermarket_tasks'] = current_time.isoformat()
                self.state_manager.save_state()

                print(f"[ORCHESTRATOR] ✓ After-market tasks complete")

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ After-market tasks error: {e}")
        elif is_after_market and last_aftermarket_run:
            last_run_dt = datetime.fromisoformat(last_aftermarket_run)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  After-market tasks: Already ran today")
        else:
            print(f"[ORCHESTRATOR] 💤 After-market tasks: Waiting for market close (runs at 4:30 PM ET)")

        # ========================================================================
        # Daily Pre-IPO Monitoring (Once per day, any time after 9 AM ET)
        # ========================================================================
        is_business_hours = (current_weekday < 5 and current_hour_et >= 9)
        last_preipo_run = self.state_manager.state['last_run'].get('preipo_monitoring')

        should_run_preipo = False
        if is_business_hours:
            if last_preipo_run is None:
                should_run_preipo = True
            else:
                last_run_dt = datetime.fromisoformat(last_preipo_run)
                # Only run once per day
                if last_run_dt.date() < current_time.date():
                    should_run_preipo = True

        if should_run_preipo:
            print(f"[ORCHESTRATOR] 🔍 Running pre-IPO monitoring...")

            try:
                import subprocess

                # Check pre-IPO pipeline for IPO closings
                result = subprocess.run(
                    ['/home/ubuntu/spac-research/venv/bin/python3',
                     '/home/ubuntu/spac-research/pre_ipo_ipo_close_monitor_ai.py',
                     '--commit'],
                    cwd='/home/ubuntu/spac-research',
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode == 0:
                    print(f"[ORCHESTRATOR] ✓ Pre-IPO monitoring complete")
                else:
                    print(f"[ORCHESTRATOR] ✗ Pre-IPO monitoring failed: {result.stderr[:200]}")

                # Update last run time
                self.state_manager.state['last_run']['preipo_monitoring'] = current_time.isoformat()
                self.state_manager.save_state()

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Pre-IPO monitoring error: {e}")
        elif is_business_hours and last_preipo_run:
            last_run_dt = datetime.fromisoformat(last_preipo_run)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  Pre-IPO monitoring: Already ran today")
        else:
            print(f"[ORCHESTRATOR] 💤 Pre-IPO monitoring: Waiting for business hours (runs daily after 9 AM ET)")

        # ========================================================================
        # Daily Pre-IPO Duplicate Check (Once per day, any time after 9 AM ET)
        # ========================================================================
        last_duplicate_check = self.state_manager.state['last_run'].get('preipo_duplicate_check')

        should_run_duplicate_check = False
        if is_business_hours:
            if last_duplicate_check is None:
                should_run_duplicate_check = True
            else:
                last_run_dt = datetime.fromisoformat(last_duplicate_check)
                # Only run once per day
                if last_run_dt.date() < current_time.date():
                    should_run_duplicate_check = True

        if should_run_duplicate_check:
            print(f"[ORCHESTRATOR] 🔍 Running pre-IPO duplicate check...")

            try:
                task = AgentTask(
                    task_id=f"preipo_duplicate_check_{current_time.strftime('%Y%m%d')}",
                    agent_name="pre_ipo_duplicate_checker",
                    task_type="check_duplicates",
                    priority=TaskPriority.MEDIUM,
                    status=TaskStatus.PENDING,
                    created_at=current_time,
                    parameters={}
                )

                result_task = self.agents['pre_ipo_duplicate_checker'].execute(task)

                if result_task.status == TaskStatus.COMPLETED:
                    duplicates_found = result_task.result.get('duplicates_found', 0)
                    if duplicates_found > 0:
                        print(f"[ORCHESTRATOR] ⚠️  Pre-IPO duplicate check: Found {duplicates_found} duplicate(s)")
                    else:
                        print(f"[ORCHESTRATOR] ✓ Pre-IPO duplicate check: No duplicates found")
                else:
                    print(f"[ORCHESTRATOR] ✗ Pre-IPO duplicate check failed: {result_task.error}")

                # Update last run time
                self.state_manager.state['last_run']['preipo_duplicate_check'] = current_time.isoformat()
                self.state_manager.save_state()

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Pre-IPO duplicate check error: {e}")
                import traceback
                traceback.print_exc()
        elif is_business_hours and last_duplicate_check:
            last_run_dt = datetime.fromisoformat(last_duplicate_check)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  Pre-IPO duplicate check: Already ran today")
        else:
            print(f"[ORCHESTRATOR] 💤 Pre-IPO duplicate check: Waiting for business hours (runs daily after 9 AM ET)")

        # ========================================================================
        # Daily Premium Alert Check (Once per day, any time after 9 AM ET)
        # ========================================================================
        last_premium_check = self.state_manager.state['last_run'].get('premium_alert_check')

        should_run_premium_check = False
        if is_business_hours:
            if last_premium_check is None:
                should_run_premium_check = True
            else:
                last_run_dt = datetime.fromisoformat(last_premium_check)
                # Only run once per day
                if last_run_dt.date() < current_time.date():
                    should_run_premium_check = True

        if should_run_premium_check:
            print(f"[ORCHESTRATOR] 🔔 Running premium alert check...")

            try:
                task = AgentTask(
                    task_id=f"premium_alert_check_{current_time.strftime('%Y%m%d')}",
                    agent_name="premium_alert",
                    task_type="check_thresholds",
                    priority=TaskPriority.MEDIUM,
                    status=TaskStatus.PENDING,
                    created_at=current_time,
                    parameters={}
                )

                result_task = self.agents['premium_alert'].execute(task)

                if result_task.status == TaskStatus.COMPLETED:
                    total_alerts = result_task.result.get('total_alerts', 0)
                    predeal_count = result_task.result.get('predeal_count', 0)
                    livedeal_count = result_task.result.get('livedeal_count', 0)
                    if total_alerts > 0:
                        print(f"[ORCHESTRATOR] 🚨 Premium alerts: {predeal_count} pre-deal + {livedeal_count} live deals")
                    else:
                        print(f"[ORCHESTRATOR] ✓ Premium alert check: No SPACs above thresholds")
                else:
                    print(f"[ORCHESTRATOR] ✗ Premium alert check failed: {result_task.error}")

                # Update last run time
                self.state_manager.state['last_run']['premium_alert_check'] = current_time.isoformat()
                self.state_manager.save_state()

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Premium alert check error: {e}")
                import traceback
                traceback.print_exc()
        elif is_business_hours and last_premium_check:
            last_run_dt = datetime.fromisoformat(last_premium_check)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  Premium alert check: Already ran today")
        else:
            print(f"[ORCHESTRATOR] 💤 Premium alert check: Waiting for business hours (runs daily after 9 AM ET)")

        # ========================================================================
        # Daily Pre-IPO S-1 Finder (Once per day, any time after 9 AM ET)
        # ========================================================================
        last_s1_search = self.state_manager.state['last_run'].get('preipo_s1_search')

        should_run_s1_search = False
        if is_business_hours:
            if last_s1_search is None:
                should_run_s1_search = True
            else:
                last_run_dt = datetime.fromisoformat(last_s1_search)
                # Only run once per day
                if last_run_dt.date() < current_time.date():
                    should_run_s1_search = True

        if should_run_s1_search:
            print(f"[ORCHESTRATOR] 🔍 Running pre-IPO S-1 finder...")

            try:
                import subprocess

                # Search for new S-1 filings (pre-IPO SPACs)
                result = subprocess.run(
                    ['/home/ubuntu/spac-research/venv/bin/python3',
                     '/home/ubuntu/spac-research/pre_ipo_spac_finder.py'],
                    cwd='/home/ubuntu/spac-research',
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode == 0:
                    # Parse output for new SPACs found
                    output = result.stdout
                    if "Found 0 new pre-IPO SPACs" in output:
                        print(f"[ORCHESTRATOR] ✓ Pre-IPO S-1 search: No new filings")
                    else:
                        # Extract count from output
                        import re
                        match = re.search(r'Found (\d+) new pre-IPO SPACs', output)
                        if match:
                            count = int(match.group(1))
                            print(f"[ORCHESTRATOR] 🎉 Pre-IPO S-1 search: Found {count} new SPAC(s)")
                        else:
                            print(f"[ORCHESTRATOR] ✓ Pre-IPO S-1 search complete")
                else:
                    print(f"[ORCHESTRATOR] ✗ Pre-IPO S-1 search failed: {result.stderr[:200]}")

                # Update last run time
                self.state_manager.state['last_run']['preipo_s1_search'] = current_time.isoformat()
                self.state_manager.save_state()

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Pre-IPO S-1 search error: {e}")
        elif is_business_hours and last_s1_search:
            last_run_dt = datetime.fromisoformat(last_s1_search)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  Pre-IPO S-1 search: Already ran today")
        else:
            print(f"[ORCHESTRATOR] 💤 Pre-IPO S-1 search: Waiting for business hours (runs daily after 9 AM ET)")

        # ========================================================================
        # Weekly Deal Enrichment (Sundays at 9 AM ET)
        # ========================================================================
        is_sunday_morning = (current_weekday == 6 and current_hour_et >= 9)
        last_enrichment_run = self.state_manager.state['last_run'].get('weekly_enrichment')

        should_run_enrichment = False
        if is_sunday_morning:
            if last_enrichment_run is None:
                should_run_enrichment = True
            else:
                last_run_dt = datetime.fromisoformat(last_enrichment_run)
                # Only run once per week
                days_since_last = (current_time - last_run_dt).days
                if days_since_last >= 7:
                    should_run_enrichment = True

        if should_run_enrichment:
            print(f"[ORCHESTRATOR] 📚 Running weekly deal enrichment...")

            try:
                import subprocess

                scripts = [
                    ('Deal announcement scraper', 'deal_announcement_scraper.py', ['--commit']),
                    ('S-4 merger docs', 's4_scraper.py', ['--commit']),
                    ('Proxy statements', 'proxy_scraper.py', ['--commit']),
                    # ('Redemption results', 'redemption_scraper.py', ['--commit']),  # DEPRECATED: Use RedemptionExtractor agent
                    ('Deal closing detector', 'deal_closing_detector.py', ['--commit']),
                    ('Pre-IPO S-1 finder', 'pre_ipo_spac_finder.py', []),
                    ('Deal verification', 'deal_monitor_complete.py', ['--mode', 'verify'])
                ]

                for name, script, args in scripts:
                    print(f"[ORCHESTRATOR]   → {name}...")
                    result = subprocess.run(
                        ['/home/ubuntu/spac-research/venv/bin/python3',
                         f'/home/ubuntu/spac-research/{script}'] + args,
                        cwd='/home/ubuntu/spac-research',
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                    if result.returncode == 0:
                        print(f"[ORCHESTRATOR]     ✓ {name} complete")
                    else:
                        print(f"[ORCHESTRATOR]     ✗ {name} failed: {result.stderr[:100]}")

                # Update last run time
                self.state_manager.state['last_run']['weekly_enrichment'] = current_time.isoformat()
                self.state_manager.save_state()

                print(f"[ORCHESTRATOR] ✓ Weekly enrichment complete")

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Weekly enrichment error: {e}")
        elif is_sunday_morning and last_enrichment_run:
            last_run_dt = datetime.fromisoformat(last_enrichment_run)
            days_since_last = (current_time - last_run_dt).days
            if days_since_last < 7:
                print(f"[ORCHESTRATOR] ⏭️  Weekly enrichment: Ran {days_since_last} days ago, next in {7 - days_since_last} days")
        else:
            next_sunday = (7 - current_weekday) if current_weekday < 6 else 1
            print(f"[ORCHESTRATOR] 💤 Weekly enrichment: Next run in {next_sunday} day(s) (Sunday 9 AM ET)")

        # ========================================================================
        # Daily Filing Report (11:59 PM ET every day)
        # ========================================================================
        is_end_of_day = (current_hour_et == 23 and current_time.minute >= 55)
        last_report_run = self.state_manager.state['last_run'].get('daily_filing_report')

        should_run_report = False
        if is_end_of_day:
            if last_report_run is None:
                should_run_report = True
            else:
                last_run_dt = datetime.fromisoformat(last_report_run)
                # Only run once per day
                if last_run_dt.date() != current_time.date():
                    should_run_report = True

        if should_run_report:
            print(f"[ORCHESTRATOR] 📊 Generating daily filing report...")

            try:
                from daily_filing_report import DailyFilingReport

                reporter = DailyFilingReport()
                report = reporter.generate_report()

                # Send via Telegram
                reporter.send_telegram_report(report)

                # Update last run time
                self.state_manager.state['last_run']['daily_filing_report'] = current_time.isoformat()
                self.state_manager.save_state()

                print(f"[ORCHESTRATOR] ✓ Daily filing report complete")

            except Exception as e:
                print(f"[ORCHESTRATOR] ✗ Daily filing report error: {e}")
                import traceback
                traceback.print_exc()
        elif is_end_of_day and last_report_run:
            last_run_dt = datetime.fromisoformat(last_report_run)
            if last_run_dt.date() == current_time.date():
                print(f"[ORCHESTRATOR] ⏭️  Daily filing report: Already ran today")
        else:
            # Calculate time until next report (11:59 PM ET)
            if current_hour_et >= 23:
                hours_until = 24 - current_hour_et
            else:
                hours_until = 23 - current_hour_et
            print(f"[ORCHESTRATOR] 💤 Daily filing report: Next run in ~{hours_until} hour(s) (11:55 PM ET)")

        # ========================================================================
        # SEC Filing Monitor (Every 5-15 minutes, 24/7)
        # ========================================================================
        # Adaptive interval: 5 min for accelerated tickers, 15 min otherwise
        from orchestrator_trigger import get_accelerated_polling_tickers

        accelerated_tickers = get_accelerated_polling_tickers()
        sec_interval_minutes = 5 if accelerated_tickers else 15

        last_sec_run = self.state_manager.state['last_run'].get('sec_monitor')

        should_run_sec = False
        if last_sec_run is None:
            should_run_sec = True
        else:
            last_run_dt = datetime.fromisoformat(last_sec_run)
            minutes_since_last = (current_time - last_run_dt).total_seconds() / 60

            if minutes_since_last >= sec_interval_minutes:
                should_run_sec = True

        if should_run_sec:
            if accelerated_tickers:
                print(f"[ORCHESTRATOR] 🚀 Running accelerated SEC filing monitor (5 min interval)")
                print(f"   Accelerated polling for: {', '.join(accelerated_tickers)}")
            else:
                print(f"[ORCHESTRATOR] 📄 Running SEC filing monitor...")

            try:
                # Check critical dependencies BEFORE importing
                missing_deps = []
                try:
                    import feedparser
                except ImportError:
                    missing_deps.append('feedparser')

                try:
                    import bs4
                except ImportError:
                    missing_deps.append('beautifulsoup4')

                if missing_deps:
                    error_msg = f"🚨 SEC MONITOR DEPENDENCY ERROR\n\nMissing: {', '.join(missing_deps)}\n\nInstall: pip install {' '.join(missing_deps)}"
                    print(f"[ORCHESTRATOR] ✗ {error_msg}")

                    # Send Telegram alert (critical failure)
                    try:
                        telegram_task = AgentTask(
                            task_id=f"telegram_critical_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            agent_name="telegram",
                            task_type="send_alert",
                            priority=TaskPriority.CRITICAL,
                            status=TaskStatus.PENDING,
                            created_at=datetime.now(),
                            parameters={'alert_text': error_msg}
                        )
                        self.agents['telegram'].execute(telegram_task)
                    except:
                        pass  # Don't fail if Telegram also fails

                    return  # Skip this run, will retry next cycle

                from sec_filing_monitor import SECFilingMonitor

                # Create monitor and poll all SPACs
                monitor = SECFilingMonitor(poll_interval_seconds=sec_interval_minutes * 60)
                filings = monitor.poll_all_spacs()

                # Track successfully processed filings
                processed_filing_ids = []

                # Process any new filings found
                if filings:
                    print(f"[ORCHESTRATOR]   ✓ Found {len(filings)} new filing(s)")

                    for filing in filings:
                        # Classify and route through process_filing
                        classification = monitor.classify_filing(filing)

                        print(f"[ORCHESTRATOR]   📄 {filing['type']} for {filing.get('ticker', filing.get('cik', 'UNKNOWN'))}")
                        print(f"      Priority: {classification['priority']}, Agents: {', '.join(classification['agents_needed'])}")

                        # Route to process_filing (returns True if successfully logged)
                        if classification['agents_needed']:
                            success = self.process_filing(filing, classification)
                            if success:
                                processed_filing_ids.append(filing['id'])
                else:
                    print(f"[ORCHESTRATOR]   No new filings")

                # Mark successfully processed filings as "seen" and save state
                # This prevents re-processing AND ensures failed filings are retried next run
                if processed_filing_ids:
                    monitor.mark_filings_processed(processed_filing_ids)
                elif filings:
                    # No filings were successfully processed, but we still need to save state
                    # to update last_check time (otherwise we'll keep trying the same filings)
                    print(f"[ORCHESTRATOR]   ⚠️  0/{len(filings)} filings successfully processed - will retry next run")
                    # Still update last_check to prevent infinite retries of permanently broken filings
                    monitor._save_state()

                # Update last run time AND write health status
                self.state_manager.state['last_run']['sec_monitor'] = current_time.isoformat()
                self.state_manager.save_state()

                # Write health check file
                self._write_sec_monitor_health('healthy', len(filings) if filings else 0)

            except ImportError as e:
                error_msg = f"🚨 SEC MONITOR IMPORT ERROR: {e}\n\nThe SEC filing monitor cannot start. Deal detection is DISABLED!"
                print(f"[ORCHESTRATOR] ✗ {error_msg}")

                # Send Telegram alert
                try:
                    telegram_task = AgentTask(
                        task_id=f"telegram_critical_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="telegram",
                        task_type="send_alert",
                        priority=TaskPriority.CRITICAL,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'alert_text': error_msg}
                    )
                    self.agents['telegram'].execute(telegram_task)
                except:
                    pass

                self._write_sec_monitor_health('failed_import', 0)

            except Exception as e:
                error_msg = f"SEC filing monitor error: {e}"
                print(f"[ORCHESTRATOR] ✗ {error_msg}")
                import traceback
                traceback.print_exc()

                # Check if this is a recurring error
                error_count = self.state_manager.state.get('sec_monitor_error_count', 0) + 1
                self.state_manager.state['sec_monitor_error_count'] = error_count

                # Alert on 3rd consecutive error
                if error_count >= 3:
                    alert_msg = f"⚠️ SEC MONITOR FAILING\n\nError count: {error_count}\nLast error: {error_msg}\n\nDeal detection may be impaired!"
                    try:
                        telegram_task = AgentTask(
                            task_id=f"telegram_warning_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            agent_name="telegram",
                            task_type="send_alert",
                            priority=TaskPriority.HIGH,
                            status=TaskStatus.PENDING,
                            created_at=datetime.now(),
                            parameters={'alert_text': alert_msg}
                        )
                        self.agents['telegram'].execute(telegram_task)
                        # Reset counter after alerting
                        self.state_manager.state['sec_monitor_error_count'] = 0
                    except:
                        pass

                self._write_sec_monitor_health('error', 0)
        else:
            minutes_since_last = (current_time - datetime.fromisoformat(last_sec_run)).total_seconds() / 60
            minutes_until_next = sec_interval_minutes - minutes_since_last

            status_msg = "🚀 Accelerated" if accelerated_tickers else "📄 Regular"
            print(f"[ORCHESTRATOR] ⏭️  SEC monitor ({status_msg}): Last run {minutes_since_last:.0f} min ago, "
                  f"next in {minutes_until_next:.0f} min")

            if accelerated_tickers:
                print(f"   Accelerated for: {', '.join(accelerated_tickers)}")

    def run(self):
        """Main orchestration loop"""

        print(f"\n{'='*80}")
        print(f"SPAC AI Agent Orchestrator - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")

        # Step 0: Check service health and restart if needed
        self.check_service_health()

        # Step 0.5: Run scheduled monitoring tasks (Reddit every 30 min)
        self.run_scheduled_monitoring()

        # Step 1: Check for approved validation issues and process them
        self.process_approved_validation_issues()

        # Step 1: Analyze system state with AI
        print("[ORCHESTRATOR] Analyzing system state...")
        decision = self.analyze_system_state()

        print(f"\n[ORCHESTRATOR] Decision: {decision.get('reasoning')}")
        print(f"[ORCHESTRATOR] Scheduled {len(decision.get('tasks', []))} tasks\n")

        # Step 2: Schedule tasks
        self.schedule_tasks(decision)

        # Step 3: Execute tasks
        self.execute_tasks()

        # Step 4: Summary
        print(f"{'='*80}")
        print(f"Orchestration complete")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='SPAC AI Agent Orchestrator')
    parser.add_argument('--continuous', action='store_true',
                        help='Run continuously (daemon mode)')
    parser.add_argument('--interval', type=int, default=3600,
                        help='Interval between runs in seconds (default: 3600 = 1 hour)')

    args = parser.parse_args()

    orchestrator = Orchestrator()

    if args.continuous:
        print(f"Starting orchestrator in CONTINUOUS mode (interval: {args.interval}s)")
        print(f"Press Ctrl+C to stop\n")

        try:
            while True:
                orchestrator.run()

                print(f"\n⏰ Sleeping for {args.interval} seconds...")
                print(f"   Next run at: {(datetime.now() + timedelta(seconds=args.interval)).strftime('%Y-%m-%d %H:%M:%S')}")
                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\n\n🛑 Orchestrator stopped by user")
    else:
        # Single run mode
        orchestrator.run()
