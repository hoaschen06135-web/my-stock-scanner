import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與 Secrets 讀取 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"] # 從 Secrets 取得您的 API Token

# --- 2. KD 技術指標計算函數 (標準 9, 3, 3) ---
def calculate_kd(df):
    """計算 RSV 與 KD 線"""
    # 取得 9 日內的最高與最低價
    low_min = df['low'].rolling(window=9).min()
    high_max = df['high'].rolling(window=9).max()
    # 計算 RSV (未成熟隨機值)
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        # 標準 KD 遞迴公式：昨日值 * 2/3 + 今日值 * 1/3
        k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        d = d_list[-1] * (2/3) + k * (1/3)
        k_list.append(k); d_list.append(d)
    df['K'], df['D'] = k_list, d_list
    return df

# --- 3. KD 即時分析彈窗 ---
@st.dialog("📈 個股 KD 技術分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("從 FinMind 獲取穩定數據中..."):
        dl = DataLoader(); dl.login(token=TOKEN)
        # 抓取 60 天數據以供計算
        start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(stock_id=stock_id.split('.')[0], start_date=start_date)
        
        if not df.empty:
            df = calculate_kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='#1f77b4')))
            fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='#ff7f0e')))
            # 固定 0-100 範圍並加入 20/80 警戒線
            fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0, r=0, t=20, b=0))
            fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="超買區")
            fig.add_hline(y=20, line_dash="dash", line_color="green", annotation_text="超賣區")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("暫無該股票數據。")
    if st.button("關閉分析"): st.rerun()

# --- 4. 主介面：顯示關注名單與法人籌碼 ---
st.title("⭐ 雲端關注清單監控")

# 讀取 Google Sheets 關注名單
try:
    watchlist = conn.read()
except:
    st.info("尚未同步關注股票，請先使用 scanner.py。")
    st.stop()

if watchlist is not None and not watchlist.empty:
    dl = DataLoader(); dl.login(token=TOKEN)
    st.markdown("---")
    
    # 逐一處理名單中的股票
    for _, row in watchlist.iterrows():
        sid, sname = row['股票代號'], row['名稱']
        pure_id = sid.split('.')[0]
        
        c1, c2, c3 = st.columns([2, 5, 1])
        c1.write(f"### {sname}\n`{sid}`")
        
        # 抓取三大法人買賣超
        with c2:
            try:
                start_c = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                inst_df = dl.taiwan_stock_institutional_investors_buy_sell(stock_id=pure_id, start_date=start_c)
                if not inst_df.empty:
                    last_dt = inst_df['date'].max()
                    today = inst_df[inst_df['date'] == last_dt]
                    chips = []
                    for _, r in today.iterrows():
                        net = (r['buy'] - r['sell']) // 1000 # 換算為張數
                        color = "red" if net > 0 else "green"
                        chips.append(f"{r['name']}: <span style='color:{color}'>{net}張</span>")
                    st.markdown(f"🗓️ {last_dt}<br>{' | '.join(chips)}", unsafe_allow_html=True)
            except:
                st.caption("籌碼載入中...")

        # 點擊按鈕觸發 KD 彈窗
        if c3.button("📈 KD", key=f"btn_{pure_id}"):
            show_kd_dialog(sid, sname)
    
    st.markdown("---")
    if st.button("🔄 刷新雲端名單與數據"):
        st.rerun()
