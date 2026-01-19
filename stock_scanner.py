import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import os
import time
import urllib3
import plotly.graph_objects as go
from io import StringIO # 修正 read_html 棄用問題

# --- 1. 環境設定與初始化 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = []

# --- 2. 數據抓取與精確篩選函數 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    """強制過濾 $ 符號雜訊，僅保留 4 位數純數字標的，恢復搜尋功能"""
    urls = [("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", ".TW"),
            ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", ".TWO")]
    ticker_data = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url, suffix in urls:
        try:
            res = requests.get(url, headers=headers, verify=False, timeout=10)
            # 使用 StringIO 包裝 HTML，解決 image_0844c5.png 中的棄用警告
            df = pd.read_html(StringIO(res.text))[0].iloc[1:]
            for val in df[0]:
                if '　' in str(val):
                    parts = val.split('　')
                    code, name = parts[0].strip(), parts[1].strip()
                    # 關鍵：排除權證代號，只留 4 位數字，防止 Yahoo 封鎖 IP
                    if code.isdigit() and len(code) == 4:
                        ticker_data.append(f"{code}{suffix},{name}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_stock_data(tickers_with_names, low_chg=0.0, high_chg=10.0, low_vol=0.0, high_vol=99.0, low_turn=0.0, high_turn=99.0):
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

            # 根據側邊欄手動輸入的數值進行篩選
            if not (low_chg <= change <= high_chg): continue
            if not (low_vol <= vol_ratio <= high_vol): continue
            if not (low_turn <= turnover <= high_turn): continue
            
            results.append({
                "選取": False, "股票代號": t, "名稱": mapping[t],
                "漲幅": change, "量比": vol_ratio, "換手率": turnover, "流通市值": mcap
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. KD 線彈窗 (解決 ValueError) ---
@st.dialog("個股 KD 指標分析")
def show_kd_window(item):
    """修復 image_07c11f.png 中的數據賦值錯誤"""
    code, name = item.split(',')[0], item.split(',')[1]
    df = yf.download(code, period="1mo", progress=False)
    if not df.empty and len(df) >= 9:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        low_9, high_9 = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        rsv = ((df['Close'] - low_9) / (high_9 - low_9) * 100).fillna(50).tolist()
        k, d = [50.0], [50.0]
        for i in range(1, len(rsv)):
            k.append(k[-1] * (2/3) + rsv[i] * (1/3))
            d.append(d[-1] * (2/3) + k[-1] * (1/3))
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=k, name='K線', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df.index, y=d, name='D線', line=dict(color='orange')))
        fig.update_layout(yaxis=dict(range=[0, 100]), height=350, margin=dict(l=0, r=0, t=30, b=0))
        # 修正寬度報錯：使用正確的參數
        st.plotly_chart(fig, use_container_width=True)
    if st.button("關閉"): st.rerun()

# --- 4. 側邊欄配置 (群組置頂) ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])
st.sidebar.markdown("---")

# --- 5. 頁面邏輯 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    num_p_g = 100
    num_groups = math.ceil(len(tickers) / num_p_g)
    
    # --- 群組選擇位置移至上方 ---
    st.sidebar.subheader("📦 選擇掃描群組")
    sel_g = st.sidebar.selectbox("每組 100 支標的", [f"第 {i+1} 組" for i in range(num_groups)])
    st.sidebar.markdown("---")
    
    st.sidebar.subheader("🔍 篩選參數設定")
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=3.0, step=0.1)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=5.0, step=0.1)
    low_vol = st.sidebar.number_input("量比下限", value=1.0, step=0.1)
    high_vol = st.sidebar.number_input("量比上限", value=99.0, step=1.0)
    low_turn = st.sidebar.number_input("換手率下限 (%)", value=3.0, step=0.1)
    high_turn = st.sidebar.number_input("換手率上限 (%)", value=5.0, step=0.1)
    
    if st.button("🚀 開始掃描"):
        with st.spinner(f"正在掃描並過濾 {sel_g}..."):
            idx = int(sel_g.split(' ')[1]) - 1
            st.session_state['scan_res'] = fetch_stock_data(
                tickers[idx*num_p_g : (idx+1)*num_p_g], 
                low_chg, high_chg, low_vol, high_vol, low_turn, high_turn
            )

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        st.subheader(f"篩選結果 (符合多重條件共 {len(df)} 支標的)")
        if not df.empty:
            # 解決 image_0848e1.png 寬度報錯：將 width="full" 改回 use_container_width=True
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="scan_editor")
            if st.button("➕ 加入關注清單"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']: st.session_state['watchlist'].append(item)
                st.success("已加入關注！")
        else: st.info("當前條件下無符合標的，請更換群組或調整參數。")

elif page == "我的關注清單":
    st.header("⭐ 我的關注清單")
    if not st.session_state['watchlist']:
        st.info("尚無關注股票。")
    else:
        if st.button("🔄 刷新全部數據") or 'watch_df' not in st.session_state:
            st.session_state['watch_df'] = fetch_stock_data(st.session_state['watchlist'], -10, 10, 0, 99, 0, 99)
        
        watch_df = st.session_state['watch_df']
        for i, row in watch_df.iterrows():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{row['名稱']}** ({row['股票代號']}) | 漲幅: {row['漲幅']}% | 量比: {row['量比']} | 換手: {row['換手率']}%")
            if c2.button("📈 KD線", key=f"kd_{row['股票代號']}"):
                show_kd_window(f"{row['股票代號']},{row['名稱']}")
            if c3.button("❌ 移除", key=f"rm_{row['股票代號']}"):
                st.session_state['watchlist'].remove(f"{row['股票代號']},{row['名稱']}")
                st.session_state.pop('watch_df', None); st.rerun()
