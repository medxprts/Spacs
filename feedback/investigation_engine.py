#!/usr/bin/env python3
"""
Investigation Engine - AI-Powered Root Cause Analysis
Version: 2.0.0

Simplified version of investigation_agent.py (1,353 lines → ~400 lines)
Focuses on core investigation logic, removes orchestration complexity.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()


class InvestigationEngine:
    """
    AI-powered root cause analysis for data quality issues

    Features:
    - Anomaly detection
    - Hypothesis generation
    - Evidence collection
    - Root cause diagnosis
    - Learning from past cases
    """

    def __init__(self):
        """Initialize investigation engine"""
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            self.ai_client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com"
            )
        else:
            self.ai_client = None
            print("⚠️  DEEPSEEK_API_KEY not found - investigations will be limited")

    def investigate_issue(
        self,
        issue: Dict,
        context: Dict,
        past_learnings: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Investigate a data quality issue

        Args:
            issue: Issue dictionary with problem details
            context: SPAC context (ipo_date, deal_status, etc.)
            past_learnings: Optional list of similar past cases

        Returns:
            Investigation result with root cause and proposed fix
        """
        # 1. Detect anomalies
        anomalies = self.detect_anomalies(issue, context)

        # 2. Generate hypotheses
        hypotheses = self.generate_hypotheses(anomalies, context, past_learnings)

        # 3. Test hypotheses (evidence collection)
        evidence = self.collect_evidence(hypotheses, context)

        # 4. Diagnose root cause
        diagnosis = self.diagnose_root_cause(anomalies, hypotheses, evidence)

        return {
            'anomalies': anomalies,
            'hypotheses': hypotheses,
            'evidence': evidence,
            'diagnosis': diagnosis,
            'confidence': diagnosis.get('confidence', 0.5)
        }

    def detect_anomalies(self, issue: Dict, context: Dict) -> List[Dict]:
        """
        Detect suspicious patterns in data

        Args:
            issue: Issue details
            context: SPAC context

        Returns:
            List of detected anomalies
        """
        anomalies = []

        # Anomaly 1: Temporal inconsistency (deal before IPO)
        if context.get('announced_date') and context.get('ipo_date'):
            announced = context['announced_date']
            ipo = context['ipo_date']

            if isinstance(announced, str):
                announced = datetime.fromisoformat(announced)
            if isinstance(ipo, str):
                ipo = datetime.fromisoformat(ipo)

            if announced < ipo:
                years_gap = (ipo - announced).days / 365.25
                anomalies.append({
                    'type': 'temporal_inconsistency',
                    'severity': 'CRITICAL',
                    'description': f'Deal announced {years_gap:.1f} years BEFORE IPO',
                    'evidence': {
                        'announced_date': str(announced),
                        'ipo_date': str(ipo),
                        'gap_years': round(years_gap, 1)
                    },
                    'hypothesis': 'Wrong CIK - ticker was recycled from old company'
                })

        # Anomaly 2: Trust cash exceeds IPO proceeds
        if context.get('trust_cash') and context.get('ipo_proceeds'):
            trust_cash = context['trust_cash']
            ipo_proceeds = context['ipo_proceeds']

            # Parse IPO proceeds if string
            if isinstance(ipo_proceeds, str):
                ipo_proceeds = float(ipo_proceeds.replace('$', '').replace('M', ''))
                ipo_proceeds *= 1_000_000  # Convert to dollars

            if trust_cash > ipo_proceeds * 1.05:  # 5% buffer
                anomalies.append({
                    'type': 'trust_cash_exceeds_ipo',
                    'severity': 'CRITICAL',
                    'description': f'Trust cash ${trust_cash/1e6:.1f}M exceeds IPO ${ipo_proceeds/1e6:.1f}M',
                    'evidence': {
                        'trust_cash': trust_cash,
                        'ipo_proceeds': ipo_proceeds,
                        'percent_over': round((trust_cash / ipo_proceeds - 1) * 100, 1)
                    },
                    'hypothesis': 'Circular calculation error using wrong trust_value'
                })

        # Anomaly 3: Company name mismatch
        if context.get('database_company_name') and context.get('sec_company_name'):
            db_name = context['database_company_name'].lower()
            sec_name = context['sec_company_name'].lower()

            if db_name not in sec_name and sec_name not in db_name:
                anomalies.append({
                    'type': 'company_name_mismatch',
                    'severity': 'CRITICAL',
                    'description': f'Database: "{context["database_company_name"]}" vs SEC: "{context["sec_company_name"]}"',
                    'evidence': {
                        'database_name': context['database_company_name'],
                        'sec_name': context['sec_company_name']
                    },
                    'hypothesis': 'Wrong CIK - ticker was recycled'
                })

        return anomalies

    def generate_hypotheses(
        self,
        anomalies: List[Dict],
        context: Dict,
        past_learnings: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Generate hypotheses for root causes using AI

        Args:
            anomalies: Detected anomalies
            context: SPAC context
            past_learnings: Past similar cases

        Returns:
            List of hypotheses ranked by likelihood
        """
        if not self.ai_client or not anomalies:
            # Fallback to rule-based hypotheses
            return self._generate_rule_based_hypotheses(anomalies)

        # Build prompt with past learnings
        learning_context = ""
        if past_learnings:
            learning_context = "\n**PAST LEARNINGS:**\n"
            for case in past_learnings[:5]:
                learning_context += f"- {case.get('ticker')}: {case.get('learning', 'No details')}\n"

        prompt = f"""Analyze this data quality issue and generate hypotheses for the root cause.

**Anomalies Detected:**
{self._format_anomalies(anomalies)}

**Context:**
Ticker: {context.get('ticker', 'Unknown')}
IPO Date: {context.get('ipo_date', 'Unknown')}
Deal Status: {context.get('deal_status', 'Unknown')}

{learning_context}

Generate 3-5 hypotheses ranked by likelihood. For each hypothesis:
1. Root cause description
2. Supporting evidence
3. Likelihood (0.0-1.0)
4. How to verify

Output as JSON array of hypothesis objects.
"""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a data quality investigator."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                response_format={"type": "json_object"}
            )

            import json
            result = json.loads(response.choices[0].message.content)
            return result.get('hypotheses', [])

        except Exception as e:
            print(f"⚠️  AI hypothesis generation failed: {e}")
            return self._generate_rule_based_hypotheses(anomalies)

    def _generate_rule_based_hypotheses(self, anomalies: List[Dict]) -> List[Dict]:
        """Fallback rule-based hypothesis generation"""
        hypotheses = []

        for anomaly in anomalies:
            if anomaly['type'] == 'temporal_inconsistency':
                hypotheses.append({
                    'root_cause': 'Ticker reuse - CIK points to old company',
                    'likelihood': 0.9,
                    'verification': 'Check SEC EDGAR for company name and filing history'
                })

            elif anomaly['type'] == 'trust_cash_exceeds_ipo':
                hypotheses.append({
                    'root_cause': 'Circular calculation using incorrect trust_value',
                    'likelihood': 0.85,
                    'verification': 'Check 424B4 prospectus for actual trust account value'
                })

            elif anomaly['type'] == 'company_name_mismatch':
                hypotheses.append({
                    'root_cause': 'Wrong CIK or database entry error',
                    'likelihood': 0.8,
                    'verification': 'Verify CIK matches current SPAC, not old company'
                })

        return hypotheses

    def collect_evidence(self, hypotheses: List[Dict], context: Dict) -> Dict:
        """
        Collect evidence to test hypotheses

        Args:
            hypotheses: Generated hypotheses
            context: SPAC context

        Returns:
            Evidence dictionary
        """
        evidence = {
            'sec_filings_checked': False,
            'cik_verified': False,
            'findings': []
        }

        # In real implementation, would:
        # 1. Fetch SEC filings
        # 2. Verify CIK
        # 3. Check for extensions
        # 4. Validate data sources

        # For now, return placeholder
        evidence['findings'].append({
            'source': 'investigation_engine',
            'message': 'Evidence collection requires SEC API integration'
        })

        return evidence

    def diagnose_root_cause(
        self,
        anomalies: List[Dict],
        hypotheses: List[Dict],
        evidence: Dict
    ) -> Dict:
        """
        Diagnose root cause based on anomalies, hypotheses, and evidence

        Args:
            anomalies: Detected anomalies
            hypotheses: Generated hypotheses
            evidence: Collected evidence

        Returns:
            Diagnosis with root cause and proposed fix
        """
        if not hypotheses:
            return {
                'root_cause': 'Unknown - insufficient data',
                'confidence': 0.3,
                'proposed_fix': 'Manual investigation required'
            }

        # Select most likely hypothesis
        top_hypothesis = max(hypotheses, key=lambda h: h.get('likelihood', 0))

        return {
            'root_cause': top_hypothesis.get('root_cause', 'Unknown'),
            'confidence': top_hypothesis.get('likelihood', 0.5),
            'proposed_fix': top_hypothesis.get('verification', 'Manual review'),
            'anomalies_detected': len(anomalies),
            'hypotheses_tested': len(hypotheses)
        }

    def _format_anomalies(self, anomalies: List[Dict]) -> str:
        """Format anomalies for prompt"""
        formatted = []
        for i, anomaly in enumerate(anomalies, 1):
            formatted.append(f"{i}. {anomaly['description']} (Severity: {anomaly['severity']})")
        return "\n".join(formatted)


if __name__ == "__main__":
    # Test investigation engine
    engine = InvestigationEngine()

    test_issue = {
        'ticker': 'TEST',
        'field': 'trust_cash',
        'message': 'Trust cash exceeds IPO proceeds'
    }

    test_context = {
        'ticker': 'TEST',
        'trust_cash': 454_500_000,
        'ipo_proceeds': '100M',
        'ipo_date': '2024-01-15'
    }

    result = engine.investigate_issue(test_issue, test_context)
    print(f"Investigation complete:")
    print(f"  Anomalies: {len(result['anomalies'])}")
    print(f"  Root cause: {result['diagnosis']['root_cause']}")
    print(f"  Confidence: {result['diagnosis']['confidence']}")
