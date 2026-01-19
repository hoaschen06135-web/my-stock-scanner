import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="行動分析站-修復版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 行情與換手率抓取 (Yahoo 來源) ---
@st.cache_data(ttl=600)
def fetch_market_data(sid_tw):
    try:
        # 修復連線衝突：不手動設定 Session
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period='5d')
        
        # 獲取總股數 (解決換手率 0% 問題)
        try:
            shares = ticker.fast_info.shares_outstanding
        except:
            shares = ticker.info.get('sharesOutstanding', 0)
            
        if not hist.empty:
            return hist, shares, None
        return pd.DataFrame(), 0, "暫無行情"
    except Exception as e:
        return pd.DataFrame(), 0, str(e)

# --- 3. 籌碼抓取 (FinMind 來源) ---
def fetch_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        # 認證後可縮短延遲，但仍保留緩衝
        time.sleep(0.5) 
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. UI 介面 ---
st.title("🚀 專業關注清單 (修復版)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.error("請確認 Google Sheets 連線狀態。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid_tw})")
        c_y, c_fm = st.columns(2)
        
        with c_y:
            if st.button(f"🔍 更新行情 ({sid})", key=f"y_{sid}"):
                with st.spinner("讀取 Yahoo..."):
                    h, s, err = fetch_market_data(sid_tw)
                    if not h.empty:
                        last_p = round(h['Close'].iloc[-1], 2)
                        chg = ((last_p - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
                        vol = h['Volume'].iloc[-1]
                        # 換手率計算
                        turnover = (vol / s) * 100 if s > 0 else 0
                        
                        color = "red" if chg > 0 else "green"
                        st.metric("現價", f"{last_p}", f"{chg:.2f}%")
                        st.info(f"今日換手率: {turnover:.2f}%")
                    else:
                        st.error(f"行情錯誤: {err}")

        with c_fm:
            if st.button(f"📊 讀取籌碼 ({sid})", key=f"fm_{sid}"):
                with st.spinner("讀取 FinMind..."):
                    df = fetch_chips(sid)
                    if not df.empty:
                        last_d = df['date'].max()
                        today = df[df['date'] == last_d]
                        mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                        total_net = 0
                        results = []
                        for label, kw in mapping.items():
                            r = today[today['name'].isin(kw)]
                            if not r.empty:
                                n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                                total_net += n
                                results.append(f"{label}: {n}張")
                        st.write(f"🗓️ {last_d} | 合計: {total_net}張")
                        st.write(" | ".join(results))
                    else:
                        st.warning("籌碼抓取失敗，請確認 API 狀態。")
