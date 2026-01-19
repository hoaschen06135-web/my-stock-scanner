import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="雙核心監控站-穩定相容版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. Yahoo 數據抓取：移除自定義 Session，解決環境衝突 ---
@st.cache_data(ttl=600)
def fetch_market_data(sid_tw):
    try:
        # 直接使用 Ticker，不傳入自定義 Session
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period='5d')
        
        # 獲取總股數 (解決換手率 0% 問題)
        try:
            shares = ticker.fast_info.shares_outstanding
        except:
            shares = ticker.info.get('sharesOutstanding', 0)
            
        if not hist.empty:
            return hist, shares, None
        return pd.DataFrame(), 0, "暫無行情數據"
    except Exception as e:
        return pd.DataFrame(), 0, str(e)

# --- 3. FinMind 數據抓取 (認證帳戶專用) ---
def fetch_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        # 認證後可保持 0.5 秒緩衝
        time.sleep(0.5) 
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. 主介面顯示 ---
st.title("🚀 專業關注清單 (無衝突穩定版)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.error("請確認 Google Sheets 連線。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid_tw})")
        col_y, col_fm = st.columns(2)
        
        # 按鈕一：行情與換手率
        with col_y:
            if st.button(f"🔍 行情與換手率 ({sid})", key=f"y_{sid}"):
                with st.spinner("Yahoo 加載中..."):
                    h, s, err = fetch_market_data(sid_tw)
                    if not h.empty:
                        last_p = round(h['Close'].iloc[-1], 2)
                        chg = ((last_p - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
                        vol = h['Volume'].iloc[-1]
                        # 換手率公式：$$Turnover\ Rate = \frac{Volume}{Total\ Shares} \times 100\%$$
                        turnover = (vol / s) * 100 if s > 0 else 0
                        
                        color = "red" if chg > 0 else "green"
                        st.metric("現價", f"{last_p}", f"{chg:.2f}%")
                        st.info(f"今日換手率: {turnover:.2f}%")
                    else:
                        st.error(f"錯誤: {err}")

        # 按鈕二：籌碼
        with col_fm:
            if st.button(f"📊 三大法人籌碼 ({sid})", key=f"fm_{sid}"):
                with st.spinner("FinMind 加載中..."):
                    df = fetch_fm_chips(sid)
                    if not df.empty:
                        last_d = df['date'].max()
                        today = df[df['date'] == last_d]
                        mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                        results = []
                        for label, kw in mapping.items():
                            r = today[today['name'].isin(kw)]
                            if not r.empty:
                                n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                                results.append(f"{label}: {n}張")
                        st.write(f"🗓️ {last_d} | {' | '.join(results)}")
                    else:
                        st.warning("籌碼數據讀取失敗。")
