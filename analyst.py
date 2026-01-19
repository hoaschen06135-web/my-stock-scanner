import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# 1. 環境設定與初始化
st.set_page_config(layout="wide", page_title="旗艦監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 2. yfinance 資料抓取 (穩定性高，提供總股數解決換手率問題)
@st.cache_data(ttl=3600)
def fetch_y_data(sid_tw):
    try:
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period="1mo")
        info = ticker.info
        # 直接從 Yahoo 取得總股數，這是換手率的分母
        shares = info.get('sharesOutstanding', 0)
        return hist, shares
    except:
        return pd.DataFrame(), 0

# 3. FinMind 籌碼抓取 (專供法人數據，加入限流保護)
@st.cache_data(ttl=1800)
def fetch_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        # 強制延遲 2 秒，適應未驗證帳號的超低頻率限制
        time.sleep(2.0)
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 主介面顯示
st.title("🚀 專業關注清單 (切換雙來源版)")

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
    # 自動代號處理：sid=2887, sid_tw=2887.TW
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_tw}`")
            
            # --- 切換來源 A: 使用 yfinance 處理行情與換手率 ---
            y_hist, y_shares = fetch_y_data(sid_tw)
            
            if not y_hist.empty:
                last_price = round(y_hist['Close'].iloc[-1], 2)
                prev_price = y_hist['Close'].iloc[-2]
                change_pct = ((last_price - prev_price) / prev_price) * 100
                last_vol = y_hist['Volume'].iloc[-1]
                
                # 計算換手率公式：$$Turnover = \frac{Volume}{Total\ Shares} \times 100\%$$
                turnover = (last_vol / y_shares) * 100 if y_shares > 0 else 0
                
                c1, c2, c3, c4 = st.columns(4)
                color = "red" if change_pct > 0 else "green"
                c1.markdown(f"價: **{last_price}**")
                c2.markdown(f"幅: <span style='color:{color}'>{change_pct:.2f}%</span>", unsafe_allow_html=True)
                c3.markdown(f"來源: `Yahoo` <small>(不限額)</small>", unsafe_allow_html=True)
                c4.markdown(f"換手: **{turnover:.2f}%**")
                
                # --- 切換來源 B: 使用 FinMind 只抓法人籌碼 ---
                inst_df = fetch_fm_chips(sid)
                if not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_d]
                    # 鎖定診斷出的英文標籤名稱
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
                    st.caption("⚠️ FinMind 籌碼讀取中，請給它一點冷卻時間...")
            else:
                st.warning(f"無法取得 {sid_tw} 的即時行情數據。")
