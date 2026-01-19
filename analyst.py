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

# 初始化 session_state，確保數據點擊更新後不會消失
if 'data_memory' not in st.session_state:
    st.session_state.data_memory = {}

# --- 2. 核心計算函數 ---
def fetch_and_save_data(watchlist):
    """一鍵抓取所有行情與籌碼指標"""
    dl = DataLoader()
    dl.login(token=TOKEN)
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        try:
            # A. 抓取 Yahoo 數據 (行情、量比、市值)
            ticker = yf.Ticker(sid_tw)
            hist = ticker.history(period='1mo') # 取一個月資料算平均量
            info = ticker.fast_info
            
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg_pct = ((last_p - prev_p) / prev_p) * 100
                
                # 量比計算：今日成交量 / 前5日平均成交量
                avg_vol_5d = hist['Volume'].iloc[-6:-1].mean()
                vol_ratio = hist['Volume'].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
                
                # 換手率與市值
                shares = info.shares_outstanding
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000 # 單位：億元
                
                # B. 抓取 FinMind 數據 (籌碼)
                time.sleep(0.5) # 認證帳號安全緩衝
                chips_df = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, 
                    start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                
                chip_res = {"date": "-", "total": 0, "details": "籌碼讀取失敗"}
                if chips_df is not None and not chips_df.empty:
                    last_d = chips_df['date'].max()
                    td = chips_df[chips_df['date'] == last_d]
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    total_n = 0
                    det = []
                    for label, kw in mapping.items():
                        r = td[td['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            total_n += n
                            c_str = "red" if n > 0 else "green"
                            det.append(f"{label}: <span style='color:{c_str}'>{n}張</span>")
                    chip_res = {"date": last_d, "total": total_n, "details": " | ".join(det)}

                # 存入記憶體
                st.session_state.data_memory[sid] = {
                    "name": sname,
                    "price": last_p,
                    "change": chg_pct,
                    "vol_ratio": vol_ratio,
                    "turnover": turnover,
                    "mkt_cap": mkt_cap,
                    "chips": chip_res
                }
        except Exception as e:
            st.error(f"{sid} 更新錯誤: {str(e)}")

# --- 3. 側邊欄控制面板 ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
    
    st.subheader("批次數據更新")
    if st.button("🚀 一鍵更新所有數據", use_container_width=True):
        with st.spinner("同步抓取 Yahoo 與 FinMind 數據中..."):
            fetch_and_save_data(watchlist)
            st.rerun() # 強制刷新畫面顯示數據

    if st.button("🧹 清除快取記憶", use_container_width=True):
        st.session_state.data_memory = {}
        st.rerun()

# --- 4. 主畫面顯示邏輯 ---
st.title("🚀 專業關注清單監控 (全指標)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    sname = row['名稱']
    
    with st.container(border=True):
        # 檢查記憶體中是否有這支股票的數據
        if sid in st.session_state.data_memory:
            d = st.session_state.data_memory[sid]
            
            # 第一列：現價與基本指標
            col1, col2, col3, col4, col5 = st.columns(5)
            color = "red" if d['change'] > 0 else "green"
            
            col1.metric("現價", f"{d['price']}", f"{d['change']:.2f}%")
            col2.metric("量比", f"{d['vol_ratio']:.2f}")
            col3.metric("換手率", f"{d['turnover']:.2f}%")
            col4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            col5.caption(f"數據時間\n{d['chips']['date']}")
            
            # 第二列：三大法人籌碼
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(
                f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>"
                f"三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span>"
                f"<br><small>{c['details']}</small></div>", 
                unsafe_allow_html=True
            )
        else:
            # 沒數據時的初始狀態
            st.subheader(f"{sname} ({sid}.TW)")
            st.info("請點擊左側「一鍵更新所有數據」按鈕獲取即時指標。")
