import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化環境與 Session State ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站-常駐版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 初始化記憶體，確保數據不會消失
if 'market_results' not in st.session_state:
    st.session_state.market_results = {}
if 'chip_results' not in st.session_state:
    st.session_state.chip_results = {}

# --- 2. 數據抓取函數 ---
def fetch_all_market(watchlist):
    """批次抓取 Yahoo 行情與換手率"""
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        try:
            ticker = yf.Ticker(sid_tw)
            hist = ticker.history(period='5d')
            shares = ticker.fast_info.shares_outstanding
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                vol = hist['Volume'].iloc[-1]
                # 換手率公式：$$Turnover = \frac{Volume}{Total\ Shares} \times 100\%$$
                turnover = (vol / shares) * 100 if shares > 0 else 0
                st.session_state.market_results[sid] = {
                    "price": last_p, "change": chg, "turnover": turnover
                }
        except:
            continue

def fetch_all_chips(watchlist):
    """批次抓取 FinMind 籌碼數據"""
    dl = DataLoader()
    dl.login(token=TOKEN)
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        try:
            time.sleep(0.5) # 認證帳號後的安全延遲
            df = dl.taiwan_stock_institutional_investors(
                stock_id=sid, 
                start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
            )
            if df is not None and not df.empty:
                last_d = df['date'].max()
                today = df[df['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                res = {"date": last_d, "total": 0, "details": []}
                for label, kw in mapping.items():
                    r = today[today['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        res["total"] += n
                        res["details"].append(f"{label}: {n}張")
                st.session_state.chip_results[sid] = res
        except:
            continue

# --- 3. 側邊欄控制面板 ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
    
    st.subheader("批次更新數據")
    if st.button("🔄 更新所有行情 (Yahoo)", use_container_width=True):
        with st.spinner("行情抓取中..."):
            fetch_all_market(watchlist)
            st.rerun()
            
    if st.button("📊 更新所有籌碼 (FinMind)", use_container_width=True):
        with st.spinner("籌碼分析中..."):
            fetch_all_chips(watchlist)
            st.rerun()

    if st.button("🧹 清除快取記憶", use_container_width=True):
        st.session_state.market_results = {}
        st.session_state.chip_results = {}
        st.rerun()

# --- 4. 主畫面顯示 ---
st.title("🚀 專業關注清單監控 (數據常駐版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    sname = row['名稱']
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid}.TW)")
        
        # 顯示行情 (若有記憶數據)
        if sid in st.session_state.market_results:
            m = st.session_state.market_results[sid]
            c1, c2, c3 = st.columns(3)
            color = "red" if m['change'] > 0 else "green"
            c1.metric("現價", f"{m['price']}", f"{m['change']:.2f}%")
            c2.info(f"今日換手率: {m['turnover']:.2f}%")
            c3.caption("數據來源: Yahoo Finance")
        
        # 顯示籌碼 (若有記憶數據)
        if sid in st.session_state.chip_results:
            c = st.session_state.chip_results[sid]
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(f"🗓️ **{c['date']}** | 三大法人合計: <span style='color:{t_color}'>{c['total']}張</span>", unsafe_allow_html=True)
            st.write(" | ".join(c['details']))
