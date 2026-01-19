import streamlit as st
import yfinance as yf
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import requests, math, urllib3

# --- 1. 初始化環境與連線 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股全市場精確篩選系統")

# 建立 Google Sheets 連線
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=3600)
def get_clean_tickers():
    """從證交所抓取名單，過濾 4 萬筆雜訊"""
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
                    p = val.split('　')
                    if p[0].isdigit() and len(p[0]) == 4:
                        ticker_data.append(f"{p[0]}{suffix},{p[1]}")
        except: continue
    return sorted(list(set(ticker_data)))

def fetch_data(tickers_with_names, low_chg=0.0, high_chg=10.0, low_vol=1.0, high_vol=99.0, low_turn=0.0, high_turn=100.0):
    if not tickers_with_names: return pd.DataFrame()
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    tickers = list(mapping.keys())
    data = yf.download(tickers, period="6d", group_by='ticker', progress=False)
    res = []
    for t in tickers:
        try:
            d = data[t]
            if d.empty or len(d) < 2: continue
            c_now, c_pre = d['Close'].iloc[-1], d['Close'].iloc[-2]
            change = ((c_now - c_pre) / c_pre) * 100
            vol_avg = d['Volume'].iloc[:-1].mean()
            vol_ratio = d['Volume'].iloc[-1] / vol_avg if vol_avg > 0 else 0
            
            info = yf.Ticker(t).info
            turnover = (d['Volume'].iloc[-1] / info.get('sharesOutstanding', 1)) * 100
            mcap = info.get('marketCap', 0) / 1e8
            
            if not (low_chg <= change <= high_chg): continue
            if not (low_vol <= vol_ratio <= high_vol): continue
            if not (low_turn <= turnover <= high_turn): continue
            
            res.append({
                "選取": True if (3.0 <= change <= 5.0) else False,
                "股票代號": t, "名稱": mapping[t], 
                "漲幅": round(change, 2), "量比": round(vol_ratio, 2),
                "換手率": f"{round(turnover, 2)}%", "流通市值": f"{round(mcap, 2)} 億"
            })
        except: continue
    return pd.DataFrame(res)

# --- 2. 側邊欄介面：找回消失的搜尋與群組 ---
st.sidebar.header("🔍 搜尋與篩選設定")

# 1. 單一股票搜尋
single_q = st.sidebar.text_input("單一股票搜尋 (如: 2330)", placeholder="輸入後按 Enter")

# 2. 掃描群組選擇
all_stocks = get_clean_tickers()
g_size = 100
num_groups = math.ceil(len(all_stocks) / g_size)
sel_group = st.sidebar.selectbox("選擇掃描群組", [f"第 {i+1} 組" for i in range(num_groups)])

st.sidebar.markdown("---")

# 3. 數值參數設定
low_chg = st.sidebar.number_input("漲幅下限 (%)", value=0.0, step=0.1)
high_chg = st.sidebar.number_input("漲幅上限 (%)", value=10.0, step=0.1)
low_vol = st.sidebar.number_input("量比下限", value=1.0, step=0.1)
high_vol = st.sidebar.number_input("量比上限", value=99.0, step=1.0)
low_turn = st.sidebar.number_input("換手率下限 (%)", value=0.0, step=0.1)
high_turn = st.sidebar.number_input("換手率上限 (%)", value=100.0, step=1.0)

# --- 3. 執行邏輯 ---
st.title("⚖️ 台股全市場精確篩選系統")

# 判斷執行模式
if single_q:
    match = [s for s in all_stocks if s.startswith(single_q)]
    if match:
        if st.button(f"🔍 立即查詢 {match[0]}"):
            st.session_state['scan_res'] = fetch_data([match[0]], low_chg=-99, high_chg=99, low_vol=0, low_turn=0)
    else: st.sidebar.error("找不到該代碼")

if st.button(f"🚀 開始掃描 {sel_group}"):
    idx = int(sel_group.split(' ')[1]) - 1
    current_list = all_stocks[idx*g_size : (idx+1)*g_size]
    with st.spinner(f"正在掃描 {sel_group}..."):
        st.session_state['scan_res'] = fetch_data(current_list, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn)

# --- 4. 結果顯示與 Sheets 同步：修正 image_22aceb.png 的偏移 ---
if 'scan_res' in st.session_state:
    df = st.session_state['scan_res']
    if not df.empty:
        edit_df = st.data_editor(df, hide_index=True, key="main_editor", use_container_width=True)
        
        if st.button("➕ 將選中股票同步至 Google Sheets"):
            # 只選取正確的欄位，防止 ticker_item 產生
            to_add = edit_df[edit_df["選取"] == True][["股票代號", "名稱"]]
            
            if not to_add.empty:
                try:
                    existing = conn.read()
                    if existing is not None and not existing.empty:
                        # 確保讀回來的資料也只有這兩欄，避免欄位偏移
                        existing = existing[["股票代號", "名稱"]] if "股票代號" in existing.columns else pd.DataFrame(columns=["股票代號", "名稱"])
                        updated = pd.concat([existing, to_add]).drop_duplicates(subset=["股票代號"])
                    else:
                        updated = to_add
                    
                    conn.update(data=updated)
                    st.success("✅ 同步成功！請至分析頁面查看數據。")
                except Exception as e:
                    st.error(f"同步失敗：{e}")
    else:
        st.info("符合條件的標的為 0，請調整篩選參數。")
