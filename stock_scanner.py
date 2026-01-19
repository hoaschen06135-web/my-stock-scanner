import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import urllib3
import plotly.graph_objects as go
from io import StringIO
from streamlit_gsheets import GSheetsConnection

# --- 1. 環境設定與 Google Sheets 連線 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

# 建立連線
conn = st.connection("gsheets", type=GSheetsConnection)

def sync_to_sheets(watchlist):
    """將清單同步回 Google Sheets"""
    new_df = pd.DataFrame({"ticker_item": watchlist})
    conn.update(worksheet="Sheet1", data=new_df)

# 初始化關注名單 (解決 NameError)
if 'watchlist' not in st.session_state:
    try:
        df = conn.read(worksheet="Sheet1", ttl="0")
        st.session_state['watchlist'] = df["ticker_item"].dropna().tolist() if not df.empty else []
    except:
        st.session_state['watchlist'] = []

# --- 2. 數據抓取函數 (解決 read_html 棄用警告) ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    urls = [("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", ".TW")]
    ticker_data = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url, suffix in urls:
        try:
            res = requests.get(url, headers=headers, verify=False, timeout=10)
            # 修正警告：使用 StringIO 包裝內容
            df = pd.read_html(StringIO(res.text))[0].iloc[1:]
            for val in df[0]:
                if '　' in str(val):
                    code = val.split('　')[0].strip()
                    name = val.split('　')[1].strip()
                    if code.isdigit() and len(code) == 4:
                        ticker_data.append(f"{code}{suffix},{name}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_stock_data(tickers_with_names, low_chg=0.0, high_chg=10.0, low_vol=0.0, high_vol=99.0, low_turn=0.0, high_turn=99.0):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    # 這裡加入錯誤處理，若 Yahoo 沒回傳資料，會拋出明確訊息
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t]
            if t_data.empty or len(t_data) < 2: continue
            if isinstance(t_data.columns, pd.MultiIndex): t_data.columns = t_data.columns.get_level_values(0)
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = round(t_data['Volume'].iloc[-1] / vol_avg, 2) if vol_avg > 0 else 0
            info = yf.Ticker(t).info
            turnover = round((t_data['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100, 2)
            mcap = f"{round(info.get('marketCap', 0) / 1e8, 2)} 億"

            if not (low_chg <= change <= high_chg and low_vol <= vol_ratio <= high_vol and low_turn <= turnover <= high_turn): continue
            results.append({"選取": False, "股票代號": t, "名稱": mapping[t], "漲幅": change, "量比": vol_ratio, "換手率": turnover, "流通市值": mcap})
        except: continue
    return pd.DataFrame(results)

# --- 3. 頁面邏輯 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    num_p_g = 100
    num_groups = math.ceil(len(tickers) / num_p_g)
    sel_g = st.sidebar.selectbox("選擇掃描群組", [f"第 {i+1} 組" for i in range(num_groups)])
    
    st.sidebar.subheader("🔍 篩選參數")
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=3.0)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=5.0)
    low_vol = st.sidebar.number_input("量比下限", value=1.0)
    low_turn = st.sidebar.number_input("換手率下限 (%)", value=3.0)
    
    if st.button("🚀 開始掃描"):
        with st.spinner(f"正在掃描 {sel_g}..."):
            idx = int(sel_g.split(' ')[1]) - 1
            st.session_state['scan_res'] = fetch_stock_data(tickers[idx*num_p_g : (idx+1)*num_p_g], low_chg, high_chg, low_vol, 99.0, low_turn, 99.0)

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            # 修正 InvalidWidthError
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 加入關注清單"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']: st.session_state['watchlist'].append(item)
                sync_to_sheets(st.session_state['watchlist'])
                st.success("同步成功！資料已寫入雲端。")
        else:
            st.warning("當前條件下無符合標的，或是 Yahoo 數據暫時無法抓取。請稍候再試。")
