import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
import requests
from io import StringIO
import math
import urllib3

# 基礎環境與頁面設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股精確篩選系統")

# --- 1. 技術指標與彈出視窗 ---
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
            fig.add_hline(y=80, line_dash="dash", line_color="red")
            fig.add_hline(y=20, line_dash="dash", line_color="green")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("無法讀取歷史數據")

# --- 2. 數據處理函數 ---
def sync_to_sheets(watchlist):
    """將清單同步回 Google Sheets"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist})
        conn.update(worksheet="Sheet1", data=new_df)
        return True
    except Exception as e:
        st.error(f"同步失敗：{e}")
        return False

@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    res = requests.get(url, verify=False)
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    return [f"{str(val).split('　')[0]}.TW,{str(val).split('　')[1]}" for val in df[0] 
            if '　' in str(val) and str(val).split('　')[0].isdigit()]

def fetch_live_data(tickers_with_names, l_chg=-10, l_vol=0):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            results.append({
                "股票代號": t, "名稱": mapping[t], 
                "漲幅(%)": change, "量比": vol_ratio, "目前價格": round(c_now, 2)
            })
        except: continue
    return pd.DataFrame(results)

# --- 3. 介面與導航 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    single_search = st.sidebar.text_input("🔍 單一股票搜尋 (如: 2330)")
    sel_g = st.sidebar.selectbox("1. 選擇掃描群組", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    
    l_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    l_vol = st.sidebar.number_input("量比下限", value=1.0)
    
    if st.button("🚀 開始掃描"):
        with st.spinner("抓取數據中..."):
            if single_search.strip():
                code = f"{single_search.strip()}.TW" if ".TW" not in single_search.upper() else single_search.strip()
                target = [f"{code},搜尋結果"]
            else:
                target = tickers[int(sel_g.split(' ')[1])*100-100 : int(sel_g.split(' ')[1])*100]
            st.session_state['scan_res'] = fetch_live_data(target, l_chg, l_vol)

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            # 增加選取欄位
            df.insert(0, "選取", False)
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 同步選中項目至雲端清單"):
                to_add = edit_df[edit_df["選取"] == True]
                new_items = [f"{r['股票代號']},{r['名稱']}" for _, r in to_add.iterrows()]
                try:
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    df_cloud = conn.read(worksheet="Sheet1", ttl="0")
                    existing = df_cloud["ticker_item"].dropna().tolist() if not df_cloud.empty else []
                    updated = list(set(existing + new_items))
                    if sync_to_sheets(updated): st.success("✅ 已同步至雲端！")
                except: st.error("連線試算表失敗")

elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    if st.button("🔄 刷新即時數據"):
        st.cache_data.clear()
        st.rerun()

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_cloud = conn.read(worksheet="Sheet1", ttl="0")
        watchlist = df_cloud["ticker_item"].dropna().tolist() if not df_cloud.empty else []
        
        if watchlist:
            with st.spinner("抓取即時行情中..."):
                live_df = fetch_live_data(watchlist)
            
            st.info("💡 提示：點擊下方表格選中一列後，即可進行『技術分析』或『刪除股票』。")
            
            # 使用正確的橫線語法 single-row
            event = st.dataframe(live_df, on_select="rerun", selection_mode="single-row", use_container_width=True, hide_index=True)
            
            if event.selection.rows:
                idx = event.selection.rows[0]
                row = live_df.iloc[idx]
                
                # 放置功能按鈕
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📊 查看 {row['名稱']} KD 視窗", use_container_width=True):
                        show_kd_dialog(row['股票代號'], row['名稱'])
                with col2:
                    # 🗑️ 新增刪除功能
                    if st.button(f"🗑️ 從雲端刪除 {row['名稱']}", type="secondary", use_container_width=True):
                        # 重新計算清單，排除掉目前選中的這檔股票
                        ticker_to_remove = row['股票代號']
                        updated_watchlist = [item for item in watchlist if not item.startswith(f"{ticker_to_remove},")]
                        if sync_to_sheets(updated_watchlist):
                            st.success(f"✅ 已成功刪除 {row['名稱']}")
                            st.rerun() # 刪除後自動刷新頁面
        else:
            st.info("目前清單是空的。")
    except Exception as e:
        st.error(f"連線雲端失敗：{e}")
