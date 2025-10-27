"""
Universal Filing Intelligence Agent

AI-powered comprehensive filing analyzer that:
1. Scans ANY filing type for ALL relevant SPAC data
2. Dynamically routes to specialized extraction agents
3. Ensures no data is missed regardless of filing type

Replaces narrow rule-based routing with intelligent content analysis.
"""

import os
import sys
import json
from typing import Dict, List, Optional
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC

# AI for intelligent analysis
try:
    from openai import OpenAI
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False


class UniversalFilingAnalyzer(BaseAgent):
    """
    Intelligent filing analyzer that detects ALL relevant data types

    Instead of hard-coded rules like "8-K → DealDetector only",
    this agent scans the entire filing and identifies what data exists.
    """

    def __init__(self):
        super().__init__("UniversalFilingAnalyzer")

    async def can_process(self, filing: Dict) -> bool:
        """All filings can be analyzed"""
        return True

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Analyze filing and route to appropriate agents"""
        content = filing.get('content', '')
        if not content:
            return None

        # ENHANCEMENT: Fetch and analyze exhibits if needed
        analysis = self.analyze_filing_content(filing, content)

        # If relevance is high but data extraction might be in exhibits,
        # fetch key exhibits
        if analysis['relevance_score'] > 70 and self._should_fetch_exhibits(analysis):
            print(f"   📎 High-value filing detected - fetching key exhibits...")
            exhibits = self._fetch_key_exhibits(filing)
            if exhibits:
                # Re-analyze with exhibit content included
                full_content = content + "\n\n" + "\n\n".join(exhibits.values())
                analysis = self.analyze_filing_content(filing, full_content)
                print(f"   ✓ Re-analyzed with {len(exhibits)} exhibits")

        return analysis

    def _get_filing_type_guidance(self, filing_type: str) -> str:
        """
        Provide filing-type-specific guidance to AI based on domain knowledge

        This incorporates learnings from rule-based classification
        """
        guidance_map = {
            '8-K': """
8-K = Current Report (filed within 4 days of material event)

⏱️ TIMELINESS: This is the MOST TIMELY source for deal-related data.
   8-K filed within 4 days of announcement → HIGHEST PRIORITY for deal data
   (10-Q/10-K may discuss same deal weeks/months later → LOWER PRIORITY)

KEY THINGS TO LOOK FOR:
- Item 1.01: Entry into Material Definitive Agreement → DEAL ANNOUNCEMENT
- Item 1.02: Termination of Material Definitive Agreement → DEAL TERMINATION
- Item 2.01: Completion of Acquisition → DEAL COMPLETED
- Item 3.02: Unregistered Sales of Equity → PIPE FINANCING
- Item 5.02: Departure/Election of Directors → MANAGEMENT CHANGES
- Item 5.03: Amendments to Charter → DEADLINE EXTENSION
- Item 8.01: Other Events → Check for vote dates, redemption data
- Item 9.01: Financial Statements → May include trust account updates

COMMON SCENARIOS:
- Deal announcement: Look for target name, deal value, vote date, PIPE terms
- Extension: Look for new deadline date, sponsor deposit
- Redemption results: Look for shares redeemed, % redeemed, post-redemption cash

DATA PRECEDENCE:
- Deal data (target, deal_value, vote_date, PIPE) → 8-K is PRIMARY SOURCE
- Trust account data → SECONDARY SOURCE (prefer 10-Q/10-K quarterly updates)
""",
            '425': """
Form 425 = Communications about Business Combinations

ALWAYS CONTAINS:
- Deal announcement or update
- Target company information
- Deal rationale and strategic benefits
- Often includes press releases

LOOK FOR:
- Deal terms (value, structure)
- Shareholder vote dates
- PIPE investor names
- Pro forma financial projections
- Management commentary
""",
            'S-4': """
S-4 = Merger Registration Statement

COMPREHENSIVE DOCUMENT - Contains almost everything:
- Complete deal structure
- Target company financials
- Pro forma combined financials
- PIPE details
- Earnout provisions
- Warrant terms
- Sponsor economics
- Vote procedures
- Redemption mechanics
- Risk factors

This is the DEFINITIVE source for deal terms.
""",
            'DEFM14A': """
DEFM14A = Definitive Merger Proxy Statement

CRITICAL DOCUMENT - Sent to shareholders before vote

ALWAYS CONTAINS:
- Shareholder vote date
- Record date for voting
- Deal terms (comprehensive)
- Redemption instructions and deadlines
- Pro forma financials
- Fairness opinions
- Board recommendations
- Sponsor/insider conflicts

LOOK FOR:
- Vote date (usually ~30 days after filing)
- Redemption deadline (usually 2 days before vote)
- Preliminary redemption numbers (if amended proxy)
""",
            'DEFA14A': """
DEFA14A = Additional Proxy Materials

Filed AFTER initial proxy (DEFM14A) with updates

COMMONLY CONTAINS:
- Updated redemption numbers
- Preliminary vote results
- Revised financial projections
- Supplemental disclosures
- Answers to shareholder questions

PRIORITIZE: redemption_data, material_updates
""",
            '10-Q': """
10-Q = Quarterly Report

⏱️ TIMELINESS: PRIMARY SOURCE for trust account data (quarterly balance updates)
   BUT SECONDARY SOURCE for deal data (8-K is more timely for deal announcements)

ALWAYS CONTAINS (in Financial Statements):
- Trust account balance
- Shares outstanding (subject to redemption)
- Warrant liability
- Related party transactions
- Working capital

LOOK FOR:
- "Cash and securities held in Trust Account": trust_cash
- "Class A common stock subject to redemption": shares_outstanding
- "Warrant liability" fair value changes
- Sponsor loans or advances

MAY ALSO DISCUSS (if deal announced in quarter):
- Deal announcement details (but 8-K will be more timely source)
- PIPE terms (but 8-K will have more detail)

DATA PRECEDENCE:
- Trust account data → 10-Q is PRIMARY SOURCE (quarterly updates)
- Deal data (target, deal_value) → SECONDARY SOURCE (8-K is more timely)
- Use latest filing date: 10-Q vs 10-K, whichever is most recent
""",
            '10-K': """
10-K = Annual Report (same as 10-Q but more comprehensive)

⏱️ TIMELINESS: PRIMARY SOURCE for trust account data (annual balance update)
   BUT SECONDARY SOURCE for deal data (8-K is more timely for deal announcements)

Contains everything in 10-Q plus:
- Full year financials
- Management discussion & analysis (MD&A)
- Detailed sponsor economics
- Complete warrant terms
- Risk factors

DATA PRECEDENCE:
- Trust account data → 10-K is PRIMARY SOURCE (but 10-Q may be more recent)
- Deal data (target, deal_value) → SECONDARY SOURCE (8-K is more timely)
- Use latest filing date: 10-Q vs 10-K, whichever is most recent
""",
            'DEF 14A': """
DEF 14A = Proxy Statement (for annual meeting, NOT merger)

USUALLY CONTAINS:
- Director elections
- Executive compensation
- Governance proposals
- Extension votes
- May include deadline extension proposals

LOOK FOR:
- Meeting date
- Extension proposals (new deadline dates)
- Board changes
""",
            'SC TO': """
SC TO = Tender Offer Schedule

ALTERNATIVE DEAL STRUCTURE (no shareholder vote required)

LOOK FOR:
- Tender offer terms
- Minimum tender condition
- Expiration date
- Redemption provisions
- Deal structure (often all-cash)
""",
            'Form 25': """
Form 25 = Delisting Notification

CRITICAL EVENT - Company being delisted from exchange

SCENARIOS:
- Deal completed successfully → COMPLETED status
- Failed to find deal → LIQUIDATED status
- Voluntary delisting

ALWAYS UPDATE: completion_terms or liquidation
""",
            '8-K/A': """
8-K/A = Amendment to 8-K

IMPORTANT: May contain corrections or updates

COMMONLY FIXES:
- Deal values
- Vote dates
- Financial statements
- Exhibit corrections

PRIORITIZE: material_updates flag
""",
            'S-1': """
S-1 = IPO Registration

POTENTIAL NEW SPAC

LOOK FOR:
- Company structure (is it a SPAC?)
- IPO size and pricing
- Unit structure
- Trust account terms
- Sponsor information
- Banker(s)
- Target industry focus
""",
            '424B4': """
424B4 = Final Prospectus (IPO pricing)

Filed AFTER IPO prices

CONTAINS:
- Final IPO size
- Final unit price
- Over-allotment details
- Use of proceeds
- Trust account mechanics
- Detailed unit/warrant terms
"""
        }

        return guidance_map.get(filing_type, f"No specific guidance for {filing_type} - use general analysis")

    def _should_fetch_exhibits(self, analysis: Dict) -> bool:
        """Determine if we should fetch exhibits for deeper analysis"""
        data_types = analysis.get('data_types', {})

        # Fetch exhibits if dealing with important events that have detailed docs
        return any([
            data_types.get('deal_announcement'),
            data_types.get('pipe_data'),
            data_types.get('earnout_terms'),
            data_types.get('sponsor_terms'),
            data_types.get('redemption_data')
        ])

    def _fetch_key_exhibits(self, filing: Dict) -> Dict[str, str]:
        """
        Intelligently fetch the most important exhibits

        SEC exhibit naming conventions:
        - EX-2.1 = Business Combination Agreement (KEY for deals)
        - EX-10.1 = Material contracts (PIPE agreements)
        - EX-99.1 = Press releases (Summary of deal)
        - EX-99.2 = Investor presentations
        - EX-99.3 = Pro forma financials
        """
        import requests
        from bs4 import BeautifulSoup

        exhibits = {}

        try:
            # Get filing index page
            filing_url = filing.get('url')
            if not filing_url:
                return exhibits

            response = requests.get(filing_url, headers={
                'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
            }, timeout=30)

            soup = BeautifulSoup(response.content, 'html.parser')

            # Priority exhibit types (in order of importance)
            priority_exhibits = [
                'EX-2.1',   # Business Combination Agreement
                'EX-99.1',  # Press Release
                'EX-10.1',  # PIPE Agreement
                'EX-99.2',  # Investor Presentation
                'EX-10.2',  # Additional Material Contracts
                'EX-99.3'   # Pro Forma Financials
            ]

            # Find exhibit links
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    # Check if this row contains an exhibit
                    exhibit_type = cells[3].text.strip() if len(cells) > 3 else ''

                    if any(priority in exhibit_type for priority in priority_exhibits):
                        # Found a priority exhibit - fetch it
                        link = cells[2].find('a', href=True)
                        if link:
                            exhibit_url = f"https://www.sec.gov{link['href']}"

                            # Fetch exhibit content
                            exhibit_response = requests.get(exhibit_url, headers={
                                'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
                            }, timeout=30)

                            # Extract text (limit to 50k chars per exhibit)
                            exhibit_soup = BeautifulSoup(exhibit_response.content, 'html.parser')
                            exhibit_text = exhibit_soup.get_text()[:50000]

                            exhibits[exhibit_type] = exhibit_text
                            print(f"      ✓ Fetched {exhibit_type}: {len(exhibit_text):,} chars")

                            # Stop after fetching 3 exhibits to avoid excessive API calls
                            if len(exhibits) >= 3:
                                break

        except Exception as e:
            print(f"      ⚠️  Error fetching exhibits: {e}")

        return exhibits

    def analyze_filing_content(self, filing: Dict, content: str) -> Dict:
        """
        Analyze filing content and determine what data types are present

        Returns:
            {
                'data_types': {
                    'deal_announcement': bool,
                    'vote_date': bool,
                    'redemption_data': bool,
                    'trust_account_data': bool,
                    'extension': bool,
                    'pipe_data': bool,
                    'earnout_terms': bool,
                    'warrant_terms': bool,
                    'sponsor_terms': bool,
                    'completion_terms': bool,
                    'liquidation': bool
                },
                'relevance_score': int (0-100),
                'summary': str,
                'recommended_agents': List[str]
            }
        """

        if not AI_AVAILABLE:
            print(f"   ⚠️  AI not available - falling back to keyword detection")
            return self._keyword_based_analysis(filing, content)

        try:
            # Limit to first 20k chars for analysis (full content used by extractors)
            excerpt = content[:20000]

            # Get filing-type-specific guidance from our domain knowledge
            filing_guidance = self._get_filing_type_guidance(filing.get('type'))

            prompt = f"""
Analyze this SEC filing and identify ALL data types relevant to our SPAC database.

Filing Type: {filing.get('type')}
Filing Date: {filing.get('date')}
Company: {filing.get('ticker', 'UNKNOWN')}

FILING TYPE CONTEXT:
{filing_guidance}

SCAN FOR THESE DATA TYPES (return true/false for each):

1. **deal_announcement**: Business combination agreement, merger, target company
2. **vote_date**: Shareholder meeting date, record date, voting deadline
3. **redemption_data**: Shares redeemed, redemption percentage, post-redemption cash
4. **trust_account_data**: Trust balance, shares outstanding, NAV per share
5. **extension**: Deadline extension, charter amendment, new termination date
6. **pipe_data**: PIPE size, PIPE price, PIPE investors
7. **earnout_terms**: Earnout shares, triggers, thresholds
8. **warrant_terms**: Warrant exercise price, expiration, redemption terms
9. **sponsor_terms**: Sponsor promote, founder shares, at-risk capital
10. **completion_terms**: Deal closing, ticker change, post-merger structure
11. **liquidation**: Trust liquidation, dissolution, return of capital
12. **material_updates**: Significant changes to previously disclosed terms

Also provide:
- **relevance_score** (0-100): How important is this filing for database updates?
- **summary** (1-2 sentences): What are the key updates in this filing?

Return JSON:
{{
    "data_types": {{
        "deal_announcement": true/false,
        "vote_date": true/false,
        "redemption_data": true/false,
        "trust_account_data": true/false,
        "extension": true/false,
        "pipe_data": true/false,
        "earnout_terms": true/false,
        "warrant_terms": true/false,
        "sponsor_terms": true/false,
        "completion_terms": true/false,
        "liquidation": true/false,
        "material_updates": true/false
    }},
    "relevance_score": 85,
    "summary": "Announces merger with XYZ Corp for $500M, shareholder vote on Jan 15, includes $100M PIPE"
}}

Filing Text:
{excerpt}
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing analysis expert. Identify all data types present in filings."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1  # Low temperature for consistent detection
            )

            analysis = json.loads(response.choices[0].message.content)

            # Map data types to recommended agents
            analysis['recommended_agents'] = self._map_data_types_to_agents(
                analysis.get('data_types', {})
            )

            print(f"   🔍 AI Analysis: {analysis['relevance_score']}/100 relevance")
            print(f"   📝 Summary: {analysis.get('summary', 'N/A')}")
            print(f"   🎯 Detected: {sum(analysis['data_types'].values())} data types")
            print(f"   🤖 Routing to: {len(analysis['recommended_agents'])} agents")

            return analysis

        except Exception as e:
            print(f"   ⚠️  AI analysis failed: {e}")
            return self._keyword_based_analysis(filing, content)

    def _map_data_types_to_agents(self, data_types: Dict[str, bool]) -> List[str]:
        """
        Map detected data types to specialized extraction agents

        This is the intelligence layer that routes dynamically based on content
        """
        agents = []

        if data_types.get('deal_announcement'):
            agents.append('DealDetector')

        if data_types.get('vote_date'):
            agents.append('VoteExtractor')

        if data_types.get('redemption_data'):
            agents.append('RedemptionExtractor')

        if data_types.get('trust_account_data'):
            agents.append('TrustAccountProcessor')

        if data_types.get('extension'):
            agents.append('ExtensionMonitor')

        if data_types.get('pipe_data'):
            agents.append('PIPEExtractor')

        if data_types.get('earnout_terms'):
            agents.append('EarnoutExtractor')

        if data_types.get('warrant_terms'):
            agents.append('WarrantExtractor')

        if data_types.get('sponsor_terms'):
            agents.append('SponsorExtractor')

        if data_types.get('completion_terms'):
            agents.append('CompletionMonitor')

        if data_types.get('liquidation'):
            agents.append('LiquidationDetector')

        return agents

    def _keyword_based_analysis(self, filing: Dict, content: str) -> Dict:
        """
        Fallback: keyword-based detection if AI unavailable
        Less accurate but better than nothing
        """
        content_lower = content.lower()

        data_types = {
            'deal_announcement': any(k in content_lower for k in [
                'business combination agreement',
                'merger agreement',
                'definitive agreement',
                'target company'
            ]),
            'vote_date': any(k in content_lower for k in [
                'shareholder meeting',
                'special meeting',
                'record date'
            ]),
            'redemption_data': any(k in content_lower for k in [
                'shares redeemed',
                'redemption',
                'shares tendered'
            ]),
            'trust_account_data': any(k in content_lower for k in [
                'trust account',
                'trust balance',
                'shares outstanding'
            ]),
            'extension': any(k in content_lower for k in [
                'extension',
                'charter amendment',
                'termination date'
            ]),
            'pipe_data': any(k in content_lower for k in [
                'pipe',
                'private investment',
                'concurrent financing'
            ]),
            'earnout_terms': 'earnout' in content_lower,
            'warrant_terms': 'warrant' in content_lower,
            'sponsor_terms': any(k in content_lower for k in [
                'founder shares',
                'sponsor'
            ]),
            'completion_terms': any(k in content_lower for k in [
                'closing',
                'consummation',
                'business combination completed'
            ]),
            'liquidation': any(k in content_lower for k in [
                'liquidation',
                'dissolution',
                'wind down'
            ])
        }

        relevance_score = sum(data_types.values()) * 10  # Rough estimate

        return {
            'data_types': data_types,
            'relevance_score': min(relevance_score, 100),
            'summary': 'Keyword-based analysis (AI unavailable)',
            'recommended_agents': self._map_data_types_to_agents(data_types)
        }


def test_analyzer():
    """Test the universal analyzer"""

    # Test with sample content
    sample_filing = {
        'type': '8-K',
        'date': datetime.now(),
        'ticker': 'TEST'
    }

    sample_content = """
    Business Combination Agreement

    XYZ SPAC Corp ("Company") announced today that it has entered into a definitive
    business combination agreement with ABC Technology Inc. ("ABC" or "Target").

    Transaction Terms:
    - Enterprise Value: $500 million
    - Shareholder Meeting: January 15, 2026
    - Expected Close: Q1 2026
    - PIPE: $100 million at $10.00 per share
    - Earnout: 5 million shares upon achieving $100M revenue

    As of September 30, 2025, the Company had $450 million in trust with 45 million
    shares outstanding.
    """

    analyzer = UniversalFilingAnalyzer()
    result = analyzer.analyze_filing_content(sample_filing, sample_content)

    print("\n" + "="*60)
    print("UNIVERSAL FILING ANALYZER - TEST RESULTS")
    print("="*60)
    print(json.dumps(result, indent=2))
    print("="*60)


if __name__ == '__main__':
    test_analyzer()
