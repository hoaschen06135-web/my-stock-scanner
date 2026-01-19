import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="專業行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 緩存安全抓取：解決 KeyError: 'data' 與 503 頻率限制 ---
@st.cache_data(ttl=3600)
def fetch_fm_data(sid, dataset, start_date):
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    
    # 清理代號格式
    pure_id = str(sid).split('.')[0].replace(' ', '').strip()
    
    try:
        # 每筆請求間隔 1 秒，防止未驗證帳號被封鎖
        time.sleep(1.0)
        if dataset == "Daily":
            res = dl.taiwan_stock_daily(stock_id=pure_id, start_date=start_date)
        elif dataset == "Inst":
            res = dl.taiwan_stock_institutional_investors(stock_id=pure_id, start_date=start_date)
        elif dataset == "Poll":
            res = dl.taiwan_stock_shares_poll(stock_id=pure_id, start_date=start_date)
        
        if res is not None and isinstance(res, pd.DataFrame) and not res.empty:
            return res
    except:
        return pd.DataFrame()
    return pd.DataFrame()

# --- 3. 核心指標計算 ---
def calculate_metrics(df, total_shares):
    # 修正：使用 Trading_Volume 避免 image_247405.png 的 KeyError
    vol_col = 'Trading_Volume'
    if vol_col not in df.columns or len(df) < 5: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
    vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 換手率：(今日成交股數 / 總發行股數) * 100
    turnover = (df[vol_col].iloc[-1] / total_shares) * 100 if total_shares > 0 else 0
    
    return {"price": close_t, "change": change_pct, "vol_ratio": vol_ratio, "turnover": turnover}

# --- 4. 側邊欄控制面板 ---
st.sidebar.title("⚙️ 控制面板")
if st.sidebar.button("🔄 強制刷新雲端數據"):
    st.cache_data.clear()
    st.rerun()

# --- 5. 主介面顯示 ---
st.title("🚀 專業關注清單監控")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("清單為空。")
    st.stop()

for _, row in watchlist.iterrows():
    raw_sid = str(row['股票代號'])
    pure_id = raw_sid.split('.')[0].replace(' ', '').strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{pure_id}.TW`")
            
            # A. 抓取行情資料
            df_daily = fetch_fm_data(pure_id, "Daily", (datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
            
            if not df_daily.empty:
                # B. 多源補齊總股數：解決換手率 0.0%
                poll_df = fetch_fm_data(pure_id, "Poll", (datetime.now()-timedelta(45)).strftime('%Y-%m-%d'))
                total_shares = 0
                if not poll_df.empty:
                    last_p = poll_df['date'].max()
                    total_shares = poll_df[poll_df['date'] == last_p]['number_of_shares'].sum()
                
                m = calculate_metrics(df_daily, total_shares)
                if m:
                    c1, c2, c3, c4 = st.columns(4)
                    color = "red" if m['change'] > 0 else "green"
                    c1.markdown(f"價: **{m['price']}**")
                    c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                    c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                    c4.markdown(f"換手: **{m['turnover']:.2f}%**")
                
                # C. 法人籌碼：鎖定診斷出的英文名稱
                inst_df = fetch_fm_data(pure_id, "Inst", (datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
                if not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_d]
                    
                    # 使用診斷顯示的 Foreign_Investor 等標籤
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    chips = []
                    total_net = 0
                    for label, kw in mapping.items():
                        r = today[today['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            total_net += n
                            c = "red" if n > 0 else "green"
                            chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    
                    t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                    st.markdown(f"<small>🗓️ {last_d} | 合計: <span style='color:{t_color}'>{total_net}張</span> | {' '.join(chips)}</small>", unsafe_allow_html=True)
            else:
                st.warning(f"目前頻率過快或 API 限額已滿，請稍後再試。")
