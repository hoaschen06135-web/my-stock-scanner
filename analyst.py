import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
# 確保 Secrets 中有設定此金鑰
TOKEN = st.secrets["FINMIND_TOKEN"] 

# --- 2. KD 計算函數 (9, 3, 3) ---
def calculate_kd(df):
    """計算台股標準 KD 指標"""
    low_min = df['low'].rolling(window=9).min()
    high_max = df['high'].rolling(window=9).max()
    # RSV 公式: (今日收盤 - 9日最低) / (9日最高 - 9日最低) * 100
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        # 遞迴平滑公式
        k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        d = d_list[-1] * (2/3) + k * (1/3)
        k_list.append(k); d_list.append(d)
    df['K'], df['D'] = k_list, d_list
    return df

# --- 3. 分析彈窗 ---
@st.dialog("📈 個股深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("獲取數據中..."):
        dl = DataLoader()
        # 直接在方法中傳入 token，避開 AttributeError
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(
            stock_id=stock_id.split('.')[0], 
            start_date=start_dt,
            token=TOKEN
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
            st.error("無法取得數據，請確認 Token 是否有效。")

# --- 4. 主介面 ---
st.title("⭐ 雲端關注清單監控")

# 讀取試算表，指定正確的欄位
try:
    watchlist = conn.read()
    # 修正欄位偏移問題：強制只取這兩欄
    if watchlist is not None and not watchlist.empty:
        watchlist = watchlist[["股票代號", "名稱"]]
except Exception as e:
    st.error(f"讀取失敗，請確認試算表欄位是否正確 (A1:股票代號, B1:名稱)。")
    st.stop()

if watchlist is not None and not watchlist.empty:
    dl = DataLoader()
    st.markdown("---")
    
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
                    start_date=start_c,
                    token=TOKEN
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
                st.caption("暫無籌碼數據")

        if c3.button("📈 分析", key=f"btn_{pure_id}"):
            show_kd_dialog(sid, sname)
    
    if st.button("🔄 刷新頁面"):
        st.rerun()
