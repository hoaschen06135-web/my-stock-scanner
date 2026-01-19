import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# 1. 初始化與環境設定
st.set_page_config(layout="wide", page_title="雙核心監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 2. 建立偽裝瀏覽器的連線 Session，防止 Yahoo 限流
def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    return session

@st.cache_data(ttl=600)
def get_yahoo_info(sid_tw):
    try:
        # 使用自定義 Session 連線
        ticker = yf.Ticker(sid_tw, session=get_session())
        hist = ticker.history(period='5d')
        # 取得總股數以計算換手率
        info = ticker.info
        shares = info.get('sharesOutstanding', 0)
        
        if hist.empty:
            return pd.DataFrame(), 0, "Yahoo 回傳數據為空，請稍後再試。"
        return hist, shares, None
    except Exception as e:
        return pd.DataFrame(), 0, f"連線異常: {str(e)}"

# 3. FinMind 籌碼抓取 (獨立按鈕控制)
def get_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        time.sleep(1) # 保護延遲，防止 503 錯誤
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 主介面邏輯
st.title("🚀 專業關注清單 (修復限流版)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("請確認 Google Sheets 資料。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid_tw})")
        col_btn1, col_btn2 = st.columns(2)
        
        # 按鈕一：Yahoo 行情與換手率 (免 API 額度)
        with col_btn1:
            if st.button(f"🔍 點我更新：行情與換手率", key=f"y_btn_{sid}"):
                with st.spinner("正在偽裝請求..."):
                    hist, shares, err = get_yahoo_info(sid_tw)
                    if not hist.empty:
                        last_p = round(hist['Close'].iloc[-1], 2)
                        chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                        vol = hist['Volume'].iloc[-1]
                        # 換手率：(成交股數 / 總股數) * 100
                        turnover = (vol / shares) * 100 if shares > 0 else 0
                        
                        color = "red" if chg > 0 else "green"
                        st.success(f"現價: {last_p} | 漲幅: {chg:.2f}%")
                        st.info(f"今日換手率: {turnover:.2f}%")
                    else:
                        st.error(f"錯誤: {err}")

        # 按鈕二：FinMind 法人籌碼 (消耗額度)
        with col_btn2:
            if st.button(f"📊 點我更新：三大法人籌碼", key=f"fm_btn_{sid}"):
                with st.spinner("FinMind 數據抓取中..."):
                    chips = get_fm_chips(sid)
                    if not chips.empty:
                        last_d = chips['date'].max()
                        today = chips[chips['date'] == last_d]
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
                        st.warning("籌碼 API 頻率過快或額度不足")
