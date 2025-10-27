#!/usr/bin/env python3
"""
Filing Orchestrator - Intelligent Filing Router

Routes SEC filings to specialized agents based on filing type and content.
Handles complex scenarios where one filing needs multiple agents.

Architecture:
    SEC Filing Monitor → Filing Orchestrator → Agent Dispatcher → Specialized Agents
"""

import sys
import os
from typing import Dict, List, Optional
from datetime import datetime

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC

# Import all specialized agents
from agents.deal_detector_agent import DealDetectorAgent
from agents.extension_monitor_agent import ExtensionMonitorAgent
from agents.quarterly_report_extractor import QuarterlyReportExtractor
from agents.filing_processor import FilingProcessor
from utils.telegram_notifier import send_telegram_alert


class FilingOrchestrator:
    """
    Orchestrates routing of SEC filings to appropriate agents

    Key Features:
    - Multi-agent routing (one filing can trigger multiple agents)
    - Priority-based processing (CRITICAL → HIGH → MEDIUM → LOW)
    - Agent registry (easily add new agents)
    - Error handling and fallbacks
    """

    def __init__(self):
        self.db = SessionLocal()

        # Agent Registry: Maps agent names to instances
        self.agent_registry = {
            # Deal-related agents
            'DealDetector': DealDetectorAgent(),
            'FilingProcessor': FilingProcessor(),

            # Trust account agents
            'TrustAccountProcessor': QuarterlyReportExtractor(),

            # Extension/redemption agents
            'ExtensionMonitor': ExtensionMonitorAgent(),
            'RedemptionProcessor': self._get_redemption_processor(),

            # S-4 processor
            'S4Processor': self._get_s4_processor(),

            # Specialized agents (to be implemented)
            'DelistingDetector': self._get_delisting_detector(),
            'ProxyProcessor': self._get_proxy_processor(),
            'IPODetector': self._get_ipo_detector(),
            'CompletionMonitor': self._get_completion_monitor(),
            'EffectivenessMonitor': self._get_effectiveness_monitor(),
            'ComplianceMonitor': self._get_compliance_monitor(),
        }

        print(f"✅ Filing Orchestrator initialized")
        print(f"   Registered {len(self.agent_registry)} agents")

    def _get_redemption_processor(self):
        """Get or create redemption processor agent"""
        try:
            from redemption_scraper import RedemptionScraper
            return RedemptionScraper()
        except:
            return None

    def _get_s4_processor(self):
        """Get or create S-4 processor agent"""
        try:
            from s4_scraper import S4Scraper
            return S4Scraper()
        except:
            return None

    def _get_delisting_detector(self):
        """Get or create delisting detector agent"""
        # Placeholder - implement later
        return None

    def _get_proxy_processor(self):
        """Get or create proxy processor agent"""
        try:
            from proxy_scraper import ProxyScraper
            return ProxyScraper()
        except:
            return None

    def _get_ipo_detector(self):
        """Get or create IPO detector agent"""
        # Placeholder - implement later
        return None

    def _get_completion_monitor(self):
        """Get or create deal completion monitor"""
        try:
            from deal_closing_detector import DealClosingDetector
            return DealClosingDetector()
        except:
            return None

    def _get_effectiveness_monitor(self):
        """Get or create S-4 effectiveness monitor"""
        # Placeholder - implement later
        return None

    def _get_compliance_monitor(self):
        """Get or create compliance monitor"""
        # Placeholder - implement later
        return None

    def process_filing(self, filing: Dict, classification: Dict, ticker: str) -> Dict:
        """
        Process a filing by routing to appropriate agents

        Args:
            filing: Filing metadata (type, date, url, title, summary)
            classification: Classification result from SEC Filing Monitor
            ticker: SPAC ticker

        Returns:
            Processing result with agent outputs
        """
        print(f"\n{'='*70}")
        print(f"📄 FILING ORCHESTRATOR - Processing {filing['type']}")
        print(f"{'='*70}")
        print(f"   Ticker: {ticker}")
        print(f"   Filed: {filing['date'].strftime('%Y-%m-%d')}")
        print(f"   Priority: {classification['priority']}")
        print(f"   Agents: {', '.join(classification['agents_needed'])}")
        print(f"   Reason: {classification['reason']}")

        results = {
            'filing': filing,
            'ticker': ticker,
            'priority': classification['priority'],
            'agents_dispatched': [],
            'agent_results': {},
            'success': False,
            'errors': []
        }

        # Process agents in priority order
        for agent_name in classification['agents_needed']:
            print(f"\n   → Dispatching to {agent_name}...")

            agent = self.agent_registry.get(agent_name)

            if not agent:
                print(f"      ⚠️  Agent '{agent_name}' not available (not implemented yet)")
                results['errors'].append(f"{agent_name} not available")
                continue

            try:
                # Route to appropriate agent method
                agent_result = self._dispatch_to_agent(agent, agent_name, filing, ticker)

                results['agents_dispatched'].append(agent_name)
                results['agent_results'][agent_name] = agent_result

                if agent_result.get('success'):
                    print(f"      ✅ {agent_name} completed successfully")
                    if agent_result.get('findings'):
                        print(f"         Findings: {agent_result['findings']}")
                else:
                    print(f"      ⚠️  {agent_name} completed with warnings")

            except Exception as e:
                print(f"      ❌ {agent_name} failed: {e}")
                results['errors'].append(f"{agent_name}: {str(e)}")

        # Summary
        success_count = sum(1 for r in results['agent_results'].values() if r.get('success'))
        results['success'] = success_count > 0

        print(f"\n   {'='*66}")
        print(f"   Summary: {success_count}/{len(classification['agents_needed'])} agents succeeded")
        if results['errors']:
            print(f"   Errors: {len(results['errors'])}")
        print(f"   {'='*66}\n")

        # Send Telegram notification for critical filings
        if classification['priority'] == 'CRITICAL':
            self._send_critical_filing_alert(filing, ticker, results)

        return results

    def _dispatch_to_agent(self, agent, agent_name: str, filing: Dict, ticker: str) -> Dict:
        """
        Dispatch filing to specific agent based on agent type

        Different agents have different interfaces - handle them appropriately
        """

        # TrustAccountProcessor (QuarterlyReportExtractor)
        if agent_name == 'TrustAccountProcessor':
            # This agent has async process_filing method
            import asyncio
            try:
                result = asyncio.run(agent.process_filing(filing, ticker))
                return result
            except:
                # Fallback: call synchronously if async fails
                return {'success': False, 'error': 'Async processing failed'}

        # DealDetector
        elif agent_name == 'DealDetector':
            # Get SPAC from database
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return {'success': False, 'error': f'SPAC {ticker} not found'}

            # DealDetectorAgent has detect_deal_in_filing method
            result = agent.detect_deal_in_filing(
                cik=spac.cik,
                filing={
                    'type': filing['type'],
                    'date': filing['date'],
                    'url': filing['url']
                }
            )
            return result if result else {'success': False, 'findings': 'No deal detected'}

        # FilingProcessor (DEFM14A, PREM14A, etc.)
        elif agent_name == 'FilingProcessor':
            # FilingProcessor handles proxy filings
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return {'success': False, 'error': f'SPAC {ticker} not found'}

            result = agent.process_filing(
                ticker=ticker,
                filing=filing
            )
            return result if result else {'success': False, 'findings': 'No data extracted'}

        # ExtensionMonitor
        elif agent_name == 'ExtensionMonitor':
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return {'success': False, 'error': f'SPAC {ticker} not found'}

            result = agent.check_extension(
                cik=spac.cik,
                filing={
                    'type': filing['type'],
                    'date': filing['date'],
                    'url': filing['url']
                }
            )
            return result if result else {'success': False, 'findings': 'No extension detected'}

        # RedemptionProcessor
        elif agent_name == 'RedemptionProcessor':
            if not agent:
                return {'success': False, 'error': 'RedemptionProcessor not available'}

            result = agent.scrape_redemption(ticker, filing)
            return result if result else {'success': False, 'findings': 'No redemption data'}

        # S4Processor
        elif agent_name == 'S4Processor':
            if not agent:
                return {'success': False, 'error': 'S4Processor not available'}

            result = agent.scrape_s4(ticker, filing['url'])
            return result if result else {'success': False, 'findings': 'No S-4 data extracted'}

        # ProxyProcessor
        elif agent_name == 'ProxyProcessor':
            if not agent:
                return {'success': False, 'error': 'ProxyProcessor not available'}

            result = agent.scrape_proxy(ticker, filing['url'])
            return result if result else {'success': False, 'findings': 'No proxy data extracted'}

        # DelistingDetector (Form 25)
        elif agent_name == 'DelistingDetector':
            return self._detect_delisting(ticker, filing)

        # CompletionMonitor (deal closing)
        elif agent_name == 'CompletionMonitor':
            if not agent:
                return {'success': False, 'error': 'CompletionMonitor not available'}

            result = agent.detect_closing(ticker, filing)
            return result if result else {'success': False, 'findings': 'No deal closing detected'}

        # Default: agent not implemented yet
        else:
            return {'success': False, 'error': f'Agent {agent_name} dispatch not implemented'}

    def _detect_delisting(self, ticker: str, filing: Dict) -> Dict:
        """
        Detect delisting from Form 25

        Form 25 is filed when a company:
        - Voluntarily delists from exchange
        - Liquidates
        - Merges and ceases to exist
        """
        print(f"      🚨 Form 25 detected - {ticker} delisting/liquidating")

        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            return {'success': False, 'error': f'SPAC {ticker} not found'}

        # Determine reason for delisting
        title_lower = filing.get('title', '').lower()
        summary_lower = filing.get('summary', '').lower()

        if 'merger' in summary_lower or 'combination' in summary_lower or 'acquisition' in summary_lower:
            reason = 'COMPLETED'  # Deal completed successfully
            message = f"✅ {ticker} - Deal completed (Form 25 filed)"
        elif 'liquidat' in summary_lower or 'dissolv' in summary_lower:
            reason = 'LIQUIDATED'  # SPAC liquidated
            message = f"⚠️  {ticker} - Liquidating (Form 25 filed)"
        else:
            reason = 'DELISTED'  # Generic delisting
            message = f"⚠️  {ticker} - Delisting (Form 25 filed)"

        # Update database
        old_status = spac.deal_status
        spac.deal_status = reason
        self.db.commit()

        # Send Telegram alert
        send_telegram_alert(f"{message}\nPrevious status: {old_status}")

        return {
            'success': True,
            'findings': f'Delisting detected: {reason}',
            'old_status': old_status,
            'new_status': reason,
            'filing_date': filing['date']
        }

    def _send_critical_filing_alert(self, filing: Dict, ticker: str, results: Dict):
        """Send Telegram alert for critical filings"""

        message = f"🚨 <b>CRITICAL FILING DETECTED</b>\n\n"
        message += f"<b>Ticker:</b> {ticker}\n"
        message += f"<b>Filing:</b> {filing['type']}\n"
        message += f"<b>Date:</b> {filing['date'].strftime('%Y-%m-%d')}\n\n"

        message += f"<b>Agents Dispatched:</b>\n"
        for agent_name in results['agents_dispatched']:
            result = results['agent_results'].get(agent_name, {})
            status = "✅" if result.get('success') else "⚠️"
            message += f"  {status} {agent_name}\n"

        if results.get('errors'):
            message += f"\n<b>Errors:</b> {len(results['errors'])}\n"

        send_telegram_alert(message)

    def close(self):
        """Cleanup"""
        self.db.close()


def test_orchestrator():
    """Test the filing orchestrator with sample filings"""

    orchestrator = FilingOrchestrator()

    # Test filings
    test_cases = [
        {
            'filing': {
                'type': '10-Q',
                'date': datetime(2025, 11, 14),
                'url': 'https://www.sec.gov/...',
                'title': 'Quarterly Report',
                'summary': 'Form 10-Q for Q3 2025'
            },
            'classification': {
                'priority': 'MEDIUM',
                'agents_needed': ['TrustAccountProcessor'],
                'reason': 'Quarterly report - trust account update'
            },
            'ticker': 'AEXA'
        },
        {
            'filing': {
                'type': '25',
                'date': datetime(2025, 11, 15),
                'url': 'https://www.sec.gov/...',
                'title': 'Notification of delisting',
                'summary': 'Merger completed, delisting from NYSE'
            },
            'classification': {
                'priority': 'CRITICAL',
                'agents_needed': ['DelistingDetector'],
                'reason': 'Form 25 - Delisting notification'
            },
            'ticker': 'TEST'
        },
        {
            'filing': {
                'type': 'DEFM14A',
                'date': datetime(2025, 11, 16),
                'url': 'https://www.sec.gov/...',
                'title': 'Definitive Merger Proxy',
                'summary': 'Proxy statement for business combination vote'
            },
            'classification': {
                'priority': 'HIGH',
                'agents_needed': ['FilingProcessor'],
                'reason': 'Merger proxy - vote details'
            },
            'ticker': 'CEP'
        }
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n\n{'#'*70}")
        print(f"TEST CASE {i}/{len(test_cases)}")
        print(f"{'#'*70}")

        result = orchestrator.process_filing(
            filing=test_case['filing'],
            classification=test_case['classification'],
            ticker=test_case['ticker']
        )

        print(f"\n✅ Test case {i} completed")
        print(f"   Success: {result['success']}")
        print(f"   Agents dispatched: {len(result['agents_dispatched'])}")

    orchestrator.close()


if __name__ == "__main__":
    test_orchestrator()
