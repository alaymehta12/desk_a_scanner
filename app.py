import streamlit as st
import pandas as pd
from datetime import datetime, date
import calendar
from kiteconnect import KiteConnect
import requests
import time
import json
import uuid
import io

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
# 2. SIDEBAR
# ==========================================
st.sidebar.header("🔑 Zerodha API Authentication")
DEFAULT_API_KEY = "5pq7uvvfukm67tzt"
api_key = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
access_token = st.sidebar.text_input(
    "Daily Access Token", type="password",
    help="Paste your active daily session access token here."
)

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Thresholds")
min_arb_yield = st.sidebar.slider(
    "Min Cash-Futures Yield (% p.a.)", min_value=2.0, max_value=20.0, value=6.0, step=0.5
)
min_dte_cutoff = st.sidebar.slider(
    "Min DTE Before Auto-Rollover (Days)", min_value=1, max_value=10, value=4
)

st.sidebar.markdown("---")
st.sidebar.header("⛏️ MCX Specific Filters")
min_mcx_yield = st.sidebar.slider(
    "Min MCX Spread Yield (% p.a.)", min_value=2.0, max_value=20.0, value=6.0, step=0.5
)

st.sidebar.markdown("---")
st.sidebar.header("🛠 Display")
show_all_trades = st.sidebar.checkbox("Show All Trades (incl. below-target)", value=True)

st.sidebar.markdown("---")
st.sidebar.header("🔔 Telegram Alerts")
enable_alerts = st.sidebar.checkbox("Enable Telegram Push Alerts", value=False)
telegram_bot_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID")
refresh_interval = st.sidebar.slider(
    "Auto-Refresh Rate (Seconds)", min_value=10, max_value=120, value=30,
    help="Keep ≥30s on Streamlit Cloud to avoid resource limits."
)

# ==========================================
# 3. EXPIRY & CONTRACT HELPERS
# ==========================================

def get_last_thursday(year, month):
    _, last_day = calendar.monthrange(year, month)
    dt = date(year, month, last_day)
    offset = (dt.weekday() - 3) % 7
    return date(year, month, last_day - offset)


def get_mcx_expiry(commodity, year, month):
    """
    NatGas: last business day of the month BEFORE the contract month.
    All others: last business day of the contract month.
    """
    if commodity == "NATURALGAS":
        if month == 1:
            ref_year, ref_month = year - 1, 12
        else:
            ref_year, ref_month = year, month - 1
        _, last_day = calendar.monthrange(ref_year, ref_month)
        d = date(ref_year, ref_month, last_day)
        while d.weekday() > 4:
            from datetime import timedelta
            d -= timedelta(days=1)
        return d
    else:
        _, last_day = calendar.monthrange(year, month)
        d = date(year, month, last_day)
        while d.weekday() > 4:
            from datetime import timedelta
            d -= timedelta(days=1)
        return d


def get_target_month(base_date, month_offset):
    m = base_date.month + month_offset
    y = base_date.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    expiry = get_last_thursday(y, m)
    return {
        "year": y,
        "month": m,
        "year_str": str(y)[-2:],
        "month_str": datetime(y, m, 1).strftime("%b").upper(),
        "expiry_date": expiry,
        "dte": (expiry - today).days
    }


now = datetime.now()
today = now.date()
curr_month_expiry = get_last_thursday(now.year, now.month)
curr_dte = (curr_month_expiry - today).days

if curr_dte <= min_dte_cutoff:
    base_month_offset = 1
    st.info(
        f"📅 **Auto-Rollover Active:** Current month expires in {curr_dte} days. "
        "Base scanning shifted to next month."
    )
else:
    base_month_offset = 0

m1 = get_target_month(now, base_month_offset)
m2 = get_target_month(now, base_month_offset + 1)
m3 = get_target_month(now, base_month_offset + 2)

# ==========================================
# 4. INSTRUMENT UNIVERSE
# ==========================================

MCX_PHYSICAL_DELIVERY = {
    "GOLD", "SILVER", "GOLDGUINEA", "GOLDPETAL", "SILVERMIC", "MENTHAOIL"
}

MCX_COMMODITIES = [
    "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
    "GOLD", "SILVER", "CRUDEOILM", "NATURALGAS", "MENTHAOIL",
    "GOLDGUINEA", "GOLDPETAL", "SILVERMIC"
]

TOP_100_STOCKS = sorted([
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "LT", "SBIN", "BHARTIARTL",
    "BAJFINANCE", "KOTAKBANK", "AXISBANK", "ASIANPAINT", "HINDUNILVR", "MARUTI", "SUNPHARMA",
    "TITAN", "TATASTEEL", "ULTRACEMCO", "POWERGRID", "NTPC", "TATAMOTORS", "M&M", "JSWSTEEL",
    "GRASIM", "HCLTECH", "TECHM", "WIPRO", "ADANIENT", "ADANIPORTS", "TATACONSUMER",
    "BRITANNIA", "EICHERMOT", "DIVISLAB", "DRREDDY", "CIPLA", "HEROMOTOCO", "APOLLOHOSP",
    "HDFCLIFE", "SBILIFE", "INDUSINDBK", "BPCL", "HINDPETRO", "IOC", "BEL", "HAL", "VEDL",
    "BHEL", "RECLTD", "PFC", "DLF", "TRENT", "GAIL", "SIEMENS", "ABB", "CANBK", "BANKBARODA",
    "CHOLAFIN", "SHRIRAMFIN", "TATACOMM", "COALINDIA", "TVSMOTOR", "AMBUJACEM", "SHREECEM",
    "BOSCHLTD", "INDHOTEL", "PIDILITIND", "HAVELLS", "PNB", "ICICIPRULI", "ICICIGI",
    "GODREJCP", "DABUR", "COLPAL", "MARICO", "MGL", "IGL", "PETRONET", "LTIM", "OBEROIRLTY",
    "GODREJPROP", "AUBANK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "MUTHOOTFIN",
    "MANAPPURAM", "SAIL", "NMDC", "NATIONALUM", "HINDALCO", "HINDCOPPER", "JINDALSTEL",
    "TATACHEM", "DEEPAKNTR", "PIIND", "UPL", "AUROPHARMA", "LUPIN", "TORNTPHARM"
])

CASH_FUT_STOCKS = sorted(set(TOP_100_STOCKS + [
    "AARTIIND", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ALKEM", "APOLLOTYRE", "ASHOKLEY",
    "ASTRAL", "ATUL", "BAJAJ-AUTO", "BAJAJFINSV", "BALKRISIND", "BALRAMCHIN", "BATAINDIA",
    "BERGEPAINT", "BHARATFORG", "BIOCON", "BSE", "CANFINHOME", "CHAMBLFERT", "COFORGE",
    "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DALBHARAT", "DIXON", "ESCORTS",
    "EXIDEIND", "GLENMARK", "GMRINFRA", "GNFC", "GRANULES", "GUJGASLTD", "HDFCAMC", "IDEA",
    "IEX", "INDIACEM", "INDIAMART", "INDIGO", "IPCALAB", "IRCTC", "JIOFIN", "JUBLFOOD",
    "L&TFH", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LTTS", "M&MFIN", "MCX", "METROPOLIS",
    "MFSL", "MOTHERSON", "MPHASIS", "MRF", "NAUKRI", "NAVINFLUOR", "NESTLEIND", "OFSS",
    "ONGC", "PAGEIND", "PEL", "PERSISTENT", "POLYCAB", "PVRINOX", "RAMCOCEM", "RBLBANK",
    "SBICARD", "SRF", "SUNTV", "SYNGENE", "TATAPOWER", "UBL", "VOLTAS", "ZEEL", "ZYDUSLIFE"
]))

# ==========================================
# 5. HELPER FUNCTIONS
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


@st.cache_data(ttl=3600)
def fetch_fo_ban_list():
    url = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nseindia.com/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and len(resp.text.strip()) > 30:
            lines = resp.text.strip().splitlines()
            banned = set()
            for line in lines[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    symbol = parts[1].strip().upper()
                    if symbol:
                        banned.add(symbol)
            return banned
        return set()
    except Exception:
        return set()


def initialize_kite(key, token):
    try:
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        kite.profile()
        return kite
    except Exception as e:
        st.error(f"❌ Kite Connection Error: {e}")
        return None


@st.cache_data(ttl=86400)
def get_lot_sizes(_kite, exchange):
    try:
        instruments = _kite.instruments(exchange)
        return {item["tradingsymbol"]: item["lot_size"] for item in instruments}
    except Exception:
        return {}


def calculate_equity_arb_charges(cash_price, fut_price, qty):
    cash_buy_val = cash_price * qty
    cash_sell_val = fut_price * qty
    cash_turnover = cash_buy_val + cash_sell_val
    cash_stt = (cash_buy_val * 0.001) + (cash_sell_val * 0.001)
    cash_exc_txn = cash_turnover * 0.0000307
    cash_stamp = cash_buy_val * 0.00015
    cash_sebi = cash_turnover * 0.000001
    cash_gst = (cash_exc_txn + cash_sebi) * 0.18
    cash_dp = 15.93
    total_cash = cash_stt + cash_exc_txn + cash_stamp + cash_sebi + cash_gst + cash_dp

    fut_sell_val = fut_price * qty
    fut_buy_val = fut_price * qty
    fut_turnover = fut_sell_val + fut_buy_val
    fut_brokerage = 40.0
    fut_stt = fut_sell_val * 0.0002
    fut_exc_txn = fut_turnover * 0.0000183
    fut_stamp = fut_buy_val * 0.00002
    fut_sebi = fut_turnover * 0.000001
    fut_gst = (fut_brokerage + fut_exc_txn + fut_sebi) * 0.18
    total_fut = fut_brokerage + fut_stt + fut_exc_txn + fut_stamp + fut_sebi + fut_gst

    gross_profit = (fut_price - cash_price) * qty
    total_charges = total_cash + total_fut
    net_profit = gross_profit - total_charges
    return round(gross_profit, 2), round(total_charges, 2), round(net_profit, 2)


def calculate_mcx_spread_charges(near_price, far_price, qty):
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
# 6. TRADE LOG — STATE MANAGEMENT
# Trades persist within the browser session via st.session_state.
# Users download a JSON backup and can re-upload it to restore.
# ==========================================

def init_trade_log():
    if "trade_log" not in st.session_state:
        st.session_state.trade_log = []


def add_trade(trade: dict):
    trade["id"] = str(uuid.uuid4())[:8]
    trade["entry_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    trade["status"] = "OPEN"
    trade["exit_spread"] = None
    trade["exit_date"] = None
    trade["realised_pnl"] = None
    st.session_state.trade_log.append(trade)


def close_trade(trade_id: str, exit_spread: float):
    for t in st.session_state.trade_log:
        if t["id"] == trade_id:
            t["status"] = "CLOSED"
            t["exit_spread"] = exit_spread
            t["exit_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry_spread = t["entry_spread"]
            qty = t["lot_size"]
            # Realised P&L = (entry spread - exit spread) * qty - charges
            # For a spread trade: you SOLD the spread at entry_spread, buy it back at exit_spread
            # Profit if exit_spread < entry_spread (spread narrowed)
            raw_pnl = (entry_spread - exit_spread) * qty
            charges = t.get("entry_charges", 0) + t.get("exit_charges", 0)
            t["realised_pnl"] = round(raw_pnl - charges, 2)
            break


def delete_trade(trade_id: str):
    st.session_state.trade_log = [
        t for t in st.session_state.trade_log if t["id"] != trade_id
    ]


def get_live_spread(kite_instance, trade):
    """Fetch current live spread for an open trade from Kite."""
    try:
        trade_type = trade.get("trade_type", "")
        buy_sym = trade.get("buy_contract", "")
        sell_sym = trade.get("sell_contract", "")
        if not buy_sym or not sell_sym:
            return None
        q = kite_instance.quote([buy_sym, sell_sym])
        buy_price = q.get(buy_sym, {}).get("last_price", 0)
        sell_price = q.get(sell_sym, {}).get("last_price", 0)
        if buy_price > 0 and sell_price > 0:
            return round(abs(sell_price - buy_price), 2)
        return None
    except Exception:
        return None


def export_trades_json():
    return json.dumps(st.session_state.trade_log, indent=2, default=str)


def export_trades_csv():
    if not st.session_state.trade_log:
        return ""
    df = pd.DataFrame(st.session_state.trade_log)
    return df.to_csv(index=False)


# ==========================================
# 7. GATE: ACCESS TOKEN REQUIRED
# ==========================================
if not access_token:
    st.warning("👈 Please enter today's active Daily Access Token in the sidebar to load the scanner.")
    st.stop()

kite = initialize_kite(api_key, access_token)
if not kite:
    st.stop()

nfo_lot_sizes = get_lot_sizes(kite, "NFO")
mcx_lot_sizes = get_lot_sizes(kite, "MCX")
fo_ban_list = fetch_fo_ban_list()
init_trade_log()

with st.sidebar:
    st.markdown("---")
    st.header("🚫 F&O Ban List")
    if fo_ban_list:
        st.error(f"**{len(fo_ban_list)} stock(s) banned today:**\n" + ", ".join(sorted(fo_ban_list)))
    else:
        st.success("✅ No stocks in F&O ban today")

# ==========================================
# 8. TABS
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Equity Curve Arbitrage",
    "⛏️ MCX Curve Spreads",
    "📋 Trade Log",
    "📖 Cost Sheet & Docs"
])

# ==========================================
# TAB 1: EQUITY CASH-FUTURES ARBITRAGE
# ==========================================
with tab1:
    st.subheader(
        f"Equity Arbitrage Curve Scanner — "
        f"{m1['month_str']} to {m3['month_str']} | {len(CASH_FUT_STOCKS)} Stocks"
    )

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
            if not cash_q:
                continue
            cash_price = cash_q["last_price"]
            if cash_price <= 0:
                continue

            curve_months = [(1, m1), (2, m2)]
            if stock in TOP_100_STOCKS:
                curve_months.append((3, m3))

            for month_gap, m_data in curve_months:
                fut_contract_name = f"{stock}{m_data['year_str']}{m_data['month_str']}FUT"
                fut_sym = f"NFO:{fut_contract_name}"
                fut_q = quotes.get(fut_sym)
                if not fut_q or fut_q["last_price"] <= 0:
                    continue

                fut_price = fut_q["last_price"]
                lot_size = nfo_lot_sizes.get(fut_contract_name, 1000)
                cash_outlay = cash_price * lot_size
                fut_margin = (fut_price * lot_size) * 0.20
                total_capital_req = cash_outlay + fut_margin

                gross_profit, total_taxes, net_profit = calculate_equity_arb_charges(
                    cash_price, fut_price, lot_size
                )
                if net_profit <= 0:
                    continue

                abs_spread = fut_price - cash_price
                annualized_yield = ((abs_spread / cash_price) * (365 / max(m_data['dte'], 1))) * 100
                rotc_yield = ((net_profit / total_capital_req) * (365 / max(m_data['dte'], 1))) * 100
                is_banned = stock in fo_ban_list

                if is_banned:
                    status_tag = "🚫 F&O BAN — Cannot Enter"
                elif annualized_yield > 25.0:
                    status_tag = "⚠️ Corporate Action Check"
                elif annualized_yield >= min_arb_yield:
                    status_tag = "🔥 TARGET HIT"
                else:
                    status_tag = "Normal"

                if status_tag in ("🔥 TARGET HIT", "🚫 F&O BAN — Cannot Enter",
                                  "⚠️ Corporate Action Check") or show_all_trades:
                    arb_data.append({
                        "Symbol": stock,
                        "Buy Leg": "NSE Cash",
                        "Sell Leg": f"{m_data['month_str']} FUT",
                        "Months Out": f"{month_gap} Mo.",
                        "DTE": m_data["dte"],
                        "Cash Price (₹)": f"{cash_price:.2f}",
                        "Future Price (₹)": f"{fut_price:.2f}",
                        "Lot Size": lot_size,
                        "Capital Req (₹)": f"{total_capital_req:,.0f}",
                        "Spread (₹)": round(abs_spread, 2),
                        "Yield % p.a.": round(annualized_yield, 2),
                        "ROTC % p.a.": round(rotc_yield, 2),
                        "Gross Profit (₹)": gross_profit,
                        "Charges (₹)": total_taxes,
                        "Net Profit (₹)": net_profit,
                        "Status": status_tag
                    })

                if enable_alerts and status_tag == "🔥 TARGET HIT":
                    msg = (
                        f"🚨 *ARB ALERT: {stock}*\n"
                        f"Leg: {m_data['month_str']} FUT ({month_gap} Mo.)\n"
                        f"Yield: {annualized_yield:.2f}% p.a. | Net: ₹{net_profit:,.0f}"
                    )
                    send_telegram_alert(msg, telegram_bot_token, telegram_chat_id)

        df_arb = pd.DataFrame(arb_data)

        if not df_arb.empty:
            priority = {"🔥 TARGET HIT": 0, "⚠️ Corporate Action Check": 1,
                        "Normal": 2, "🚫 F&O BAN — Cannot Enter": 3}
            df_arb["_sort"] = df_arb["Status"].map(priority).fillna(2)
            df_arb = df_arb.sort_values(
                by=["_sort", "ROTC % p.a."], ascending=[True, False]
            ).drop(columns=["_sort"]).reset_index(drop=True)

            def highlight_arb(row):
                if row["Status"] == "🔥 TARGET HIT":
                    return ["background-color: #1e3d2f; color: #7cfc00"] * len(row)
                elif row["Status"] == "⚠️ Corporate Action Check":
                    return ["background-color: #4a3800; color: #ffcc00"] * len(row)
                elif row["Status"] == "🚫 F&O BAN — Cannot Enter":
                    return ["background-color: #3d0000; color: #ff6666"] * len(row)
                return [""] * len(row)

            st.dataframe(df_arb.style.apply(highlight_arb, axis=1), use_container_width=True)
        else:
            st.info("No positive-yield arbitrage opportunities found on the curve right now.")

        st.markdown("---")
        st.markdown("### 🏷 Status Legend — Equity")
        st.caption("""
        🔥 **TARGET HIT** — Profitable net of all taxes, yield above your target. Entry recommended.
        ⚠️ **Corporate Action Check** — Yield >25% p.a. A dividend or bonus is likely embedded. Verify NSE corporate actions before entering.
        **Normal** — Profitable but below your yield target. Monitor.
        🚫 **F&O BAN** — Cannot open fresh futures positions today. Skip entirely.
        """)

    except Exception as e:
        st.error(f"Error processing Equity Curve data: {e}")

# ==========================================
# TAB 2: MCX COMMODITY CALENDAR SPREADS
# ==========================================
with tab2:
    st.subheader("MCX Commodity Multi-Month Curve Scanner (M1×M2, M1×M3, M2×M3)")

    mcx_symbols = []
    for metal in MCX_COMMODITIES:
        mcx_symbols.append(f"MCX:{metal}{m1['year_str']}{m1['month_str']}FUT")
        mcx_symbols.append(f"MCX:{metal}{m2['year_str']}{m2['month_str']}FUT")
        mcx_symbols.append(f"MCX:{metal}{m3['year_str']}{m3['month_str']}FUT")

    try:
        mcx_quotes = kite.quote(mcx_symbols)
        spread_data = []

        for metal in MCX_COMMODITIES:
            is_physical = metal in MCX_PHYSICAL_DELIVERY
            m1_expiry = get_mcx_expiry(metal, m1['year'], m1['month'])
            m2_expiry = get_mcx_expiry(metal, m2['year'], m2['month'])
            m3_expiry = get_mcx_expiry(metal, m3['year'], m3['month'])
            mcx_dte = {
                "m1": max((m1_expiry - today).days, 1),
                "m2": max((m2_expiry - today).days, 1),
                "m3": max((m3_expiry - today).days, 1),
            }

            pairs = [
                (m1, m2, "1 Mo.", "m1"),
                (m1, m3, "2 Mo.", "m1"),
                (m2, m3, "1 Mo.", "m2"),
            ]

            for leg1_m, leg2_m, gap_label, near_key in pairs:
                leg1_name = f"{metal}{leg1_m['year_str']}{leg1_m['month_str']}FUT"
                leg2_name = f"{metal}{leg2_m['year_str']}{leg2_m['month_str']}FUT"
                q1 = mcx_quotes.get(f"MCX:{leg1_name}")
                q2 = mcx_quotes.get(f"MCX:{leg2_name}")
                if not (q1 and q2 and q1["last_price"] > 0 and q2["last_price"] > 0):
                    continue

                p1 = q1["last_price"]
                p2 = q2["last_price"]
                lot_size = mcx_lot_sizes.get(leg1_name, 1)
                total_capital_req = (p1 * lot_size) * 0.10

                if p2 >= p1:
                    action = "Buy Near, Short Far"
                    buy_leg = leg1_m["month_str"]
                    sell_leg = leg2_m["month_str"]
                else:
                    action = "Short Near, Buy Far"
                    buy_leg = leg2_m["month_str"]
                    sell_leg = leg1_m["month_str"]

                abs_spread = abs(p2 - p1)
                gross_profit, total_taxes, net_profit = calculate_mcx_spread_charges(p1, p2, lot_size)
                days_held = mcx_dte[near_key]
                annualized_yield = ((abs_spread / p1) * (365 / days_held)) * 100
                rotc_yield = ((net_profit / total_capital_req) * (365 / days_held)) * 100

                tender_flag = is_physical and days_held <= 7
                tender_str = " ⚠️ EXIT NOW — Tender Period" if tender_flag else ""

                if net_profit <= 0:
                    status_tag = f"Loss Making (Monitor){tender_str}"
                elif annualized_yield >= min_mcx_yield:
                    status_tag = f"🔥 TARGET HIT{tender_str}"
                else:
                    status_tag = f"Normal{tender_str}"

                if show_all_trades or "🔥 TARGET HIT" in status_tag:
                    spread_data.append({
                        "Commodity": metal,
                        "Action": action,
                        "Buy Leg": f"{buy_leg} FUT",
                        "Sell Leg": f"{sell_leg} FUT",
                        "Gap": gap_label,
                        "Days Held": days_held,
                        "Near Price (₹)": f"{p1:.2f}",
                        "Far Price (₹)": f"{p2:.2f}",
                        "Lot Size": lot_size,
                        "Margin (₹)": f"{total_capital_req:,.0f}",
                        "Spread (₹)": round(abs_spread, 2),
                        "Yield % p.a.": round(annualized_yield, 2),
                        "ROTC % p.a.": round(rotc_yield, 2),
                        "Gross Profit (₹)": gross_profit,
                        "Charges (₹)": total_taxes,
                        "Net Profit (₹)": net_profit,
                        "Status": status_tag
                    })

                if enable_alerts and "🔥 TARGET HIT" in status_tag and net_profit > 0:
                    msg = (
                        f"🚨 *MCX ALERT: {metal}*\n"
                        f"{action} | Gap: {gap_label}\n"
                        f"Net: ₹{net_profit:,.0f} | ROTC: {rotc_yield:.1f}% p.a."
                    )
                    send_telegram_alert(msg, telegram_bot_token, telegram_chat_id)

        df_spread = pd.DataFrame(spread_data)

        if not df_spread.empty:
            df_spread["_loss"] = df_spread["Net Profit (₹)"] < 0
            df_spread = df_spread.sort_values(
                by=["_loss", "ROTC % p.a."], ascending=[True, False]
            ).drop(columns=["_loss"]).reset_index(drop=True)

            def highlight_spread(row):
                if "EXIT NOW" in row["Status"]:
                    return ["background-color: #5c0000; color: #ff4444"] * len(row)
                elif "🔥 TARGET HIT" in row["Status"]:
                    return ["background-color: #3b2d18; color: #ffd700"] * len(row)
                elif "Loss Making" in row["Status"]:
                    return ["color: #ff6666"] * len(row)
                return [""] * len(row)

            st.dataframe(df_spread.style.apply(highlight_spread, axis=1), use_container_width=True)
        else:
            st.info("No MCX spread data available.")

        st.markdown("---")
        st.markdown("### 🏷 Status Legend — MCX")
        st.caption("""
        🔥 **TARGET HIT** — Profitable net of all taxes, yield above your MCX target.
        **Normal** — Profitable but yield below target. Monitor.
        **Loss Making (Monitor)** — Spread too narrow to cover charges. Watch for widening.
        ⚠️ **EXIT NOW — Tender Period** — Physical delivery contract within 7 days of near-leg expiry. Exit both legs immediately.
        """)
        st.markdown("**Physical delivery contracts (exit ≥5 days before near expiry):** GOLD · SILVER · GOLDGUINEA · GOLDPETAL · SILVERMIC · MENTHAOIL")

    except Exception as e:
        st.error(f"Error fetching MCX data: {e}")

# ==========================================
# TAB 3: TRADE LOG
# ==========================================
with tab3:
    st.subheader("📋 Trade Log — Project Kavya")
    st.caption("All trades are stored in your browser session. Download a backup after each session to preserve your records.")

    # ── Summary metrics row ──────────────────────────────────────
    open_trades = [t for t in st.session_state.trade_log if t["status"] == "OPEN"]
    closed_trades = [t for t in st.session_state.trade_log if t["status"] == "CLOSED"]
    total_realised = sum(t.get("realised_pnl") or 0 for t in closed_trades)
    total_locked = sum(t.get("locked_net_profit") or 0 for t in open_trades)
    total_capital_at_risk = sum(t.get("capital_deployed") or 0 for t in open_trades)

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Open Trades", len(open_trades))
    col_b.metric("Closed Trades", len(closed_trades))
    col_c.metric(
        "Total Realised P&L",
        f"₹{total_realised:,.0f}",
        delta=None
    )
    col_d.metric(
        "Locked-In Profit (Open)",
        f"₹{total_locked:,.0f}",
        help="Sum of net profit locked at entry across all open trades."
    )

    st.markdown("---")

    # ── Live MTM refresh for open trades ─────────────────────────
    if open_trades:
        with st.expander("📡 Live MTM — Open Trades", expanded=True):
            mtm_data = []
            for t in open_trades:
                live_spread = get_live_spread(kite, t)
                entry_spread = t.get("entry_spread", 0)
                lot_size = t.get("lot_size", 1)
                locked_np = t.get("locked_net_profit", 0)

                if live_spread is not None:
                    spread_change = entry_spread - live_spread  # positive = narrowing = good
                    live_pnl = round(spread_change * lot_size, 2)
                    # DTE countdown
                    expiry_str = t.get("near_expiry", "")
                    try:
                        expiry_d = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                        dte_remaining = (expiry_d - today).days
                    except Exception:
                        dte_remaining = "—"

                    pnl_vs_locked = round(live_pnl - locked_np, 2)
                    mtm_data.append({
                        "ID": t["id"],
                        "Instrument": t.get("instrument", ""),
                        "Trade Type": t.get("trade_type", ""),
                        "Buy Leg": t.get("buy_contract_display", ""),
                        "Sell Leg": t.get("sell_contract_display", ""),
                        "Entry Spread (₹)": entry_spread,
                        "Live Spread (₹)": live_spread,
                        "Δ Spread (₹)": round(entry_spread - live_spread, 2),
                        "Live MTM P&L (₹)": live_pnl,
                        "Locked Net Profit (₹)": locked_np,
                        "Vs Locked (₹)": pnl_vs_locked,
                        "DTE Remaining": dte_remaining,
                        "Capital Deployed (₹)": t.get("capital_deployed", 0),
                        "Entry Date": t.get("entry_date", ""),
                    })
                else:
                    mtm_data.append({
                        "ID": t["id"],
                        "Instrument": t.get("instrument", ""),
                        "Trade Type": t.get("trade_type", ""),
                        "Buy Leg": t.get("buy_contract_display", ""),
                        "Sell Leg": t.get("sell_contract_display", ""),
                        "Entry Spread (₹)": entry_spread,
                        "Live Spread (₹)": "—",
                        "Δ Spread (₹)": "—",
                        "Live MTM P&L (₹)": "—",
                        "Locked Net Profit (₹)": locked_np,
                        "Vs Locked (₹)": "—",
                        "DTE Remaining": "—",
                        "Capital Deployed (₹)": t.get("capital_deployed", 0),
                        "Entry Date": t.get("entry_date", ""),
                    })

            if mtm_data:
                df_mtm = pd.DataFrame(mtm_data)

                def highlight_mtm(row):
                    try:
                        delta = float(row["Vs Locked (₹)"])
                        if delta >= 0:
                            return ["background-color: #1e3d2f; color: #7cfc00"] * len(row)
                        else:
                            return ["background-color: #3d1a00; color: #ff9955"] * len(row)
                    except Exception:
                        return [""] * len(row)

                st.dataframe(df_mtm.style.apply(highlight_mtm, axis=1), use_container_width=True)

                # ── Tender period alerts on open physical contracts ──
                for t in open_trades:
                    if t.get("is_physical_delivery"):
                        expiry_str = t.get("near_expiry", "")
                        try:
                            expiry_d = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                            dte_rem = (expiry_d - today).days
                            if dte_rem <= 7:
                                st.error(
                                    f"🚨 **URGENT — EXIT {t.get('instrument', '')} NOW!** "
                                    f"Physical delivery contract. {dte_rem} days to near-leg expiry. "
                                    "Tender period begins in 5 trading days."
                                )
                        except Exception:
                            pass

    # ── Close a trade ─────────────────────────────────────────────
    if open_trades:
        st.markdown("---")
        st.markdown("#### 🔒 Close a Trade")
        close_col1, close_col2, close_col3 = st.columns([2, 2, 1])
        trade_ids = [f"{t['id']} — {t.get('instrument','')} {t.get('buy_contract_display','')}×{t.get('sell_contract_display','')}" for t in open_trades]
        selected_close = close_col1.selectbox("Select trade to close", trade_ids, key="close_select")
        exit_spread_input = close_col2.number_input(
            "Exit Spread (₹) — actual spread when you squared off",
            min_value=0.0, value=0.0, step=0.5, key="exit_spread_input"
        )
        if close_col3.button("✅ Mark Closed", key="btn_close"):
            trade_id_to_close = selected_close.split(" — ")[0]
            close_trade(trade_id_to_close, exit_spread_input)
            st.success(f"Trade {trade_id_to_close} marked as closed.")
            st.rerun()

    # ── Add new trade ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ➕ Log a New Trade")

    with st.form("new_trade_form", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        trade_type = fc1.selectbox(
            "Trade Type",
            ["MCX Calendar Spread", "Equity Cash-Futures Arb"],
            key="form_trade_type"
        )
        instrument = fc2.text_input(
            "Instrument / Symbol",
            placeholder="e.g. GOLDGUINEA or RELIANCE",
            key="form_instrument"
        )

        fc3, fc4 = st.columns(2)
        buy_contract_display = fc3.text_input(
            "Buy Leg Contract",
            placeholder="e.g. GOLDGUINEA26AUGFUT or NSE Cash",
            key="form_buy_display"
        )
        sell_contract_display = fc4.text_input(
            "Sell Leg Contract",
            placeholder="e.g. GOLDGUINEA26SEPFUT or RELIANCE26AUGFUT",
            key="form_sell_display"
        )

        fc5, fc6, fc7 = st.columns(3)
        buy_contract_kite = fc5.text_input(
            "Buy Leg Kite Symbol (for live MTM)",
            placeholder="e.g. MCX:GOLDGUINEA26AUGFUT",
            key="form_buy_kite"
        )
        sell_contract_kite = fc6.text_input(
            "Sell Leg Kite Symbol (for live MTM)",
            placeholder="e.g. MCX:GOLDGUINEA26SEPFUT",
            key="form_sell_kite"
        )
        lot_size = fc7.number_input("Lot Size", min_value=1, value=1, step=1, key="form_lot")

        fc8, fc9, fc10 = st.columns(3)
        entry_spread = fc8.number_input(
            "Entry Spread (₹) — Far minus Near at time of entry",
            min_value=0.0, value=0.0, step=0.5, key="form_spread"
        )
        locked_net_profit = fc9.number_input(
            "Locked Net Profit (₹) — from scanner",
            min_value=0.0, value=0.0, step=1.0, key="form_np"
        )
        capital_deployed = fc10.number_input(
            "Capital Deployed (₹) — margin or cash outlay",
            min_value=0.0, value=0.0, step=100.0, key="form_capital"
        )

        fc11, fc12, fc13 = st.columns(3)
        near_expiry = fc11.date_input(
            "Near Leg Expiry Date",
            value=m1["expiry_date"],
            key="form_expiry"
        )
        entry_charges = fc12.number_input(
            "Entry Charges (₹) — from scanner",
            min_value=0.0, value=0.0, step=1.0, key="form_charges"
        )
        is_physical = fc13.checkbox(
            "Physical Delivery Contract?",
            key="form_physical",
            help="Tick for Gold, Silver, GoldGuinea, GoldPetal, SilverMic, Mentha Oil"
        )

        notes = st.text_area(
            "Notes (optional)",
            placeholder="e.g. Entered at ₹265 spread, targeting ₹100 exit, contango",
            key="form_notes"
        )

        submitted = st.form_submit_button("➕ Add Trade to Log")

    if submitted:
        if not instrument or not buy_contract_display or not sell_contract_display:
            st.error("Please fill in Instrument, Buy Leg, and Sell Leg at minimum.")
        else:
            new_trade = {
                "trade_type": trade_type,
                "instrument": instrument.upper().strip(),
                "buy_contract_display": buy_contract_display.strip(),
                "sell_contract_display": sell_contract_display.strip(),
                "buy_contract": buy_contract_kite.strip(),
                "sell_contract": sell_contract_kite.strip(),
                "lot_size": int(lot_size),
                "entry_spread": float(entry_spread),
                "locked_net_profit": float(locked_net_profit),
                "capital_deployed": float(capital_deployed),
                "near_expiry": str(near_expiry),
                "entry_charges": float(entry_charges),
                "exit_charges": float(entry_charges),  # assume same for exit
                "is_physical_delivery": bool(is_physical),
                "notes": notes.strip(),
            }
            add_trade(new_trade)
            st.success(f"✅ Trade logged: {instrument.upper()} {buy_contract_display} × {sell_contract_display}")
            st.rerun()

    # ── Closed trades history ──────────────────────────────────────
    if closed_trades:
        st.markdown("---")
        st.markdown("#### 📜 Closed Trades History")
        df_closed = pd.DataFrame(closed_trades)
        display_cols = [c for c in [
            "id", "entry_date", "exit_date", "trade_type", "instrument",
            "buy_contract_display", "sell_contract_display",
            "entry_spread", "exit_spread", "lot_size",
            "locked_net_profit", "realised_pnl", "notes"
        ] if c in df_closed.columns]
        df_closed_display = df_closed[display_cols].copy()
        df_closed_display.columns = [c.replace("_", " ").title() for c in display_cols]

        def highlight_closed(row):
            try:
                pnl = float(row.get("Realised Pnl", 0))
                if pnl >= 0:
                    return ["background-color: #1e3d2f; color: #7cfc00"] * len(row)
                else:
                    return ["background-color: #3d0000; color: #ff6666"] * len(row)
            except Exception:
                return [""] * len(row)

        st.dataframe(df_closed_display.style.apply(highlight_closed, axis=1), use_container_width=True)

    # ── Delete a trade ─────────────────────────────────────────────
    if st.session_state.trade_log:
        st.markdown("---")
        with st.expander("🗑 Delete a Trade (use with care)"):
            all_ids = [
                f"{t['id']} — {t.get('instrument','')} [{t['status']}]"
                for t in st.session_state.trade_log
            ]
            del_select = st.selectbox("Select trade to delete", all_ids, key="del_select")
            if st.button("🗑 Delete Trade", key="btn_delete"):
                delete_trade(del_select.split(" — ")[0])
                st.warning("Trade deleted.")
                st.rerun()

    # ── Backup & Restore ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 💾 Backup & Restore")
    st.info(
        "**Important:** Trades are stored in your browser session only. "
        "Download a backup after each session. Upload it next time to restore your log."
    )

    bcol1, bcol2 = st.columns(2)

    with bcol1:
        st.markdown("**Download backup**")
        if st.session_state.trade_log:
            json_str = export_trades_json()
            st.download_button(
                label="⬇️ Download Trade Log (JSON)",
                data=json_str,
                file_name=f"kavya_trade_log_{today.strftime('%Y%m%d')}.json",
                mime="application/json",
                key="dl_json"
            )
            csv_str = export_trades_csv()
            st.download_button(
                label="⬇️ Download Trade Log (CSV)",
                data=csv_str,
                file_name=f"kavya_trade_log_{today.strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="dl_csv"
            )
        else:
            st.caption("No trades to download yet.")

    with bcol2:
        st.markdown("**Restore from backup**")
        uploaded = st.file_uploader(
            "Upload a previously downloaded JSON backup",
            type=["json"],
            key="upload_json"
        )
        if uploaded is not None:
            try:
                loaded = json.load(uploaded)
                if isinstance(loaded, list):
                    st.session_state.trade_log = loaded
                    st.success(f"✅ Restored {len(loaded)} trades from backup.")
                    st.rerun()
                else:
                    st.error("Invalid backup file format.")
            except Exception as ex:
                st.error(f"Could not read backup: {ex}")

# ==========================================
# TAB 4: COST SHEET & DOCUMENTATION
# ==========================================
with tab4:
    st.markdown("""
## 📖 Desk A — Trading Cost Sheet, Formulas & Execution Logic

---
### 1. Strategy Overview

**Equity Cash-Futures Arbitrage (NSE)**
Buy the underlying stock (CNC delivery) and short the futures contract simultaneously. NSE Clearing guarantees futures settle to cash price at expiry — fully delta-neutral, guaranteed convergence.

*Capital:* 100% stock value + ~20% SPAN/Exposure futures margin.

**MCX Calendar Spread**
Opposite positions in two different expiry months of the same commodity. Profit from spread convergence as near month approaches expiry. Works in contango (Buy Near, Short Far) and backwardation (Short Near, Buy Far). No physical commodity ownership needed.

*Capital:* ~10% of near-leg value (MCX spread margin benefit).

---
### 2. Net Profit Formulas

```
Equity:
  Gross Profit = (Futures Price − Cash Price) × Lot Size
  Net Profit   = Gross Profit − Total Regulatory Charges

MCX Spread:
  Gross Profit = |Far Price − Near Price| × Lot Size
  Net Profit   = Gross Profit − Total Regulatory Charges

Annualised Yield % p.a. = (Gross Profit / Entry Price) × (365 / DTE) × 100
ROTC % p.a.             = (Net Profit / Total Capital Deployed) × (365 / DTE) × 100

MTM P&L (open trade) = (Entry Spread − Live Spread) × Lot Size
```

---
### 3. Brokerage & Regulatory Cost Sheet (Zerodha 2026)

| Charge | Equity Cash (CNC) | Equity Futures (NFO) | Commodity (MCX) |
|:---|:---|:---|:---|
| **Brokerage** | ₹0 | ₹40 round-trip | ₹80 (4-leg calendar round-trip) |
| **STT / CTT** | 0.1% buy + 0.1% sell | 0.02% sell side only | 0.01% CTT on sell side only |
| **Exchange Txn** | 0.00307% | 0.00183% | 0.0021% |
| **Stamp Duty** | 0.015% on buy | 0.002% on buy | 0.002% on buy |
| **SEBI Charges** | ₹10/crore | ₹10/crore | ₹10/crore |
| **DP Charge** | ₹15.93 flat (demat exit) | N/A | N/A |
| **GST** | 18% on (Txn + SEBI) | 18% on (Brokerage + Txn + SEBI) | 18% on (Brokerage + Txn + SEBI) |

---
### 4. Curve Scanning Logic

**Equity:** M1 and M2 — full 180+ stock universe. M3 — Top 100 liquid stocks only.
Auto-rollover when current month DTE ≤ sidebar cutoff.

**MCX:** All 3 pairs: M1×M2 (1 month), M1×M3 (2 months), M2×M3 (1 month).
Direction auto-detected. NatGas uses its own expiry calendar (last business day of prior month).

**F&O Ban List:** Fetched live from NSE Clearing every session (cached 1 hour). Banned stocks blocked from entry.

---
### 5. Key Risk Rules

1. Never hold an equity arb through a corporate action (dividend, bonus, split).
2. Exit MCX physical delivery contracts ≥5 trading days before near-leg expiry (Gold, Silver, GoldGuinea, GoldPetal, SilverMic, Mentha Oil). Tender period = compulsory physical settlement + heavy penalty fees.
3. Maintain 2×–3× margin buffer in Zerodha Commodity segment against MTM swings.
4. MCX spreads can diverge. Set a hard stop: if spread expands to 1.5× entry, exit and take the loss.
5. NatGas has a different expiry calendar from all other MCX contracts — always verify.
""")

# ==========================================
# 9. AUTO-REFRESH
# ==========================================
time.sleep(refresh_interval)
st.rerun()
