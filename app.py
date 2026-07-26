import streamlit as st
import pandas as pd
from datetime import datetime, date
import calendar
from kiteconnect import KiteConnect
import requests
import time

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Desk A | Real-Time Institutional Scanner",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Desk A: Institutional Cash-Futures & MCX Spread Scanner")
st.caption("Project Kavya — Proprietary Institutional Research & Execution Dashboard")

# ==========================================
# 2. SIDEBAR - ADVANCED CONFIGURATION
# ==========================================
st.sidebar.header("🔑 Zerodha API Authentication")
DEFAULT_API_KEY = "5pq7uvvfukm67tzt"
api_key = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
access_token = st.sidebar.text_input("Daily Access Token", type="password", help="Paste your active daily session access token here")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Filters & Risk Controls")

# Rule 1: Yield Thresholds
min_arb_yield = st.sidebar.slider("Min Cash-Futures Yield (% p.a.)", min_value=2.0, max_value=20.0, value=6.0, step=0.5)

# Rule 2: Liquidity & Slippage Filters
min_volume = st.sidebar.number_input("Min Futures Volume", value=100000, step=50000, help="Filters out illiquid futures contracts.")
max_bid_ask_spread = st.sidebar.number_input("Max Bid-Ask Spread (₹)", value=0.50, step=0.05, help="Maximum gap between top Bid and Ask allowed in order book.")

# Rule 3: Budget & Capital Controls
max_cash_budget = st.sidebar.number_input("Max Cash Outlay (₹)", value=550000, step=25000, help="Filters out stocks where cash leg exceeds your tranche budget.")

# Rule 4: Expiry Week Cutoff
min_dte_cutoff = st.sidebar.slider("Min DTE Before Auto-Rollover (Days)", min_value=1, max_value=7, value=4, help="Auto-switches to Next Month futures if current month DTE is too low.")

st.sidebar.markdown("---")
st.sidebar.header("🛠️ System Debugging")
show_filtered_stocks = st.sidebar.checkbox("Show Filtered/Rejected Stocks (Debug Mode)", value=True, help="Shows all stocks and why they were filtered out.")

st.sidebar.markdown("---")
st.sidebar.header("⛏️ MCX Options")
min_mcx_spread = st.sidebar.number_input("Min MCX Spread Trigger (₹)", value=5.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("🔔 Telegram Push Alerts")
enable_alerts = st.sidebar.checkbox("Enable Telegram Push Alerts", value=False)
telegram_bot_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID")
refresh_interval = st.sidebar.slider("Auto-Refresh Rate (Seconds)", min_value=2, max_value=30, value=5)

# ==========================================
# 3. EXPANDED F&O WATCHLIST CONFIGURATION
# ==========================================
def get_last_thursday(year, month):
    """Calculates the exact date of the last Thursday for any given month/year (NSE Expiry)."""
    _, last_day = calendar.monthrange(year, month)
    dt = date(year, month, last_day)
    offset = (dt.weekday() - 3) % 7
    return date(year, month, last_day - offset)

now = datetime.now()
today = now.date()

# Dynamic Contract Month Selection (Current vs. Next Month)
curr_month_expiry = get_last_thursday(now.year, now.month)
curr_dte = (curr_month_expiry - today).days

if curr_dte < min_dte_cutoff:
    # Auto-Rollover to Next Month Contract if Expiry is too close
    if now.month == 12:
        target_year, target_month = now.year + 1, 1
    else:
        target_year, target_month = now.year, now.month + 1
    active_expiry = get_last_thursday(target_year, target_month)
    active_dte = (active_expiry - today).days
    target_dt = datetime(target_year, target_month, 1)
    st.info(f"📅 **Auto-Rollover Active:** Current month expires in {curr_dte} days. Scanning **{target_dt.strftime('%b').upper()}** contract (Expiry: {active_expiry}, DTE: {active_dte} days).")
else:
    active_expiry = curr_month_expiry
    active_dte = curr_dte
    target_dt = datetime(now.year, now.month, 1)

year_str = target_dt.strftime("%y")
curr_month_str = target_dt.strftime("%b").upper()

# Next Month String for MCX Spreads
if now.month == 12:
    mcx_next_dt = datetime(now.year + 1, 1, 1)
else:
    mcx_next_dt = datetime(now.year, now.month + 1, 1)
mcx_next_month_str = mcx_next_dt.strftime("%b").upper()

MCX_COMMODITIES = [
    "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
    "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "MENTHAOIL"
]

CASH_FUT_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS", 
    "ALKEM", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", 
    "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", 
    "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", 
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", 
    "CANBK", "CANFINHOME", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", 
    "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR", 
    "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", 
    "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", 
    "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", 
    "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI", "ICICIPRULI", 
    "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM", "INDIAMART", "INDIGO", 
    "INDUSINDBK", "INFY", "IOC", "IPCALAB", "IRCTC", "ITC", "JINDALSTEL", "JIOFIN", "JSWSTEEL", 
    "JUBLFOOD", "KOTAKBANK", "L&TFH", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", 
    "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCX", "METROPOLIS", 
    "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", 
    "NAVINFLUOR", "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", 
    "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POWERGRID", 
    "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN", 
    "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNTV", "SUNPHARMA", "SYNGENE", "TATACHEM", 
    "TATACOMM", "TATACONSUMER", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", 
    "TORNTPHARM", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", 
    "ZEEL", "ZYDUSLIFE"
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
    except Exception:
        pass

def initialize_kite(key, token):
    try:
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        return kite
    except Exception as e:
        st.error(f"Kite Connection Error: {e}")
        return None

@st.cache_data(ttl=86400)
def get_lot_sizes(_kite, exchange):
    try:
        instruments = _kite.instruments(exchange)
        return {item["tradingsymbol"]: item["lot_size"] for item in instruments}
    except Exception:
        return {}

def calculate_arbitrage_net_profit(cash_buy_price, cash_sell_price, fut_sell_price, fut_buy_price, qty):
    # CASH LEG CHARGES
    cash_buy_val = cash_buy_price * qty
    cash_sell_val = cash_sell_price * qty
    cash_turnover = cash_buy_val + cash_sell_val
    cash_brokerage = 0.0 
    cash_stt = (cash_buy_val * 0.001) + (cash_sell_val * 0.001)
    cash_exc_txn = cash_turnover * 0.0000307
    cash_stamp = cash_buy_val * 0.00015
    cash_sebi = cash_turnover * 0.000001
    cash_gst = (cash_brokerage + cash_exc_txn + cash_sebi) * 0.18  
    cash_dp = 15.93
    total_cash_charges = cash_brokerage + cash_stt + cash_exc_txn + cash_stamp + cash_sebi + cash_gst + cash_dp
    
    # FUTURES LEG CHARGES
    fut_sell_val = fut_sell_price * qty
    fut_buy_val = fut_buy_price * qty 
    fut_turnover = fut_sell_val + fut_buy_val
    fut_brokerage = 40.0
    fut_stt = fut_sell_val * 0.0002
    fut_exc_txn = fut_turnover * 0.0000183
    fut_stamp = fut_buy_val * 0.00002
    fut_sebi = fut_turnover * 0.000001  
    fut_gst = (fut_brokerage + fut_exc_txn + fut_sebi) * 0.18 
    total_fut_charges = fut_brokerage + fut_stt + fut_exc_txn + fut_stamp + fut_sebi + fut_gst
    
    gross_profit = (cash_sell_val - cash_buy_val) + (fut_sell_val - fut_buy_val)
    total_charges = total_cash_charges + total_fut_charges
    net_profit = gross_profit - total_charges
    
    return round(total_charges, 2), round(net_profit, 2)

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# ==========================================
# 5. DASHBOARD RENDER
# ==========================================
if not access_token:
    st.warning("👈 Please enter today's active Daily Access Token in the sidebar to load the scanner.")
    st.stop()

kite = initialize_kite(api_key, access_token)

if kite:
    nfo_lot_sizes = get_lot_sizes(kite, "NFO")
    
    tab1, tab2, tab3 = st.tabs([
        "📈 Cash-Futures Arbitrage Board", 
        "⛏️ MCX Calendar Spreads", 
        "📖 System & Risk Documentation"
    ])

    with tab1:
        st.subheader(f"Equity Cash vs. Futures Scanner ({len(CASH_FUT_STOCKS)} Stocks | Expiry: {active_expiry})")
        
        symbols_to_quote = []
        for stock in CASH_FUT_STOCKS:
            cash_sym = f"NSE:{stock}"
            fut_sym = f"NFO:{stock}{year_str}{curr_month_str}FUT"
            symbols_to_quote.extend([cash_sym, fut_sym])
            
        try:
            quotes = {}
            for chunk in chunk_list(symbols_to_quote, 400):
                quotes.update(kite.quote(chunk))
                
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
                    fut_volume = fut_q.get("volume", 0)
                    
                    # Extract Order Book Depth for Bid-Ask Spread Check
                    fut_depth = fut_q.get("depth", {})
                    buy_orders = fut_depth.get("buy", [])
                    sell_orders = fut_depth.get("sell", [])
                    
                    if buy_orders and sell_orders:
                        top_bid = buy_orders[0].get("price", 0)
                        top_ask = sell_orders[0].get("price", 0)
                        bid_ask_gap = round(top_ask - top_bid, 2) if (top_ask > 0 and top_bid > 0) else 0.0
                    else:
                        bid_ask_gap = 0.0

                    # Lot Size & Capital Metrics
                    lot_size = nfo_lot_sizes.get(fut_contract_name, 1000)
                    cash_outlay = cash_price * lot_size
                    fut_margin = (fut_price * lot_size) * 0.20  # ~20% standard margin requirement
                    total_capital_req = cash_outlay + fut_margin
                    
                    # Compute Profit and Spread
                    abs_spread = fut_price - cash_price
                    
                    total_taxes, net_profit = calculate_arbitrage_net_profit(
                        cash_buy_price=cash_price,
                        cash_sell_price=fut_price,
                        fut_sell_price=fut_price,
                        fut_buy_price=fut_price, 
                        qty=lot_size
                    )

                    annualized_yield = ((abs_spread / cash_price) * (365 / max(active_dte, 1))) * 100
                    rotc_yield = ((net_profit / total_capital_req) * (365 / max(active_dte, 1))) * 100

                    # Evaluate if stock passes all risk/budget filters
                    passed_all_filters = (
                        cash_price > 0 and fut_price > 0 and 
                        fut_volume >= min_volume and 
                        bid_ask_gap <= max_bid_ask_spread and 
                        cash_outlay <= max_cash_budget and
                        net_profit > 0
                    )

                    # Determine specific status tag
                    if passed_all_filters:
                        if annualized_yield > 25.0:
                            status_tag = "⚠️ Dividend/Ban Check"
                        elif annualized_yield >= min_arb_yield:
                            status_tag = "🔥 TARGET HIT"
                        else:
                            status_tag = "Normal"
                    else:
                        if net_profit <= 0:
                            status_tag = "❌ Negative Net Profit"
                        elif cash_outlay > max_cash_budget:
                            status_tag = "❌ Over Budget"
                        elif fut_volume < min_volume:
                            status_tag = "❌ Low Volume"
                        elif bid_ask_gap > max_bid_ask_spread:
                            status_tag = "❌ Wide Spread (Slippage)"
                        else:
                            status_tag = "❌ Filtered"

                    # TELEGRAM ALERT
                    if enable_alerts and passed_all_filters and (min_arb_yield <= annualized_yield <= 25.0):
                        msg = f"🚨 *ARBITRAGE ALERT: {stock}*\nYield: {annualized_yield:.2f}% p.a.\nROTC: {rotc_yield:.2f}% p.a.\nNet Profit: ₹{net_profit}\nCash Outlay: ₹{cash_outlay:,.0f}"
                        send_telegram_alert(msg, telegram_bot_token, telegram_chat_id)

                    # Only append if passed OR if Debug Mode is ON
                    if passed_all_filters or show_filtered_stocks:
                        arb_data.append({
                            "Symbol": stock,
                            "Contract": fut_contract_name,
                            "Cash Price (₹)": f"{cash_price:.2f}",
                            "Future Price (₹)": f"{fut_price:.2f}",
                            "Lot Size": lot_size,
                            "Cash Outlay (₹)": f"{cash_outlay:,.0f}",
                            "Total Capital (₹)": f"{total_capital_req:,.0f}",
                            "Bid-Ask Gap (₹)": bid_ask_gap,
                            "Volume": fut_volume,
                            "DTE": active_dte,
                            "Spread (₹)": round(abs_spread, 2),
                            "Yield (% p.a.)": round(annualized_yield, 2),
                            "ROTC (% p.a.)": round(rotc_yield, 2),
                            "Net Profit (₹)": net_profit,
                            "Status": status_tag
                        })

            df_arb = pd.DataFrame(arb_data)
            
            if not df_arb.empty:
                # Rank by ROTC, pushing rejected stocks to the bottom
                df_arb['is_rejected'] = df_arb['Status'].str.contains("❌")
                df_arb = df_arb.sort_values(by=["is_rejected", "ROTC (% p.a.)"], ascending=[True, False]).drop(columns=['is_rejected']).reset_index(drop=True)
                
                def highlight_arb(row):
                    if row["Status"] == "🔥 TARGET HIT":
                        return ['background-color: #1e3d2f; color: #7cfc00'] * len(row)
                    elif row["Status"] == "⚠️ Dividend/Ban Check":
                        return ['background-color: #4a3800; color: #ffcc00'] * len(row)
                    elif "❌" in row["Status"]:
                        return ['background-color: #2b2b2b; color: #666666'] * len(row) # Dimmed out for rejected stocks
                    return [''] * len(row)

                st.dataframe(df_arb.style.apply(highlight_arb, axis=1), use_container_width=True)
            else:
                st.info("No arbitrage opportunities found. Toggle 'Show Filtered/Rejected Stocks' in the sidebar to see diagnostic data.")

        except Exception as e:
            st.error(f"Error processing Cash-Futures data: {e}")

    with tab2:
        st.subheader("All MCX Commodity Calendar Spread Scanner")
        
        mcx_symbols = []
        for metal in MCX_COMMODITIES:
            near_sym = f"MCX:{metal}{year_str}{curr_month_str}FUT"
            far_sym = f"MCX:{metal}{year_str}{mcx_next_month_str}FUT"
            mcx_symbols.extend([near_sym, far_sym])

        try:
            mcx_quotes = kite.quote(mcx_symbols)
            spread_data = []

            for metal in MCX_COMMODITIES:
                near_contract_name = f"{metal}{year_str}{curr_month_str}FUT"
                far_contract_name = f"{metal}{year_str}{mcx_next_month_str}FUT"
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

    with tab3:
        st.markdown("""
        ### 📖 Desk A Risk Rules & System Logic

        1. **Bid-Ask Spread Filter:** Reads top depth (`buy[0]` and `sell[0]`). Hides stocks with gaps > ₹0.50 to eliminate execution slippage.
        2. **ROTC (Return on Total Capital):** Ranks opportunities by annualized return on combined cash outlay and futures margin requirement.
        3. **Dynamic DTE Rollover:** Auto-switches to next month's futures contract if current month expiry is less than the specified days away.
        4. **Dividend Anomaly Warning:** Flags any yield > 25% p.a. as `⚠️ Dividend/Ban Check` to avoid fake price discrepancies caused by corporate action adjustments.
        5. **Debug Mode:** A toggle to view stocks failing constraints (e.g. over budget, negative net profit), colored grey for immediate diagnosis.
        """)

    time.sleep(refresh_interval)
    st.rerun()
