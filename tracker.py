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
st.set_page_config(page_title="股票追蹤系統", page_icon="📈", layout="wide")
st.title("📈 股票追蹤系統")

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
# 2. 資料庫連線與記憶體快取 (核心除錯區)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 💡 只有在記憶體沒資料時，才去跟 Google 要資料
if "my_data" not in st.session_state:
    st.session_state.my_data = conn.read(worksheet="工作表1", ttl=0)

df = st.session_state.my_data

# 確保基礎欄位存在
expected_cols = ['id', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']
if df.empty or 'id' not in df.columns:
    df = pd.DataFrame(columns=expected_cols)

# 格式清洗
df = df.dropna(subset=['id'])
if not df.empty:
    df['id'] = df['id'].astype(int)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date']).sort_values('Date')

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
            if not history.empty: return round(history['Close'].iloc[-1], 2)
        except: continue
    return 0.0

# ==========================================
# 4. 側邊欄：新增交易紀錄表單
# ==========================================
st.sidebar.header("✍️ 交易與管理")

# 手動同步按鈕
if st.sidebar.button("🔄 從雲端強制重新讀取", use_container_width=True):
    if "my_data" in st.session_state:
        del st.session_state["my_data"]
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("新增紀錄")

# 動態帳戶選單
existing_accounts = sorted([str(x).strip() for x in df['Account'].dropna().unique()]) if not df.empty else ["媽媽"]
acc_opt = st.sidebar.selectbox("👤 選擇帳戶", existing_accounts + ["➕ 新增..."])
final_account = st.sidebar.text_input("✏️ 新帳戶名稱").strip() if acc_opt == "➕ 新增..." else acc_opt

existing_symbols = sorted(df['Symbol'].dropna().unique().tolist()) if not df.empty else ["0050.TW"]
sym_opt = st.sidebar.selectbox("🏷️ 股票代號", existing_symbols + ["➕ 新增..."])
final_symbol = st.sidebar.text_input("✏️ 新代號 (.TW/.TWO)").strip().upper() if sym_opt == "➕ 新增..." else sym_opt

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_shares = st.number_input("🔢 股數", min_value=0, step=1, value=0)
    f_total_all_in = st.number_input("💰 總金額 (已含手續費/稅)", min_value=0.0, step=100.0, value=0.0)
    f_fee = st.number_input("🏦 其中包含的手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 其中包含的交易稅", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入試算表")
    
    if submitted and final_account and final_symbol:
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
            'Symbol': final_symbol,
            'Shares': f_shares,
            'Price': round(calc_price, 2),
            'Fee': f_fee,
            'Tax': f_tax,
            'Total_Amount': round(f_total_all_in, 2),
            'Unit_Cost': round(unit_cost, 2)
        }])
        
        updated_df = pd.concat([df, new_data], ignore_index=True)
        
        # 1. 寫入 Google Sheets
        conn.update(worksheet="工作表1", data=updated_df)
        
        # 🌟 關鍵修復：強制清除 Streamlit 的全域快取，防止重整時讀到舊資料！
        st.cache_data.clear()
        
        # 3. ⚡ 秒速更新記憶體
        st.session_state.my_data = updated_df
        
        st.sidebar.success("✅ 成功寫入！")
        st.rerun()

# ==========================================
# 5. 資料處理邏輯
# ==========================================
accounts_data = {}
if not df.empty:
    for _, row in df.iterrows():
        acc = str(row['Account']).strip()
        if acc not in accounts_data: accounts_data[acc] = {'inventory': {}, 'cash_flows': []}
        inv = accounts_data[acc]['inventory']
        sym, t_type, shares = row['Symbol'], row['Type'], row['Shares']
        
        total_amt = row['Total_Amount'] if 'Total_Amount' in row and pd.notnull(row['Total_Amount']) else ((row['Shares']*row['Price'])+row['Fee'])

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
# 6. 介面呈現 (加入台股紅漲綠跌彩色系統)
# ==========================================
acc_list = list(accounts_data.keys())
if not acc_list:
    st.info("👋 目前沒有資料，請新增第一筆紀錄！")
    st.stop()

sel_acc = st.selectbox("👤 選擇要查看的帳戶", acc_list)
st.header(f"💼 帳戶：{sel_acc}")

data = accounts_data[sel_acc]
p_data = []
t_mv, t_cost, t_upnl, t_rpnl = 0.0, 0.0, 0.0, 0.0

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
        
        # 💡 關鍵改變：為了讓表格可以判斷顏色與排序，這裡改存「純數字」
        p_data.append({
            "標的": sym, 
            "股數": int(d['shares']),
            "含費均價": d['total_cost']/d['shares'],
            "最新現價": cur_p,
            "市值": int(round(mv, 0)),
            "損益": int(round(upnl, 0)),
            "總報酬 %": roi
        })

# ==========================================
# 📊 第一層：投資總覽 (指標卡上色)
# ==========================================
st.subheader("📊 投資總覽")
overall_roi = (t_upnl / t_cost * 100) if t_cost > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("💰 總市值", f"${int(round(t_mv, 0)):,}")
c2.metric("🪙 總投資成本", f"${int(round(t_cost, 0)):,}")
# 加上 delta 與 delta_color="inverse" 變成紅賺綠賠
c3.metric("📉 未實現損益", f"${int(round(t_upnl, 0)):,}", delta=f"{int(round(t_upnl, 0)):,}", delta_color="inverse")

c4, c5, c6 = st.columns(3)
c4.metric("🧧 已實現損益", f"${int(round(t_rpnl, 0)):,}", delta=f"{int(round(t_rpnl, 0)):,}", delta_color="inverse")
c5.metric("📈 總報酬率", f"{overall_roi:.2f}%", delta=f"{overall_roi:.2f}%", delta_color="inverse")

temp_cf = data['cash_flows'].copy()
if t_mv > 0: temp_cf.append((pd.to_datetime(datetime.today().date()), t_mv))
try:
    x_val = xirr([cf[0] for cf in temp_cf], [cf[1] for cf in temp_cf]) * 100 if len(temp_cf) >= 2 else 0
except: x_val = 0
c6.metric("📊 年化報酬 (XIRR)", f"{x_val:.2f}%", delta=f"{x_val:.2f}%", delta_color="inverse")

st.divider()

# ==========================================
# 📋 第二層：庫存明細 (表格上色)
# ==========================================
st.subheader("📋 庫存明細")
if p_data: 
    df_portfolio = pd.DataFrame(p_data)

    # 🎨 定義上色邏輯：大於0紅色，小於0綠色
    def color_profit_loss(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return 'color: #ff4b4b;'  # Streamlit 預設紅
            elif val < 0:
                return 'color: #09ab3b;'  # Streamlit 預設綠
        return ''

    # 將顏色套用到「損益」和「總報酬 %」這兩個欄位
    try:
        styled_df = df_portfolio.style.map(color_profit_loss, subset=['損益', '總報酬 %'])
    except AttributeError: # 相容舊版 Pandas
        styled_df = df_portfolio.style.applymap(color_profit_loss, subset=['損益', '總報酬 %'])

    # 重新把數字格式化為帶有千分位與小數點的字串
    styled_df = styled_df.format({
        "股數": "{:,}",
        "含費均價": "{:.2f}",
        "最新現價": "{:.2f}",
        "市值": "{:,}",
        "損益": "{:,}",
        "總報酬 %": "{:.2f}%"
    })

    # 顯示彩色表格
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("📜 管理交易紀錄")

# 先整理好要顯示的資料 (這樣我們才能核對 ID，並在下方顯示)
h_df = df[df['Account'] == sel_acc].copy()
h_df['Date'] = pd.to_datetime(h_df['Date'], errors='coerce').dt.date
h_df = h_df.dropna(subset=['Date']).sort_values('Date', ascending=False)

for col in ['Price', 'Unit_Cost']:
    h_df[col] = h_df[col].map(lambda x: f"{float(x):.2f}")
h_df['Total_Amount'] = h_df['Total_Amount'].map(lambda x: f"{int(round(float(x), 0)):,}")
h_df['Shares'] = h_df['Shares'].map(lambda x: f"{int(x):,}")

# ==========================================
# 1. 刪除區塊 (移到上方)
# ==========================================
with st.form("del_f"):
    st.write("🗑️ **刪除指定紀錄**")
    # 用 columns 讓輸入框和按鈕排在同一列，比較節省空間
    col_id, col_btn = st.columns([3, 1])
    with col_id:
        did = st.number_input("⚠️ 請參考下方表格，輸入要刪除的 ID", min_value=0, step=1)
    with col_btn:
        st.write("") # 往下推一點，讓按鈕跟輸入框對齊
        st.write("")
        submit_del = st.form_submit_button("🗑️ 確認刪除")
        
    if submit_del:
        if did in df['id'].values:
            updated_df = df[df['id'] != did]
            # 1. 寫入 Google
            conn.update(worksheet="工作表1", data=updated_df)
            # 2. 清除快取
            st.cache_data.clear()
            # 3. 秒速更新記憶體
            st.session_state.my_data = updated_df
            st.success(f"✅ 已成功刪除 ID {did} 的紀錄！")
            st.rerun()
        else:
            st.error("找不到此 ID，請確認後再輸入。")

# ==========================================
# 2. 詳細紀錄表格 (移到下方)
# ==========================================
st.write("#### 📝 詳細紀錄明細")
st.dataframe(h_df[['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']], use_container_width=True, hide_index=True)
