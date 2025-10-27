#!/usr/bin/env python3
"""
Web Research Agent
Automatically investigates data quality issues using web search before sending to human

Features:
- Searches for SPAC deal announcements/terminations
- Analyzes search results with AI
- Proposes database fixes with confidence scores
- Integrates with Telegram approval workflow

Integration: Called by Data Validator Agent when issues detected
"""

import sys
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import json
import re

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC

# AI Setup
try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
except Exception as e:
    AI_AVAILABLE = False
    print(f"⚠️  AI not available: {e}")


class WebResearchAgent:
    """
    Investigates data quality issues using web search + AI analysis

    Workflow:
    1. Receive validation issue from Data Validator
    2. Construct search query based on issue type
    3. Execute web search
    4. AI analyzes results + proposes fix
    5. Return findings with confidence score
    """

    def __init__(self):
        self.search_available = True  # Claude Code has WebSearch tool
        self.ai_available = AI_AVAILABLE

    def investigate_issue(self, issue: Dict) -> Dict:
        """
        Main entry point: investigate a validation issue

        Args:
            issue: Dict with keys: ticker, rule, severity, description, field, actual, expected

        Returns:
            Dict with:
                - research_findings: str (what was found online)
                - suggested_fix: str (SQL or description of fix)
                - confidence: int (0-100)
                - sources: List[str] (URLs found)
        """
        ticker = issue.get('ticker')
        rule = issue.get('rule')
        field = issue.get('field')

        print(f"\n🔍 [WEB RESEARCH] Investigating {ticker}: {rule}")

        # Route to appropriate research method based on issue type
        if rule == 'Suspicious Data Overwrite':
            return self._research_deal_status(ticker, issue)
        elif 'target' in field.lower() or 'deal' in rule.lower():
            return self._research_deal_status(ticker, issue)
        elif 'trust' in field.lower():
            return self._research_trust_value(ticker, issue)
        elif 'deadline' in field.lower():
            return self._research_deadline(ticker, issue)
        else:
            # Generic research
            return self._generic_research(ticker, issue)

    def _research_deal_status(self, ticker: str, issue: Dict) -> Dict:
        """
        Research if SPAC has active/terminated deal

        Uses multi-query strategy for better coverage:
        1. General deal status search
        2. Recent merger/acquisition search
        3. SEC filing search
        """
        from web_search_tool import web_search

        # Get SPAC company name from database for better searches
        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            company_name = spac.company if spac else None
        finally:
            db.close()

        # Multi-query strategy for comprehensive results
        queries = []

        # Query 1: Direct ticker + deal keywords
        queries.append(f"{ticker} SPAC merger agreement deal 2025")

        # Query 2: Company name + target keywords (if available)
        if company_name:
            # Clean company name (remove "Corp", "Ltd", etc for better results)
            clean_name = company_name.replace(' Corp.', '').replace(' Ltd.', '').replace(' Inc.', '')
            queries.append(f'"{clean_name}" business combination announcement')

        # Query 3: SEC filing specific
        queries.append(f"{ticker} SEC filing 8-K merger termination")

        all_results = []

        for i, query in enumerate(queries[:2], 1):  # Limit to 2 queries to save API quota
            print(f"   Query {i}/{min(2, len(queries))}: {query}")

            try:
                results = web_search(query, max_results=5)
                if results and "not available" not in results.lower():
                    all_results.append(f"\n--- Search Query {i}: {query} ---\n{results}")
            except Exception as e:
                print(f"   ⚠️  Query {i} error: {e}")

        if not all_results:
            return {
                'research_findings': 'No search results found',
                'suggested_fix': 'Manual review required',
                'confidence': 0,
                'sources': []
            }

        # Combine all search results
        combined_results = "\n".join(all_results)

        # AI analyzes combined results
        analysis = self._analyze_with_ai(ticker, issue, combined_results)

        # ENHANCED: Verify findings against SEC filings
        try:
            from sec_verification_module import SECVerifier
            verifier = SECVerifier()
            verification = verifier.verify_deal_announcement(ticker, analysis)

            # Add SEC verification results to analysis
            analysis['sec_verified'] = verification['sec_verified']
            analysis['sec_filing_url'] = verification['sec_filing_url']
            analysis['sec_filing_date'] = verification['sec_filing_date']

            # Adjust confidence based on SEC verification
            original_confidence = analysis.get('confidence', 0)
            boost = verification['verification_confidence_boost']
            analysis['confidence'] = min(100, max(0, original_confidence + boost))

            # Update reasoning to include SEC verification
            analysis['reasoning'] += f"\n\nSEC Verification: {verification['reasoning']}"

            if verification['sec_verified']:
                print(f"   ✅ SEC VERIFIED (+{boost} confidence)")
            elif boost < 0:
                print(f"   ⚠️  SEC CONFLICT ({boost:+d} confidence)")

        except Exception as e:
            print(f"   ⚠️  SEC verification skipped: {e}")

        return analysis

    def _analyze_with_ai(self, ticker: str, issue: Dict, search_results: str) -> Dict:
        """
        Use AI to analyze search results and propose fix
        """
        if not self.ai_available:
            return {
                'research_findings': search_results[:500],
                'suggested_fix': 'AI not available - manual review required',
                'confidence': 50,
                'sources': []
            }

        prompt = f"""You are analyzing web search results to diagnose a SPAC data quality issue. Be VERY CAREFUL to read all search results thoroughly.

SPAC Ticker: {ticker}
Issue Type: {issue.get('rule')}
Problem: {issue.get('description')}
Current Database Status: {issue.get('actual')}

WEB SEARCH RESULTS (Multiple Queries):
{search_results}

ANALYSIS INSTRUCTIONS:
1. **Read ALL search results carefully** - don't just scan the first few words
2. Look for these key signals:
   - "merger agreement" / "business combination agreement" = ACTIVE DEAL
   - "terminated" / "mutual termination" = TERMINATED DEAL
   - "entered into" + recent date = NEW DEAL ANNOUNCEMENT
   - SEC filing dates (look for May/June/July 2025 = recent)
   - Specific target company names mentioned
3. **Cross-reference information** across multiple results
4. **Extract specific dates and names** when found
5. Assign confidence based on evidence quality:
   - 90-100%: Multiple sources confirm same info + SEC filing evidence
   - 75-89%: Clear evidence from credible sources
   - 60-74%: Single source or vague information
   - <60%: Conflicting or insufficient evidence

IMPORTANT RULES:
- "A SPAC III Acquisition Corp" is the FULL NAME for ticker ASPC (not a different entity!)
- If you see recent merger agreements (2025 dates), that means ACTIVE DEAL
- If ticker appears in SEC filings with "8-K" and "merger agreement", that's STRONG EVIDENCE
- Don't assume results are irrelevant just because they don't match ticker exactly
- Chinese language results (like "DA: A SPAC III...") are often valuable - they reference deals

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "findings": "Clear 2-3 sentence summary of what you found",
  "deal_status": "SEARCHING|ANNOUNCED|COMPLETED|LIQUIDATED",
  "target_company": "Exact company name from results or null",
  "deal_value": 123,
  "announced_date": "YYYY-MM-DD",
  "suggested_sql": "UPDATE spacs SET deal_status='X', target='Y', deal_value=Z, announced_date='YYYY-MM-DD' WHERE ticker='{ticker}';",
  "confidence": 85,
  "sources": ["https://url1.com", "https://url2.com"],
  "reasoning": "Why you're confident: cite specific evidence from search results"
}}

If NO evidence of a deal, return:
{{
  "findings": "No evidence of announced deal found in search results",
  "deal_status": "SEARCHING",
  "target_company": null,
  "deal_value": null,
  "announced_date": null,
  "suggested_sql": "UPDATE spacs SET deal_filing_url=NULL WHERE ticker='{ticker}';",
  "confidence": 80,
  "sources": [],
  "reasoning": "Searched multiple queries, no deal announcements found"
}}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert SPAC data analyst with deep knowledge of M&A terminology, SEC filings, and corporate announcements. Your job is to carefully read search results and extract accurate deal information. Be thorough and precise."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON from response
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())

                return {
                    'research_findings': analysis.get('findings', ''),
                    'suggested_fix': analysis.get('suggested_sql', ''),
                    'confidence': analysis.get('confidence', 0),
                    'sources': analysis.get('sources', []),
                    'deal_status': analysis.get('deal_status'),
                    'target_company': analysis.get('target_company'),
                    'deal_value': analysis.get('deal_value'),
                    'announced_date': analysis.get('announced_date'),
                    'reasoning': analysis.get('reasoning', '')
                }
            else:
                raise ValueError("Could not parse AI response as JSON")

        except Exception as e:
            print(f"   ⚠️  AI analysis error: {e}")
            return {
                'research_findings': 'AI analysis failed',
                'suggested_fix': 'Manual review required',
                'confidence': 0,
                'sources': []
            }

    def _research_trust_value(self, ticker: str, issue: Dict) -> Dict:
        """Research trust value / NAV from SEC filings or news"""
        query = f"{ticker} SPAC trust value NAV per share IPO prospectus"
        # Similar implementation to _research_deal_status
        return self._generic_research(ticker, issue, custom_query=query)

    def _research_deadline(self, ticker: str, issue: Dict) -> Dict:
        """Research deadline date from SEC filings"""
        query = f"{ticker} SPAC deadline extension liquidation date"
        return self._generic_research(ticker, issue, custom_query=query)

    def _generic_research(self, ticker: str, issue: Dict, custom_query: str = None) -> Dict:
        """Generic research for any issue type"""
        from web_search_tool import web_search

        if custom_query:
            query = custom_query
        else:
            query = f"{ticker} SPAC {issue.get('field')} {issue.get('rule')}"

        try:
            search_results = web_search(query)
            analysis = self._analyze_with_ai(ticker, issue, search_results)
            return analysis
        except Exception as e:
            return {
                'research_findings': f'Research failed: {e}',
                'suggested_fix': 'Manual review required',
                'confidence': 0,
                'sources': []
            }


class WebResearchAgentWrapper:
    """
    Orchestrator-compatible wrapper for Web Research Agent
    Implements standard agent interface
    """

    def __init__(self, agent_name: str, state_manager):
        self.agent_name = agent_name
        self.state_manager = state_manager
        self.agent = WebResearchAgent()

    def execute(self, task):
        """
        Execute web research task

        Task types:
        - investigate_issue: Research a specific validation issue
        """
        from agent_orchestrator import TaskStatus

        task.status = TaskStatus.IN_PROGRESS

        try:
            issue = task.parameters.get('issue')

            if not issue:
                task.status = TaskStatus.FAILED
                task.error = "No issue provided"
                return task

            # Perform research
            findings = self.agent.investigate_issue(issue)

            task.result = findings
            task.status = TaskStatus.COMPLETED

            print(f"   ✓ Research complete: {findings.get('confidence')}% confidence")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            print(f"   ✗ Research failed: {e}")

        return task


# Standalone test
if __name__ == "__main__":
    agent = WebResearchAgent()

    # Test issue
    test_issue = {
        'ticker': 'VACH',
        'rule': 'Suspicious Data Overwrite',
        'severity': 'HIGH',
        'field': 'deal_status',
        'description': 'SEARCHING but has deal_filing_url',
        'actual': 'SEARCHING',
        'expected': 'ANNOUNCED or null deal_filing_url'
    }

    print("🧪 Testing Web Research Agent...")
    result = agent.investigate_issue(test_issue)

    print(f"\n📊 RESULTS:")
    print(f"Findings: {result.get('research_findings')}")
    print(f"Suggested Fix: {result.get('suggested_fix')}")
    print(f"Confidence: {result.get('confidence')}%")
    print(f"Sources: {result.get('sources')}")
