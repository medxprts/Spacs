import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# Import timezone helpers
from utils.timezone_helper import (
    format_datetime, format_short_date, format_long_date,
    format_news_timestamp, now_eastern, to_eastern
)

# Import number formatting
from utils.number_parser import format_number_display

# Import the AI agent
try:
    from spac_agent import SPACAIAgent
    AGENT_AVAILABLE = True
except:
    AGENT_AVAILABLE = False

# Import database
from database import SessionLocal, SPAC, MarketSnapshot, UserIssue
from pre_ipo_database import SessionLocal as PreIPOSessionLocal, PreIPOSPAC

st.set_page_config(
    page_title="LEVP SPAC Platform",
    page_icon="📊",
    layout="wide"
)

# Initialize session state
if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []
if 'agent' not in st.session_state:
    if AGENT_AVAILABLE:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            try:
                st.session_state.agent = SPACAIAgent(api_key=api_key)
            except:
                st.session_state.agent = None
        else:
            st.session_state.agent = None
    else:
        st.session_state.agent = None

# Load premium history data
@st.cache_data(ttl=300)
def load_premium_history(days=90):
    """Load historical premium snapshots"""
    db = SessionLocal()
    try:
        from datetime import timedelta
        cutoff_date = datetime.now().date() - timedelta(days=days)

        snapshots = db.query(MarketSnapshot).filter(
            MarketSnapshot.snapshot_date >= cutoff_date
        ).order_by(MarketSnapshot.snapshot_date).all()

        data = []
        for s in snapshots:
            data.append({
                'date': s.snapshot_date,
                'avg_premium_predeal': s.avg_premium_predeal,
                'median_premium_predeal': s.median_premium_predeal,
                'weighted_avg_premium_predeal': s.weighted_avg_premium_predeal,
                'count_predeal': s.count_predeal,
                'avg_premium_announced': s.avg_premium_announced,
                'median_premium_announced': s.median_premium_announced,
                'weighted_avg_premium_announced': s.weighted_avg_premium_announced,
                'count_announced': s.count_announced
            })

        return pd.DataFrame(data)
    finally:
        db.close()

# Load data from database
@st.cache_data(ttl=300)
def load_spac_data():
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).all()
        data = []
        today = datetime.now().date()

        for s in spacs:
            # Calculate days_to_deadline dynamically
            days_left = None
            if s.deadline_date:
                deadline = s.deadline_date.date() if isinstance(s.deadline_date, datetime) else s.deadline_date
                days_left = (deadline - today).days

            data.append({
                'ticker': s.ticker,
                'company': s.company,
                'price': s.price,
                'price_change_24h': s.price_change_24h,
                'volume': s.volume,
                'premium': s.premium,
                'trust_value': s.trust_value,
                'trust_cash': s.trust_cash,
                'shares_outstanding': s.shares_outstanding,
                'founder_shares': s.founder_shares,
                'founder_ownership': s.founder_ownership,
                'deal_status': s.deal_status,
                'target': s.target,
                'expected_close': s.expected_close,
                'announced_date': to_eastern(s.announced_date),
                'completion_date': s.completion_date,
                'new_ticker': s.new_ticker,
                'shareholder_vote_date': to_eastern(s.shareholder_vote_date),
                'price_at_announcement': s.price_at_announcement,
                'return_since_announcement': s.return_since_announcement,
                'days_to_deadline': days_left,  # Calculated dynamically
                'market_cap': s.market_cap,
                'yahoo_market_cap': s.yahoo_market_cap,
                'market_cap_variance': s.market_cap_variance,
                'risk_level': s.risk_level,
                'sector': s.sector,
                'banker': s.banker,
                'co_bankers': s.co_bankers,
                'sponsor': s.sponsor,
                'deal_value': s.deal_value,
                'pipe_size': s.pipe_size,
                'pipe_price': s.pipe_price,
                'min_cash': s.min_cash,
                'ipo_date': to_eastern(s.ipo_date),
                'ipo_proceeds': s.ipo_proceeds,
                'unit_ticker': s.unit_ticker,
                'warrant_ticker': s.warrant_ticker,
                'right_ticker': s.right_ticker,
                'unit_price': s.unit_price,
                'warrant_price': s.warrant_price,
                'rights_price': s.rights_price,
                'unit_structure': s.unit_structure,
                'deadline_date': to_eastern(s.deadline_date),
                'deadline_months': s.deadline_months,
                'redemptions_occurred': s.redemptions_occurred,
                'shares_redeemed': s.shares_redeemed,
                'redemption_percentage': s.redemption_percentage,
                'redemption_amount': s.redemption_amount,
                'last_redemption_date': s.last_redemption_date,
                'latest_s4_date': to_eastern(s.latest_s4_date),
                'proxy_filed_date': to_eastern(s.proxy_filed_date),
                'last_scraped_at': to_eastern(s.last_scraped_at),
                'last_price_update': to_eastern(s.last_price_update),
                'notes': s.notes,
                # Sponsor economics
                'sponsor_total_at_risk': s.sponsor_total_at_risk,
                'sponsor_at_risk_percentage': s.sponsor_at_risk_percentage,
                # Source document URLs
                'prospectus_424b4_url': s.prospectus_424b4_url,
                'deal_filing_url': s.deal_filing_url,
                'press_release_url': s.press_release_url,
                's1_filing_url': s.s1_filing_url,
                's4_filing_url': s.s4_filing_url,
                'proxy_filing_url': s.proxy_filing_url,
                'sec_company_url': s.sec_company_url
            })
        return pd.DataFrame(data)
    finally:
        db.close()

df = load_spac_data()

# Calculate tradeable float and volume as % of float
def calculate_float_metrics(row):
    """
    Calculate public float and volume % of float

    KEY INSIGHT (Oct 20, 2025):
    For pre-deal SPACs, ALL Class A shares are freely tradeable.
    Float = shares_outstanding (no need to subtract founder/redeemed)

    Why? Class A shares are:
    - All public (sold in IPO)
    - All redeemable (can be redeemed for trust value)
    - All liquid (trade on exchange)

    Founder shares are Class B (separate, not counted in shares_outstanding)
    """
    shares_out = row.get('shares_outstanding')
    deal_status = row.get('deal_status')
    volume = row.get('volume')

    if not shares_out:
        return None, None

    # For pre-deal SPACs (SEARCHING, ANNOUNCED):
    # Float = shares_outstanding (all Class A shares are tradeable)
    if deal_status in ['SEARCHING', 'ANNOUNCED']:
        public_float = shares_out
    else:
        # For completed deals, we'd ideally use Yahoo's floatShares
        # but for now, use shares_outstanding as approximation
        public_float = shares_out

    # Volume as % of float
    volume_pct_float = (volume / public_float * 100) if volume else None

    return public_float, volume_pct_float

df['public_float'] = df.apply(lambda row: calculate_float_metrics(row)[0], axis=1)
df['volume_pct_float'] = df.apply(lambda row: calculate_float_metrics(row)[1], axis=1)

# Helper function to convert IPO proceeds string to numeric for sorting
def parse_ipo_proceeds(value):
    """Convert '$100M' or '$150,650,000' to millions (100.0, 150.65)"""
    if pd.isna(value) or not value:
        return None
    try:
        # Remove $ and commas
        cleaned = value.replace('$', '').replace(',', '')

        # If it ends with M, just remove M and convert
        if cleaned.endswith('M'):
            return float(cleaned.replace('M', ''))
        else:
            # Otherwise it's in dollars, convert to millions
            return float(cleaned) / 1_000_000
    except:
        return None

# Load pre-IPO SPAC data
# IMPORTANT: Cache disabled for debugging - re-enable with @st.cache_data(ttl=60) after confirming it works
def load_pre_ipo_data():
    db = PreIPOSessionLocal()
    try:
        spacs = db.query(PreIPOSPAC).filter(
            PreIPOSPAC.moved_to_main_pipeline == False
        ).all()
        data = []
        for s in spacs:
            data.append({
                'company': s.company,
                'expected_ticker': s.expected_ticker,
                'cik': s.cik,
                's1_filing_date': s.s1_filing_date,
                'filing_status': s.filing_status,
                'effectiveness_date': s.effectiveness_date,
                'pricing_date': s.pricing_date,
                'target_proceeds': s.target_proceeds,
                'ipo_price_range': s.ipo_price_range,
                'trust_per_unit': s.trust_per_unit,
                'unit_structure': s.unit_structure,
                'charter_deadline_months': s.charter_deadline_months,
                'target_sector': s.target_sector,
                'target_geography': s.target_geography,
                'target_description': s.target_description,
                'sponsor': s.sponsor,
                'lead_banker': s.lead_banker,
                'co_bankers': s.co_bankers,
                'amendment_count': s.amendment_count,
                's1_url': s.s1_url,
                'last_checked': to_eastern(s.last_checked)
            })
        return pd.DataFrame(data)
    finally:
        db.close()

pre_ipo_df = load_pre_ipo_data()

# Sidebar
st.sidebar.title("📊 SPAC Research")
st.sidebar.markdown("---")

page = st.sidebar.radio("Navigate", [
    "🤖 AI Chat",
    "📰 News Feed",
    "📈 Live Deals",
    "✅ Completed Deals",
    "🔍 Pre-Deal SPACs",
    "🚀 Pre-IPO Pipeline",
    "📊 Analytics",
    "⭐ Watchlist",
    "🐛 Report Issues"
])

st.sidebar.markdown("---")
st.sidebar.info(f"""
**Total SPACs:** {len(df)}
**Announced Deals:** {len(df[df['deal_status'] == 'ANNOUNCED'])}
**Completed Deals:** {len(df[df['deal_status'] == 'COMPLETED'])}
**Searching:** {len(df[df['deal_status'] == 'SEARCHING'])}

**Last Updated:** {format_datetime(now_eastern())}
""")

# ============================================================================
# PAGE: AI CHAT
# ============================================================================
if page == "🤖 AI Chat":
    st.title("🤖 AI SPAC Research Assistant")
    st.markdown("Ask me anything about SPACs in natural language!")
    
    if st.session_state.agent is None:
        st.error("⚠️ AI Agent not available. Set DEEPSEEK_API_KEY in .env file.")
    else:
        with st.expander("💡 Example Questions"):
            st.markdown("""
            - Show me all Goldman Sachs SPACs with premium over 15%
            - What are the top 5 SPACs by market cap?
            - Compare Goldman Sachs and JPMorgan Chase
            """)
        
        st.markdown("---")
        
        col1, col2 = st.columns([4, 1])
        with col1:
            user_input = st.text_input("Your question:", placeholder="Ask about SPACs...")
        with col2:
            send_button = st.button("Send 🚀")
        
        if st.button("Clear Chat"):
            st.session_state.conversation_history = []
            st.rerun()
        
        st.markdown("### 💬 Conversation")
        
        for msg in st.session_state.conversation_history:
            if msg["role"] == "user":
                st.markdown(f'**You:** {msg["content"]}')
            elif msg["role"] == "assistant" and msg.get("content"):
                st.markdown(f'**Agent:** {msg["content"]}')
        
        if send_button and user_input:
            with st.spinner("🤔 Thinking..."):
                try:
                    result = st.session_state.agent.chat(user_input, st.session_state.conversation_history)
                    st.session_state.conversation_history = result["conversation_history"]
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

# ============================================================================
# PAGE: NEWS FEED
# ============================================================================
elif page == "📰 News Feed":
    from utils.filing_logger import get_recent_filings

    st.title("📰 SPAC News Feed")
    st.markdown("Real-time SEC filings across all SPACs")

    # Sidebar filters
    st.sidebar.header("News Feed Filters")

    # Date range filter
    days_back = st.sidebar.selectbox(
        "Time Period",
        options=[7, 14, 30, 60, 90],
        index=2,  # Default to 30 days
        format_func=lambda x: f"Last {x} days",
        key="news_days"
    )

    # Tag filter
    tag_filter = st.sidebar.multiselect(
        "Filter by Event Type",
        options=[
            # Deal-related
            'Deal Announcement',
            'Deal Communication',
            'Deal Registration',
            'Deal Proxy',
            'Deal Completion',
            'Additional Deal Proxy Materials',

            # IPO-related
            'IPO Registration',
            'IPO Pricing',
            'IPO Prospectus Supplement',
            'IPO Securities Registration',
            'Exchange Listing Certification',

            # Events
            '8-K Current Report',
            'Name Change',
            'Charter Amendment',
            'Timeline Change',
            'Vote Results',
            'Redemption',
            'Extension',

            # Financial reports
            'Quarterly Report',
            'Annual Report',

            # Shareholder filings
            'Large Shareholder Filing',
            'Passive Investment Filing',

            # Other
            'Delisting Notice',
            'S-4 Effectiveness'
        ],
        default=[],
        key="news_tags"
    )

    # Priority filter
    priority_filter = st.sidebar.multiselect(
        "Filter by Priority",
        options=['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
        default=[],
        key="news_priority"
    )

    # Fetch filings
    @st.cache_data(ttl=300)  # Cache for 5 minutes
    def load_filings(days: int):
        """Load recent filings from database"""
        return get_recent_filings(days=days, limit=500)

    filings = load_filings(days_back)

    # Apply filters
    if tag_filter:
        filings = [f for f in filings if f['tag'] in tag_filter]

    if priority_filter:
        filings = [f for f in filings if f['priority'] in priority_filter]

    # Display stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Filings", len(filings))
    with col2:
        high_priority = len([f for f in filings if f['priority'] in ['CRITICAL', 'HIGH']])
        st.metric("High Priority", high_priority)
    with col3:
        deal_related = len([f for f in filings if 'Deal' in f.get('tag', '')])
        st.metric("Deal-Related", deal_related)
    with col4:
        unique_spacs = len(set(f['ticker'] for f in filings))
        st.metric("Active SPACs", unique_spacs)

    st.markdown("---")

    # Display filings
    if not filings:
        st.info("📭 No filings found. The SEC filing monitor will populate this feed automatically as it detects new filings.")
        st.markdown("""
        **How it works:**
        - The SEC filing monitor runs in the background
        - It polls the SEC every 15 minutes for new filings
        - All detected filings are automatically logged here
        - You'll see: Deal announcements, extensions, votes, proxies, and more
        """)
    else:
        # Group by date
        filings_by_date = {}
        for filing in filings:
            filing_date = filing['filing_date']
            if filing_date not in filings_by_date:
                filings_by_date[filing_date] = []
            filings_by_date[filing_date].append(filing)

        # Display grouped by date
        for filing_date in sorted(filings_by_date.keys(), reverse=True):
            st.subheader(f"📅 {format_long_date(filing_date)}")

            for filing in filings_by_date[filing_date]:
                # Priority-based styling
                if filing.get('priority') == 'CRITICAL':
                    border_color = '#f44336'
                    priority_emoji = '🔴'
                elif filing.get('priority') == 'HIGH':
                    border_color = '#ff9800'
                    priority_emoji = '🟠'
                elif filing.get('priority') == 'MEDIUM':
                    border_color = '#2196F3'
                    priority_emoji = '🔵'
                else:
                    border_color = '#9E9E9E'
                    priority_emoji = '⚪'

                # Tag-based badge colors
                tag = filing.get('tag', '8-K Current Report')
                if 'Deal' in tag:
                    tag_color = '#4CAF50'  # Green for deals
                    tag_emoji = '🤝'
                elif 'IPO' in tag or 'Pricing' in tag:
                    tag_color = '#2196F3'  # Blue for IPO
                    tag_emoji = '🎯'
                elif 'Extension' in tag or 'Timeline' in tag:
                    tag_color = '#FF9800'  # Orange for extensions
                    tag_emoji = '⏰'
                elif 'Vote' in tag or 'Proxy' in tag:
                    tag_color = '#9C27B0'  # Purple for votes
                    tag_emoji = '🗳️'
                elif 'Name Change' in tag or 'Charter' in tag:
                    tag_color = '#00BCD4'  # Cyan for name changes
                    tag_emoji = '✏️'
                elif 'Redemption' in tag:
                    tag_color = '#F44336'  # Red for redemptions
                    tag_emoji = '💰'
                elif 'Report' in tag:
                    tag_color = '#607D8B'  # Grey for reports
                    tag_emoji = '📊'
                else:
                    tag_color = '#9E9E9E'  # Default grey
                    tag_emoji = '📄'

                # Create enhanced filing card
                with st.container():
                    # Header row with ticker, tag badge, and timestamp
                    col1, col2, col3 = st.columns([2, 3, 2])

                    with col1:
                        st.markdown(f"### {filing['ticker']}")

                    with col2:
                        # Tag badge with color
                        st.markdown(f"""
                        <span style="background-color: {tag_color}; color: white; padding: 4px 12px;
                        border-radius: 12px; font-size: 14px; font-weight: 500;">
                        {tag_emoji} {tag}
                        </span>
                        """, unsafe_allow_html=True)

                    with col3:
                        st.caption(f"{priority_emoji} {format_news_timestamp(filing['detected_at'])}")

                    # Summary row (prominent display)
                    if filing.get('summary'):
                        st.markdown(f"**{filing['summary']}**")
                    else:
                        st.markdown(f"*No summary available*")

                    # Footer row with filing type and link
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.caption(f"Filing Type: {filing['filing_type']}")
                    with col2:
                        st.markdown(f"[🔗 View Filing]({filing['filing_url']})")

                    st.markdown("---")

        # Export button
        if st.button("📥 Export to CSV"):
            import pandas as pd
            from datetime import date
            df_export = pd.DataFrame(filings)
            csv = df_export.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"spac_news_{now_eastern().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

# ============================================================================
# PAGE: LIVE DEALS
# ============================================================================
elif page == "📈 Live Deals":
    st.title("📈 Live SPAC Deals")

    df_deals = df[df['deal_status'] == 'ANNOUNCED'].copy()

    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        min_premium = st.number_input("Min Premium %", value=-10.0, step=5.0)
    with col2:
        max_premium = st.number_input("Max Premium %", value=200.0, step=10.0)
    with col3:
        bankers = [b for b in df_deals['banker'].unique() if b is not None]
        banker_filter = st.selectbox("Investment Banker", ["All"] + sorted(bankers))
    with col4:
        sectors = [s for s in df_deals['sector'].unique() if s is not None]
        sector_filter = st.selectbox("Sector", ["All"] + sorted(sectors))

    df_deals = df_deals[(df_deals['premium'] >= min_premium) & (df_deals['premium'] <= max_premium)]
    if banker_filter != "All":
        df_deals = df_deals[df_deals['banker'] == banker_filter]
    if sector_filter != "All":
        df_deals = df_deals[df_deals['sector'] == sector_filter]

    # Calculate metrics AFTER filters are applied
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Deals", len(df_deals))
    with col2:
        avg_prem = df_deals['premium'].mean()
        st.metric("Avg Premium", f"+{avg_prem:.1f}%")
    with col3:
        total_deal_val = len([d for d in df_deals['deal_value'] if d and d != 'TBD'])
        st.metric("Valued Deals", total_deal_val)
    with col4:
        closing_soon = len([d for d in df_deals['days_to_deadline'] if d and d > 0 and d < 90])
        st.metric("Closing Soon", closing_soon)
    
    df_deals = df_deals.sort_values('premium', ascending=False)
    
    st.markdown(f"### 🎯 {len(df_deals)} Announced Deals")
    
    if len(df_deals) == 0:
        st.info("No deals match your filters.")
    else:
        display_df = df_deals.copy()

        # Keep all numeric columns as numbers for proper sorting
        # Formatting is done via column_config below
        display_df['Premium'] = display_df['premium']
        display_df['Price'] = display_df['price']
        display_df['% Daily Change'] = display_df['price_change_24h']

        # Keep volume as numeric for sorting (formatting handled by column_config)
        display_df['Volume'] = display_df['volume']
        display_df['Vol % Float'] = display_df['volume_pct_float']

        # Format money fields for readable display ($275.0M instead of 275000000 - consistent 1 decimal)
        display_df['Market Cap'] = display_df['market_cap'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['Days Left'] = display_df['days_to_deadline']
        display_df['Return'] = display_df['return_since_announcement']

        display_df['PIPE Size'] = display_df['pipe_size'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['PIPE Price'] = display_df['pipe_price'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else '-'
        )
        display_df['Min Cash'] = display_df['min_cash'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['Redemptions'] = display_df['redemption_percentage']
        display_df['Warrant Price'] = display_df['warrant_price']
        display_df['Unit Price'] = display_df['unit_price']
        display_df['Rights Price'] = display_df['rights_price']

        # Sponsor economics - convert to millions for display
        display_df['Sponsor Committed'] = display_df['sponsor_total_at_risk'] / 1e6 if 'sponsor_total_at_risk' in display_df else None
        display_df['Sponsor Committed %'] = display_df['sponsor_at_risk_percentage']

        # Prepare source document links (moved to far right)
        # Keep URLs for LinkColumn rendering
        display_df['prospectus_424b4_url_display'] = display_df['prospectus_424b4_url']
        display_df['deal_filing_url_display'] = display_df['deal_filing_url']
        display_df['press_release_url_display'] = display_df['press_release_url']
        display_df['s4_filing_url_display'] = display_df['s4_filing_url']
        display_df['proxy_filing_url_display'] = display_df['proxy_filing_url']
        display_df['sec_company_url_display'] = display_df['sec_company_url']

        # Keep trust_value as number for sorting
        display_df['Trust Value (NAV)'] = display_df['trust_value']

        columns_to_show = ['ticker', 'company', 'target', 'Premium', 'Price', 'Trust Value (NAV)', '% Daily Change', 'Volume', 'Vol % Float', 'Warrant Price',
                          'Unit Price', 'Rights Price', 'Return', 'Market Cap',
                          'deal_value', 'announced_date', 'latest_s4_date', 'proxy_filed_date',
                          'shareholder_vote_date', 'expected_close', 'Days Left', 'Redemptions',
                          'PIPE Size', 'PIPE Price', 'Min Cash', 'Sponsor Committed',
                          'sponsor', 'sector', 'banker', 'last_price_update', 'last_scraped_at', 'notes',
                          'prospectus_424b4_url_display', 'deal_filing_url_display', 'press_release_url_display',
                          's4_filing_url_display', 'proxy_filing_url_display', 'sec_company_url_display']

        display_df = display_df[columns_to_show].rename(columns={
            'ticker': 'Ticker',
            'company': 'Company',
            'target': 'Target Company',
            'Premium': 'Premium',  # Already renamed, keep as-is
            'Price': 'Price',  # Already renamed, keep as-is
            'Trust Value (NAV)': 'Trust Value (NAV)',  # Already renamed, keep as-is
            '% Daily Change': '% Daily Change',  # Already renamed, keep as-is
            'Volume': 'Volume',  # Already renamed, keep as-is
            'Vol % Float': 'Vol % Float',  # Already renamed, keep as-is
            'Warrant Price': 'Warrant Price',  # Already renamed, keep as-is
            'Unit Price': 'Unit Price',  # Already renamed, keep as-is
            'Rights Price': 'Rights Price',  # Already renamed, keep as-is
            'Return': 'Return',  # Already renamed, keep as-is
            'Market Cap': 'Market Cap',  # Already renamed, keep as-is
            'Days Left': 'Days Left',  # Already renamed, keep as-is
            'Redemptions': 'Redemptions',  # Already renamed, keep as-is
            'PIPE Size': 'PIPE Size',  # Already renamed, keep as-is
            'PIPE Price': 'PIPE Price',  # Already renamed, keep as-is
            'Min Cash': 'Min Cash',  # Already renamed, keep as-is
            'Sponsor Committed': 'Sponsor Committed',  # Already renamed, keep as-is
            'deal_value': 'Deal Value',
            'announced_date': 'Announced',
            'latest_s4_date': 'S-4 Filed',
            'proxy_filed_date': 'Proxy Filed',
            'shareholder_vote_date': 'Vote Date',
            'expected_close': 'Expected Close',
            'sponsor': 'Sponsor',
            'banker': 'Lead Banker',
            'sector': 'Sector',
            'last_price_update': 'Price Updated',
            'last_scraped_at': 'Data Scraped',
            'notes': 'Premium Analysis',
            'prospectus_424b4_url_display': '📕 424B4 (Prospectus)',
            'deal_filing_url_display': '📄 Deal Filing (8-K/425)',
            'press_release_url_display': '📰 Press Release',
            's4_filing_url_display': '📋 S-4 (Merger Reg)',
            'proxy_filing_url_display': '🗳️ Proxy (DEF 14A)',
            'sec_company_url_display': '🏛️ SEC Filings'
        })
        
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            column_order=['Ticker'] + [col for col in display_df.columns if col != 'Ticker'],
            column_config={
                'Ticker': st.column_config.TextColumn(width="small"),
                'Company': st.column_config.TextColumn(width="medium"),
                'Target Company': st.column_config.TextColumn(width="medium"),
                'Premium': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Trust Value (NAV)': st.column_config.NumberColumn(width="small", format="$%.2f", help="Net Asset Value per share from IPO trust account"),
                '% Daily Change': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Volume': st.column_config.NumberColumn(width="small", format="%,d"),
                'Vol % Float': st.column_config.NumberColumn(width="small", format="%.1f%%", help="Daily volume as % of public float (shares - founder shares - redemptions)"),
                'Warrant Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Unit Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Rights Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Return': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Market Cap': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'Deal Value': st.column_config.TextColumn(width="small"),  # Keep as text (has "TBD", etc.)
                'Announced': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'S-4 Filed': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Proxy Filed': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Vote Date': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Expected Close': st.column_config.TextColumn(width="medium"),  # Keep as text (dates as strings)
                'Days Left': st.column_config.NumberColumn(width="small", format="%d days"),
                'Redemptions': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'PIPE Size': st.column_config.NumberColumn(width="small", format="$%.0fM", help="Total size of PIPE financing in millions"),
                'PIPE Price': st.column_config.NumberColumn(width="small", format="$%.2f", help="Price per share for PIPE investors"),
                'Min Cash': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'Sponsor Committed': st.column_config.NumberColumn(
                    width="small",
                    format="$%.2fM",
                    help="Total sponsor capital committed at IPO (founder shares + private placement). NOTE: Only founder shares (~$25k) are truly at risk; private placement units get ~$10/unit back in liquidation."
                ),
                'Sponsor': st.column_config.TextColumn(width="medium"),
                'Sector': st.column_config.TextColumn(width="medium"),
                'Lead Banker': st.column_config.TextColumn(width="medium"),
                'Price Updated': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD HH:mm"),
                'Premium Analysis': st.column_config.TextColumn(width="large"),
                '📕 424B4 (Prospectus)': st.column_config.LinkColumn(width="medium"),
                '📄 Deal Filing (8-K/425)': st.column_config.LinkColumn(width="medium"),
                '📰 Press Release': st.column_config.LinkColumn(width="medium"),
                '📋 S-4 (Merger Reg)': st.column_config.LinkColumn(width="medium"),
                '🗳️ Proxy (DEF 14A)': st.column_config.LinkColumn(width="medium"),
                '🏛️ SEC Filings': st.column_config.LinkColumn(width="medium")
            }
        )

# ============================================================================
# PAGE: COMPLETED DEALS
# ============================================================================
elif page == "✅ Completed Deals":
    st.title("✅ Completed & Terminated Deals")
    st.markdown("Track SPAC deal outcomes: successful mergers and terminated agreements")

    # Load from deal_history table for comprehensive history
    @st.cache_data(ttl=300)
    def load_deal_history():
        from database import SessionLocal
        import pandas as pd

        db = SessionLocal()
        try:
            # Query deal_history table
            query = """
                SELECT
                    ticker, company_name, target_company, deal_value,
                    announced_date, expected_close, completion_date, termination_date,
                    deal_status, termination_reason, is_current, notes
                FROM deal_history
                ORDER BY
                    CASE
                        WHEN completion_date IS NOT NULL THEN completion_date
                        WHEN termination_date IS NOT NULL THEN termination_date
                        ELSE announced_date
                    END DESC
            """
            return pd.read_sql(query, db.bind)
        finally:
            db.close()

    df_history = load_deal_history()

    # Also get completed deals from main spacs table
    df_completed = df[df['deal_status'] == 'COMPLETED'].copy()

    # Summary metrics - combine both sources
    total_completed = len(df_completed) + len(df_history[df_history['deal_status'] == 'COMPLETED'])
    total_terminated = len(df_history[df_history['deal_status'] == 'TERMINATED'])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("✅ Completed Deals", total_completed)
    with col2:
        st.metric("❌ Terminated Deals", total_terminated)
    with col3:
        # Safely calculate this year's completions
        this_year_completed = 0
        if len(df_completed) > 0 and 'completion_date' in df_completed.columns:
            df_completed_valid = df_completed[df_completed['completion_date'].notna()].copy()
            if len(df_completed_valid) > 0:
                # Ensure completion_date is datetime64 type for comparison
                df_completed_valid['completion_date'] = pd.to_datetime(df_completed_valid['completion_date'])
                # Remove timezone for comparison (tz-naive)
                if hasattr(df_completed_valid['completion_date'].dtype, 'tz') and df_completed_valid['completion_date'].dtype.tz is not None:
                    df_completed_valid['completion_date'] = df_completed_valid['completion_date'].dt.tz_localize(None)
                year_start = pd.Timestamp(year=datetime.now().year, month=1, day=1)
                this_year_completed = len(df_completed_valid[df_completed_valid['completion_date'] >= year_start])
        st.metric("Completed This Year", this_year_completed)
    with col4:
        if len(df_history) > 0:
            # Calculate average days to close (only for completed deals)
            df_completed_history = df_history[
                (df_history['deal_status'] == 'COMPLETED') &
                (df_history['completion_date'].notna()) &
                (df_history['announced_date'].notna())
            ]
            if len(df_completed_history) > 0:
                avg_days = (df_completed_history['completion_date'] - df_completed_history['announced_date']).dt.days.mean()
                if pd.notna(avg_days):
                    st.metric("Avg Days to Close", f"{int(avg_days)} days")
                else:
                    st.metric("Avg Days to Close", "N/A")
            else:
                st.metric("Avg Days to Close", "N/A")
        else:
            st.metric("Avg Days to Close", "N/A")

    st.markdown("---")

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["✅ Completed", "❌ Terminated", "📊 All History"])

    with tab1:
        st.markdown("### Successfully Closed Mergers")
        display_df = df_completed[[
            'ticker', 'company', 'target', 'announced_date', 'completion_date',
            'new_ticker', 'deal_value', 'sector', 'banker'
        ]].copy()

        if len(display_df) > 0:
            # Ensure dates are datetime64 for arithmetic
            display_df['completion_date'] = pd.to_datetime(display_df['completion_date'], errors='coerce')
            display_df['announced_date'] = pd.to_datetime(display_df['announced_date'], errors='coerce')

            # Remove timezone for arithmetic (tz-naive)
            if hasattr(display_df['completion_date'].dtype, 'tz') and display_df['completion_date'].dtype.tz is not None:
                display_df['completion_date'] = display_df['completion_date'].dt.tz_localize(None)
            if hasattr(display_df['announced_date'].dtype, 'tz') and display_df['announced_date'].dtype.tz is not None:
                display_df['announced_date'] = display_df['announced_date'].dt.tz_localize(None)

            # Calculate days to close
            display_df['Days to Close'] = (display_df['completion_date'] - display_df['announced_date']).dt.days

            # Format dates
            display_df['Announced'] = display_df['announced_date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
            )
            display_df['Completed'] = display_df['completion_date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
            )

            # Rename and select columns
            display_df = display_df.rename(columns={
                'ticker': 'Original SPAC',
                'company': 'SPAC Name',
                'target': 'Target Company',
                'new_ticker': 'New Ticker',
                'deal_value': 'Deal Value',
                'sector': 'Sector',
                'banker': 'Banker'
            })

            final_cols = ['Original SPAC', 'Target Company', 'Announced', 'Completed',
                         'Days to Close', 'New Ticker', 'Deal Value', 'Sector', 'Banker']

            st.dataframe(display_df[final_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No completed deals found")

    with tab2:
        st.markdown("### Terminated Deal Agreements")
        df_terminated = df_history[df_history['deal_status'] == 'TERMINATED'].copy()

        if len(df_terminated) > 0:
            # Ensure dates are datetime64 for arithmetic
            df_terminated['termination_date'] = pd.to_datetime(df_terminated['termination_date'], errors='coerce')
            df_terminated['announced_date'] = pd.to_datetime(df_terminated['announced_date'], errors='coerce')

            # Calculate days before termination
            df_terminated['Days Before Termination'] = (
                df_terminated['termination_date'] - df_terminated['announced_date']
            ).dt.days

            # Format dates
            df_terminated['Announced'] = df_terminated['announced_date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
            )
            df_terminated['Terminated'] = df_terminated['termination_date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
            )

            # Select and rename columns
            display_cols = {
                'ticker': 'SPAC',
                'target_company': 'Target',
                'Announced': 'Announced',
                'Terminated': 'Terminated',
                'Days Before Termination': 'Days Active',
                'termination_reason': 'Reason',
                'deal_value': 'Deal Value'
            }

            display_df = df_terminated.rename(columns=display_cols)
            final_cols = ['SPAC', 'Target', 'Announced', 'Terminated', 'Days Active', 'Reason', 'Deal Value']

            st.dataframe(display_df[final_cols], use_container_width=True, hide_index=True)

            # Show termination reasons summary
            if df_terminated['termination_reason'].notna().sum() > 0:
                st.markdown("#### Common Termination Reasons")
                for reason in df_terminated['termination_reason'].dropna().unique():
                    count = len(df_terminated[df_terminated['termination_reason'] == reason])
                    st.markdown(f"- {reason} ({count} deal{'s' if count > 1 else ''})")
        else:
            st.info("No terminated deals found")

    with tab3:
        st.markdown("### Complete Deal History")
        st.markdown("Shows ALL deals including multiple attempts per SPAC")

        if len(df_history) > 0:
            # Format for display
            display_df = df_history.copy()

            display_df['Announced'] = display_df['announced_date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
            )
            display_df['Outcome Date'] = display_df.apply(
                lambda row: row['completion_date'].strftime('%Y-%m-%d') if pd.notna(row['completion_date'])
                else row['termination_date'].strftime('%Y-%m-%d') if pd.notna(row['termination_date'])
                else 'N/A',
                axis=1
            )

            display_df['Status'] = display_df['deal_status'].apply(
                lambda x: '✅ Completed' if x == 'COMPLETED' else '❌ Terminated' if x == 'TERMINATED' else '🔄 Announced'
            )

            # Rename columns
            display_cols = {
                'ticker': 'SPAC',
                'target_company': 'Target',
                'deal_value': 'Deal Value',
                'Announced': 'Announced',
                'Outcome Date': 'Outcome Date',
                'Status': 'Status',
                'is_current': 'Current Deal'
            }

            display_df = display_df.rename(columns=display_cols)
            final_cols = ['SPAC', 'Target', 'Deal Value', 'Announced', 'Outcome Date', 'Status', 'Current Deal']

            st.dataframe(display_df[final_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No deal history found")

    st.markdown("---")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        # Safely get years from completion dates
        years = []
        if len(df_completed) > 0 and 'completion_date' in df_completed.columns:
            # Ensure datetime type before accessing .dt accessor
            df_completed['completion_date'] = pd.to_datetime(df_completed['completion_date'], errors='coerce')
            valid_years = df_completed['completion_date'].dt.year.dropna().unique()
            if len(valid_years) > 0:
                years = sorted(valid_years.tolist(), reverse=True)

        year_filter = st.selectbox(
            "Completion Year",
            ["All"] + years
        )
    with col2:
        sectors = []
        if len(df_completed) > 0 and 'sector' in df_completed.columns:
            sectors = [s for s in df_completed['sector'].unique() if s is not None and s != '']
        sector_filter = st.selectbox("Sector", ["All"] + sorted(sectors))
    with col3:
        bankers = []
        if len(df_completed) > 0 and 'banker' in df_completed.columns:
            bankers = [b for b in df_completed['banker'].unique() if b is not None and b != '']
        banker_filter = st.selectbox("Investment Banker", ["All"] + sorted(bankers))

    # Apply filters
    if len(df_completed) > 0:
        # Ensure completion_date is datetime for filtering and sorting
        if 'completion_date' in df_completed.columns:
            df_completed['completion_date'] = pd.to_datetime(df_completed['completion_date'], errors='coerce')

        if year_filter != "All" and 'completion_date' in df_completed.columns:
            df_completed = df_completed[df_completed['completion_date'].dt.year == year_filter]
        if sector_filter != "All" and 'sector' in df_completed.columns:
            df_completed = df_completed[df_completed['sector'] == sector_filter]
        if banker_filter != "All" and 'banker' in df_completed.columns:
            df_completed = df_completed[df_completed['banker'] == banker_filter]

        # Sort by completion date (most recent first)
        if 'completion_date' in df_completed.columns:
            df_completed = df_completed.sort_values('completion_date', ascending=False, na_position='last')

    st.markdown(f"### 🎯 {len(df_completed)} Completed Deals")

    if len(df_completed) == 0:
        st.info("No completed deals match your filters.")
    else:
        # Prepare display dataframe
        display_df = df_completed[[
            'ticker', 'company', 'target', 'announced_date', 'completion_date',
            'new_ticker', 'deal_value', 'sector', 'banker'
        ]].copy()

        # Remove timezone for arithmetic (tz-naive)
        if hasattr(display_df['completion_date'].dtype, 'tz') and display_df['completion_date'].dtype.tz is not None:
            display_df['completion_date'] = display_df['completion_date'].dt.tz_localize(None)
        if hasattr(display_df['announced_date'].dtype, 'tz') and display_df['announced_date'].dtype.tz is not None:
            display_df['announced_date'] = display_df['announced_date'].dt.tz_localize(None)

        # Calculate days from announcement to close
        display_df['Days to Close'] = (display_df['completion_date'] - display_df['announced_date']).dt.days

        # Format dates
        display_df['Announced'] = display_df['announced_date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
        )
        display_df['Completed'] = display_df['completion_date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
        )

        # Format deal value for readable display
        display_df['Deal Value'] = display_df['deal_value'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) and x != 'TBD' else "N/A"
        )

        # Rename columns for display
        display_cols = {
            'ticker': 'Original SPAC',
            'company': 'SPAC Name',
            'target': 'Target Company',
            'Announced': 'Announced',
            'Completed': 'Completed',
            'Days to Close': 'Days to Close',
            'new_ticker': 'New Ticker',
            'Deal Value': 'Deal Value',
            'sector': 'Sector',
            'banker': 'Banker'
        }

        display_df = display_df.rename(columns=display_cols)

        # Select and reorder columns
        final_columns = [
            'Original SPAC', 'SPAC Name', 'Target Company', 'Announced',
            'Completed', 'Days to Close', 'New Ticker', 'Deal Value', 'Sector', 'Banker'
        ]

        display_df = display_df[final_columns]

        # Display as interactive table
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'Original SPAC': st.column_config.TextColumn('Original SPAC', width='small'),
                'SPAC Name': st.column_config.TextColumn('SPAC Name', width='medium'),
                'Target Company': st.column_config.TextColumn('Target Company', width='medium'),
                'Announced': st.column_config.TextColumn('Announced', width='small'),
                'Completed': st.column_config.TextColumn('Completed', width='small'),
                'Days to Close': st.column_config.NumberColumn('Days to Close', width='small'),
                'New Ticker': st.column_config.TextColumn('New Ticker', width='small'),
                'Deal Value': st.column_config.TextColumn('Deal Value', width='small'),
                'Sector': st.column_config.TextColumn('Sector', width='medium'),
                'Banker': st.column_config.TextColumn('Banker', width='medium')
            }
        )

        # Download button
        csv = display_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Completed Deals CSV",
            data=csv,
            file_name=f"completed_spac_deals_{now_eastern().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# ============================================================================
# PAGE: PRE-DEAL SPACs
# ============================================================================
elif page == "🔍 Pre-Deal SPACs":
    st.title("🔍 Pre-Deal SPACs")

    df_predeal = df[df['deal_status'] == 'SEARCHING'].copy()
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Pre-Deal", len(df_predeal))
    with col2:
        near_nav = len(df_predeal[df_predeal['premium'] < 5])
        st.metric("Near NAV (<5%)", near_nav)
    with col3:
        high_prem = len(df_predeal[df_predeal['premium'] > 10])
        st.metric("High Premium (>10%)", high_prem)
    with col4:
        urgent = len([d for d in df_predeal['days_to_deadline'] if d and d > 0 and d < 90])
        st.metric("Urgent (<90 days)", urgent)
    with col5:
        redeemed = len([r for r in df_predeal['redemptions_occurred'] if r == True])
        st.metric("Had Redemptions", redeemed)
    
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        min_premium = st.number_input("Min Premium %", value=-100.0, step=5.0)
    with col2:
        risk_filter = st.selectbox("Risk Level", ["All", "safe", "urgent", "expired"])
    with col3:
        # Filter out None values before sorting
        bankers = [b for b in df_predeal['banker'].unique() if b is not None]
        banker_filter = st.selectbox("Investment Banker", ["All"] + sorted(bankers))
    with col4:
        search_term = st.text_input("🔍 Search", placeholder="Ticker or company...")

    # Apply premium filter only if premium is not None
    df_predeal = df_predeal[(df_predeal['premium'] >= min_premium) | (df_predeal['premium'].isna())]
    if risk_filter != "All":
        df_predeal = df_predeal[df_predeal['risk_level'] == risk_filter]
    if banker_filter != "All":
        df_predeal = df_predeal[df_predeal['banker'] == banker_filter]
    if search_term:
        mask = (df_predeal['ticker'].str.contains(search_term, case=False, na=False) |
                df_predeal['company'].str.contains(search_term, case=False, na=False))
        df_predeal = df_predeal[mask]
    
    df_predeal = df_predeal.sort_values('premium', ascending=False)
    
    st.markdown(f"### 🔍 {len(df_predeal)} Pre-Deal SPACs")
    
    if len(df_predeal) == 0:
        st.info("No SPACs match your filters.")
    else:
        display_df = df_predeal.copy()

        # Convert IPO proceeds to numeric for sorting
        display_df['ipo_proceeds_numeric'] = display_df['ipo_proceeds'].apply(parse_ipo_proceeds)

        # Convert sponsor at-risk to millions for display
        display_df['sponsor_at_risk_millions'] = display_df['sponsor_total_at_risk'].apply(
            lambda x: round(x / 1_000_000, 2) if pd.notna(x) else None
        )

        # Prepare source document links for pre-deal SPACs (moved to far right)
        display_df['prospectus_424b4_url_display'] = display_df['prospectus_424b4_url']
        display_df['sec_company_url_display'] = display_df['sec_company_url']

        # Keep numeric columns for sorting, format display in column_config
        # Reorder: IPO Proceeds after Market Cap, Redemption fields after Sector, Sponsor economics after banker
        columns_to_show = ['ticker', 'company', 'price', 'volume', 'volume_pct_float', 'price_change_24h', 'warrant_price', 'unit_price', 'rights_price',
                          'trust_value', 'premium', 'notes', 'market_cap',
                          'ipo_proceeds_numeric', 'ipo_date', 'deadline_date',
                          'days_to_deadline', 'unit_ticker', 'warrant_ticker', 'right_ticker',
                          'unit_structure', 'risk_level', 'sector', 'redemption_percentage',
                          'shares_redeemed', 'banker', 'co_bankers', 'sponsor_at_risk_millions',
                          'last_price_update', 'last_scraped_at',
                          'prospectus_424b4_url_display', 'sec_company_url_display']

        display_df = display_df[columns_to_show].rename(columns={
            'ticker': 'Ticker',
            'company': 'Company',
            'price': 'Price',
            'volume': 'Volume',
            'volume_pct_float': 'Vol % Float',
            'price_change_24h': '% Daily Change',
            'warrant_price': 'Warrant Price',
            'unit_price': 'Unit Price',
            'rights_price': 'Rights Price',
            'trust_value': 'Trust NAV',
            'premium': 'Premium',
            'notes': 'Premium Analysis',
            'market_cap': 'Market Cap',
            'ipo_proceeds_numeric': 'IPO Proceeds',
            'redemption_percentage': 'Redemption %',
            'shares_redeemed': 'Shares Redeemed',
            'ipo_date': 'IPO Date',
            'deadline_date': 'Deadline',
            'days_to_deadline': 'Days Left',
            'unit_ticker': 'Unit Ticker',
            'warrant_ticker': 'Warrant Ticker',
            'right_ticker': 'Right Ticker',
            'unit_structure': 'Unit Structure',
            'risk_level': 'Risk',
            'sector': 'Sector',
            'banker': 'Lead Banker',
            'co_bankers': 'Co-Managers',
            'sponsor_at_risk_millions': 'Sponsor Committed',
            'last_price_update': 'Price Updated',
            'last_scraped_at': 'Data Scraped',
            'prospectus_424b4_url_display': '📕 424B4 (Final Prospectus)',
            'sec_company_url_display': '🏛️ SEC Filings'
        })

        # Note: Streamlit doesn't support frozen/pinned columns natively
        # Ticker is placed first for easier navigation when scrolling
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            column_order=['Ticker'] + [col for col in display_df.columns if col != 'Ticker'],
            column_config={
                'Ticker': st.column_config.TextColumn(width="small"),
                'Company': st.column_config.TextColumn(width="medium"),
                'Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Volume': st.column_config.NumberColumn(width="small", format="%,d"),
                'Vol % Float': st.column_config.NumberColumn(width="small", format="%.1f%%", help="Daily volume as % of public float (shares - founder shares - redemptions)"),
                '% Daily Change': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Warrant Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Unit Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Rights Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Trust NAV': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Premium': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Premium Analysis': st.column_config.TextColumn(width="large"),
                'Market Cap': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'IPO Proceeds': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'IPO Date': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Deadline': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Redemption %': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Shares Redeemed': st.column_config.NumberColumn(width="medium", format="%d"),
                'Days Left': st.column_config.NumberColumn(width="small", format="%d days"),
                'Unit Ticker': st.column_config.TextColumn(width="small"),
                'Warrant Ticker': st.column_config.TextColumn(width="small"),
                'Right Ticker': st.column_config.TextColumn(width="small"),
                'Unit Structure': st.column_config.TextColumn(width="medium"),
                'Risk': st.column_config.TextColumn(width="small"),
                'Sector': st.column_config.TextColumn(width="medium"),
                'Lead Banker': st.column_config.TextColumn(width="large"),
                'Co-Managers': st.column_config.TextColumn(width="large"),
                'Sponsor Committed': st.column_config.NumberColumn(
                    width="medium",
                    format="$%.2fM",
                    help="Total sponsor capital committed at IPO (founder shares + private placement). NOTE: Only founder shares (~$25k) are truly at risk; private placement units get ~$10/unit back in liquidation."
                ),
                'Price Updated': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD HH:mm"),
                'Data Scraped': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD"),
                '📕 424B4 (Final Prospectus)': st.column_config.LinkColumn(width="medium"),
                '🏛️ SEC Filings': st.column_config.LinkColumn(width="medium")
            }
        )

# ============================================================================
# PAGE: PRE-IPO PIPELINE
# ============================================================================
elif page == "🚀 Pre-IPO Pipeline":
    st.title("🚀 Pre-IPO SPAC Pipeline")
    st.markdown("Track SPACs from S-1 filing through IPO close")

    # Add refresh button to clear cache
    col_refresh, col_spacer = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()

    if len(pre_ipo_df) == 0:
        st.info("No pre-IPO SPACs currently in pipeline. Run `python3 pre_ipo_spac_finder.py` to search for new S-1 filings.")
    else:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📋 Total Pre-IPO", len(pre_ipo_df))
        with col2:
            s1_filed = len(pre_ipo_df[pre_ipo_df['filing_status'] == 'S-1'])
            st.metric("📝 S-1 Filed", s1_filed)
        with col3:
            effective = len(pre_ipo_df[pre_ipo_df['filing_status'] == 'Effective'])
            st.metric("✅ Effective", effective)
        with col4:
            priced = len(pre_ipo_df[pre_ipo_df['filing_status'] == 'Priced'])
            st.metric("💰 Priced", priced)

        st.markdown("---")

        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            status_filter = st.multiselect(
                "Filing Status",
                options=pre_ipo_df['filing_status'].unique().tolist(),
                default=pre_ipo_df['filing_status'].unique().tolist()
            )
        with col2:
            sector_options = pre_ipo_df['target_sector'].dropna().unique().tolist()
            if sector_options:
                sector_filter = st.multiselect(
                    "Target Sector",
                    options=sector_options,
                    default=sector_options
                )
            else:
                sector_filter = []
        with col3:
            banker_options = pre_ipo_df['lead_banker'].dropna().unique().tolist()
            if banker_options:
                banker_filter = st.multiselect(
                    "Lead Banker",
                    options=banker_options,
                    default=banker_options
                )
            else:
                banker_filter = []

        # Apply filters
        filtered_df = pre_ipo_df.copy()
        if status_filter:
            filtered_df = filtered_df[filtered_df['filing_status'].isin(status_filter)]
        if sector_filter:
            # Include rows where target_sector is in filter OR is null/None
            filtered_df = filtered_df[
                (filtered_df['target_sector'].isin(sector_filter)) |
                (filtered_df['target_sector'].isna())
            ]
        if banker_filter:
            # Include rows where lead_banker is in filter OR is null/None
            filtered_df = filtered_df[
                (filtered_df['lead_banker'].isin(banker_filter)) |
                (filtered_df['lead_banker'].isna())
            ]

        st.markdown(f"**Showing {len(filtered_df)} of {len(pre_ipo_df)} pre-IPO SPACs**")

        # Main table
        if len(filtered_df) > 0:
            display_df = filtered_df[[
                'company', 'expected_ticker', 'filing_status', 's1_filing_date',
                'target_proceeds', 'unit_structure', 'charter_deadline_months',
                'target_sector', 'target_geography', 'sponsor', 'lead_banker',
                'amendment_count'
            ]].copy()

            display_df = display_df.rename(columns={
                'company': 'Company',
                'expected_ticker': 'Ticker',
                'filing_status': 'Status',
                's1_filing_date': 'S-1 Filed',
                'target_proceeds': 'Target Proceeds',
                'unit_structure': 'Unit Structure',
                'charter_deadline_months': 'Deadline (mo)',
                'target_sector': 'Target Sector',
                'target_geography': 'Geography',
                'sponsor': 'Sponsor',
                'lead_banker': 'Lead Banker',
                'amendment_count': 'Amendments'
            })

            # Note: Company column kept first for easier navigation
            st.dataframe(
                display_df,
                hide_index=True,
                use_container_width=True,
                column_order=['Company'] + [col for col in display_df.columns if col != 'Company'],
                column_config={
                    'Company': st.column_config.TextColumn(width="large"),
                    'Ticker': st.column_config.TextColumn(width="small"),
                    'Status': st.column_config.TextColumn(width="small"),
                    'S-1 Filed': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                    'Target Proceeds': st.column_config.TextColumn(width="small"),
                    'Unit Structure': st.column_config.TextColumn(width="medium"),
                    'Deadline (mo)': st.column_config.NumberColumn(width="small", format="%d"),
                    'Target Sector': st.column_config.TextColumn(width="medium"),
                    'Geography': st.column_config.TextColumn(width="medium"),
                    'Sponsor': st.column_config.TextColumn(width="medium"),
                    'Lead Banker': st.column_config.TextColumn(width="large"),
                    'Amendments': st.column_config.NumberColumn(width="small", format="%d")
                }
            )

            # Detail view
            st.markdown("---")
            st.markdown("### 📖 Detail View")

            selected_company = st.selectbox(
                "Select a SPAC to view details:",
                options=filtered_df['company'].tolist()
            )

            if selected_company:
                spac_detail = filtered_df[filtered_df['company'] == selected_company].iloc[0]

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"**Company:** {spac_detail['company']}")
                    st.markdown(f"**Ticker:** {spac_detail['expected_ticker'] or 'TBD'}")
                    st.markdown(f"**Status:** {spac_detail['filing_status']}")
                    st.markdown(f"**S-1 Filed:** {spac_detail['s1_filing_date']}")
                    if spac_detail['effectiveness_date']:
                        st.markdown(f"**Effective Date:** {spac_detail['effectiveness_date']}")
                    if spac_detail['pricing_date']:
                        st.markdown(f"**Pricing Date:** {spac_detail['pricing_date']}")
                    st.markdown(f"**Amendments:** {spac_detail['amendment_count']}")

                with col2:
                    st.markdown(f"**Target Proceeds:** {spac_detail['target_proceeds'] or 'N/A'}")
                    st.markdown(f"**IPO Price Range:** {spac_detail['ipo_price_range'] or 'N/A'}")
                    st.markdown(f"**Trust/Unit:** ${spac_detail['trust_per_unit'] or 10.00:.2f}")
                    st.markdown(f"**Unit Structure:** {spac_detail['unit_structure'] or 'N/A'}")
                    st.markdown(f"**Deadline:** {spac_detail['charter_deadline_months']} months")
                    st.markdown(f"**Sponsor:** {spac_detail['sponsor'] or 'N/A'}")
                    st.markdown(f"**Lead Banker:** {spac_detail['lead_banker'] or 'N/A'}")

                if spac_detail['target_description']:
                    st.markdown("**Target Strategy:**")
                    st.info(spac_detail['target_description'])

                if spac_detail['target_sector']:
                    st.markdown(f"**Target Sector:** {spac_detail['target_sector']}")
                if spac_detail['target_geography']:
                    st.markdown(f"**Target Geography:** {spac_detail['target_geography']}")

                if spac_detail['s1_url']:
                    st.markdown(f"[📄 View S-1 Filing]({spac_detail['s1_url']})")

        st.markdown("---")
        st.markdown("""
        **Pipeline Management:**
        - 🔍 Search for new S-1s: `python3 pre_ipo_spac_finder.py`
        - 📊 Check status updates: `python3 pre_ipo_status_monitor.py`
        - 🎓 Graduate closed IPOs: `python3 pre_ipo_graduation.py`
        """)

# ============================================================================
# PAGE: ANALYTICS
# ============================================================================
elif page == "📊 Analytics":
    st.title("📊 Market Analytics")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total SPACs", len(df))
    with col2:
        st.metric("Announced Deals", len(df[df['deal_status'] == 'ANNOUNCED']))
    with col3:
        avg_premium = df['premium'].mean()
        st.metric("Avg Premium", f"{avg_premium:.1f}%")
    with col4:
        total_cap = df['market_cap'].sum()
        st.metric("Total Market Cap", f"${total_cap/1000:.1f}B")

    st.markdown("---")

    # Premium history charts
    st.markdown("### 📈 Historical Average Premium")

    col_chart1, col_chart2 = st.columns([3, 1])

    with col_chart2:
        date_range = st.selectbox("Time Range", ["Last 30 days", "Last 90 days", "YTD 2025", "All time"], index=1)

    # Map selection to days
    days_map = {
        "Last 30 days": 30,
        "Last 90 days": 90,
        "YTD 2025": 365,  # Will filter to 2025 below
        "All time": 999
    }
    days = days_map[date_range]

    df_history = load_premium_history(days)

    if len(df_history) > 0:
        # Filter for YTD if selected
        if date_range == "YTD 2025":
            df_history = df_history[df_history['date'] >= pd.Timestamp('2025-01-01').date()]

        # Split into two charts side-by-side
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("#### 🔍 Pre-Deal SPACs (Searching)")
            # Create dual-axis chart using plotly
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots

            fig_predeal = make_subplots(specs=[[{"secondary_y": True}]])

            # Market cap weighted average premium line (primary y-axis)
            fig_predeal.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['weighted_avg_premium_predeal'],
                    name="Weighted Avg",
                    line=dict(color='#1f77b4', width=3),
                    mode='lines+markers'
                ),
                secondary_y=False
            )

            # Simple average premium line (primary y-axis)
            fig_predeal.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['avg_premium_predeal'],
                    name="Simple Avg",
                    line=dict(color='#ff7f0e', width=2, dash='dot'),
                    mode='lines'
                ),
                secondary_y=False
            )

            # Median premium line (primary y-axis)
            fig_predeal.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['median_premium_predeal'],
                    name="Median",
                    line=dict(color='#7f7f7f', width=2, dash='dash'),
                    mode='lines'
                ),
                secondary_y=False
            )

            # SPAC count line (secondary y-axis)
            fig_predeal.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['count_predeal'],
                    name="# SPACs",
                    line=dict(color='#2ca02c', width=2),
                    mode='lines'
                ),
                secondary_y=True
            )

            # Update axes
            fig_predeal.update_xaxes(title_text="Date")
            fig_predeal.update_yaxes(title_text="Premium %", secondary_y=False)
            fig_predeal.update_yaxes(title_text="Number of SPACs", secondary_y=True)

            # Update layout
            fig_predeal.update_layout(
                height=350,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=40, b=0)
            )

            st.plotly_chart(fig_predeal, use_container_width=True)

            # Show current stats
            latest = df_history.iloc[-1]
            weighted_text = f"{latest['weighted_avg_premium_predeal']:.2f}%" if pd.notna(latest['weighted_avg_premium_predeal']) else "N/A"
            st.caption(f"💡 Latest: **{weighted_text}** across {int(latest['count_predeal'])} SPACs")

        with chart_col2:
            st.markdown("#### 🎯 Announced Deal SPACs")
            # Create dual-axis chart using plotly
            fig_announced = make_subplots(specs=[[{"secondary_y": True}]])

            # Market cap weighted average premium line (primary y-axis)
            fig_announced.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['weighted_avg_premium_announced'],
                    name="Weighted Avg",
                    line=dict(color='#d62728', width=3),
                    mode='lines+markers'
                ),
                secondary_y=False
            )

            # Simple average premium line (primary y-axis)
            fig_announced.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['avg_premium_announced'],
                    name="Simple Avg",
                    line=dict(color='#ff7f0e', width=2, dash='dot'),
                    mode='lines'
                ),
                secondary_y=False
            )

            # Median premium line (primary y-axis)
            fig_announced.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['median_premium_announced'],
                    name="Median",
                    line=dict(color='#7f7f7f', width=2, dash='dash'),
                    mode='lines'
                ),
                secondary_y=False
            )

            # SPAC count line (secondary y-axis)
            fig_announced.add_trace(
                go.Scatter(
                    x=df_history['date'],
                    y=df_history['count_announced'],
                    name="# SPACs",
                    line=dict(color='#2ca02c', width=2),
                    mode='lines'
                ),
                secondary_y=True
            )

            # Update axes
            fig_announced.update_xaxes(title_text="Date")
            fig_announced.update_yaxes(title_text="Premium %", secondary_y=False)
            fig_announced.update_yaxes(title_text="Number of SPACs", secondary_y=True)

            # Update layout
            fig_announced.update_layout(
                height=350,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=40, b=0)
            )

            st.plotly_chart(fig_announced, use_container_width=True)

            # Show current stats
            latest = df_history.iloc[-1]
            weighted_text_ann = f"{latest['weighted_avg_premium_announced']:.2f}%" if pd.notna(latest['weighted_avg_premium_announced']) else "N/A"
            st.caption(f"💡 Latest: **{weighted_text_ann}** across {int(latest['count_announced'])} SPACs")
    else:
        st.info("📊 Premium history tracking started today. Check back tomorrow for the first data point!")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Premium Distribution")
        fig = px.histogram(df, x='premium', nbins=30)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### Top Investment Bankers")
        banker_counts = df['banker'].value_counts().head(10)
        fig = px.bar(x=banker_counts.index, y=banker_counts.values)
        st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# PAGE: WATCHLIST
# ============================================================================
elif page == "⭐ Watchlist":
    st.title("⭐ My Watchlist")

    # ==========================================================================
    # AUTOMATED OPPORTUNITY RANKINGS
    # ==========================================================================
    st.markdown("## 🎯 Automated Opportunity Rankings")

    # Methodology explanation (collapsible)
    with st.expander("📖 Scoring Methodology", expanded=False):
        st.markdown("""
        ### Phase 1: "Loaded Gun" Score (0-60 points) - Pre-Deal Quality

        Evaluates SPAC quality **before** a deal is announced. Higher scores indicate better structure and potential.

        **Components:**
        - **Market Cap (0-10)**: IPO size as proxy for liquidity and institutional interest
          - ≥$500M: 10 pts | ≥$300M: 8 pts | ≥$150M: 6 pts | ≥$100M: 4 pts | ≥$50M: 2 pts
        - **Sponsor Quality (0-15)**: Investment banker tier
          - Tier 1 (Goldman, JPM, Citi): 15 pts | Tier 2: 10 pts | Tier 3: 5 pts
        - **Hot Sector (0-10)**: Market narrative strength
          - Hot sectors (AI, FinTech, EV, etc.): 10 pts | Other: 0 pts
        - **Dilution (0-15)**: Founder share dilution (lower = better for public shareholders)
          - <15%: 15 pts | <20%: 12 pts | <25%: 8 pts | <30%: 4 pts | ≥30%: 0 pts
        - **Promote Vesting (0-10)**: Sponsor alignment with shareholders
          - Performance vesting: 10 pts | Time-based: 5 pts | Immediate: 0 pts

        ### Phase 2: "Lit Fuse" Score (0-90 points) - Post-Deal Momentum

        *(Not yet implemented)* Will evaluate deal quality, PIPE terms, institutional interest, and volume signals.

        ### Data Sources
        - All data extracted from SEC filings (424B4, 8-K, 10-Q)
        - Updated automatically when new filings detected
        - Missing data = 0 points for that component
        """)

    st.markdown("*Algorithmic scoring based on IPO size, banker tier, sponsor track record, sector trends, dilution, and vesting alignment*")

    # Default weights
    market_cap_weight = 1.0
    banker_weight = 1.0
    sponsor_weight = 1.0
    sector_weight = 1.0
    dilution_weight = 1.0
    promote_weight = 1.0

    # Weight adjustment controls
    with st.expander("⚙️ Adjust Scoring Weights (Advanced)", expanded=False):
        st.markdown("Customize the importance of each scoring component:")

        col1, col2, col3 = st.columns(3)

        with col1:
            market_cap_weight = st.slider("Market Cap", 0.0, 2.0, market_cap_weight, 0.1, help="Multiplier for IPO size score")
            banker_weight = st.slider("Banker Quality", 0.0, 2.0, banker_weight, 0.1, help="Multiplier for underwriter tier score (Goldman, JPM, etc.)")

        with col2:
            sponsor_weight = st.slider("Sponsor Quality", 0.0, 2.0, sponsor_weight, 0.1, help="Multiplier for founder team track record")
            sector_weight = st.slider("Hot Sector", 0.0, 2.0, sector_weight, 0.1, help="Multiplier for sector narrative score")

        with col3:
            dilution_weight = st.slider("Low Dilution", 0.0, 2.0, dilution_weight, 0.1, help="Multiplier for founder dilution score")
            promote_weight = st.slider("Promote Vesting", 0.0, 2.0, promote_weight, 0.1, help="Multiplier for vesting alignment score")

        if any([market_cap_weight != 1.0, banker_weight != 1.0, sponsor_weight != 1.0, sector_weight != 1.0,
                dilution_weight != 1.0, promote_weight != 1.0]):
            st.info(f"🔧 Custom weights active: Mkt×{market_cap_weight} | Bank×{banker_weight} | Spon×{sponsor_weight} | Sect×{sector_weight} | Dil×{dilution_weight} | Prom×{promote_weight}")
            if st.button("Reset to Default Weights"):
                st.rerun()

    # Load opportunity scores from database
    try:
        from database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()

        # Get top opportunities (combined score)
        top_opps_query = text("""
            SELECT
                s.ticker,
                s.company,
                s.deal_status,
                s.sector_classified,
                s.price,
                s.premium,
                o.total_score,
                o.loaded_gun_score,
                o.lit_fuse_score,
                o.alert_threshold,
                o.tier
            FROM spacs s
            LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE o.total_score >= 70
            ORDER BY o.total_score DESC
            LIMIT 10
        """)
        top_opps = pd.read_sql(top_opps_query, db.bind)

        # Show top opportunities if any exist
        if len(top_opps) > 0:
            st.markdown("### 🔥 Top Opportunities (Score ≥ 70)")

            for idx, row in top_opps.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 3])

                with col1:
                    threshold_emoji = {
                        'EXTREME': '🔥',
                        'STRONG': '🎯',
                        'MODERATE': '⚠️'
                    }.get(row['alert_threshold'], '📊')

                    st.markdown(f"**{threshold_emoji} {row['ticker']}** - {row['company'][:40]}")
                    st.caption(f"{row['sector_classified']} | {row['deal_status']}")

                with col2:
                    st.metric("Total Score", f"{row['total_score']}/150")

                with col3:
                    st.metric("Phase 1", f"{row['loaded_gun_score']}/75")
                    st.caption(f"Phase 2: {row['lit_fuse_score']}/90")

                with col4:
                    if pd.notna(row['price']):
                        st.metric("Price", f"${row['price']:.2f}")
                    if pd.notna(row['premium']):
                        st.caption(f"Premium: {row['premium']:.1f}%")

                st.markdown("---")
        else:
            st.info("No SPACs currently scored. Run opportunity scoring to see rankings.")

        # Show Loaded Guns (pre-deal only) - with custom weights
        loaded_guns_query = text(f"""
            SELECT
                s.ticker,
                s.company,
                s.sponsor_normalized,
                s.sector_classified,
                s.price,
                s.premium,
                s.deadline_date,
                o.loaded_gun_score,
                o.market_cap_score,
                o.banker_score,
                o.sponsor_score,
                o.sector_score,
                o.dilution_score,
                o.promote_score,
                (o.market_cap_score * {market_cap_weight} +
                 o.banker_score * {banker_weight} +
                 o.sponsor_score * {sponsor_weight} +
                 o.sector_score * {sector_weight} +
                 o.dilution_score * {dilution_weight} +
                 o.promote_score * {promote_weight}) as weighted_score
            FROM spacs s
            LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'SEARCHING'
              AND o.loaded_gun_score >= 20
            ORDER BY weighted_score DESC
            LIMIT 20
        """)
        loaded_guns = pd.read_sql(loaded_guns_query, db.bind)

        if len(loaded_guns) > 0:
            # Update header based on weights
            if any([market_cap_weight != 1.0, banker_weight != 1.0, sponsor_weight != 1.0, sector_weight != 1.0,
                    dilution_weight != 1.0, promote_weight != 1.0]):
                st.markdown("### 🔫 Loaded Guns - Pre-Deal SPACs (Custom Weights)")
                st.caption(f"Weighted scores shown | Mkt×{market_cap_weight} Bank×{banker_weight} Spon×{sponsor_weight} Sect×{sector_weight} Dil×{dilution_weight} Prom×{promote_weight}")
            else:
                st.markdown("### 🔫 Loaded Guns - Pre-Deal SPACs (Phase 1 Score ≥ 20)")
                st.caption("Quality: Mkt Cap (0-10) + Banker (0-15) + Sponsor (0-15) + Sector (0-10) + Dilution (0-15) + Promote (0-10)")

            # Create table data
            table_data = []
            for idx, row in loaded_guns.iterrows():
                # Use weighted score if custom weights applied
                display_score = row['weighted_score'] if any([market_cap_weight != 1.0, banker_weight != 1.0, sponsor_weight != 1.0,
                                                                sector_weight != 1.0, dilution_weight != 1.0,
                                                                promote_weight != 1.0]) else row['loaded_gun_score']
                max_score = market_cap_weight*10 + banker_weight*15 + sponsor_weight*15 + sector_weight*10 + dilution_weight*15 + promote_weight*10

                tier_emoji = "🥇" if display_score >= max_score*0.75 else "🥈" if display_score >= max_score*0.60 else "🥉"
                price_str = f"${row['price']:.2f}" if pd.notna(row['price']) else "N/A"
                premium_str = f"{row['premium']:.1f}%" if pd.notna(row['premium']) else "N/A"

                table_data.append({
                    'Rank': f"{tier_emoji} #{idx+1}",
                    'Ticker': row['ticker'],
                    'Score': f"{display_score:.0f}/{max_score:.0f}" if max_score != 75 else f"{row['loaded_gun_score']}/75",
                    'Mkt': row['market_cap_score'],
                    'Bank': row['banker_score'],
                    'Spon': row['sponsor_score'],
                    'Sect': row['sector_score'],
                    'Dil': row['dilution_score'],
                    'Prom': row['promote_score'],
                    'Price': price_str,
                    'Premium': premium_str,
                    'Company': row['company'][:30] if pd.notna(row['company']) else ''
                })

            df_display = pd.DataFrame(table_data)
            st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Show Lit Fuses (announced deals)
        lit_fuses_query = text("""
            SELECT
                s.ticker,
                s.company,
                s.target,
                s.price,
                s.premium,
                s.pipe_size,
                s.volume_pct_of_float,
                o.lit_fuse_score,
                o.pipe_size_score,
                o.pipe_quality_score,
                o.volume_score,
                (SELECT COUNT(*) FROM pipe_investors pi
                 WHERE pi.ticker = s.ticker AND pi.is_tier1 = TRUE) as tier1_count
            FROM spacs s
            LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'ANNOUNCED'
              AND o.lit_fuse_score >= 50
            ORDER BY o.lit_fuse_score DESC
            LIMIT 10
        """)
        lit_fuses = pd.read_sql(lit_fuses_query, db.bind)

        if len(lit_fuses) > 0:
            st.markdown("### 🚀 Lit Fuses - Hot Deals (Phase 2 Score ≥ 50)")

            for idx, row in lit_fuses.iterrows():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 3])

                with col1:
                    st.markdown(f"**🚀 {row['ticker']}** → {row['target'][:30]}")
                    st.caption(f"{row['company'][:40]}")

                with col2:
                    st.metric("Phase 2 Score", f"{row['lit_fuse_score']}/90")

                with col3:
                    if row['tier1_count'] > 0:
                        st.caption(f"✅ {row['tier1_count']} Tier-1 Investor{'s' if row['tier1_count'] > 1 else ''}")
                    if pd.notna(row['volume_pct_of_float']) and row['volume_pct_of_float'] > 5:
                        st.caption(f"🔥 {row['volume_pct_of_float']:.1f}% float traded")

                with col4:
                    if pd.notna(row['price']):
                        st.metric("Price", f"${row['price']:.2f}")
                    if pd.notna(row['premium']):
                        st.caption(f"Premium: {row['premium']:.1f}%")

                st.markdown("---")

        db.close()

    except Exception as e:
        st.warning(f"Opportunity rankings not yet available. Run scoring to populate.")
        st.caption(f"Debug: {str(e)}")

    st.markdown("---")

    # Define watchlist tickers
    LIVE_DEAL_WATCHLIST = ['BACQ']
    PRE_DEAL_WATCHLIST = ['CAEP', 'TACO', 'PMTR', 'ATII', 'CEPT', 'AEXA']

    # ==========================================================================
    # MANUAL WATCHLIST - LIVE DEALS
    # ==========================================================================
    st.markdown("## 📈 Manual Watchlist - Live Deals")

    df_live_watchlist = df[df['ticker'].isin(LIVE_DEAL_WATCHLIST) & (df['deal_status'] == 'ANNOUNCED')].copy()

    if len(df_live_watchlist) == 0:
        st.info("No live deal SPACs in watchlist or deals not yet announced.")
    else:
        display_df = df_live_watchlist.copy()

        # Keep all numeric columns as numbers for proper sorting
        display_df['Premium'] = display_df['premium']
        display_df['Price'] = display_df['price']
        display_df['% Daily Change'] = display_df['price_change_24h']

        # Keep volume as numeric for sorting (formatting handled by column_config)
        display_df['Volume'] = display_df['volume']
        display_df['Vol % Float'] = display_df['volume_pct_float']

        # Format money fields for readable display ($275.0M instead of 275000000 - consistent 1 decimal)
        display_df['Market Cap'] = display_df['market_cap'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['Days Left'] = display_df['days_to_deadline']
        display_df['Return'] = display_df['return_since_announcement']

        display_df['PIPE Size'] = display_df['pipe_size'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['PIPE Price'] = display_df['pipe_price'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else '-'
        )
        display_df['Min Cash'] = display_df['min_cash'].apply(
            lambda x: format_number_display(x, 'money') if pd.notna(x) else '-'
        )
        display_df['Redemptions'] = display_df['redemption_percentage']
        display_df['Warrant Price'] = display_df['warrant_price']
        display_df['Unit Price'] = display_df['unit_price']
        display_df['Rights Price'] = display_df['rights_price']
        display_df['Sponsor Committed'] = display_df['sponsor_total_at_risk'] / 1e6 if 'sponsor_total_at_risk' in display_df else None
        display_df['Sponsor Committed %'] = display_df['sponsor_at_risk_percentage']
        display_df['prospectus_424b4_url_display'] = display_df['prospectus_424b4_url']
        display_df['deal_filing_url_display'] = display_df['deal_filing_url']
        display_df['press_release_url_display'] = display_df['press_release_url']
        display_df['s4_filing_url_display'] = display_df['s4_filing_url']
        display_df['proxy_filing_url_display'] = display_df['proxy_filing_url']
        display_df['sec_company_url_display'] = display_df['sec_company_url']
        display_df['Trust Value (NAV)'] = display_df['trust_value']

        columns_to_show = ['ticker', 'company', 'target', 'Premium', 'Price', 'Trust Value (NAV)', '% Daily Change', 'Volume', 'Vol % Float', 'Warrant Price',
                          'Unit Price', 'Rights Price', 'Return', 'Market Cap',
                          'deal_value', 'announced_date', 'latest_s4_date', 'proxy_filed_date',
                          'shareholder_vote_date', 'expected_close', 'Days Left', 'Redemptions',
                          'PIPE Size', 'PIPE Price', 'Min Cash', 'Sponsor Committed',
                          'sponsor', 'sector', 'banker', 'last_price_update', 'last_scraped_at', 'notes',
                          'prospectus_424b4_url_display', 'deal_filing_url_display', 'press_release_url_display',
                          's4_filing_url_display', 'proxy_filing_url_display', 'sec_company_url_display']

        display_df = display_df[columns_to_show].rename(columns={
            'ticker': 'Ticker',
            'company': 'Company',
            'target': 'Target Company',
            'deal_value': 'Deal Value',
            'announced_date': 'Announced',
            'latest_s4_date': 'S-4 Filed',
            'proxy_filed_date': 'Proxy Filed',
            'shareholder_vote_date': 'Vote Date',
            'expected_close': 'Expected Close',
            'sponsor': 'Sponsor',
            'banker': 'Lead Banker',
            'sector': 'Sector',
            'last_price_update': 'Price Updated',
            'last_scraped_at': 'Data Scraped',
            'notes': 'Premium Analysis',
            'prospectus_424b4_url_display': '📕 424B4 (Prospectus)',
            'deal_filing_url_display': '📄 Deal Filing (8-K/425)',
            'press_release_url_display': '📰 Press Release',
            's4_filing_url_display': '📋 S-4 (Merger Reg)',
            'proxy_filing_url_display': '🗳️ Proxy (DEF 14A)',
            'sec_company_url_display': '🏛️ SEC Filings'
        })

        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            column_order=['Ticker'] + [col for col in display_df.columns if col != 'Ticker'],
            column_config={
                'Ticker': st.column_config.TextColumn(width="small"),
                'Company': st.column_config.TextColumn(width="medium"),
                'Target Company': st.column_config.TextColumn(width="medium"),
                'Premium': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Trust Value (NAV)': st.column_config.NumberColumn(width="small", format="$%.2f", help="Net Asset Value per share from IPO trust account"),
                '% Daily Change': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Volume': st.column_config.NumberColumn(width="small", format="%,d"),
                'Vol % Float': st.column_config.NumberColumn(width="small", format="%.1f%%", help="Daily volume as % of public float"),
                'Warrant Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Unit Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Rights Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Return': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Market Cap': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'Deal Value': st.column_config.TextColumn(width="medium"),
                'Announced': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'S-4 Filed': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Proxy Filed': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Vote Date': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Expected Close': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Days Left': st.column_config.NumberColumn(width="small", format="%d days"),
                'Redemptions': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'PIPE Size': st.column_config.TextColumn(width="medium"),
                'PIPE Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Min Cash': st.column_config.TextColumn(width="medium"),
                'Sponsor Committed': st.column_config.NumberColumn(width="medium", format="$%.2fM"),
                'Sponsor': st.column_config.TextColumn(width="medium"),
                'Lead Banker': st.column_config.TextColumn(width="large"),
                'Sector': st.column_config.TextColumn(width="medium"),
                'Price Updated': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD HH:mm"),
                'Data Scraped': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD"),
                'Premium Analysis': st.column_config.TextColumn(width="large"),
                '📕 424B4 (Prospectus)': st.column_config.LinkColumn(width="medium"),
                '📄 Deal Filing (8-K/425)': st.column_config.LinkColumn(width="medium"),
                '📰 Press Release': st.column_config.LinkColumn(width="medium"),
                '📋 S-4 (Merger Reg)': st.column_config.LinkColumn(width="medium"),
                '🗳️ Proxy (DEF 14A)': st.column_config.LinkColumn(width="medium"),
                '🏛️ SEC Filings': st.column_config.LinkColumn(width="medium")
            }
        )

    st.markdown("---")

    # ==========================================================================
    # PRE-DEAL WATCHLIST
    # ==========================================================================
    st.markdown("## 🔍 Pre-Deal SPACs Watchlist")

    df_predeal_watchlist = df[df['ticker'].isin(PRE_DEAL_WATCHLIST) & (df['deal_status'] == 'SEARCHING')].copy()

    if len(df_predeal_watchlist) == 0:
        st.info("No pre-deal SPACs in watchlist or deals already announced.")
    else:
        display_df = df_predeal_watchlist.copy()

        # Convert IPO proceeds to numeric for sorting
        display_df['ipo_proceeds_numeric'] = display_df['ipo_proceeds'].apply(parse_ipo_proceeds)

        # Convert sponsor at-risk to millions for display
        display_df['sponsor_at_risk_millions'] = display_df['sponsor_total_at_risk'].apply(
            lambda x: round(x / 1_000_000, 2) if pd.notna(x) else None
        )

        # Prepare source document links
        display_df['prospectus_424b4_url_display'] = display_df['prospectus_424b4_url']
        display_df['sec_company_url_display'] = display_df['sec_company_url']

        columns_to_show = ['ticker', 'company', 'price', 'volume', 'volume_pct_float', 'price_change_24h', 'warrant_price', 'unit_price', 'rights_price',
                          'trust_value', 'premium', 'notes', 'market_cap',
                          'ipo_proceeds_numeric', 'ipo_date', 'deadline_date',
                          'days_to_deadline', 'unit_ticker', 'warrant_ticker', 'right_ticker',
                          'unit_structure', 'risk_level', 'sector', 'redemption_percentage',
                          'shares_redeemed', 'banker', 'co_bankers', 'sponsor_at_risk_millions',
                          'last_price_update', 'last_scraped_at',
                          'prospectus_424b4_url_display', 'sec_company_url_display']

        display_df = display_df[columns_to_show].rename(columns={
            'ticker': 'Ticker',
            'company': 'Company',
            'price': 'Price',
            'volume': 'Volume',
            'volume_pct_float': 'Vol % Float',
            'price_change_24h': '% Daily Change',
            'warrant_price': 'Warrant Price',
            'unit_price': 'Unit Price',
            'rights_price': 'Rights Price',
            'trust_value': 'Trust NAV',
            'premium': 'Premium',
            'notes': 'Premium Analysis',
            'market_cap': 'Market Cap',
            'ipo_proceeds_numeric': 'IPO Proceeds',
            'redemption_percentage': 'Redemption %',
            'shares_redeemed': 'Shares Redeemed',
            'ipo_date': 'IPO Date',
            'deadline_date': 'Deadline',
            'days_to_deadline': 'Days Left',
            'unit_ticker': 'Unit Ticker',
            'warrant_ticker': 'Warrant Ticker',
            'right_ticker': 'Right Ticker',
            'unit_structure': 'Unit Structure',
            'risk_level': 'Risk',
            'sector': 'Sector',
            'banker': 'Lead Banker',
            'co_bankers': 'Co-Managers',
            'sponsor_at_risk_millions': 'Sponsor Committed',
            'last_price_update': 'Price Updated',
            'last_scraped_at': 'Data Scraped',
            'prospectus_424b4_url_display': '📕 424B4 (Final Prospectus)',
            'sec_company_url_display': '🏛️ SEC Filings'
        })

        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            column_order=['Ticker'] + [col for col in display_df.columns if col != 'Ticker'],
            column_config={
                'Ticker': st.column_config.TextColumn(width="small"),
                'Company': st.column_config.TextColumn(width="medium"),
                'Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Volume': st.column_config.NumberColumn(width="small", format="%,d"),
                'Vol % Float': st.column_config.NumberColumn(width="small", format="%.1f%%", help="Daily volume as % of public float"),
                '% Daily Change': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Warrant Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Unit Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Rights Price': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Trust NAV': st.column_config.NumberColumn(width="small", format="$%.2f"),
                'Premium': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Premium Analysis': st.column_config.TextColumn(width="large"),
                'Market Cap': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'IPO Proceeds': st.column_config.NumberColumn(width="small", format="$%.0fM"),
                'IPO Date': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Deadline': st.column_config.DateColumn(width="medium", format="YYYY-MM-DD"),
                'Redemption %': st.column_config.NumberColumn(width="small", format="%.1f%%"),
                'Shares Redeemed': st.column_config.NumberColumn(width="medium", format="%d"),
                'Days Left': st.column_config.NumberColumn(width="small", format="%d days"),
                'Unit Ticker': st.column_config.TextColumn(width="small"),
                'Warrant Ticker': st.column_config.TextColumn(width="small"),
                'Right Ticker': st.column_config.TextColumn(width="small"),
                'Unit Structure': st.column_config.TextColumn(width="medium"),
                'Risk': st.column_config.TextColumn(width="small"),
                'Sector': st.column_config.TextColumn(width="medium"),
                'Lead Banker': st.column_config.TextColumn(width="large"),
                'Co-Managers': st.column_config.TextColumn(width="large"),
                'Sponsor Committed': st.column_config.NumberColumn(
                    width="medium",
                    format="$%.2fM",
                    help="Total sponsor capital committed at IPO (founder shares + private placement)"
                ),
                'Price Updated': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD HH:mm"),
                'Data Scraped': st.column_config.DatetimeColumn(width="medium", format="YYYY-MM-DD"),
                '📕 424B4 (Final Prospectus)': st.column_config.LinkColumn(width="medium"),
                '🏛️ SEC Filings': st.column_config.LinkColumn(width="medium")
            }
        )

# ============================================================================
# PAGE: REPORT ISSUES
# ============================================================================
elif page == "🐛 Report Issues":
    st.title("🐛 Report Issues & Feedback")
    st.markdown("""
    Found a bug? Have a feature request? Data quality issue? Let us know!

    Your feedback helps us improve the SPAC research platform. All submissions are reviewed by our AI agent,
    which suggests fixes and sends them to our team for approval.
    """)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Submit New Issue")

        with st.form("issue_form"):
            issue_type = st.selectbox(
                "Issue Type",
                options=["bug", "feature", "data_quality", "other"],
                format_func=lambda x: {
                    "bug": "🐛 Bug Report",
                    "feature": "✨ Feature Request",
                    "data_quality": "📊 Data Quality Issue",
                    "other": "💬 Other Feedback"
                }[x]
            )

            title = st.text_input(
                "Issue Title",
                placeholder="Brief summary of the issue",
                max_chars=200
            )

            description = st.text_area(
                "Description",
                placeholder="Provide details about the issue, steps to reproduce (for bugs), or describe the feature you'd like to see...",
                height=150
            )

            col_a, col_b = st.columns(2)

            with col_a:
                ticker_related = st.text_input(
                    "Related SPAC Ticker (optional)",
                    placeholder="e.g., AEXA",
                    max_chars=10
                ).upper()

            with col_b:
                page_location = st.selectbox(
                    "Where did you encounter this?",
                    options=["", "AI Chat", "Live Deals", "Completed Deals", "Pre-Deal SPACs", "Pre-IPO Pipeline", "Analytics", "Watchlist", "Other"]
                )

            submitted = st.form_submit_button("Submit Issue", type="primary", use_container_width=True)

            if submitted:
                if not title or not description:
                    st.error("⚠️ Please provide both a title and description")
                else:
                    # Save to database (data_quality_conversations)
                    db = SessionLocal()
                    try:
                        import json
                        from datetime import datetime

                        issue_id = f"user_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                        original_data = json.dumps({
                            'description': description,
                            'page_location': page_location,
                            'priority': 'medium',
                            'submitted_via': 'streamlit_ui'
                        })

                        learning_notes = f"{title}\n\n{description}"

                        # Insert into data_quality_conversations
                        from sqlalchemy import text
                        db.execute(text("""
                            INSERT INTO data_quality_conversations (
                                issue_id, issue_type, ticker, created_at, status,
                                original_data, learning_notes, issue_source
                            )
                            VALUES (
                                :issue_id, :issue_type, :ticker, NOW(), 'pending',
                                :original_data, :learning_notes, 'user_reported'
                            )
                        """), {
                            'issue_id': issue_id,
                            'issue_type': issue_type,
                            'ticker': ticker_related if ticker_related else None,
                            'original_data': original_data,
                            'learning_notes': learning_notes
                        })
                        db.commit()

                        st.success(f"✅ Issue submitted successfully!")
                        st.balloons()
                        st.info("🤖 Our AI agent will analyze your issue and suggest a fix. We'll review and implement it soon!")

                    except Exception as e:
                        st.error(f"❌ Error submitting issue: {e}")
                        db.rollback()
                    finally:
                        db.close()

    with col2:
        st.subheader("📊 Issue Stats")

        db = SessionLocal()
        try:
            from sqlalchemy import text

            # Query data_quality_conversations for user-reported issues
            total_issues = db.execute(text("""
                SELECT COUNT(*) FROM data_quality_conversations
                WHERE issue_source = 'user_reported'
            """)).scalar()

            open_issues = db.execute(text("""
                SELECT COUNT(*) FROM data_quality_conversations
                WHERE issue_source = 'user_reported'
                AND status IN ('pending', 'active')
            """)).scalar()

            resolved_issues = db.execute(text("""
                SELECT COUNT(*) FROM data_quality_conversations
                WHERE issue_source = 'user_reported'
                AND status = 'completed'
            """)).scalar()

            st.metric("Total Issues", total_issues)
            st.metric("Open", open_issues)
            st.metric("Resolved", resolved_issues)

        finally:
            db.close()

    st.markdown("---")

    # Show recent issues
    st.subheader("Recent Issues")

    tab1, tab2, tab3 = st.tabs(["🔓 Open", "✅ Resolved", "📝 All"])

    with tab1:
        db = SessionLocal()
        try:
            open_issues = db.query(UserIssue).filter(UserIssue.status == 'open').order_by(UserIssue.submitted_at.desc()).limit(10).all()

            if open_issues:
                for issue in open_issues:
                    with st.expander(f"#{issue.id} - {issue.title}"):
                        issue_type_emoji = {
                            'bug': '🐛',
                            'feature': '✨',
                            'data_quality': '📊',
                            'other': '💬'
                        }
                        st.markdown(f"**Type:** {issue_type_emoji.get(issue.issue_type, '💬')} {issue.issue_type.replace('_', ' ').title()}")
                        st.markdown(f"**Status:** {issue.status.title()}")
                        st.markdown(f"**Submitted:** {format_datetime(issue.submitted_at)}")
                        if issue.ticker_related:
                            st.markdown(f"**Related SPAC:** {issue.ticker_related}")
                        if issue.page_location:
                            st.markdown(f"**Page:** {issue.page_location}")
                        st.markdown(f"**Description:**\n\n{issue.description}")
            else:
                st.info("No open issues")
        finally:
            db.close()

    with tab2:
        db = SessionLocal()
        try:
            resolved_issues = db.query(UserIssue).filter(UserIssue.status == 'resolved').order_by(UserIssue.resolved_at.desc()).limit(10).all()

            if resolved_issues:
                for issue in resolved_issues:
                    with st.expander(f"#{issue.id} - {issue.title} ✅"):
                        st.markdown(f"**Type:** {issue.issue_type.replace('_', ' ').title()}")
                        st.markdown(f"**Submitted:** {format_datetime(issue.submitted_at)}")
                        st.markdown(f"**Resolved:** {format_datetime(issue.resolved_at) if issue.resolved_at else 'N/A'}")
                        if issue.resolution_notes:
                            st.success(f"**Resolution:** {issue.resolution_notes}")
            else:
                st.info("No resolved issues yet")
        finally:
            db.close()

    with tab3:
        db = SessionLocal()
        try:
            all_issues = db.query(UserIssue).order_by(UserIssue.submitted_at.desc()).limit(20).all()

            if all_issues:
                issue_data = []
                for issue in all_issues:
                    issue_data.append({
                        'ID': issue.id,
                        'Type': issue.issue_type,
                        'Title': issue.title,
                        'Status': issue.status,
                        'Submitted': format_short_date(issue.submitted_at),
                        'Ticker': issue.ticker_related if issue.ticker_related else '-'
                    })

                st.dataframe(pd.DataFrame(issue_data), use_container_width=True)
            else:
                st.info("No issues submitted yet")
        finally:
            db.close()

st.markdown("---")
st.markdown(f"**Last Updated:** {format_datetime(now_eastern())}")
