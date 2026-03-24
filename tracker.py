import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from pyxirr import xirr
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import requests

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
# 3. 核心功能：抓取單純股價
# ==========================================
@st.cache_data(ttl=3600)
def get_stock_info(symbol):
    symbol = str(symbol).strip().upper()
    search_list = [symbol]
    if "." not in symbol:
        search_list.extend([f"{symbol}.TW", f"{symbol}.TWO"])
    for s in search_list:
        try:
            ticker = yf.Ticker(s)
            history = ticker.history(period="2d")
            if not history.empty: 
                price = round(history['Close'].iloc[-1], 2)
                return price  # 💡 改回只回傳一個數字
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
    
    submitted = st.form_submit_button("💾 輸入")
    
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
# 🌟 新增：批次匯入檔案功能 (自動計算 Price 與 Unit_Cost)
# ==========================================
with st.sidebar.expander("📂 批次匯入紀錄 (CSV)"):
    st.markdown("👉 **步驟 1：下載標準範本**")
    st.caption("⚠️ `Type` 請填寫：`Buy`, `Sell`, `Cash_Div`, `Stock_Div`")
    
    # 💡 亮點 1：範本把 Price 拿掉了，使用者少填一欄！
    template_cols = ['Account', 'Date', 'Type', 'Symbol', 'Shares', 'Fee', 'Tax', 'Total_Amount']
    template_df = pd.DataFrame(columns=template_cols)
    csv_template = template_df.to_csv(index=False).encode('utf-8-sig') 
    
    st.download_button(
        label="📥 下載 CSV 範本",
        data=csv_template,
        file_name="import_template.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    st.markdown("👉 **步驟 2：上傳填妥的 CSV**")
    uploaded_file = st.file_uploader("選擇檔案", type=["csv"], label_visibility="collapsed")
    
    if uploaded_file is not None:
        if st.button("🚀 確認批次匯入", type="primary", use_container_width=True):
            try:
                import_df = pd.read_csv(uploaded_file)
                
                # 防呆 1：檢查欄位有沒有被亂改
                if not all(col in import_df.columns for col in template_cols):
                    st.error("❌ 欄位錯誤！請確保使用剛下載的最新範本。")
                elif import_df.empty:
                    st.warning("⚠️ 檔案裡面沒有資料喔！")
                else:
                    # 綁定使用者
                    import_df['Username'] = USER
                    
                    # 確保數字格式正確 (把空值補 0)
                    for col in ['Shares', 'Total_Amount', 'Fee', 'Tax']:
                        import_df[col] = pd.to_numeric(import_df[col], errors='coerce').fillna(0)
                    
                    # 💡 亮點 2：系統自動反推計算 Price (單價)
                    def calculate_price(row):
                        if row['Shares'] <= 0: return 0
                        if row['Type'] == 'Buy':
                            net_amt = row['Total_Amount'] - row['Fee']
                        elif row['Type'] == 'Sell':
                            net_amt = row['Total_Amount'] + row['Fee'] + row['Tax']
                        else:
                            net_amt = row['Total_Amount']
                        return round(net_amt / row['Shares'], 2)
                        
                    import_df['Price'] = import_df.apply(calculate_price, axis=1)
                    
                    # 系統自動計算 Unit_Cost (均價)
                    import_df['Unit_Cost'] = import_df.apply(
                        lambda row: round(row['Total_Amount'] / row['Shares'], 2) if row['Shares'] > 0 else 0, 
                        axis=1
                    )
                    
                    # 系統自動給予連續的流水號 ID
                    start_id = int(full_df['id'].max() + 1) if not full_df.empty else 1
                    import_df['id'] = range(start_id, start_id + len(import_df))
                    
                    # 整理成跟資料庫一模一樣的欄位順序 (這時 Price 已經被生出來了)
                    final_import_df = import_df[['id', 'Username', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']]
                    
                    # 合併並寫入 Google Sheets
                    updated_full_df = pd.concat([full_df, final_import_df], ignore_index=True)
                    conn.update(worksheet="Database", data=updated_full_df)
                    
                    st.cache_data.clear()
                    st.session_state.my_data = updated_full_df
                    st.success(f"✅ 成功匯入 {len(import_df)} 筆紀錄，並自動計算完單價與均價！")
                    st.rerun()
                    
            except Exception as e:
                st.error(f"❌ 匯入時發生錯誤：{e}")
                
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
                # 💡 這裡改回只接收價格
                cur_p = get_stock_info(sym) 
                
                mv = cur_p * d['shares']
                est_sell_cost = mv * 0.003 + mv * 0.001425
                net_market_value = mv - est_sell_cost
                upnl = net_market_value - d['total_cost'] if cur_p > 0 else 0.0
                roi = (upnl / d['total_cost'] * 100) if d['total_cost'] > 0 else 0
                t_mv += mv
                t_cost += d['total_cost']
                t_upnl += upnl
                
                # 💡 這裡把 "名稱" 欄位拿掉了
                p_data.append({
                    "標的": sym, 
                    "股數": int(d['shares']), 
                    "含費均價": d['total_cost']/d['shares'],
                    "最新現價": cur_p, 
                    "市值": int(round(mv, 0)), 
                    "損益": int(round(upnl, 0)), 
                    "總報酬 %": roi
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
st.subheader("📋 庫存與歷史明細")

# ==========================================
# 🎨 上色小幫手 (放在外面讓兩個分頁共用)
# ==========================================
def color_profit_loss(val):
    if isinstance(val, (int, float)):
        if val > 0: return 'color: #ff4b4b;'  # 賺錢顯示紅色
        elif val < 0: return 'color: #09ab3b;' # 賠錢顯示綠色
    return ''

# 🌟 建立兩個分頁
tab1, tab2 = st.tabs(["📊 現有庫存", "🏁 已出清明細"])

# ==========================================
# 📂 分頁 1：現有庫存
# ==========================================
with tab1:
    if p_data: 
        df_portfolio = pd.DataFrame(p_data)
        df_portfolio = df_portfolio.sort_values(by="標的", ascending=True).reset_index(drop=True)

        try: 
            styled_df = df_portfolio.style.map(color_profit_loss, subset=['損益', '總報酬 %'])
        except AttributeError: 
            styled_df = df_portfolio.style.applymap(color_profit_loss, subset=['損益', '總報酬 %'])

        styled_df = styled_df.format({"股數": "{:,}", "含費均價": "{:.2f}", "最新現價": "{:.2f}", "市值": "{:,}", "損益": "{:,}", "總報酬 %": "{:.2f}%"})
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("目前沒有現有庫存資料喔！")

# ==========================================
# 📂 分頁 2：已出清的歷史戰績
# ==========================================
with tab2:
    cleared_data = []
    
    # 尋找已經賣光 (股數為 0) 的股票
    for sym, d in data['inventory'].items():
        if d['shares'] == 0:
            # 從你的交易紀錄 (h_df) 中抓出這檔股票的所有買賣紀錄
            sym_df = h_df[h_df['Symbol'] == sym]
            
            # 分別加總買進與賣出的總額 (確保轉為 float 避免型態錯誤)
            total_buy = sym_df[sym_df['Type'] == 'Buy']['Total_Amount'].astype(float).sum()
            total_sell = sym_df[sym_df['Type'] == 'Sell']['Total_Amount'].astype(float).sum()
            
            # 如果你有紀錄現金股利，也把它加進獲利裡
            total_div = sym_df[sym_df['Type'] == 'Cash_Div']['Total_Amount'].astype(float).sum() if 'Cash_Div' in sym_df['Type'].values else 0.0
            
            # 結算損益：總收入(賣出+股利) - 總成本(買進)
            realized_pnl = (total_sell + total_div) - total_buy
            
            # 結算報酬率
            roi = (realized_pnl / total_buy * 100) if total_buy > 0 else 0.0
            
            cleared_data.append({
                "標的": sym,
                "總買進成本": int(total_buy),
                "總賣出收入": int(total_sell),
                "損益": int(round(realized_pnl, 0)),
                "總報酬 %": roi
            })
            
    if cleared_data:
        df_cleared = pd.DataFrame(cleared_data)
        df_cleared = df_cleared.sort_values(by="標的", ascending=True).reset_index(drop=True)
        
        # 套用紅綠上色魔法！
        try: 
            styled_cleared = df_cleared.style.map(color_profit_loss, subset=['損益', '總報酬 %'])
        except AttributeError: 
            styled_cleared = df_cleared.style.applymap(color_profit_loss, subset=['損益', '總報酬 %'])
            
        styled_cleared = styled_cleared.format({
            "總買進成本": "{:,}", 
            "總賣出收入": "{:,}", 
            "損益": "{:,}", 
            "總報酬 %": "{:.2f}%"
        })
        st.dataframe(styled_cleared, use_container_width=True, hide_index=True)
    else:
        st.info("目前還沒有已出清的標的紀錄。")
            
    st.divider()
    st.subheader("🥧 資產配置")
    pie_df = pd.DataFrame(p_data)
    pie_df = pie_df[pie_df['市值'] > 0] 
    if not pie_df.empty:
        # 💡 這裡把 names 改回 '標的'
        fig = px.pie(pie_df, values='市值', names='標的', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textposition='inside', textinfo='percent+label') 
        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)") 
        st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("📜 管理交易紀錄")

# 1. 準備原始資料
h_df = user_df[user_df['Account'] == sel_acc].copy()
h_df['Date'] = pd.to_datetime(h_df['Date'], errors='coerce').dt.date
h_df = h_df.dropna(subset=['Date']).sort_values('Date', ascending=False)

# 💡 算出總共有幾筆資料
record_count = len(h_df)

# 將筆數顯示在標題上，並把操作提示改成小字 (caption) 讓畫面更乾淨
st.write(f"#### 📝 詳細紀錄明細 (共 {record_count} 筆)")
st.caption("💡 提示：點擊表格欄位可直接修改數字，勾選最左側框框即可刪除。")

display_cols = ['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']
display_df = h_df[display_cols].copy()
display_df.insert(0, "🗑️ 刪除", False)

# ... (下方接續原本的 edited_df = st.data_editor(...) 程式碼保持不變)

# 2. 🌟 終極互動表格：解鎖所有欄位供編輯！
edited_df = st.data_editor(
    display_df,
    column_config={
        "🗑️ 刪除": st.column_config.CheckboxColumn("🗑️ 刪除", default=False),
        "id": None, # 隱藏 ID
        "Date": st.column_config.DateColumn("📅 日期", format="YYYY-MM-DD"),
        "Type": st.column_config.SelectboxColumn("🔄 類型", options=["Buy", "Sell", "Cash_Div", "Stock_Div"]),
        "Symbol": st.column_config.TextColumn("🏷️ 代號"),
        "Shares": st.column_config.NumberColumn("🔢 股數"),
        "Price": st.column_config.NumberColumn("💲 單價", format="%.2f"),
        "Total_Amount": st.column_config.NumberColumn("💰 總額"),
        "Unit_Cost": st.column_config.NumberColumn("🪙 均價", format="%.2f"),
    },
    disabled=["id"], # 🔒 只有 id 是鎖定不能改的，其他全部開放編輯！
    hide_index=True,
    use_container_width=True,
    key="tx_editor" # 🔑 設定 key 來捕捉你修改了什麼
)

# ==========================================
# 動作 A：處理刪除 (保持原本的邏輯)
# ==========================================
deleted_ids = edited_df[edited_df["🗑️ 刪除"] == True]["id"].tolist()

if len(deleted_ids) > 0:
    if st.button(f"🚨 確認刪除選取的 {len(deleted_ids)} 筆紀錄", type="primary", use_container_width=True):
        updated_full_df = full_df[~full_df['id'].isin(deleted_ids)]
        conn.update(worksheet="Database", data=updated_full_df)
        st.cache_data.clear()
        st.session_state.my_data = updated_full_df
        st.success("✅ 已成功刪除！")
        st.rerun()

# ==========================================
# 動作 B：處理修改 (神級新功能)
# ==========================================
editor_state = st.session_state.get("tx_editor", {})
edited_rows = editor_state.get("edited_rows", {})

# 過濾出「不是打勾刪除」的真正資料修改
real_edits = {}
for row_idx, edits in edited_rows.items():
    meaningful_edits = {k: v for k, v in edits.items() if k != "🗑️ 刪除"}
    if meaningful_edits:
        real_edits[row_idx] = meaningful_edits

# 如果偵測到你有改數字，就跳出儲存按鈕
if len(real_edits) > 0:
    st.info("✏️ 系統偵測到您修改了資料，請點擊下方按鈕儲存變更：")
    if st.button("💾 儲存修改", type="secondary", use_container_width=True):
        updated_full_df = full_df.copy()
        
        # 找出你改了哪一列的哪個欄位，把它寫進總資料庫
        for row_idx, edits in real_edits.items():
            record_id = display_df.iloc[row_idx]['id']
            for col_name, new_val in edits.items():
                updated_full_df.loc[updated_full_df['id'] == record_id, col_name] = new_val
                
        # 寫回 Google Sheets
        conn.update(worksheet="Database", data=updated_full_df)
        st.cache_data.clear()
        st.session_state.my_data = updated_full_df
        st.success("✅ 已成功儲存修改！")
        st.rerun()
