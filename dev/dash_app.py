#!/usr/bin/env python3
"""
dash_app.py - Dash Dashboard for SPAC Research Platform

Purpose: Modern, interactive dashboard with powerful table controls
Advantages over Streamlit:
- Dash DataTable: Built-in sorting, filtering, pagination, export
- Better performance for large datasets
- More customizable styling
- Professional UI components

Usage:
    python3 dash_app.py
    # Opens on http://localhost:8050

    # Production
    gunicorn dash_app:server -b 0.0.0.0:8050 --workers 4
"""

import dash
from dash import dcc, html, dash_table, Input, Output, State, callback
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, SPAC, MarketSnapshot
from pre_ipo_database import SessionLocal as PreIPOSessionLocal, PreIPOSPAC

# Initialize Dash app with Bootstrap theme
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.CYBORG],  # Dark theme (or try BOOTSTRAP, FLATLY for light)
    suppress_callback_exceptions=True,
    title="LEVP SPAC Platform"
)

server = app.server  # For gunicorn deployment

# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

def load_spac_data():
    """Load all SPAC data from database"""
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).all()
        data = []
        today = datetime.now().date()

        for s in spacs:
            # Calculate days_to_deadline
            days_left = None
            if s.deadline_date:
                deadline = s.deadline_date.date() if isinstance(s.deadline_date, datetime) else s.deadline_date
                days_left = (deadline - today).days

            data.append({
                'ticker': s.ticker,
                'company': s.company,
                'price': s.price,
                'price_change_24h': s.price_change_24h,
                'premium': s.premium,
                'trust_value': s.trust_value,
                'trust_cash': s.trust_cash,
                'deal_status': s.deal_status,
                'target': s.target,
                'expected_close': s.expected_close,
                'announced_date': s.announced_date,
                'ipo_date': s.ipo_date,
                'deadline_date': s.deadline_date,
                'days_to_deadline': days_left,
                'banker': s.banker,
                'sector': s.sector,
                'deal_value': s.deal_value,
                'shares_outstanding': s.shares_outstanding,
                'market_cap': s.market_cap,
                'warrant_ticker': s.warrant_ticker,
                'unit_ticker': s.unit_ticker
            })

        return pd.DataFrame(data)
    finally:
        db.close()


def load_premium_history(days=90):
    """Load historical premium data"""
    db = SessionLocal()
    try:
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
                'avg_premium_announced': s.avg_premium_announced,
                'median_premium_announced': s.median_premium_announced,
                'count_predeal': s.count_predeal,
                'count_announced': s.count_announced
            })

        return pd.DataFrame(data)
    finally:
        db.close()


# ============================================================================
# LAYOUT COMPONENTS
# ============================================================================

def create_navbar():
    """Create navigation bar"""
    return dbc.NavbarSimple(
        children=[
            dbc.NavItem(dbc.NavLink("Live Deals", href="/", id="nav-live")),
            dbc.NavItem(dbc.NavLink("Pre-Deal SPACs", href="/predeal", id="nav-predeal")),
            dbc.NavItem(dbc.NavLink("Completed", href="/completed", id="nav-completed")),
            dbc.NavItem(dbc.NavLink("Analytics", href="/analytics", id="nav-analytics")),
            dbc.NavItem(dbc.NavLink("AI Chat", href="/chat", id="nav-chat")),
        ],
        brand="📊 LEVP SPAC Platform",
        brand_href="/",
        color="primary",
        dark=True,
        className="mb-3"
    )


def create_summary_cards(df):
    """Create summary metrics cards"""
    announced_count = len(df[df['deal_status'] == 'ANNOUNCED'])
    completed_count = len(df[df['deal_status'] == 'COMPLETED'])
    searching_count = len(df[df['deal_status'] == 'SEARCHING'])

    avg_premium_announced = df[df['deal_status'] == 'ANNOUNCED']['premium'].mean() if announced_count > 0 else 0
    avg_premium_predeal = df[df['deal_status'] == 'SEARCHING']['premium'].mean() if searching_count > 0 else 0

    cards = dbc.Row([
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Total SPACs", className="card-title"),
                    html.H2(f"{len(df)}", className="text-primary")
                ])
            ], color="dark", outline=True),
            width=2
        ),
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Announced Deals", className="card-title"),
                    html.H2(f"{announced_count}", className="text-success")
                ])
            ], color="dark", outline=True),
            width=2
        ),
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Avg Premium (Deals)", className="card-title"),
                    html.H2(f"{avg_premium_announced:.1f}%", className="text-info")
                ])
            ], color="dark", outline=True),
            width=2
        ),
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Pre-Deal SPACs", className="card-title"),
                    html.H2(f"{searching_count}", className="text-warning")
                ])
            ], color="dark", outline=True),
            width=2
        ),
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Avg Premium (Pre-Deal)", className="card-title"),
                    html.H2(f"{avg_premium_predeal:.1f}%", className="text-secondary")
                ])
            ], color="dark", outline=True),
            width=2
        ),
        dbc.Col(
            dbc.Card([
                dbc.CardBody([
                    html.H5("Completed", className="card-title"),
                    html.H2(f"{completed_count}", className="text-muted")
                ])
            ], color="dark", outline=True),
            width=2
        ),
    ], className="mb-4")

    return cards


def create_interactive_table(df, table_id, page_size=25):
    """
    Create interactive DataTable with sorting, filtering, pagination, export

    This is the KEY advantage over Streamlit - Dash DataTable is incredibly powerful!
    """
    # Format columns for display
    df_display = df.copy()

    # Format numeric columns
    if 'premium' in df_display.columns:
        df_display['premium'] = df_display['premium'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if 'price' in df_display.columns:
        df_display['price'] = df_display['price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "")
    if 'price_change_24h' in df_display.columns:
        df_display['price_change_24h'] = df_display['price_change_24h'].apply(
            lambda x: f"{x:+.2f}%" if pd.notna(x) else ""
        )
    if 'trust_value' in df_display.columns:
        df_display['trust_value'] = df_display['trust_value'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "")
    if 'trust_cash' in df_display.columns:
        df_display['trust_cash'] = df_display['trust_cash'].apply(
            lambda x: f"${x/1e6:.1f}M" if pd.notna(x) and x > 0 else ""
        )
    if 'market_cap' in df_display.columns:
        df_display['market_cap'] = df_display['market_cap'].apply(
            lambda x: f"${x/1e6:.0f}M" if pd.notna(x) and x > 0 else ""
        )

    # Format dates (handle missing values)
    date_columns = ['expected_close', 'announced_date', 'ipo_date', 'deadline_date']
    for col in date_columns:
        if col in df_display.columns:
            df_display[col] = pd.to_datetime(df_display[col], errors='coerce').dt.strftime('%Y-%m-%d')
            df_display[col] = df_display[col].fillna('')  # Replace NaT with empty string

    # Define column styling
    columns = []
    for col in df_display.columns:
        col_config = {'name': col.replace('_', ' ').title(), 'id': col}

        # Numeric columns - right align
        if col in ['premium', 'price', 'price_change_24h', 'trust_value', 'trust_cash',
                   'market_cap', 'days_to_deadline']:
            col_config['type'] = 'numeric'

        columns.append(col_config)

    # Create DataTable with ALL the interactive features
    table = dash_table.DataTable(
        id=table_id,
        columns=columns,
        data=df_display.to_dict('records'),

        # SORTING: Click column headers to sort
        sort_action='native',
        sort_mode='multi',  # Hold shift to sort by multiple columns

        # FILTERING: Type in column headers to filter
        filter_action='native',

        # PAGINATION
        page_size=page_size,
        page_action='native',

        # SELECTION: Click rows to select
        row_selectable='multi',
        selected_rows=[],

        # EXPORT: Download as CSV
        export_format='csv',
        export_headers='display',

        # STYLING
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'backgroundColor': '#1e1e1e',
            'color': 'white',
            'border': '1px solid #444',
            'minWidth': '100px',
            'maxWidth': '300px',
            'overflow': 'hidden',
            'textOverflow': 'ellipsis',
        },
        style_header={
            'backgroundColor': '#2a2a2a',
            'fontWeight': 'bold',
            'border': '1px solid #666',
            'color': 'white'
        },
        style_data_conditional=[
            # Conditional formatting for premium
            {
                'if': {
                    'filter_query': '{premium} contains "+"',
                },
                'backgroundColor': '#1a4d1a',  # Green for positive
            },
            {
                'if': {
                    'filter_query': '{premium} contains "-"',
                },
                'backgroundColor': '#4d1a1a',  # Red for negative
            },
            # Highlight selected rows
            {
                'if': {'state': 'selected'},
                'backgroundColor': '#004080',
                'border': '1px solid white',
            }
        ],

        # Tooltip for long text
        tooltip_data=[
            {
                column: {'value': str(value), 'type': 'markdown'}
                for column, value in row.items()
            } for row in df_display.to_dict('records')
        ],
        tooltip_duration=None,

        # Fixed header while scrolling
        fixed_rows={'headers': True},
    )

    return table


# ============================================================================
# PAGE LAYOUTS
# ============================================================================

def live_deals_page():
    """Live Deals page - Announced deals with interactive table"""
    df = load_spac_data()
    df_deals = df[df['deal_status'] == 'ANNOUNCED'].copy()

    # Select and reorder columns
    columns_to_show = ['ticker', 'company', 'target', 'price', 'price_change_24h', 'premium',
                       'trust_value', 'deal_value', 'announced_date', 'expected_close',
                       'days_to_deadline', 'banker', 'sector']
    df_deals = df_deals[columns_to_show]

    # Sort by premium descending
    df_deals = df_deals.sort_values('premium', ascending=False)

    layout = html.Div([
        html.H2("📈 Live Deals - Announced Mergers", className="mb-3"),
        html.P(f"Showing {len(df_deals)} announced SPAC deals", className="text-muted mb-4"),

        create_summary_cards(df),

        # Filters
        dbc.Row([
            dbc.Col([
                html.Label("Filter by Banker:"),
                dcc.Dropdown(
                    id='banker-filter',
                    options=[{'label': 'All', 'value': 'all'}] +
                            [{'label': b, 'value': b} for b in df_deals['banker'].dropna().unique()],
                    value='all',
                    clearable=False,
                    className="mb-3"
                )
            ], width=3),
            dbc.Col([
                html.Label("Filter by Sector:"),
                dcc.Dropdown(
                    id='sector-filter',
                    options=[{'label': 'All', 'value': 'all'}] +
                            [{'label': s, 'value': s} for s in df_deals['sector'].dropna().unique()],
                    value='all',
                    clearable=False,
                    className="mb-3"
                )
            ], width=3),
            dbc.Col([
                html.Label("Premium Range:"),
                dcc.RangeSlider(
                    id='premium-slider',
                    min=df_deals['premium'].min(),
                    max=df_deals['premium'].max(),
                    value=[df_deals['premium'].min(), df_deals['premium'].max()],
                    marks={int(df_deals['premium'].min()): f"{int(df_deals['premium'].min())}%",
                           int(df_deals['premium'].max()): f"{int(df_deals['premium'].max())}%"},
                    tooltip={"placement": "bottom", "always_visible": True}
                )
            ], width=6),
        ], className="mb-4"),

        # The star of the show - Interactive DataTable!
        html.Div(id='deals-table-container', children=[
            create_interactive_table(df_deals, 'deals-table', page_size=25)
        ]),

        # Quick stats below table
        html.Div(id='table-stats', className="mt-3")
    ])

    return layout


def predeal_spacs_page():
    """Pre-Deal SPACs page - SPACs still searching for targets"""
    df = load_spac_data()
    df_predeal = df[df['deal_status'] == 'SEARCHING'].copy()

    # Select columns
    columns_to_show = ['ticker', 'company', 'price', 'price_change_24h', 'premium',
                       'trust_value', 'trust_cash', 'ipo_date', 'deadline_date',
                       'days_to_deadline', 'banker', 'sector']
    df_predeal = df_predeal[columns_to_show]

    # Sort by days_to_deadline
    df_predeal = df_predeal.sort_values('days_to_deadline', ascending=True)

    # Risk classification
    df_predeal['risk_level'] = df_predeal['days_to_deadline'].apply(
        lambda x: '🔴 Urgent' if pd.notna(x) and x < 90
                  else '🟡 Safe' if pd.notna(x) and x > 180
                  else '🟠 Moderate'
    )

    layout = html.Div([
        html.H2("🔍 Pre-Deal SPACs - Searching for Targets", className="mb-3"),
        html.P(f"Showing {len(df_predeal)} pre-deal SPACs", className="text-muted mb-4"),

        create_summary_cards(df),

        # Interactive table
        create_interactive_table(df_predeal, 'predeal-table', page_size=30)
    ])

    return layout


def analytics_page():
    """Analytics page - Charts and visualizations"""
    df = load_spac_data()
    df_history = load_premium_history(days=90)

    # Premium distribution
    fig_premium = px.histogram(
        df[df['deal_status'].isin(['SEARCHING', 'ANNOUNCED'])],
        x='premium',
        color='deal_status',
        nbins=50,
        title='Premium Distribution',
        labels={'premium': 'Premium (%)', 'count': 'Number of SPACs'},
        template='plotly_dark'
    )

    # Premium over time
    fig_time = go.Figure()
    if not df_history.empty:
        fig_time.add_trace(go.Scatter(
            x=df_history['date'],
            y=df_history['avg_premium_predeal'],
            mode='lines',
            name='Pre-Deal Avg',
            line=dict(color='#636EFA')
        ))
        fig_time.add_trace(go.Scatter(
            x=df_history['date'],
            y=df_history['avg_premium_announced'],
            mode='lines',
            name='Announced Avg',
            line=dict(color='#00CC96')
        ))
    fig_time.update_layout(
        title='Average Premium Over Time (90 Days)',
        xaxis_title='Date',
        yaxis_title='Premium (%)',
        template='plotly_dark',
        hovermode='x unified'
    )

    # Banker distribution
    banker_counts = df.groupby('banker').size().sort_values(ascending=False).head(10)
    fig_bankers = px.bar(
        x=banker_counts.values,
        y=banker_counts.index,
        orientation='h',
        title='Top 10 Bankers by SPAC Count',
        labels={'x': 'Number of SPACs', 'y': 'Banker'},
        template='plotly_dark'
    )

    layout = html.Div([
        html.H2("📊 Market Analytics", className="mb-4"),

        dbc.Row([
            dbc.Col([dcc.Graph(figure=fig_premium)], width=6),
            dbc.Col([dcc.Graph(figure=fig_bankers)], width=6),
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([dcc.Graph(figure=fig_time)], width=12),
        ])
    ])

    return layout


def chat_page():
    """AI Chat page - Natural language queries"""
    layout = html.Div([
        html.H2("🤖 AI SPAC Research Assistant", className="mb-3"),
        html.P("Ask me anything about SPACs in natural language!", className="text-muted mb-4"),

        dbc.Alert(
            "AI Chat integration coming soon! Will use DeepSeek API for natural language queries.",
            color="info"
        ),

        dbc.Row([
            dbc.Col([
                dbc.Textarea(
                    id='chat-input',
                    placeholder="e.g., 'Show me Goldman Sachs SPACs with premium over 15%'",
                    style={'height': '100px'},
                    className="mb-3"
                ),
                dbc.Button("Ask AI", id='chat-submit', color="primary", className="mb-3"),
            ], width=12)
        ]),

        html.Div(id='chat-output', className="mt-3")
    ])

    return layout


# ============================================================================
# MAIN APP LAYOUT
# ============================================================================

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    create_navbar(),
    dbc.Container([
        html.Div(id='page-content', className="mt-3")
    ], fluid=True, style={'backgroundColor': '#0e1117', 'minHeight': '100vh'})
])


# ============================================================================
# CALLBACKS
# ============================================================================

@callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    """Route to different pages based on URL"""
    if pathname == '/predeal':
        return predeal_spacs_page()
    elif pathname == '/completed':
        return html.Div([html.H2("Completed Deals"), html.P("Coming soon...")])
    elif pathname == '/analytics':
        return analytics_page()
    elif pathname == '/chat':
        return chat_page()
    else:  # Default to live deals
        return live_deals_page()


@callback(
    Output('deals-table-container', 'children'),
    [Input('banker-filter', 'value'),
     Input('sector-filter', 'value'),
     Input('premium-slider', 'value')]
)
def update_deals_table(banker, sector, premium_range):
    """Update table based on filters"""
    df = load_spac_data()
    df_deals = df[df['deal_status'] == 'ANNOUNCED'].copy()

    # Apply filters
    if banker != 'all':
        df_deals = df_deals[df_deals['banker'] == banker]
    if sector != 'all':
        df_deals = df_deals[df_deals['sector'] == sector]
    if premium_range:
        df_deals = df_deals[
            (df_deals['premium'] >= premium_range[0]) &
            (df_deals['premium'] <= premium_range[1])
        ]

    columns_to_show = ['ticker', 'company', 'target', 'price', 'price_change_24h', 'premium',
                       'trust_value', 'deal_value', 'announced_date', 'expected_close',
                       'days_to_deadline', 'banker', 'sector']
    df_deals = df_deals[columns_to_show]
    df_deals = df_deals.sort_values('premium', ascending=False)

    return create_interactive_table(df_deals, 'deals-table', page_size=25)


@callback(
    Output('table-stats', 'children'),
    Input('deals-table', 'selected_rows'),
    State('deals-table', 'data')
)
def show_selection_stats(selected_rows, data):
    """Show stats for selected rows"""
    if not selected_rows:
        return ""

    selected_data = [data[i] for i in selected_rows]
    df_selected = pd.DataFrame(selected_data)

    return dbc.Alert([
        html.H5(f"Selected {len(selected_rows)} rows"),
        html.P(f"Average Premium: {df_selected['premium'].str.rstrip('%').astype(float).mean():.2f}%"),
    ], color="info")


# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == '__main__':
    print("="*70)
    print("🚀 Starting Dash SPAC Dashboard")
    print("="*70)
    print(f"📊 Dashboard: http://localhost:8050")
    print(f"📝 Features:")
    print(f"   ✓ Interactive tables with sorting/filtering/pagination")
    print(f"   ✓ Export to CSV")
    print(f"   ✓ Multi-row selection")
    print(f"   ✓ Real-time filtering")
    print("="*70)

    app.run(debug=True, host='0.0.0.0', port=8050)
