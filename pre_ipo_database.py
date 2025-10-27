#!/usr/bin/env python3
"""
Pre-IPO SPAC Database Schema
Tracks SPACs from S-1 filing through IPO close
"""

from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

class PreIPOSPAC(Base):
    """Pre-IPO SPACs tracked from S-1 filing until IPO close"""
    __tablename__ = 'pre_ipo_spacs'

    # Core identification
    id = Column(Integer, primary_key=True, index=True)
    company = Column(String, nullable=False, index=True)  # "Acme Acquisition Corp"
    expected_ticker = Column(String, index=True)  # Proposed ticker from S-1
    cik = Column(String, index=True)  # SEC CIK number

    # Filing information
    s1_filing_date = Column(Date, index=True)  # Initial S-1 filing date
    latest_s1a_date = Column(Date)  # Most recent S-1/A amendment
    amendment_count = Column(Integer, default=0)  # Number of amendments
    filing_status = Column(String, index=True)  # "S-1", "S-1/A", "Effective", "Priced", "Closed"
    effectiveness_date = Column(Date)  # When SEC declares effective

    # IPO Structure & Terms
    target_proceeds = Column(String)  # "$300M" - target raise amount
    ipo_price_range = Column(String)  # "$10.00" or "$9.75-$10.25"
    actual_ipo_price = Column(Float)  # Actual price when IPO closes
    trust_per_unit = Column(Float)  # Target NAV per unit (usually $10.00)
    units_offered = Column(Integer)  # Number of units in offering

    # Unit Structure
    unit_structure = Column(String)  # "1 share + 1/3 warrant" or "1 share + 1 right"
    warrant_ratio = Column(String)  # "1/3", "1/2", "1"
    warrant_strike = Column(Float)  # Exercise price (usually $11.50)
    has_rights = Column(Boolean, default=False)  # True if units include rights instead of warrants

    # Timeline & Deadlines
    charter_deadline_months = Column(Integer)  # Months after IPO close (18, 21, 24)
    pricing_date = Column(Date)  # When IPO prices (424B4 filed)
    ipo_close_date = Column(Date)  # When IPO actually closes (8-K filed)

    # Target & Strategy
    target_sector = Column(String)  # "Technology", "Healthcare", "Financial Services"
    target_geography = Column(String)  # "North America", "Asia-Pacific", "Global"
    target_description = Column(Text)  # Full description from S-1 of what they're looking for
    min_target_valuation = Column(String)  # Minimum size target (e.g., "$500M enterprise value")

    # Sponsor & Management
    sponsor = Column(String)  # Sponsor entity name
    sponsor_team = Column(Text)  # Key management team members
    sponsor_promote = Column(Float)  # Founder shares percentage (typically 20%)
    sponsor_track_record = Column(Text)  # Previous SPAC experience/deals

    # Banking & Legal
    lead_banker = Column(String)  # Lead underwriter/book-runner
    co_bankers = Column(String)  # Other underwriters
    legal_advisor = Column(String)  # Legal counsel
    underwriter_discount = Column(Float)  # Underwriting fee percentage

    # Financial Terms
    sponsor_capital = Column(Float)  # Capital committed by sponsor
    over_allotment = Column(Float)  # Green shoe option (usually 15%)
    private_placement_warrants = Column(Integer)  # Warrants purchased by sponsor

    # SEC URLs
    s1_url = Column(String)  # Link to initial S-1
    latest_filing_url = Column(String)  # Link to most recent filing

    # Pipeline Management
    moved_to_main_pipeline = Column(Boolean, default=False)  # True when graduated to main SPAC table
    main_spac_id = Column(Integer)  # Foreign key to SPAC table when graduated

    # Quality Indicators
    banker_tier = Column(String)  # "Bulge Bracket", "Middle Market", "Boutique"
    sponsor_quality_score = Column(Float)  # 0-100 based on track record

    # Monitoring
    last_checked = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    created_at = Column(DateTime, default=datetime.now)
    notes = Column(Text)  # Manual notes/observations


# Database connection (same as main database)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://spac_user:spacpass123@localhost:5432/spac_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_pre_ipo_db():
    """Initialize pre-IPO SPAC table (won't recreate if exists)"""
    Base.metadata.create_all(bind=engine)
    print("✅ Pre-IPO SPAC table created/verified")


if __name__ == "__main__":
    # Initialize the table
    init_pre_ipo_db()

    # Show sample usage
    db = SessionLocal()
    try:
        count = db.query(PreIPOSPAC).count()
        print(f"📊 Pre-IPO SPACs in database: {count}")

        # Show recent filings
        recent = db.query(PreIPOSPAC).order_by(
            PreIPOSPAC.s1_filing_date.desc()
        ).limit(5).all()

        if recent:
            print("\n📋 Most Recent Filings:")
            for spac in recent:
                print(f"  • {spac.company} ({spac.expected_ticker})")
                print(f"    Filed: {spac.s1_filing_date}, Status: {spac.filing_status}")
                if spac.target_sector:
                    print(f"    Target: {spac.target_sector}")
    finally:
        db.close()
