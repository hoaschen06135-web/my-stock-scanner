import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
import requests
from io import StringIO
import math
import urllib3

# 基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股精確篩選系統")

# --- 1. KD 指標計算與彈出視窗 ---
def calculate_kd(df):
    """計算 KD 指標 (9, 3, 3)"""
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    return k, d

@st.dialog("📈 技術面分析 (KD線)")
def show_kd_dialog(ticker, name):
    st.write(f"#### {name} ({ticker})")
    with st.spinner("抓取歷史數據中..."):
        hist = yf.download(ticker, period="3mo", progress=False)
        if not hist.empty:
            hist['K'], hist['D'] = calculate_kd(hist)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hist.index, y=hist['K'], name='K值', line=dict(color='#1f77b4')))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['D'], name='D值', line=dict(color='#ff7f0e')))
            fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="超買區")
            fig.add_hline(y=20, line_dash="dash", line_color="green", annotation_text="超賣區")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("無法抓取歷史數據")

# --- 2. 核心數據獲取邏輯 ---
def fetch_live_data(tickers_with_names):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    
    # 抓取 6 天數據以確保能計算量比
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty: continue
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            tk = yf.Ticker(t)
            shares = tk.info.get('sharesOutstanding', 1)
            turnover = round((t_data['Volume'].iloc[-1] / shares) * 100, 2)
            mcap = f"{round(tk.info.get('marketCap', 0)/1e8, 2)} 億"

            results.append({
                "選取": False, "股票代號": t, "名稱": mapping[t], 
                "漲幅(%)": change, "量比": vol_ratio, 
                "換手率(%)": turnover, "流通市值": mcap, "最後價格": round(c_now, 2)
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. 頁面導航 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

# --- 頁面一：全市場分組掃描 (含單一搜尋) ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選系統")
    
    single_search = st.sidebar.text_input("🔍 單一股票搜尋 (如: 2330)")
    
    if st.button("🚀 開始掃描"):
        # 這裡根據您的需求進行掃描邏輯...
        # ...
        st.session_state['scan_res'] = fetch_live_data([...]) # 填入目標代號
        st.rerun()

# --- 頁面二：我的關注清單 (含即時更新與 KD 彈窗) ---
elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    
    # 即時更新按鈕
    if st.button("🔄 刷新即時數據與篩選指標"):
        st.cache_data.clear()
        st.rerun()

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_cloud = conn.read(worksheet="Sheet1", ttl="0")
        watchlist = df_cloud["ticker_item"].dropna().tolist() if not df_cloud.empty else []
        
        if watchlist:
            with st.spinner("更新數據中..."):
                live_df = fetch_live_data(watchlist) # 同步顯示台泥、精金等標的數據
            
            st.info("💡 提示：點擊下方表格選中股票後，再點擊下方按鈕即可彈出 KD 技術線圖。")
            
            # 解決 WidthError，確保表格寬度正確
            event = st.dataframe(live_df, on_select="rerun", selection_mode="single_row", use_container_width=True, hide_index=True)
            
            if event.selection.rows:
                idx = event.selection.rows[0]
                row = live_df.iloc[idx]
                if st.button(f"📊 彈出 {row['名稱']} ({row['股票代號']}) KD 視窗"):
                    show_kd_dialog(row['股票代號'], row['名稱'])
        else:
            st.info("目前清單是空的，請先去掃描並加入股票。")
    except Exception as e:
        st.error(f"連線試算表出錯：{e}")
