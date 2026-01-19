import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import urllib3
from io import StringIO
from streamlit_gsheets import GSheetsConnection

# 基礎環境設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

# 建立 Google Sheets 連線
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"連線設定錯誤: {e}")
    st.stop()

def sync_to_sheets(watchlist):
    """將清單同步寫回雲端試算表"""
    new_df = pd.DataFrame({"ticker_item": watchlist})
    conn.update(worksheet="Sheet1", data=new_df)

# 初始化關注名單
if 'watchlist' not in st.session_state:
    try:
        df = conn.read(worksheet="Sheet1", ttl="0")
        st.session_state['watchlist'] = df["ticker_item"].dropna().tolist() if not df.empty else []
    except:
        st.session_state['watchlist'] = []

# --- 數據抓取 ---
@st.cache_data(ttl=3600)
def get_cleaned_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    # 修正棄用警告
    df = pd.read_html(StringIO(res.text))[0].iloc[1:]
    ticker_data = []
    for val in df[0]:
        if '　' in str(val):
            code = val.split('　')[0].strip()
            name = val.split('　')[1].strip()
            if code.isdigit() and len(code) == 4:
                ticker_data.append(f"{code}.TW,{name}")
    return ticker_data

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    """核心抓取與篩選邏輯，包含新增加的上限設定"""
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    # 批次下載數據
    data = yf.download(list(mapping.keys()), period="6d", group_by='ticker', progress=False)
    
    results = []
    for t in mapping.keys():
        try:
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            if isinstance(t_data.columns, pd.MultiIndex): t_data.columns = t_data.columns.get_level_values(0)
            
            c_now, c_pre = t_data['Close'].iloc[-1], t_data['Close'].iloc[-2]
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = round(t_data['Volume'].iloc[-1] / vol_avg, 2) if vol_avg > 0 else 0
            
            # 獲取換手率與市值資料
            tk = yf.Ticker(t)
            info = tk.info
            shares = info.get('sharesOutstanding', 1)
            turnover = round((t_data['Volume'].iloc[-1] / shares) * 100, 2)
            mcap = f"{round(info.get('marketCap', 0) / 1e8, 2)} 億"

            # 多重條件篩選 (含上限)
            if not (low_chg <= change <= high_chg and 
                    low_vol <= vol_ratio <= high_vol and 
                    low_turn <= turnover <= high_turn):
                continue
                
            results.append({"選取": False, "股票代號": t, "名稱": mapping[t], "漲幅": change, "量比": vol_ratio, "換手率": turnover, "流通市值": mcap})
        except: continue
    return pd.DataFrame(results)

# --- 側邊欄介面 ---
st.sidebar.title("🚀 股市導航選單")
page = st.sidebar.radio("請選擇頁面：", ["全市場分組掃描", "我的關注清單"])

if page == "全市場分組掃描":
    st.header("⚖️ 台股全市場精確篩選系統")
    tickers = get_cleaned_tickers()
    
    # 1. 位置調整：在群組下方新增單一搜尋
    sel_g = st.sidebar.selectbox("選擇掃描群組 (每組100支)", [f"第 {i+1} 組" for i in range(math.ceil(len(tickers)/100))])
    single_search = st.sidebar.text_input("🔍 單一股票搜尋 (輸入代號，如 2330)", help="若輸入代號，將優先掃描此股票而非群組")
    
    st.sidebar.subheader("🎯 篩選參數設定")
    low_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0)
    high_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0)
    
    # 2. 新增上限設定
    col1, col2 = st.sidebar.columns(2)
    low_vol = col1.number_input("量比下限", value=1.0)
    high_vol = col2.number_input("量比上限", value=99.0)
    
    col3, col4 = st.sidebar.columns(2)
    low_turn = col3.number_input("換手率下限 (%)", value=1.0)
    high_turn = col4.number_input("換手率上限 (%)", value=99.0)
    
    if st.button("🚀 開始掃描"):
        with st.spinner("正在獲取數據..."):
            # 判斷是單一搜尋還是分組掃描
            if single_search.strip():
                code = single_search.strip().split('.')[0]
                target_tickers = [f"{code}.TW,搜尋結果"]
            else:
                idx = int(sel_g.split(' ')[1]) - 1
                target_tickers = tickers[idx*100 : (idx+1)*100]
            
            st.session_state['scan_res'] = fetch_stock_data(target_tickers, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn)

    if 'scan_res' in st.session_state:
        df = st.session_state['scan_res']
        if not df.empty:
            # 修正寬度語法
            edit_df = st.data_editor(df, hide_index=True, use_container_width=True, key="editor")
            if st.button("➕ 同步至雲端關注清單"):
                to_add = edit_df[edit_df["選取"] == True]
                for _, r in to_add.iterrows():
                    item = f"{r['股票代號']},{r['名稱']}"
                    if item not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(item)
                sync_to_sheets(st.session_state['watchlist'])
                st.success("同步成功！")
        else:
            st.warning("查無符合條件的標的。")

# --- 關注清單頁面 ---
elif page == "我的關注清單":
    st.header("⭐ 雲端關注清單管理")
    if st.session_state['watchlist']:
        # 顯示名單邏輯...
        st.write(f"目前共有 {len(st.session_state['watchlist'])} 支關注標的。")
        if st.button("♻️ 重新同步雲端"):
            st.rerun()
    else:
        st.info("目前清單為空，請從掃描頁面加入。")
