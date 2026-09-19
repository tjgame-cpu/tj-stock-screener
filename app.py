import os
import sys
import subprocess
import streamlit as st
import sqlite3
import pandas as pd
import smtplib
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import yfinance as yf
from screener import StockScreeningEngine, update_past_predictions, init_db, DB_NAME

# --- EMAIL CREDENTIALS ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "jogeshisere@gmail.com"
SENDER_PASSWORD = "qevibvfvdumbzxdw"
RECEIVER_EMAIL = "jogeshthakkar2141@gmail.com"

init_db()

# --- STREAMLIT PAGE CONFIG & SOFT SLATE THEME STYLING ---
st.set_page_config(layout="wide", page_title="TJ's Stock Screener", page_icon="⚡")

st.markdown("""
<style>
    /* Soft Charcoal & Slate Canvas (Eye-Friendly Non-Glare Theme) */
    .stApp {
        background-color: #1a1f2c;
        color: #e2e8f0;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    }
    
    /* Sidebar Drawer Styling (Muted Dark Slate) */
    section[data-testid="stSidebar"] {
        background-color: #141824 !important;
        border-right: 1px solid #2d3548;
    }
    
    /* Control Panel & Glassmorphism Cards */
    .terminal-card {
        background: #222838;
        border: 1px solid #2d3548;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    .metric-card {
        background: linear-gradient(135deg, #252e40 0%, #1e2536 100%);
        border: 1px solid #2f384d;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    
    .metric-title {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .metric-value {
        color: #f8fafc;
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 4px;
    }

    /* Buttons (Gentle Indigo Accent) */
    div.stButton > button {
        background-color: #3b82f6 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 10px 24px !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px !important;
        transition: all 0.2s ease-in-out !important;
    }
    
    div.stButton > button:hover {
        background-color: #2563eb !important;
        box-shadow: 0 0 10px rgba(59, 130, 246, 0.4) !important;
        transform: translateY(-1px);
    }

    /* Sub-tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #141824;
        padding: 6px;
        border-radius: 10px;
        border: 1px solid #2d3548;
    }

    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 6px;
        color: #94a3b8;
        font-weight: 600;
        padding: 0 20px;
    }

    .stTabs [aria-selected="true"] {
        background-color: #252e40 !important;
        color: #38bdf8 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "stocks_df" not in st.session_state:
    st.session_state.stocks_df = None
if "etfs_df" not in st.session_state:
    st.session_state.etfs_df = None

def send_excel_email(stocks_dataframe, etfs_dataframe, subject_title="🚀 TJ's Momentum Alert Matrix V3", custom_body=None):
    if SENDER_EMAIL == "your_actual_email@gmail.com" or SENDER_PASSWORD == "abcd efgh ijkl mnop":
        st.sidebar.warning("⚠️ Email skipped. Configure credentials inside app.py.")
        return False
        
    try:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            if not stocks_dataframe.empty:
                stocks_dataframe.to_excel(writer, sheet_name='Equity Stocks', index=False)
            if not etfs_dataframe.empty:
                etfs_dataframe.to_excel(writer, sheet_name='Basket ETFs', index=False)
                
        excel_data = excel_buffer.getvalue()
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"{subject_title} - {pd.Timestamp.now().strftime('%d-%b-%Y')}"
        
        body = custom_body if custom_body else "Attached is your V3 live screening report featuring Buy Zone Range, Stop Loss, RVOL, R:R Ratio, and 3 Timeframe Targets (1-15d, 16-45d, 46-90d)."
        msg.attach(MIMEText(body, 'plain'))
        
        attachment = MIMEBase('application', 'octet-stream')
        attachment.set_payload(excel_data)
        encoders.encode_base64(attachment)
        attachment.add_header('Content-Disposition', f'attachment; filename=Alpha_Report_V3_{pd.Timestamp.now().strftime("%Y%m%d")}.xlsx')
        msg.attach(attachment)
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.sidebar.error(f"Failed to dispatch email: {e}")
        return False

# --- SIDEBAR NAVIGATION ---
st.sidebar.markdown("### ⚡ **TJ's Stock Screener V3**")
st.sidebar.caption("Institutional Trading Terminal")
st.sidebar.markdown("---")

nav_choice = st.sidebar.radio(
    "Navigation Console",
    ["🎯 Live Strategy Scanner", "📜 Performance Ledger Log", "🧪 Strategy Backtest Sandbox"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.markdown("#### ⚙️ System Status")
st.sidebar.markdown("🟢 Database: **`predictions_v3.db`**")
st.sidebar.markdown("🟢 Live Quotes: **Yahoo Finance API**")

# --- HARD-KILL PROCESS RECOVERY BUTTON ---
st.sidebar.markdown("---")
if st.sidebar.button("🔴 Stop & Exit Screener", use_container_width=True):
    st.sidebar.error("Terminating backend server process...")
    try:
        pid = os.getpid()
        subprocess.Popen(f"taskkill /F /PID {pid} /T", shell=True)
    except Exception:
        os._exit(0)

# ==========================================
# 1. LIVE STRATEGY SCANNER VIEW
# ==========================================
if nav_choice == "🎯 Live Strategy Scanner":
    st.title("📊 TJ's Stock Screener Console")
    st.caption("Real-Time Quantitative Momentum & Institutional Money Flow Matrix")
    
    # --- CENTER-PAGE CONTROL DECK ---
    with st.container():
        st.markdown('<div class="terminal-card">', unsafe_allow_html=True)
        st.subheader("🎛️ Scanner Parameter & Search Control Deck")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            watchlist_input = st.text_area(
                "Watchlist Tickers (Comma Separated Handles)",
                "KEI, NCC, TRENT, TATASTEEL, RECLTD, ASTRAL, COFORGE, DIXON, HAL, HINDPETRO",
                height=90,
                help="Add custom stock symbols without suffix. '.NS' will be attached automatically."
            )
            
        with col2:
            st.markdown("##### Baseline Universes")
            enable_auto_index = st.checkbox("Include Core Nifty Stocks Baseline", value=True)
            enable_etf_baseline = st.checkbox("Include Liquid ETFs Baseline", value=True)
            run_scan = st.button("🚀 EXECUTE SYSTEM SCAN", use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True)

    # Prepare Ticker List
    manual_tickers = []
    if watchlist_input:
        raw_tokens = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]
        for token in raw_tokens:
            if not (token.endswith(".NS") or token.endswith(".BO")):
                manual_tickers.append(f"{token}.NS")
            else:
                manual_tickers.append(token)

    AUTO_STOCK_STOCKS = [
        "RELIANCE.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS", "SBIN.NS",
        "TCS.NS", "INFY.NS", "BAJFINANCE.NS", "HINDUNILVR.NS", "LT.NS",
        "SUNPHARMA.NS", "MARUTI.NS", "M&M.NS", "HCLTECH.NS", "AXISBANK.NS",
        "ITC.NS", "NTPC.NS", "ONGC.NS", "KOTAKBANK.NS", "TITAN.NS"
    ]

    AUTO_ETF_STOCKS = [
        "NIFTYBEES.NS", "BANKBEES.NS", "ITBEES.NS", "GOLDBEES.NS", "SILVERBEES.NS", 
        "PHARMABEES.NS", "CONSUMBEES.NS", "AUTOBEES.NS", "MID150BEES.NS", "JUNIORBEES.NS",
        "CPSEETF.NS", "MON100.NS", "MAFANG.NS", "HDFCNIFTY.NS", "SETFNIF50.NS", 
        "SETFNIFBK.NS", "ICICILIQUID.NS", "LIQUIDBEES.NS", "AXISNIFTY.NS", "KOTAKNIFTY.NS"
    ]

    tickers_to_scan = manual_tickers
    if enable_auto_index:
        tickers_to_scan = list(set(tickers_to_scan + AUTO_STOCK_STOCKS))
    if enable_etf_baseline:
        tickers_to_scan = list(set(tickers_to_scan + AUTO_ETF_STOCKS))
    tickers_to_scan.sort()

    # Trigger Scan Processing
    if run_scan:
        with st.status("🛠️ Executing Quantitative Array Calculations...", expanded=True) as status:
            st.write("🔄 Synchronizing historical database records...")
            update_past_predictions()
            
            st.write("📈 Computing Dual EMA, CMF Money Flow, RVOL Spikes & 3 Target Horizons...")
            engine = StockScreeningEngine(tickers_to_scan)
            engine.fetch_data()
            
            st.write("🤖 Running 6-Feature Random Forest ML Model...")
            results_df = engine.apply_filters()
            status.update(label="✅ Scanner Analysis Complete!", state="complete", expanded=False)
            
        if not results_df.empty:
            is_etf = results_df["Ticker"].isin(AUTO_ETF_STOCKS) | results_df["Ticker"].str.contains("BEES|ETF|MON100|MAFANG", case=False, regex=True)
            stocks_df = results_df[~is_etf].copy()
            etfs_df = results_df[is_etf].copy()
            
            stocks_df["Ticker"] = stocks_df["Ticker"].str.replace(".NS", "")
            etfs_df["Ticker"] = etfs_df["Ticker"].str.replace(".NS", "")
            
            st.session_state.stocks_df = stocks_df
            st.session_state.etfs_df = etfs_df
            
            with st.spinner("Dispatching V3 report email..."):
                send_excel_email(stocks_df, etfs_df)
        else:
            st.session_state.stocks_df = None
            st.session_state.etfs_df = None

    # --- DISPLAY OUTPUT RESULTS ---
    if st.session_state.stocks_df is not None or st.session_state.etfs_df is not None:
        
        # Calculate Summary Metrics
        combined_df = pd.concat([st.session_state.stocks_df, st.session_state.etfs_df], ignore_index=True) if st.session_state.stocks_df is not None else st.session_state.etfs_df
        total_scanned = len(combined_df)
        bullish_count = (combined_df["Momentum Vector"] == "Bullish").sum()
        bearish_count = (combined_df["Momentum Vector"] == "Bearish").sum()
        heavy_accum = (combined_df["FII/DII Institutional Flow"] == "Heavy Accumulation").sum()

        # Summary Metric Cards
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f'<div class="metric-card"><div class="metric-title">Total Scanned</div><div class="metric-value">{total_scanned}</div></div>', unsafe_allow_html=True)
        m2.markdown(f'<div class="metric-card"><div class="metric-title">Bullish Setups</div><div class="metric-value" style="color:#10b981;">{bullish_count}</div></div>', unsafe_allow_html=True)
        m3.markdown(f'<div class="metric-card"><div class="metric-title">Bearish Shorts</div><div class="metric-value" style="color:#f43f5e;">{bearish_count}</div></div>', unsafe_allow_html=True)
        m4.markdown(f'<div class="metric-card"><div class="metric-title">Heavy Accumulation</div><div class="metric-value" style="color:#38bdf8;">{heavy_accum}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.info("💡 **9:15 AM Execution Rule:** Enter trades when price opens inside the **Buy Zone Range**. Do not enter if price gaps past the range limit.")

        def highlight_signals(val):
            if val == 'Bullish': return 'background-color: rgba(16, 185, 129, 0.18); color: #10b981; font-weight: bold;'
            if val == 'Bearish': return 'background-color: rgba(244, 63, 94, 0.18); color: #f43f5e; font-weight: bold;'
            return ''

        # MAIN OUTPUT SUB-TABS (STOCKS VS ETFS)
        tab_stocks, tab_etfs = st.tabs(["📈 Verified Equity Stocks", "📊 Verified Sector & Index ETFs"])

        with tab_stocks:
            if st.session_state.stocks_df is not None and not st.session_state.stocks_df.empty:
                st.data_editor(
                    st.session_state.stocks_df.style.map(highlight_signals, subset=["Momentum Vector"]),
                    column_config={
                        "TradingView Link": st.column_config.LinkColumn("TradingView Chart link", display_text="Launch Chart ↗"),
                        "Current Market Price": st.column_config.NumberColumn(format="₹%.2f")
                    },
                    disabled=True,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No Equity Stock Setups found.")

        with tab_etfs:
            if st.session_state.etfs_df is not None and not st.session_state.etfs_df.empty:
                st.data_editor(
                    st.session_state.etfs_df.style.map(highlight_signals, subset=["Momentum Vector"]),
                    column_config={
                        "TradingView Link": st.column_config.LinkColumn("TradingView Chart link", display_text="Launch Chart ↗"),
                        "Current Market Price": st.column_config.NumberColumn(format="₹%.2f")
                    },
                    disabled=True,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No Basket ETF Setups found.")

# ==========================================
# 2. PERFORMANCE LEDGER LOG VIEW
# ==========================================
elif nav_choice == "📜 Performance Ledger Log":
    st.title("📜 Performance Audit Ledger (3 Target Horizons)")
    st.caption("Historical Prediction Outcome Tracker & Target Hit Verification Engine")
    
    if st.button("🔄 Synchronize Tracker Outcomes", use_container_width=False):
        update_past_predictions()
        st.rerun()

    try:
        conn = sqlite3.connect(DB_NAME)
        ledger_df = pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC", conn)
        conn.close()
        
        if not ledger_df.empty:
            with st.spinner("Streaming live price quotes..."):
                live_quotes = {}
                for tk in ledger_df["ticker"].unique():
                    try:
                        ticker_clean = tk if tk.endswith(".NS") else f"{tk}.NS"
                        h = yf.Ticker(ticker_clean).history(period="1d")
                        live_quotes[tk] = round(h['Close'].iloc[-1], 2) if not h.empty else "N/A"
                    except:
                        live_quotes[tk] = "N/A"
            
            ledger_df["current_mp"] = ledger_df["ticker"].map(live_quotes)
            ledger_df["ticker"] = ledger_df["ticker"].str.replace(".NS", "")
            
            ledger_df = ledger_df[[
                "id", "date", "ticker", "signal_price", "current_mp", "buy_zone", "stop_loss", "rvol", "risk_reward", "direction", "ml_confidence",
                "target_1_15", "target_16_45", "target_46_90", "fii_dii_status", 
                "status_1_15", "status_16_45", "status_46_90", "days_elapsed"
            ]]
            
            ledger_df.columns = [
                "ID", "Scan Date", "Ticker", "Entry Price", "Current Price", "Buy Zone Range", "Stop Loss", "RVOL", "R:R Ratio", "Vector", "ML Confidence",
                "Target (1-15d)", "Target (16-45d)", "Target (46-90d)", "FII/DII Status",
                "Status (1-15d)", "Status (16-45d)", "Status (46-90d)", "Days Active"
            ]
            
            is_active = (ledger_df["Status (1-15d)"] == "Tracking") | (ledger_df["Status (16-45d)"] == "Tracking") | (ledger_df["Status (46-90d)"] == "Tracking")
            active_tracks = ledger_df[is_active].copy()
            closed_tracks = ledger_df[~is_active].copy()
            
            def highlight_status(val):
                if val == 'Hit': return 'background-color: rgba(16, 185, 129, 0.22); color: #10b981; font-weight: bold;'
                if val == 'Missed': return 'background-color: rgba(244, 63, 94, 0.22); color: #f43f5e; font-weight: bold;'
                return 'background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; font-weight: bold;'

            tab_act, tab_closed = st.tabs(["⏳ Active Tracks Monitored", "✅ Closed Historical Tracks"])
            
            with tab_act:
                if not active_tracks.empty:
                    st.dataframe(active_tracks.style.map(highlight_status, subset=["Status (1-15d)", "Status (16-45d)", "Status (46-90d)"]), use_container_width=True, hide_index=True)
                else:
                    st.info("No active tracks currently monitored.")

            with tab_closed:
                if not closed_tracks.empty:
                    st.dataframe(closed_tracks.style.map(highlight_status, subset=["Status (1-15d)", "Status (16-45d)", "Status (46-90d)"]), use_container_width=True, hide_index=True)
                else:
                    st.info("No predictions closed yet in database.")
        else:
            st.info("The performance database tracker is currently empty.")
    except Exception as e:
        st.error(f"Ledger hook failure: {e}")

# ==========================================
# 3. STRATEGY BACKTEST SANDBOX VIEW
# ==========================================
elif nav_choice == "🧪 Strategy Backtest Sandbox":
    st.title("🧪 Strategy Backtest Sandbox & Data Exporter")
    st.caption("Historical Backtest Simulator across 3 Target Timeframes")
    
    col_a, col_b = st.columns([1, 1])
    
    with col_a:
        run_backtest_btn = st.button("🔬 Execute Backtest Simulation", use_container_width=True)
    with col_b:
        try:
            conn = sqlite3.connect(DB_NAME)
            db_export_df = pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC", conn)
            conn.close()
            
            if not db_export_df.empty:
                csv_buffer = db_export_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Export Ledger Data (CSV for AI Audit)",
                    data=csv_buffer,
                    file_name=f"Predictions_V3_Database_Export_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                st.info("No historical database records to export.")
        except Exception as e:
            st.error(f"Export engine error: {e}")

    st.markdown("---")

    if run_backtest_btn:
        with st.spinner("Auditing historical price bars against ATR targets across 3 horizons..."):
            engine = StockScreeningEngine(tickers_to_scan)
            engine.fetch_data()
            bt_df = engine.run_backtest()
            
            if not bt_df.empty:
                total_sims = len(bt_df)
                hits_1_15 = (bt_df["Status (1-15d)"] == "Hit").sum()
                hits_16_45 = (bt_df["Status (16-45d)"] == "Hit").sum()
                hits_46_90 = (bt_df["Status (46-90d)"] == "Hit").sum()
                overall_wins = ((bt_df["Status (1-15d)"] == "Hit") | (bt_df["Status (16-45d)"] == "Hit") | (bt_df["Status (46-90d)"] == "Hit")).sum()
                
                win_rate = round((overall_wins / total_sims) * 100, 1)
                rate_1_15 = round((hits_1_15 / total_sims) * 100, 1)
                rate_16_45 = round((hits_16_45 / total_sims) * 100, 1)
                rate_46_90 = round((hits_46_90 / total_sims) * 100, 1)
                
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Simulated Triggers", total_sims)
                c2.metric("Overall Win Rate", f"{win_rate}%")
                c3.metric("1-15d Hit Rate", f"{rate_1_15}%")
                c4.metric("16-45d Hit Rate", f"{rate_16_45}%")
                c5.metric("46-90d Hit Rate", f"{rate_46_90}%")
                
                def highlight_bt(val):
                    if val == 'Hit': return 'background-color: rgba(16, 185, 129, 0.22); color: #10b981; font-weight: bold;'
                    if val == 'Missed': return 'background-color: rgba(244, 63, 94, 0.22); color: #f43f5e; font-weight: bold;'
                    return ''

                st.dataframe(bt_df.style.map(highlight_bt, subset=["Status (1-15d)", "Status (16-45d)", "Status (46-90d)"]), use_container_width=True, hide_index=True)
            else:
                st.warning("Insufficient historical chart bars found to run simulation.")
