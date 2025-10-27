"""
Monitors and updates deadline extensions from SEC filings
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC
from datetime import datetime, timedelta


class DeadlineExtensionAgent(OrchestratorAgentBase):
    """Monitors and updates deadline extensions from SEC filings"""

    def execute(self, task):
        self._start_task(task)

        try:
            from deadline_extension_monitor import DeadlineExtensionMonitor

            monitor = DeadlineExtensionMonitor()

            # Get parameters
            commit = task.parameters.get('commit', False) if task.parameters else False
            specific_ticker = task.parameters.get('ticker') if task.parameters else None

            if specific_ticker:
                # Check specific SPAC
                db = SessionLocal()
                spac = db.query(SPAC).filter(SPAC.ticker == specific_ticker).first()
                db.close()

                if not spac or not spac.cik:
                    raise Exception(f"SPAC {specific_ticker} not found or missing CIK")

                print(f"  Checking {specific_ticker} for extensions...")
                ext_result = monitor.check_for_extensions(spac.cik, spac.deadline_date)

                extensions_found = 1 if ext_result['has_extensions'] else 0
                updated = 0

                if ext_result['latest_deadline']:
                    new_deadline = datetime.strptime(ext_result['latest_deadline'], '%Y-%m-%d').date()
                    current_deadline = spac.deadline_date.date() if hasattr(spac.deadline_date, 'date') else spac.deadline_date

                    if current_deadline != new_deadline and commit:
                        db = SessionLocal()
                        spac = db.query(SPAC).filter(SPAC.ticker == specific_ticker).first()
                        spac.deadline_date = datetime.combine(new_deadline, datetime.min.time())
                        spac.extension_count = (spac.extension_count or 0) + 1
                        spac.is_extended = True
                        db.commit()
                        db.close()
                        updated = 1
            else:
                # Check all active SPACs
                db = SessionLocal()
                spacs = db.query(SPAC).filter(
                    SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
                ).all()
                db.close()

                print(f"  Checking {len(spacs)} active SPACs for extensions...")

                extensions_found = 0
                updated = 0

                for spac in spacs:
                    if not spac.cik:
                        # Try to fetch missing CIK
                        try:
                            from sec_data_scraper import SPACDataEnricher
                            scraper = SPACDataEnricher()
                            cik = scraper.get_cik(spac.company)
                            if cik:
                                spac.cik = cik
                                db_update = SessionLocal()
                                spac_obj = db_update.query(SPAC).filter(SPAC.ticker == spac.ticker).first()
                                spac_obj.cik = cik
                                db_update.commit()
                                db_update.close()
                                print(f"  ✅ {spac.ticker}: Found and saved CIK {cik}")
                            else:
                                continue
                        except Exception as e:
                            print(f"  ⚠️  {spac.ticker}: Could not fetch CIK: {e}")
                            continue

                    ext_result = monitor.check_for_extensions(spac.cik, spac.deadline_date)

                    if ext_result['latest_deadline']:
                        extensions_found += 1
                        new_deadline = datetime.strptime(ext_result['latest_deadline'], '%Y-%m-%d').date()
                        current_deadline = spac.deadline_date.date() if hasattr(spac.deadline_date, 'date') else spac.deadline_date

                        if current_deadline != new_deadline:
                            print(f"  → {spac.ticker}: {current_deadline} → {new_deadline}")
                            if commit:
                                db = SessionLocal()
                                spac_obj = db.query(SPAC).filter(SPAC.ticker == spac.ticker).first()
                                spac_obj.deadline_date = datetime.combine(new_deadline, datetime.min.time())
                                spac_obj.extension_count = (spac_obj.extension_count or 0) + 1
                                spac_obj.is_extended = True
                                db.commit()
                                db.close()
                                updated += 1

                    time.sleep(0.3)  # Rate limit

            monitor.close()

            result = {
                'extensions_found': extensions_found,
                'deadlines_updated': updated,
                'commit_mode': commit
            }

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task


