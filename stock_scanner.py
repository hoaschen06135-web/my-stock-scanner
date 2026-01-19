import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import time
import urllib3
from io import StringIO
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# 基礎環境設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

# --- 1. 定義同步函數 (放在最上方避免 NameError) ---
def sync_to_sheets(watchlist):
    """將清單同步寫回雲端試算表"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        # 確保工作表名稱為 Sheet1
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"同步失敗：{e}")
        return False

# --- 2. 初始化連線與 Session State ---
if 'watchlist' not in st.session_state:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        st.session_state['watchlist'] = df["ticker_item"].dropna().tolist() if not df.empty else []
    except:
        st.session_state['watchlist'] = []

if 'last_scan_time' not in st.session_state:
    st.session_state['last_scan_time'] = datetime.now() - timedelta(seconds=60)

# --- 3. 數據抓取邏輯 (修正棄用警告) ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] if '　' in str(val) and str(val).split('　')[0].isdigit() and len(str(val).split('　')[0]) == 4]

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False, threads=False)
    if data.empty: return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            if isinstance(t_data.columns, pd.MultiIndex): t_data.columns = t_data.columns.get_level_values(0)
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            info = yf.Ticker(t).info
            turnover = round((t_data['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100, 2)
            
            if low_chg <= change <= high_chg and low_vol <= vol_ratio <= high_vol and low_turn <= turnover <= high_turn:
                results.append({"選取": False, "股票代號": t, "名稱": mapping[t], "漲幅": change, "量比": vol_ratio, "換手率": turnover, "流通市值": f"{round(info.get('marketCap', 0)/1e8, 2)} 億"})
        except: continue
    return pd.DataFrame(results)

# --- 4. 介面與冷卻機制 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    
    sel_g = st.sidebar.selectbox("選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    single_search = st.sidebar.text_input("🔍 單一股票搜尋 (如 2330)")
    
    # 參數設定
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    col1, col2 = st.sidebar.columns(2)
    low_vol, high_vol = col1.number_input("量比下限", value=1.0), col2.number_input("量比上限", value=99.0)
    
    # 冷卻計時器
    time_diff = (datetime.now() - st.session_state['last_scan_time']).total_seconds()
    wait_time = max(0, int(15 - time_diff))
    
    if wait_time > 0:
        st.sidebar.warning(f"⏳ 請稍候 {wait_time} 秒再進行下一次掃描")
        btn_active = False
    else:
        st.sidebar.success("✅ 系統已就緒")
        btn_active = True

    if st.button("🚀 開始掃描", disabled=not btn_active):
        st.session_state['last_scan_time'] = datetime.now()
        target = [f"{single_search.strip()}.TW,搜尋結果"] if single_search.strip() else tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
        st.session_state['scan_res'] = fetch_stock_data(target, low_chg, high_chg, low_vol, high_vol, 0, 99)
        st.rerun()

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 加入 Google Sheets"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']: st.session_state['watchlist'].append(item)
                if sync_to_sheets(st.session_state['watchlist']):
                    st.success("同步成功！已寫入試算表。")
        else:
            st.warning("查無符合標的。")
