import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from pyxirr import xirr
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. 網頁基本設定 & 連線 Google Sheets
# ==========================================
st.set_page_config(page_title="股票庫存追蹤系統", page_icon="📈", layout="wide")
st.title("📈 家族/個人股票追蹤系統 (Google 試算表版)")

# 建立連線 (ttl=0 代表每次都抓取最新資料，不使用快取)
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(spreadsheet="https://docs.google.com/spreadsheets/d/1x1zFrreF7xfPqp6eyToih1ZJpUVrV_Nk9FpyCneM5AU/edit", worksheet="工作表1", ttl=0)

# 如果試算表是完全空白的，先幫它建立好欄位
expected_columns = ['id', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax']
if df.empty or len(df.columns) == 0 or 'id' not in df.columns:
    df = pd.DataFrame(columns=expected_columns)
    conn.update(worksheet="工作表1", data=df)

# 確保資料格式正確 (避免 id 變成小數點)
df = df.dropna(subset=['id']) # 移除全空的無效列
if not df.empty:
    df['id'] = df['id'].astype(int)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

# ==========================================
# 2. 側邊欄：新增交易紀錄表單
# ==========================================
st.sidebar.header("✍️ 新增交易紀錄")

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_account = st.text_input("👤 帳戶名稱", value="主要帳戶")
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 交易類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_symbol = st.text_input("🏷️ 股票代號 (台股請加 .TW)", value="2330.TW")
    f_shares = st.number_input("🔢 股數 (現金股利請填 0)", min_value=0, step=1, value=1000)
    f_price = st.number_input("💲 成交價 / 每股股息", min_value=0.0, step=0.1, value=0.0)
    f_fee = st.number_input("🏦 手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 交易稅 (賣出才有)", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入 Google 試算表")
    
    if submitted:
        # 自動產生新的 ID (找出目前的最高 ID + 1)
        new_id = int(df['id'].max()) + 1 if not df.empty else 1
        
        # 建立新資料的 DataFrame
        new_data = pd.DataFrame([{
            'id': new_id,
            'Account': f_account,
            'Date': f_date.strftime("%Y-%m-%d"),
            'Type': f_type,
            'Symbol': f_symbol.upper(),
            'Shares': f_shares,
            'Price': f_price,
            'Fee': f_fee,
            'Tax': f_tax
        }])
        
        # 把新資料接在舊資料後面，並更新回 Google Sheets
        updated_df = pd.concat([df, new_data], ignore_index=True)
        conn.update(worksheet="工作表1", data=updated_df)
        
        st.sidebar.success("✅ 交易紀錄已成功寫入！")
        st.rerun()

# 如果還是沒有任何資料，提示使用者輸入
if df.empty:
    st.info("👋 歡迎使用！你的 Google 試算表目前是空的，請從左側邊欄新增第一筆紀錄！")
    st.stop()

# ==========================================
# 3. 核心運算與快取股價
# ==========================================
@st.cache_data(ttl=3600)
def get_current_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="1d")
        if not history.empty:
            return history['Close'].iloc[-1]
    except Exception:
        pass
    return 0.0

accounts_data = {}
for index, row in df.iterrows():
    acc = row['Account']
    if acc not in accounts_data:
        accounts_data[acc] = {'inventory': {}, 'cash_flows': []}
        
    inv = accounts_data[acc]['inventory']
    cash_flows = accounts_data[acc]['cash_flows']
    
    sym, t_type, shares, price = row['Symbol'], row['Type'], int(row['Shares']), float(row['Price'])
    fee, tax, date = float(row['Fee']), float(row['Tax']), row['Date']

    if sym not in inv:
        inv[sym] = {'shares': 0, 'total_cost': 0.0, 'realized_pnl': 0.0, 'total_dividends': 0.0}

    if t_type == 'Buy':
        cost = (shares * price) + fee
        inv[sym]['shares'] += shares
        inv[sym]['total_cost'] += cost
        cash_flows.append((date, -cost))
    elif t_type == 'Sell':
        if inv[sym]['shares'] >= shares:
            avg_cost = inv[sym]['total_cost'] / inv[sym]['shares']
            cost_of_sold = avg_cost * shares
            net_proceeds = (shares * price) - fee - tax
            inv[sym]['shares'] -= shares
            inv[sym]['total_cost'] -= cost_of_sold
            inv[sym]['realized_pnl'] += (net_proceeds - cost_of_sold)
            cash_flows.append((date, net_proceeds))
    elif t_type == 'Cash_Div':
        inv[sym]['total_dividends'] += price
        cash_flows.append((date, price))
    elif t_type == 'Stock_Div':
        inv[sym]['shares'] += shares

# ==========================================
# 4. 介面呈現：指標與圖表
# ==========================================
account_list = list(accounts_data.keys())
selected_account = st.selectbox("👤 選擇要查看的帳戶", account_list)

st.write(f"### 📊 【 {selected_account} 】的投資總覽")

data = accounts_data[selected_account]
inventory = data['inventory']
cash_flows = data['cash_flows']

total_market_value, total_unrealized_pnl, total_realized_pnl = 0.0, 0.0, 0.0
portfolio_data = []

for sym, inv_data in inventory.items():
    shares = inv_data['shares']
    total_cost = inv_data['total_cost']
    total_realized_pnl += inv_data['realized_pnl']
    
    if shares > 0:
        current_price = get_current_price(sym)
        market_value = current_price * shares
        unrealized_pnl = market_value - total_cost
        avg_price = total_cost / shares
        roi = (unrealized_pnl / total_cost) * 100 if total_cost > 0 else 0
        
        total_market_value += market_value
        total_unrealized_pnl += unrealized_pnl
        
        portfolio_data.append({
            "股票代號": sym,
            "庫存股數": shares,
            "平均成本": round(avg_price, 2),
            "最新市價": round(current_price, 2),
            "目前現值": round(market_value, 0),
            "未實現損益": round(unrealized_pnl, 0),
            "報酬率 (%)": round(roi, 2)
        })

today = pd.to_datetime(datetime.today().date())
if total_market_value > 0:
    cash_flows.append((today, total_market_value))

try:
    dates = [cf[0] for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]
    xirr_val = xirr(dates, amounts)
    xirr_percentage = xirr_val * 100 if xirr_val else 0.0
except:
    xirr_percentage = 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("總市值", f"${total_market_value:,.0f}")
col2.metric("未實現損益", f"${total_unrealized_pnl:,.0f}")
col3.metric("已實現損益", f"${total_realized_pnl:,.0f}")
col4.metric("年化報酬率 (XIRR)", f"{xirr_percentage:.2f}%")

st.divider()

col_table, col_chart = st.columns([3, 2])
with col_table:
    st.write("#### 📝 庫存明細")
    if portfolio_data:
        st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True, hide_index=True)
    else:
        st.info("目前沒有庫存。")
with col_chart:
    st.write("#### 🥧 資產配置比例")
    if portfolio_data:
        fig = px.pie(pd.DataFrame(portfolio_data), values='目前現值', names='股票代號', hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 5. ⚙️ 管理與刪除交易紀錄 (更新回 Google Sheets)
# ==========================================
st.divider()
st.write(f"### ⚙️ 管理 【 {selected_account} 】 的交易紀錄")

df_account = df[df['Account'] == selected_account]
st.dataframe(df_account, use_container_width=True, hide_index=True)

with st.form("delete_form"):
    col_del1, col_del2 = st.columns([3, 1])
    with col_del1:
        delete_id = st.number_input("⚠️ 請輸入要刪除的『紀錄 ID』", min_value=0, step=1)
    with col_del2:
        st.write("") 
        st.write("") 
        submit_delete = st.form_submit_button("🗑️ 刪除此筆紀錄")

    if submit_delete:
        if delete_id > 0 and delete_id in df['id'].values:
            # 篩選掉要刪除的 ID，留下其他的資料
            df_kept = df[df['id'] != delete_id]
            # 更新回 Google Sheets
            conn.update(worksheet="工作表1", data=df_kept)
            st.success(f"✅ 已成功刪除 ID 為 {delete_id} 的紀錄！")
            st.rerun() 
        else:
            st.warning("找不到此 ID，請確認後再輸入。")