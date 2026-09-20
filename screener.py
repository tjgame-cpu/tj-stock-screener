import pandas as pd
import numpy as np
import yfinance as yf
import sqlite3
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier

# Clean database generation for extended metrics
DB_NAME = "predictions_v5.db"

# --- INBUILT DISCOVERY UNIVERSES ---
CURATED_UNIVERSES = {
    "Nifty 50 Heavyweights": [
        "RELIANCE.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS", "SBIN.NS",
        "TCS.NS", "INFY.NS", "BAJFINANCE.NS", "HINDUNILVR.NS", "LT.NS",
        "SUNPHARMA.NS", "MARUTI.NS", "M&M.NS", "HCLTECH.NS", "AXISBANK.NS",
        "ITC.NS", "NTPC.NS", "ONGC.NS", "KOTAKBANK.NS", "TITAN.NS",
        "TATASTEEL.NS", "POWERGRID.NS", "ULTRACEMCO.NS", "COALINDIA.NS", "ADANIENT.NS"
    ],
    "High-Growth Midcaps": [
        "TRENT.NS", "VBL.NS", "POLYCAB.NS", "KEI.NS", "NCC.NS",
        "DIXON.NS", "PERSISTENT.NS", "COFORGE.NS", "BSE.NS", "HAL.NS",
        "BEL.NS", "MAZDOCK.NS", "RVNL.NS", "SUZLON.NS", "IDEA.NS"
    ],
    "Top 50 Liquid ETFs": [
        "NIFTYBEES.NS", "JUNIORBEES.NS", "BANKBEES.NS", "ITBEES.NS", "GOLDBEES.NS", 
        "SILVERBEES.NS", "LIQUIDBEES.NS", "PHARMABEES.NS", "CONSUMBEES.NS", "AUTOBEES.NS",
        "MID150BEES.NS", "SETFNIF50.NS", "SETFNIFBK.NS", "SBIETFNIF.NS", "ICICINIFTY.NS",
        "ICICIBANKN.NS", "ICICITECH.NS", "ICICIPHARM.NS", "ICICINXT.NS", "HDFCNIFTY.NS",
        "HDFCBANKETF.NS", "HDFCGOLD.NS", "HDFCSENETF.NS", "UTINIFTETF.NS", "AXISNIFTY.NS",
        "KOTAKNIFTY.NS", "KOTAKBKETF.NS", "KOTAKGOLD.NS", "MOM100.NS", "MON100.NS",
        "MAFANG.NS", "MASPTOP50.NS", "MOGROW.NS", "CPSEETF.NS", "BHARAT22.NS",
        "NV20BEES.NS", "PSUBNKBEES.NS", "MAKEINDIA.NS", "ALPL30BEES.NS", "INFRABEES.NS",
        "DIVOPPBEES.NS", "ICICILIQ.NS", "LIQUIDCASE.NS", "ICICIMCAP.NS", "SETFNN50.NS",
        "AXISCBPETF.NS", "EBBETF0430.NS", "HDFCLOWVOL.NS", "ICICIALPHA.NS", "KOTAKALPHA.NS"
    ]
}


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            signal_price REAL,
            direction TEXT,
            ml_confidence REAL,
            entry_range TEXT,
            stoploss REAL,
            rvol REAL,
            target_short REAL,
            target_long REAL,
            fii_dii_status TEXT,
            status_short TEXT DEFAULT 'Tracking',
            status_long TEXT DEFAULT 'Tracking',
            days_elapsed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def update_past_predictions():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    try:
        df_pending = pd.read_sql_query("SELECT * FROM predictions WHERE status_short='Tracking' OR status_long='Tracking'", conn)
    except Exception:
        conn.close()
        return
        
    if df_pending.empty:
        conn.close()
        return

    for ticker in df_pending['ticker'].unique():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="6mo")
            if hist.empty:
                continue
                
            ticker_rows = df_pending[df_pending['ticker'] == ticker]
            for _, row in ticker_rows.iterrows():
                pred_date = datetime.strptime(row['date'], '%Y-%m-%d').date()
                post_data = hist[hist.index.date > pred_date]
                if post_data.empty:
                    continue
                
                days_passed = len(post_data)
                direction = row['direction']
                
                short_window = post_data.head(15)
                long_window = post_data.head(90)
                
                status_short = row['status_short']
                status_long = row['status_long']
                
                if status_short == 'Tracking':
                    if direction == "Bullish" and short_window['High'].max() >= row['target_short']: status_short = 'Hit'
                    elif direction == "Bearish" and short_window['Low'].min() <= row['target_short']: status_short = 'Hit'
                    elif days_passed >= 15: status_short = 'Missed'
                        
                if status_long == 'Tracking':
                    if direction == "Bullish" and long_window['High'].max() >= row['target_long']: status_long = 'Hit'
                    elif direction == "Bearish" and long_window['Low'].min() <= row['target_long']: status_long = 'Hit'
                    elif days_passed >= 90: status_long = 'Missed'
                
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE predictions SET status_short = ?, status_long = ?, days_elapsed = ? WHERE id = ?
                ''', (status_short, status_long, days_passed, row['id']))
        except Exception as e:
            print(f"Update error for {ticker}: {e}")
            
    conn.commit()
    conn.close()

class StockScreeningEngine:
    def __init__(self, tickers):
        self.tickers = tickers
        self.data_store = {}
        init_db()
        
    def fetch_data(self):
        for ticker in self.tickers:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="1y")
                if not hist.empty and len(hist) > 50:
                    self.data_store[ticker] = {"history": hist, "info": {}}
            except Exception as e:
                print(f"Skipping {ticker}: {e}")

    def apply_filters(self):
        screened_results = []
        today_str = datetime.today().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        for ticker, data in self.data_store.items():
            hist = data["history"].copy()
            close_prices = hist['Close']
            
            # 200 SMA Structural Floor
            sma_200 = close_prices.rolling(window=200).mean().iloc[-1] if len(close_prices) >= 200 else close_prices.rolling(window=50).mean().iloc[-1]
            current_price = round(close_prices.iloc[-1], 2)
            prev_close = round(close_prices.iloc[-2], 2)
            
            price_change = round(current_price - prev_close, 2)
            price_change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)
            
            # Relative Volume (RVol) institutional metrics
            hist['Vol_SMA'] = hist['Volume'].rolling(window=20).mean()
            last_vol = hist['Volume'].iloc[-1]
            avg_vol = hist['Vol_SMA'].iloc[-1] if hist['Vol_SMA'].iloc[-1] > 0 else 1.0
            rvol = round(float(last_vol / avg_vol), 2)
            
            # FII/DII Proxy Indicator
            if rvol >= 1.5 and price_change > 0:
                fii_dii_flow = "Institutional Accumulation"
            elif rvol >= 1.5 and price_change < 0:
                fii_dii_flow = "Institutional Distribution"
            else:
                fii_dii_flow = "Normal Market Rotation"
                
            # Directional Trend
            direction = "Bullish" if current_price >= sma_200 else "Bearish"
            
            # ML Signal Confidence
            hist['Returns'] = hist['Close'].pct_change()
            hist['RSI'] = self.calculate_rsi(hist['Close'], 14)
            
            if direction == "Bullish":
                hist['Target_Class'] = np.where(hist['Returns'].shift(-5) > 0.005, 1, 0)
            else:
                hist['Target_Class'] = np.where(hist['Returns'].shift(-5) < -0.005, 1, 0)
                
            features = ['Returns', 'RSI']
            df_ml = hist[features + ['Target_Class']].dropna()
            
            ml_confidence = 50.0
            if len(df_ml) > 30:
                X = df_ml[features]
                y = df_ml['Target_Class']
                clf = RandomForestClassifier(n_estimators=40, random_state=42)
                clf.fit(X[:-1], y[:-1])
                last_features = np.array([hist[features].iloc[-1]])
                ml_confidence = round(float(clf.predict_proba(last_features)[0][1]) * 100, 1)

            # Target Bands & Dynamic Stoploss
            vol = hist['Returns'].rolling(window=20).std().iloc[-1]
            if pd.isna(vol) or vol == 0: vol = 0.02
                
            if direction == "Bullish":
                target_short = round(current_price * (1 + (vol * 1.8)), 2)
                target_long = round(current_price * (1 + (vol * 4.3)), 2)
                stoploss = round(current_price * (1 - (vol * 1.2)), 2)
                entry_range = f"₹{round(current_price * 0.995, 2)} - ₹{round(current_price * 1.005, 2)}"
            else:
                target_short = round(current_price * (1 - (vol * 1.8)), 2)
                target_long = round(current_price * (1 - (vol * 4.3)), 2)
                stoploss = round(current_price * (1 + (vol * 1.2)), 2)
                entry_range = f"₹{round(current_price * 0.995, 2)} - ₹{round(current_price * 1.005, 2)}"

            pct_short = round(((target_short - current_price) / current_price) * 100, 1)
            pct_long = round(((target_long - current_price) / current_price) * 100, 1)
            
            str_pct_short = f"+{pct_short}%" if pct_short > 0 else f"{pct_short}%"
            str_pct_long = f"+{pct_long}%" if pct_long > 0 else f"{pct_long}%"

            # SQLite Log
            cursor.execute("SELECT id FROM predictions WHERE date=? AND ticker=?", (today_str, ticker))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO predictions (date, ticker, signal_price, direction, ml_confidence, entry_range, stoploss, rvol, target_short, target_long, fii_dii_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (today_str, ticker, current_price, direction, ml_confidence, entry_range, stoploss, rvol, target_short, target_long, fii_dii_flow))

            clean_symbol = ticker.replace(".NS", "").replace(".BO", "")
            tv_url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean_symbol}"

            screened_results.append({
                "Ticker": clean_symbol,
                "RawTicker": ticker,
                "Current Price": current_price,
                "Price Change": price_change,
                "Price Change Pct": price_change_pct,
                "Momentum Vector": direction,
                "ML Signal Confidence": ml_confidence,
                "Entry Range": entry_range,
                "Stoploss": stoploss,
                "RVol": rvol,
                "Swing Target 1-15d": f"₹{target_short} ({str_pct_short})",
                "Structural Target 20-90d": f"₹{target_long} ({str_pct_long})",
                "Target Short Num": target_short,
                "Target Long Num": target_long,
                "FII/DII Institutional Flow": fii_dii_flow,
                "TradingView Link": tv_url
            })
            
        conn.commit()
        conn.close()
        return pd.DataFrame(screened_results)

    def run_backtest(self):
        backtest_logs = []
        for ticker, data in self.data_store.items():
            hist = data["history"]
            if len(hist) < 150: continue
            close_prices = hist['Close']
            sma_50 = close_prices.rolling(window=50).mean()
            
            for i in range(100, len(hist) - 90, 15):
                price_at_trigger = close_prices.iloc[i]
                sma_val = sma_50.iloc[i]
                date_at_trigger = hist.index[i].strftime('%Y-%m-%d')
                
                if pd.isna(sma_val): continue
                direction = "Bullish" if price_at_trigger >= sma_val else "Bearish"
                
                forward_window = hist.iloc[i+1 : i+91]
                max_forward = forward_window['High'].max()
                min_forward = forward_window['Low'].min()
                
                max_upside = ((max_forward - price_at_trigger) / price_at_trigger) * 100
                max_drawdown = ((min_forward - price_at_trigger) / price_at_trigger) * 100
                
                backtest_logs.append({
                    "Ticker": ticker.replace(".NS", ""),
                    "Sim Date": date_at_trigger,
                    "Trigger Price": round(price_at_trigger, 2),
                    "Direction": direction,
                    "Simulated Peak Return %": round(max_upside, 2),
                    "Simulated Max Drawdown %": round(max_drawdown, 2)
                })
        return pd.DataFrame(backtest_logs)

    @staticmethod
    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))
