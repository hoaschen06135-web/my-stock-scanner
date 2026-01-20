import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="法人鎖碼監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 核心計算邏輯 ---
def calculate_kdj(df):
    """引擎 A：本地計算 KD (保證 100% 畫出圖表)"""
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def get_streak(df):
    """計算法人連續買超天數 (鎖碼核心)"""
    if not isinstance(df, pd.DataFrame) or df.empty: return 0
    # 合計三大法人每日買賣超
    daily = df.groupby('date').apply(lambda x: (pd.to_numeric(x['buy']).sum() - pd.to_numeric(x['sell']).sum())).sort_index(ascending=False)
    streak = 0
    for val in daily:
        if val > 0: streak += 1
        else: break
    return streak

# --- 3. 引擎 B：證交所 OpenAPI ---
@st.cache_data(ttl=3600)
def fetch_twse_data():
    """直連證交所 JSON API (避開 Yahoo 限流)"""
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL"
        res = requests.get(url, timeout=10)
        return pd.DataFrame(res.json()).set_index('Code')
    except: return pd.DataFrame()

# --- 4. 同步與抓取 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    twse_stats = fetch_twse_data()

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        report = {"name": row['名稱'], "market": None, "chips": None, "twse": None, "hist": None}
        
        # Yahoo 引擎：價格與 KD
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                report["market"] = {"price": last_p, "change": chg}
                report["hist"] = calculate_kdj(hist)
        except: pass

        # 證交所引擎：本益比/殖利率
        if sid in twse_stats.index:
            s = twse_stats.loc[sid]
            report["twse"] = {"pe": s.get('PEratio', '-'), "yield": s.get('DividendYield', '-')}

        # FinMind 引擎：鎖碼連買計算
        try:
            time.sleep(0.5) # 防止 Token 被鎖
            raw_res = dl.get_data(dataset="TaiwanStockInstitutionalInvestors", data_id=sid, start_date=(datetime.now() - timedelta(30)).strftime('%Y-%m-%d'))
            if isinstance(raw_res, pd.DataFrame) and not raw_res.empty:
                report["chips"] = {"streak": get_streak(raw_res), "net": int((pd.to_numeric(raw_res[raw_res['date']==raw_res['date'].max()]['buy']).sum() - pd.to_numeric(raw_res[raw_res['date']==raw_res['date'].max()]['sell']).sum()) // 1000)}
        except: pass
        
        st.session_state.stock_memory[sid] = report

# --- 5. UI 呈現 ---
st.title("🛡️ 專業級法人鎖碼監控站")
with st.sidebar:
    if st.button("🚀 一鍵同步全清單", use_container_width=True):
        raw_df = conn.read(ttl=0).dropna(how='all')
        watchlist = raw_df.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
        sync_all_data(watchlist)
        st.rerun()

if st.session_state.stock_memory:
    for sid, d in st.session_state.stock_memory.items():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
            c1.subheader(d['name'])
            c1.caption(f"{sid}.TW")
            if d['market']:
                c2.metric("股價", f"{d['market']['price']}", f"{d['market']['change']:.2f}%")
            if d['chips']:
                streak = d['chips']['streak']
                label = f"🔥 連買 {streak} 天" if streak >= 3 else (f"👍 連買 {streak} 天" if streak > 0 else "⚖️ 買賣拉鋸")
                color = "#FF4B4B" if streak >= 3 else ("#FFA500" if streak > 0 else "#808080")
                c3.markdown(f"<div style='background-color:{color}; padding:10px; border-radius:10px; color:white; text-align:center;'><b>{label}</b><br><small>昨日: {d['chips']['net']} 張</small></div>", unsafe_allow_html=True)
            with c4:
                if d['hist'] is not None:
                    with st.popover("📈 KD圖"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D'))
                        st.plotly_chart(fig, use_container_width=True)
