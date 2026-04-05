import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import streamlit.components.v1 as components
from pyxirr import xirr
from datetime import datetime
from supabase import create_client, Client # 🌟 換成 Supabase 套件
import requests

# ==========================================
# 1. 網頁基本設定 & Supabase 連線
# ==========================================
st.set_page_config(page_title="股票追蹤系統", page_icon="📈", layout="wide")
st.title("📈 股票追蹤系統")

# 🌟 啟動 Supabase 光速引擎
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

def login_system():
    if "current_user" in st.session_state:
        return True

    st.subheader("🔐 系統登入與註冊")
    tab1, tab2 = st.tabs(["🔑 登入", "📝 註冊帳號"])

    with tab1:
        with st.form("login_form"):
            l_user = st.text_input("👤 帳號").strip()
            l_pw = st.text_input("🔒 密碼", type="password").strip()
            if st.form_submit_button("登入"):
                if l_user == "" or l_pw == "":
                    st.warning("請輸入帳號密碼")
                else:
                    # 🌟 瞬間去資料庫比對帳號密碼！
                    res = supabase.table("users").select("*").eq("username", l_user).eq("password", l_pw).execute()
                    if len(res.data) > 0:
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
                elif len(r_user) < 3 or len(r_pw) < 4:
                    st.error("⚠️ 帳號至少 3 碼，密碼至少 4 碼")
                else:
                    # 檢查帳號是否重複
                    check = supabase.table("users").select("username").eq("username", r_user).execute()
                    if len(check.data) > 0:
                        st.error("⚠️ 此帳號已經有人使用了，請換一個！")
                    else:
                        # 🌟 寫入新帳號
                        supabase.table("users").insert({"username": r_user, "password": r_pw}).execute()
                        st.success("✅ 註冊成功！請切換到「登入」分頁進行登入。")

    return False

if not login_system():
    st.stop()

USER = st.session_state["current_user"]

# ==========================================
# 2. 資料庫連線 (瞬間拉取資料)
# ==========================================
# 🌟 直接從 transactions 資料表撈出所有資料
response = supabase.table("transactions").select("*").execute()
full_df = pd.DataFrame(response.data)

# 如果資料庫是空的，給它一個預設的小寫骨架
expected_cols_lower = ['id', 'username', 'account', 'date', 'type', 'symbol', 'shares', 'price', 'fee', 'tax', 'total_amount', 'unit_cost']
if full_df.empty:
    full_df = pd.DataFrame(columns=expected_cols_lower)

# 💡 終極防呆：不管資料庫傳來什麼，先全部轉小寫，再統一翻譯成系統認得的大寫開頭！
full_df.columns = [str(c).lower() for c in full_df.columns]
rename_map = {
    'username': 'Username', 'account': 'Account', 'date': 'Date', 'type': 'Type', 
    'symbol': 'Symbol', 'shares': 'Shares', 'price': 'Price', 'fee': 'Fee', 
    'tax': 'Tax', 'total_amount': 'Total_Amount', 'unit_cost': 'Unit_Cost'
}
full_df = full_df.rename(columns=rename_map)

# 🌟 整理資料與強制轉型
if not full_df.empty:
    full_df['id'] = full_df['id'].astype(int)
    full_df['Date'] = pd.to_datetime(full_df['Date'], errors='coerce')
    
    # 強制把所有跟錢、股數有關的欄位變成真正的數字，把空缺補 0
    for col in ['Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']:
        full_df[col] = pd.to_numeric(full_df[col], errors='coerce').fillna(0)
        
    # 剔除沒有日期的無效資料，並按日期排序
    full_df = full_df.dropna(subset=['Date']).sort_values('Date')

# 🛡️ 隱形的牆：只抓取屬於當前登入者的資料
user_df = full_df[full_df['Username'] == USER].copy()

# ==========================================
# 3. 核心功能：抓取單純股價 (三重保險版)
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
            
            # 保險 1：嘗試用最快的 fast_info 抓取
            try:
                price = ticker.fast_info['lastPrice']
                if price > 0: return round(price, 2)
            except: pass
            
            # 保險 2：嘗試用原本的 history 抓取
            history = ticker.history(period="1d")
            if not history.empty:
                return round(history['Close'].iloc[-1], 2)
        except:
            continue
            
    # 🌟 終極保險 3：如果 yfinance 徹底罷工，我們自己寫爬蟲去 Yahoo 抓！
    try:
        tw_symbol = f"{symbol}.TW" if "." not in symbol else symbol
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tw_symbol}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        price = data['chart']['result'][0]['meta']['regularMarketPrice']
        if price > 0: return round(price, 2)
    except:
        pass

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

        # 🌟 寫入時，欄位名稱必須改成「小寫」來對應 Supabase 資料庫！
        new_row = {
            'username': USER,
            'account': final_account,
            'date': f_date.strftime("%Y-%m-%d"),
            'type': f_type,
            'symbol': final_symbol,
            'shares': float(f_shares),
            'price': round(float(calc_price), 2),
            'fee': float(f_fee),
            'tax': float(f_tax),
            'total_amount': round(float(f_total_all_in), 2),
            'unit_cost': round(float(unit_cost), 2)
        }
        
        # 💡 光速寫入！直接呼叫 Supabase 的 insert 魔法
        supabase.table("transactions").insert(new_row).execute()
        
        st.sidebar.success("✅ 成功寫入！")
        st.rerun() # 直接重整，網頁會瞬間去要最新資料


# ==========================================
# 🌟 新增：批次匯入檔案功能 (自動計算 Price 與 Unit_Cost)
# ==========================================
with st.sidebar.expander("📂 批次匯入紀錄 (CSV)"):
    st.markdown("👉 **步驟 1：下載標準範本**")
    st.caption("⚠️ `Type` 請填寫：`Buy`, `Sell`, `Cash_Div`, `Stock_Div`")
    
    # 🌟 產生小寫欄位的 CSV 範本
    template_df = pd.DataFrame(columns=['account', 'date', 'type', 'symbol', 'shares', 'fee', 'tax', 'total_amount'])
    csv_template = template_df.to_csv(index=False).encode('utf-8-sig')
        
    st.download_button(
        label="📥 下載 CSV 匯入範本",
        data=csv_template,
        file_name="import_template.csv",
        mime="text/csv"
    )
    
    st.markdown("👉 **步驟 2：上傳填妥的 CSV**")
    uploaded_file = st.file_uploader("選擇檔案", type=["csv"], label_visibility="collapsed")
    
    if uploaded_file is not None:
        if st.button("🚀 確認批次匯入", type="primary", use_container_width=True):
            try:
                # 🌟 智慧判斷編碼：先嘗試 UTF-8，失敗的話就切換成 Excel 中文版愛用的 Big5
                try:
                    import_df = pd.read_csv(uploaded_file)
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    import_df = pd.read_csv(uploaded_file, encoding='big5')
                    
                template_cols = template_df.columns.tolist()
                
                # 防呆 1：檢查欄位有沒有被亂改 (忽略大小寫比較)
                import_cols_lower = [str(c).lower() for c in import_df.columns]
                if not all(col in import_cols_lower for col in template_cols):
                    st.error("❌ 欄位錯誤！請確保使用剛下載的最新範本。")
                elif import_df.empty:
                    st.warning("⚠️ 檔案裡面沒有資料喔！")
                else:
                    # 統一將上傳的欄位轉成首字母大寫，方便後續計算邏輯
                    import_df.columns = import_cols_lower
                    rename_import_map = {
                        'account': 'Account', 'date': 'Date', 'type': 'Type', 
                        'symbol': 'Symbol', 'shares': 'Shares', 
                        'fee': 'Fee', 'tax': 'Tax', 'total_amount': 'Total_Amount'
                    }
                    import_df = import_df.rename(columns=rename_import_map)
                    
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
                    
                    # 💡 亮點 3：在 Supabase 裡，我們不需要自己算 id 了！
                    # 整理要匯入的欄位，並把大寫的欄位名稱轉成「小寫」，對應資料庫格式
                    final_import_df = import_df[['Username', 'Account', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Fee', 'Tax', 'Total_Amount', 'Unit_Cost']].copy()
                    final_import_df.columns = final_import_df.columns.str.lower()
                    
                    # 🌟 將表格轉換成「字典列表 (List of Dictionaries)」的格式
                    records_to_insert = final_import_df.to_dict(orient='records')
                    
                    # 🚀 呼叫 Supabase 進行「批次光速寫入」
                    supabase.table("transactions").insert(records_to_insert).execute()
                    
                    st.success(f"✅ 成功匯入 {len(import_df)} 筆紀錄，資料庫已自動分配流水號！")
                    st.rerun()
                    
            except Exception as e:
                st.error(f"❌ 匯入時發生錯誤：{e}")
# ==========================================
# 🛠️ 側邊欄：帳戶與標的批次管理工具
# ==========================================
st.sidebar.markdown("---")
with st.sidebar.expander("🛠️ 帳戶與標的管理 (改名/刪除)"):
    st.caption("如果打錯字或想清空某個帳戶/股票，可以在這裡批次處理。")
    manage_type = st.radio("你要管理什麼？", ["🏦 帳戶", "🏷️ 股票標的"])
    
    if manage_type == "🏦 帳戶":
        target_list = user_df['Account'].unique().tolist() if not user_df.empty else []
        if target_list:
            old_name = st.selectbox("選擇要處理的帳戶", target_list)
            new_name = st.text_input("輸入新帳戶名稱 (若只是要刪除請留白)")
            
            col1, col2 = st.columns(2)
            if col1.button("📝 批次改名"):
                if new_name:
                    # 呼叫 Supabase 把該帳戶的所有紀錄換成新名字
                    supabase.table("transactions").update({"account": new_name}).eq("account", old_name).eq("username", USER).execute()
                    st.sidebar.success(f"✅ 已全數更新為 {new_name}")
                    st.rerun()
                else:
                    st.sidebar.warning("請輸入新名稱")
                    
            if col2.button("🚨 刪除帳戶"):
                # 呼叫 Supabase 刪除該帳戶的所有紀錄
                supabase.table("transactions").delete().eq("account", old_name).eq("username", USER).execute()
                st.sidebar.success(f"✅ {old_name} 及底下所有紀錄已刪除")
                st.rerun()
        else:
            st.write("目前沒有任何帳戶。")
            
    else:
        target_list = user_df['Symbol'].unique().tolist() if not user_df.empty else []
        if target_list:
            old_name = st.selectbox("選擇要處理的標的", target_list)
            new_name = st.text_input("輸入新標的代號 (若只是要刪除請留白)")
            
            col1, col2 = st.columns(2)
            if col1.button("📝 批次改名 "):
                if new_name:
                    # 呼叫 Supabase 把該股票的所有紀錄換成新名字
                    supabase.table("transactions").update({"symbol": new_name}).eq("symbol", old_name).eq("username", USER).execute()
                    st.sidebar.success(f"✅ 已全數更新為 {new_name}")
                    st.rerun()
                else:
                    st.sidebar.warning("請輸入新代號")
                    
            if col2.button("🚨 刪除標的"):
                # 呼叫 Supabase 刪除該股票的所有紀錄
                supabase.table("transactions").delete().eq("symbol", old_name).eq("username", USER).execute()
                st.sidebar.success(f"✅ {old_name} 及底下所有紀錄已刪除")
                st.rerun()
        else:
            st.write("目前沒有任何標的。")

# ==========================================
# 5. 資料處理邏輯 (新增今年以來的計算)
# ==========================================
accounts_data = {}
current_year = datetime.today().year # 🌟 抓取今年的年份

if not user_df.empty:
    for _, row in user_df.iterrows():
        acc = str(row['Account']).strip()
        if acc not in accounts_data: accounts_data[acc] = {'inventory': {}, 'cash_flows': []}
        inv = accounts_data[acc]['inventory']
        sym, t_type, shares = row['Symbol'], row['Type'], row['Shares']
        
        total_amt = row['Total_Amount'] if 'Total_Amount' in row and pd.notnull(row['Total_Amount']) else ((row['Shares']*row['Price'])+row['Fee'])

        # 💡 字典裡多加一個 'ytd_rpnl' 用來單獨存「今年的獲利」
        if sym not in inv: inv[sym] = {'shares': 0, 'total_cost': 0.0, 'realized_pnl': 0.0, 'ytd_rpnl': 0.0}

        is_this_year = (row['Date'].year == current_year) # 判斷這筆交易是不是今年的

        if t_type == 'Buy':
            inv[sym]['shares'] += shares
            inv[sym]['total_cost'] += total_amt
            accounts_data[acc]['cash_flows'].append((row['Date'], -total_amt))
        elif t_type == 'Sell':
            if inv[sym]['shares'] > 0:
                avg_cost = inv[sym]['total_cost'] / inv[sym]['shares']
                trade_pnl = total_amt - (avg_cost * shares)
                
                inv[sym]['realized_pnl'] += trade_pnl
                if is_this_year: inv[sym]['ytd_rpnl'] += trade_pnl # 🌟 如果是今年賣的，記一筆！
                
                inv[sym]['total_cost'] -= (avg_cost * shares)
                inv[sym]['shares'] -= shares
                accounts_data[acc]['cash_flows'].append((row['Date'], total_amt))
        elif t_type == 'Cash_Div':
            inv[sym]['realized_pnl'] += total_amt
            if is_this_year: inv[sym]['ytd_rpnl'] += total_amt # 🌟 如果是今年領的股利，記一筆！
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
t_net_mv = 0.0  # 🌟 新增：用來裝「扣除稅費後的淨市值」

# 取得原本的總結算
t_rpnl = sum(inv_item['realized_pnl'] for inv_item in data['inventory'].values())

# 🌟 取得「今年」的已實現損益總結算
t_ytd_rpnl = sum(inv_item['ytd_rpnl'] for inv_item in data['inventory'].values())

# 🌟 計算「今年淨投入本金」(今年買進花掉的錢 - 今年賣出拿回的錢)
ytd_net_invest = sum(-cf[1] for cf in data['cash_flows'] if cf[0].year == current_year)

for sym, d in data['inventory'].items():
    current_shares = round(d['shares'], 2)
    if current_shares > 0:
        cur_p = get_stock_info(sym) 
        
        mv = cur_p * d['shares']
        est_sell_cost = mv * 0.003 + mv * 0.001425
        net_market_value = mv - est_sell_cost
        upnl = net_market_value - d['total_cost'] if cur_p > 0 else 0.0
        
        # 🌟 新增：計算這檔股票的「歷史總投入本金」當作分母
        sym_df = user_df[(user_df['Account'] == sel_acc) & (user_df['Symbol'] == sym)]
        total_buy_sym = pd.to_numeric(sym_df[sym_df['Type'].astype(str).str.contains('buy|買', case=False, na=False)]['Total_Amount'], errors='coerce').sum()
        
        # 🌟 新增：該標的的終極總報酬率 = (未實現 + 已實現) / 歷史總本金
        roi_sym = ((upnl + d['realized_pnl']) / total_buy_sym * 100) if total_buy_sym > 0 else 0

        t_mv += mv
        t_cost += d['total_cost']
        t_upnl += upnl
        t_net_mv += net_market_value  # (確保上次修改的淨值變數有留著)
        
        p_data.append({
            "標的": sym, 
            "股數": int(d['shares']), 
            "含費均價": d['total_cost']/d['shares'],
            "最新現價": cur_p, 
            "市值": int(round(mv, 0)), 
            "未實現損益": int(round(upnl, 0)), 
            "已實現損益": int(round(d['realized_pnl'], 0)), 
            "總報酬 %": roi_sym  # 🌟 這裡把原本的「未實現報酬 %」換掉了！
        })
        
# ------------------------------------------
# A. 投資總覽區塊
# ------------------------------------------
st.subheader("📊 投資總覽")

account_df = user_df[user_df['Account'] == sel_acc]
historical_total_buy = account_df[account_df['Type'].astype(str).str.contains('buy|買', case=False, na=False)]['Total_Amount'].sum()
overall_roi = ((t_upnl + t_rpnl) / historical_total_buy * 100) if historical_total_buy > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("💰 總市值", f"${int(round(t_mv, 0)):,}") 
c2.metric("🪙 總投資成本", f"${int(round(t_cost, 0)):,}", delta=f"{int(round(ytd_net_invest, 0)):,}", delta_color="off")
c3.metric("📉 未實現損益", f"${int(round(t_upnl, 0)):,}") 

c4, c5, c6 = st.columns(3)
c4.metric("🧧 已實現損益", f"${int(round(t_rpnl, 0)):,}", delta=f"{int(round(t_ytd_rpnl, 0)):,}", delta_color="inverse")
c5.metric("📈 總報酬率", f"{overall_roi:.2f}%") 

temp_cf = data['cash_flows'].copy()
if t_net_mv > 0: temp_cf.append((pd.to_datetime(datetime.today().date()), t_net_mv))
try: x_val = xirr([cf[0] for cf in temp_cf], [cf[1] for cf in temp_cf]) * 100 if len(temp_cf) >= 2 else 0
except: x_val = 0
c6.metric("📊 年化報酬 (XIRR)", f"{x_val:.2f}%")

# ------------------------------------------
# B. 庫存與歷史明細區塊
# ------------------------------------------
st.divider()
st.subheader("📋 庫存與歷史明細")

def color_profit_loss(val):
    if isinstance(val, (int, float)):
        if val > 0: return 'color: #ff4b4b;'
        elif val < 0: return 'color: #09ab3b;'
    return ''

tab1, tab2 = st.tabs(["📊 現有庫存", "🏁 已出清明細"])

with tab1:
    if p_data: 
        df_portfolio = pd.DataFrame(p_data)
        df_portfolio = df_portfolio.sort_values(by="標的", ascending=True).reset_index(drop=True)
        try: 
            styled_df = df_portfolio.style.map(color_profit_loss, subset=['未實現損益', '已實現損益', '總報酬 %'])
        except AttributeError: 
            styled_df = df_portfolio.style.applymap(color_profit_loss, subset=['未實現損益', '已實現損益', '總報酬 %'])

        styled_df = styled_df.format({
            "股數": "{:,}", "含費均價": "{:.2f}", "最新現價": "{:.2f}", 
            "市值": "{:,}", "未實現損益": "{:,}", "已實現損益": "{:,}", "總報酬 %": "{:.2f}%"
        })
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("目前無庫存資料。")

with tab2:
    cleared_data = []
    for sym, d in data['inventory'].items():
        if round(d['shares'], 2) <= 0:
            sym_df = user_df[(user_df['Account'] == sel_acc) & (user_df['Symbol'] == sym)]
            total_buy = pd.to_numeric(sym_df[sym_df['Type'] == 'Buy']['Total_Amount'], errors='coerce').sum()
            total_sell = pd.to_numeric(sym_df[sym_df['Type'] == 'Sell']['Total_Amount'], errors='coerce').sum()
            total_div = pd.to_numeric(sym_df[sym_df['Type'] == 'Cash_Div']['Total_Amount'], errors='coerce').sum() if 'Cash_Div' in sym_df['Type'].values else 0.0
            
            system_rpnl = d['realized_pnl']
            roi = (system_rpnl / total_buy * 100) if total_buy > 0 else 0.0
            cleared_data.append({
                "標的": sym, "總買進成本": int(total_buy), "總賣出收入": int(total_sell),
                "股利": int(total_div), "損益": int(round(system_rpnl, 0)), "總報酬 %": roi
            })
            
    if cleared_data:
        df_cleared = pd.DataFrame(cleared_data)
        df_cleared = df_cleared.sort_values(by="標的", ascending=True).reset_index(drop=True)
        try: 
            styled_cleared = df_cleared.style.map(color_profit_loss, subset=['損益', '總報酬 %'])
        except AttributeError: 
            styled_cleared = df_cleared.style.applymap(color_profit_loss, subset=['損益', '總報酬 %'])
        styled_cleared = styled_cleared.format({
            "總買進成本": "{:,}", "總賣出收入": "{:,}", "股利": "{:,}", "損益": "{:,}", "總報酬 %": "{:.2f}%"
        })
        st.dataframe(styled_cleared, use_container_width=True, hide_index=True)
    else:
        st.info("無已出清明細。")

# ------------------------------------------
# C. 資產配置區塊
# ------------------------------------------
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

# ------------------------------------------
# D. 管理交易紀錄區塊
# ------------------------------------------
st.divider()
st.subheader("📜 管理交易紀錄")

h_df = user_df[user_df['Account'] == sel_acc].copy()
h_df['Date'] = pd.to_datetime(h_df['Date'], errors='coerce').dt.date
h_df = h_df.dropna(subset=['Date']).sort_values('Date', ascending=False)

st.write(f"#### 📝 詳細紀錄明細 (共 {len(h_df)} 筆)")
st.caption("💡 提示：點擊表格可直接修改，勾選🗑️即可點擊下方按鈕刪除。")

display_cols = ['id', 'Date', 'Type', 'Symbol', 'Shares', 'Price', 'Total_Amount', 'Unit_Cost']
display_df = h_df[display_cols].copy()
display_df.insert(0, "🗑️ 刪除", False)

edited_df = st.data_editor(
    display_df,
    column_config={
        "🗑️ 刪除": st.column_config.CheckboxColumn("🗑️ 刪除", default=False),
        "id": None, 
        "Date": st.column_config.DateColumn("📅 日期", format="YYYY-MM-DD"),
        "Type": st.column_config.SelectboxColumn("🔄 類型", options=["Buy", "Sell", "Cash_Div", "Stock_Div"]),
        "Symbol": st.column_config.TextColumn("🏷️ 代號"),
        "Shares": st.column_config.NumberColumn("🔢 股數"),
        "Price": st.column_config.NumberColumn("💲 單價", format="%.2f"),
        "Total_Amount": st.column_config.NumberColumn("💰 總額"),
        "Unit_Cost": st.column_config.NumberColumn("🪙 均價", format="%.2f"),
    },
    disabled=["id"], 
    hide_index=True,
    use_container_width=True,
    key="tx_editor"
)

# 處理刪除
deleted_ids = edited_df[edited_df["🗑️ 刪除"] == True]["id"].tolist()
if len(deleted_ids) > 0:
    if st.button(f"🚨 確認刪除選取的 {len(deleted_ids)} 筆紀錄", type="primary", use_container_width=True):
        for d_id in deleted_ids:
            supabase.table("transactions").delete().eq("id", int(d_id)).execute()
        st.success("✅ 已成功刪除！")
        st.rerun()

# 處理修改
editor_state = st.session_state.get("tx_editor", {})
edited_rows = editor_state.get("edited_rows", {})
if edited_rows:
    st.info("✏️ 系統偵測到修改，請點擊下方儲存：")
    if st.button("💾 儲存修改", type="secondary", use_container_width=True):
        for row_idx, edits in edited_rows.items():
            record_id = int(display_df.iloc[row_idx]['id'])
            update_data = {}
            for col_name, new_val in edits.items():
                if col_name == 'Date' and new_val:
                    update_data[col_name.lower()] = new_val.strftime("%Y-%m-%d")
                else:
                    update_data[col_name.lower()] = new_val
            supabase.table("transactions").update(update_data).eq("id", record_id).execute()
        st.success("✅ 修改已儲存！")
        st.rerun()
