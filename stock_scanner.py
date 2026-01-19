import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import urllib3
import plotly.graph_objects as go
from io import StringIO
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# 基礎環境與頁面設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端篩選系統 (含KD線)")

# --- 1. KD 指標計算函數 ---
def calculate_kd(df, n=9, k_period=3, d_period=3):
    """計算 KD 指標 (9, 3, 3)"""
    low_min = df['Low'].rolling(window=n).min()
    high_max = df['High'].rolling(window=n).max()
    rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
    
    k = rsv.ewm(com=k_period-1, adjust=False).mean()
    d = k.ewm(com=d_period-1, adjust=False).mean()
    return k, d

# --- 2. 同步與讀取函數 ---
def sync_to_sheets(watchlist):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗：{e}")
        return False

def load_watchlist():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        return df["ticker_item"].dropna().unique().tolist() if not df.empty else []
    except:
        return []

# --- 3. 初始化 ---
if 'watchlist' not in st.session_state:
    st.session_state['watchlist'] = load_watchlist()

# --- 4. 數據抓取邏輯 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    res = requests.get(url, verify=False)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    # 使用 yfinance 抓取數據
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    if data.empty: return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            if low_chg <= change <= high_chg and low_vol <= vol_ratio <= high_vol:
                results.append({"選取": False, "股票代號": t, "名稱": mapping[t], "漲幅 (%)": change, "量比": vol_ratio})
        except: continue
    return pd.DataFrame(results)

# --- 5. 側邊欄與頁面切換 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

# --- 頁面一：全市場分組掃描 ---
if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場篩選系統")
    tickers = get_cleaned_tickers()
    
    # 補回「單一股票搜尋」
    single_search = st.sidebar.text_input("🔍 單一股票搜尋 (如: 2330)")
    sel_g = st.sidebar.selectbox("1. 選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    
    # 篩選參數設定
    l_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    l_vol = st.sidebar.number_input("量比下限", value=1.0)
    
    if st.button("🚀 開始掃描"):
        with st.spinner("抓取數據中..."):
            # 優先處理單一搜尋
            if single_search.strip():
                code = f"{single_search.strip()}.TW" if ".TW" not in single_search.upper() else single_search.strip()
                target = [f"{code},搜尋結果"]
            else:
                target = tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
            
            st.session_state['scan_res'] = fetch_stock_data(target, l_chg, 10.0, l_vol, 99.0)

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            # 修正 WidthError
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 同步選中項目至雲端清單"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(item)
                if sync_to_sheets(st.session_state['watchlist']):
                    st.success("✅ 已同步至雲端！")
        else:
            st.warning("查無符合條件的股票。")

# --- 頁面二：我的關注清單 (含 KD 圖表) ---
elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    
    if st.button("🔄 重新從雲端抓取"):
        st.session_state['watchlist'] = load_watchlist()
        st.rerun()
    
    current_watchlist = st.session_state['watchlist']
    if current_watchlist:
        # 顯示清單表格
        display_list = [{"刪除": False, "股票代號": i.split(',')[0], "名稱": i.split(',')[1]} for i in current_watchlist]
        watch_df = pd.DataFrame(display_list)
        edited_watch = st.data_editor(watch_df, hide_index=True, use_container_width=True, key="watch_editor")
        
        if st.button("💾 儲存修改 (刪除選中項)"):
            new_list = [f"{r['股票代號']},{r['名稱']}" for _, r in edited_watch.iterrows() if not r["刪除"]]
            st.session_state['watchlist'] = new_list
            if sync_to_sheets(new_list):
                st.success("✅ 修改已儲存至雲端")
                st.rerun()
        
        # --- KD 線顯示區塊 ---
        st.divider()
        st.subheader("📈 關注個股 KD 趨勢 (近期)")
        
        # 選擇要查看 KD 的股票
        selected_ticker = st.selectbox("請選擇股票查看 KD 線：", [i.split(',')[0] for i in current_watchlist])
        
        if selected_ticker:
            with st.spinner(f"繪製 {selected_ticker} 圖表中..."):
                # 抓取較長期的歷史數據計算 KD
                hist = yf.download(selected_ticker, period="3mo", progress=False)
                if not hist.empty:
                    hist['K'], hist['D'] = calculate_kd(hist)
                    
                    # 繪製 Plotly 圖表
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['K'], name='K值 (9,3)', line=dict(color='blue')))
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['D'], name='D值 (9,3)', line=dict(color='orange')))
                    
                    # 加入 80/20 警戒線
                    fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="超買區")
                    fig.add_hline(y=20, line_dash="dash", line_color="green", annotation_text="超賣區")
                    
                    fig.update_layout(title=f"{selected_ticker} KD 技術指標圖", xaxis_title="日期", yaxis_title="數值", height=400)
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("目前清單是空的。")
