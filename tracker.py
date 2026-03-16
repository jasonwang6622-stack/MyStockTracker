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
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if "password_correct" not in st.session_state:
        st.text_input("🔒 請輸入密碼", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 請輸入密碼", type="password", on_change=password_entered, key="password")
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

if df.empty or 'id' not in df.columns:
    df = pd.DataFrame(columns=['id', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost'])

df = df.dropna(subset=['id'])
if not df.empty:
    df['id'] = df['id'].astype(int)
    df['Date'] = pd.to_datetime(df['Date'])

# ==========================================
# 3. 核心功能：抓取股價 (快取 1 小時)
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
            if not history.empty:
                return round(history['Close'].iloc[-1], 2)
        except:
            continue
    return 0.0

# ==========================================
# 4. 側邊欄：輸入表單 (改為總金額含規費)
# ==========================================
st.sidebar.header("✍️ 新增交易紀錄")

existing_accounts = sorted(df['Account'].dropna().unique().tolist()) if not df.empty else ["媽媽"]
acc_opt = st.sidebar.selectbox("👤 選擇帳戶", existing_accounts + ["➕ 新增..."])
final_account = st.sidebar.text_input("新帳戶名稱") if acc_opt == "➕ 新增..." else acc_opt

existing_symbols = sorted(df['Symbol'].dropna().unique().tolist()) if not df.empty else ["0050.TW"]
sym_opt = st.sidebar.selectbox("🏷️ 股票代號", existing_symbols + ["➕ 新增..."])
final_symbol = st.sidebar.text_input("新代號 (.TW/.TWO)") if sym_opt == "➕ 新增..." else sym_opt

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_shares = st.number_input("🔢 股數", min_value=0, step=1, value=0)
    
    # 核心修正：輸入的總金額已含規費
    f_total_all_in = st.number_input("💰 總金額 (已含手續費/稅)", min_value=0.0, step=1.0, value=0.0)
    f_fee = st.number_input("🏦 其中包含的手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 其中包含的交易稅", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入試算表")
    
    if submitted and final_account and final_symbol:
        # 反推成交單價 (不含規費的淨單價)
        if f_type == "Buy":
            net_amount = f_total_all_in - f_fee
        elif f_type == "Sell":
            net_amount = f_total_all_in + f_fee + f_tax
        else:
            net_amount = f_total_all_in
            
        calc_price = net_amount / f_shares if f_shares > 0 else 0
        unit_cost = f_total_all_in / f_shares if f_shares > 0 else 0

        new_data = pd.DataFrame([{
            'id': int(df['id'].max() + 1) if not df.empty else 1,
            'Account': final_account,
            'Date': f_date.strftime("%Y-%m-%d"),
            'Type': f_type,
            'Symbol': final_symbol.upper(),
            'Shares': f_shares,
            'Price': round(calc_price, 2),
            'Fee': f_fee,
            'Tax': f_tax,
            'Total_Amount': round(f_total_all_in, 2),
            'Unit_Cost': round(unit_cost, 2)
        }])
        
        conn.update(worksheet="工作表1", data=pd.concat([df, new_data], ignore_index=True))
        st.sidebar.success("✅ 成功寫入！")
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
        sym, t_type, shares = row['Symbol'], row['Type'], row['Shares']
        
        # 取得總金額
        total_amt = row['Total_Amount'] if 'Total_Amount' in row else ((row['Shares']*row['Price'])+row['Fee'])

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
# 6. 介面呈現 (格式化：損益取整數，價格保留兩位)
# ==========================================
acc_list = list(accounts_data.keys())
if not acc_list: st.stop()

sel_acc = st.selectbox("👤 選擇帳戶", acc_list)
st.header(f"💼 帳戶：{sel_acc}")

data = accounts_data[sel_acc]
p_data = []
t_mv, t_cost, t_upnl, t_rpnl = 0.0, 0.0, 0.0, 0.0

# 取得該帳戶已實現損益 (從 inventory 中加總)
t_rpnl = sum(inv_item['realized_pnl'] for inv_item in data['inventory'].values())

for sym, d in data['inventory'].items():
    if d['shares'] > 0:
        cur_p = get_current_price(sym)
        mv = cur_p * d['shares']
        upnl = mv - d['total_cost']
        roi = (upnl / d['total_cost'] * 100) if d['total_cost'] > 0 else 0
        t_mv += mv
        t_cost += d['total_cost']
        t_upnl += upnl
        p_data.append({
            "標的": sym, "股數": int(d['shares']),
            "含費均價": f"{d['total_cost']/d['shares']:.2f}",
            "最新現價": f"{cur_p:.2f}",
            "市值": f"{int(round(mv, 0)):,}",      # 取整數並加逗號
            "損益": f"{int(round(upnl, 0)):,}",    # 取整數並加逗號
            "總報酬 %": f"{roi:.2f}%"
        })

# 1. 投資總覽 (大指標取整數)
st.subheader("📊 投資總覽")
overall_roi = (t_upnl / t_cost * 100) if t_cost > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("💰 總市值", f"${int(round(t_mv, 0)):,}")
c2.metric("🪙 總投資成本", f"${int(round(t_cost, 0)):,}")
c3.metric("📉 未實現損益", f"${int(round(t_upnl, 0)):,}", delta=f"{int(round(t_upnl, 0)):,}")

c4, c5, c6 = st.columns(3)
c4.metric("🧧 已實現損益", f"${int(round(t_rpnl, 0)):,}")
c5.metric("📈 總報酬率", f"{overall_roi:.2f}%")

# XIRR 年化報酬
temp_cf = data['cash_flows'].copy()
if t_mv > 0: temp_cf.append((pd.to_datetime(datetime.today().date()), t_mv))
try:
    x_val = xirr([cf[0] for cf in temp_cf], [cf[1] for cf in temp_cf]) * 100 if len(temp_cf) >=2 else 0
except: x_val = 0
c6.metric("📊 年化報酬 (XIRR)", f"{x_val:.2f}%")

st.divider()

# 2. 庫存明細
st.subheader("📋 庫存明細")
if p_data: 
    st.dataframe(pd.DataFrame(p_data), use_container_width=True, hide_index=True)

st.divider()

# 3. 管理交易紀錄 (保持小數點供對帳用)
st.subheader("📜 管理交易紀錄")
h_df = df[df['Account'] == sel_acc].copy()
h_df['Date'] = pd.to_datetime(h_df['Date']).dt.date
h_df = h_df.sort_values('Date', ascending=False)

# 格式化顯示 (管理介面保留兩位小數方便精確對帳)
for col in ['Price', 'Total_Amount', 'Unit_Cost']:
    h_df[col] = h_df[col].map(lambda x: f"{float(x):.2f}")

st.dataframe(h_df[['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']], use_container_width=True, hide_index=True)

with st.form("del_f"):
    did = st.number_input("⚠️ 刪除 ID", min_value=0, step=1)
    if st.form_submit_button("🗑️ 刪除"):
        if did in df['id'].values:
            conn.update(worksheet="工作表1", data=df[df['id'] != did])
            st.success("已刪除！")
            st.rerun()
