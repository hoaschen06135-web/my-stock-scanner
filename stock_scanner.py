import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import urllib3
from io import StringIO
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# 基礎環境設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端篩選系統")

# --- 1. 同步與讀取函數 ---
def sync_to_sheets(watchlist):
    """將清單寫回 Google Sheets"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗：{e}")
        return False

def load_watchlist():
    """從 Google Sheets 讀取最新的關注清單"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        if not df.empty and "ticker_item" in df.columns:
            return df["ticker_item"].dropna().unique().tolist()
        return []
    except:
        return []

# --- 2. 初始化 Session State ---
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = load_watchlist()

if 'last_scan_time' not in st.session_state:
    st.session_state['last_scan_time'] = datetime.now() - timedelta(seconds=60)

# --- 3. 核心數據抓取邏輯 (恢復真實抓取) ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    
    # 真正的 yfinance 數據抓取
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    if data.empty: return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            # 取得換手率所需資訊
            tk = yf.Ticker(t)
            shares = tk.info.get('sharesOutstanding', 1)
            turnover = round((t_data['Volume'].iloc[-1] / shares) * 100, 2)
            mcap = f"{round(tk.info.get('marketCap', 0)/1e8, 2)} 億"

            # 篩選條件
            if low_chg <= change <= high_chg and \
               low_vol <= vol_ratio <= high_vol and \
               low_turn <= turnover <= high_turn:
                results.append({
                    "選取": False, 
                    "股票代號": t, 
                    "名稱": mapping[t], 
                    "漲幅": change, 
                    "量比": vol_ratio, 
                    "換手率": turnover, 
                    "流通市值": mcap
                })
        except: continue
    return pd.DataFrame(results)

# --- 4. 側邊欄與導航 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

# --- 頁面一：全市場掃描 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    
    sel_g = st.sidebar.selectbox("1. 選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    single_search = st.sidebar.text_input("🔍 2. 單一股票搜尋 (如 2330)")
    
    st.sidebar.subheader("3. 篩選參數設定")
    l_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    h_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    l_vol = st.sidebar.number_input("量比下限", value=1.0)
    h_vol = st.sidebar.number_input("量比上限", value=99.0)
    l_turn = st.sidebar.number_input("換手下限 (%)", value=0.5)
    h_turn = st.sidebar.number_input("換手上限 (%)", value=99.0)
    
    wait = max(0, int(15 - (datetime.now() - st.session_state['last_scan_time']).total_seconds()))
    if wait > 0:
        st.sidebar.warning(f"⏳ 冷卻中，請等候 {wait} 秒")
        btn_active = False
    else:
        st.sidebar.success("✅ 系統就緒")
        btn_active = True

    if st.button("🚀 開始掃描", disabled=not btn_active):
        st.session_state['last_scan_time'] = datetime.now()
        with st.spinner("正在抓取即時數據..."):
            target = [f"{single_search.strip()}.TW,搜尋結果"] if single_search.strip() else tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
            st.session_state['scan_res'] = fetch_stock_data(target, l_chg, h_chg, l_vol, h_vol, l_turn, h_turn)
            st.rerun()

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            edit_df = st.data_editor(df, hide_index=True, width="full", key="editor")
            if st.button("➕ 同步選中項目至雲端"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(item)
                if sync_to_sheets(st.session_state['watchlist']):
                    st.success("✅ 同步成功！請切換到『我的關注清單』查看。")
        else:
            st.warning("查無符合條件的股票。")

# --- 頁面二：我的關注清單 ---
elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    
    if st.button("🔄 重新從雲端抓取"):
        st.session_state['watchlist'] = load_watchlist()
        st.rerun()
    
    current_list = st.session_state['watchlist']
    
    if current_list:
        display_data = []
        for item in current_list:
            tk, name = item.split(',')
            display_data.append({"刪除": False, "股票代號": tk, "名稱": name})
        
        watch_df = pd.DataFrame(display_data)
        edited_watch = st.data_editor(watch_df, hide_index=True, width="full", key="watch_editor")
        
        if st.button("💾 儲存修改 (刪除選中項)"):
            new_list = []
            for _, r in edited_watch.iterrows():
                if not r["刪除"]:
                    new_list.append(f"{r['股票代號']},{r['名稱']}")
            st.session_state['watchlist'] = new_list
            if sync_to_sheets(new_list):
                st.success("✅ 修改已儲存至雲端")
                st.rerun()
    else:
        st.info("目前清單是空的，請先到『全市場分組掃描』加入股票。")
