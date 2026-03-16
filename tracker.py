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
st.title("📈 股票追蹤系統")

# ==========================================
# 🔒 密碼鎖系統 (新增這個區塊)
# ==========================================
def check_password():
    """驗證使用者輸入的密碼是否正確"""
    def password_entered():
        # 檢查輸入的密碼有沒有和 secrets 裡的一樣
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 驗證成功後就把輸入框的密碼清掉，比較安全
        else:
            st.session_state["password_correct"] = False

    # 如果是第一次進來，還沒有驗證過
    if "password_correct" not in st.session_state:
        st.text_input("🔒 請輸入密碼以查看你的資產", type="password", on_change=password_entered, key="password")
        return False
        
    # 如果輸入錯誤
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 請輸入密碼以查看你的資產", type="password", on_change=password_entered, key="password")
        st.error("❌ 密碼錯誤，請重新輸入！")
        return False
        
    # 密碼正確，放行！
    else:
        return True

# --- 🛑 守門員：如果密碼不對，就立刻停止執行後面的所有程式 ---
if not check_password():
    st.stop()

# 建立連線 (ttl=0 代表每次都抓取最新資料，不使用快取)
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="工作表1", ttl=0)

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

# --- 🚀 進階功能 1：動態帳戶選單 ---
if not df.empty and 'Account' in df.columns:
    existing_accounts = sorted(df['Account'].dropna().unique().tolist())
else:
    existing_accounts = ["媽媽"]
    
account_options = existing_accounts + ["➕ 新增其他帳戶..."]
selected_acc_option = st.sidebar.selectbox("👤 選擇帳戶", account_options)

if selected_acc_option == "➕ 新增其他帳戶...":
    final_account = st.sidebar.text_input("✏️ 手動輸入新帳戶名稱", placeholder="例如: 存股帳戶")
else:
    final_account = selected_acc_option

# --- 🚀 進階功能 2：動態股票選單 ---
if not df.empty and 'Symbol' in df.columns:
    existing_symbols = sorted(df['Symbol'].dropna().unique().tolist())
else:
    existing_symbols = ["0050.TW"]
    
symbol_options = existing_symbols + ["➕ 新增其他股票..."]
selected_sym_option = st.sidebar.selectbox("🏷️ 選擇股票 (可輸入數字搜尋)", symbol_options)

if selected_sym_option == "➕ 新增其他股票...":
    final_symbol = st.sidebar.text_input("✏️ 手動輸入新代號 (上市.TW/上櫃.TWO)", placeholder="例如: 8069.TWO")
else:
    final_symbol = selected_sym_option

# --- 下方是固定不變的數值表單 ---
with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 交易類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    
    f_shares = st.number_input("🔢 股數 (現金股利請填 0)", min_value=0, step=1, value=1000)
    f_price = st.number_input("💲 成交價 / 每股股息", min_value=0.0, step=0.1, value=0.0)
    f_fee = st.number_input("🏦 手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 交易稅 (賣出才有)", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入 Google 試算表")
    
    if submitted:
        # 雙重防呆：確保帳戶和股票都有填寫
        if not final_account:
            st.sidebar.error("⚠️ 請確實輸入帳戶名稱！")
        elif not final_symbol:
            st.sidebar.error("⚠️ 請確實輸入股票代號！")
        else:
            new_id = int(df['id'].max()) + 1 if not df.empty else 1
            
            new_data = pd.DataFrame([{
                'id': new_id,
                'Account': final_account,
                'Date': f_date.strftime("%Y-%m-%d"),
                'Type': f_type,
                'Symbol': final_symbol.upper(),
                'Shares': f_shares,
                'Price': f_price,
                'Fee': f_fee,
                'Tax': f_tax
            }])
            
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(worksheet="工作表1", data=updated_df)
            
            st.sidebar.success(f"✅ 成功寫入 {final_account} 的 {final_symbol.upper()} 紀錄！")
            st.rerun()

# ==========================================
# 3. 核心運算與快取股價
# ==========================================
@st.cache_data(ttl=3600)
def get_current_price(symbol):
    # 先把代號轉成大寫並修剪掉前後空格
    symbol = str(symbol).strip().upper()
    
    # 自動補強邏輯：如果使用者忘記加後綴，我們幫他試試看
    search_list = [symbol]
    if "." not in symbol:
        search_list.append(f"{symbol}.TW")
        search_list.append(f"{symbol}.TWO")

    for s in search_list:
        try:
            ticker = yf.Ticker(s)
            # 抓取最近兩天的資料確保一定有最新收盤價
            history = ticker.history(period="2d")
            if not history.empty:
                return history['Close'].iloc[-1]
        except Exception:
            continue
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

if not account_list:
    st.info("👋 歡迎！請從左側邊欄新增第一筆紀錄（記得台股代號要加 .TW 或 .TWO 喔）")
    st.stop()

selected_account = st.selectbox("👤 選擇要查看的帳戶", account_list)

# --- 核心顯示邏輯 ---
if selected_account in accounts_data:
    st.write(f"### 📊 【 {selected_account} 】 的投資總覽")
    
    data = accounts_data[selected_account]
    inventory = data['inventory']
    cash_flows = data['cash_flows']

    total_market_value, total_unrealized_pnl, total_realized_pnl = 0.0, 0.0, 0.0
    portfolio_data = []

    for sym, inv_data in inventory.items():
        shares = inv_data['shares']
        total_cost = inv_data['total_cost']
        total_realized_pnl += inv_data['realized_pnl']
        
        # 只要有股份，就應該顯示出來
        if shares > 0:
            current_price = get_current_price(sym)
            
            # 如果抓不到市價 (current_price 為 0)，就先拿平均成本當市價，避免畫面崩潰
            display_price = current_price if current_price > 0 else (total_cost / shares)
            market_value = current_price * shares
            unrealized_pnl = market_value - total_cost if current_price > 0 else 0.0
            avg_price = total_cost / shares
            roi = (unrealized_pnl / total_cost) * 100 if (total_cost > 0 and current_price > 0) else 0.0
            
            total_market_value += market_value
            total_unrealized_pnl += unrealized_pnl
            
            portfolio_data.append({
                "🏷️ 股票代號": sym,
                "📦 庫存股數": int(shares),
                "🪙 平均成本": round(avg_price, 2),
                "🔔 最新市價": round(current_price, 2) if current_price > 0 else "抓取失敗",
                "💎 目前現值": round(market_value, 0),
                "📈 未實現損益": round(unrealized_pnl, 0),
                "🚀 報酬率 (%)": f"{roi:.2f}%"
            })

    # --- 顯示指標卡 (加上防呆檢查) ---
    if portfolio_data or total_realized_pnl != 0:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 總市值", f"${total_market_value:,.0f}")
        col2.metric("📉 未實現損益", f"${total_unrealized_pnl:,.0f}")
        col3.metric("🧧 已實現損益", f"${total_realized_pnl:,.0f}")
        
        # 計算 XIRR
        today = pd.to_datetime(datetime.today().date())
        temp_cash_flows = cash_flows.copy()
        if total_market_value > 0:
            temp_cash_flows.append((today, total_market_value))
        
        try:
            dates = [cf[0] for cf in temp_cash_flows]
            amounts = [cf[1] for cf in temp_cash_flows]
            xirr_val = xirr(dates, amounts)
            xirr_percentage = xirr_val * 100 if xirr_val else 0.0
        except:
            xirr_percentage = 0.0
        
        col4.metric("📊 年化報酬率", f"{xirr_percentage:.2f}%")

        st.divider()

        # 顯示表格與圓餅圖
        col_table, col_chart = st.columns([3, 2])
        with col_table:
            st.write("#### 📝 庫存明細")
            if portfolio_data:
                st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True, hide_index=True)
            else:
                st.info("目前無庫存股份。")
        with col_chart:
            st.write("#### 🥧 資產配置")
            if portfolio_data and total_market_value > 0:
                fig = px.pie(pd.DataFrame(portfolio_data), values='💎 目前現值', names='🏷️ 股票代號', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ 帳戶中沒有有效的庫存資料。請檢查股票代號是否包含 .TW 或 .TWO。")

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
