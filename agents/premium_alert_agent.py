"""
Monitors SPACs trading above premium thresholds and sends alerts
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase, TaskStatus
from agent_orchestrator import AgentTask, TaskPriority, AI_CLIENT
from database import SessionLocal, SPAC
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class PremiumAlertAgent(OrchestratorAgentBase):
    """Monitors SPACs trading above premium thresholds and sends alerts

    Thresholds:
    - Pre-deal SPACs (SEARCHING): Alert if premium >= 5%
    - Live deal SPACs (ANNOUNCED): Alert if premium >= 10%
    """

    PREDEAL_THRESHOLD = 5.0  # 5% premium for pre-deal SPACs
    LIVEDEAL_THRESHOLD = 10.0  # 10% premium for live deals

    def execute(self, task):
        self._start_task(task)

        try:
            from datetime import timedelta

            print("\n🔔 Checking premium thresholds...")

            db = SessionLocal()

            # Get current time
            now = datetime.now()

            # FIRST: Clear alert timestamps for SPACs that dropped below their threshold
            # This allows re-alerting when they go back above threshold

            # Pre-deal SPACs that dropped below 5% threshold
            predeal_reset = db.query(SPAC).filter(
                SPAC.deal_status == 'SEARCHING',
                SPAC.premium < self.PREDEAL_THRESHOLD,
                SPAC.premium_alert_last_sent.isnot(None),
                SPAC.price.isnot(None)
            ).all()

            # Live deal SPACs that dropped below 10% threshold
            livedeal_reset = db.query(SPAC).filter(
                SPAC.deal_status == 'ANNOUNCED',
                SPAC.premium < self.LIVEDEAL_THRESHOLD,
                SPAC.premium_alert_last_sent.isnot(None),
                SPAC.price.isnot(None)
            ).all()

            reset_count = 0
            for spac in predeal_reset + livedeal_reset:
                spac.premium_alert_last_sent = None
                reset_count += 1

            if reset_count > 0:
                db.commit()
                print(f"   🔄 Reset {reset_count} SPAC(s) that dropped below threshold (can re-alert)")

            # NOW: Find pre-deal SPACs above 5% threshold that haven't been alerted
            predeal_alerts = db.query(SPAC).filter(
                SPAC.deal_status == 'SEARCHING',
                SPAC.premium >= self.PREDEAL_THRESHOLD,
                SPAC.price.isnot(None),
                SPAC.trust_value.isnot(None),
                # Only alert if not alerted yet (timestamp gets cleared when premium drops)
                SPAC.premium_alert_last_sent.is_(None)
            ).order_by(SPAC.premium.desc()).all()

            # Find live deal SPACs above 10% threshold that haven't been alerted
            livedeal_alerts = db.query(SPAC).filter(
                SPAC.deal_status == 'ANNOUNCED',
                SPAC.premium >= self.LIVEDEAL_THRESHOLD,
                SPAC.price.isnot(None),
                SPAC.trust_value.isnot(None),
                # Only alert if not alerted yet (timestamp gets cleared when premium drops)
                SPAC.premium_alert_last_sent.is_(None)
            ).order_by(SPAC.premium.desc()).all()

            result = {
                'predeal_count': len(predeal_alerts),
                'livedeal_count': len(livedeal_alerts),
                'total_alerts': len(predeal_alerts) + len(livedeal_alerts),
                'predeal_spacs': [s.ticker for s in predeal_alerts],
                'livedeal_spacs': [s.ticker for s in livedeal_alerts]
            }

            if predeal_alerts or livedeal_alerts:
                print(f"   🚨 Found {len(predeal_alerts)} pre-deal + {len(livedeal_alerts)} live deal alerts")

                # Send Telegram alert if configured
                if hasattr(self, 'orchestrator_ref') and 'telegram' in self.orchestrator_ref.agents:
                    alert_text = "🔥 <b>PREMIUM ALERTS</b>\n\n"

                    if predeal_alerts:
                        alert_text += f"<b>🔍 PRE-DEAL SPACs (≥{self.PREDEAL_THRESHOLD}% premium)</b>\n"
                        for spac in predeal_alerts:
                            alert_text += f"• <b>{spac.ticker}</b> - {spac.company}\n"
                            alert_text += f"  Price: ${spac.price:.2f} | NAV: ${float(spac.trust_value):.2f}\n"
                            alert_text += f"  Premium: <b>{spac.premium:.1f}%</b>\n"
                            alert_text += f"  Banker: {spac.banker or 'N/A'}\n\n"

                    if livedeal_alerts:
                        alert_text += f"<b>🎯 LIVE DEALS (≥{self.LIVEDEAL_THRESHOLD}% premium)</b>\n"
                        for spac in livedeal_alerts:
                            alert_text += f"• <b>{spac.ticker}</b> - {spac.company}\n"
                            alert_text += f"  Target: {spac.target}\n"
                            alert_text += f"  Price: ${spac.price:.2f} | NAV: ${float(spac.trust_value):.2f}\n"
                            alert_text += f"  Premium: <b>{spac.premium:.1f}%</b>\n"
                            alert_text += f"  Banker: {spac.banker or 'N/A'}\n\n"

                    alert_text += f"<i>Once alerted, SPACs will re-alert only if premium drops below threshold and rises again</i>"

                    telegram_task = AgentTask(
                        task_id=f"telegram_premium_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="telegram",
                        task_type="send_alert",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'alert_text': alert_text}
                    )
                    self.orchestrator_ref.agents['telegram'].execute(telegram_task)

                    # Update last alert sent timestamp + generate AI analysis for all alerted SPACs
                    for spac in predeal_alerts + livedeal_alerts:
                        spac.premium_alert_last_sent = now

                        # Generate AI analysis and save to notes field
                        analysis = self._generate_premium_analysis(spac)
                        if analysis:
                            spac.notes = analysis
                            print(f"      ✍️  Generated analysis for {spac.ticker}: {analysis[:60]}...")

                    db.commit()
                    print(f"   ✅ Telegram alert sent, timestamps + analysis updated")

            else:
                print(f"   ✅ No new premium alerts (checked {db.query(SPAC).filter(SPAC.price.isnot(None)).count()} SPACs)")

            db.close()

            self._complete_task(task, result)

        except Exception as e:
            print(f"   ❌ Error checking premium thresholds: {e}")
            import traceback
            traceback.print_exc()
            self._fail_task(task, str(e))

        return task

    def _generate_premium_analysis(self, spac: SPAC) -> Optional[str]:
        """
        Use AI to analyze why a SPAC is trading at a significant premium
        Returns 1-2 sentence explanation for the notes field
        """
        try:
            # Gather context
            context_parts = []
            context_parts.append(f"SPAC: {spac.ticker} ({spac.company})")
            context_parts.append(f"Price: ${spac.price:.2f}, NAV: ${float(spac.trust_value):.2f}, Premium: {spac.premium:.1f}%")

            if spac.deal_status == 'ANNOUNCED' and spac.target:
                context_parts.append(f"Deal: {spac.target}")
                if spac.announced_date:
                    context_parts.append(f"Announced: {spac.announced_date}")
            elif spac.deal_status_detail == 'RUMORED_DEAL' and spac.rumored_target:
                context_parts.append(f"Status: RUMORED DEAL with {spac.rumored_target} (Confidence: {spac.rumor_confidence}%)")
            else:
                context_parts.append(f"Status: SEARCHING")

            if spac.banker:
                context_parts.append(f"Banker: {spac.banker}")
            if spac.sponsor:
                context_parts.append(f"Sponsor: {spac.sponsor}")
            if spac.sector:
                context_parts.append(f"Sector: {spac.sector}")
            if spac.days_to_deadline:
                if spac.days_to_deadline < 90:
                    context_parts.append(f"⚠️ Deadline in {spac.days_to_deadline} days")

            context = "\n".join(context_parts)

            prompt = f"""Analyze why this SPAC is trading at a {spac.premium:.1f}% premium.

{context}

Provide a concise 1-2 sentence explanation. Focus on:
- **RUMORED DEALS**: If status shows "RUMORED DEAL", this is the PRIMARY driver - mention the rumored target first
- Deal quality/target attractiveness (if announced deal)
- Target company fundamentals, valuation, and market opportunity
- Deal terms: PIPE size, valuation multiples, sponsor dilution
- Sector momentum or market conditions (AI, crypto, defense, healthcare)
- Sponsor track record (prior SPAC performance, reputation)
- Political/Trump connections (if relevant)
- Deadline urgency/redemption dynamics

Examples (EXACTLY this format):
- "Market speculation on rumored $2B deal with Securitize (90% confidence) driving significant premium."
- "Strong target fundamentals: Hadron Energy's $500M revenue and 2x EV/sales valuation in hot nuclear energy sector."
- "High-confidence rumored business combination with AI infrastructure company attracting institutional interest."
- "Attractive PIPE terms at $10/share with $225M commitment providing downside protection in crypto sector."
- "Deal announced with Terrestrial Energy, a nuclear SMR company with $1B+ addressable market in net-zero energy transition."

IMPORTANT:
- Keep response under 200 characters total
- Do NOT start with "Premium driven by" - just state the reason
- Focus on TARGET QUALITY and DEAL TERMS, not banker/sponsor prestige
- Be specific and data-driven"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150
            )

            explanation = response.choices[0].message.content.strip()
            explanation = explanation.replace('"', '').replace('*', '')

            return explanation

        except Exception as e:
            print(f"      ⚠️  AI analysis error for {spac.ticker}: {e}")
            return None


class DataQualityFixerAgent(OrchestratorAgentBase):
    """Autonomous Data Quality Fixer - fixes type errors, dates, orchestrates re-scraping"""
