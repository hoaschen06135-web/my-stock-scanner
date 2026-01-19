import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import os
import time
import urllib3
import plotly.graph_objects as go

# --- 1. 環境設定與初始化 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

# 初始化關注名單 (session_state)
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = []

# --- 2. 數據抓取與計算函數 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    """抓取純淨名單，過濾 4 萬筆雜訊標的"""
    urls = [("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", ".TW"),
            ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", ".TWO")]
    ticker_data = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url, suffix in urls:
        try:
            res = requests.get(url, headers=headers, verify=False, timeout=10)
            df = pd.read_html(res.text)[0].iloc[1:]
            for val in df[0]:
                if '　' in str(val):
                    parts = val.split('　')
                    if len(parts) >= 2:
                        code, name = parts[0].strip(), parts[1].strip()
                        # 僅保留 4 位數純數字標的，解決大量 no price data found 報錯
                        if code.isdigit() and len(code) == 4:
                            ticker_data.append(f"{code}{suffix},{name}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_stock_data(tickers_with_names, mode="fast", low=0.0, high=10.0):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    tickers = list(mapping.keys())
    # 抓取資料以計算指標
    data = yf.download(tickers, period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in tickers:
        try:
            t_data = data[t]
            if t_data.empty or len(t_data) < 2: continue
            
            # 處理 MultiIndex 欄位格式
            if isinstance(t_data.columns, pd.MultiIndex):
                t_data.columns = t_data.columns.get_level_values(0)
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = ((c_now - c_pre) / c_pre) * 100
            
            # 若為分組掃描模式，套用漲幅過濾
            if mode == "fast" and not (low <= change <= high): continue
            
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = t_data['Volume'].iloc[-1] / vol_avg if vol_avg > 0 else 0
            info = yf.Ticker(t).info
            turnover = (t_data['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100
            mcap = info.get('marketCap', 0) / 1e8
            
            results.append({
                "選取": False, # --- 修正點：取消自動勾選，預設為 False ---
                "股票代號": t, "名稱": mapping[t],
                "漲幅": round(change, 2), "量比": round(vol_ratio, 2),
                "換手率": round(turnover, 2), "流通市值": f"{round(mcap, 2)} 億"
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. KD 線彈窗函數 (修復 ValueError 版本) ---
@st.dialog("個股 KD 指標分析")
def show_kd_window(item):
    """彈出小視窗顯示圖表與數值"""
    code, name = item.split(',')[0], item.split(',')[1]
    with st.spinner("獲取 KD 數據中..."):
        df = yf.download(code, period="1mo", progress=False)
        
        if not df.empty and len(df) >= 9:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 穩定版計算邏輯：避免 iloc 直接賦值報錯
            low_9 = df['Low'].rolling(window=9).min()
            high_9 = df['High'].rolling(window=9).max()
            rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
            rsv_clean = rsv.fillna(50).tolist() # 預先處理空值
            
            k_list, d_list = [50.0], [50.0]
            for i in range(1, len(rsv_clean)):
                curr_k = k_list[-1] * (2/3) + rsv_clean[i] * (1/3)
                curr_d = d_list[-1] * (2/3) + curr_k * (1/3)
                k_list.append(curr_k)
                d_list.append(curr_d)
            
            df_plot = df.copy()
            df_plot['K'], df_plot['D'] = k_list, d_list
            
            # 繪製圖表
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K'], name='K值 (藍)', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D'], name='D值 (橘)', line=dict(color='orange')))
            fig.update_layout(yaxis=dict(range=[0, 100]), height=350, margin=dict(l=0, r=0, t=30, b=0))
            # 20/80 參考線
            fig.add_hline(y=80, line_dash="dash", line_color="red")
            fig.add_hline(y=20, line_dash="dash", line_color="green")
            st.plotly_chart(fig, use_container_width=True)
            
            st.write(f"當前數值：K = **{round(k_list[-1], 2)}**, D = **{round(d_list[-1], 2)}**")
        else:
            st.error("數據不足，無法生成 KD 圖表。")
            
    if st.button("關閉視窗"): st.rerun()

# --- 4. 側邊欄導覽 (解決 NameError: page) ---
st.sidebar.title("🚀 股市導航選單")
# 優先定義 page 變數，解決 image_076764.png 的問題
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

st.sidebar.markdown("---")

# --- 5. 分頁頁面邏輯 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選系統")
    
    # 參數設定區 (打字輸入模式)
    st.sidebar.subheader("掃描參數")
    low_val = st.sidebar.number_input("漲幅下限 (%)", value=3.0, step=0.1)
    high_val = st.sidebar.number_input("漲幅上限 (%)", value=5.0, step=0.1)
    
    tickers = get_cleaned_tickers()
    group_size = 100
    num_groups = math.ceil(len(tickers) / group_size)
    sel_g = st.sidebar.selectbox("選擇掃描群組 (每組100支)", [f"第 {i+1} 組" for i in range(num_groups)])
    
    if st.button("🚀 開始掃描"):
        with st.spinner(f"正在分析 {sel_g}..."):
            idx = int(sel_g.split(' ')[1]) - 1
            st.session_state['scan_df'] = fetch_stock_data(tickers[idx*group_size : (idx+1)*group_size], mode="fast", low=low_val, high=high_val)

    if 'scan_df' in st.session_state:
        df_scan = st.session_state['scan_df']
        # --- 修正點：確保此處不會再被 apply 自動勾選覆寫 ---
        st.subheader(f"掃描結果 (顯示漲幅 {low_val}% ~ {high_val}% 標的)")
        # 顯示結果表格
        edit_df = st.data_editor(df_scan, hide_index=True, key="scan_editor", use_container_width=True)
        
        if st.button("➕ 將勾選股票加入關注清單"):
            to_add = edit_df[edit_df["選取"] == True]
            for _, row in to_add.iterrows():
                item = f"{row['股票代號']},{row['名稱']}"
                if item not in st.session_state['watchlist']:
                    st.session_state['watchlist'].append(item)
            st.success(f"已成功加入 {len(to_add)} 支標的！")

elif page == "我的關注清單":
    st.header("⭐ 我的關注清單")
    if not st.session_state['watchlist']:
        st.info("目前尚無關注股票，請至掃描頁面手動勾選加入。")
    else:
        if st.button("🔄 刷新最新數據") or 'watch_df' not in st.session_state:
            with st.spinner("同步市場報價中..."):
                st.session_state['watch_df'] = fetch_stock_data(st.session_state['watchlist'], mode="full")
        
        watch_df = st.session_state['watch_df']
        # 顯示關注列表
        for i, row in watch_df.iterrows():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{row['名稱']}** ({row['股票代號']}) | 漲幅: **{row['漲幅']}%** | 量比: **{row['量比']}**")
            # KD 彈窗按鈕
            if c2.button("📈 KD線", key=f"kd_{row['股票代號']}"):
                show_kd_window(f"{row['股票代號']},{row['名稱']}")
            # 移除按鈕
            if c3.button("❌ 移除", key=f"rm_{row['股票代號']}"):
                item = f"{row['股票代號']},{row['名稱']}"
                st.session_state['watchlist'].remove(item)
                st.session_state.pop('watch_df', None)
                st.rerun()
