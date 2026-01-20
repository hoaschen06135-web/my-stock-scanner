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
import urllib3 # 用於忽略 SSL 警告

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="法人鎖碼監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets.get("FINMIND_TOKEN", "") 

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# 模擬真實瀏覽器的 Headers (避開證交所擋爬蟲)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}

# --- 2. 核心計算邏輯 ---
def calculate_kdj(df):
    """引擎 A：本地計算 KD"""
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def get_streak(df):
    """計算法人連續買超天數"""
    if not isinstance(df, pd.DataFrame) or df.empty: return 0
    # 合計三大法人每日買賣超
    daily = df.groupby('date').apply(lambda x: (pd.to_numeric(x['buy']).sum() - pd.to_numeric(x['sell']).sum())).sort_index(ascending=False)
    streak = 0
    for val in daily:
        if val > 0: streak += 1
        else: break
    return streak

# --- 3. 引擎 B：證交所 OpenAPI (已修復 SSL 與 NameError) ---
@st.cache_data(ttl=3600)
def fetch_twse_data():
    """直連證交所 JSON API (強制跳過 SSL 驗證)"""
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL"
        
        # [修復] 忽略不安全連線的警告
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # [修復] verify=False 跳過 SSL 檢查，解決 image_4e50eb.png 報錯
        res = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        
        if res.status_code == 200:
            return pd.DataFrame(res.json()).set_index('Code')
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.warning(f"⚠️ 證交所數據連線異常 (已跳過): {e}")
        return pd.DataFrame()

# --- 4. 同步與抓取 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    if TOKEN:
        try: dl.login(token=TOKEN)
        except: pass
    
    # A. 抓取證交所資料 (這裡會調用修復後的函式)
    twse_stats = fetch_twse_data()
    
    # B. 抓取 Yahoo 股價
    sids_raw = [str(x).split('.')[0].strip() for x in watchlist['股票代號']]
    sids_tw = [f"{s}.TW" for s in sids_raw]
    
    st.info(f"正在同步 {len(sids_tw)} 檔個股數據...")
    progress_bar = st.progress(0)
    
    # 一次下載避免迴圈鎖 IP
    try:
        all_hist = yf.download(sids_tw, period='3mo', group_by='ticker', threads=True)
    except:
        all_hist = pd.DataFrame()

    for i, (sid, sid_full) in enumerate(zip(sids_raw, sids_tw)):
        name = watchlist.iloc[i]['名稱']
        report = {"name": name, "market": None, "chips": None, "twse": None, "hist": None}
        
        # 1. 解析 Yahoo
        try:
            if not all_hist.empty:
                # 處理單檔與多檔回傳格式差異
                if len(sids_tw) > 1:
                    hist = all_hist[sid_full].dropna() if sid_full in all_hist else pd.DataFrame()
                else:
                    hist = all_hist.dropna()

                if not hist.empty:
                    last_p = round(float(hist['Close'].iloc[-1]), 2)
                    prev_p = round(float(hist['Close'].iloc[-2]), 2)
                    chg = ((last_p - prev_p) / prev_p) * 100
                    report["market"] = {"price": last_p, "change": chg}
                    report["hist"] = calculate_kdj(hist)
        except: pass

        # 2. 填入證交所本益比/殖利率
        if sid in twse_stats.index:
            s = twse_stats.loc[sid]
            report["twse"] = {"pe": s.get('PEratio', '-'), "yield": s.get('DividendYield', '-')}

        # 3. FinMind 籌碼 (防崩潰 + 隨機延遲)
        try:
            time.sleep(random.uniform(0.5, 1.5)) 
            start_date = (datetime.now() - timedelta(40)).strftime('%Y-%m-%d')
            raw_res = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=start_date
            )
            
            if isinstance(raw_res, pd.DataFrame) and not raw_res.empty:
                last_date = raw_res['date'].max()
                today_data = raw_res[raw_res['date'] == last_date]
                net_buy = (pd.to_numeric(today_data['buy']).sum() - pd.to_numeric(today_data['sell']).sum()) // 1000
                report["chips"] = {"streak": get_streak(raw_res), "net": int(net_buy)}
        except: pass
        
        st.session_state.stock_memory[sid] = report
        progress_bar.progress((i + 1) / len(sids_raw))

    st.success("同步完成！")

# --- 5. UI 呈現 ---
st.title("🛡️ 專業級法人鎖碼監控站")

with st.sidebar:
    st.header("控制台")
    if st.button("🚀 一鍵同步全清單", use_container_width=True):
        try:
            raw_df = conn.read(ttl=0).dropna(how='all')
            watchlist = raw_df.iloc[:, :2].copy()
            watchlist.columns = ["股票代號", "名稱"]
            sync_all_data(watchlist)
            st.rerun()
        except Exception as e:
            st.error(f"清單讀取失敗: {e}")

if st.session_state.stock_memory:
    # 排序：優先顯示連買天數多的
    sorted_stocks = sorted(
        st.session_state.stock_memory.items(), 
        key=lambda x: x[1]['chips']['streak'] if x[1]['chips'] else 0, 
        reverse=True
    )

    for sid, d in sorted_stocks:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
            
            with c1:
                st.subheader(f"{d['name']}")
                st.caption(f"{sid}.TW")
                if d['twse']:
                    st.write(f"PE: {d['twse']['pe']} | 殖利率: {d['twse']['yield']}%")

            with c2:
                if d['market']:
                    st.metric("股價", f"{d['market']['price']}", f"{d['market']['change']:.2f}%")
                else:
                    st.write("-")

            with c3:
                if d['chips']:
                    streak = d['chips']['streak']
                    net = d['chips']['net']
                    if streak >= 3:
                        label, color = f"🔥 強力鎖碼 (連買 {streak} 天)", "#FF4B4B"
                    elif streak > 0:
                        label, color = f"👍 資金流入 (連買 {streak} 天)", "#FFA500"
                    else:
                        label, color = "⚖️ 籌碼觀望", "#808080"
                    
                    st.markdown(f"<div style='background-color:{color}; padding:10px; border-radius:10px; color:white; text-align:center;'><b>{label}</b><br><small>昨日買超: {net} 張</small></div>", unsafe_allow_html=True)

            with c4:
                if d['hist'] is not None:
                    with st.popover("📈 KD 技術圖"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D'))
                        fig.update_layout(height=250, margin=dict(l=0,r=0,t=20,b=0))
                        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("👈 請點擊左側「一鍵同步」開始分析")
