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
    page_title="Desk A | Institutional Curve Scanner",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Desk A: Institutional Yield & Curve Scanner")
st.caption("Project Kavya — Proprietary Arbitrage & Calendar Spread Dashboard")

# ==========================================
# 2. SIDEBAR - ADVANCED CONFIGURATION
# ==========================================
st.sidebar.header("🔑 Zerodha API Authentication")
DEFAULT_API_KEY = "5pq7uvvfukm67tzt"
api_key = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
access_token = st.sidebar.text_input("Daily Access Token", type="password", help="Paste your active daily session access token here")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Thresholds & Filters")

min_arb_yield = st.sidebar.slider("Min Cash-Futures Yield (% p.a.)", min_value=2.0, max_value=20.0, value=6.0, step=0.5)
min_dte_cutoff = st.sidebar.slider("Min DTE Before Auto-Rollover (Days)", min_value=1, max_value=10, value=4, help="Auto-switches to Next Month futures if current month DTE is less than or equal to this.")

st.sidebar.markdown("---")
st.sidebar.header("⛏️ MCX Specific Filters")
min_mcx_yield = st.sidebar.slider("Min MCX Spread Yield (% p.a.)", min_value=2.0, max_value=20.0, value=6.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("🛠️ System Debugging")
show_filtered_stocks = st.sidebar.checkbox("Show Filtered/Rejected Trades", value=True, help="Shows trades failing yield constraints.")

st.sidebar.markdown("---")
st.sidebar.header("🔔 Telegram Push Alerts")
enable_alerts = st.sidebar.checkbox("Enable Telegram Push Alerts", value=False)
telegram_bot_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID")
refresh_interval = st.sidebar.slider("Auto-Refresh Rate (Seconds)", min_value=2, max_value=30, value=5)

# ==========================================
# 3. EXPANDED F&O & CURVE CONFIGURATION
# ==========================================
def get_last_thursday(year, month):
    _, last_day = calendar.monthrange(year, month)
    dt = date(year, month, last_day)
    offset = (dt.weekday() - 3) % 7
    return date(year, month, last_day - offset)

def get_target_month(base_date, month_offset):
    m = base_date.month + month_offset
    y = base_date.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    expiry = get_last_thursday(y, m)
    return {
        "year_str": str(y)[-2:],
        "month_str": datetime(y, m, 1).strftime("%b").upper(),
        "expiry_date": expiry,
        "dte": (expiry - today).days
    }

now = datetime.now()
today = now.date()

curr_month_expiry = get_last_thursday(now.year, now.month)
curr_dte = (curr_month_expiry - today).days

# DTE Auto-Rollover Logic for the "Base" Month (M1)
if curr_dte <= min_dte_cutoff:
    base_month_offset = 1
    st.info(f"📅 **Auto-Rollover Active:** Current month expires in {curr_dte} days. Base scanning shifted to next month.")
else:
    base_month_offset = 0

# Generate M1 (Near), M2 (Next), M3 (Far) Contracts
m1 = get_target_month(now, base_month_offset)
m2 = get_target_month(now, base_month_offset + 1)
m3 = get_target_month(now, base_month_offset + 2)

MCX_COMMODITIES = [
    "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
    "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "MENTHAOIL",
    "GOLDGUINEA", "GOLDPETAL", "SILVERMIC"
]

# Top 100 highly liquid stocks (Permitted for Month 3 Far Curve Scanning)
TOP_100_STOCKS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "LT", "SBIN", "BHARTIARTL", "BAJFINANCE",
    "KOTAKBANK", "AXISBANK", "ASIANPAINT", "HINDUNILVR", "MARUTI", "SUNPHARMA", "TITAN", "TATASTEEL", 
    "ULTRACEMCO", "POWERGRID", "NTPC", "TATAMOTORS", "M&M", "JSWSTEEL", "GRASIM", "HCLTECH", "TECHM", 
    "WIPRO", "ADANIENT", "ADANIPORTS", "TATACONSUMER", "BRITANNIA", "EICHERMOT", "DIVISLAB", "DRREDDY", 
    "CIPLA", "HEROMOTOCO", "APOLLOHOSP", "HDFCLIFE", "SBILIFE", "INDUSINDBK", "BPCL", "HINDPETRO", 
    "IOC", "BEL", "HAL", "VEDL", "BHEL", "RECLTD", "PFC", "DLF", "TRENT", "GAIL", "SIEMENS", "ABB", 
    "CANBK", "BANKBARODA", "CHOLAFIN", "SHRIRAMFIN", "TATACOMM", "COALINDIA", "TVSMOTOR", "AMBUJACEM", 
    "SHREECEM", "BOSCHLTD", "INDHOTEL", "PIDILITIND", "HAVELLS", "PNB", "ICICIPRULI", "ICICIGI", 
    "GODREJCP", "DABUR", "COLPAL", "MARICO", "MGL", "IGL", "PETRONET", "LTIM", "OBEROIRLTY", 
    "GODREJPROP", "AUBANK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "MUTHOOTFIN", "MANAPPURAM", 
    "SAIL", "NMDC", "NATIONALUM", "HINDALCO", "HINDCOPPER", "JINDALSTEL", "TATACHEM", "DEEPAKNTR", 
    "PIIND", "UPL", "AUROPHARMA", "LUPIN", "TORNTPHARM"
]

# Full 180+ F&O Universe (Permitted for Month 1 and Month 2)
CASH_FUT_STOCKS = list(set(TOP_100_STOCKS + [
    "AARTIIND", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ALKEM", "APOLLOTYRE", "ASHOKLEY", "ASTRAL", 
    "ATUL", "BAJAJ-AUTO", "BAJAJFINSV", "BALKRISIND", "BALRAMCHIN", "BATAINDIA", "BERGEPAINT", 
    "BHARATFORG", "BIOCON", "BSE", "CANFINHOME", "CHAMBLFERT", "COFORGE", "CONCOR", "COROMANDEL", 
    "CROMPTON", "CUB", "CUMMINSIND", "DALBHARAT", "DIXON", "ESCORTS", "EXIDEIND", "GLENMARK", 
    "GMRINFRA", "GNFC", "GRANULES", "GUJGASLTD", "HDFCAMC", "IDEA", "IEX", "INDIACEM", "INDIAMART", 
    "INDIGO", "IPCALAB", "IRCTC", "JIOFIN", "JUBLFOOD", "L&TFH", "LALPATHLAB", "LAURUSLABS", 
    "LICHSGFIN", "LTTS", "M&MFIN", "MCX", "METROPOLIS", "MFSL", "MOTHERSON", "MPHASIS", "MRF", 
    "NAUKRI", "NAVINFLUOR", "NESTLEIND", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", "POLYCAB", 
    "PVRINOX", "RAMCOCEM", "RBLBANK", "SBICARD", "SRF", "SUNTV", "SYNGENE", "TATAPOWER", "UBL", 
    "VOLTAS", "ZEEL", "ZYDUSLIFE"
]))

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================
def calculate_arbitrage_net_profit(cash_buy_price, cash_sell_price, fut_sell_price, fut_buy_price, qty):
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
    
    return round(gross_profit, 2), round(total_charges, 2), round(net_profit, 2)

def calculate_mcx_spread_net_profit(near_price, far_price, qty):
    buy_turnover = (near_price + far_price) * qty
    sell_turnover = (near_price + far_price) * qty
    total_turnover = buy_turnover + sell_turnover

    mcx_brokerage = 80.0 
    mcx_ctt = sell_turnover * 0.0001
    mcx_exc_txn = total_turnover * 0.000021
    mcx_stamp = buy_turnover * 0.00002
    mcx_sebi = total_turnover * 0.000001  
    mcx_gst = (mcx_brokerage + mcx_exc_txn + mcx_sebi) * 0.18 
    
    total_charges = mcx_brokerage + mcx_ctt + mcx_exc_txn + mcx_stamp + mcx_sebi + mcx_gst
    
    gross_profit = abs(far_price - near_price) * qty
    net_profit = gross_profit - total_charges
    
    return round(gross_profit, 2), round(total_charges, 2), round(net_profit, 2)

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# ==========================================
# 5. DASHBOARD RENDER
# ==========================================
if not access_token:
    st.warning("👈 Please enter today's active Daily Access Token in the sidebar to load the scanner.")
    st.stop()

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

@st.cache_data(ttl=86400)
def get_lot_sizes(_kite, exchange):
    try:
        instruments = _kite.instruments(exchange)
        return {item["tradingsymbol"]: item["lot_size"] for item in instruments}
    except Exception:
        return {}

nfo_lot_sizes = get_lot_sizes(kite, "NFO")
mcx_lot_sizes = get_lot_sizes(kite, "MCX")

tab1, tab2, tab3 = st.tabs([
    "📈 Equity Curve Arbitrage", 
    "⛏️ MCX Curve Spreads", 
    "📖 Cost Sheet & Logic Docs"
])

# ------------------------------------------
# TAB 1: EQUITY CASH-FUTURES ARBITRAGE
# ------------------------------------------
with tab1:
    st.subheader(f"Equity Arbitrage Curve Scanner (Spanning {m1['month_str']} to {m3['month_str']})")
    
    symbols_to_quote = []
    for stock in CASH_FUT_STOCKS:
        symbols_to_quote.append(f"NSE:{stock}")
        symbols_to_quote.append(f"NFO:{stock}{m1['year_str']}{m1['month_str']}FUT")
        symbols_to_quote.append(f"NFO:{stock}{m2['year_str']}{m2['month_str']}FUT")
        if stock in TOP_100_STOCKS:
            symbols_to_quote.append(f"NFO:{stock}{m3['year_str']}{m3['month_str']}FUT")
        
    try:
        quotes = {}
        for chunk in chunk_list(symbols_to_quote, 400):
            quotes.update(kite.quote(chunk))
            
        arb_data = []

        for stock in CASH_FUT_STOCKS:
            cash_sym = f"NSE:{stock}"
            cash_q = quotes.get(cash_sym)
            if not cash_q: continue
            cash_price = cash_q["last_price"]
            if cash_price <= 0: continue

            # Evaluate Curve: Month 1, Month 2, Month 3
            curve_months = [(1, m1), (2, m2)]
            if stock in TOP_100_STOCKS:
                curve_months.append((3, m3))

            for month_gap, m_data in curve_months:
                fut_contract_name = f"{stock}{m_data['year_str']}{m_data['month_str']}FUT"
                fut_sym = f"NFO:{fut_contract_name}"
                fut_q = quotes.get(fut_sym)

                if fut_q and fut_q["last_price"] > 0:
                    fut_price = fut_q["last_price"]
                    lot_size = nfo_lot_sizes.get(fut_contract_name, 1000)
                    
                    cash_outlay = cash_price * lot_size
                    fut_margin = (fut_price * lot_size) * 0.20
                    total_capital_req = cash_outlay + fut_margin
                    
                    abs_spread = fut_price - cash_price
                    gross_profit, total_taxes, net_profit = calculate_arbitrage_net_profit(
                        cash_buy_price=cash_price, cash_sell_price=fut_price,
                        fut_sell_price=fut_price, fut_buy_price=fut_price, qty=lot_size
                    )

                    if net_profit <= 0:
                        continue

                    annualized_yield = ((abs_spread / cash_price) * (365 / max(m_data['dte'], 1))) * 100
                    rotc_yield = ((net_profit / total_capital_req) * (365 / max(m_data['dte'], 1))) * 100

                    if annualized_yield > 25.0:
                        status_tag = "⚠️ Dividend/Ban Check"
                    elif annualized_yield >= min_arb_yield:
                        status_tag = "🔥 TARGET HIT"
                    else:
                        status_tag = "Normal"

                    if show_filtered_stocks or status_tag != "Normal":
                        arb_data.append({
                            "Symbol": stock,
                            "Buy Leg": f"NSE Cash",
                            "Sell Leg": f"{m_data['month_str']} FUT",
                            "Gap": f"{month_gap} Mo.",
                            "DTE": m_data['dte'],
                            "Cash Price": f"₹{cash_price:.2f}",
                            "Future Price": f"₹{fut_price:.2f}",
                            "Capital Req": f"₹{total_capital_req:,.0f}",
                            "Spread": f"₹{abs_spread:.2f}",
                            "Yield (% p.a.)": round(annualized_yield, 2),
                            "ROTC (% p.a.)": round(rotc_yield, 2),
                            "Gross Profit": f"₹{gross_profit:,.0f}",
                            "Taxes": f"₹{total_taxes:,.0f}",
                            "Net Profit": net_profit,
                            "Status": status_tag
                        })

        df_arb = pd.DataFrame(arb_data)
        
        if not df_arb.empty:
            df_arb = df_arb.sort_values(by=["Yield (% p.a.)", "Net Profit"], ascending=[False, False]).reset_index(drop=True)
            
            def highlight_arb(row):
                if row["Status"] == "🔥 TARGET HIT": return ['background-color: #1e3d2f; color: #7cfc00'] * len(row)
                elif row["Status"] == "⚠️ Dividend/Ban Check": return ['background-color: #4a3800; color: #ffcc00'] * len(row)
                return [''] * len(row)

            st.dataframe(df_arb.style.apply(highlight_arb, axis=1), use_container_width=True)
        else:
            st.info("No positive-yield arbitrage opportunities found on the curve.")

    except Exception as e:
        st.error(f"Error processing Equity Curve data: {e}")

# ------------------------------------------
# TAB 2: MCX COMMODITY CALENDAR SPREADS
# ------------------------------------------
with tab2:
    st.subheader("MCX Commodity Multi-Month Curve Scanner")
    
    mcx_symbols = []
    for metal in MCX_COMMODITIES:
        mcx_symbols.append(f"MCX:{metal}{m1['year_str']}{m1['month_str']}FUT")
        mcx_symbols.append(f"MCX:{metal}{m2['year_str']}{m2['month_str']}FUT")
        mcx_symbols.append(f"MCX:{metal}{m3['year_str']}{m3['month_str']}FUT")

    try:
        mcx_quotes = kite.quote(mcx_symbols)
        spread_data = []

        for metal in MCX_COMMODITIES:
            # Construct combinations: (M1, M2 - 1mo gap), (M1, M3 - 2mo gap), (M2, M3 - 1mo gap)
            pairs = [
                (m1, m2, "1 Mo."),
                (m1, m3, "2 Mo."),
                (m2, m3, "1 Mo.")
            ]
            
            for leg1, leg2, gap_label in pairs:
                leg1_name = f"{metal}{leg1['year_str']}{leg1['month_str']}FUT"
                leg2_name = f"{metal}{leg2['year_str']}{leg2['month_str']}FUT"
                
                q1 = mcx_quotes.get(f"MCX:{leg1_name}")
                q2 = mcx_quotes.get(f"MCX:{leg2_name}")

                if q1 and q2 and q1["last_price"] > 0 and q2["last_price"] > 0:
                    p1 = q1["last_price"]
                    p2 = q2["last_price"]
                    
                    lot_size = mcx_lot_sizes.get(leg1_name, 1)
                    total_capital_req = (p1 * lot_size) * 0.10  
                    
                    # Reverse Arbitrage Logic
                    action = "Buy Near, Short Far" if p2 >= p1 else "Short Near, Buy Far"
                    
                    # Contract name assignments for display
                    if p2 >= p1:
                        buy_leg = leg1['month_str']
                        sell_leg = leg2['month_str']
                    else:
                        buy_leg = leg2['month_str']
                        sell_leg = leg1['month_str']

                    abs_spread = abs(p2 - p1)
                    gross_profit, total_taxes, net_profit = calculate_mcx_spread_net_profit(p1, p2, lot_size)

                    # Days held = DTE of the near leg
                    days_held = max(leg1['dte'], 1)
                    annualized_yield = ((abs_spread / p1) * (365 / days_held)) * 100
                    rotc_yield = ((net_profit / total_capital_req) * (365 / days_held)) * 100

                    if net_profit <= 0:
                        status_tag = "Loss Making (Monitor)"
                    elif annualized_yield >= min_mcx_yield:
                        status_tag = "🔥 TARGET HIT"
                    else:
                        status_tag = "Normal"

                    if show_filtered_stocks or status_tag == "🔥 TARGET HIT":
                        spread_data.append({
                            "Commodity": metal,
                            "Action": action,
                            "Buy Leg": f"{buy_leg} FUT",
                            "Sell Leg": f"{sell_leg} FUT",
                            "Gap": gap_label,
                            "Leg 1 Price": f"₹{p1:.2f}",
                            "Leg 2 Price": f"₹{p2:.2f}",
                            "Margin": f"₹{total_capital_req:,.0f}",
                            "Spread": f"₹{abs_spread:.2f}",
                            "Yield (% p.a.)": round(annualized_yield, 2),
                            "ROTC (% p.a.)": round(rotc_yield, 2),
                            "Gross Profit": f"₹{gross_profit:,.0f}",
                            "Taxes": f"₹{total_taxes:,.0f}",
                            "Net Profit": net_profit,
                            "Status": status_tag
                        })

        df_spread = pd.DataFrame(spread_data)
        
        if not df_spread.empty:
            df_spread['is_rejected'] = df_spread['Status'].str.contains("Loss Making")
            df_spread = df_spread.sort_values(by=["is_rejected", "Yield (% p.a.)"], ascending=[True, False]).drop(columns=['is_rejected']).reset_index(drop=True)
            
            def highlight_spread(row):
                if row["Status"] == "🔥 TARGET HIT": return ['background-color: #3b2d18; color: #ffd700'] * len(row)
                elif row["Status"] == "Loss Making (Monitor)": return ['color: #ff6666'] * len(row)
                return [''] * len(row)

            st.dataframe(df_spread.style.apply(highlight_spread, axis=1), use_container_width=True)
        else:
            st.info("No MCX spreads available.")

    except Exception as e:
        st.error(f"Error fetching MCX data: {e}")

# ------------------------------------------
# TAB 3: COST SHEET & DOCUMENTATION
# ------------------------------------------
with tab3:
    st.markdown("""
    ### 📖 Desk A: Trading Cost Sheet & Execution Logic
    
    This documentation outlines the mathematical assumptions and precise regulatory taxation schedules programmed into the scanner to calculate true Net Profit across multi-month curves.
    
    ---

    #### 1. Curve Execution Strategy
    
    *   **Equity Curve Constraints:** The scanner tracks arbitrage opportunities 1, 2, and 3 months into the future. Because liquidity drops significantly in far-month contracts, **Month 3 trades are strictly restricted to the Top 100 most liquid F&O stocks** (e.g., Reliance, HDFC, Infosys) to prevent execution slippage.
    *   **MCX Curve Constraints:** The scanner looks at near, next, and far month combinations. Gold and Silver often skip months natively on MCX (bi-monthly cycles). The system dynamically evaluates Contango and Backwardation to explicitly issue the correct Buy and Sell leg assignments.
    *   **Capital Allocation (ROTC):** 
        *   *Equity:* Requires 100% upfront capital for the cash delivery leg, plus an assumed ~20% SPAN/Exposure margin for the short future leg.
        *   *Commodity:* Assumes exchange-mandated calendar spread margin benefits, requiring roughly ~10% of the near contract's value.

    ---

    #### 2. Net Profit Calculation Formulas
    
    **Equity Net Profit (Cash vs Future)**
    $$ \\text{Net Profit} = [(\\text{Future}_{Entry} - \\text{Cash}_{Entry}) \\times \\text{Lot Size}] - (\\text{Total Cash Charges} + \\text{Total Future Charges}) $$

    **Commodities Net Profit (Calendar Spread)**
    $$ \\text{Net Profit} = [|\\text{Far}_{Entry} - \\text{Near}_{Entry}| \\times \\text{Lot Size}] - (\\text{Total MCX Charges}) $$

    ---

    #### 3. Brokerage & Regulatory Cost Sheet (Zerodha 2026)

    | Charge Type | Equity Cash (Delivery) | Equity Futures (NFO) | Commodity Futures (MCX) |
    | :--- | :--- | :--- | :--- |
    | **Brokerage** | ₹0 | ₹40 (Round Trip) | ₹80 (4-Leg Calendar Round Trip) |
    | **STT / CTT** | 0.1% (Buy & Sell) | 0.02% (Sell Side Only) | 0.01% CTT (Sell Side Only) |
    | **Exchange Txn** | 0.00307% | 0.00183% | ~0.0021% |
    | **Stamp Duty** | 0.015% (Buy Side Only) | 0.002% (Buy Side Only) | 0.002% (Buy Side Only) |
    | **SEBI Charges** | ₹10 per Crore | ₹10 per Crore | ₹10 per Crore |
    | **DP Charge** | ₹15.93 (Flat, on exit) | Not Applicable | Not Applicable |
    | **GST** | 18% on (Brokerage + SEBI + Txn) | 18% on (Brokerage + SEBI + Txn) | 18% on (Brokerage + SEBI + Txn) |
    """)

time.sleep(refresh_interval)
st.rerun()
