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

# --- 1. 同步與讀取函數 (定義在最上方避免 NameError) ---
def sync_to_sheets(watchlist):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗：{e}")
        return False

def load_watchlist():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        return df["ticker_item"].dropna().unique().tolist() if not df.empty else []
    except:
        return []

# --- 2. 初始化與數據抓取 ---
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = load_watchlist()

@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    res = requests.get(url, verify=False)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    # 恢復真實抓取數據，移除寫死的 2330
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    if data.empty: return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty: continue
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            if low_chg <= change <= high_chg and low_vol <= vol_ratio <= high_vol:
                results.append({"選取": False, "股票代號": t, "名稱": mapping[t], "漲幅": change, "量比": vol_ratio})
        except: continue
    return pd.DataFrame(results)

# --- 3. 介面邏輯 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    sel_g = st.sidebar.selectbox("1. 選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    
    if st.button("🚀 開始掃描"):
        target = tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
        st.session_state['scan_res'] = fetch_stock_data(target, 0.0, 10.0, 1.0, 99.0, 0.5, 99.0)

    if 'scan_res' in st.session_state:
        # 修正：改回 use_container_width=True 以解決 WidthError
        edit_df = st.data_editor(st.session_state['scan_res'], hide_index=True, use_container_width=True, key="editor")
        if st.button("➕ 加入 Google Sheets"):
            to_add = edit_df[edit_df["選取"] == True]
            for _, r in to_add.iterrows():
                st.session_state['watchlist'].append(f"{r['股票代號']},{r['名稱']}")
            if sync_to_sheets(st.session_state['watchlist']):
                st.success("同步成功！")
