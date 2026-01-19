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

if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = []

# --- 2. 數據抓取與篩選函數 ---
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
                        if code.isdigit() and len(code) == 4:
                            ticker_data.append(f"{code}{suffix},{name}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_stock_data(tickers_with_names, mode="fast", low_chg=0.0, high_chg=10.0, low_vol=0.0, high_vol=99.0, low_turn=0.0, high_turn=99.0):
    """根據多重參數篩選股票"""
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    tickers = list(mapping.keys())
    data = yf.download(tickers, period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in tickers:
        try:
            t_data = data[t]
            if t_data.empty or len(t_data) < 2: continue
            if isinstance(t_data.columns, pd.MultiIndex):
                t_data.columns = t_data.columns.get_level_values(0)
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = round(t_data['Volume'].iloc[-1] / vol_avg, 2) if vol_avg > 0 else 0
            
            info = yf.Ticker(t).info
            turnover = round((t_data['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100, 2)
            mcap = f"{round(info.get('marketCap', 0) / 1e8, 2)} 億"

            # 執行背景篩選
            if not (low_chg <= change <= high_chg): continue
            if not (low_vol <= vol_ratio <= high_vol): continue
            if not (low_turn <= turnover <= high_turn): continue
            
            results.append({
                "選取": False, "股票代號": t, "名稱": mapping[t],
                "漲幅": change, "量比": vol_ratio, "換手率": turnover, "流通市值": mcap
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. KD 線彈窗函數 ---
@st.dialog("個股 KD 指標分析")
def show_kd_window(item):
    """修復版 KD 計算"""
    code, name = item.split(',')[0], item.split(',')[1]
    df = yf.download(code, period="1mo", progress=False)
    if not df.empty and len(df) >= 9:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        low_9, high_9 = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        rsv_clean = rsv.fillna(50).tolist()
        k, d = [50.0], [50.0]
        for i in range(1, len(rsv_clean)):
            curr_k = k[-1] * (2/3) + rsv_clean[i] * (1/3)
            curr_d = d[-1] * (2/3) + curr_k * (1/3)
            k.append(curr_k); d.append(curr_d)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=k, name='K線', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df.index, y=d, name='D線', line=dict(color='orange')))
        fig.update_layout(yaxis=dict(range=[0, 100]), height=350, margin=dict(l=0, r=0, t=30, b=0))
        fig.add_hline(y=80, line_dash="dash", line_color="red")
        fig.add_hline(y=20, line_dash="dash", line_color="green")
        st.plotly_chart(fig, use_container_width=True)
    if st.button("關閉視窗"): st.rerun()

# --- 4. 側邊欄與分頁導覽 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])
st.sidebar.markdown("---")

# --- 5. 頁面邏輯 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    
    # 讀取名單並分組
    tickers = get_cleaned_tickers()
    num_p_g = 100
    num_g = math.ceil(len(tickers) / num_p_g)
    
    # --- 調整位置：群組選擇移至最上方 ---
    st.sidebar.subheader("📦 選擇掃描群組")
    sel_g = st.sidebar.selectbox("每組 100 支標的", [f"第 {i+1} 組" for i in range(num_g)])
    
    st.sidebar.markdown("---")
    
    # --- 篩選參數設定區 ---
    st.sidebar.subheader("🔍 篩選參數設定")
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=3.0, step=0.1)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=5.0, step=0.1)
    low_vol = st.sidebar.number_input("量比下限", value=1.0, step=0.1)
    high_vol = st.sidebar.number_input("量比上限", value=99.0, step=1.0)
    low_turn = st.sidebar.number_input("換手率下限 (%)", value=3.0, step=0.1)
    high_turn = st.sidebar.number_input("換手率上限 (%)", value=5.0, step=0.1)
    
    if st.button("🚀 開始掃描"):
        with st.spinner(f"正在分析並過濾 {sel_g}..."):
            idx = int(sel_g.split(' ')[1]) - 1
            st.session_state['scan_df'] = fetch_stock_data(
                tickers[idx*num_p_g : (idx+1)*num_p_g], 
                low_chg=low_chg, high_chg=high_chg, 
                low_vol=low_vol, high_vol=high_vol, 
                low_turn=low_turn, high_turn=high_turn
            )

    if 'scan_df' in st.session_state:
        df_scan = st.session_state['scan_df']
        st.subheader(f"篩選結果 (符合多重條件共 {len(df_scan)} 支標的)")
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
        st.info("尚無關注股票，請至掃描頁面手動勾選加入。")
    else:
        if st.button("🔄 刷新全清單數據") or 'watch_df' not in st.session_state:
            st.session_state['watch_df'] = fetch_stock_data(st.session_state['watchlist'], mode="full")
        
        watch_df = st.session_state['watch_df']
        for i, row in watch_df.iterrows():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{row['名稱']}** ({row['股票代號']}) | 漲幅: **{row['漲幅']}%** | 量比: **{row['量比']}** | 換手: **{row['換手率']}%**")
            if c2.button("📈 KD線", key=f"kd_{row['股票代號']}"):
                show_kd_window(f"{row['股票代號']},{row['名稱']}")
            if c3.button("❌ 移除", key=f"rm_{row['股票代號']}"):
                item = f"{row['股票代號']},{row['名稱']}"
                st.session_state['watchlist'].remove(item)
                st.session_state.pop('watch_df', None)
                st.rerun()
