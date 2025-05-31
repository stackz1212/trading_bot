import os
import logging
from sqlalchemy import create_engine
from dotenv import load_dotenv
import krakenex
import ta
import pandas as pd
import time
import json

# --- Load configuration ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../config/.env'))
with open(os.path.join(os.path.dirname(__file__), '../config/config.json')) as f:
    cfg = json.load(f)

# --- Logging setup ---
logging.basicConfig(
    filename='../logs/bot.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# --- DB setup (SQLite + SQLAlchemy) ---
engine = create_engine('sqlite:///../trades.db', echo=False)

# --- Kraken API setup ---
k = krakenex.API(cfg["api_key"], cfg["api_secret"])
SYMBOL = 'XXDGZUSD'   # Kraken code for DOGE/USD. Change as needed.

def fetch_ohlc(pair=SYMBOL, interval=1):
    resp = k.query_public('OHLC', {'pair': pair, 'interval': interval})
    result = resp['result']
    # Find correct key, as Kraken sometimes adds '.d'
    for k_ in result:
        if k_ != 'last':
            df = pd.DataFrame(result[k_], columns=[
                'time', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
            ])
            df = df.astype({'close': float})
            return df
    return None

def get_open_orders():
    resp = k.query_private('OpenOrders')
    return resp.get('result', {}).get('open', {})

def get_current_signal(df):
    # Example: Simple 5/15 SMA crossover
    df['sma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['sma15'] = ta.trend.sma_indicator(df['close'], window=15)
    # Simple long/short/no-signal
    if df['sma5'].iloc[-1] > df['sma15'].iloc[-1]:
        return 'long'
    elif df['sma5'].iloc[-1] < df['sma15'].iloc[-1]:
        return 'short'
    else:
        return 'none'

def order_still_valid(order, current_signal):
    """Determine if the order matches the current strategy signal.
       E.g., If signal flips, pending order is stale."""
    descr = order['descr']
    order_type = descr['type']      # 'buy' or 'sell'
    # Example: If signal is 'long', only keep 'buy' orders
    if current_signal == 'long' and order_type == 'buy':
        return True
    if current_signal == 'short' and order_type == 'sell':
        return True
    # For all other combos, consider stale
    return False

def remove_stale_orders():
    open_orders = get_open_orders()
    df = fetch_ohlc()
    if df is None or len(df) < 20:
        logger.warning("OHLC data fetch failed or not enough data")
        return
    current_signal = get_current_signal(df)
    logger.info(f"Current signal: {current_signal}")

    for order_id, order in open_orders.items():
        if not order_still_valid(order, current_signal):
            try:
                k.query_private('CancelOrder', {'txid': order_id})
                logger.info(f"Cancelled stale order: {order_id}")
                # Do not log to DB as per your requirements
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {str(e)}")

def main_loop():
    logger.info("Bot started.")
    while True:
        try:
            remove_stale_orders()
            # Place your main trading logic here: check signals, place/cancel orders, etc.
            time.sleep(15)  # Loop interval (seconds)
        except Exception as e:
            logger.error(f"Exception in main loop: {str(e)}")
            time.sleep(15)

if __name__ == "__main__":
    main_loop()
