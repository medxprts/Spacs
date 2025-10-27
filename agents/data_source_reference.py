"""
Data Source Reference Module

Centralized documentation of data sources and precedence rules for all agents.
Agents should consult this module to ensure they're extracting from the correct sources.

See also:
- DATA_SOURCE_MATRIX.md - Comprehensive documentation
- DATA_SOURCE_QUICK_REFERENCE.md - Quick lookup guide
- FILING_DATA_PRECEDENCE.md - Detailed precedence rules
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class DataSource:
    """Represents a data source for a specific field"""
    primary_source: str
    primary_filing_type: List[str]
    secondary_sources: List[str]
    timeliness: str  # e.g., "0-4 days", "Quarterly", "One-time"
    precedence_rule: str
    location: Optional[str] = None  # e.g., "Item 1.01", "EX-2.1"


# ============================================================================
# DEAL-RELATED DATA (Event-Based, 8-K PRIMARY)
# ============================================================================

DEAL_DATA_SOURCES = {
    'target': DataSource(
        primary_source="8-K (Item 1.01) or Form 425",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['10-Q', '10-K', 'S-4', 'DEFM14A'],
        timeliness="0-4 days after announcement",
        precedence_rule="8-K > 10-Q/10-K (8-K is more timely)",
        location="Item 1.01, EX-99.1 (press release)"
    ),
    'deal_value': DataSource(
        primary_source="8-K (Item 1.01) or Form 425",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['10-Q', 'S-4', 'DEFM14A'],
        timeliness="0-4 days after announcement",
        precedence_rule="8-K > 10-Q/10-K (8-K is more timely)",
        location="Item 1.01, EX-99.1"
    ),
    'announced_date': DataSource(
        primary_source="8-K (Item 1.01)",
        primary_filing_type=['8-K'],
        secondary_sources=['425', 'S-4'],
        timeliness="0-4 days after announcement",
        precedence_rule="Use 8-K filing date",
        location="Item 1.01"
    ),
    'sector': DataSource(
        primary_source="8-K exhibits (press release)",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['S-4', 'DEFM14A', '10-Q'],
        timeliness="0-4 days after announcement",
        precedence_rule="8-K > later filings",
        location="EX-99.1 (press release)"
    ),
    'expected_close': DataSource(
        primary_source="8-K or Form 425",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after announcement",
        precedence_rule="8-K > later filings",
        location="EX-99.1, Item 1.01"
    ),
}


# ============================================================================
# TRUST ACCOUNT DATA (Periodic, 10-Q/10-K PRIMARY)
# ============================================================================

TRUST_DATA_SOURCES = {
    'trust_cash': DataSource(
        primary_source="10-Q or 10-K (whichever is latest)",
        primary_filing_type=['10-Q', '10-K'],
        secondary_sources=['8-K (Item 9.01)', 'DEFM14A'],
        timeliness="Quarterly (45 days after quarter end)",
        precedence_rule="Latest filing date wins (10-Q Nov 15 > 10-K Feb 28 if Nov is newer)",
        location="Financial Statements - 'Cash and securities held in Trust Account'"
    ),
    'trust_value': DataSource(
        primary_source="10-Q or 10-K",
        primary_filing_type=['10-Q', '10-K'],
        secondary_sources=['8-K', 'DEFM14A'],
        timeliness="Quarterly",
        precedence_rule="Latest filing date wins",
        location="Financial Statements - NAV per share calculation"
    ),
    'shares_outstanding': DataSource(
        primary_source="10-Q or 10-K",
        primary_filing_type=['10-Q', '10-K'],
        secondary_sources=['8-K', 'DEFM14A'],
        timeliness="Quarterly",
        precedence_rule="Latest filing date wins",
        location="Financial Statements - 'Class A common stock subject to redemption'"
    ),
}


# ============================================================================
# PIPE FINANCING DATA (8-K Exhibits)
# ============================================================================

PIPE_DATA_SOURCES = {
    'pipe_size': DataSource(
        primary_source="8-K exhibits (PIPE agreement)",
        primary_filing_type=['8-K'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="8-K exhibits > later filings",
        location="EX-10.1 (PIPE subscription agreement), EX-99.1 (press release)"
    ),
    'pipe_price': DataSource(
        primary_source="8-K exhibits",
        primary_filing_type=['8-K'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="8-K exhibits > later filings",
        location="EX-10.1"
    ),
    'has_pipe': DataSource(
        primary_source="8-K (Item 3.02 or exhibits)",
        primary_filing_type=['8-K'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="8-K > later filings",
        location="Item 3.02 or EX-10.1"
    ),
}


# ============================================================================
# EARNOUT DATA (8-K Exhibits - Business Combination Agreement)
# ============================================================================

EARNOUT_DATA_SOURCES = {
    'earnout_shares': DataSource(
        primary_source="8-K exhibits (Business Combination Agreement)",
        primary_filing_type=['8-K'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="8-K exhibits > later filings",
        location="EX-2.1 (BCA), EX-99.1 (press release summary)"
    ),
    'has_earnout': DataSource(
        primary_source="8-K exhibits",
        primary_filing_type=['8-K'],
        secondary_sources=['S-4', 'DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="8-K exhibits > later filings",
        location="EX-2.1, EX-99.1"
    ),
}


# ============================================================================
# VOTE DATA (DEFM14A PRIMARY)
# ============================================================================

VOTE_DATA_SOURCES = {
    'shareholder_vote_date': DataSource(
        primary_source="DEFM14A (Definitive Merger Proxy)",
        primary_filing_type=['DEFM14A'],
        secondary_sources=['8-K (Item 8.01)', 'DEFA14A (if postponed)'],
        timeliness="20+ days before vote",
        precedence_rule="DEFA14A revised date > DEFM14A original date (if vote postponed)",
        location="Cover page, 'Notice of Special Meeting'"
    ),
    'record_date': DataSource(
        primary_source="DEFM14A",
        primary_filing_type=['DEFM14A'],
        secondary_sources=['DEFA14A'],
        timeliness="20+ days before vote",
        precedence_rule="DEFM14A > DEFA14A",
        location="Cover page, 'Notice of Special Meeting'"
    ),
}


# ============================================================================
# REDEMPTION DATA (8-K Post-Vote PRIMARY)
# ============================================================================

REDEMPTION_DATA_SOURCES = {
    'redemption_percentage': DataSource(
        primary_source="8-K (filed after vote)",
        primary_filing_type=['8-K'],
        secondary_sources=['DEFA14A (preliminary estimates)'],
        timeliness="0-4 days after vote",
        precedence_rule="Final results (8-K post-vote) > Preliminary estimates (DEFA14A pre-vote)",
        location="Item 8.01 or Item 2.01"
    ),
    'shares_redeemed': DataSource(
        primary_source="8-K (filed after vote)",
        primary_filing_type=['8-K'],
        secondary_sources=['DEFA14A'],
        timeliness="0-4 days after vote",
        precedence_rule="8-K final > DEFA14A preliminary",
        location="Item 8.01 or Item 2.01"
    ),
    'post_redemption_cash': DataSource(
        primary_source="8-K (filed after vote)",
        primary_filing_type=['8-K'],
        secondary_sources=['DEFA14A'],
        timeliness="0-4 days after vote",
        precedence_rule="8-K final > DEFA14A preliminary",
        location="Item 8.01 or Item 2.01"
    ),
}


# ============================================================================
# EXTENSION DATA (8-K Item 5.03 PRIMARY)
# ============================================================================

EXTENSION_DATA_SOURCES = {
    'deadline_date': DataSource(
        primary_source="S-1/424B4 (initial), then 8-K Item 5.03 (extensions)",
        primary_filing_type=['S-1', '424B4', '8-K'],
        secondary_sources=['DEF 14A (extension proposal)'],
        timeliness="0-4 days after extension approval",
        precedence_rule="8-K Item 5.03 > DEF 14A proposal",
        location="Item 5.03 (charter amendment)"
    ),
    'is_extended': DataSource(
        primary_source="8-K Item 5.03",
        primary_filing_type=['8-K'],
        secondary_sources=['DEF 14A'],
        timeliness="0-4 days after approval",
        precedence_rule="8-K > DEF 14A",
        location="Item 5.03"
    ),
    'extension_count': DataSource(
        primary_source="8-K Item 5.03 (incremented per extension)",
        primary_filing_type=['8-K'],
        secondary_sources=[],
        timeliness="0-4 days after approval",
        precedence_rule="Increment on each 8-K Item 5.03",
        location="Item 5.03"
    ),
}


# ============================================================================
# IPO DATA (S-1/424B4 PRIMARY - One-Time)
# ============================================================================

IPO_DATA_SOURCES = {
    'ipo_date': DataSource(
        primary_source="S-1/A (final) or 424B4",
        primary_filing_type=['424B4', 'S-1/A'],
        secondary_sources=['8-K (trading commencement)'],
        timeliness="At IPO closing",
        precedence_rule="Use closing date, not pricing date",
        location="Final prospectus"
    ),
    'ipo_price': DataSource(
        primary_source="424B4",
        primary_filing_type=['424B4'],
        secondary_sources=['S-1/A'],
        timeliness="At IPO",
        precedence_rule="424B4 > S-1/A",
        location="Final prospectus"
    ),
    'ipo_proceeds': DataSource(
        primary_source="424B4",
        primary_filing_type=['424B4'],
        secondary_sources=['8-K', 'S-1/A'],
        timeliness="At IPO",
        precedence_rule="424B4 > S-1/A",
        location="Final prospectus - gross proceeds"
    ),
}


# ============================================================================
# WARRANT TERMS (S-1/424B4 - Set at IPO, Rarely Change)
# ============================================================================

WARRANT_DATA_SOURCES = {
    'strike_price': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=['8-K (if warrant amendment)'],
        timeliness="Set at IPO",
        precedence_rule="IPO docs unless 8-K amendment filed",
        location="'Description of Warrants' section"
    ),
    'warrant_ratio': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=[],
        timeliness="Set at IPO",
        precedence_rule="IPO docs",
        location="Unit structure description"
    ),
    'expiration_years': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=[],
        timeliness="Set at IPO (usually 5 years)",
        precedence_rule="IPO docs",
        location="'Description of Warrants'"
    ),
    'redemption_price': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=['8-K (warrant call)'],
        timeliness="Set at IPO (usually $18.00)",
        precedence_rule="IPO docs unless 8-K redemption call",
        location="'Description of Warrants'"
    ),
}


# ============================================================================
# SPONSOR ECONOMICS (S-1/424B4 - Set at IPO)
# ============================================================================

SPONSOR_DATA_SOURCES = {
    'sponsor_promote': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=['10-K', 'DEFM14A'],
        timeliness="Set at IPO (usually 20%)",
        precedence_rule="IPO docs unless updated in 10-K",
        location="'Certain Relationships and Related Party Transactions'"
    ),
    'founder_shares': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=['10-K', 'DEFM14A'],
        timeliness="Set at IPO",
        precedence_rule="IPO docs",
        location="'Principal Stockholders' section"
    ),
    'sponsor_total_at_risk': DataSource(
        primary_source="S-1 or 424B4",
        primary_filing_type=['S-1', '424B4'],
        secondary_sources=['10-K'],
        timeliness="Set at IPO, updated if new investment",
        precedence_rule="IPO docs, then 10-K for updates",
        location="'Certain Relationships' section"
    ),
}


# ============================================================================
# PROJECTIONS DATA (Investor Presentation - 8-K/425 Exhibits)
# ============================================================================

PROJECTIONS_DATA_SOURCES = {
    'projected_revenue': DataSource(
        primary_source="Investor Presentation (8-K or 425 exhibits)",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['DEFM14A', 'S-4'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="Investor presentation > DEFM14A pro formas",
        location="EX-99.2 (investor deck PDF)"
    ),
    'projected_ebitda': DataSource(
        primary_source="Investor Presentation",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['DEFM14A', 'S-4'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="Investor presentation > DEFM14A",
        location="EX-99.2"
    ),
    'addressable_market_size': DataSource(
        primary_source="Investor Presentation",
        primary_filing_type=['8-K', '425'],
        secondary_sources=['DEFM14A'],
        timeliness="0-4 days after deal announcement",
        precedence_rule="Investor presentation",
        location="EX-99.2 ('Market Opportunity' slide)"
    ),
}


# ============================================================================
# HELPER FUNCTIONS FOR AGENTS
# ============================================================================

def get_data_source(field_name: str) -> Optional[DataSource]:
    """
    Get the data source information for a specific field

    Args:
        field_name: Database field name (e.g., 'target', 'trust_cash')

    Returns:
        DataSource object with source information, or None if not found
    """
    all_sources = {
        **DEAL_DATA_SOURCES,
        **TRUST_DATA_SOURCES,
        **PIPE_DATA_SOURCES,
        **EARNOUT_DATA_SOURCES,
        **VOTE_DATA_SOURCES,
        **REDEMPTION_DATA_SOURCES,
        **EXTENSION_DATA_SOURCES,
        **IPO_DATA_SOURCES,
        **WARRANT_DATA_SOURCES,
        **SPONSOR_DATA_SOURCES,
        **PROJECTIONS_DATA_SOURCES,
    }
    return all_sources.get(field_name)


def should_process_filing_for_field(field_name: str, filing_type: str) -> bool:
    """
    Determine if a filing type is a valid source for a specific field

    Args:
        field_name: Database field name
        filing_type: SEC filing type (e.g., '8-K', '10-Q')

    Returns:
        bool: True if this filing type can provide this field
    """
    source = get_data_source(field_name)
    if not source:
        return False

    # Check if filing type is primary or secondary source
    return filing_type in source.primary_filing_type or filing_type in source.secondary_sources


def is_primary_source(field_name: str, filing_type: str) -> bool:
    """
    Check if a filing type is the PRIMARY source for a field

    Args:
        field_name: Database field name
        filing_type: SEC filing type

    Returns:
        bool: True if this is the primary source
    """
    source = get_data_source(field_name)
    if not source:
        return False

    return filing_type in source.primary_filing_type


def get_exhibit_location(field_name: str) -> Optional[str]:
    """
    Get the exhibit location for a field (e.g., 'EX-2.1', 'EX-99.1')

    Args:
        field_name: Database field name

    Returns:
        str: Exhibit location or None
    """
    source = get_data_source(field_name)
    return source.location if source else None


def get_timeliness_guidance() -> str:
    """
    Get comprehensive timeliness guidance for agents

    Returns:
        str: Multi-line guidance string
    """
    return """
DATA TIMELINESS GUIDANCE FOR AGENTS:

1. DEAL-RELATED DATA (Events):
   PRIMARY: 8-K, 425
   WHY: Filed within 4 days of announcement (SEC requirement)
   FIELDS: target, deal_value, announced_date, pipe_size, earnout_shares, sector
   CRITICAL: 10-Q/10-K may mention same deal 30+ days later - DO NOT overwrite 8-K data

2. TRUST ACCOUNT DATA (Periodic):
   PRIMARY: 10-Q, 10-K
   WHY: Quarterly audited/reviewed financials
   FIELDS: trust_cash, trust_value, shares_outstanding, min_cash
   PRECEDENCE: Latest filing date wins (10-Q Nov > 10-K Feb if Nov is newer)

3. IPO DATA (One-Time):
   PRIMARY: S-1, 424B4
   WHY: Official IPO prospectus with final pricing
   FIELDS: ipo_date, ipo_price, unit_structure, warrant_terms, sponsor_economics
   NOTE: Set at IPO, rarely changes

4. VOTE DATA (Scheduled):
   PRIMARY: DEFM14A
   WHY: Official shareholder notice (20+ days before vote)
   FIELDS: shareholder_vote_date, record_date, vote_threshold

5. REDEMPTION DATA (Post-Event):
   PRIMARY: 8-K (post-vote)
   WHY: Final results after vote
   FIELDS: redemption_percentage, shares_redeemed, post_redemption_cash
   PRECEDENCE: Final (8-K) > Preliminary (DEFA14A)

6. EXTENSION DATA (Event):
   PRIMARY: 8-K (Item 5.03)
   WHY: Charter amendment filing (within 4 days of approval)
   FIELDS: deadline_date, is_extended, extension_count

KEY PRINCIPLE:
"8-K for events (deals, extensions), 10-Q/10-K for periodic data (trust balance),
 S-1 for IPO data (warrant terms, sponsor economics), DEFM14A for vote dates."

CRITICAL PRECEDENCE RULE:
- Deal data: 8-K (Day 0-4) > 10-Q (Day 30-45) - ALWAYS prefer 8-K for timeliness
- Trust data: 10-Q/10-K (quarterly authoritative) > 8-K (occasional mentions)
"""


# ============================================================================
# AGENT GUIDANCE STRINGS
# ============================================================================

DEAL_DETECTOR_GUIDANCE = """
You are processing a filing for deal announcement data.

PRIMARY SOURCE: 8-K (Item 1.01) or Form 425
TIMELINESS: Filed 0-4 days after deal announcement

FIELDS TO EXTRACT:
- target: Target company name
- deal_value: Transaction value
- announced_date: Deal announcement date (use filing date)
- sector: Target company industry
- expected_close: Expected closing date

EXHIBIT PRIORITY:
1. EX-99.1 - Press Release (summary, best for target name and deal value)
2. EX-2.1 - Business Combination Agreement (full legal terms)
3. EX-99.2 - Investor Presentation (strategic rationale)

PRECEDENCE RULE:
- DO NOT overwrite existing deal data from 8-K with 10-Q/10-K data
- 10-Q may mention deal 30+ days later, but 8-K is primary source
- Only update if no 8-K data exists or if this filing is newer
"""

TRUST_ACCOUNT_GUIDANCE = """
You are processing a filing for trust account data.

PRIMARY SOURCE: 10-Q or 10-K (whichever is latest)
TIMELINESS: Filed 45 days after quarter end

FIELDS TO EXTRACT:
- trust_cash: Total dollars in trust account
- trust_value: NAV per share
- shares_outstanding: Shares subject to redemption

LOCATION IN FILING:
- Balance Sheet: "Cash and securities held in Trust Account"
- Equity Section: "Class A common stock subject to redemption"
- Notes: Trust account disclosures

PRECEDENCE RULE:
- Latest filing date wins: 10-Q Nov 15 > 10-K Feb 28 (if Nov is newer)
- 10-Q/10-K > 8-K mentions (quarterly reports are authoritative)
- Always track filing_date and source for precedence validation

VALIDATION:
- Trust cash should not deviate >10% from prior quarter without explanation
- Shares outstanding should match or decrease (due to redemptions)
- NAV should be ~$10.00 (varies slightly due to interest/expenses)
"""

PIPE_EXTRACTOR_GUIDANCE = """
You are processing a filing for PIPE financing data.

PRIMARY SOURCE: 8-K exhibits (filed with deal announcement)
TIMELINESS: Filed 0-4 days after deal announcement

FIELDS TO EXTRACT:
- pipe_size: Total PIPE amount (in dollars)
- pipe_price: PIPE purchase price per share
- has_pipe: Boolean flag

EXHIBIT PRIORITY:
1. EX-10.1 - PIPE Subscription Agreement (most detailed)
2. EX-99.1 - Press Release (summary)

TYPICAL VALUES:
- PIPE price: Usually $10.00 (at NAV)
- PIPE size: $50M - $300M (varies by deal)

VALIDATION:
- PIPE price should be ~$10.00 (within $0.50)
- PIPE size should be reasonable (< deal_value)
"""

EARNOUT_EXTRACTOR_GUIDANCE = """
You are processing a filing for earnout terms.

PRIMARY SOURCE: 8-K exhibits (Business Combination Agreement)
TIMELINESS: Filed 0-4 days after deal announcement

FIELDS TO EXTRACT:
- earnout_shares: Number of earnout shares
- has_earnout: Boolean flag
- earnout_triggers: Text description of triggers

EXHIBIT PRIORITY:
1. EX-2.1 - Business Combination Agreement (full formula)
2. EX-99.1 - Press Release (summary)

TYPICAL STRUCTURE:
- Stock price triggers: e.g., "$12.50 for 20 days"
- Revenue triggers: e.g., "$100M revenue in Year 2"
- EBITDA triggers: e.g., "$25M EBITDA in Year 3"

VALIDATION:
- Earnout shares should be < 50% of total deal shares
"""


# ============================================================================
# EXHIBIT PRIORITY GUIDE
# ============================================================================

EXHIBIT_PRIORITY = {
    'deal_announcement': ['EX-99.1', 'EX-2.1', 'EX-99.2'],  # Press release, BCA, Presentation
    'pipe_data': ['EX-10.1', 'EX-99.1'],  # PIPE agreement, Press release
    'earnout_terms': ['EX-2.1', 'EX-99.1'],  # BCA, Press release
    'projections': ['EX-99.2', 'EX-99.3'],  # Investor presentation, Pro formas
}


def get_exhibit_priority_for_data_type(data_type: str) -> List[str]:
    """
    Get priority-ordered list of exhibits for a data type

    Args:
        data_type: Type of data (e.g., 'deal_announcement', 'pipe_data')

    Returns:
        List of exhibit codes in priority order
    """
    return EXHIBIT_PRIORITY.get(data_type, [])
