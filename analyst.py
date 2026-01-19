import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="旗艦監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. yfinance 資料抓取 (穩定性高，免 API 額度) ---
@st.cache_data(ttl=3600)
def fetch_yfinance_data(sid_tw):
    """取得 Yahoo Finance 的行情與總股數"""
    try:
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period="1mo")
        info = ticker.info
        # 獲取發行總股數，這是解決換手率 0% 的關鍵
        shares = info.get('sharesOutstanding', 0)
        return hist, shares
    except:
        return pd.DataFrame(), 0

# --- 3. FinMind 籌碼抓取 (加入限流保護與快取) ---
@st.cache_data(ttl=1800)
def fetch_fm_chips(sid):
    """專門處理三大法人張數"""
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    try:
        # 強制延遲 1 秒，防止未驗證帳號被 503 攔截
        time.sleep(1)
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. 主介面顯示 ---
st.title("🚀 專業關注清單 (雙核心版)")

if st.sidebar.button("🔄 強制刷新數據"):
    st.cache_data.clear()
    st.rerun()

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.stop()

for _, row in watchlist.iterrows():
    # 代號自動清理與格式轉換
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_tw}`")
            
            # 使用 yfinance 處理價格與換手率 (避開 FinMind 額度)
            y_hist, y_shares = fetch_yfinance_data(sid_tw)
            
            if not y_hist.empty:
                last_price = round(y_hist['Close'].iloc[-1], 2)
                prev_price = y_hist['Close'].iloc[-2]
                change_pct = ((last_price - prev_price) / prev_price) * 100
                last_vol = y_hist['Volume'].iloc[-1]
                
                # 計算換手率
                turnover = (last_vol / y_shares) * 100 if y_shares > 0 else 0
                
                c1, c2, c3, c4 = st.columns(4)
                color = "red" if change_pct > 0 else "green"
                c1.markdown(f"價: **{last_price}**")
                c2.markdown(f"幅: <span style='color:{color}'>{change_pct:.2f}%</span>", unsafe_allow_html=True)
                c3.markdown(f"來源: `Yahoo`")
                c4.markdown(f"換手: **{turnover:.2f}%**")
                
                # 使用 FinMind 處理三大法人張數
                inst_df = fetch_fm_chips(sid)
                if not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_d]
                    # 鎖定您的環境診斷出的標籤
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
                    st.caption("⚠️ 籌碼資料獲取中或頻率過快，請稍後...")
            else:
                st.warning(f"無法取得 {sid_tw} 的即時數據。")
