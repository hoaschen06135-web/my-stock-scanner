import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站-終極穩定版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 核心數據處理 ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def sync_data(watchlist):
    dl = DataLoader()
    # 修復 image_30a344.png 的屬性報錯
    try:
        if hasattr(dl, 'login'): dl.login(token=TOKEN)
    except: pass

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        report = {"name": row['名稱'], "market": None, "chips": None, "err_y": None, "hist": None}
        
        try:
            # 關鍵修復：依照 image_319ee4.png 提示，不手動設定 session
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                # 修復 image_30aac3.png 屬性抓取路徑
                info = tk.info
                shares = info.get('sharesOutstanding', 0)
                
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                
                # 計算四大指標
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000
                
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": turnover, "mkt_cap": mkt_cap}
                report["hist"] = calculate_kdj(hist)
        except Exception as e: report["err_y"] = str(e)

        try:
            # FinMind 籌碼數據抓取
            time.sleep(0.5)
            df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
            if df is not None and not df.empty:
                last_d = df['date'].max()
                td = df[df['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
        except: pass
        st.session_state.stock_memory[sid] = report

# --- 3. 介面呈現 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單"):
        st.cache_data.clear()
        st.rerun()
        
    try:
        raw = conn.read(ttl=600).dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except: st.stop()
    
    if st.button("🚀 一鍵同步所有指標", use_container_width=True):
        with st.spinner("正在抓取數據..."):
            sync_data(watchlist)
            st.rerun()

st.title("🚀 專業數據監控站 (終極穩定版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_t, col_k = st.columns([7, 3])
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_t: st.subheader(f"{d['name']} ({sid}.TW)")
            with col_k:
                if d["hist"] is not None:
                    # KD 彈出視窗按鈕
                    with st.popover("📈 查看 KD"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值'))
                        fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                        st.plotly_chart(fig, use_container_width=True)
            
            # 顯示報錯訊息診斷
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            
            if d["market"]:
                m = d["market"]; c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m['turnover']:.2f}%")
                c4.metric("流通市值", f"{m['mkt_cap']:.1f} 億")
            
            if d["chips"]:
                c = d["chips"]; t_c = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_c}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側按鈕。")
