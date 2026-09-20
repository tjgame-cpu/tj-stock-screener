import streamlit as st
import sqlite3
import pandas as pd
from screener import StockScreeningEngine, update_past_predictions, init_db, DB_NAME, CURATED_UNIVERSES
import plotly.graph_objects as go
import yfinance as yf

init_db()

st.set_page_config(page_title="Alpha Horizon Terminal", layout="wide")

# --- FORCED PURE LIGHT THEME CSS INJECTION ---
st.markdown("""
<style>
    /* 1. Global Viewport & Container Reset */
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stAppViewBlockContainer"] {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
    }
    
    /* 2. Text & Typography Overrides */
    h1, h2, h3, h4, h5, h6, p, span, div, label, li {
        color: #0F172A !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 3. Input Boxes & Text Areas (Fixes Black Box Glitch) */
    textarea, input, [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="base-input"] {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        -webkit-text-fill-color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
    }
    textarea:focus, input:focus {
        border-color: #2563EB !important;
        box-shadow: 0 0 0 1px #2563EB !important;
    }

    /* 4. Buttons (Fixes Black Button Glitch) */
    .stButton > button {
        background-color: #F8FAFC !important;
        color: #0F172A !important;
        -webkit-text-fill-color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 8px 16px !important;
    }
    .stButton > button:hover {
        background-color: #E2E8F0 !important;
        border-color: #94A3B8 !important;
    }
    
    /* Primary Red Action Button */
    .stButton > button[kind="primary"] {
        background-color: #EF4444 !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        border: none !important;
        font-weight: 700 !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #DC2626 !important;
    }

    /* 5. Zerodha Kite Watchlist Cards */
    .kite-row {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        transition: transform 0.1s ease, box-shadow 0.1s ease;
    }
    .kite-row:hover {
        border-color: #94A3B8;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.08);
    }
    
    .bull-green {
        color: #00A25B !important;
        font-weight: 700;
    }
    .bear-red {
        color: #DF514C !important;
        font-weight: 700;
    }
    
    .ticker-sub {
        font-size: 0.75rem;
        color: #64748B !important;
        font-weight: 600;
        margin-left: 4px;
    }
    
    .pill-bull {
        background-color: #E6F7EF;
        color: #00A25B !important;
        font-size: 0.75rem;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
    }
    .pill-bear {
        background-color: #FDF0EE;
        color: #DF514C !important;
        font-size: 0.75rem;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
    }

    /* Expander styling */
    [data-testid="stExpander"] {
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# Master list aggregation
ALL_INBUILT_TICKERS = list(dict.fromkeys(
    CURATED_UNIVERSES["Nifty 50 Heavyweights"] +
    CURATED_UNIVERSES["High-Growth Midcaps"] +
    CURATED_UNIVERSES["Top 50 Liquid ETFs"]
))
ALL_CLEAN_NAMES = ", ".join([t.replace(".NS", "") for t in ALL_INBUILT_TICKERS])

if "active_watchlist" not in st.session_state:
    st.session_state.active_watchlist = ALL_CLEAN_NAMES

st.title("📊 Alpha Horizon Watchlist Terminal")

# Top Indices Strip
col_idx1, col_idx2, col_idx3, col_idx4 = st.columns(4)
col_idx1.metric("NIFTY 50", "23,346.40", "+75.80 (+0.32%)")
col_idx2.metric("BANK NIFTY", "56,358.70", "+302.95 (+0.54%)")
col_idx3.metric("INDIA VIX", "13.45", "-0.40 (-2.88%)", delta_color="inverse")
col_idx4.metric("SYSTEM STATE", "ONLINE", "Ready")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📱 Kite Watchlist & Scanner", "📜 Performance Ledger", "🧪 Backtest Sandbox"])

# --- SIDEBAR CONFIGURATION ---
st.sidebar.subheader("🔍 Inbuilt Market Finder")
st.sidebar.caption("Tap below to load all 50+ Heavyweights, Midcaps, and Liquid ETFs into your queue:")

if st.sidebar.button("⚡ Run Inbuilt Market Finder (Load All)"):
    st.session_state.active_watchlist = ALL_CLEAN_NAMES
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Active Watchlist Queue")

watchlist_input = st.sidebar.text_area(
    "Tickers in Queue (Comma separated):", 
    value=st.session_state.active_watchlist,
    height=160
)
st.session_state.active_watchlist = watchlist_input

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
            st.warning("No tickers found in the active queue. Tap 'Run Inbuilt Market Finder' to load assets.")
        else:
            with st.status(f"⚡ Running Screening Engine on {len(parsed_tickers)} queued assets...", expanded=True) as status:
                st.write("🔄 Auditing past tracked positions...")
                update_past_predictions()
                st.write("📈 Pulling technical candle blocks & volumes...")
                engine = StockScreeningEngine(parsed_tickers)
                engine.fetch_data()
                st.write("🤖 Deriving RSI, SMA filters, FII/DII flow & ML confidence...")
                results_df = engine.apply_filters()
                status.update(label="✅ Quantitative Analysis Complete!", state="complete", expanded=False)
                
            if not results_df.empty:
                # Segment Equities vs ETFs
                is_etf = results_df["RawTicker"].isin(CURATED_UNIVERSES["Top 50 Liquid ETFs"]) | results_df["Ticker"].str.contains("BEES|ETF|MON100|MAFANG", case=False, regex=True)
                stocks_df = results_df[~is_etf].copy()
                etfs_df = results_df[is_etf].copy()
                
                # Render function for Kite cards
                def render_watchlist_cards(df, title_label):
                    st.markdown(f"### {title_label} ({len(df)})")
                    if df.empty:
                        st.info("No assets qualified under structural thresholds today.")
                        return
                    for _, row in df.iterrows():
                        is_bull = row["Momentum Vector"] == "Bullish"
                        color_cls = "bull-green" if is_bull else "bear-red"
                        pill_cls = "pill-bull" if is_bull else "pill-bear"
                        chg_sign = "+" if row["Price Change"] >= 0 else ""
                        
                        st.markdown(f"""
                        <div class="kite-row">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="font-size: 1.15rem; font-weight: 700; color: #0F172A;">{row['Ticker']}</span>
                                    <span class="ticker-sub">NSE</span>
                                    <span class="{pill_cls}" style="margin-left: 8px;">{row['Momentum Vector'].upper()}</span>
                                    <span style="font-size: 0.8rem; background: #F1F5F9; color: #334155; padding: 2px 6px; border-radius: 4px; margin-left: 4px; font-weight: 600;">RVol: {row['RVol']}x</span>
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
                        
                        with st.expander(f"📊 Deep Analysis & Charts for {row['Ticker']}"):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("ML Signal Confidence", f"{row['ML Signal Confidence']}%")
                            c2.metric("Institutional Volume (FII/DII)", row["FII/DII Institutional Flow"])
                            c3.metric("Relative Volume Footprint", f"{row['RVol']}x Average")
                            
                            st.markdown(f"👉 **[Open {row['Ticker']} Live Chart on TradingView ↗]({row['TradingView Link']})**")
                            
                            try:
                                df_c = yf.Ticker(row["RawTicker"]).history(period="3mo")
                                fig = go.Figure(data=[go.Candlestick(
                                    x=df_c.index, open=df_c['Open'], high=df_c['High'],
                                    low=df_c['Low'], close=df_c['Close']
                                )])
                                fig.update_layout(
                                    height=260,
                                    margin=dict(l=10, r=10, t=20, b=10),
                                    xaxis_rangeslider_visible=False,
                                    paper_bgcolor='#FFFFFF',
                                    plot_bgcolor='#FFFFFF'
                                )
                                st.plotly_chart(fig, use_container_width=True)
                            except Exception:
                                st.caption("Chart preview unavailable.")

                render_watchlist_cards(stocks_df, "📈 Verified Equity Stock Setups")
                st.markdown("---")
                render_watchlist_cards(etfs_df, "📊 Verified Sector & Index ETF Setups")
            else:
                st.info("No matching trend setups found for the selected tickers.")
    else:
        st.info("👈 Tap **'⚡ Run Inbuilt Market Finder'** in the sidebar, then tap **'🚀 Run Quantitative Scan'** to analyze all stocks and ETFs.")

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
            engine = StockScreeningEngine(parsed_tickers[:15] if parsed_tickers else CURATED_UNIVERSES["Nifty 50 Heavyweights"][:10])
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
