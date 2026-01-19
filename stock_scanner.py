import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

st.set_page_config(layout="wide", page_title="台股精確篩選系統")

# --- 1. KD 指標計算與彈出視窗 ---
def calculate_kd(df):
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    return k, d

@st.dialog("📈 技術面分析 (KD線)")
def show_kd_dialog(ticker, name):
    st.write(f"#### {name} ({ticker})")
    hist = yf.download(ticker, period="3mo", progress=False)
    if not hist.empty:
        hist['K'], hist['D'] = calculate_kd(hist)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist['K'], name='K值', line=dict(color='#1f77b4')))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['D'], name='D值', line=dict(color='#ff7f0e')))
        fig.add_hline(y=80, line_dash="dash", line_color="red")
        fig.add_hline(y=20, line_dash="dash", line_color="green")
        st.plotly_chart(fig, use_container_width=True)

# --- 2. 數據獲取 (含即時數據與篩選) ---
def get_live_data(watchlist_items):
    if not watchlist_items: return pd.DataFrame()
    tickers = [i.split(',')[0] for i in watchlist_items]
    names = {i.split(',')[0]: i.split(',')[1] for i in watchlist_items}
    
    # 抓取 6 天數據計算量比
    data = yf.download(tickers, period="6d", group_by='ticker', progress=False)
    results = []
    for t in tickers:
        try:
            t_data = data[t] if len(tickers) > 1 else data
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            chg = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            results.append({"股票代號": t, "名稱": names[t], "目前價格": round(c_now, 2), "漲幅(%)": chg, "量比": vol_ratio})
        except: continue
    return pd.DataFrame(results)

# --- 3. 頁面邏輯 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    
    # 即時更新按鈕
    if st.button("🔄 立即更新即時數據"):
        st.cache_data.clear()
        st.rerun()

    conn = st.connection("gsheets", type=GSheetsConnection)
    df_cloud = conn.read(worksheet="Sheet1", ttl="0")
    watchlist = df_cloud["ticker_item"].dropna().tolist() if not df_cloud.empty else []

    if watchlist:
        live_df = get_live_data(watchlist)
        st.write("點選下方股票後，點擊按鈕查看 KD 線視窗：")
        # 使用 selection 模式
        event = st.dataframe(live_df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single_row")
        
        if event.selection.rows:
            idx = event.selection.rows[0]
            selected_stock = live_df.iloc[idx]
            if st.button(f"📊 查看 {selected_stock['名稱']} 的 KD 視窗"):
                show_kd_dialog(selected_stock['股票代號'], selected_stock['名稱'])
    else:
        st.info("清單目前是空的。")
