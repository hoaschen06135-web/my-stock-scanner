import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="雙核心行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. yfinance 備援抓取函數 (解決換手率 0% 與行情報錯) ---
@st.cache_data(ttl=3600)
def fetch_yfinance_data(sid_tw):
    """抓取 Yahoo Finance 的行情與總股數"""
    try:
        ticker = yf.Ticker(sid_tw)
        # 取得行情
        hist = ticker.history(period="1mo")
        # 取得總股數 (換手率分母)
        info = ticker.info
        shares = info.get('sharesOutstanding', 0)
        return hist, shares
    except:
        return pd.DataFrame(), 0

# --- 3. FinMind 籌碼抓取函數 (含限流保護) ---
@st.cache_data(ttl=3600)
def fetch_finmind_chips(sid):
    """專門抓取三大法人數據"""
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    try:
        time.sleep(1) # 強制延遲防止 503
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. 主介面 ---
st.title("🚀 專業關注清單 (FinMind + Yahoo)")
if st.sidebar.button("🔄 全球數據刷新"):
    st.cache_data.clear()
    st.rerun()

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.stop()

for _, row in watchlist.iterrows():
    # 統一格式：sid=2887, sid_tw=2887.TW
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_tw}`")
            
            # --- 優先使用 yfinance 抓取行情與換手率 (穩定性高) ---
            y_hist, y_shares = fetch_yfinance_data(sid_tw)
            
            if not y_hist.empty:
                # 計算基礎指標
                last_price = round(y_hist['Close'].iloc[-1], 2)
                prev_price = y_hist['Close'].iloc[-2]
                change_pct = ((last_price - prev_price) / prev_price) * 100
                last_vol = y_hist['Volume'].iloc[-1]
                
                # 換手率：(當日成交量 / 總股數) * 100
                turnover = (last_vol / y_shares) * 100 if y_shares > 0 else 0
                
                # 排版顯示
                c1, c2, c3, c4 = st.columns(4)
                color = "red" if change_pct > 0 else "green"
                c1.markdown(f"價: **{last_price}**")
                c2.markdown(f"幅: <span style='color:{color}'>{change_pct:.2f}%</span>", unsafe_allow_html=True)
                c3.markdown(f"來源: `Yahoo` <small>(免額度)</small>", unsafe_allow_html=True)
                c4.markdown(f"換手: **{turnover:.2f}%**")
                
                # --- 抓取 FinMind 籌碼數據 (核心價值) ---
                inst_df = fetch_finmind_chips(sid)
                if not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_d]
                    # 鎖定您診斷出的英文名稱
                    map_inst = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    chips = []
                    total_net = 0
                    for label, kw in map_inst.items():
                        r = today[today['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            total_net += n
                            c = "red" if n > 0 else "green"
                            chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    
                    t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                    st.markdown(f"<small>🗓️ {last_d} | 三大法人合計: <span style='color:{t_color}'>{total_net}張</span> | {' '.join(chips)}</small>", unsafe_allow_html=True)
                else:
                    st.caption("⚠️ FinMind 籌碼限流中，請稍後再試...")
            else:
                st.error(f"無法取得 {sid} 的任何數據。")
