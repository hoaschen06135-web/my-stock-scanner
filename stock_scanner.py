import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import urllib3
from io import StringIO
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# 基礎環境設定，忽略安全證書警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端篩選系統")

# --- 1. 同步與讀取函數 (解決 NameError) ---
def sync_to_sheets(watchlist):
    """將關注清單同步回 Google Sheets"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        # ⚠️ 請確保您的試算表分頁名稱確實是 Sheet1
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗：{e}")
        return False

def load_watchlist():
    """從雲端讀取最新的關注清單"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        if not df.empty and "ticker_item" in df.columns:
            # 去除空值與重複項
            return df["ticker_item"].dropna().unique().tolist()
        return []
    except:
        return []

# --- 2. 初始化 Session State ---
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = load_watchlist()

# --- 3. 核心數據抓取邏輯 (全功能復原) ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    """從證交所抓取台股代號與名稱"""
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    """抓取即時行情並根據『設定條件』篩選"""
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    
    # 批次下載數據
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    if data.empty: return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            
            # 計算各項指標
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            # 取得個股詳細資訊 (換手率與市值)
            tk = yf.Ticker(t)
            shares = tk.info.get('sharesOutstanding', 1)
            turnover = round((t_data['Volume'].iloc[-1] / shares) * 100, 2)
            mcap = f"{round(tk.info.get('marketCap', 0)/1e8, 2)} 億"

            # 執行您設定的篩選條件
            if low_chg <= change <= high_chg and \
               low_vol <= vol_ratio <= high_vol and \
               low_turn <= turnover <= high_turn:
                results.append({
                    "選取": False, 
                    "股票代號": t, 
                    "名稱": mapping[t], 
                    "漲幅 (%)": change, 
                    "量比": vol_ratio, 
                    "換手率 (%)": turnover, 
                    "流通市值": mcap
                })
        except: continue
    return pd.DataFrame(results)

# --- 4. 側邊欄導覽與設定條件 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選系統")
    tickers = get_cleaned_tickers()
    
    # 復原所有的設定條件
    st.sidebar.subheader("1. 選擇範圍")
    sel_g = st.sidebar.selectbox("選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    
    st.sidebar.subheader("2. 篩選參數設定")
    l_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    h_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    l_vol = st.sidebar.number_input("量比下限", value=1.0)
    h_vol = st.sidebar.number_input("量比上限", value=99.0)
    l_turn = st.sidebar.number_input("換手下限 (%)", value=0.1)
    h_turn = st.sidebar.number_input("換手上限 (%)", value=99.0)
    
    if st.button("🚀 開始掃描"):
        with st.spinner("正在分析市場數據..."):
            target = tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
            st.session_state['scan_res'] = fetch_stock_data(target, l_chg, h_chg, l_vol, h_vol, l_turn, h_turn)
    
    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            # ⚠️ 修正 StreamlitInvalidWidthError：使用 use_container_width=True
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 同步選中項目至雲端清單"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(item)
                if sync_to_sheets(st.session_state['watchlist']):
                    st.success("✅ 已同步至雲端！切換到左側『我的關注清單』即可查看。")
        else:
            st.warning("目前市場中查無符合條件的股票，請嘗試調低篩選標準。")

# --- 頁面二：我的關注清單 (修復不顯示問題) ---
elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    
    if st.button("🔄 從雲端重新讀取"):
        st.session_state['watchlist'] = load_watchlist()
        st.rerun()
    
    current_list = st.session_state['watchlist']
    
    if current_list:
        display_data = []
        for item in current_list:
            if ',' in item:
                tk, name = item.split(',')
                display_data.append({"刪除": False, "股票代號": tk, "名稱": name})
        
        watch_df = pd.DataFrame(display_data)
        edited_watch = st.data_editor(watch_df, hide_index=True, use_container_width=True, key="watch_editor")
        
        if st.button("💾 儲存修改 (刪除選中項)"):
            new_list = [f"{r['股票代號']},{r['名稱']}" for _, r in edited_watch.iterrows() if not r["刪除"]]
            st.session_state['watchlist'] = new_list
            if sync_to_sheets(new_list):
                st.success("✅ 修改已儲存")
                st.rerun()
    else:
        st.info("目前清單是空的，請到『全市場分組掃描』頁面將股票加入。")
