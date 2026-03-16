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
        st.text_input("🔒 請輸入密碼以查看資產", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 請輸入密碼以查看資產", type="password", on_change=password_entered, key="password")
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

# 確保基礎欄位包含新欄位
expected_columns = ['id', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']
if df.empty or 'id' not in df.columns:
    df = pd.DataFrame(columns=expected_columns)

df = df.dropna(subset=['id'])
if not df.empty:
    df['id'] = df['id'].astype(int)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

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
            ticker = yf.Ticker(s)
            history = ticker.history(period="2d")
            if not history.empty:
                return history['Close'].iloc[-1]
        except:
            continue
    return 0.0

# ==========================================
# 4. 側邊欄：新增交易紀錄表單
# ==========================================
st.sidebar.header("✍️ 新增交易紀錄")

# 動態選單邏輯
existing_accounts = sorted(df['Account'].dropna().unique().tolist()) if not df.empty else ["媽媽"]
acc_opt = st.sidebar.selectbox("👤 選擇帳戶", existing_accounts + ["➕ 新增其他帳戶..."])
final_account = st.sidebar.text_input("✏️ 手動輸入新帳戶") if acc_opt == "➕ 新增其他帳戶..." else acc_opt

existing_symbols = sorted(df['Symbol'].dropna().unique().tolist()) if not df.empty else ["0050.TW"]
sym_opt = st.sidebar.selectbox("🏷️ 選擇股票 (可輸入數字搜尋)", existing_symbols + ["➕ 新增其他股票..."])
final_symbol = st.sidebar.text_input("✏️ 手動輸入新代號") if sym_opt == "➕ 新增其他股票..." else sym_opt

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 交易類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_shares = st.number_input("🔢 股數 (張/股)", min_value=0, step=1, value=0)
    
    # 改為輸入總金額
    f_total_raw = st.number_input("💰 總成交金額 (不含規費)", min_value=0.0, step=100.0, value=0.0)
    f_fee = st.number_input("🏦 手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 交易稅", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入 Google 試算表")
    
    if submitted and final_account and final_symbol:
        # 計算邏輯
        calc_price = f_total_raw / f_shares if f_shares > 0 else 0
        
        if f_type == "Buy":
            total_amt = f_total_raw + f_fee
            unit_cost = total_amt / f_shares if f_shares > 0 else 0
        elif f_type == "Sell":
            total_amt = f_total_raw - f_fee - f_tax
            unit_cost = calc_price # 賣出時紀錄單價
        else: # 股利
            total_amt = f_total_raw
            unit_cost = f_total_raw

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
            'Total_Amount': round(total_amt, 0),
            'Unit_Cost': round(unit_cost, 2)
        }])
        
        updated_df = pd.concat([df, new_data], ignore_index=True)
        conn.update(worksheet="工作表1", data=updated_df)
        st.sidebar.success(f"✅ 成功寫入紀錄！")
        st.rerun()

# ==========================================
# 5. 資料處理與運算
# ==========================================
accounts_data = {}
if not df.empty:
    for _, row in df.iterrows():
        acc = row['Account']
        if acc not in accounts_data:
            accounts_data[acc] = {'inventory': {}, 'cash_flows': []}
        
        inv = accounts_data[acc]['inventory']
        sym, t_type, shares = row['Symbol'], row['Type'], row['Shares']
        
        # 兼容舊資料：如果沒有 Total_Amount 就現場算
        if 'Total_Amount' in row and pd.notnull(row['Total_Amount']):
            total_amt = row['Total_Amount']
        else:
            p, f, t = row['Price'], row['Fee'], row['Tax']
            total_amt = (shares * p) + f if t_type == 'Buy' else (shares * p) - f - t

        if sym not in inv:
            inv[sym] = {'shares': 0, 'total_cost': 0.0, 'realized_pnl': 0.0}

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
account_list = list(accounts_data.keys())
if not account_list:
    st.info("👋 歡迎！請從左側邊欄新增第一筆紀錄。")
    st.stop()

selected_account = st.selectbox("👤 選擇要查看的帳戶", account_list)

if selected_account in accounts_data:
    st.header(f"💼 帳戶：{selected_account}")
    data = accounts_data[selected_account]
    
    total_market_value, total_unrealized_pnl, total_realized_pnl, total_invested_cost = 0.0, 0.0, 0.0, 0.0
    portfolio_data = []

    for sym, inv_data in data['inventory'].items():
        shares, cost = inv_data['shares'], inv_data['total_cost']
        realized = inv_data['realized_pnl']
        total_realized_pnl += realized
        
        if shares > 0:
            current_price = get_current_price(sym)
            market_value = current_price * shares
            unrealized_pnl = market_value - cost if current_price > 0 else 0.0
            
            # 個別標的總報酬率
            individual_total_roi = (unrealized_pnl / cost * 100) if cost > 0 else 0
            
            total_market_value += market_value
            total_unrealized_pnl += unrealized_pnl
            total_invested_cost += cost
            
            portfolio_data.append({
                "🏷️ 股票": sym, 
                "📦 股數": int(shares),
                "🪙 含費均價": round(cost/shares, 2), 
                "🔔 最新現價": current_price,
                "💎 市值": round(market_value, 0), 
                "📈 損益": round(unrealized_pnl, 0),
                "🚀 總報酬 %": f"{individual_total_roi:.2f}%"
            })

    # ==========================================
    # 第一層：【投資總覽】
    # ==========================================
    st.subheader("📊 帳戶總結資產")
    
    # 計算帳戶總報酬率 (Total ROI)
    overall_total_roi = (total_unrealized_pnl / total_invested_cost * 100) if total_invested_cost > 0 else 0

    # 計算 XIRR (年化報酬率)
    today = pd.to_datetime(datetime.today().date())
    temp_cash_flows = data['cash_flows'].copy()
    if total_market_value > 0:
        temp_cash_flows.append((today, total_market_value))
    
    try:
        if len(temp_cash_flows) >= 2:
            dates = [cf[0] for cf in temp_cash_flows]
            amounts = [cf[1] for cf in temp_cash_flows]
            xirr_val = xirr(dates, amounts)
            xirr_percentage = xirr_val * 100 if xirr_val else 0.0
        else:
            xirr_percentage = 0.0
    except:
        xirr_percentage = 0.0

    # 顯示指標卡 (分兩排顯示，視覺上更舒適)
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 總市值", f"${total_market_value:,.0f}")
    c2.metric("🪙 總投資成本", f"${total_invested_cost:,.0f}")
    c3.metric("📉 未實現損益", f"${total_unrealized_pnl:,.0f}", delta=f"{total_unrealized_pnl:,.0f}")

    c4, c5, c6 = st.columns(3)
    c4.metric("🧧 已實現損益", f"${total_realized_pnl:,.0f}")
    c5.metric("📈 總報酬率", f"{overall_total_roi:.2f}%")
    c6.metric("📊 年化報酬 (XIRR)", f"{xirr_percentage:.2f}%")

    st.divider()

    # 第二層：【庫存明細】
    st.subheader("📋 個別標的明細")
    if portfolio_data:
        st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True, hide_index=True)
    
    # 第三層：【資產配置】
    if portfolio_data:
        st.divider()
        st.subheader("🥧 資產配置比例")
        fig = px.pie(pd.DataFrame(portfolio_data), values='💎 市值', names='🏷️ 股票', hole=0.4, 
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)

# 管理紀錄區域
st.divider()
st.write(f"### ⚙️ 管理交易紀錄")
hist_df = df[df['Account'] == selected_account].sort_values('Date', ascending=False)
st.dataframe(hist_df[['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']], use_container_width=True, hide_index=True)

with st.form("delete_form"):
    del_id = st.number_input("⚠️ 輸入要刪除的紀錄 ID", min_value=0, step=1)
    if st.form_submit_button("🗑️ 刪除紀錄"):
        if del_id in df['id'].values:
            conn.update(worksheet="工作表1", data=df[df['id'] != del_id])
            st.success("已刪除！")
            st.rerun()
