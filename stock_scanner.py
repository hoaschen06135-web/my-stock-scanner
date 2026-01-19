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
    if len(df) < 9: return pd.Series(), pd.Series()
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
        else: st.error("無法讀取該股票數據")

# --- 2. 雲端數據處理 ---
def sync_to_sheets(watchlist):
    """將清單同步回雲端，確保不破壞標題列"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_df = pd.DataFrame({"ticker_item": watchlist if watchlist else [None]})
        conn.update(worksheet="Sheet1", data=new_df)
        st.cache_data.clear() 
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗：{e}")
        return False

def load_watchlist_safely():
    """從雲端讀取關注清單"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl="0")
        if df is not None and not df.empty and "ticker_item" in df.columns:
            return df["ticker_item"].dropna().astype(str).unique().tolist()
        return []
    except: return []

# --- 3. 核心數據獲取 (區分篩選模式) ---
def fetch_stock_data(tickers_with_names, l_chg=None, l_vol=None):
    """獲取數據。若 l_chg 為 None，則不進行篩選（用於關注清單）"""
    if not tickers_with_names: return pd.DataFrame()
    valid_items = [t for t in tickers_with_names if ',' in str(t)]
    mapping = {t.split(',')[0]: t.split(',')[1] for t in valid_items}
    
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty: continue
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_ratio = round(t_data['Volume'].iloc[-1] / t_data['Volume'].iloc[:-1].mean(), 2)
            
            # --- 關鍵邏輯：決定是否過濾 ---
            is_match = True
            if l_chg is not None and change < l_chg: is_match = False
            if l_vol is not None and vol_ratio < l_vol: is_match = False
            
            if is_match:
                results.append({"股票代號": t, "名稱": mapping[t], "漲幅(%)": change, "量比": vol_ratio, "目前價格": round(c_now, 2)})
        except: continue
    return pd.DataFrame(results)

# --- 4. 介面呈現 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    # 此處省略 get_cleaned_tickers 代碼以保持簡潔
    
    l_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    l_vol = st.sidebar.number_input("量比下限", value=1.0)
    
    if st.button("🚀 開始篩選掃描"):
        # 傳入篩選參數
        st.session_state['scan_res'] = fetch_stock_data(get_cleaned_tickers()[:100], l_chg, l_vol)

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            if "選取" not in df.columns: df.insert(0, "選取", False)
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 同步選中項目至雲端清單"):
                current = load_watchlist_safely()
                to_add = [f"{r['股票代號']},{r['名稱']}" for _, r in edit_df[edit_df["選取"] == True].iterrows()]
                if sync_to_sheets(list(set(current + to_add))): st.success("✅ 已同步！")
        else: st.warning("目前市場無符合條件的股票。")

elif page == "我的關注清單":
    st.header("⭐ 我的雲端關注清單")
    if st.button("🔄 刷新即時數據"):
        st.cache_data.clear()
        st.rerun()

    watchlist = load_watchlist_safely()
    if watchlist:
        # ⚠️ 注意：此處 fetch_stock_data 不傳入 l_chg/l_vol，代表「不篩選，全部顯示」
        live_df = fetch_stock_data(watchlist)
        
        if not live_df.empty:
            st.info("💡 提示：點擊下方表格選中一列後，即可進行『分析』或『刪除』。")
            event = st.dataframe(live_df, on_select="rerun", selection_mode="single-row", use_container_width=True, hide_index=True)
            
            if event.selection.rows:
                idx = event.selection.rows[0]
                row = live_df.iloc[idx]
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📊 查看 {row['名稱']} KD 視窗", use_container_width=True):
                        show_kd_dialog(row['股票代號'], row['名稱'])
                with col2:
                    if st.button(f"🗑️ 從雲端刪除 {row['名稱']}", type="secondary", use_container_width=True):
                        updated = [item for item in watchlist if not item.startswith(f"{row['股票代號']},")]
                        if sync_to_sheets(updated):
                            st.success(f"✅ 已刪除 {row['名稱']}")
                            st.rerun()
    else: st.info("目前清單是空的。")
