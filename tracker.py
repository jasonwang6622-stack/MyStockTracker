import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from pyxirr import xirr
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. 網頁基本設定 & 密碼鎖
# ==========================================
st.set_page_config(page_title="所有人", page_icon="📈", layout="wide")
st.title("📈 所有人")

def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("🔒 請輸入密碼", type="password", on_change=lambda: st.session_state.update({"password_correct": st.session_state["password_input"] == st.secrets["password"]}), key="password_input")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 請輸入密碼", type="password", on_change=lambda: st.session_state.update({"password_correct": st.session_state["password_input"] == st.secrets["password"]}), key="password_input")
        st.error("❌ 密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. 連線 Google Sheets
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="工作表1", ttl=0)

# 確保基礎欄位存在 (新增了 Total_Amount 和 Unit_Cost)
expected_columns = ['id', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']
if df.empty or 'id' not in df.columns:
    df = pd.DataFrame(columns=expected_columns)

# ==========================================
# 3. 核心功能：抓取股價
# ==========================================
@st.cache_data(ttl=3600)
def get_current_price(symbol):
    symbol = str(symbol).strip().upper()
    search_list = [symbol]
    if "." not in symbol:
        search_list.extend([f"{symbol}.TW", f"{symbol}.TWO"])
    for s in search_list:
        try:
            history = yf.Ticker(s).history(period="2d")
            if not history.empty: return history['Close'].iloc[-1]
        except: continue
    return 0.0

# ==========================================
# 4. 側邊欄：智慧輸入表單
# ==========================================
st.sidebar.header("✍️ 新增交易紀錄")

# 帳戶與股票選單 (自動學習)
existing_accounts = sorted(df['Account'].dropna().unique().tolist()) if not df.empty else ["主要帳戶"]
acc_opt = st.sidebar.selectbox("👤 帳戶", existing_accounts + ["➕ 新增..."])
final_account = st.sidebar.text_input("新帳戶名稱") if acc_opt == "➕ 新增..." else acc_opt

existing_symbols = sorted(df['Symbol'].dropna().unique().tolist()) if not df.empty else ["2330.TW"]
sym_opt = st.sidebar.selectbox("🏷️ 股票 (可搜尋數字)", existing_symbols + ["➕ 新增..."])
final_symbol = st.sidebar.text_input("新代號 (.TW/.TWO)") if sym_opt == "➕ 新增..." else sym_opt

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_shares = st.number_input("🔢 股數", min_value=0, step=1, value=0)
    
    # 這裡改成輸入「總成交金額」
    f_total_raw = st.number_input("💰 總成交金額 (不含規費)", min_value=0.0, step=100.0, value=0.0)
    f_fee = st.number_input("🏦 手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 交易稅", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入 Google 試算表")
    
    if submitted and final_account and final_symbol:
        # 計算：成交價 = 總金額 / 股數
        calc_price = f_total_raw / f_shares if f_shares > 0 else 0
        
        # 計算：總支出/收入 (買入=金額+費, 賣出=金額-費-稅)
        if f_type == "Buy":
            total_amt = f_total_raw + f_fee
            unit_cost = total_amt / f_shares if f_shares > 0 else 0
        elif f_type == "Sell":
            total_amt = f_total_raw - f_fee - f_tax
            unit_cost = (f_total_raw / f_shares) if f_shares > 0 else 0 # 賣出時 unit_cost 紀錄純單價
        else: # 股利
            total_amt = f_total_raw
            unit_cost = f_total_raw
            
        new_data = pd.DataFrame([{
            'id': int(df['id'].max() + 1) if not df.empty else 1,
            'Account': final_account, 'Date': f_date.strftime("%Y-%m-%d"),
            'Type': f_type, 'Symbol': final_symbol.upper(),
            'Shares': f_shares, 'Price': round(calc_price, 2),
            'Fee': f_fee, 'Tax': f_tax, 
            'Total_Amount': round(total_amt, 0), 'Unit_Cost': round(unit_cost, 2)
        }])
        
        conn.update(worksheet="工作表1", data=pd.concat([df, new_data], ignore_index=True))
        st.sidebar.success("✅ 已紀錄！")
        st.rerun()

# ==========================================
# 5. 資料處理邏輯
# ==========================================
accounts_data = {}
if not df.empty:
    for _, row in df.iterrows():
        acc = row['Account']
        if acc not in accounts_data: accounts_data[acc] = {'inventory': {}, 'cash_flows': []}
        inv = accounts_data[acc]['inventory']
        sym, t_type, shares, total_amt = row['Symbol'], row['Type'], row['Shares'], row['Total_Amount']
        
        if sym not in inv: inv[sym] = {'shares': 0, 'total_cost': 0.0, 'realized_pnl': 0.0}
        
        if t_type == 'Buy':
            inv[sym]['shares'] += shares
            inv[sym]['total_cost'] += total_amt
            accounts_data[acc]['cash_flows'].append((row['Date'], -total_amt))
        elif t_type == 'Sell':
            if inv[sym]['shares'] > 0:
                avg_cost = inv[sym]['total_cost'] / inv[sym]['shares']
                inv[sym]['realized_pnl'] += (total_amt - (avg_cost * shares))
                inv[sym]['total_cost'] -= (avg_cost * shares)
                inv[sym]['shares'] -= shares
                accounts_data[acc]['cash_flows'].append((row['Date'], total_amt))
        elif t_type == 'Cash_Div':
            inv[sym]['realized_pnl'] += total_amt
            accounts_data[acc]['cash_flows'].append((row['Date'], total_amt))
        elif t_type == 'Stock_Div':
            inv[sym]['shares'] += shares

# ==========================================
# 6. 介面呈現
# ==========================================
acc_list = list(accounts_data.keys())
if not acc_list:
    st.info("請新增第一筆交易。")
    st.stop()

sel_acc = st.selectbox("👤 選擇帳戶", acc_list)
st.header(f"💼 帳戶：{sel_acc}")

# 計算彙總數據
inv = accounts_data[sel_acc]['inventory']
p_data = []
t_mv, t_cost, t_upnl, t_rpnl = 0.0, 0.0, 0.0, 0.0

for sym, d in inv.items():
    if d['shares'] > 0:
        cur_p = get_current_price(sym)
        mv = cur_p * d['shares']
        upnl = mv - d['total_cost']
        roi = (upnl / d['total_cost'] * 100) if d['total_cost'] > 0 else 0
        t_mv += mv
        t_cost += d['total_cost']
        t_upnl += upnl
        p_data.append({
            "標的": sym, "股數": d['shares'], "平均含費成本": round(d['total_cost']/d['shares'], 2),
            "現價": cur_p, "市值": round(mv, 0), "損益": round(upnl, 0), "報酬率": f"{roi:.2f}%"
        })
    t_rpnl += d['realized_pnl']

# 1. 總覽
st.subheader("📊 投資總覽")
c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 總市值", f"${t_mv:,.0f}")
c2.metric("🪙 總投資成本", f"${t_cost:,.0f}")
c3.metric("📉 未實現損益", f"${t_upnl:,.0f}", delta=f"{t_upnl:,.0f}")
c4.metric("🧧 已實現損益", f"${t_rpnl:,.0f}")

st.divider()

# 2. 明細
st.subheader("📋 庫存明細")
if p_data: st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)

# 3. 歷史紀錄 (含新欄位)
st.divider()
st.subheader("📜 交易歷史紀錄")
hist_df = df[df['Account'] == sel_acc].sort_values('Date', ascending=False)
st.dataframe(hist_df[['Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']], use_container_width=True, hide_index=True)
