import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化與記憶體 ---
st.set_page_config(layout="wide", page_title="專業關注清單監控")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. KDJ 指標計算 ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

# --- 3. 數據同步核心 (修復換手率 0.00% 問題) ---
def sync_all_data(watchlist):
    dl = DataLoader()
    try:
        if hasattr(dl, 'login'): dl.login(token=TOKEN)
    except: pass
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "hist": None}
        
        # Yahoo 引擎：負責 漲幅、量比、換手率
        try:
            # 依照報錯建議，不設定自定義 session，讓 yfinance 自行處理
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                # 增加 1.5 秒延遲，提高抓取總股數的成功率
                time.sleep(1.5)
                
                # 換手率核心修正：嘗試多個股數屬性
                try:
                    info_data = tk.info
                    shares = info_data.get('sharesOutstanding') or info_data.get('floatShares') or 0
                except:
                    shares = 0
                
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                
                # 換手率公式：成交量 / 總股數
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": turnover}
                report["hist"] = calculate_kdj(hist)
        except Exception as e: report["err_y"] = f"Yahoo 故障: {str(e)}"

        # FinMind 引擎：僅負責籌碼
        try:
            time.sleep(0.5)
            chips_df = dl.taiwan_stock_institutional_investors(
                stock_id=sid, start_date=(datetime.now()-timedelta(14)).strftime('%Y-%m-%d')
            )
            if chips_df is not None and not chips_df.empty:
                last_d = chips_df['date'].max()
                td = chips_df[chips_df['date'] == last_d]
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

# --- 4. 側邊欄與主畫面呈現 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    raw = conn.read(ttl=600).dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]

    if st.button("🚀 一鍵同步所有數據指標", use_container_width=True):
        with st.spinner("同步數據中，請稍候..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

st.title("🚀 專業關注清單監控")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_t, col_k = st.columns([7, 3])
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_t: st.subheader(f"{d['name']} ({sid}.TW)")
            with col_k:
                if d["hist"] is not None:
                    with st.popover("📈 查看 KD"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值'))
                        fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                        st.plotly_chart(fig, use_container_width=True)
            
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            
            if d["market"]:
                m = d["market"]; c1, c2, c3 = st.columns(3)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                # 若換手率仍為 0.00%，會在下方顯示數據異常提示
                c3.metric("換手率", f"{m['turnover']:.2f}%")
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側「一鍵同步」。")
