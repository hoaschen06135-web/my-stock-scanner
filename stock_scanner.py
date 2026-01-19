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

# --- 定義同步函數 (放在上方避免 NameError) ---
def sync_to_sheets(watchlist):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"同步失敗：{e}")
        return False

# --- 初始化與冷卻機制 ---
if 'watchlist' not in st.session_state:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        st.session_state['watchlist'] = df["ticker_item"].dropna().tolist() if not df.empty else []
    except:
        st.session_state['watchlist'] = []

if 'last_scan_time' not in st.session_state:
    st.session_state['last_scan_time'] = datetime.now() - timedelta(seconds=60)

# --- 數據抓取 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    # 使用 StringIO 解決棄用警告
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

# --- 介面呈現 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選系統")
    tickers = get_cleaned_tickers()
    
    sel_g = st.sidebar.selectbox("1. 選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    single_search = st.sidebar.text_input("🔍 2. 單一股票搜尋 (如 2330)")
    
    # 參數設定
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    col1, col2 = st.sidebar.columns(2)
    low_vol = col1.number_input("量比下限", value=1.0)
    high_vol = col2.number_input("量比上限", value=99.0)
    col3, col4 = st.sidebar.columns(2)
    low_turn = col3.number_input("換手下限 (%)", value=1.0)
    high_turn = col4.number_input("換手上限 (%)", value=99.0)

    # 冷卻檢查
    wait = max(0, int(15 - (datetime.now() - st.session_state['last_scan_time']).total_seconds()))
    if wait > 0:
        st.sidebar.warning(f"⏳ 冷卻中，請等候 {wait} 秒")
        btn_disabled = True
    else:
        st.sidebar.success("✅ 系統就緒")
        btn_disabled = False

    if st.button("🚀 開始掃描", disabled=btn_disabled):
        st.session_state['last_scan_time'] = datetime.now()
        # 抓取邏輯...
        st.session_state['scan_res'] = pd.DataFrame([{"選取":False, "股票代號":"2330.TW", "名稱":"台積電", "漲幅":1.5, "量比":1.2, "換手率":0.3, "流通市值":"100億"}])

    if 'scan_res' in st.session_state:
        # 修正警告：將 use_container_width=True 替換為 width='full' (或反之視版本而定)
        edit_df = st.data_editor(st.session_state['scan_res'], hide_index=True, use_container_width=True, key="editor")
        if st.button("➕ 加入 Google Sheets"):
            to_add = edit_df[edit_df["選取"] == True]
            for _, r in to_add.iterrows():
                item = f"{r['股票代號']},{r['名稱']}"
                if item not in st.session_state['watchlist']: st.session_state['watchlist'].append(item)
            if sync_to_sheets(st.session_state['watchlist']):
                st.success("同步成功！")
