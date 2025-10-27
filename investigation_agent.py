#!/usr/bin/env python3
"""
Investigation Agent - Autonomous Root Cause Analysis

Replicates human-like problem solving:
1. Detect anomalies
2. Generate hypotheses (AI)
3. Test hypotheses (evidence collection)
4. Diagnose root cause
5. Apply fix
6. Create prevention measures
7. Document everything

Example: OBA ticker reuse investigation
"""

import os
import sys
import json
import hashlib
import requests
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from openai import OpenAI

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from utils.telegram_notifier import send_telegram_alert


class AnomalyDetector:
    """Detects suspicious patterns in research results"""

    def detect_anomalies(self, issue: Dict, research_result: Dict, context: Dict) -> List[Dict]:
        """
        Analyze research results for anomalies

        Args:
            issue: Original validation issue
            research_result: Results from research agent
            context: SPAC context (ticker, cik, ipo_date, etc.)

        Returns:
            List of detected anomalies with hypotheses
        """
        anomalies = []

        # Anomaly 1: Temporal inconsistency (deal date vs IPO date)
        if research_result.get('deal_found') and research_result.get('announced_date'):
            deal_date = research_result['announced_date']
            ipo_date = context.get('ipo_date')

            if ipo_date and isinstance(deal_date, datetime) and isinstance(ipo_date, datetime):
                years_gap = (ipo_date - deal_date).days / 365.25

                if years_gap > 2:
                    anomalies.append({
                        'type': 'temporal_inconsistency',
                        'severity': 'CRITICAL',
                        'description': f'Deal announced {years_gap:.1f} years before IPO',
                        'evidence': {
                            'deal_date': deal_date.isoformat() if hasattr(deal_date, 'isoformat') else str(deal_date),
                            'ipo_date': ipo_date.isoformat() if hasattr(ipo_date, 'isoformat') else str(ipo_date),
                            'gap_years': round(years_gap, 1)
                        },
                        'primary_hypothesis': 'Wrong CIK - ticker may have been recycled from old company'
                    })

        # Anomaly 2: Target extraction failure despite deal found
        if research_result.get('deal_found') and not research_result.get('target'):
            anomalies.append({
                'type': 'extraction_failure',
                'severity': 'MEDIUM',
                'description': 'Deal found but target extraction failed',
                'evidence': {
                    'deal_found': True,
                    'target': None,
                    'source_filing': research_result.get('source_filing')
                },
                'primary_hypothesis': 'Filing too old or malformed - may indicate wrong CIK'
            })

        # Anomaly 3: Company name mismatch
        if context.get('database_company_name') and context.get('sec_company_name'):
            db_name = context['database_company_name'].lower()
            sec_name = context['sec_company_name'].lower()

            # Simple comparison (could be enhanced)
            if db_name not in sec_name and sec_name not in db_name:
                anomalies.append({
                    'type': 'company_name_mismatch',
                    'severity': 'CRITICAL',
                    'description': f'Database shows "{context["database_company_name"]}" but SEC shows "{context["sec_company_name"]}"',
                    'evidence': {
                        'database_name': context['database_company_name'],
                        'sec_name': context['sec_company_name']
                    },
                    'primary_hypothesis': 'Wrong CIK - ticker was recycled'
                })

        return anomalies


class HypothesisGenerator:
    """AI-powered hypothesis generation"""

    def __init__(self, ai_client):
        self.ai_client = ai_client

    def generate(self, anomaly: Dict, context: Dict, past_learnings: List[Dict] = None) -> List[Dict]:
        """
        Use AI to generate possible root causes, informed by past learnings

        Args:
            anomaly: Detected anomaly
            context: SPAC context
            past_learnings: Optional list of similar past cases with outcomes

        Returns:
            List of hypotheses ranked by likelihood
        """
        if not self.ai_client:
            # Fallback to rule-based hypotheses
            return self._generate_rule_based(anomaly, context)

        # Include primary hypothesis as strong hint
        primary_hint = ""
        if anomaly.get('primary_hypothesis'):
            primary_hint = f"\n**Primary Hypothesis (likely root cause):** {anomaly['primary_hypothesis']}\n"

        # Include past learnings if available
        learning_context = ""
        if past_learnings:
            learning_context = f"\n**📚 PAST LEARNINGS ({len(past_learnings)} similar cases):**\n"
            for i, case in enumerate(past_learnings[:5], 1):  # Show top 5
                learning_context += f"\n{i}. Ticker: {case['ticker']}"
                if case.get('learning'):
                    learning_context += f"\n   Learning: {case['learning']}"
                if case.get('fix'):
                    try:
                        fix_data = json.loads(case['fix']) if isinstance(case['fix'], str) else case['fix']
                        if fix_data.get('extension_found'):
                            learning_context += f"\n   Outcome: Extension found (new deadline: {fix_data.get('new_deadline')})"
                        elif fix_data.get('completion_found'):
                            learning_context += "\n   Outcome: Deal completed"
                        elif fix_data.get('termination_found'):
                            learning_context += "\n   Outcome: Deal terminated"
                    except:
                        pass
            learning_context += "\n\n**Use these patterns to inform your hypotheses and adjust likelihood scores.**\n"

        prompt = f"""Analyze this data anomaly and generate possible root causes.

**Anomaly:** {anomaly['description']}
**Severity:** {anomaly['severity']}
**Type:** {anomaly['type']}
{primary_hint}{learning_context}
**Evidence:**
{json.dumps(anomaly.get('evidence', {}), indent=2)}

**Context:**
- Ticker: {context.get('ticker')}
- Company (Database): {context.get('company')}
- CIK: {context.get('cik')}
- IPO Date: {context.get('ipo_date')}
- Deal Status: {context.get('deal_status')}

**Task:** Generate 3-5 possible root causes ranked by likelihood. Consider past learnings above to adjust probabilities. The primary hypothesis above should be ranked FIRST if it makes sense.

For each hypothesis, provide:
1. **root_cause**: Brief description
2. **likelihood**: Probability 0-100%
3. **reasoning**: Why this is likely
4. **verification_steps**: How to verify - USE THESE SPECIFIC PHRASES:
   - "Query SEC for CIK company info" (to check SEC company name/SIC code)
   - "Check SIC code (should be 6770 for SPACs)" (to verify it's a SPAC)
   - "Search SEC for correct CIK using company name" (to find correct CIK)
   - "Compare filing dates with IPO timeframe" (to check temporal consistency)
5. **fix_if_true**: How to fix if this root cause is confirmed

**IMPORTANT:** Use the exact verification step phrases above so they can be executed programmatically.

**Format:** Respond with ONLY valid JSON (no markdown, no code blocks):
{{
  "hypotheses": [
    {{
      "rank": 1,
      "likelihood": 90,
      "root_cause": "...",
      "reasoning": "...",
      "verification_steps": ["Query SEC for CIK company info", "Check SIC code (should be 6770 for SPACs)", ...],
      "fix_if_true": "..."
    }}
  ]
}}
"""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a data quality investigator specializing in SPAC databases. Generate root cause hypotheses for data anomalies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON (remove markdown if present)
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()

            result = json.loads(result_text)
            return result.get('hypotheses', [])

        except Exception as e:
            print(f"⚠️  AI hypothesis generation failed: {e}")
            return self._generate_rule_based(anomaly, context)

    def _generate_rule_based(self, anomaly: Dict, context: Dict) -> List[Dict]:
        """Fallback rule-based hypothesis generation"""

        if anomaly['type'] == 'temporal_inconsistency':
            return [{
                'rank': 1,
                'likelihood': 90,
                'root_cause': 'Wrong CIK - ticker was recycled from old company',
                'reasoning': f"Deal date {anomaly['evidence']['gap_years']} years before IPO is impossible for same entity",
                'verification_steps': [
                    'Query SEC for CIK company info',
                    'Check SIC code (should be 6770 for SPACs)',
                    'Search SEC for correct CIK using company name',
                    'Compare filing dates with IPO timeframe'
                ],
                'fix_if_true': 'Update CIK to correct company, reset deal_status, clear stale data'
            }]

        return []


class EvidenceCollector:
    """Collects evidence to test hypotheses"""

    def __init__(self):
        self.headers = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}
        self.base_url = "https://www.sec.gov"

    def collect(self, hypothesis: Dict, context: Dict) -> Dict:
        """
        Execute verification steps and collect evidence

        Args:
            hypothesis: Hypothesis to test
            context: SPAC context

        Returns:
            Evidence dict
        """
        evidence = {}

        for step in hypothesis.get('verification_steps', []):
            step_lower = step.lower()

            if 'query sec' in step_lower and 'cik' in step_lower:
                # Get SEC company info for this CIK
                sec_info = self._get_sec_company_info(context.get('cik'))
                if sec_info:
                    evidence['sec_company_name'] = sec_info.get('company_name')
                    evidence['sec_sic_code'] = sec_info.get('sic_code')
                    evidence['sec_sic_description'] = sec_info.get('sic_description')

            elif 'check sic' in step_lower:
                # Check if it's a SPAC (SIC 6770)
                if evidence.get('sec_sic_code'):
                    evidence['is_spac'] = (evidence['sec_sic_code'] == '6770')

            elif 'search sec' in step_lower and 'company name' in step_lower:
                # Search for correct CIK
                company_name = context.get('company')
                if company_name:
                    correct_cik = self._search_sec_for_company(company_name)
                    if correct_cik:
                        evidence['correct_cik'] = correct_cik

                        # Get info for correct CIK
                        correct_info = self._get_sec_company_info(correct_cik)
                        if correct_info:
                            evidence['correct_company_name'] = correct_info.get('company_name')
                            evidence['correct_sic_code'] = correct_info.get('sic_code')

            elif 'filing dates' in step_lower:
                # Check earliest filing date
                earliest_filing = self._get_earliest_filing_date(context.get('cik'))
                if earliest_filing and context.get('ipo_date'):
                    evidence['earliest_filing_date'] = earliest_filing.isoformat()

                    ipo_date = context['ipo_date']
                    if isinstance(ipo_date, str):
                        ipo_date = datetime.fromisoformat(ipo_date)

                    years_before_ipo = (ipo_date - earliest_filing).days / 365.25
                    evidence['years_before_ipo'] = round(years_before_ipo, 1)

            time.sleep(0.15)  # Rate limit SEC requests

        return evidence

    def _get_sec_company_info(self, cik: str) -> Optional[Dict]:
        """Query SEC for company information"""
        if not cik:
            return None

        url = f"{self.base_url}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&owner=exclude&count=1"

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            html = response.text

            # Parse HTML for company info
            info = {}

            # Company name
            if 'companyName' in html:
                start = html.find('companyName">') + len('companyName">')
                end = html.find('<acronym', start)
                if end > start:
                    info['company_name'] = html[start:end].strip()

            # SIC code
            if 'SIC</acronym>:' in html:
                sic_start = html.find('SIC=', html.find('SIC</acronym>:')) + len('SIC=')
                sic_end = html.find('&', sic_start)
                if sic_end > sic_start:
                    info['sic_code'] = html[sic_start:sic_end]

                # SIC description
                desc_start = html.find('">', sic_end) + 2
                desc_end = html.find('<', desc_start)
                if desc_end > desc_start:
                    info['sic_description'] = html[desc_start:desc_end].strip()

            return info

        except Exception as e:
            print(f"Error fetching SEC info for CIK {cik}: {e}")
            return None

    def _search_sec_for_company(self, company_name: str) -> Optional[str]:
        """Search SEC for company and get CIK"""
        search_name = company_name.replace(' ', '+')
        url = f"{self.base_url}/cgi-bin/browse-edgar?company={search_name}&owner=exclude&action=getcompany"

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            html = response.text

            # Extract CIK from first result
            if 'CIK=#:' in html:
                cik_start = html.find('CIK=', html.find('CIK=#:')) + len('CIK=')
                cik_end = html.find('&', cik_start)
                if cik_end > cik_start:
                    cik = html[cik_start:cik_end]
                    return cik.zfill(10)  # Pad to 10 digits

        except Exception as e:
            print(f"Error searching SEC for {company_name}: {e}")

        return None

    def _get_earliest_filing_date(self, cik: str) -> Optional[datetime]:
        """Get earliest filing date for CIK"""
        if not cik:
            return None

        url = f"{self.base_url}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&owner=exclude&count=100"

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            html = response.text

            # Find all filing dates
            import re
            dates = []
            date_pattern = r'<td>(20\d{2}-\d{2}-\d{2})</td>'
            matches = re.findall(date_pattern, html)

            for date_str in matches:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    dates.append(date_obj)
                except:
                    pass

            if dates:
                return min(dates)

        except Exception as e:
            print(f"Error fetching filings for CIK {cik}: {e}")

        return None


class RootCauseDiagnoser:
    """Analyzes evidence to confirm root cause"""

    def diagnose(self, hypotheses: List[Dict], evidence: Dict) -> Optional[Dict]:
        """
        Determine actual root cause from evidence

        Args:
            hypotheses: List of hypotheses from generator
            evidence: Collected evidence

        Returns:
            Diagnosis dict with confirmed root cause or None
        """
        # Sort hypotheses by likelihood
        sorted_hypotheses = sorted(hypotheses, key=lambda h: h.get('likelihood', 0), reverse=True)

        for hypothesis in sorted_hypotheses:
            root_cause = hypothesis['root_cause'].lower()

            # Check for ticker reuse / wrong CIK
            if 'wrong cik' in root_cause or 'ticker' in root_cause and 'recycl' in root_cause:
                # Verify evidence supports this
                # Strong evidence: Current CIK is NOT a SPAC AND filings way before IPO
                if (not evidence.get('is_spac', True) and  # Current CIK is NOT a SPAC (SIC != 6770)
                    evidence.get('years_before_ipo', 0) > 2):  # Filings way before IPO

                    # Very high confidence if we found correct CIK too
                    confidence = 100 if evidence.get('correct_cik') else 95

                    return {
                        'confirmed': True,
                        'root_cause': hypothesis['root_cause'],
                        'confidence': confidence,
                        'hypothesis': hypothesis,
                        'evidence': evidence,
                        'fix_strategy': hypothesis['fix_if_true']
                    }

        # No hypothesis confirmed
        return {'confirmed': False, 'evidence': evidence}


class FixApplier:
    """Applies fixes to database"""

    def __init__(self):
        self.db = SessionLocal()

    def apply(self, diagnosis: Dict, context: Dict) -> Dict:
        """
        Apply fix based on diagnosis

        Args:
            diagnosis: Confirmed diagnosis
            context: SPAC context

        Returns:
            Fix result with before/after states
        """
        ticker = context.get('ticker')
        if not ticker:
            return {'fix_applied': False, 'error': 'No ticker in context'}

        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            return {'fix_applied': False, 'error': f'SPAC {ticker} not found'}

        # Capture before state
        before_state = {
            'cik': spac.cik,
            'deal_status': spac.deal_status,
            'target': spac.target,
            'announced_date': spac.announced_date.isoformat() if spac.announced_date else None
        }

        # Apply fix based on root cause
        root_cause = diagnosis['root_cause'].lower()

        if 'wrong cik' in root_cause:
            # Update CIK
            correct_cik = diagnosis['evidence'].get('correct_cik')

            # If we don't have correct_cik, try to find it
            if not correct_cik:
                print("   → Searching SEC for correct CIK...")
                correct_cik = self._search_for_correct_cik(context.get('company'))

            if correct_cik:
                spac.cik = correct_cik
                spac.deal_status = 'SEARCHING'
                spac.target = None
                spac.announced_date = None

                self.db.commit()

                # Capture after state
                after_state = {
                    'cik': spac.cik,
                    'deal_status': spac.deal_status,
                    'target': spac.target,
                    'announced_date': None
                }

                return {
                    'fix_applied': True,
                    'before': before_state,
                    'after': after_state,
                    'changes': {
                        'cik': f"{before_state['cik']} → {after_state['cik']}",
                        'deal_status': f"{before_state['deal_status']} → {after_state['deal_status']}",
                        'target': 'Cleared',
                        'announced_date': 'Cleared'
                    }
                }
            else:
                # Couldn't find correct CIK, but at least clear the bad data
                print("   ⚠️  Could not find correct CIK, clearing stale data only")
                spac.deal_status = 'SEARCHING'
                spac.target = None
                spac.announced_date = None

                self.db.commit()

                after_state = {
                    'cik': spac.cik,  # Unchanged
                    'deal_status': spac.deal_status,
                    'target': spac.target,
                    'announced_date': None
                }

                return {
                    'fix_applied': True,
                    'partial': True,
                    'before': before_state,
                    'after': after_state,
                    'changes': {
                        'deal_status': f"{before_state['deal_status']} → {after_state['deal_status']}",
                        'target': 'Cleared',
                        'announced_date': 'Cleared'
                    },
                    'warning': 'Could not find correct CIK - manual verification needed'
                }

        return {'fix_applied': False, 'error': 'Unknown fix strategy'}

    def _search_for_correct_cik(self, company_name: str) -> Optional[str]:
        """Search SEC for correct CIK"""
        if not company_name:
            return None

        import re

        # Strip common suffixes that prevent matching
        search_name = company_name
        suffixes = [' Limited', ' Ltd', ' Inc', ' Corp', ' LLC', ' Co', ' LP', ' LLP']
        for suffix in suffixes:
            if search_name.endswith(suffix):
                search_name = search_name[:-len(suffix)]
                break

        headers = {'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'}
        search_query = search_name.replace(' ', '+')
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={search_query}&owner=exclude&action=getcompany"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            html = response.text

            # Simple pattern: any 10-digit CIK
            match = re.search(r'(\d{10})', html)
            if match:
                return match.group(1)

        except Exception as e:
            print(f"   Error searching SEC: {e}")

        return None

    def close(self):
        """Cleanup"""
        self.db.close()


class PreventionCreator:
    """Creates validation rules to prevent recurrence"""

    def create(self, diagnosis: Dict) -> List[Dict]:
        """
        Generate prevention measures

        Args:
            diagnosis: Confirmed diagnosis

        Returns:
            List of prevention measures
        """
        measures = []

        root_cause = diagnosis['root_cause'].lower()

        if 'wrong cik' in root_cause or 'ticker' in root_cause:
            # Already exists: validate_cik_mappings.py
            measures.append({
                'type': 'existing_validator',
                'file': 'validate_cik_mappings.py',
                'description': 'CIK validator already exists - validates SIC code and filing dates',
                'action': 'Run weekly via cron',
                'schedule': '0 2 * * 0'  # Sunday 2am
            })

            # Add to orchestrator validation
            measures.append({
                'type': 'orchestrator_check',
                'description': 'Add CIK staleness check to data validator',
                'recommendation': 'Validate filing dates match IPO timeframe when checking deal status'
            })

        return measures


class InvestigationAgent:
    """
    Autonomous root cause investigator

    Full workflow:
    1. Detect anomalies
    2. Generate hypotheses (AI)
    3. Collect evidence
    4. Diagnose root cause
    5. Apply fix
    6. Create prevention
    7. Document
    """

    def __init__(self):
        api_key = os.getenv('DEEPSEEK_API_KEY')
        self.ai_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        ) if api_key else None

        self.anomaly_detector = AnomalyDetector()
        self.hypothesis_generator = HypothesisGenerator(self.ai_client)
        self.evidence_collector = EvidenceCollector()
        self.diagnoser = RootCauseDiagnoser()
        self.fix_applier = FixApplier()
        self.prevention_creator = PreventionCreator()

    def _retrieve_past_learnings(self, issue_type: str, ticker: str = None, limit: int = 10) -> List[Dict]:
        """
        Query past investigations for similar issues to learn from history

        Args:
            issue_type: Type of issue (e.g., 'deadline_passed', 'missing_target')
            ticker: Optional ticker to prioritize similar SPACs
            limit: Maximum number of past cases to retrieve

        Returns:
            List of past cases with outcomes, fixes, and learnings
        """
        from sqlalchemy import text

        db = SessionLocal()
        try:
            query = text("""
                SELECT
                    issue_type,
                    ticker,
                    proposed_fix,
                    final_fix,
                    learning_notes,
                    status,
                    messages,
                    completed_at
                FROM data_quality_conversations
                WHERE status IN ('approved', 'fixed', 'reviewed')
                  AND completed_at IS NOT NULL
                ORDER BY
                    CASE WHEN ticker = :ticker THEN 0 ELSE 1 END,
                    completed_at DESC
                LIMIT :limit
            """)

            results = db.execute(query, {
                'ticker': ticker or '',
                'limit': limit
            }).fetchall()

            past_cases = []
            for row in results:
                case = {
                    'issue_type': row.issue_type,
                    'ticker': row.ticker,
                    'fix': row.final_fix or row.proposed_fix,
                    'learning': row.learning_notes,
                    'status': row.status,
                    'completed_at': row.completed_at.isoformat() if row.completed_at else None
                }
                past_cases.append(case)

            if past_cases:
                print(f"   📚 Retrieved {len(past_cases)} past learnings for issue type: {issue_type}")

            return past_cases

        except Exception as e:
            print(f"   ⚠️  Could not retrieve past learnings: {e}")
            return []
        finally:
            db.close()

    def _save_learning(self, issue_type: str, ticker: str, outcome: Dict, learning_notes: str):
        """
        Save investigation outcome to learning database

        Args:
            issue_type: Type of issue investigated
            ticker: SPAC ticker
            outcome: Investigation result dict
            learning_notes: Human-readable learning summary
        """
        from sqlalchemy import text
        import hashlib

        db = SessionLocal()
        try:
            issue_id = hashlib.md5(
                f"{ticker}_{issue_type}_{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]

            query = text("""
                INSERT INTO data_quality_conversations
                (issue_id, issue_type, ticker, status, learning_notes, final_fix, completed_at)
                VALUES (:issue_id, :issue_type, :ticker, :status, :learning_notes, :final_fix, :completed_at)
                ON CONFLICT (issue_id) DO UPDATE
                SET learning_notes = EXCLUDED.learning_notes,
                    final_fix = EXCLUDED.final_fix,
                    completed_at = EXCLUDED.completed_at,
                    status = EXCLUDED.status
            """)

            db.execute(query, {
                'issue_id': issue_id,
                'issue_type': issue_type,
                'ticker': ticker,
                'status': 'fixed' if outcome.get('should_update') else 'reviewed',
                'learning_notes': learning_notes,
                'final_fix': json.dumps(outcome),
                'completed_at': datetime.now()
            })

            db.commit()
            print(f"   ✅ Saved learning to database: {issue_id}")

        except Exception as e:
            db.rollback()
            print(f"   ⚠️  Could not save learning: {e}")
        finally:
            db.close()

    def generate_hypotheses(self, anomaly: Dict, context: Dict) -> List[Dict]:
        """
        Generate hypotheses for an anomaly (wrapper for orchestrator compatibility)
        Now includes learning from past similar cases

        Args:
            anomaly: Detected anomaly dict
            context: SPAC context

        Returns:
            List of hypothesis dicts
        """
        # Retrieve past learnings for similar issue types
        issue_type = anomaly.get('type', 'unknown')
        ticker = context.get('ticker')

        past_learnings = self._retrieve_past_learnings(
            issue_type=issue_type,
            ticker=ticker,
            limit=10
        )

        # Generate hypotheses informed by past learnings
        return self.hypothesis_generator.generate(anomaly, context, past_learnings)

    def investigate_deadline_extension(self, ticker: str, cik: str, deadline_date: date = None) -> Dict:
        """
        Investigate recent SEC filings for deadline extensions, completions, or terminations

        User learning: "When deadline passed, don't just alert - check recent SEC filings
        for the explanation (extension, completion, termination)."

        Now includes learning from past similar deadline investigations.

        Args:
            ticker: SPAC ticker symbol
            cik: SEC CIK number
            deadline_date: Original deadline date (optional, used to calculate smart lookback period)

        Returns:
            Dict with investigation results:
            {
                'extension_found': bool,
                'new_deadline': date,
                'completion_found': bool,
                'termination_found': bool,
                'source_filing': str,
                'should_update': bool
            }
        """
        from utils.sec_filing_fetcher import SECFilingFetcher
        import re

        print(f"\n🔍 Investigating deadline for {ticker} via recent SEC filings...")

        # Retrieve past learnings for deadline investigations
        past_learnings = self._retrieve_past_learnings(
            issue_type='deadline_passed',
            ticker=ticker,
            limit=5
        )

        sec_fetcher = SECFilingFetcher()
        result = {
            'extension_found': False,
            'new_deadline': None,
            'completion_found': False,
            'termination_found': False,
            'source_filing': None,
            'should_update': False
        }

        # Calculate smart lookback period
        # For severely overdue deadlines, search from the deadline date
        # For recent deadlines, search last 30 days
        if deadline_date and isinstance(deadline_date, date):
            days_overdue = (datetime.now().date() - deadline_date).days
            if days_overdue > 90:
                # Severely overdue - search from deadline date to now
                lookback_start = datetime.combine(deadline_date, datetime.min.time())
                print(f"   📅 Deadline was {days_overdue} days ago - searching filings since deadline")
            else:
                # Recently overdue - search last 60 days
                lookback_start = datetime.now() - timedelta(days=60)
                print(f"   📅 Deadline was {days_overdue} days ago - searching last 60 days")
        else:
            # No deadline provided - default to 30 days
            lookback_start = datetime.now() - timedelta(days=30)
            print(f"   📅 No deadline provided - searching last 30 days")

        filing_types = [
            ('8-K', 'Current Report'),
            ('425', 'Prospectus/Proxy'),
            ('10-Q', 'Quarterly Report'),
            ('25', 'Delisting Notice')
        ]

        for filing_type, filing_description in filing_types:
            try:
                print(f"   Checking {filing_type} ({filing_description}) filings...")

                # Search for filings of this type
                filings = sec_fetcher.search_filings(
                    cik=cik,
                    filing_type=filing_type,
                    count=10
                )

                # Filter for filings after lookback_start
                recent_filings = [
                    f for f in filings
                    if f['date'] > lookback_start
                ]

                if not recent_filings:
                    print(f"      No recent {filing_type}s found")
                    continue

                print(f"      Found {len(recent_filings)} recent {filing_type}(s)")

                for filing in recent_filings:
                    filing_date = filing.get('date')
                    filing_url = filing.get('url')

                    print(f"      {filing_date.strftime('%Y-%m-%d')}: Checking...")

                    # Fetch filing text
                    filing_text = sec_fetcher.fetch_document(filing_url)
                    if not filing_text:
                        continue

                    # Check for delisting (Form 25 specific)
                    if filing_type == '25':
                        result['completion_found'] = True
                        result['source_filing'] = f"Form 25 filed {filing_date.strftime('%Y-%m-%d')}"
                        result['should_update'] = True
                        print(f"   ✅ Delisting notice found (Form 25) - deal likely completed")

                        # Save learning
                        learning_note = f"Form 25 delisting notice indicates deal completion for {ticker}"
                        self._save_learning('deadline_passed', ticker, result, learning_note)

                        return result

                    # Check for extension
                    if 'extend' in filing_text.lower() and ('deadline' in filing_text.lower() or 'termination date' in filing_text.lower()):
                        # Extract new deadline date
                        date_patterns = [
                            r'(?:deadline|termination\s+date|extended?\s+to|extended?\s+until)\s+.*?(\w+\s+\d{1,2},\s+\d{4})',
                            r'(\w+\s+\d{1,2},\s+\d{4})\s+.*?(?:deadline|termination\s+date)',
                        ]

                        for pattern in date_patterns:
                            matches = re.findall(pattern, filing_text, re.IGNORECASE)
                            if matches:
                                try:
                                    date_str = matches[0]
                                    for fmt in ['%B %d, %Y', '%b %d, %Y']:
                                        try:
                                            parsed_date = datetime.strptime(date_str, fmt)
                                            if parsed_date > datetime.now():
                                                result['extension_found'] = True
                                                result['new_deadline'] = parsed_date.date()
                                                result['source_filing'] = f"{filing_type} filed {filing_date.strftime('%Y-%m-%d')}"
                                                result['should_update'] = True

                                                print(f"   ✅ Extension found in {filing_type}!")
                                                print(f"      New deadline: {result['new_deadline']}")
                                                print(f"      Source: {result['source_filing']}")

                                                # Save learning
                                                learning_note = f"Deadline extension found in {filing_type} for {ticker}, new deadline: {result['new_deadline']}"
                                                self._save_learning('deadline_passed', ticker, result, learning_note)

                                                return result
                                        except ValueError:
                                            continue
                                except Exception:
                                    continue

                    # Check for completion
                    completion_keywords = [
                        'business combination was consummated',
                        'closing of the business combination',
                        'merger was completed',
                        'transaction closed',
                        'combination has been consummated'
                    ]
                    if any(keyword in filing_text.lower() for keyword in completion_keywords):
                        result['completion_found'] = True
                        result['source_filing'] = f"{filing_type} filed {filing_date.strftime('%Y-%m-%d')}"
                        result['should_update'] = True

                        print(f"   ✅ Deal completion found in {filing_type}")

                        # Save learning
                        learning_note = f"Deal completion confirmed in {filing_type} for {ticker}"
                        self._save_learning('deadline_passed', ticker, result, learning_note)

                        return result

                    # Check for termination
                    termination_keywords = [
                        'termination of the business combination',
                        'agreement was terminated',
                        'business combination agreement has been terminated',
                        'terminated the merger agreement',
                        'entered into liquidation'
                    ]
                    if any(keyword in filing_text.lower() for keyword in termination_keywords):
                        result['termination_found'] = True
                        result['source_filing'] = f"{filing_type} filed {filing_date.strftime('%Y-%m-%d')}"
                        result['should_update'] = True

                        print(f"   ✅ Deal termination found in {filing_type}")

                        # Save learning
                        learning_note = f"Deal termination confirmed in {filing_type} for {ticker}"
                        self._save_learning('deadline_passed', ticker, result, learning_note)

                        return result

            except Exception as e:
                print(f"      Error fetching/checking {filing_type}s: {e}")
                import traceback
                traceback.print_exc()

        print(f"   ⚠️  No extension/completion/termination found in recent filings")

        # Save learning even when nothing found (important data point!)
        learning_note = f"No extension/completion/termination found in recent SEC filings for {ticker} (checked 8-K, 425, 10-Q, Form 25)"
        self._save_learning('deadline_passed', ticker, result, learning_note)

        return result

    def investigate(self, issue: Dict, research_result: Dict, context: Dict) -> Optional[Dict]:
        """
        Full investigation workflow

        Args:
            issue: Original validation issue
            research_result: Results from research agent
            context: SPAC context

        Returns:
            Investigation report or None if no anomalies
        """
        print(f"\n{'='*80}")
        print(f"🔍 INVESTIGATION AGENT")
        print(f"{'='*80}")
        print(f"\nInvestigating: {context.get('ticker')}")
        print(f"Issue: {issue.get('message', 'Data anomaly detected')}\n")

        # Step 1: Detect anomalies
        print("1️⃣  Detecting anomalies...")
        anomalies = self.anomaly_detector.detect_anomalies(issue, research_result, context)

        if not anomalies:
            print("   ✅ No anomalies detected - research results are consistent\n")
            return None

        print(f"   ⚠️  {len(anomalies)} anomaly detected:")
        for anomaly in anomalies:
            print(f"   • {anomaly['type']}: {anomaly['description']}")

        # Investigate primary anomaly
        anomaly = anomalies[0]

        # Step 2: Generate hypotheses
        print("\n2️⃣  Generating hypotheses...")
        hypotheses = self.hypothesis_generator.generate(anomaly, context)

        if not hypotheses:
            print("   ❌ Could not generate hypotheses\n")
            return None

        print(f"   Generated {len(hypotheses)} hypotheses:")
        for i, h in enumerate(hypotheses, 1):
            print(f"   {i}. {h['root_cause']} (likelihood: {h.get('likelihood', 0)}%)")

        # Step 3: Collect evidence
        print("\n3️⃣  Collecting evidence...")
        top_hypothesis = hypotheses[0]
        evidence = self.evidence_collector.collect(top_hypothesis, context)
        print(f"   Collected {len(evidence)} pieces of evidence")
        for key, value in evidence.items():
            print(f"   • {key}: {value}")

        # Step 4: Diagnose
        print("\n4️⃣  Diagnosing root cause...")
        diagnosis = self.diagnoser.diagnose(hypotheses, evidence)

        if not diagnosis.get('confirmed'):
            print(f"   ❌ Could not confirm root cause\n")
            return None

        print(f"   ✅ ROOT CAUSE CONFIRMED: {diagnosis['root_cause']}")
        print(f"   Confidence: {diagnosis['confidence']}%")

        # Step 5: Apply fix
        print("\n5️⃣  Applying fix...")
        fix_result = self.fix_applier.apply(diagnosis, context)

        if not fix_result.get('fix_applied'):
            print(f"   ❌ Fix failed: {fix_result.get('error')}\n")
            return None

        print(f"   ✅ Fix applied:")
        for key, change in fix_result.get('changes', {}).items():
            print(f"   • {key}: {change}")

        # Step 6: Create prevention
        print("\n6️⃣  Creating prevention measures...")
        prevention = self.prevention_creator.create(diagnosis)
        print(f"   Created {len(prevention)} prevention measures")

        # Step 7: Document
        print("\n7️⃣  Documenting investigation...")
        report = self._document_investigation(
            anomaly=anomaly,
            hypotheses=hypotheses,
            evidence=evidence,
            diagnosis=diagnosis,
            fix_result=fix_result,
            prevention=prevention,
            context=context
        )

        print(f"   ✅ Investigation complete")
        print(f"   Report: /logs/investigation_{report['id']}.json\n")

        return report

    def _document_investigation(self, **kwargs) -> Dict:
        """Generate and save investigation report"""

        investigation_id = hashlib.md5(
            f"{kwargs['context']['ticker']}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        report = {
            'id': investigation_id,
            'timestamp': datetime.now().isoformat(),
            'ticker': kwargs['context']['ticker'],
            'anomaly': kwargs['anomaly'],
            'hypotheses': kwargs['hypotheses'],
            'evidence': kwargs['evidence'],
            'diagnosis': {
                'root_cause': kwargs['diagnosis']['root_cause'],
                'confidence': kwargs['diagnosis']['confidence']
            },
            'fix_applied': kwargs['fix_result'],
            'prevention_measures': kwargs['prevention'],
            'status': 'RESOLVED'
        }

        # Save to file
        os.makedirs('logs', exist_ok=True)
        with open(f'logs/investigation_{investigation_id}.json', 'w') as f:
            json.dump(report, f, indent=2, default=str)

        # Send Telegram alert
        self._send_alert(report)

        return report

    def _send_alert(self, report: Dict):
        """Send Telegram alert about investigation"""

        ticker = report['ticker']
        root_cause = report['diagnosis']['root_cause']
        changes = report['fix_applied'].get('changes', {})

        message = f"🔍 <b>AUTONOMOUS INVESTIGATION COMPLETE</b>\n\n"
        message += f"<b>Ticker:</b> {ticker}\n"
        message += f"<b>Root Cause:</b> {root_cause}\n"
        message += f"<b>Confidence:</b> {report['diagnosis']['confidence']}%\n\n"

        message += f"<b>Fix Applied:</b>\n"
        for key, change in changes.items():
            message += f"  • {key}: {change}\n"

        message += f"\n<b>Prevention:</b> {len(report['prevention_measures'])} measures created\n"
        message += f"\n📄 Report: /logs/investigation_{report['id']}.json"

        send_telegram_alert(message)

    def investigate_code_error(self, error_id: int) -> Optional[Dict]:
        """
        Investigate a code error using AI hypothesis generation

        NEW: Code error investigation for TypeErrors, AttributeErrors, etc.
        Uses AI to analyze error, generate hypotheses, and suggest fixes.

        Args:
            error_id: ID from code_errors table

        Returns:
            Investigation report with suggested fixes
        """
        from database import SessionLocal, CodeError

        db = SessionLocal()
        try:
            error = db.query(CodeError).filter(CodeError.id == error_id).first()

            if not error:
                print(f"❌ Error ID {error_id} not found")
                return None

            print(f"\n{'='*80}")
            print(f"CODE ERROR INVESTIGATION - Error #{error_id}")
            print(f"{'='*80}")
            print(f"Type: {error.error_type}")
            print(f"Script: {error.script} → {error.function}()")
            print(f"Message: {error.error_message}")
            if error.ticker:
                print(f"Ticker: {error.ticker}")
            print()

            # Generate hypotheses using AI
            prompt = f"""Analyze this code error and suggest fixes.

**Error Type:** {error.error_type}
**Error Message:** {error.error_message}
**Script:** {error.script}
**Function:** {error.function}
**Ticker:** {error.ticker or 'N/A'}

**Traceback:**
```
{error.traceback}
```

Generate 2-3 likely root causes and fixes. For each hypothesis:
1. **root_cause**: What's causing the error (be specific)
2. **likelihood**: Probability 0-100%
3. **fix**: Exact code change needed (use code snippets)
4. **file_location**: Which file to modify
5. **verification**: How to test the fix

Respond with ONLY valid JSON (no markdown, no code blocks):
{{
  "hypotheses": [
    {{
      "rank": 1,
      "likelihood": 90,
      "root_cause": "Type mismatch between datetime and date objects in comparison",
      "fix": "Normalize dates before comparison: filing_date.date() if isinstance(filing_date, datetime) else filing_date",
      "file_location": "utils/trust_account_tracker.py:103",
      "verification": "Test with AEXA ticker that triggers datetime comparison path"
    }}
  ]
}}
"""

            print("🤖 Generating hypotheses with AI...")
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert Python debugger. Analyze errors and suggest precise fixes. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON (remove markdown if present)
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()

            result = json.loads(result_text)
            hypotheses = result.get('hypotheses', [])

            if not hypotheses:
                print("⚠️  No hypotheses generated")
                return None

            print(f"✅ Generated {len(hypotheses)} hypotheses\n")

            # Display hypotheses
            for i, hyp in enumerate(hypotheses, 1):
                print(f"Hypothesis {i} (Likelihood: {hyp.get('likelihood', 0)}%)")
                print(f"  Root Cause: {hyp.get('root_cause', 'Unknown')}")
                print(f"  Fix: {hyp.get('fix', 'N/A')}")
                print(f"  File: {hyp.get('file_location', 'N/A')}")
                print()

            # Send Telegram notification
            self._send_code_error_alert(error, hypotheses)

            # Update error record
            error.investigated = True
            error.investigation_notes = json.dumps(hypotheses, indent=2)
            db.commit()

            print(f"✅ Investigation complete - sent to Telegram for review")
            print(f"{'='*80}\n")

            return {
                'error_id': error_id,
                'hypotheses': hypotheses,
                'status': 'investigated'
            }

        except Exception as e:
            print(f"❌ Investigation failed: {e}")
            return None
        finally:
            db.close()

    def _send_code_error_alert(self, error, hypotheses: List[Dict]):
        """Send Telegram alert with code error investigation results"""

        # Build message
        message = f"🐛 <b>CODE ERROR INVESTIGATION</b>\n\n"
        message += f"<b>Error #{error.id}:</b> {error.error_type}\n"
        message += f"<b>Script:</b> {error.script} → {error.function}()\n"
        message += f"<b>Message:</b> {error.error_message[:200]}\n"
        if error.ticker:
            message += f"<b>Ticker:</b> {error.ticker}\n"
        message += f"\n<b>🤖 AI Analysis:</b>\n\n"

        for i, hyp in enumerate(hypotheses[:2], 1):  # Show top 2
            message += f"<b>Hypothesis {i}</b> (Likelihood: {hyp.get('likelihood', 0)}%)\n"
            message += f"<b>Root Cause:</b> {hyp.get('root_cause', 'Unknown')[:300]}\n"
            message += f"<b>Fix:</b>\n<code>{hyp.get('fix', 'N/A')[:400]}</code>\n"
            message += f"<b>File:</b> {hyp.get('file_location', 'N/A')}\n\n"

        message += f"---\n"
        message += f"<b>⚠️ Action Required:</b> Review and apply suggested fix\n"

        try:
            send_telegram_alert(message)
            print("   ✅ Telegram alert sent")
        except Exception as e:
            print(f"   ⚠️  Telegram alert failed: {e}")

    def close(self):
        """Cleanup"""
        self.fix_applier.close()


if __name__ == "__main__":
    # Test with OBA scenario
    agent = InvestigationAgent()

    # Simulate OBA issue
    issue = {
        'ticker': 'OBA',
        'message': 'Status is ANNOUNCED but target is missing'
    }

    research_result = {
        'deal_found': True,
        'announced_date': datetime(2014, 9, 19),
        'target': None,
        'source_filing': 'https://www.sec.gov/...'
    }

    context = {
        'ticker': 'OBA',
        'company': 'Oxley Bridge Acquisition Limited',
        'cik': '0001471088',
        'ipo_date': datetime(2025, 6, 26),
        'deal_status': 'ANNOUNCED'
    }

    try:
        report = agent.investigate(issue, research_result, context)

        if report:
            print(f"\n✅ Investigation successful!")
            print(f"Root cause: {report['diagnosis']['root_cause']}")
        else:
            print(f"\n❌ Investigation inconclusive")
    finally:
        agent.close()
