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

# 初始化關注名單
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = []

# --- 2. 數據抓取與計算函數 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
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
                        if code.isdigit() and len(code) == 4:
                            ticker_data.append(f"{code}{suffix},{name}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_stock_data(tickers_with_names, mode="fast", low=0.0, high=10.0):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    tickers = list(mapping.keys())
    data = yf.download(tickers, period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in tickers:
        try:
            t_data = data[t]
            if t_data.empty or len(t_data) < 2: continue
            # 確保欄位是平坦的 (處理 yfinance v0.2+ 格式)
            if isinstance(t_data.columns, pd.MultiIndex):
                t_data.columns = t_data.columns.get_level_values(0)
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = ((c_now - c_pre) / c_pre) * 100
            
            if mode == "fast" and not (low <= change <= high): continue
            
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = t_data['Volume'].iloc[-1] / vol_avg if vol_avg > 0 else 0
            info = yf.Ticker(t).info
            turnover = (t_data['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100
            mcap = info.get('marketCap', 0) / 1e8
            
            results.append({
                "選取": False, "股票代號": t, "名稱": mapping[t],
                "漲幅": round(change, 2), "量比": round(vol_ratio, 2),
                "換手率": round(turnover, 2), "流通市值": f"{round(mcap, 2)} 億"
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. KD 線彈窗函數 (修正版本) ---
@st.dialog("個股 KD 指標分析")
def show_kd_window(item):
    code, name = item.split(',')[0], item.split(',')[1]
    df = yf.download(code, period="1mo", progress=False)
    
    if not df.empty and len(df) >= 9:
        # 修正欄位格式
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # 穩定版 KD 計算 (解決 ValueError)
        low_min = df['Low'].rolling(window=9).min()
        high_max = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50) # 預先處理空值，不要在迴圈中修改
        
        k_vals, d_vals = [50.0], [50.0]
        for i in range(1, len(rsv)):
            current_k = k_vals[-1] * (2/3) + rsv.iloc[i] * (1/3)
            current_d = d_vals[-1] * (2/3) + current_k * (1/3)
            k_vals.append(current_k)
            d_vals.append(current_d)
            
        df['K'], df['D'] = k_vals, d_vals
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], name='K線 (藍)', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], name='D線 (橘)', line=dict(color='orange')))
        fig.update_layout(
            yaxis=dict(range=[0, 100], title="數值"),
            height=350, margin=dict(l=0, r=0, t=30, b=0)
        )
        # 加入 20/80 參考線
        fig.add_hline(y=80, line_dash="dash", line_color="red")
        fig.add_hline(y=20, line_dash="dash", line_color="green")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("數據不足，無法計算 KD 線。")
    if st.button("關閉視窗"): st.rerun()

# --- 4. 導覽選單 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])
st.sidebar.markdown("---")

# --- 5. 頁面邏輯 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選")
    low_in = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    high_in = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    
    tickers = get_cleaned_tickers()
    num_per_group = 100
    num_groups = math.ceil(len(tickers) / num_per_group)
    sel_g = st.sidebar.selectbox("選擇掃描群組", [f"第 {i+1} 組" for i in range(num_groups)])
    
    if st.button("🚀 開始掃描"):
        idx = int(sel_g.split(' ')[1]) - 1
        current_list = tickers[idx*num_per_group : (idx+1)*num_per_group]
        st.session_state['scan_df'] = fetch_stock_data(current_list, low=low_in, high=high_in)

    if 'scan_df' in st.session_state:
        df = st.session_state['scan_df']
        df["選取"] = df["漲幅"].apply(lambda x: 3.0 <= x <= 5.0) # 自動勾選
        edit_df = st.data_editor(df, hide_index=True, key="scan_editor")
        
        if st.button("➕ 將勾選股票加入關注清單"):
            to_add = edit_df[edit_df["選取"] == True]
            for _, row in to_add.iterrows():
                item = f"{row['股票代號']},{row['名稱']}"
                if item not in st.session_state['watchlist']:
                    st.session_state['watchlist'].append(item)
            st.success(f"已加入 {len(to_add)} 支股票")

elif page == "我的關注清單":
    st.header("⭐ 我的關注清單")
    if not st.session_state['watchlist']:
        st.info("尚無關注股票，請至掃描頁面加入。")
    else:
        if st.button("🔄 刷新全部數據") or 'watch_df' not in st.session_state:
            st.session_state['watch_df'] = fetch_stock_data(st.session_state['watchlist'], mode="full")
        
        watch_df = st.session_state['watch_df']
        for i, row in watch_df.iterrows():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{row['名稱']}** ({row['股票代號']}) | 漲幅: {row['漲幅']}% | 量比: {row['量比']}")
            if c2.button("📈 KD線", key=f"kd_{row['股票代號']}"):
                show_kd_window(f"{row['股票代號']},{row['名稱']}")
            if c3.button("❌ 移除", key=f"rm_{row['股票代號']}"):
                item = f"{row['股票代號']},{row['名稱']}"
                st.session_state['watchlist'].remove(item)
                st.session_state.pop('watch_df', None)
                st.rerun()
