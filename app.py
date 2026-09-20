import streamlit as st
import sqlite3
import pandas as pd
from screener import StockScreeningEngine, update_past_predictions, init_db, DB_NAME, CURATED_UNIVERSES
import plotly.graph_objects as go
import yfinance as yf

init_db()

st.set_page_config(page_title="Alpha Horizon Terminal", layout="wide")

# --- STRICT PURE LIGHT THEME CSS INJECTION ---
st.markdown("""
<style>
    /* Force complete white background and pure black/dark text */
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stAppViewBlockContainer"] {
        background-color: #FFFFFF !important;
        color: #111111 !important;
    }
    
    /* Ensure all text, titles, labels stay visible & dark */
    h1, h2, h3, h4, h5, h6, p, span, div, label {
        color: #111111 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #F8F9FA !important;
        border-right: 1px solid #E5E7EB !important;
    }
    
    /* Zerodha Kite Watchlist Card Styling */
    .kite-row {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        transition: transform 0.1s ease, box-shadow 0.1s ease;
    }
    .kite-row:hover {
        border-color: #CBD5E1;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.08);
    }
    
    /* Price color classes */
    .bull-green {
        color: #00A25B !important;
        font-weight: 700;
    }
    .bear-red {
        color: #DF514C !important;
        font-weight: 700;
    }
    
    /* Sub-text tags */
    .ticker-sub {
        font-size: 0.75rem;
        color: #64748B !important;
        font-weight: 600;
    }
    
    .pill-bull {
        background-color: #E6F7EF;
        color: #00A25B !important;
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
    .pill-bear {
        background-color: #FDF0EE;
        color: #DF514C !important;
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State for active watchlist
if "active_watchlist" not in st.session_state:
    st.session_state.active_watchlist = "TRENT, VBL, POLYCAB, KEI, NIFTYBEES, GOLDBEES"

st.title("📊 Alpha Horizon Watchlist Terminal")

# Top Indices Strip (Zerodha Kite Style)
col_idx1, col_idx2, col_idx3, col_idx4 = st.columns(4)
col_idx1.metric("NIFTY 50", "23,346.40", "+75.80 (+0.32%)")
col_idx2.metric("BANK NIFTY", "56,358.70", "+302.95 (+0.54%)")
col_idx3.metric("INDIA VIX", "13.45", "-0.40 (-2.88%)", delta_color="inverse")
col_idx4.metric("SYSTEM STATE", "LIVE ENGINE", "Ready")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📱 Kite Watchlist & Scanner", "📜 Performance Ledger", "🧪 Backtest Sandbox"])

# --- SIDEBAR: INBUILT DISCOVERY & QUEUE ---
st.sidebar.subheader("🔍 Inbuilt Stock & ETF Finder")
st.sidebar.caption("Tap any button below to instantly populate your watchlist:")

if st.sidebar.button("🏢 Load Nifty 50 Giants"):
    st.session_state.active_watchlist = ", ".join([t.replace(".NS", "") for t in CURATED_UNIVERSES["Nifty 50 Heavyweights"][:12]])

if st.sidebar.button("🚀 Load High-Growth Midcaps"):
    st.session_state.active_watchlist = ", ".join([t.replace(".NS", "") for t in CURATED_UNIVERSES["High-Growth Midcaps"]])

if st.sidebar.button("🪙 Load Top 50 Liquid ETFs"):
    st.session_state.active_watchlist = ", ".join([t.replace(".NS", "") for t in CURATED_UNIVERSES["Top 50 Liquid ETFs"][:15]])

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Active Watchlist Queue")

# Editable text area bound to session state
watchlist_input = st.sidebar.text_area(
    "Tickers in Queue (Comma separated):", 
    value=st.session_state.active_watchlist,
    height=120
)
st.session_state.active_watchlist = watchlist_input

# Parse tickers safely
parsed_tickers = []
if watchlist_input:
    for token in [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]:
        if not (token.endswith(".NS") or token.endswith(".BO")):
            parsed_tickers.append(f"{token}.NS")
        else:
            parsed_tickers.append(token)

run_scan = st.sidebar.button("🚀 Run Quantitative Scan", type="primary")

# --- TAB 1: ZERODHA KITE STYLE WATCHLIST ---
with tab1:
    if run_scan:
        if not parsed_tickers:
            st.warning("Please add or select tickers to scan.")
        else:
            with st.status("⚡ Scanning Market Technicals & Volume Flow...", expanded=True) as status:
                st.write("🔄 Syncing historical target records...")
                update_past_predictions()
                st.write(f"📈 Querying OHLC data for {len(parsed_tickers)} assets...")
                engine = StockScreeningEngine(parsed_tickers)
                engine.fetch_data()
                st.write("🛡️ Evaluating 200 SMA trends, RVol footprints & ML Signal Confidence...")
                results_df = engine.apply_filters()
                status.update(label="✅ Scan Complete!", state="complete", expanded=False)
                
            if not results_df.empty:
                st.subheader(f"Watchlist Results ({len(results_df)} Assets)")
                
                # Render each stock card in Zerodha Watchlist aesthetic
                for _, row in results_df.iterrows():
                    is_bull = row["Momentum Vector"] == "Bullish"
                    color_cls = "bull-green" if is_bull else "bear-red"
                    pill_cls = "pill-bull" if is_bull else "pill-bear"
                    chg_sign = "+" if row["Price Change"] >= 0 else ""
                    
                    with st.container():
                        st.markdown(f"""
                        <div class="kite-row">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="font-size: 1.15rem; font-weight: 700; color: #111;">{row['Ticker']}</span>
                                    <span class="ticker-sub">NSE</span>
                                    <span class="{pill_cls}" style="margin-left: 8px;">{row['Momentum Vector'].upper()}</span>
                                    <span style="font-size: 0.8rem; background: #F1F5F9; color: #475569; padding: 2px 6px; border-radius: 4px; margin-left: 4px; font-weight: 600;">RVol: {row['RVol']}x</span>
                                </div>
                                <div style="text-align: right;">
                                    <div class="{color_cls}" style="font-size: 1.15rem;">₹{row['Current Price']}</div>
                                    <div class="{color_cls}" style="font-size: 0.8rem;">{chg_sign}{row['Price Change']} ({chg_sign}{row['Price Change Pct']}%)</div>
                                </div>
                            </div>
                            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #E2E8F0; font-size: 0.82rem;">
                                <div><span style="color: #64748B;">Entry Range:</span><br><b>{row['Entry Range']}</b></div>
                                <div><span style="color: #64748B;">Stoploss:</span><br><b style="color: #DF514C;">₹{row['Stoploss']}</b></div>
                                <div><span style="color: #64748B;">Swing (1-15d):</span><br><b class="{color_cls}">{row['Swing Target 1-15d']}</b></div>
                                <div><span style="color: #64748B;">Target (20-90d):</span><br><b class="{color_cls}">{row['Structural Target 20-90d']}</b></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Expandable drawer for deep analytics
                        with st.expander(f"📊 View Deep Analytics & Chart Link for {row['Ticker']}"):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("ML Signal Confidence", f"{row['ML Signal Confidence']}%")
                            c2.metric("Institutional Volume (FII/DII)", row["FII/DII Institutional Flow"])
                            c3.metric("Relative Volume Footprint", f"{row['RVol']}x Average")
                            
                            st.markdown(f"""
                            👉 **[Open {row['Ticker']} Live Chart on TradingView ↗]({row['TradingView Link']})**
                            """, unsafe_allow_html=True)
                            
                            # Local Candlestick preview
                            try:
                                df_c = yf.Ticker(row["RawTicker"]).history(period="3mo")
                                fig = go.Figure(data=[go.Candlestick(
                                    x=df_c.index, open=df_c['Open'], high=df_c['High'],
                                    low=df_c['Low'], close=df_c['Close']
                                )])
                                fig.update_layout(
                                    title=f"{row['Ticker']} 3-Month Price Action",
                                    height=300,
                                    margin=dict(l=20, r=20, t=40, b=20),
                                    xaxis_rangeslider_visible=False,
                                    paper_bgcolor='#FFFFFF',
                                    plot_bgcolor='#FFFFFF'
                                )
                                st.plotly_chart(fig, use_container_width=True)
                            except Exception:
                                st.caption("Chart preview unavailable.")
            else:
                st.info("No matching trend setups found for the selected tickers.")
    else:
        st.info("👈 Choose an inbuilt universe from the sidebar or type tickers, then tap **'🚀 Run Quantitative Scan'**.")

# --- TAB 2: AUDIT & LEDGER ---
with tab2:
    st.subheader("Performance Tracking Audit Ledger")
    if st.button("Force Synchronize Tracker Outcomes"):
        with st.spinner("Auditing past targets against current highs/lows..."):
            update_past_predictions()
            st.rerun()

    try:
        conn = sqlite3.connect(DB_NAME)
        ledger_df = pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC", conn)
        conn.close()
        
        if not ledger_df.empty:
            ledger_df["ticker"] = ledger_df["ticker"].str.replace(".NS", "").str.replace(".BO", "")
            
            def highlight_status(val):
                if val == 'Hit': return 'background-color: #E6F7EF; color: #00A25B; font-weight: bold;'
                if val == 'Missed': return 'background-color: #FDF0EE; color: #DF514C; font-weight: bold;'
                return 'background-color: #FFF7ED; color: #C2410C; font-weight: bold;'

            st.dataframe(ledger_df.style.map(highlight_status, subset=["status_short", "status_long"]), use_container_width=True)
        else:
            st.info("No historical predictions logged yet. Run a scan to register trades.")
    except Exception as e:
        st.error(f"Ledger load failure: {e}")

# --- TAB 3: BACKTEST ---
with tab3:
    st.subheader("Historical Strategy Backtest Sandbox")
    st.write("Simulates entry signals and reward-to-risk performance over historical daily candles.")
    
    if st.button("🔬 Execute Backtest Simulation"):
        with st.spinner("Processing historical backtest cycles..."):
            engine = StockScreeningEngine(parsed_tickers if parsed_tickers else CURATED_UNIVERSES["Nifty 50 Heavyweights"][:10])
            engine.fetch_data()
            bt_df = engine.run_backtest()
            
            if not bt_df.empty:
                st.success(f"Simulation completed across {len(bt_df)} setups.")
                avg_gain = bt_df["Simulated Peak Return %"].mean()
                avg_dd = bt_df["Simulated Max Drawdown %"].mean()
                
                c1, c2 = st.columns(2)
                c1.metric("Average Peak Simulated Upside", f"+{round(avg_gain, 2)}%")
                c2.metric("Average Max Drawdown", f"{round(avg_dd, 2)}%")
                st.dataframe(bt_df, use_container_width=True)
            else:
                st.warning("Insufficient historical bars to compile backtest.")
