# database.py - COMPLETE MODEL (97 COLUMNS - Phase 1+2: Added 424B4 + management + sponsor economics)

from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

class SPAC(Base):
    __tablename__ = 'spacs'
    
    # Core identification
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True, nullable=False)
    company = Column(String, nullable=False)
    
    # Pricing
    price = Column(Float)
    common_price = Column(Float)
    warrant_price = Column(Float)
    unit_price = Column(Float)
    rights_price = Column(Float)
    ipo_price = Column(Float)
    
    # Premium/Valuation
    premium = Column(Float)
    warrant_premium = Column(Float)
    tev = Column(Float)
    
    # Deal Information
    deal_status = Column(String)
    deal_status_detail = Column(String)       # Detailed status: 'RUMORED_DEAL', 'CONFIRMED_DEAL', etc.
    target = Column(String)
    rumored_target = Column(String)           # Rumored target before confirmation
    rumor_confidence = Column(Integer)        # Confidence level 0-100 for rumors
    rumor_detected_date = Column(Date)        # When rumor first detected
    accelerated_polling_until = Column(DateTime)  # Enable accelerated SEC polling until this time
    expected_close = Column(String)
    announced_date = Column(Date)
    deal_value = Column(String)
    deal_value_source = Column(String)        # Filing type that provided value (e.g., "8-K", "DEFM14A", "S-4")
    deal_value_filing_date = Column(Date)     # Date of filing that provided value
    deal_value_updated_at = Column(DateTime)  # When we last updated it
    price_at_announcement = Column(Float)
    trust_at_announcement = Column(Float)
    return_since_announcement = Column(Float)

    # Lifecycle Tracking (Completion/Termination)
    completion_date = Column(Date)           # Date deal closed (if COMPLETED)
    new_ticker = Column(String)              # Post-merger ticker symbol
    delisting_date = Column(Date)            # Date delisted from exchange
    merger_termination_date = Column(Date)   # Date merger agreement terminated
    liquidation_date = Column(Date)          # Date liquidation announced
    extension_date = Column(Date)            # Date of most recent extension
    
    # Deadlines and Timeline
    days_to_deadline = Column(Integer)
    deadline_date = Column(Date)  # Current deadline (updated after extensions)
    original_deadline_date = Column(Date)  # Original charter deadline (never changes)
    deadline_months = Column(Integer)
    redemption_deadline = Column(Date)
    shareholder_vote_date = Column(Date)
    extension_count = Column(Integer)
    is_extended = Column(Boolean)
    
    # Trust Account (CONSOLIDATED - no duplicates)
    trust_cash = Column(Float)              # Total $ in trust
    trust_cash_source = Column(String)      # Filing type that provided value (e.g., "10-Q", "10-K")
    trust_cash_filing_date = Column(Date)   # Date of filing that provided value
    trust_value = Column(Numeric(10, 2))   # Per share NAV
    trust_value_source = Column(String)     # Filing type that provided value (e.g., "10-Q", "CALCULATED")
    trust_value_filing_date = Column(Date)  # Date of filing/calculation
    shares_outstanding = Column(Float)      # Public redeemable shares
    shares_source = Column(String)          # Filing type that provided value (e.g., "424B4", "8-K", "10-Q")
    shares_filing_date = Column(Date)       # Date of filing that provided value
    founder_shares = Column(Float)          # Non-redeemable founder shares
    founder_ownership = Column(Float)       # Founder ownership %
    estimated_redemptions = Column(Float)
    post_redemption_cash = Column(Float)

    # Redemption Tracking
    redemptions_occurred = Column(Boolean)  # Whether any redemptions have occurred
    shares_redeemed = Column(Integer)       # Total shares redeemed
    redemption_amount = Column(Float)       # Total $ amount redeemed
    redemption_percentage = Column(Float)   # % of public shares redeemed
    last_redemption_date = Column(Date)     # Date of most recent redemption
    redemption_events = Column(Integer)     # Number of redemption events
    processed_redemption_dates = Column(Text)  # JSON array of redemption filing dates processed
    
    # Market Data
    market_cap = Column(Float)
    yahoo_market_cap = Column(Float)  # Yahoo Finance market cap for validation
    market_cap_variance = Column(Float)  # Variance % between our calc and Yahoo's
    volume = Column(Integer)  # Daily trading volume
    dollar_volume_24h = Column(Integer)  # Dollar volume traded (price * volume)
    volume_24h = Column(Float)
    volume_avg_30d = Column(Float)
    price_change_24h = Column(Float)
    public_float = Column(Integer)  # Shares available for public trading (shares_outstanding - founder - PP)
    volume_on_announcement_day = Column(Integer)  # Volume on deal announcement day
    volume_pct_of_float = Column(Float)  # Volume as % of public float
    
    # Risk and Classification
    risk_level = Column(String)
    sector = Column(String)
    sector_details = Column(Text)  # Detailed sector/subsector description from 424B4
    sector_classified = Column(String)  # Classified sector from AI extraction (AI, FinTech, etc.)
    sector_confidence = Column(Integer)  # Confidence score 0-100 for sector classification
    is_hot_sector = Column(Boolean, default=False)  # Whether sector is in hot narrative list
    geography = Column(String)
    banker_tier = Column(String)
    sponsor_quality_score = Column(Float)
    
    # IPO Details (NO ipo_proceeds_amount - dropped)
    ipo_date = Column(Date)
    ipo_proceeds = Column(String)          # String like "$300M"
    unit_ticker = Column(String)
    # NO common_ticker - dropped (ticker is sufficient)
    warrant_ticker = Column(String)
    right_ticker = Column(String)          # Rights ticker (similar to warrants)
    unit_structure = Column(String)
    warrant_ratio = Column(String)
    warrant_exercise_price = Column(Float)  # Warrant strike price (typically $11.50)

    # Overallotment Details (from 424B4)
    overallotment_units = Column(Float)                          # 5,400,000 units
    overallotment_percentage = Column(Float)                     # 15%
    overallotment_days = Column(Integer)                         # 45 days
    overallotment_exercised = Column(Boolean)                    # True/False/None
    shares_outstanding_base = Column(Float)                      # 36M (before overallotment)
    shares_outstanding_with_overallotment = Column(Float)        # 41.4M (after overallotment)
    overallotment_finalized_date = Column(Date)                  # When confirmed

    # Extension Terms (from 424B4)
    extension_available = Column(Boolean)                        # Can deadline be extended?
    extension_months_available = Column(Integer)                 # 3, 6, or 12 months
    extension_requires_loi = Column(Boolean)                     # Need LOI/agreement?
    extension_requires_vote = Column(Boolean)                    # Need shareholder vote?
    extension_deposit_per_share = Column(Float)                  # $0.03 - $0.10
    extension_automatic = Column(Boolean)                        # Automatic vs requires action
    max_deadline_with_extensions = Column(Integer)               # 27, 30, 36 months total

    # Warrant Terms - Enhanced (from 424B4)
    warrant_expiration_years = Column(Integer)                   # 5 years typical
    warrant_expiration_trigger = Column(Text)                    # "Business combination" or "IPO date"
    warrant_cashless_exercise = Column(Boolean)                  # Can exercise without cash
    warrant_redemption_price = Column(Float)                     # $18.00 typical
    warrant_redemption_days = Column(Text)                       # "20 trading days within a 30-trading day period"
    
    # Deal Structure
    min_cash = Column(Float)
    min_cash_percentage = Column(Float)
    pipe_size = Column(Float)
    pipe_price = Column(Float)
    pipe_percentage = Column(Float)            # PIPE size as % of trust
    pipe_lockup_months = Column(Integer)       # PIPE share lockup period in months
    has_pipe = Column(Boolean)
    earnout_shares = Column(Float)
    has_earnout = Column(Boolean)
    forward_purchase = Column(Float)
    vote_approval_threshold = Column(Float)
    
    # Parties Involved
    banker = Column(String)                # Lead investment banker
    co_bankers = Column(String)            # Other co-managers/underwriters
    sponsor = Column(String)
    sponsor_normalized = Column(String)    # Normalized sponsor name (grouped by family)
    sponsor_promote = Column(Float)
    legal_advisor = Column(String)

    # Management Team (from 424B4)
    management_team = Column(Text)                    # JSON or comma-separated list of key executives
    management_summary = Column(Text)                 # Brief backgrounds of management
    key_executives = Column(Text)                     # CEO, CFO, etc. with titles

    # Sponsor Economics (from 424B4)
    founder_shares_cost = Column(Float)               # Cost of founder shares (typically $25,000)
    private_placement_cost = Column(Float)            # Cost of private placement units
    private_placement_units = Column(Float)           # Number of private placement units
    sponsor_total_at_risk = Column(Float)             # Total sponsor capital at risk
    sponsor_at_risk_percentage = Column(Float)        # Sponsor capital as % of IPO size
    promote_vesting_type = Column(String)             # 'standard' or 'performance' based vesting
    promote_vesting_prices = Column(Text)             # JSON array of price milestones (e.g., [12.00, 15.00, 18.00])
    
    # SEC Filings (NO sec_cik - dropped)
    cik = Column(String)                   # CIK number
    latest_8k_date = Column(Date)
    latest_s4_date = Column(Date)
    proxy_filed_date = Column(Date)
    
    # Status Flags
    is_liquidating = Column(Boolean)
    alert_sent = Column(Boolean)

    # Source Document Links (with document type descriptions)
    deal_filing_url = Column(String)       # URL to 8-K/425 announcing deal
    press_release_url = Column(String)      # URL to press release (if available)
    s1_filing_url = Column(String)          # URL to S-1 IPO registration
    prospectus_424b4_url = Column(Text)     # URL to 424B4 final prospectus
    s4_filing_url = Column(String)          # URL to latest S-4 (merger registration)
    proxy_filing_url = Column(String)       # URL to DEF 14A (proxy statement)
    sec_company_url = Column(String)        # URL to SEC EDGAR company page

    # Metadata
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_scraped_at = Column(DateTime)  # Timestamp of last SEC scraper run
    last_price_update = Column(DateTime)  # Timestamp of last price update
    premium_alert_last_sent = Column(DateTime)  # Timestamp of last premium alert sent
    created_at = Column(DateTime, default=datetime.now)
    data_source = Column(String)
    notes = Column(Text)


class MarketSnapshot(Base):
    """Daily snapshot of SPAC market metrics for historical tracking"""
    __tablename__ = 'market_snapshots'

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, unique=True, nullable=False, index=True)

    # Pre-deal SPAC metrics
    avg_premium_predeal = Column(Float)
    median_premium_predeal = Column(Float)
    weighted_avg_premium_predeal = Column(Float)  # Market cap weighted average
    count_predeal = Column(Integer)

    # Announced deal metrics
    avg_premium_announced = Column(Float)
    median_premium_announced = Column(Float)
    weighted_avg_premium_announced = Column(Float)  # Market cap weighted average
    count_announced = Column(Integer)

    # Metadata
    created_at = Column(DateTime, default=datetime.now)


class UserIssue(Base):
    """User-submitted issues, bugs, and feature requests"""
    __tablename__ = 'user_issues'

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_type = Column(String(20))  # 'bug', 'feature', 'data_quality', 'other'
    title = Column(String(200))
    description = Column(Text)
    ticker_related = Column(String(10), nullable=True)  # Optional: related SPAC ticker
    page_location = Column(String(100), nullable=True)  # Which page/section the issue is on
    status = Column(String(20), default='open')  # 'open', 'in_progress', 'resolved', 'closed'
    priority = Column(String(20), default='medium')  # 'low', 'medium', 'high', 'critical'
    submitted_at = Column(DateTime, default=datetime.now)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)


class CodeError(Base):
    """Code errors detected during script execution for investigation"""
    __tablename__ = 'code_errors'

    id = Column(Integer, primary_key=True, autoincrement=True)
    error_type = Column(String(100))  # TypeError, AttributeError, etc.
    error_message = Column(Text)
    traceback = Column(Text)
    script = Column(String(255))  # Script where error occurred
    function = Column(String(255))  # Function where error occurred
    ticker = Column(String(10), nullable=True)  # Related ticker if applicable
    context = Column(Text, nullable=True)  # JSON context (args, etc.)
    detected_at = Column(DateTime, default=datetime.now)
    investigated = Column(Boolean, default=False)
    fixed = Column(Boolean, default=False)
    fix_applied_at = Column(DateTime, nullable=True)
    investigation_notes = Column(Text, nullable=True)  # AI-generated hypothesis & fix


class PriceSpikeAlert(Base):
    """Track price spike alerts sent to prevent duplicate alerts on same day"""
    __tablename__ = 'price_spike_alerts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False)
    alert_date = Column(Date, nullable=False)
    price = Column(Float)
    change_pct = Column(Float)
    created_at = Column(DateTime, default=datetime.now)


class FilingEvent(Base):
    """SEC filing events for SPAC news feed"""
    __tablename__ = 'filing_events'

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    filing_type = Column(String(20), nullable=False, index=True)  # 8-K, 424B4, S-4, DEFM14A, etc.
    filing_date = Column(Date, nullable=False, index=True)
    filing_url = Column(Text, nullable=False)
    filing_title = Column(Text)

    # Categorization
    tag = Column(String(50), index=True)  # Deal Announcement, Timeline Change, IPO Prospectus, etc.
    priority = Column(String(20))  # HIGH, MEDIUM, LOW

    # Filing details
    item_number = Column(String(20))  # For 8-Ks: 1.01, 5.03, 5.07, etc.
    summary = Column(Text)  # Brief summary of filing

    # Metadata
    detected_at = Column(DateTime, default=datetime.now, index=True)
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime)


# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://spac_user:your_password@localhost:5432/spac_db")
engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # Base connection pool (up from default 5)
    max_overflow=10,     # Additional overflow connections (default 10)
    pool_timeout=60,     # Wait up to 60s for connection (up from 30s)
    pool_pre_ping=True   # Verify connections before using (prevents stale connections)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize database (won't recreate existing tables)"""
    Base.metadata.create_all(bind=engine)
