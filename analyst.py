import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# 1. 初始化與環境設定
st.set_page_config(layout="wide", page_title="雙核心監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 2. Yahoo 數據抓取 (行情與換手率 - 不限額度)
@st.cache_data(ttl=600)
def get_yahoo_info(sid_tw):
    try:
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period='5d')
        shares = ticker.info.get('sharesOutstanding', 0)
        return hist, shares
    except:
        return pd.DataFrame(), 0

# 3. FinMind 籌碼抓取 (法人張數 - 消耗額度)
def get_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        # 增加保護延遲，防止 503 錯誤
        time.sleep(1) 
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 主介面邏輯
st.title("🚀 專業關注清單 (雙按鈕獨立版)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("清單為空。")
    st.stop()

# 遍歷每支股票顯示按鈕
for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid_tw})")
        
        # 建立兩個按鈕的欄位
        col_btn1, col_btn2 = st.columns(2)
        
        # 按鈕一：Yahoo 行情 (免 API 額度)
        with col_btn1:
            if st.button(f"🔍 點我更新：行情與換手率", key=f"y_btn_{sid}"):
                hist, shares = get_yahoo_info(sid_tw)
                if not hist.empty:
                    last_p = round(hist['Close'].iloc[-1], 2)
                    chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                    vol = hist['Volume'].iloc[-1]
                    # 使用 Yahoo 股本計算精確換手率
                    turnover = (vol / shares) * 100 if shares > 0 else 0
                    
                    color = "red" if chg > 0 else "green"
                    st.success(f"現價: {last_p} | 漲幅: {chg:.2f}%")
                    st.info(f"今日換手率: {turnover:.2f}%")
                else:
                    st.error("無法取得 Yahoo 行情，請稍後再試。")

        # 按鈕二：FinMind 法人籌碼 (消耗 API 額度)
        with col_btn2:
            if st.button(f"📊 點我更新：三大法人籌碼", key=f"fm_btn_{sid}"):
                chips = get_fm_chips(sid)
                if not chips.empty:
                    last_d = chips['date'].max()
                    today = chips[chips['date'] == last_d]
                    # 鎖定您的帳號環境診斷出的標籤
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    results = []
                    for label, kw in mapping.items():
                        r = today[today['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            c = "red" if n > 0 else "green"
                            results.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    st.markdown(f"🗓️ {last_d} | {' '.join(results)}", unsafe_allow_html=True)
                else:
                    st.warning("籌碼額度已滿或頻率過快，請稍等 1 分鐘再按")
