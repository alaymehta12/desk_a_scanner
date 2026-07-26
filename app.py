import streamlit as st
import pandas as pd
from datetime import datetime
from kiteconnect import KiteConnect
import requests
import time

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Desk A | Real-Time Scanner",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Desk A: Cash-Futures & MCX Calendar Spread Scanner")
st.caption("Project Kavya — Proprietary Institutional Research Dashboard")

# ==========================================
# 2. SIDEBAR - SIMPLE AUTHENTICATION
# ==========================================
st.sidebar.header("🔑 Zerodha API Authentication")

DEFAULT_API_KEY = "5pq7uvvfukm67tzt"

api_key = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
access_token = st.sidebar.text_input("Daily Access Token", type="password", help="Paste your active daily session access token here")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Thresholds")
min_arb_yield = st.sidebar.slider("Min Cash-Futures Yield (% p.a.)", min_value=4.0, max_value=20.0, value=8.0, step=0.5)
min_mcx_spread = st.sidebar.number_input("Min MCX Spread Trigger (₹)", value=5.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("🔔 Telegram Alerts (Phase 2)")
enable_alerts = st.sidebar.checkbox("Enable Telegram Push Alerts", value=False)
telegram_bot_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID")

refresh_interval = st.sidebar.slider("Auto-Refresh Rate (Seconds)", min_value=2, max_value=30, value=5)

# ==========================================
# 3. EXPANDED WATCHLIST CONFIGURATION
# ==========================================
now = datetime.now()
year_str = now.strftime("%y") # e.g., '26'
curr_month_str = now.strftime("%b").upper() # e.g., 'JUL'

if now.month == 12:
    next_month_dt = datetime(now.year + 1, 1, 1)
else:
    next_month_dt = datetime(now.year, now.month + 1, 1)
next_month_str = next_month_dt.strftime("%b").upper()

# Complete MCX Tradable Commodity Universe
MCX_COMMODITIES = [
    "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
    "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "MENTHAOIL"
]

# Top Liquid Nifty 100 / F&O Universe
CASH_FUT_STOCKS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", 
    "LT", "KOTAKBANK", "AXISBANK", "ASIANPAINT", "HINDUNILVR", "BAJFINANCE", "MARUTI", 
    "SUNPHARMA", "TITAN", "TATASTEEL", "ULTRACEMCO", "POWERGRID", "NTPC", "COALINDIA", 
    "TATAMOTORS", "M&M", "JSWSTEEL", "GRASIM", "HCLTECH", "TECHM", "WIPRO", "ADANIENT", 
    "ADANIPORTS", "TATACONSUMER", "BRITANNIA", "EICHERMOT", "DIVISLAB", "DRREDDY", "CIPLA", 
    "HEROMOTOCO", "APOLLOHOSP", "HDFCLIFE", "SBILIFE", "INDUSINDBK", "BPCL", "HINDPETRO", 
    "IOC", "BEL", "HAL", "VEDL", "BHEL", "RECLTD", "PFC", "DLF", "TRENT", "GAIL", 
    "SIEMENS", "ABB", "CANBK", "BANKBARODA", "CHOLAFIN", "SHRIRAMFIN", "TATACOMM"
]

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================
def send_telegram_alert(message, token, chat_id):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        st.error(f"Telegram alert error: {e}")

def initialize_kite(key, token):
    try:
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        return kite
    except Exception as e:
        st.error(f"Kite Connection Error: {e}")
        return None

@st.cache_data(ttl=86400) # Cache lot sizes for 24 hours
def get_lot_sizes(_kite, exchange):
    """Fetches and caches live lot sizes from Zerodha for accurate net profit calculations."""
    try:
        instruments = _kite.instruments(exchange)
        return {item["tradingsymbol"]: item["lot_size"] for item in instruments}
    except Exception as e:
        return {}

def calculate_arbitrage_net_profit(cash_buy_price, cash_sell_price, fut_sell_price, fut_buy_price, qty):
    """
    Calculates the precise Net Profit of a Cash-Futures arbitrage trade on Zerodha.
    Assumes standard F&O lot sizes (where 0.03% brokerage > Rs 20, capping it at Rs 20/order).
    """
    # 1. CASH LEG (EQUITY DELIVERY) CHARGES
    cash_buy_val = cash_buy_price * qty
    cash_sell_val = cash_sell_price * qty
    cash_turnover = cash_buy_val + cash_sell_val
    
    cash_brokerage = 0.0 
    cash_stt = (cash_buy_val * 0.001) + (cash_sell_val * 0.001)  # 0.1% on Buy & Sell
    cash_exc_txn = cash_turnover * 0.0000307  # NSE Txn Charge 0.00307%
    cash_stamp = cash_buy_val * 0.00015  # 0.015% Stamp Duty on Buy side only
    cash_sebi = cash_turnover * 0.000001  # Rs 10 per crore
    cash_gst = (cash_brokerage + cash_exc_txn + cash_sebi) * 0.18  
    cash_dp = 15.93  # Zerodha DP Charge 
    
    total_cash_charges = cash_brokerage + cash_stt + cash_exc_txn + cash_stamp + cash_sebi + cash_gst + cash_dp
    
    # 2. FUTURES LEG CHARGES
    fut_sell_val = fut_sell_price * qty
    fut_buy_val = fut_buy_price * qty 
    fut_turnover = fut_sell_val + fut_buy_val
    
    fut_brokerage = 40.0  # Rs 20 entry + Rs 20 exit
    fut_stt = fut_sell_val * 0.0002  # 0.02% STT applied ONLY on the Sell side
    fut_exc_txn = fut_turnover * 0.0000183  # NSE Txn Charge 0.00183%
    fut_stamp = fut_buy_val * 0.00002  # 0.002% Stamp Duty on Buy side only
    fut_sebi = fut_turnover * 0.000001  
    fut_gst = (fut_brokerage + fut_exc_txn + fut_sebi) * 0.18 
    
    total_fut_charges = fut_brokerage + fut_stt + fut_exc_txn + fut_stamp + fut_sebi + fut_gst
    
    # 3. PROFIT CALCULATION
    gross_profit = (cash_sell_val - cash_buy_val) + (fut_sell_val - fut_buy_val)
    total_charges = total_cash_charges + total_fut_charges
    net_profit = gross_profit - total_charges
    
    return round(total_charges, 2), round(net_profit, 2)

# ==========================================
# 5. DASHBOARD RENDER
# ==========================================
if not access_token:
    st.warning("👈 Please enter today's active Daily Access Token in the sidebar to load the scanner.")
    st.stop()

kite = initialize_kite(api_key, access_token)

if kite:
    # Pre-fetch and cache lot sizes natively from the API
    nfo_lot_sizes = get_lot_sizes(kite, "NFO")
    
    tab1, tab2, tab3 = st.tabs([
        "📈 Cash-Futures Arbitrage (Equity)", 
        "⛏️ MCX Calendar Spreads (Commodities)", 
        "📖 Strategy & System Docs"
    ])

    # ------------------------------------------
    # TAB 1: CASH-FUTURES ARBITRAGE
    # ------------------------------------------
    with tab1:
        st.subheader(f"Equity Cash vs. Futures Scanner ({len(CASH_FUT_STOCKS)} Stocks)")
        
        symbols_to_quote = []
        for stock in CASH_FUT_STOCKS:
            cash_sym = f"NSE:{stock}"
            fut_sym = f"NFO:{stock}{year_str}{curr_month_str}FUT"
            symbols_to_quote.extend([cash_sym, fut_sym])
            
        try:
            # Query all stock quotes in a single batched API call
            quotes = kite.quote(symbols_to_quote)
            arb_data = []

            for stock in CASH_FUT_STOCKS:
                cash_sym = f"NSE:{stock}"
                fut_contract_name = f"{stock}{year_str}{curr_month_str}FUT"
                fut_sym = f"NFO:{fut_contract_name}"

                cash_q = quotes.get(cash_sym)
                fut_q = quotes.get(fut_sym)

                if cash_q and fut_q:
                    cash_price = cash_q["last_price"]
                    fut_price = fut_q["last_price"]
                    
                    if cash_price > 0 and fut_price > 0:
                        abs_spread = fut_price - cash_price
                        days_to_expiry = max((30 - now.day), 1)
                        
                        # Fetch the dynamic lot size from our cached API pull
                        lot_size = nfo_lot_sizes.get(fut_contract_name, 1000) # Default 1000 if not found
                        
                        # We simulate closing the trade precisely when prices converge exactly on Expiry
                        total_taxes, net_profit = calculate_arbitrage_net_profit(
                            cash_buy_price=cash_price,
                            cash_sell_price=fut_price,  # Convergence Price
                            fut_sell_price=fut_price,
                            fut_buy_price=fut_price,    # Convergence Price
                            qty=lot_size
                        )

                        annualized_yield = ((abs_spread / cash_price) * (365 / days_to_expiry)) * 100

                        if enable_alerts and annualized_yield >= min_arb_yield:
                            msg = f"🚨 *ARBITRAGE ALERT: {stock}*\nYield: {annualized_yield:.2f}% p.a.\nSpread: ₹{abs_spread:.2f}\nNet Profit: ₹{net_profit}"
                            send_telegram_alert(msg, telegram_bot_token, telegram_chat_id)

                        arb_data.append({
                            "Symbol": stock,
                            "Future Contract": fut_contract_name,
                            "Cash Price (₹)": f"{cash_price:.2f}",
                            "Future Price (₹)": f"{fut_price:.2f}",
                            "Lot Size": lot_size,
                            "Spread (₹)": round(abs_spread, 2),
                            "Yield (% p.a.)": round(annualized_yield, 2),
                            "Total Taxes (₹)": total_taxes,
                            "Net Profit (₹)": net_profit,
                            "Status": "🔥 OPPORTUNITY" if annualized_yield >= min_arb_yield else "Normal"
                        })

            df_arb = pd.DataFrame(arb_data)
            df_arb = df_arb.sort_values(by="Yield (% p.a.)", ascending=False).reset_index(drop=True)

            def highlight_arb(row):
                if row["Yield (% p.a.)"] >= min_arb_yield and row["Net Profit (₹)"] > 0:
                    return ['background-color: #1e3d2f; color: #7cfc00'] * len(row)
                return [''] * len(row)

            st.dataframe(df_arb.style.apply(highlight_arb, axis=1), use_container_width=True)

        except Exception as e:
            st.error(f"Error fetching Cash-Futures data: {e}")

    # ------------------------------------------
    # TAB 2: MCX CALENDAR SPREADS
    # ------------------------------------------
    with tab2:
        st.subheader("All MCX Commodity Calendar Spread Scanner")
        
        mcx_symbols = []
        for metal in MCX_COMMODITIES:
            near_sym = f"MCX:{metal}{year_str}{curr_month_str}FUT"
            far_sym = f"MCX:{metal}{year_str}{next_month_str}FUT"
            mcx_symbols.extend([near_sym, far_sym])

        try:
            mcx_quotes = kite.quote(mcx_symbols)
            spread_data = []

            for metal in MCX_COMMODITIES:
                near_contract_name = f"{metal}{year_str}{curr_month_str}FUT"
                far_contract_name = f"{metal}{year_str}{next_month_str}FUT"
                near_sym = f"MCX:{near_contract_name}"
                far_sym = f"MCX:{far_contract_name}"

                near_q = mcx_quotes.get(near_sym)
                far_q = mcx_quotes.get(far_sym)

                if near_q and far_q:
                    near_price = near_q["last_price"]
                    far_price = far_q["last_price"]
                    spread = far_price - near_price

                    if enable_alerts and abs(spread) >= min_mcx_spread:
                        msg = f"🚨 *MCX SPREAD ALERT: {metal}*\nNear: {near_price}\nFar: {far_price}\nSpread: ₹{spread:.2f}"
                        send_telegram_alert(msg, telegram_bot_token, telegram_chat_id)

                    spread_data.append({
                        "Commodity": metal,
                        "Near Contract": near_contract_name,
                        "Far Contract": far_contract_name,
                        "Near Price (₹)": f"{near_price:.2f}",
                        "Far Price (₹)": f"{far_price:.2f}",
                        "Spread (Far - Near) ₹": round(spread, 2),
                        "Status": "⚡ WIDE SPREAD" if abs(spread) >= min_mcx_spread else "Normal"
                    })

            df_spread = pd.DataFrame(spread_data)
            
            def highlight_spread(row):
                if abs(row["Spread (Far - Near) ₹"]) >= min_mcx_spread:
                    return ['background-color: #3b2d18; color: #ffd700'] * len(row)
                return [''] * len(row)

            st.dataframe(df_spread.style.apply(highlight_spread, axis=1), use_container_width=True)

        except Exception as e:
            st.error(f"Error fetching MCX data: {e}")

    # ------------------------------------------
    # TAB 3: DOCUMENTATION & SYSTEM README
    # ------------------------------------------
    with tab3:
        st.markdown("""
        # 📖 Project Kavya — Desk A Documentation & Operational Guide

        ---

        ### 1. Executive Summary
        **Project Kavya** is an 18-year wealth compounding initiative. Desk A generates non-directional, low-volatility yield to build the primary balance sheet before transitioning into tactical hedge-fund bets.

        ---

        ### 2. Desk A Mathematical Models

        #### A. Cash-Futures Arbitrage Engine
        * **Mathematical Formula:** 
          $$\\text{Annualized Yield (\\%)} = \\left( \\frac{\\text{Future Price} - \\text{Cash Price}}{\\text{Cash Price}} \\right) \\times \\left( \\frac{365}{\\text{Days to Expiry}} \\right) \\times 100$$
        * **Execution:** Buy cash delivery, short near-month future when yield crosses target.

        #### B. MCX Calendar Spreads
        * **Mathematical Formula:**
          $$\\text{Spread} = \\text{Far Month Price} - \\text{Near Month Price}$$
        * **Execution:** Trade time-spread dislocations between near and far month futures.

        ---

        ### 3. Net Profit Calculator Parameters
        The embedded Net Profit calculator deducts the following exact exchange fees from your gross spread:
        * 0.1% STT on both Buy/Sell Equity Turnover
        * 0.02% STT on short Futures Turnover
        * 18% GST on all brokerages, NSE transaction fees, and SEBI charges
        * ₹15.93 Depository Participant (DP) charge on the cash exit leg.
        """)

    time.sleep(refresh_interval)
    st.rerun()
