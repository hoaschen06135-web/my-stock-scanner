import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import random
import plotly.graph_objects as go
import urllib3

# --- 1. 初始化 ---
st.set_page_config(layout="wide", page_title="系統診斷模式")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets.get("FINMIND_TOKEN", "")

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}
if 'debug_log' not in st.session_state:
    st.session_state.debug_log = []

def log(msg):
    st.session_state.debug_log.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")

# Headers 模擬
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

# --- 2. 證交所 API 測試 (不快取，強制測試) ---
def test_twse_connection():
    log("開始測試證交所連線...")
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/T86_ALL"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # 延長 timeout 到 30 秒
        res = requests.get(url, headers=HEADERS, timeout=30, verify=False)
        log(f"證交所回應狀態碼: {res.status_code}")
        
        if res.status_code == 200:
            df = pd.DataFrame(res.json())
            log(f"成功下載 T86 數據，筆數: {len(df)}")
            return df.set_index('Code')
        else:
            log(f"證交所連線失敗，狀態碼非 200")
            return pd.DataFrame()
    except Exception as e:
        log(f"證交所連線報錯: {str(e)}")
        return pd.DataFrame()

# --- 3. FinMind 測試 ---
def test_finmind_connection(sid):
    dl = DataLoader()
    if TOKEN:
        dl.login(token=TOKEN)
    
    log(f"測試 FinMind 抓取 {sid}...")
    try:
        data = dl.get_data(
            dataset="TaiwanStockInstitutionalInvestors",
            data_id=sid,
            start_date=(datetime.now() - timedelta(10)).strftime('%Y-%m-%d')
        )
        if isinstance(data, pd.DataFrame) and not data.empty:
            log(f"FinMind 成功抓到 {len(data)} 筆資料")
            return data
        else:
            log(f"FinMind 回傳空值 (可能是流量耗盡或資料未更新)")
            return None
    except Exception as e:
        log(f"FinMind 報錯: {str(e)}")
        return None

# --- 4. 同步核心 ---
def sync_all_data(watchlist):
    st.session_state.debug_log = [] # 清空日誌
    
    # 1. 測試證交所備援
    twse_t86 = test_twse_connection()
    
    # 2. 抓取 Yahoo
    sids_raw = [str(x).split('.')[0].strip() for x in watchlist['股票代號']]
    sids_tw = [f"{s}.TW" for s in sids_raw]
    try:
        all_hist = yf.download(sids_tw, period='3mo', group_by='ticker', threads=True)
    except Exception as e:
        log(f"Yahoo 下載失敗: {e}")
        all_hist = pd.DataFrame()

    progress_bar = st.progress(0)

    for i, (sid, sid_full) in enumerate(zip(sids_raw, sids_tw)):
        name = watchlist.iloc[i]['名稱']
        report = {"name": name, "market": None, "chips": None, "hist": None}
        
        # Yahoo 處理
        try:
            if not all_hist.empty:
                hist = all_hist[sid_full].dropna() if len(sids_tw) > 1 else all_hist.dropna()
                if not hist.empty:
                    last_p = round(float(hist['Close'].iloc[-1]), 2)
                    report["market"] = {"price": last_p}
        except: pass

        # 籌碼處理 (FinMind + T86)
        chips_data = test_finmind_connection(sid)
        
        if chips_data is not None:
             # FinMind 成功
             last = chips_data.iloc[-1]
             net = int(last['buy']) - int(last['sell'])
             report["chips"] = {"net": net, "source": "FinMind", "msg": "正常"}
        elif sid in twse_t86.index:
             # 切換備援
             try:
                 row = twse_t86.loc[sid]
                 val_str = str(row.get('ForeignInvestorNetBuySell', '0')).replace(',', '')
                 net = int(val_str) // 1000
                 report["chips"] = {"net": net, "source": "TWSE", "msg": "備援成功"}
                 log(f"{name} 使用備援數據成功: {net}")
             except Exception as e:
                 log(f"{name} 備援解析失敗: {e}")
                 report["chips"] = {"net": 0, "source": "Err", "msg": "解析失敗"}
        else:
             report["chips"] = {"net": 0, "source": "None", "msg": "雙引擎皆空"}
             log(f"❌ {name} 無法獲取籌碼 (FinMind空 + T86無資料)")

        st.session_state.stock_memory[sid] = report
        progress_bar.progress((i + 1) / len(sids_raw))

# --- UI ---
st.title("🔧 系統診斷模式")

with st.sidebar:
    st.header("診斷日誌 (Debug Log)")
    if st.button("🚀 開始診斷同步"):
        raw_df = conn.read(ttl=0).dropna(how='all')
        watchlist = raw_df.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
        sync_all_data(watchlist)
    
    # 顯示日誌
    if st.session_state.debug_log:
        st.code("\n".join(st.session_state.debug_log), language="text")

# 顯示卡片
for sid, d in st.session_state.stock_memory.items():
    with st.container(border=True):
        c1, c2 = st.columns(2)
        c1.subheader(f"{d['name']}")
        if d['chips']:
            src = d['chips']['source']
            msg = d['chips']['msg']
            net = d['chips']['net']
            c2.metric(f"籌碼 ({src})", f"{net}", f"{msg}")
        else:
            c2.error("無數據")
