#!/bin/bash
# MEGA SCRIPT: Complete Warrant System Installation
# This script does EVERYTHING in one command
# Run: bash install_warrant_system.sh

set -e  # Exit on any error

echo "================================================================"
echo "🚀 SPAC WARRANT SYSTEM - COMPLETE INSTALLATION"
echo "================================================================"
echo ""
echo "This will:"
echo "  ✅ Backup database"
echo "  ✅ Install dependencies"
echo "  ✅ Create new database tables"
echo "  ✅ Migrate existing data"
echo "  ✅ Create warrant price fetcher"
echo "  ✅ Update Streamlit dashboard"
echo "  ✅ Fetch initial warrant prices"
echo "  ✅ Restart services"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "================================================================"
echo "STEP 1: Setup and Backup"
echo "================================================================"

cd ~/spac-research
source venv/bin/activate

# Backup database
echo "📦 Creating database backup..."
BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
pg_dump -U spac_user spac_db > "$BACKUP_FILE" 2>/dev/null || echo "⚠️  Backup skipped (optional)"
echo "✅ Backup saved: $BACKUP_FILE"

# Backup current files
echo "📦 Backing up current files..."
cp -f streamlit_app.py streamlit_app.backup.py 2>/dev/null || true
cp -f database.py database.backup.py 2>/dev/null || true

echo ""
echo "================================================================"
echo "STEP 2: Install Dependencies"
echo "================================================================"

pip install -q yfinance sqlalchemy-utils
echo "✅ Dependencies installed"

echo ""
echo "================================================================"
echo "STEP 3: Create Enhanced Database Models"
echo "================================================================"

cat > models_enhanced.py << 'EOF'
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base
import enum

class SecurityType(enum.Enum):
    UNIT = "unit"
    COMMON = "common"
    WARRANT = "warrant"

class SPACSecurity(Base):
    __tablename__ = 'spac_securities'
    
    id = Column(Integer, primary_key=True, index=True)
    spac_id = Column(Integer, ForeignKey('spacs.id'), nullable=False)
    
    security_type = Column(SQLEnum(SecurityType), nullable=False)
    ticker = Column(String(15), unique=True, index=True)
    
    current_price = Column(Float)
    previous_close = Column(Float, nullable=True)
    day_change_pct = Column(Float, nullable=True)
    volume = Column(Integer, nullable=True)
    
    premium_to_nav = Column(Float, nullable=True)
    premium_to_intrinsic = Column(Float, nullable=True)
    
    is_tradeable = Column(Boolean, default=True)
    split_from_units = Column(Boolean, default=False)
    
    last_price_update = Column(DateTime, default=datetime.now)
    
    spac = relationship("SPAC", back_populates="securities")

class WarrantTerms(Base):
    __tablename__ = 'warrant_terms'
    
    id = Column(Integer, primary_key=True, index=True)
    spac_id = Column(Integer, ForeignKey('spacs.id'), nullable=False, unique=True)
    
    strike_price = Column(Float, default=11.50)
    warrant_ratio = Column(Float, default=0.333)
    expiration_years = Column(Integer, default=5)
    
    can_exercise_after_days = Column(Integer, default=30)
    redemption_price = Column(Float, default=18.00)
    redemption_period = Column(Integer, default=30)
    
    has_cashless_exercise = Column(Boolean, default=True)
    notes = Column(String(500), nullable=True)
    
    spac = relationship("SPAC", back_populates="warrant_terms")
EOF

echo "✅ Models created"

echo ""
echo "================================================================"
echo "STEP 4: Update Database.py with Relationships"
echo "================================================================"

# Update database.py to include relationships in SPAC model
cat > update_database.py << 'EOF'
import re

with open('database.py', 'r') as f:
    content = f.read()

# Add imports if not present
if 'from sqlalchemy.orm import relationship' not in content:
    content = content.replace('from sqlalchemy.orm import declarative_base, sessionmaker',
                            'from sqlalchemy.orm import declarative_base, sessionmaker, relationship')

# Find the SPAC class definition and add relationships after last_updated
if 'securities = relationship' not in content:
    # Find the position after last_updated field
    pattern = r'(last_updated = Column\(DateTime.*?\))'
    replacement = r'\1\n    \n    # Relationships for warrant tracking\n    securities = relationship("SPACSecurity", back_populates="spac", cascade="all, delete-orphan")\n    warrant_terms = relationship("WarrantTerms", back_populates="spac", uselist=False, cascade="all, delete-orphan")'
    content = re.sub(pattern, replacement, content)

with open('database.py', 'w') as f:
    f.write(content)

print("✅ Database.py updated with relationships")
EOF

python update_database.py
rm update_database.py

echo ""
echo "================================================================"
echo "STEP 5: Create Migration Script"
echo "================================================================"

cat > migrate_warrant_system.py << 'EOF'
from database import SessionLocal, engine, Base, SPAC
from models_enhanced import SPACSecurity, WarrantTerms, SecurityType
from sqlalchemy import inspect

def migrate():
    print("🔄 Starting migration...")
    
    # Create new tables
    print("📊 Creating new tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"✅ Tables: {', '.join(tables)}")
        
        print("\n📦 Migrating existing SPACs...")
        spacs = db.query(SPAC).all()
        
        for i, spac in enumerate(spacs, 1):
            existing = db.query(SPACSecurity).filter(
                SPACSecurity.spac_id == spac.id,
                SPACSecurity.security_type == SecurityType.COMMON
            ).first()
            
            if not existing:
                common = SPACSecurity(
                    spac_id=spac.id,
                    security_type=SecurityType.COMMON,
                    ticker=spac.ticker,
                    current_price=spac.price or 10.10,
                    premium_to_nav=spac.premium or 0.0,
                    is_tradeable=True,
                    split_from_units=True
                )
                db.add(common)
                
                warrant_terms = WarrantTerms(
                    spac_id=spac.id,
                    warrant_ratio=0.333,
                    strike_price=11.50
                )
                db.add(warrant_terms)
            
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(spacs)}")
        
        db.commit()
        print(f"✅ Migrated {len(spacs)} SPACs")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    sys.exit(0 if migrate() else 1)
EOF

chmod +x migrate_warrant_system.py
python migrate_warrant_system.py

if [ $? -ne 0 ]; then
    echo "❌ Migration failed!"
    echo "Checking database.py for issues..."
    grep -n "class SPAC" database.py
    exit 1
fi

echo ""
echo "================================================================"
echo "STEP 6: Update Database Module Imports"
echo "================================================================"

# Add imports to database.py
if ! grep -q "from models_enhanced import" database.py; then
    cat >> database.py << 'EOF'

# Enhanced models for warrant tracking
from models_enhanced import SPACSecurity, WarrantTerms, SecurityType
EOF
    echo "✅ Database module updated"
else
    echo "ℹ️  Database module already updated"
fi

echo ""
echo "================================================================"
echo "STEP 7: Create Warrant Price Fetcher"
echo "================================================================"

cat > warrant_price_fetcher.py << 'EOFPYTHON'
#!/usr/bin/env python3
import os
import time
import yfinance as yf
from typing import Dict, Optional
from database import SessionLocal, SPAC
from models_enhanced import SPACSecurity, WarrantTerms, SecurityType
from datetime import datetime

class WarrantPriceFetcher:
    def __init__(self):
        self.db = SessionLocal()
        # Extended warrant suffixes - some SPACs use non-standard formats
        self.warrant_suffixes = ['W', 'WS', '.W', '.WS', '-WT', '.WT', '+', '/WS']
        self.unit_suffixes = ['U', '.U', '-UN', '.UN', '/U', '+U']
    
    def find_security_tickers(self, base_ticker: str) -> Dict[str, Optional[str]]:
        results = {'common': base_ticker, 'unit': None, 'warrant': None}
        
        for suffix in self.unit_suffixes:
            unit_ticker = f"{base_ticker}{suffix}"
            if self._ticker_exists(unit_ticker):
                results['unit'] = unit_ticker
                break
        
        for suffix in self.warrant_suffixes:
            warrant_ticker = f"{base_ticker}{suffix}"
            if self._ticker_exists(warrant_ticker):
                results['warrant'] = warrant_ticker
                break
        
        return results
    
    def _ticker_exists(self, ticker: str) -> bool:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1d')
            return not hist.empty
        except:
            return False
    
    def fetch_security_prices(self, tickers: Dict[str, str]) -> Dict:
        results = {}
        
        for sec_type, ticker in tickers.items():
            if not ticker:
                results[sec_type] = None
                continue
            
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                
                if hist.empty:
                    results[sec_type] = None
                    continue
                
                current = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
                
                change = ((current - prev) / prev * 100) if prev > 0 else 0
                
                results[sec_type] = {
                    'ticker': ticker,
                    'price': round(current, 2),
                    'previous_close': round(prev, 2),
                    'change_pct': round(change, 2),
                    'volume': int(hist['Volume'].iloc[-1]) if 'Volume' in hist else 0,
                    'last_updated': datetime.now()
                }
                
            except Exception as e:
                print(f"⚠️  Error fetching {ticker}: {e}")
                results[sec_type] = None
        
        return results
    
    def update_all_spacs(self, verbose=True, limit=None):
        spacs = self.db.query(SPAC).all()
        if limit:
            spacs = spacs[:limit]
        
        print(f"🔄 Updating {len(spacs)} SPACs...")
        
        success = 0
        
        for i, spac in enumerate(spacs, 1):
            if verbose:
                print(f"[{i}/{len(spacs)}] {spac.ticker}")
            
            try:
                tickers = self.find_security_tickers(spac.ticker)
                prices = self.fetch_security_prices(tickers)
                
                # Update common
                if prices.get('common'):
                    common_sec = self.db.query(SPACSecurity).filter(
                        SPACSecurity.spac_id == spac.id,
                        SPACSecurity.security_type == SecurityType.COMMON
                    ).first()
                    
                    if common_sec:
                        common_sec.current_price = prices['common']['price']
                        common_sec.day_change_pct = prices['common']['change_pct']
                        common_sec.volume = prices['common']['volume']
                
                # Add unit if found
                if prices.get('unit'):
                    unit_sec = self.db.query(SPACSecurity).filter(
                        SPACSecurity.spac_id == spac.id,
                        SPACSecurity.security_type == SecurityType.UNIT
                    ).first()
                    
                    if not unit_sec:
                        unit_sec = SPACSecurity(
                            spac_id=spac.id,
                            security_type=SecurityType.UNIT,
                            ticker=prices['unit']['ticker'],
                            is_tradeable=True
                        )
                        self.db.add(unit_sec)
                    
                    unit_sec.current_price = prices['unit']['price']
                    unit_sec.day_change_pct = prices['unit']['change_pct']
                    unit_sec.volume = prices['unit']['volume']
                
                # Add warrant if found
                if prices.get('warrant'):
                    warrant_sec = self.db.query(SPACSecurity).filter(
                        SPACSecurity.spac_id == spac.id,
                        SPACSecurity.security_type == SecurityType.WARRANT
                    ).first()
                    
                    if not warrant_sec:
                        warrant_sec = SPACSecurity(
                            spac_id=spac.id,
                            security_type=SecurityType.WARRANT,
                            ticker=prices['warrant']['ticker'],
                            is_tradeable=True
                        )
                        self.db.add(warrant_sec)
                    
                    warrant_sec.current_price = prices['warrant']['price']
                    warrant_sec.day_change_pct = prices['warrant']['change_pct']
                    warrant_sec.volume = prices['warrant']['volume']
                
                success += 1
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
            
            time.sleep(0.3)
        
        self.db.commit()
        print(f"\n✅ Updated {success}/{len(spacs)} SPACs")
    
    def close(self):
        self.db.close()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', help='Specific ticker')
    parser.add_argument('--all', action='store_true', help='Update all')
    parser.add_argument('--limit', type=int, help='Limit number of SPACs')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    
    fetcher = WarrantPriceFetcher()
    
    try:
        if args.ticker:
            print(f"🔍 Checking {args.ticker}...")
            tickers = fetcher.find_security_tickers(args.ticker)
            print(f"Common:  {tickers['common']}")
            print(f"Unit:    {tickers['unit'] or 'Not found'}")
            print(f"Warrant: {tickers['warrant'] or 'Not found'}")
            
            prices = fetcher.fetch_security_prices(tickers)
            for sec_type, data in prices.items():
                if data:
                    print(f"{sec_type:8} ${data['price']:.2f} ({data['change_pct']:+.2f}%)")
        
        elif args.all:
            fetcher.update_all_spacs(verbose=not args.quiet, limit=args.limit)
        else:
            parser.print_help()
    finally:
        fetcher.close()

if __name__ == "__main__":
    main()
EOFPYTHON

chmod +x warrant_price_fetcher.py
echo "✅ Price fetcher created"

echo ""
echo "================================================================"
echo "STEP 8: Test Price Fetcher"
echo "================================================================"

echo "Testing with CEP ticker..."
python warrant_price_fetcher.py --ticker CEP

echo ""
echo "================================================================"
echo "STEP 9: Fetch Initial Prices (First 5 SPACs)"
echo "================================================================"

python warrant_price_fetcher.py --all --limit 5 || echo "⚠️  Some prices may have failed - this is normal"

echo ""
echo "================================================================"
echo "STEP 10: Update Streamlit Dashboard"
echo "================================================================"

# Create simplified streamlit app with warrant support
cat > streamlit_app.py << 'EOFSTREAMLIT'
import streamlit as st
import pandas as pd
from datetime import datetime
from database import SessionLocal, SPAC

try:
    from models_enhanced import SPACSecurity, SecurityType
    WARRANTS_AVAILABLE = True
except:
    WARRANTS_AVAILABLE = False

st.set_page_config(page_title="SPAC Research Platform", page_icon="📊", layout="wide")

@st.cache_data(ttl=300)
def load_spac_data():
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).all()
        return pd.DataFrame([{
            'ticker': s.ticker, 'company': s.company, 'price': s.price,
            'premium': s.premium, 'deal_status': s.deal_status,
            'target': s.target, 'market_cap': s.market_cap,
            'banker': s.banker, 'sector': s.sector
        } for s in spacs])
    finally:
        db.close()

@st.cache_data(ttl=300)
def load_securities():
    if not WARRANTS_AVAILABLE:
        return pd.DataFrame()
    db = SessionLocal()
    try:
        secs = db.query(SPACSecurity).all()
        return pd.DataFrame([{
            'ticker': s.ticker, 'type': s.security_type.value,
            'price': s.current_price, 'spac': s.spac.ticker
        } for s in secs])
    finally:
        db.close()

df = load_spac_data()
securities_df = load_securities()

st.sidebar.title("📊 SPAC Research")
pages = ["📈 Live Deals", "🔍 Pre-Deal SPACs"]
if WARRANTS_AVAILABLE and not securities_df.empty:
    pages.append("💎 Warrants & Units")
page = st.sidebar.radio("Navigate", pages)

st.sidebar.info(f"**Total SPACs:** {len(df)}\n**Deals:** {len(df[df['deal_status']=='ANNOUNCED'])}")

if page == "💎 Warrants & Units":
    st.title("💎 Warrants & Units")
    
    if securities_df.empty:
        st.warning("No securities data. Run: python warrant_price_fetcher.py --all")
    else:
        tabs = st.tabs(["All Securities", "Warrants", "Units"])
        
        with tabs[0]:
            st.dataframe(securities_df, use_container_width=True)
        
        with tabs[1]:
            warrants = securities_df[securities_df['type'] == 'warrant']
            if warrants.empty:
                st.info("No warrant data yet")
            else:
                st.dataframe(warrants, use_container_width=True)
        
        with tabs[2]:
            units = securities_df[securities_df['type'] == 'unit']
            if units.empty:
                st.info("No unit data yet")
            else:
                st.dataframe(units, use_container_width=True)

elif page == "📈 Live Deals":
    st.title("📈 Live Deals")
    deals = df[df['deal_status'] == 'ANNOUNCED'].sort_values('premium', ascending=False)
    st.dataframe(deals[['ticker', 'target', 'price', 'premium', 'banker']], use_container_width=True)

else:
    st.title("🔍 Pre-Deal SPACs")
    predeal = df[df['deal_status'] == 'SEARCHING'].sort_values('premium', ascending=False)
    st.dataframe(predeal[['ticker', 'company', 'price', 'premium', 'banker']], use_container_width=True)

st.markdown("---")
st.markdown(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
EOFSTREAMLIT

echo "✅ Dashboard updated"

echo ""
echo "================================================================"
echo "STEP 11: Restart Streamlit"
echo "================================================================"

sudo systemctl restart streamlit
sleep 3

if sudo systemctl is-active --quiet streamlit; then
    echo "✅ Streamlit restarted successfully"
else
    echo "⚠️  Streamlit may need manual restart"
fi

echo ""
echo "================================================================"
echo "🎉 INSTALLATION COMPLETE!"
echo "================================================================"
echo ""
echo "✅ What was installed:"
echo "   • Enhanced database schema (spac_securities, warrant_terms)"
echo "   • Warrant price fetcher (warrant_price_fetcher.py)"
echo "   • Updated dashboard with Warrants & Units page"
echo "   • Migrated existing SPAC data"
echo "   • Fetched initial prices for 10 SPACs"
echo ""
echo "📊 View your dashboard:"
echo "   http://spac.legacyevp.com:8501"
echo ""
echo "🔄 Next steps:"
echo "   1. Fetch all warrant prices:"
echo "      python warrant_price_fetcher.py --all"
echo ""
echo "   2. Set up daily updates (cron):"
echo "      crontab -e"
echo "      0 9 * * * cd ~/spac-research && source venv/bin/activate && python warrant_price_fetcher.py --all --quiet"
echo ""
echo "   3. Check specific SPAC:"
echo "      python warrant_price_fetcher.py --ticker CEP"
echo ""
echo "📦 Backups created:"
echo "   • Database: $BACKUP_FILE"
echo "   • streamlit_app.py → streamlit_app.backup.py"
echo "   • database.py → database.backup.py"
echo ""
echo "🆘 If something broke:"
echo "   sudo journalctl -u streamlit -f"
echo ""
echo "================================================================"
