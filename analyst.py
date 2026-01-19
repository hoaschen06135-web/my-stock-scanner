import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站-旗艦版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 核心計算函數 ---
def calculate_metrics(df, total_shares):
    """計算漲幅、量比與換手率"""
    # 自動識別成交量欄位名稱，避免 KeyError
    vol_col = next((c for c in df.columns if 'volume' in c.lower()), None)
    if not vol_col or len(df) < 2: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    # 量比：今日成交量 / 前5日平均量 (排除今日)
    if len(df) >= 6:
        avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
        vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    else:
        vol_ratio = 0
    
    # 換手率公式
    turnover = (df[vol_col].iloc[-1] / total_shares) * 100 if total_shares > 0 else 0
    
    return {"price": close_t, "change": change_pct, "vol_ratio": vol_ratio, "turnover": turnover}

# --- 3. 側邊欄控制 ---
st.sidebar.title("⚙️ 控制面板")
if st.sidebar.button("🔄 刷新全部數據"):
    st.cache_data.clear()
    st.rerun()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

# --- 4. 主介面 ---
st.title("🚀 專業關注清單監控")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("請從左側新增股票。")
    st.stop()

# 診斷資訊存放
diag_logs = []

for _, row in watchlist.iterrows():
    # 強化代號清理邏輯，解決 KeyError
    raw_sid = str(row['股票代號'])
    pure_id = raw_sid.split('.')[0].replace(' ', '').strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{pure_id}.TW`")
            
            # 抓取日 K 資料
            df_daily = dl.taiwan_stock_daily(stock_id=pure_id, start_date=(datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
            
            if df_daily is not None and not df_daily.empty:
                # --- 多重備援抓取總股數 (換手率核心) ---
                total_shares = 0
                try:
                    # 優先從「股東持股分級表」抓取最新總股數
                    poll = dl.taiwan_stock_shares_poll(stock_id=pure_id, start_date=(datetime.now()-timedelta(45)).strftime('%Y-%m-%d'))
                    if not poll.empty:
                        last_p = poll['date'].max()
                        total_shares = poll[poll['date'] == last_p]['number_of_shares'].sum()
                except Exception as e:
                    diag_logs.append(f"{pure_id} 股數抓取失敗: {str(e)}")
                
                m = calculate_metrics(df_daily, total_shares)
                if m:
                    c1, c2, c3, c4 = st.columns(4)
                    color = "red" if m['change'] > 0 else "green"
                    c1.markdown(f"價: **{m['price']}**")
                    c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                    c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                    c4.markdown(f"換手: **{m['turnover']:.2f}%**")
                
                # --- 法人籌碼 (使用 image_24d581.png 診斷出的英文標籤) ---
                inst_df = dl.taiwan_stock_institutional_investors(stock_id=pure_id, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
                if inst_df is not None and not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today_inst = inst_df[inst_df['date'] == last_d].copy()
                    
                    # 根據除錯截圖鎖定英文名稱
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    chips = []
                    total_net = 0
                    for label, kw in mapping.items():
                        r = today_inst[today_inst['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            total_net += n
                            c = "red" if n > 0 else "green"
                            chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    
                    t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                    st.markdown(f"<small>🗓️ {last_d} | 合計: <span style='color:{t_color}'>{total_net}張</span> | {' '.join(chips)}</small>", unsafe_allow_html=True)
            else:
                st.warning(f"無法取得 {pure_id} 的報價數據，請檢查代號。")

# --- 5. 系統診斷報告 ---
if diag_logs:
    with st.expander("🛠️ 系統診斷報告 (若換手率仍為 0 請截圖此處)"):
        for log in diag_logs:
            st.write(log)
