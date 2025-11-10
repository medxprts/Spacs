#!/usr/bin/env python3
"""
Daily Filing Report - End of Day Summary

Generates comprehensive report on SEC filing detection and processing:
- Filings detected and logged
- Database updates made by agents
- Processing success rates
- Any errors or failures

Runs at end of day (configurable time, default 11:59 PM EDT)
"""

import os
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from collections import defaultdict

from database import SessionLocal, SPAC, FilingEvent
from sqlalchemy import func, and_
from dotenv import load_dotenv

load_dotenv()

# Telegram integration
try:
    from telegram_agent import TelegramAgent
    TELEGRAM_AVAILABLE = True
except:
    TELEGRAM_AVAILABLE = False

# Change tracker integration
try:
    from utils.change_tracker import ChangeTracker
    CHANGE_TRACKER_AVAILABLE = True
except:
    CHANGE_TRACKER_AVAILABLE = False


class DailyFilingReport:
    """Generate end-of-day filing processing report"""

    def __init__(self, report_date: Optional[date] = None):
        """
        Args:
            report_date: Date to generate report for (default: today)
        """
        self.report_date = report_date or date.today()
        self.db = SessionLocal()

    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.close()

    def generate_report(self) -> Dict:
        """
        Generate comprehensive daily report

        Returns:
            Dict with report data
        """
        print(f"\n{'='*70}")
        print(f"DAILY SEC FILING REPORT - {self.report_date.strftime('%B %d, %Y')}")
        print(f"{'='*70}\n")

        report = {
            'date': self.report_date,
            'filings_detected': self._get_filings_detected(),
            'database_updates': self._get_database_updates(),
            'agent_performance': self._get_agent_performance(),
            'top_active_spacs': self._get_top_active_spacs(),
            'filing_types': self._get_filing_type_breakdown(),
            'critical_events': self._get_critical_events(),
            'errors': self._get_processing_errors()
        }

        # Print report
        self._print_report(report)

        return report

    def _get_filings_detected(self) -> Dict:
        """Get filings detected today"""

        filings = self.db.query(FilingEvent).filter(
            FilingEvent.filing_date == self.report_date
        ).all()

        total = len(filings)

        # Count by priority
        by_priority = defaultdict(int)
        for filing in filings:
            by_priority[filing.priority or 'UNKNOWN'] += 1

        # Count by tag
        by_tag = defaultdict(int)
        for filing in filings:
            by_tag[filing.tag or 'Unknown'] += 1

        # Get unique tickers
        unique_tickers = set(f.ticker for f in filings)

        return {
            'total': total,
            'by_priority': dict(by_priority),
            'by_tag': dict(by_tag),
            'unique_spacs': len(unique_tickers),
            'tickers': sorted(unique_tickers)
        }

    def _get_database_updates(self) -> Dict:
        """
        Get database field updates that occurred today

        Track changes to key fields in spacs table
        """

        # Query SPACs that had last_scraped_at or last_price_update today
        today_start = datetime.combine(self.report_date, datetime.min.time())
        today_end = datetime.combine(self.report_date, datetime.max.time())

        # SPACs with data updates today
        spacs_updated = self.db.query(SPAC).filter(
            and_(
                SPAC.last_scraped_at >= today_start,
                SPAC.last_scraped_at <= today_end
            )
        ).all()

        # Count field updates (fields that are not NULL and were updated today)
        field_updates = {
            'target_updates': 0,
            'deal_value_updates': 0,
            'vote_date_updates': 0,
            'deadline_updates': 0,
            'redemption_updates': 0,
            'pipe_updates': 0,
            'extension_count_updates': 0,
            'total_spacs_updated': len(spacs_updated)
        }

        for spac in spacs_updated:
            # Check which fields are populated (indication of update)
            if spac.target:
                field_updates['target_updates'] += 1
            if spac.deal_value:
                field_updates['deal_value_updates'] += 1
            if spac.shareholder_vote_date:
                field_updates['vote_date_updates'] += 1
            if spac.is_extended:
                field_updates['extension_count_updates'] += 1
            if spac.shares_redeemed and spac.shares_redeemed > 0:
                field_updates['redemption_updates'] += 1
            if spac.pipe_size and spac.pipe_size > 0:
                field_updates['pipe_updates'] += 1

        # Get SPACs with deadline updates today
        deadline_changes = self.db.query(SPAC).filter(
            and_(
                SPAC.last_scraped_at >= today_start,
                SPAC.last_scraped_at <= today_end,
                SPAC.deadline_date.isnot(None)
            )
        ).count()

        field_updates['deadline_updates'] = deadline_changes

        return field_updates

    def _get_agent_performance(self) -> Dict:
        """
        Estimate agent performance based on filing types and database updates

        Since agents don't log their individual actions, we infer from:
        - Filing types detected → which agents should have run
        - Database fields updated → which agents succeeded
        """

        filings = self.db.query(FilingEvent).filter(
            FilingEvent.filing_date == self.report_date
        ).all()

        # Map filing types to likely agents
        agent_activity = {
            'deal_detector': {
                'expected_filings': 0,
                'likely_updates': 0,
                'triggers': ['8-K', '425', 'S-4', 'DEFM14A']
            },
            'vote_tracker': {
                'expected_filings': 0,
                'likely_updates': 0,
                'triggers': ['DEFM14A', 'DEF 14A']
            },
            'extension_detector': {
                'expected_filings': 0,
                'likely_updates': 0,
                'triggers': ['8-K']
            },
            'redemption_tracker': {
                'expected_filings': 0,
                'likely_updates': 0,
                'triggers': ['8-K']
            }
        }

        # Count expected agent runs
        for filing in filings:
            for agent, config in agent_activity.items():
                if filing.filing_type in config['triggers']:
                    agent_activity[agent]['expected_filings'] += 1

        # Get actual database updates
        updates = self._get_database_updates()

        agent_activity['deal_detector']['likely_updates'] = updates.get('target_updates', 0)
        agent_activity['vote_tracker']['likely_updates'] = updates.get('vote_date_updates', 0)
        agent_activity['extension_detector']['likely_updates'] = updates.get('extension_count_updates', 0)
        agent_activity['redemption_tracker']['likely_updates'] = updates.get('redemption_updates', 0)

        return agent_activity

    def _get_top_active_spacs(self) -> List[Dict]:
        """Get SPACs with most filings today"""

        filing_counts = self.db.query(
            FilingEvent.ticker,
            func.count(FilingEvent.id).label('count')
        ).filter(
            FilingEvent.filing_date == self.report_date
        ).group_by(
            FilingEvent.ticker
        ).order_by(
            func.count(FilingEvent.id).desc()
        ).limit(10).all()

        result = []
        for ticker, count in filing_counts:
            # Get SPAC details
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            result.append({
                'ticker': ticker,
                'filing_count': count,
                'company': spac.company if spac else 'Unknown',
                'deal_status': spac.deal_status if spac else 'Unknown'
            })

        return result

    def _get_filing_type_breakdown(self) -> Dict:
        """Get breakdown of filing types"""

        type_counts = self.db.query(
            FilingEvent.filing_type,
            func.count(FilingEvent.id).label('count')
        ).filter(
            FilingEvent.filing_date == self.report_date
        ).group_by(
            FilingEvent.filing_type
        ).order_by(
            func.count(FilingEvent.id).desc()
        ).all()

        return {filing_type: count for filing_type, count in type_counts}

    def _get_critical_events(self) -> List[Dict]:
        """Get critical priority filings"""

        critical_filings = self.db.query(FilingEvent).filter(
            and_(
                FilingEvent.filing_date == self.report_date,
                FilingEvent.priority == 'CRITICAL'
            )
        ).all()

        result = []
        for filing in critical_filings:
            result.append({
                'ticker': filing.ticker,
                'filing_type': filing.filing_type,
                'tag': filing.tag,
                'summary': filing.summary
            })

        return result

    def _get_processing_errors(self) -> Dict:
        """
        Get processing errors from logs

        Note: This is a placeholder - actual implementation would parse
        orchestrator.log for errors that occurred today
        """

        # TODO: Parse logs/orchestrator.log for errors from today
        # For now, return placeholder
        return {
            'parse_errors': 0,
            'agent_failures': 0,
            'database_errors': 0,
            'network_errors': 0
        }

    def _print_report(self, report: Dict):
        """Print formatted report to console"""

        # Filing Detection Summary
        print("📊 FILING DETECTION SUMMARY")
        print("-" * 70)
        filings = report['filings_detected']
        print(f"   Total Filings Detected: {filings['total']}")
        print(f"   Unique SPACs: {filings['unique_spacs']}")
        print()

        if filings['by_priority']:
            print("   By Priority:")
            for priority, count in sorted(filings['by_priority'].items(),
                                         key=lambda x: {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(x[0], 4)):
                emoji = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🔵', 'LOW': '⚪'}.get(priority, '⚫')
                print(f"      {emoji} {priority}: {count}")
        print()

        # Database Updates
        print("🗄️  DATABASE UPDATES")
        print("-" * 70)
        updates = report['database_updates']
        print(f"   SPACs Updated: {updates['total_spacs_updated']}")
        print()
        print(f"   Field Updates:")
        print(f"      • Target (deal announcements): {updates['target_updates']}")
        print(f"      • Deal Value: {updates['deal_value_updates']}")
        print(f"      • Vote Dates: {updates['vote_date_updates']}")
        print(f"      • Deadline Extensions: {updates['extension_count_updates']}")
        print(f"      • Redemptions: {updates['redemption_updates']}")
        print(f"      • PIPE Updates: {updates['pipe_updates']}")
        print()

        # Agent Performance
        print("🤖 AGENT PERFORMANCE")
        print("-" * 70)
        for agent, data in report['agent_performance'].items():
            if data['expected_filings'] > 0:
                success_rate = (data['likely_updates'] / data['expected_filings'] * 100) if data['expected_filings'] > 0 else 0
                print(f"   {agent.replace('_', ' ').title()}:")
                print(f"      Expected runs: {data['expected_filings']}")
                print(f"      Likely updates: {data['likely_updates']}")
                print(f"      Est. success rate: {success_rate:.1f}%")
                print()

        # Top Active SPACs
        if report['top_active_spacs']:
            print("🔥 TOP ACTIVE SPACs")
            print("-" * 70)
            for i, spac in enumerate(report['top_active_spacs'][:5], 1):
                print(f"   {i}. {spac['ticker']} - {spac['filing_count']} filing(s)")
                print(f"      {spac['company']} ({spac['deal_status']})")
            print()

        # Critical Events
        if report['critical_events']:
            print("🚨 CRITICAL EVENTS")
            print("-" * 70)
            for event in report['critical_events']:
                print(f"   {event['ticker']} - {event['tag']}")
                print(f"      {event['summary']}")
                print()

        # Filing Types
        if report['filing_types']:
            print("📄 FILING TYPE BREAKDOWN")
            print("-" * 70)
            for filing_type, count in sorted(report['filing_types'].items(),
                                            key=lambda x: x[1], reverse=True)[:10]:
                print(f"   {filing_type}: {count}")
            print()

        print("=" * 70)
        print()

    def send_telegram_report(self, report: Dict):
        """Send report via Telegram"""

        if not TELEGRAM_AVAILABLE:
            print("   ⚠️  Telegram not available - skipping notification")
            return

        filings = report['filings_detected']
        updates = report['database_updates']

        # Build message
        message = f"""📊 <b>Daily SEC Filing Report</b>
📅 {self.report_date.strftime('%B %d, %Y')}

<b>📄 FILINGS DETECTED</b>
• Total: {filings['total']}
• Unique SPACs: {filings['unique_spacs']}
"""

        # Priority breakdown
        if filings['by_priority']:
            message += "\n<b>Priority Breakdown:</b>\n"
            for priority, count in sorted(filings['by_priority'].items(),
                                         key=lambda x: {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(x[0], 4)):
                emoji = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🔵', 'LOW': '⚪'}.get(priority, '⚫')
                message += f"   {emoji} {priority}: {count}\n"

        # Database updates
        message += f"""
<b>🗄️ DATABASE UPDATES</b>
• SPACs Updated: {updates['total_spacs_updated']}
• Deal Announcements: {updates['target_updates']}
• Vote Dates: {updates['vote_date_updates']}
• Extensions: {updates['extension_count_updates']}
• Redemptions: {updates['redemption_updates']}
"""

        # Critical events
        if report['critical_events']:
            message += f"\n<b>🚨 CRITICAL EVENTS ({len(report['critical_events'])})</b>\n"
            for event in report['critical_events'][:3]:  # Show top 3
                message += f"• {event['ticker']}: {event['tag']}\n"

        # Top active SPACs
        if report['top_active_spacs']:
            message += f"\n<b>🔥 TOP ACTIVE</b>\n"
            for spac in report['top_active_spacs'][:3]:
                message += f"• {spac['ticker']} ({spac['filing_count']} filings)\n"

        # Database change tracking
        if CHANGE_TRACKER_AVAILABLE:
            try:
                change_summary = ChangeTracker.get_daily_summary(self.report_date)
                if change_summary['total_changes'] > 0:
                    message += f"\n<b>📝 AUTOMATED DATABASE CHANGES</b>\n"
                    message += f"• Total Changes: {change_summary['total_changes']}\n"

                    # Top agents making changes
                    if change_summary['by_source']:
                        top_agents = change_summary['by_source'][:3]
                        agents_str = ", ".join([f"{a['source']} ({a['count']})" for a in top_agents])
                        message += f"• Top Agents: {agents_str}\n"

                    # Most updated SPACs
                    if change_summary['by_ticker']:
                        top_spacs = change_summary['by_ticker'][:3]
                        spacs_str = ", ".join([f"{s['ticker']} ({s['count']})" for s in top_spacs])
                        message += f"• Most Updated: {spacs_str}\n"
            except Exception as e:
                print(f"   ⚠️  Failed to get change tracking data: {e}")

        message += f"\n✅ Report generated at {datetime.now().strftime('%I:%M %p EDT')}"

        # Send via Telegram
        try:
            telegram = TelegramAgent()
            telegram.send_message(message)
            print("   ✅ Telegram report sent")
        except Exception as e:
            print(f"   ⚠️  Telegram send failed: {e}")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Generate daily SEC filing report')
    parser.add_argument('--date', type=str, help='Date to report on (YYYY-MM-DD), default: today')
    parser.add_argument('--telegram', action='store_true', help='Send report via Telegram')
    parser.add_argument('--quiet', action='store_true', help='Suppress console output')

    args = parser.parse_args()

    # Parse date
    if args.date:
        report_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        report_date = date.today()

    # Generate report
    reporter = DailyFilingReport(report_date=report_date)

    if not args.quiet:
        report = reporter.generate_report()
    else:
        # Generate without printing
        report = {
            'date': report_date,
            'filings_detected': reporter._get_filings_detected(),
            'database_updates': reporter._get_database_updates(),
            'agent_performance': reporter._get_agent_performance(),
            'top_active_spacs': reporter._get_top_active_spacs(),
            'filing_types': reporter._get_filing_type_breakdown(),
            'critical_events': reporter._get_critical_events(),
            'errors': reporter._get_processing_errors()
        }

    # Send Telegram if requested
    if args.telegram:
        reporter.send_telegram_report(report)


if __name__ == '__main__':
    main()
