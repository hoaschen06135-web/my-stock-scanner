import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站-穩定安全版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 安全抓取函數：增加重試與延遲 ---
@st.cache_data(ttl=1800) # 快取 30 分鐘，減少重複敲門
def safe_fetch(sid, dataset, start_date):
    dl = DataLoader()
    try:
        # 每筆資料抓取間隔 0.5 秒，防止 503 攔截
        time.sleep(0.5) 
        if dataset == "Daily":
            res = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
        elif dataset == "Inst":
            res = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start_date)
        elif dataset == "Poll":
            res = dl.taiwan_stock_shares_poll(stock_id=sid, start_date=start_date)
        
        if res is not None and not res.empty:
            return res
    except:
        return pd.DataFrame()
    return pd.DataFrame()

# --- 3. 核心指標計算 ---
def calculate_metrics(df, total_shares):
    # 使用 Trading_Volume 避免 image_247405.png 錯誤
    vol_col = 'Trading_Volume'
    if vol_col not in df.columns or len(df) < 5: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
    vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 換手率公式：今日成交量 / 總股數
    turnover = (df[vol_col].iloc[-1] / total_shares) * 100 if total_shares > 0 else 0
    
    return {"price": close_t, "change": change_pct, "vol_ratio": vol_ratio, "turnover": turnover}

# --- 4. 主介面顯示 ---
st.title("🚀 專業關注清單監控")
if st.sidebar.button("🔄 立即更新數據"):
    st.cache_data.clear()
    st.rerun()

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.stop()

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].replace(' ', '').strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.markdown(f"**{sname}** `{sid}.TW`")
        
        # A. 行情資料
        df_daily = safe_fetch(sid, "Daily", (datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
        
        if not df_daily.empty:
            # B. 總股數 (修復換手率問題)
            poll_df = safe_fetch(sid, "Poll", (datetime.now()-timedelta(45)).strftime('%Y-%m-%d'))
            total_shares = poll_df[poll_df['date'] == poll_df['date'].max()]['number_of_shares'].sum() if not poll_df.empty else 0
            
            m = calculate_metrics(df_daily, total_shares)
            if m:
                c1, c2, c3, c4 = st.columns(4)
                color = "red" if m['change'] > 0 else "green"
                c1.markdown(f"價: **{m['price']}**")
                c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                c4.markdown(f"換手: **{m['turnover']:.2f}%**")
            
            # C. 法人籌碼
            inst_df = safe_fetch(sid, "Inst", (datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
            if not inst_df.empty:
                last_d = inst_df['date'].max()
                today = inst_df[inst_df['date'] == last_d]
                # 模糊匹配名稱，防止不同版本差異
                map_inst = {"外資": ["Foreign_Investor", "外資"], "投信": ["Investment_Trust", "投信"], "自營": ["Dealer_self", "自營"]}
                chips = []
                for label, kw in map_inst.items():
                    r = today[today['name'].str.contains('|'.join(kw), na=False)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        c = "red" if n > 0 else "green"
                        chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                st.markdown(f"<small>🗓️ {last_d} | {' '.join(chips)}</small>", unsafe_allow_html=True)
        else:
            st.warning(f"目前 API 頻率過快，請稍等 1 分鐘後再重新整理。")
