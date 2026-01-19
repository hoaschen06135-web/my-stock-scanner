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

# --- 2. yfinance 數據抓取 (避開 FinMind 額度限制並修復換手率) ---
@st.cache_data(ttl=3600)
def fetch_yfinance_data(sid_tw):
    try:
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period="1mo")
        info = ticker.info
        # 直接從 Yahoo 取得總股數，解決換手率 0.0% 問題
        shares = info.get('sharesOutstanding', 0)
        return hist, shares
    except Exception:
        return pd.DataFrame(), 0

# --- 3. FinMind 籌碼抓取 (加入 503 錯誤保護) ---
@st.cache_data(ttl=1800)
def fetch_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        # 增加延遲，減少未驗證帳號被攔截的機率
        time.sleep(1.2)
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except Exception:
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
except Exception:
    st.stop()

for _, row in watchlist.iterrows():
    # 代號自動處理
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_tw}`")
            
            # 使用 yfinance 處理價格與換手率
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
                c3.markdown(f"來源: `Yahoo Finance`")
                c4.markdown(f"換手: **{turnover:.2f}%**")
                
                # 使用 FinMind 抓取籌碼
                inst_df = fetch_fm_chips(sid)
                if not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_d]
                    # 鎖定診斷截圖顯示的英文標籤
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
                    st.markdown(f"<small>🗓️ {last_d} | 合計: <span style='color:{t_color}'>{total_net}張</span> | {' '.join(chips)}</small>", unsafe_allow_html=True)
                else:
                    st.caption("⚠️ 籌碼資料獲取中或頻率過快，請稍後...")
            else:
                st.warning(f"無法取得 {sid_tw} 的數據。")
