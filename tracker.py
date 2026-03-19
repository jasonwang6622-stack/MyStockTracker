import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from pyxirr import xirr
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. 網頁基本設定 & 註冊登入系統
# ==========================================
st.set_page_config(page_title="股票追蹤系統", page_icon="📈", layout="wide")
st.title("📈 股票追蹤系統")

conn = st.connection("gsheets", type=GSheetsConnection)

def login_system():
    if "current_user" in st.session_state:
        return True

    st.subheader("🔐 系統登入與註冊")

    # 讀取帳號密碼本
    try:
        users_df = conn.read(worksheet="Users", ttl=0)
        users_df = users_df.dropna(subset=['Username'])
        
        # 🛡️ 終極解法 1：強制轉為字串，並把結尾的 .0 妖怪砍掉，再去掉多餘空白
        users_df['Username'] = users_df['Username'].astype(str).str.strip()
        users_df['Password'] = users_df['Password'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        
    except Exception:
        st.error("⚠️ 找不到 `Users` 分頁！請在 Google 試算表建立一個名為 `Users` 的分頁，並加上 Username, Password 兩欄。")
        st.stop()

    tab1, tab2 = st.tabs(["🔑 登入", "📝 註冊帳號"])

    with tab1:
        with st.form("login_form"):
            l_user = st.text_input("👤 帳號").strip()
            l_pw = st.text_input("🔒 密碼", type="password").strip()
            if st.form_submit_button("登入"):
                if l_user == "" or l_pw == "":
                    st.warning("請輸入帳號密碼")
                else:
                    matched = users_df[(users_df['Username'] == l_user) & (users_df['Password'] == l_pw)]
                    if not matched.empty:
                        st.session_state["current_user"] = l_user
                        st.success(f"歡迎回來，{l_user}！")
                        st.rerun()
                    else:
                        st.error("❌ 帳號或密碼錯誤")

    with tab2:
        with st.form("register_form"):
            r_user = st.text_input("👤 設定新帳號").strip()
            r_pw = st.text_input("🔒 設定密碼", type="password").strip()
            if st.form_submit_button("立即註冊"):
                if r_user == "" or r_pw == "":
                    st.warning("帳號密碼不能為空")
                elif r_user in users_df['Username'].values:
                    st.error("⚠️ 此帳號已經有人使用了，請換一個！")
                elif len(r_user) < 3 or len(r_pw) < 4:
                    st.error("⚠️ 帳號至少 3 碼，密碼至少 4 碼")
                else:
                    new_user_df = pd.DataFrame([{"Username": r_user, "Password": r_pw}])
                    conn.update(worksheet="Users", data=pd.concat([users_df, new_user_df], ignore_index=True))
                    
                    # 🛡️ 終極解法 2：註冊完立刻清空快取，確保下一秒登入抓到最新資料
                    st.cache_data.clear() 
                    
                    st.success("✅ 註冊成功！請切換到「登入」分頁進行登入。")

    return False
if not login_system():
    st.stop()

USER = st.session_state["current_user"]

# ==========================================
# 2. 資料庫連線 (包含隱形的牆)
# ==========================================
if "my_data" not in st.session_state:
    try:
        st.session_state.my_data = conn.read(worksheet="Database", ttl=0)
    except Exception:
        st.error("⚠️ 找不到 `Database` 分頁！請將您的資料分頁重新命名為 `Database`。")
        st.stop()

full_df = st.session_state.my_data

expected_cols = ['id', 'Username', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']
if full_df.empty or 'id' not in full_df.columns:
    full_df = pd.DataFrame(columns=expected_cols)

full_df = full_df.dropna(subset=['id'])
if not full_df.empty:
    full_df['id'] = full_df['id'].astype(int)
    full_df['Date'] = pd.to_datetime(full_df['Date'], errors='coerce')
    full_df = full_df.dropna(subset=['Date']).sort_values('Date')

# 🛡️ 隱形的牆：只抓取屬於當前使用者的資料
user_df = full_df[full_df['Username'] == USER].copy()

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
# 4. 側邊欄：新增交易與登出
# ==========================================
st.sidebar.header(f"👋 哈囉，{USER}")

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("🔄 重新讀取", use_container_width=True):
        if "my_data" in st.session_state: del st.session_state["my_data"]
        st.cache_data.clear()
        st.rerun()
with col2:
    if st.button("🚪 登出", use_container_width=True):
        st.session_state.clear() 
        st.cache_data.clear()
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("新增紀錄")

existing_accounts = sorted([str(x).strip() for x in user_df['Account'].dropna().unique()]) if not user_df.empty else ["主帳戶"]
acc_opt = st.sidebar.selectbox("👤 選擇帳戶", existing_accounts + ["➕ 新增..."])
final_account = st.sidebar.text_input("✏️ 新帳戶名稱").strip() if acc_opt == "➕ 新增..." else acc_opt

existing_symbols = sorted(user_df['Symbol'].dropna().unique().tolist()) if not user_df.empty else ["0050.TW"]
sym_opt = st.sidebar.selectbox("🏷️ 股票代號", existing_symbols + ["➕ 新增..."])
final_symbol = st.sidebar.text_input("✏️ 新代號 (.TW/.TWO)").strip().upper() if sym_opt == "➕ 新增..." else sym_opt

with st.sidebar.form("transaction_form", clear_on_submit=True):
    f_date = st.date_input("📅 交易日期", datetime.today())
    f_type = st.selectbox("🔄 類型", ["Buy", "Sell", "Cash_Div", "Stock_Div"])
    f_shares = st.number_input("🔢 股數", min_value=0, step=1, value=0)
    f_total_all_in = st.number_input("💰 總金額 (含規費)", min_value=0.0, step=100.0, value=0.0)
    f_fee = st.number_input("🏦 手續費", min_value=0.0, step=1.0, value=0.0)
    f_tax = st.number_input("🏛️ 交易稅", min_value=0.0, step=1.0, value=0.0)
    
    submitted = st.form_submit_button("💾 寫入")
    
    if submitted and final_account and final_symbol:
        if f_type == "Buy": net_amount = f_total_all_in - f_fee
        elif f_type == "Sell": net_amount = f_total_all_in + f_fee + f_tax
        else: net_amount = f_total_all_in
            
        calc_price = net_amount / f_shares if f_shares > 0 else 0
        unit_cost = f_total_all_in / f_shares if f_shares > 0 else 0

        # 寫入時，打上當前使用者的 Username 標籤
        new_row = {
            'id': int(full_df['id'].max() + 1) if not full_df.empty else 1,
            'Username': USER,
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
        }
        
        # 💡 將新資料加進「總資料庫 (full_df)」並寫入 Google Sheets
        updated_full_df = pd.concat([full_df, pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet="Database", data=updated_full_df)
        st.cache_data.clear()
        st.session_state.my_data = updated_full_df
        
        st.sidebar.success("✅ 成功寫入！")
        st.rerun()

# ==========================================
# 5. 資料處理邏輯 (只處理該使用者的 user_df)
# ==========================================
accounts_data = {}
if not user_df.empty:
    for _, row in user_df.iterrows():
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
# 6. 介面呈現 
# ==========================================
acc_list = list(accounts_data.keys())
if not acc_list:
    st.info("👋 歡迎！您的帳戶目前為空，請從左側新增第一筆紀錄！")
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
        est_sell_cost = mv * 0.003 + mv * 0.001425
        net_market_value = mv - est_sell_cost
        upnl = net_market_value - d['total_cost'] if cur_p > 0 else 0.0
        roi = (upnl / d['total_cost'] * 100) if d['total_cost'] > 0 else 0
        t_mv += mv
        t_cost += d['total_cost']
        t_upnl += upnl
        
        p_data.append({
            "標的": sym, "股數": int(d['shares']), "含費均價": d['total_cost']/d['shares'],
            "最新現價": cur_p, "市值": int(round(mv, 0)), "損益": int(round(upnl, 0)), "總報酬 %": roi
        })

st.subheader("📊 投資總覽")
overall_roi = (t_upnl / t_cost * 100) if t_cost > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("💰 總市值", f"${int(round(t_mv, 0)):,}")
c2.metric("🪙 總投資成本", f"${int(round(t_cost, 0)):,}")
c3.metric("📉 未實現損益", f"${int(round(t_upnl, 0)):,}", delta=f"{int(round(t_upnl, 0)):,}", delta_color="inverse")

c4, c5, c6 = st.columns(3)
c4.metric("🧧 已實現損益", f"${int(round(t_rpnl, 0)):,}", delta=f"{int(round(t_rpnl, 0)):,}", delta_color="inverse")
c5.metric("📈 總報酬率", f"{overall_roi:.2f}%", delta=f"{overall_roi:.2f}%", delta_color="inverse")

temp_cf = data['cash_flows'].copy()
if t_mv > 0: temp_cf.append((pd.to_datetime(datetime.today().date()), t_mv))
try: x_val = xirr([cf[0] for cf in temp_cf], [cf[1] for cf in temp_cf]) * 100 if len(temp_cf) >= 2 else 0
except: x_val = 0
c6.metric("📊 年化報酬 (XIRR)", f"{x_val:.2f}%", delta=f"{x_val:.2f}%", delta_color="inverse")

st.divider()
st.subheader("📋 庫存明細")
if p_data: 
    df_portfolio = pd.DataFrame(p_data)
    def color_profit_loss(val):
        if isinstance(val, (int, float)):
            if val > 0: return 'color: #ff4b4b;'
            elif val < 0: return 'color: #09ab3b;'
        return ''

    try: styled_df = df_portfolio.style.map(color_profit_loss, subset=['損益', '總報酬 %'])
    except AttributeError: styled_df = df_portfolio.style.applymap(color_profit_loss, subset=['損益', '總報酬 %'])

    styled_df = styled_df.format({"股數": "{:,}", "含費均價": "{:.2f}", "最新現價": "{:.2f}", "市值": "{:,}", "損益": "{:,}", "總報酬 %": "{:.2f}%"})
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

if p_data:
    st.divider()
    st.subheader("🥧 資產配置")
    pie_df = pd.DataFrame(p_data)
    pie_df = pie_df[pie_df['市值'] > 0] 
    if not pie_df.empty:
        fig = px.pie(pie_df, values='市值', names='標的', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textposition='inside', textinfo='percent+label') 
        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)") 
        st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("📜 管理交易紀錄")

# 準備該帳戶的紀錄
h_df = user_df[user_df['Account'] == sel_acc].copy()
h_df['Date'] = pd.to_datetime(h_df['Date'], errors='coerce').dt.date
h_df = h_df.dropna(subset=['Date']).sort_values('Date', ascending=False)

# 數字格式化
for col in ['Price', 'Unit_Cost']: 
    h_df[col] = h_df[col].map(lambda x: f"{float(x):.2f}")
h_df['Total_Amount'] = h_df['Total_Amount'].map(lambda x: f"{int(round(float(x), 0)):,}")
h_df['Shares'] = h_df['Shares'].map(lambda x: f"{int(x):,}")

# ==========================================
# 🌟 全新改版：打勾即刪除的互動表格
# ==========================================
st.write("#### 📝 詳細紀錄明細 (勾選最左側框框即可刪除)")

# 1. 建立顯示用的 DataFrame，並在最左邊插入「刪除打勾」欄位
display_cols = ['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']
display_df = h_df[display_cols].copy()
display_df.insert(0, "🗑️ 刪除", False) # 預設全部為未勾選 (False)

# 2. 使用 st.data_editor 產生可互動表格
edited_df = st.data_editor(
    display_df,
    column_config={
        "🗑️ 刪除": st.column_config.CheckboxColumn("🗑️ 刪除", default=False),
        "id": None, # 💡 設定為 None 就會把 id 欄位完美隱藏！
    },
    disabled=display_cols, # 鎖定其他原始資料欄位不給改，只允許操作打勾框
    hide_index=True,
    use_container_width=True
)

# 3. 抓出所有被勾選為 True 的資料的 id
deleted_ids = edited_df[edited_df["🗑️ 刪除"] == True]["id"].tolist()

# 4. 如果有任何一筆被勾選，就自動顯示紅色的確認刪除按鈕
if len(deleted_ids) > 0:
    # 用 type="primary" 讓按鈕變成醒目的紅色
    if st.button(f"🚨 確認刪除選取的 {len(deleted_ids)} 筆紀錄", type="primary", use_container_width=True):
        
        # 執行刪除：在總資料庫中，保留 id「不在」刪除名單裡的資料
        updated_full_df = full_df[~full_df['id'].isin(deleted_ids)]
        
        # 1. 寫入 Google Sheets
        conn.update(worksheet="Database", data=updated_full_df)
        
        # 2. 清除快取與更新記憶體
        st.cache_data.clear()
        st.session_state.my_data = updated_full_df
        
        st.success("✅ 已成功刪除！")
        st.rerun()
