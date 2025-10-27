#!/usr/bin/env python3
"""
SPAC News Feed - Streamlit Page

Real-time feed of all SEC filings across SPACs with:
- Date of news
- SPAC ticker
- Tag (Deal Announcement, Timeline Change, IPO Prospectus, etc.)
- Link to filing
- AI-generated summary
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, FilingEvent, SPAC
from utils.filing_logger import get_recent_filings
from utils.timezone_helper import format_news_timestamp, format_datetime, format_long_date, now_eastern


st.set_page_config(
    page_title="SPAC News Feed",
    page_icon="📰",
    layout="wide"
)

# Custom CSS for better news feed styling
st.markdown("""
<style>
    .filing-card {
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 4px solid #4CAF50;
    }
    .filing-critical {
        border-left-color: #f44336;
    }
    .filing-high {
        border-left-color: #ff9800;
    }
    .filing-medium {
        border-left-color: #2196F3;
    }
    .filing-low {
        border-left-color: #9E9E9E;
    }
    .ticker-badge {
        display: inline-block;
        padding: 4px 12px;
        background: #1E88E5;
        color: white;
        border-radius: 12px;
        font-weight: bold;
        margin-right: 10px;
    }
    .tag-badge {
        display: inline-block;
        padding: 4px 10px;
        background: #66BB6A;
        color: white;
        border-radius: 10px;
        font-size: 0.9em;
        margin-right: 8px;
    }
    .date-text {
        color: #757575;
        font-size: 0.9em;
    }
</style>
""", unsafe_allow_html=True)

st.title("📰 SPAC News Feed")
st.markdown("Real-time SEC filings across all SPACs")

# Sidebar filters
st.sidebar.header("Filters")

# Date range filter
days_back = st.sidebar.selectbox(
    "Time Period",
    options=[7, 14, 30, 60, 90],
    index=2,  # Default to 30 days
    format_func=lambda x: f"Last {x} days"
)

# Ticker filter
db = SessionLocal()
all_tickers = [t[0] for t in db.query(SPAC.ticker).filter(SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])).order_by(SPAC.ticker).all()]
db.close()

ticker_filter = st.sidebar.multiselect(
    "Filter by SPAC",
    options=all_tickers,
    default=[]
)

# Tag filter
tag_filter = st.sidebar.multiselect(
    "Filter by Event Type",
    options=[
        'Deal Announcement',
        'Deal Communication',
        'Deal Proxy',
        'Vote Results',
        'Timeline Change',
        'IPO Prospectus',
        'Deal Completion',
        'Quarterly Report',
        'Annual Report',
        'Other'
    ],
    default=[]
)

# Priority filter
priority_filter = st.sidebar.multiselect(
    "Filter by Priority",
    options=['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
    default=[]
)

# Fetch filings
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_filings(days: int):
    """Load recent filings from database"""
    return get_recent_filings(days=days, limit=500)

filings = load_filings(days_back)

# Apply filters
if ticker_filter:
    filings = [f for f in filings if f['ticker'] in ticker_filter]

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
    deal_related = len([f for f in filings if 'Deal' in f['tag']])
    st.metric("Deal-Related", deal_related)
with col4:
    unique_spacs = len(set(f['ticker'] for f in filings))
    st.metric("Active SPACs", unique_spacs)

st.markdown("---")

# Display filings
if not filings:
    st.info("No filings found for selected filters")
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
            # Priority-based card styling
            priority_class = f"filing-{filing['priority'].lower()}" if filing.get('priority') else "filing-medium"

            # Build filing card HTML
            filing_html = f"""
            <div class="filing-card {priority_class}">
                <div>
                    <span class="ticker-badge">{filing['ticker']}</span>
                    <span class="tag-badge">{filing['tag']}</span>
                    <span class="date-text">{format_news_timestamp(filing['detected_at'])}</span>
                </div>
            """

            # Add summary if available
            if filing.get('summary'):
                filing_html += f"<p style='margin-top: 10px; margin-bottom: 10px;'>{filing['summary']}</p>"

            # Add filing link
            filing_html += f"""
                <div style='margin-top: 8px;'>
                    <a href="{filing['filing_url']}" target="_blank" style='color: #1E88E5; text-decoration: none;'>
                        🔗 View {filing['filing_type']}
                    </a>
            """

            # Add item number if 8-K
            if filing.get('item_number'):
                filing_html += f" <span style='color: #757575; font-size: 0.9em;'>(Item {filing['item_number']})</span>"

            filing_html += """
                </div>
            </div>
            """

            st.markdown(filing_html, unsafe_allow_html=True)

        st.markdown("---")

# Export to CSV button
if st.sidebar.button("📥 Export to CSV"):
    df = pd.DataFrame(filings)
    csv = df.to_csv(index=False)
    st.sidebar.download_button(
        label="Download CSV",
        data=csv,
        file_name=f"spac_news_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

# Footer
st.markdown("---")
st.caption(f"Last updated: {format_datetime(now_eastern())} | Showing {len(filings)} filings from last {days_back} days")
