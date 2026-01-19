import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 環境初始化 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. KD 計算函數 ---
def calculate_kd(df):
    """計算台股標準 KD (9, 3, 3)"""
    low_min = df['low'].rolling(window=9).min()
    high_max = df['high'].rolling(window=9).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        d = d_list[-1] * (2/3) + k * (1/3)
        k_list.append(k); d_list.append(d)
    df['K'], df['D'] = k_list, d_list
    return df

# --- 3. 分析彈窗 (修正 TypeError) ---
@st.dialog("📈 個股深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("連線數據源..."):
        dl = DataLoader()
        # 修正：先登入，不直接在下載函數傳 token
        try:
            dl.login(token=TOKEN)
        except:
            pass # 避免部分版本 login 報錯
            
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(
            stock_id=stock_id.split('.')[0], 
            start_date=start_dt
        )
        
        if not df.empty:
            df = calculate_kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='orange')))
            fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0,r=0,t=20,b=0))
            fig.add_hline(y=80, line_dash="dash", line_color="red")
            fig.add_hline(y=20, line_dash="dash", line_color="green")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("無法抓取歷史數據。")

# --- 4. 主介面：讀取名單並處理欄位偏移 ---
st.title("⭐ 雲端關注清單監控")

try:
    watchlist = conn.read()
    # 解決 image_22aceb.png 的欄位偏移問題
    if watchlist is not None and not watchlist.empty:
        # 尋找包含關鍵字的欄位，不論它在 A 欄還是 B 欄
        col_id = [c for c in watchlist.columns if "代號" in c][0]
        col_name = [c for c in watchlist.columns if "名稱" in c][0]
        watchlist = watchlist[[col_id, col_name]].dropna()
        watchlist.columns = ["股票代號", "名稱"] # 重新命名統一化
except:
    st.info("請先使用掃描器同步股票至雲端。")
    st.stop()

if not watchlist.empty:
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    
    for _, row in watchlist.iterrows():
        sid, sname = str(row['股票代號']), str(row['名稱'])
        pure_id = sid.split('.')[0]
        
        c1, c2, c3 = st.columns([2, 5, 1])
        c1.write(f"### {sname}\n`{sid}`")
        
        with c2:
            try:
                start_c = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                # 抓取法人買賣超
                inst_df = dl.taiwan_stock_institutional_investors_buy_sell(
                    stock_id=pure_id, 
                    start_date=start_c
                )
                if not inst_df.empty:
                    last_dt = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_dt]
                    chips = []
                    for _, r in today.iterrows():
                        net = (r['buy'] - r['sell']) // 1000
                        color = "red" if net > 0 else "green"
                        chips.append(f"{r['name']}: <span style='color:{color}'>{net}張</span>")
                    st.markdown(f"🗓️ {last_dt}<br>{' | '.join(chips)}", unsafe_allow_html=True)
            except:
                st.caption("連線中...")

        if c3.button("📈 分析", key=f"btn_{pure_id}"):
            show_kd_dialog(sid, sname)
