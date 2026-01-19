import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化環境與記憶體 ---
st.set_page_config(layout="wide", page_title="全指標數據監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 初始化數據儲存空間，確保重新整理後數據常駐
if 'data_cache' not in st.session_state:
    st.session_state.data_cache = {}

# --- 2. 數據更新核心邏輯 ---
def update_stock_metrics(watchlist):
    """一鍵同步所有行情指標與籌碼數據"""
    # 修復 AttributeError: 'DataLoader' object has no attribute 'login'
    dl = DataLoader()
    try:
        if hasattr(dl, 'login'):
            dl.login(token=TOKEN)
    except Exception:
        pass # 若該版本無 login 則跳過，避免程式中斷

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        try:
            # A. 行情指標 (Yahoo Finance)
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='1mo')
            info = tk.fast_info
            
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                
                # 1. 漲幅 (Change Rate)
                change = ((last_p - prev_p) / prev_p) * 100
                
                # 2. 量比 (Volume Ratio)：今日量 / 前5日均量
                avg_vol_5d = hist['Volume'].iloc[-6:-1].mean()
                vol_ratio = hist['Volume'].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
                
                # 3. 換手率 (Turnover)：今日量 / 總股數
                shares = info.shares_outstanding
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                
                # 4. 流通市值 (Market Cap)：億元
                mkt_cap = (last_p * shares) / 100000000
                
                # B. 籌碼數據 (FinMind)
                time.sleep(0.5) 
                df = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, 
                    start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                
                chip_data = {"date": "-", "total": 0, "details": "籌碼讀取失敗"}
                if df is not None and not df.empty:
                    last_d = df['date'].max()
                    td = df[df['date'] == last_d]
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    n_total = 0
                    det = []
                    for label, kw in mapping.items():
                        r = td[td['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            n_total += n
                            det.append(f"{label}: {n}張")
                    chip_data = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                # 儲存到記憶體
                st.session_state.data_cache[sid] = {
                    "name": sname, "price": last_p, "change": change,
                    "vol_ratio": vol_ratio, "turnover": turnover, 
                    "mkt_cap": mkt_cap, "chips": chip_data
                }
        except:
            continue

# --- 3. 側邊欄控制 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.stop()
        
    if st.button("🚀 一鍵更新所有數據", use_container_width=True):
        with st.spinner("正在同步全球行情與法人籌碼..."):
            update_stock_metrics(watchlist)
            st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.data_cache = {}
        st.rerun()

# --- 4. 主畫面數據呈現 ---
st.title("🚀 專業關注清單監控 (全指標版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    
    with st.container(border=True):
        if sid in st.session_state.data_cache:
            d = st.session_state.data_cache[sid]
            st.subheader(f"{d['name']} ({sid}.TW)")
            
            # 顯示四大指標列
            c1, c2, c3, c4 = st.columns(4)
            color = "red" if d['change'] > 0 else "green"
            
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['vol_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 顯示籌碼方塊
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(
                f"<div style='background-color:#f0f2f6; padding:12px; border-radius:8px; border-left: 5px solid #2e7d32;'>"
                f"🗓️ 數據日期: {c['date']} | 三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span>"
                f"<br><small style='color:#555;'>{c['details']}</small></div>", 
                unsafe_allow_html=True
            )
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.info("尚未獲取數據，請點擊左側側邊欄的「一鍵更新所有數據」。")
