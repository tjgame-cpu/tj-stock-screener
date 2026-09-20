import sqlite3
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import yfinance as yf

DB_NAME = "predictions_v5.db"

# ==============================================================================
# CURATED ASSET UNIVERSES
# ==============================================================================
CURATED_UNIVERSES = {
    "Nifty 50 Heavyweights": [
        "RELIANCE.NS",
        "HDFCBANK.NS",
        "BHARTIARTL.NS",
        "ICICIBANK.NS",
        "SBIN.NS",
        "TCS.NS",
        "INFY.NS",
        "BAJFINANCE.NS",
        "HINDUNILVR.NS",
        "LT.NS",
        "SUNPHARMA.NS",
        "MARUTI.NS",
        "M&M.NS",
        "HCLTECH.NS",
        "AXISBANK.NS",
        "ITC.NS",
        "NTPC.NS",
        "ONGC.NS",
        "KOTAKBANK.NS",
        "TITAN.NS",
        "TATASTEEL.NS",
        "POWERGRID.NS",
        "ULTRACEMCO.NS",
        "COALINDIA.NS",
        "ADANIENT.NS",
    ],
    "High-Growth Midcaps": [
        "TRENT.NS",
        "VBL.NS",
        "POLYCAB.NS",
        "KEI.NS",
        "NCC.NS",
        "DIXON.NS",
        "PERSISTENT.NS",
        "COFORGE.NS",
        "BSE.NS",
        "HAL.NS",
        "BEL.NS",
        "MAZDOCK.NS",
        "RVNL.NS",
        "SUZLON.NS",
        "HINDPETRO.NS",
        "REC.NS",
    ],
    "Top 50 Liquid ETFs": [
        "NIFTYBEES.NS",
        "JUNIORBEES.NS",
        "BANKBEES.NS",
        "ITBEES.NS",
        "GOLDBEES.NS",
        "SILVERBEES.NS",
        "LIQUIDBEES.NS",
        "PHARMABEES.NS",
        "CONSUMBEES.NS",
        "AUTOBEES.NS",
        "MID150BEES.NS",
        "SETFNIF50.NS",
        "SETFNIFBK.NS",
        "SBIETFNIF.NS",
        "ICICINIFTY.NS",
        "ICICIBANKN.NS",
        "ICICITECH.NS",
        "ICICIPHARM.NS",
        "ICICINXT.NS",
        "HDFCNIFTY.NS",
        "HDFCBANKETF.NS",
        "HDFCSENETF.NS",
        "UTINIFTETF.NS",
        "AXISNIFTY.NS",
        "KOTAKNIFTY.NS",
        "KOTAKBKETF.NS",
        "KOTAKGOLD.NS",
        "MON100.NS",
        "MAFANG.NS",
        "CPSEETF.NS",
    ],
}


def init_db():
  """Initializes SQLite database schema to track setups and performance logs."""
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            signal_price REAL,
            direction TEXT,
            ml_confidence REAL,
            target_short REAL,
            target_long REAL,
            fii_dii_status TEXT,
            status_short TEXT DEFAULT 'Tracking',
            status_long TEXT DEFAULT 'Tracking',
            days_elapsed INTEGER DEFAULT 0
        )
    """)
  conn.commit()
  conn.close()


def update_past_predictions():
  """Audits pending tracking trades against recent daily high/low candles."""
  init_db()
  conn = sqlite3.connect(DB_NAME)
  try:
    df_pending = pd.read_sql_query(
        "SELECT * FROM predictions WHERE status_short='Tracking' OR"
        " status_long='Tracking'",
        conn,
    )
  except Exception:
    conn.close()
    return

  if df_pending.empty:
    conn.close()
    return

  for ticker in df_pending["ticker"].unique():
    try:
      t = yf.Ticker(ticker)
      hist = t.history(period="6mo")
      if hist.empty:
        continue

      ticker_rows = df_pending[df_pending["ticker"] == ticker]
      for _, row in ticker_rows.iterrows():
        pred_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        post_data = hist[hist.index.date > pred_date]
        if post_data.empty:
          continue

        days_passed = len(post_data)
        direction = row["direction"]
        short_window = post_data.head(15)
        long_window = post_data.head(90)

        status_short = row["status_short"]
        status_long = row["status_long"]

        if status_short == "Tracking":
          if (
              direction == "Bullish"
              and short_window["High"].max() >= row["target_short"]
          ):
            status_short = "Hit"
          elif (
              direction == "Bearish"
              and short_window["Low"].min() <= row["target_short"]
          ):
            status_short = "Hit"
          elif days_passed >= 15:
            status_short = "Missed"

        if status_long == "Tracking":
          if (
              direction == "Bullish"
              and long_window["High"].max() >= row["target_long"]
          ):
            status_long = "Hit"
          elif (
              direction == "Bearish"
              and long_window["Low"].min() <= row["target_long"]
          ):
            status_long = "Hit"
          elif days_passed >= 90:
            status_long = "Missed"

        cursor = conn.cursor()
        cursor.execute(
            """
                    UPDATE predictions SET status_short = ?, status_long = ?, days_elapsed = ? WHERE id = ?
                """,
            (status_short, status_long, days_passed, row["id"]),
        )
    except Exception:
      pass

  conn.commit()
  conn.close()


class StockScreeningEngine:

  def __init__(self, tickers):
    self.tickers = tickers
    self.data_store = {}
    init_db()

  def fetch_data(self):
    """Downloads 1y historical candles cleanly without spamming warnings."""
    for ticker in self.tickers:
      try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty or len(hist) < 60:
          continue
        self.data_store[ticker] = {"history": hist}
      except Exception:
        pass

  def apply_filters(self):
    screened_results = []
    today_str = datetime.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for ticker, data in self.data_store.items():
      hist = data["history"].copy()

      close_prices = hist["Close"]
      current_price = round(float(close_prices.iloc[-1]), 2)
      prev_close = round(float(close_prices.iloc[-2]), 2)
      price_chg = round(current_price - prev_close, 2)
      price_chg_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

      # 200 SMA / 50 SMA baseline
      if len(close_prices) >= 200:
        sma_val = close_prices.rolling(window=200).mean().iloc[-1]
      else:
        sma_val = close_prices.rolling(window=50).mean().iloc[-1]

      if pd.isna(sma_val):
        continue

      # 1. Institutional Volume Flow Proxy & RVol
      hist["Vol_SMA"] = hist["Volume"].rolling(window=20).mean()
      last_vol = hist["Volume"].iloc[-1]
      avg_vol = hist["Vol_SMA"].iloc[-1] if hist["Vol_SMA"].iloc[-1] > 0 else 1.0
      rvol = round(float(last_vol / avg_vol), 2)

      if last_vol > avg_vol * 1.4 and current_price >= prev_close:
        fii_dii_flow = "Heavy Accumulation"
      elif last_vol > avg_vol * 1.4 and current_price < prev_close:
        fii_dii_flow = "Heavy Distribution"
      else:
        fii_dii_flow = "Normal Rotation"

      # 2. Trend Classification
      direction = "Bullish" if current_price >= sma_val else "Bearish"

      # 3. Machine Learning Signal Confidence (Safe & CPU Throttling Protected)
      hist["Returns"] = hist["Close"].pct_change()
      hist["RSI"] = self.calculate_rsi(hist["Close"], 14)

      if direction == "Bullish":
        hist["Target_Class"] = np.where(hist["Returns"].shift(-5) > 0.005, 1, 0)
      else:
        hist["Target_Class"] = np.where(
            hist["Returns"].shift(-5) < -0.005, 1, 0
        )

      features = ["Returns", "RSI"]
      df_ml = hist[features + ["Target_Class"]].dropna()

      ml_confidence = 50.0
      try:
        if len(df_ml) > 30:
          X = df_ml[features]
          y = df_ml["Target_Class"]
          classes_present = np.unique(y[:-1])

          if len(classes_present) > 1:
            # Lean classifier (n_jobs=1, n_estimators=20) to stay within free Cloud limits
            clf = RandomForestClassifier(
                n_estimators=20, max_depth=4, random_state=42, n_jobs=1
            )
            clf.fit(X[:-1], y[:-1])

            last_features = pd.DataFrame(
                [hist[features].iloc[-1]], columns=features
            )
            probs = clf.predict_proba(last_features)[0]

            # SAFE CLASS CHECK: Prevents IndexError if class 1 is absent
            if 1 in clf.classes_:
              idx_1 = list(clf.classes_).index(1)
              ml_confidence = round(float(probs[idx_1]) * 100, 1)
            else:
              ml_confidence = 0.0
          elif len(classes_present) == 1:
            ml_confidence = 100.0 if classes_present[0] == 1 else 0.0
      except Exception:
        ml_confidence = 50.0

      # 4. Volatility Targets & Stoploss Brackets
      vol = hist["Returns"].rolling(window=20).std().iloc[-1]
      if pd.isna(vol) or vol == 0:
        vol = 0.02

      if direction == "Bullish":
        target_short = round(current_price * (1 + (vol * 1.8)), 2)
        target_long = round(current_price * (1 + (vol * 4.3)), 2)
        stoploss = round(current_price * (1 - (vol * 1.5)), 2)
        entry_low = round(current_price * 0.995, 2)
        entry_high = round(current_price * 1.005, 2)
      else:
        target_short = round(current_price * (1 - (vol * 1.8)), 2)
        target_long = round(current_price * (1 - (vol * 4.3)), 2)
        stoploss = round(current_price * (1 + (vol * 1.5)), 2)
        entry_low = round(current_price * 1.005, 2)
        entry_high = round(current_price * 0.995, 2)

      pct_short = round(
          ((target_short - current_price) / current_price) * 100, 1
      )
      pct_long = round(((target_long - current_price) / current_price) * 100, 1)

      str_pct_short = f"+{pct_short}%" if pct_short > 0 else f"{pct_short}%"
      str_pct_long = f"+{pct_long}%" if pct_long > 0 else f"{pct_long}%"

      # Record into ledger if not already saved today
      try:
        cursor.execute(
            "SELECT id FROM predictions WHERE date=? AND ticker=?",
            (today_str, ticker),
        )
        if not cursor.fetchone():
          cursor.execute(
              """
                        INSERT INTO predictions (date, ticker, signal_price, direction, ml_confidence, target_short, target_long, fii_dii_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
              (
                  today_str,
                  ticker,
                  current_price,
                  direction,
                  ml_confidence,
                  target_short,
                  target_long,
                  fii_dii_flow,
              ),
          )
      except Exception:
        pass

      clean_symbol = ticker.replace(".NS", "").replace(".BO", "")
      tv_url = (
          f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean_symbol}"
      )

      screened_results.append({
          "Ticker": clean_symbol,
          "RawTicker": ticker,
          "Current Price": current_price,
          "Execution Price": current_price,
          "Price Change": price_chg,
          "Price Change Pct": price_chg_pct,
          "Momentum Vector": direction,
          "RVol": rvol,
          "ML Signal Confidence": ml_confidence,
          "Entry Range": f"₹{entry_low} - ₹{entry_high}",
          "Stoploss": stoploss,
          "Swing Target 1-15d": f"₹{target_short} ({str_pct_short})",
          "Structural Target 20-90d": f"₹{target_long} ({str_pct_long})",
          "FII/DII Institutional Flow": fii_dii_flow,
          "TradingView Link": tv_url,
      })

    conn.commit()
    conn.close()
    return pd.DataFrame(screened_results)

  def run_backtest(self):
    backtest_logs = []
    for ticker, data in self.data_store.items():
      hist = data["history"]
      if len(hist) < 180:
        continue

      close_prices = hist["Close"]
      sma_val = (
          close_prices.rolling(window=200).mean()
          if len(close_prices) >= 200
          else close_prices.rolling(window=50).mean()
      )

      for i in range(120, len(hist) - 60, 20):
        price_trigger = close_prices.iloc[i]
        sma_trigger = sma_val.iloc[i]
        date_trigger = hist.index[i].strftime("%Y-%m-%d")

        if pd.isna(sma_trigger):
          continue
        direction = "Bullish" if price_trigger >= sma_trigger else "Bearish"

        forward_window = hist.iloc[i + 1 : i + 61]
        max_forward = forward_window["High"].max()
        min_forward = forward_window["Low"].min()

        max_upside = (
            (max_forward - price_trigger) / price_trigger
        ) * 100
        max_drawdown = (
            (min_forward - price_trigger) / price_trigger
        ) * 100

        backtest_logs.append({
            "Ticker": ticker.replace(".NS", ""),
            "Sim Date": date_trigger,
            "Trigger Price": round(price_trigger, 2),
            "Direction": direction,
            "Simulated Peak Return %": round(max_upside, 2),
            "Simulated Max Drawdown %": round(max_drawdown, 2),
        })
    return pd.DataFrame(backtest_logs)

  @staticmethod
  def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))
