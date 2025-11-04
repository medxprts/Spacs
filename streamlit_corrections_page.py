"""
Streamlit Data Quality & Corrections Page

View and manage data quality corrections with human-readable display.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from database import SessionLocal
from sqlalchemy import text
from utils.correction_display_helpers import (
    format_value_for_display,
    format_correction_for_telegram,
    get_value_from_correction,
    get_metadata_from_correction
)
import json


def format_correction_for_streamlit(ticker: str, final_fix: dict) -> pd.DataFrame:
    """
    Format correction as DataFrame for Streamlit display.

    Args:
        ticker: SPAC ticker
        final_fix: Final fix dict (old or new format)

    Returns:
        DataFrame with Field, Old Value, New Value, Note columns
    """
    rows = []

    for field, value in final_fix.items():
        # Get actual value and metadata
        actual_value = get_value_from_correction(value)
        metadata = get_metadata_from_correction(value)

        # Format for display
        display_value = format_value_for_display(field, value)
        note = metadata.get('note', '')

        rows.append({
            'Field': field,
            'Value': display_value,
            'Note': note if note else '-',
            'Raw Value': str(actual_value) if actual_value is not None else 'None'
        })

    return pd.DataFrame(rows)


def show_corrections_page():
    """Main corrections page"""
    st.title("📊 Data Quality & Corrections")

    st.markdown("""
    View all data quality corrections applied to SPACs.
    **New format** shows structured data (value + metadata) for better machine learning.
    """)

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        ticker_filter = st.text_input("Filter by Ticker", "")

    with col2:
        issue_type_options = get_issue_types()
        issue_type_filter = st.selectbox(
            "Filter by Issue Type",
            ["All"] + issue_type_options
        )

    with col3:
        limit = st.number_input("Show Last N Corrections", value=100, min_value=10, max_value=500, step=10)

    # Load corrections
    corrections = load_corrections(
        ticker=ticker_filter if ticker_filter else None,
        issue_type=issue_type_filter if issue_type_filter != "All" else None,
        limit=limit
    )

    if not corrections:
        st.info("No corrections found matching filters.")
        return

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Corrections", len(corrections))

    with col2:
        unique_tickers = len(set(c['ticker'] for c in corrections))
        st.metric("Unique SPACs", unique_tickers)

    with col3:
        unique_fields = len(set(
            field
            for c in corrections
            for field in c['final_fix'].keys()
        ))
        st.metric("Fields Corrected", unique_fields)

    with col4:
        recent = len([c for c in corrections if (datetime.now() - c['created_at']).days <= 7])
        st.metric("Last 7 Days", recent)

    # Display corrections
    st.markdown("---")
    st.subheader("Recent Corrections")

    # Tabs for different views
    tab1, tab2 = st.tabs(["📋 Detailed View", "📊 Table View"])

    with tab1:
        show_detailed_view(corrections)

    with tab2:
        show_table_view(corrections)


def show_detailed_view(corrections: list):
    """Show corrections in detailed expandable format"""
    for i, correction in enumerate(corrections):
        ticker = correction['ticker']
        issue_type = correction['issue_type']
        created_at = correction['created_at']
        final_fix = correction['final_fix']
        learning_notes = correction['learning_notes']

        # Create expander
        with st.expander(
            f"**{ticker}** - {issue_type} ({created_at.strftime('%Y-%m-%d %H:%M')})",
            expanded=(i < 3)  # Expand first 3
        ):
            # Learning notes
            if learning_notes:
                st.info(f"💡 **Note:** {learning_notes}")

            # Correction details
            st.markdown("#### Fields Corrected:")

            # Format as DataFrame
            df = format_correction_for_streamlit(ticker, final_fix)

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Field': st.column_config.TextColumn(width="medium"),
                    'Value': st.column_config.TextColumn(width="large"),
                    'Note': st.column_config.TextColumn(width="large"),
                    'Raw Value': st.column_config.TextColumn(width="medium")
                }
            )

            # Show raw JSON (collapsible with checkbox instead of nested expander)
            if st.checkbox(f"🔍 View Raw JSON###{i}", key=f"raw_json_{i}"):
                st.json(final_fix)


def show_table_view(corrections: list):
    """Show corrections in compact table format"""
    rows = []

    for correction in corrections:
        ticker = correction['ticker']
        issue_type = correction['issue_type']
        created_at = correction['created_at']
        final_fix = correction['final_fix']

        # Get fields corrected
        fields = list(final_fix.keys())
        fields_str = ', '.join(fields[:3])
        if len(fields) > 3:
            fields_str += f" (+{len(fields) - 3} more)"

        rows.append({
            'Ticker': ticker,
            'Issue Type': issue_type,
            'Fields': fields_str,
            'Field Count': len(fields),
            'Date': created_at.strftime('%Y-%m-%d'),
            'Time': created_at.strftime('%H:%M')
        })

    df = pd.DataFrame(rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            'Ticker': st.column_config.TextColumn(width="small"),
            'Issue Type': st.column_config.TextColumn(width="medium"),
            'Fields': st.column_config.TextColumn(width="large"),
            'Field Count': st.column_config.NumberColumn(width="small"),
            'Date': st.column_config.TextColumn(width="small"),
            'Time': st.column_config.TextColumn(width="small")
        }
    )


@st.cache_data(ttl=300)
def load_corrections(ticker: str = None, issue_type: str = None, limit: int = 50):
    """Load corrections from database"""
    db = SessionLocal()

    try:
        where_clauses = ["final_fix IS NOT NULL"]
        params = {'limit': limit}

        if ticker:
            where_clauses.append("ticker ILIKE :ticker")
            params['ticker'] = f"%{ticker}%"

        if issue_type:
            where_clauses.append("issue_type = :issue_type")
            params['issue_type'] = issue_type

        query = f"""
            SELECT
                id,
                ticker,
                issue_type,
                final_fix,
                learning_notes,
                created_at
            FROM data_quality_conversations
            WHERE {' AND '.join(where_clauses)}
            ORDER BY created_at DESC
            LIMIT :limit
        """

        result = db.execute(text(query), params)
        rows = result.fetchall()

        corrections = []
        for row in rows:
            corrections.append({
                'id': row[0],
                'ticker': row[1],
                'issue_type': row[2],
                'final_fix': row[3],
                'learning_notes': row[4],
                'created_at': row[5]
            })

        return corrections

    finally:
        db.close()


@st.cache_data(ttl=600)
def get_issue_types():
    """Get list of issue types"""
    db = SessionLocal()

    try:
        query = """
            SELECT DISTINCT issue_type
            FROM data_quality_conversations
            WHERE final_fix IS NOT NULL
            ORDER BY issue_type
        """

        result = db.execute(text(query))
        return [row[0] for row in result.fetchall()]

    finally:
        db.close()


# For testing standalone
if __name__ == '__main__':
    st.set_page_config(
        page_title="Data Quality & Corrections",
        page_icon="📊",
        layout="wide"
    )

    show_corrections_page()
