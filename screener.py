import pandas as pd
import numpy as np
import yfinance as yf
import sqlite3
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier

DB_NAME = "predictions_v3.db"

def init_db():
    """Initializes the V3 SQLite database schema with RVOL, R:R, and 3 Target Horizons."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            signal_price REAL,
            direction TEXT,
            buy_zone TEXT,
            stop_loss TEXT,
            rvol REAL,
            risk_reward REAL,
            ml_confidence REAL,
            target_1_15 REAL,
            target_16_45 REAL,
            target_46_90 REAL,
            fii_dii_status TEXT,
            status_1_15 TEXT DEFAULT 'Tracking',
            status_16_45 TEXT DEFAULT 'Tracking',
            status_46_90 TEXT DEFAULT 'Tracking',
            days_elapsed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def update_past_predictions():
    """Audits past entries against daily high/low bars across all 3 timeframes."""
    init_db()
    conn = sqlite3.connect(DB_NAME)
    try:
        df_pending = pd.read_sql_query(
            "SELECT * FROM predictions WHERE status_1_15='Tracking' OR status_16_45='Tracking' OR status_46_90='Tracking'", 
            conn
        )
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
                
                window_15 = post_data.head(15)
                window_45 = post_data.head(45)
                window_90 = post_data.head(90)
                
                status_1_15 = row['status_1_15']
                status_16_45 = row['status_16_45']
                status_46_90 = row['status_46_90']
                
                # Horizon 1: 1-15 Days
                if status_1_15 == 'Tracking':
                    if direction == "Bullish" and window_15['High'].max() >= row['target_1_15']: status_1_15 = 'Hit'
                    elif direction == "Bearish" and window_15['Low'].min() <= row['target_1_15']: status_1_15 = 'Hit'
                    elif days_passed >= 15: status_1_15 = 'Missed'
                
                # Horizon 2: 16-45 Days
                if status_16_45 == 'Tracking':
                    if direction == "Bullish" and window_45['High'].max() >= row['target_16_45']: status_16_45 = 'Hit'
                    elif direction == "Bearish" and window_45['Low'].min() <= row['target_16_45']: status_16_45 = 'Hit'
                    elif days_passed >= 45: status_16_45 = 'Missed'
                        
                # Horizon 3: 46-90 Days
                if status_46_90 == 'Tracking':
                    if direction == "Bullish" and window_90['High'].max() >= row['target_46_90']: status_46_90 = 'Hit'
                    elif direction == "Bearish" and window_90['Low'].min() <= row['target_46_90']: status_46_90 = 'Hit'
                    elif days_passed >= 90: status_46_90 = 'Missed'
                
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE predictions 
                    SET status_1_15 = ?, status_16_45 = ?, status_46_90 = ?, days_elapsed = ? 
                    WHERE id = ?
                ''', (status_1_15, status_16_45, status_46_90, days_passed, row['id']))
        except Exception as e:
            print(f"Tracking ledger check error for {ticker}: {e}")
            
    conn.commit()
    conn.close()

class StockScreeningEngine:
    def __init__(self, tickers):
        self.tickers = tickers
        self.data_store = {}
        init_db()
        
    def fetch_data(self):
        """Fetches 1 year of daily historical information for calculations."""
        for ticker in self.tickers:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="1y")
                if hist.empty or len(hist) < 200:
                    continue
                self.data_store[ticker] = {"history": hist, "info": t.info}
            except Exception:
                pass 

    def apply_filters(self):
        screened_results = []
        today_str = datetime.today().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        for ticker, data in self.data_store.items():
            hist = data["history"].copy()
            close_prices = hist['Close']
            current_price = close_prices.iloc[-1]
            
            # --- Technical Indicator Calculations ---
            ema_20 = close_prices.ewm(span=20, adjust=False).mean()
            ema_50 = close_prices.ewm(span=50, adjust=False).mean()
            sma_200 = close_prices.rolling(window=200).mean()
            
            e20 = ema_20.iloc[-1]
            e50 = ema_50.iloc[-1]
            s200 = sma_200.iloc[-1]
            
            if pd.isna(s200): continue
            
            # --- 1. Dual Trend Architecture ---
            if current_price >= e20 and e20 >= e50:
                direction = "Bullish"
            elif current_price < e20 and e20 < e50:
                direction = "Bearish"
            elif current_price >= e20 and e20 < e50:
                direction = "Bullish"  # Recovery Swing
            else:
                direction = "Bearish"  # Pullback Swing
                
            # --- 2. Chaikin Money Flow (CMF 20-Day) ---
            mf_multiplier = ((hist['Close'] - hist['Low']) - (hist['High'] - hist['Close'])) / (hist['High'] - hist['Low'] + 1e-9)
            mf_volume = mf_multiplier * hist['Volume']
            cmf_20 = mf_volume.rolling(20).sum() / (hist['Volume'].rolling(20).sum() + 1e-9)
            last_cmf = cmf_20.iloc[-1]
            
            if last_cmf > 0.08:
                fii_dii_flow = "Heavy Accumulation"
            elif last_cmf < -0.08:
                fii_dii_flow = "Heavy Distribution"
            else:
                fii_dii_flow = "Normal Rotation"

            # --- 3. Relative Volume (RVOL 20-Day) ---
            vol_sma20 = hist['Volume'].rolling(20).mean().iloc[-1]
            today_vol = hist['Volume'].iloc[-1]
            rvol_val = round(today_vol / (vol_sma20 + 1e-9), 2)
            rvol_str = f"{rvol_val}x" + (" 🔥" if rvol_val >= 1.3 else "")

            # --- 4. ATR Volatility Target & Stop Loss Scaling ---
            high_low = hist['High'] - hist['Low']
            high_close = np.abs(hist['High'] - hist['Close'].shift())
            low_close = np.abs(hist['Low'] - hist['Close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr_14 = tr.rolling(window=14).mean().iloc[-1]
            
            if pd.isna(atr_14) or atr_14 == 0:
                atr_14 = current_price * 0.02
                
            atr_pct = atr_14 / current_price
            
            # Calculate Buy Zone Range, Stop Loss, and 3 Timeframe Targets
            if direction == "Bullish":
                buy_min = round(current_price - (0.5 * atr_14), 2)
                buy_max = round(current_price + (0.3 * atr_14), 2)
                buy_zone_str = f"₹{buy_min:,.2f} - ₹{buy_max:,.2f}"

                sl_price = round(current_price - (1.5 * atr_14), 2)
                sl_pct = round(((sl_price - current_price) / current_price) * 100, 1)
                sl_str = f"₹{sl_price:,.2f} ({sl_pct}%)"

                target_1_15 = round(current_price * (1 + (atr_pct * 2.2)), 2)
                target_16_45 = round(current_price * (1 + (atr_pct * 3.5)), 2)
                target_46_90 = round(current_price * (1 + (atr_pct * 5.0)), 2)
                
                risk = current_price - sl_price
                reward_1_15 = target_1_15 - current_price
            else:
                buy_min = round(current_price - (0.3 * atr_14), 2)
                buy_max = round(current_price + (0.5 * atr_14), 2)
                buy_zone_str = f"₹{buy_min:,.2f} - ₹{buy_max:,.2f}"

                sl_price = round(current_price + (1.5 * atr_14), 2)
                sl_pct = round(((sl_price - current_price) / current_price) * 100, 1)
                sl_str = f"₹{sl_price:,.2f} (+{sl_pct}%)"

                target_1_15 = round(current_price * (1 - (atr_pct * 2.2)), 2)
                target_16_45 = round(current_price * (1 - (atr_pct * 3.5)), 2)
                target_46_90 = round(current_price * (1 - (atr_pct * 5.0)), 2)

                risk = sl_price - current_price
                reward_1_15 = current_price - target_1_15

            rr_ratio = round(reward_1_15 / (risk + 1e-9), 2)
            rr_str = f"{rr_ratio}x"

            pct_1_15 = round(((target_1_15 - current_price) / current_price) * 100, 1)
            pct_16_45 = round(((target_16_45 - current_price) / current_price) * 100, 1)
            pct_46_90 = round(((target_46_90 - current_price) / current_price) * 100, 1)
            
            str_1_15 = f"+{pct_1_15}%" if pct_1_15 > 0 else f"{pct_1_15}%"
            str_16_45 = f"+{pct_16_45}%" if pct_16_45 > 0 else f"{pct_16_45}%"
            str_46_90 = f"+{pct_46_90}%" if pct_46_90 > 0 else f"{pct_46_90}%"

            # --- 5. Enhanced 6-Feature Machine Learning Classifier ---
            hist['Returns'] = hist['Close'].pct_change()
            hist['RSI'] = self.calculate_rsi(hist['Close'], 14)
            hist['CMF'] = cmf_20
            hist['ATR_Pct'] = tr.rolling(14).mean() / hist['Close']
            hist['EMA_Dist'] = (hist['Close'] - ema_20) / ema_20
            
            ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
            ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            hist['MACD_Hist'] = macd - signal

            if direction == "Bullish":
                hist['Target_Class'] = np.where(hist['Returns'].shift(-5) > 0.005, 1, 0)
            else:
                hist['Target_Class'] = np.where(hist['Returns'].shift(-5) < -0.005, 1, 0)

            features = ['Returns', 'RSI', 'CMF', 'ATR_Pct', 'EMA_Dist', 'MACD_Hist']
            df_ml = hist[features + ['Target_Class']].dropna()

            ml_confidence = 50.0
            if len(df_ml) > 50:
                X = df_ml[features]
                y = df_ml['Target_Class']
                unique_classes = np.unique(y[:-1])

                if len(unique_classes) > 1:
                    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
                    clf.fit(X[:-1], y[:-1])

                    last_features = pd.DataFrame([hist[features].iloc[-1]], columns=features)
                    probs = clf.predict_proba(last_features)[0]

                    if 1 in clf.classes_:
                        idx_1 = np.where(clf.classes_ == 1)[0][0]
                        ml_confidence = round(float(probs[idx_1]) * 100, 1)
                    else:
                        ml_confidence = 0.0

            # Insert new prediction into historical tracker database
            cursor.execute("SELECT id FROM predictions WHERE date=? AND ticker=?", (today_str, ticker))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO predictions (
                        date, ticker, signal_price, direction, buy_zone, stop_loss, rvol, risk_reward, ml_confidence, 
                        target_1_15, target_16_45, target_46_90, fii_dii_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (today_str, ticker, round(current_price, 2), direction, buy_zone_str, sl_str, rvol_val, rr_ratio, ml_confidence, target_1_15, target_16_45, target_46_90, fii_dii_flow))

            clean_symbol = ticker.replace(".NS", "")
            tv_url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean_symbol}"

            screened_results.append({
                "Ticker": ticker,
                "Current Market Price": round(current_price, 2),
                "Buy Zone Range": buy_zone_str,
                "Stop Loss (% Risk)": sl_str,
                "R:R Ratio": rr_str,
                "RVOL Spike": rvol_str,
                "Momentum Vector": direction,
                "ML Signal Confidence": f"{ml_confidence}%",
                "Swing Target (1-15d)": f"{target_1_15} ({str_1_15})",
                "Medium Target (16-45d)": f"{target_16_45} ({str_16_45})",
                "Structural Target (46-90d)": f"{target_46_90} ({str_46_90})",
                "FII/DII Institutional Flow": fii_dii_flow,
                "TradingView Link": tv_url,
                "CMF_Val": last_cmf
            })

        conn.commit()
        conn.close()

        if screened_results:
            df_res = pd.DataFrame(screened_results)
            df_res = df_res.sort_values(by="CMF_Val", ascending=False).drop(columns=["CMF_Val"])
            return df_res
            
        return pd.DataFrame(screened_results)

    def run_backtest(self):
        """Precise Historical Backtest Simulator with 3 Timeframe Target Validations."""
        backtest_logs = []
        for ticker, data in self.data_store.items():
            hist = data["history"].copy()
            if len(hist) < 200: continue
            
            close_prices = hist['Close']
            ema_20 = close_prices.ewm(span=20, adjust=False).mean()
            ema_50 = close_prices.ewm(span=50, adjust=False).mean()
            
            high_low = hist['High'] - hist['Low']
            high_close = np.abs(hist['High'] - hist['Close'].shift())
            low_close = np.abs(hist['Low'] - hist['Close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr_series = tr.rolling(window=14).mean()
            
            for i in range(150, len(hist) - 90, 12):
                trigger_price = close_prices.iloc[i]
                e20_val = ema_20.iloc[i]
                e50_val = ema_50.iloc[i]
                atr_val = atr_series.iloc[i]
                
                if pd.isna(e20_val) or pd.isna(atr_val) or atr_val == 0: continue
                
                date_str = hist.index[i].strftime('%Y-%m-%d')
                direction = "Bullish" if trigger_price >= e20_val else "Bearish"
                atr_pct = atr_val / trigger_price
                
                if direction == "Bullish":
                    target_1_15 = round(trigger_price * (1 + (atr_pct * 2.2)), 2)
                    target_16_45 = round(trigger_price * (1 + (atr_pct * 3.5)), 2)
                    target_46_90 = round(trigger_price * (1 + (atr_pct * 5.0)), 2)
                else:
                    target_1_15 = round(trigger_price * (1 - (atr_pct * 2.2)), 2)
                    target_16_45 = round(trigger_price * (1 - (atr_pct * 3.5)), 2)
                    target_46_90 = round(trigger_price * (1 - (atr_pct * 5.0)), 2)
                
                window_15 = hist.iloc[i+1 : i+16]
                window_45 = hist.iloc[i+1 : i+46]
                window_90 = hist.iloc[i+1 : i+91]
                
                if window_15.empty or window_45.empty or window_90.empty: continue
                
                if direction == "Bullish":
                    hit_1_15 = window_15['High'].max() >= target_1_15
                    hit_16_45 = window_45['High'].max() >= target_16_45
                    hit_46_90 = window_90['High'].max() >= target_46_90
                else:
                    hit_1_15 = window_15['Low'].min() <= target_1_15
                    hit_16_45 = window_45['Low'].min() <= target_16_45
                    hit_46_90 = window_90['Low'].min() <= target_46_90
                
                backtest_logs.append({
                    "Ticker": ticker.replace(".NS", ""),
                    "Sim Date": date_str,
                    "Trigger Price": round(trigger_price, 2),
                    "Vector": direction,
                    "Target (1-15d)": target_1_15,
                    "Status (1-15d)": "Hit" if hit_1_15 else "Missed",
                    "Target (16-45d)": target_16_45,
                    "Status (16-45d)": "Hit" if hit_16_45 else "Missed",
                    "Target (46-90d)": target_46_90,
                    "Status (46-90d)": "Hit" if hit_46_90 else "Missed"
                })
        return pd.DataFrame(backtest_logs)

    @staticmethod
    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))
