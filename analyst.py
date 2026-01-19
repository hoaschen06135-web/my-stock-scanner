import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. KD 計算函數 ---
def calculate_kd(df):
    if 'min' not in df.columns: return None
    low_min = df['min'].rolling(window=9).min()
    high_max = df['max'].rolling(window=9).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        d = d_list[-1] * (2/3) + k * (1/3)
        k_list.append(k); d_list.append(d)
    df['K'], df['D'] = k_list, d_list
    return df

# --- 3. 分析彈窗 ---
@st.dialog("📈 個股深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("抓取 FinMind 數據中..."):
        dl = DataLoader()
        try: dl.login(token=TOKEN)
        except: pass
        pure_id = stock_id.split('.')[0].replace(' ', '').split(',')[0]
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(stock_id=pure_id, start_date=start_dt)
        if df is not None and not df.empty:
            df = calculate_kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='orange')))
            fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(fig, use_container_width=True)

# --- 4. 主介面 ---
st.title("⭐ 雲端關注清單監控")

try:
    raw_watchlist = conn.read()
    if raw_watchlist is not None and not raw_watchlist.empty:
        id_col = [c for c in raw_watchlist.columns if "代號" in str(c)][0]
        name_col = [c for c in raw_watchlist.columns if "名稱" in str(c)][0]
        watchlist = raw_watchlist[[id_col, name_col]].dropna()
        watchlist.columns = ["股票代號", "名稱"]
    else: st.stop()
except:
    st.error("試算表讀取錯誤。")
    st.stop()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split(',')[0].strip()
    sname = str(row['名稱']).strip()
    pure_id = sid.split('.')[0]
    
    c1, c2, c3 = st.columns([2, 5, 1])
    c1.write(f"### {sname}\n`{sid}`")
    
    with c2:
