import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化環境與記憶體 ---
st.set_page_config(layout="wide", page_title="專業數據監控站-除錯版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 初始化數據保險箱
if 'stock_cache' not in st.session_state:
    st.session_state.stock_cache = {}

# --- 2. 數據抓取核心：新增錯誤訊息回報邏輯 ---
def run_full_update(watchlist):
    """一鍵同步更新，並補獲詳細錯誤訊息"""
    # 建立 DataLoader 並檢查登入功能
    try:
        dl = DataLoader()
        if hasattr(dl, 'login'):
            dl.login(token=TOKEN)
    except Exception as e:
        st.sidebar.error(f"FinMind 登入初始化失敗: {str(e)}")
        dl = None

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        # 用於存儲單支股票的所有錯誤訊息
        error_logs = []
        
        try:
            # A. 抓取 Yahoo 數據 (漲幅、量比、換手、市值)
            ticker = yf.Ticker(sid_tw)
            hist = ticker.history(period='1mo')
            info = ticker.fast_info
            
            if hist.empty:
                error_logs.append("Yahoo Finance 回傳空數據 (可能是 Rate Limit)")
                market_data = None
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg_pct = ((last_p - prev_p) / prev_p) * 100
                
                # 量比：今日量 / 前5日均量
                avg_vol_5d = hist['Volume'].iloc[-6:-1].mean()
                v_ratio = hist['Volume'].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
                
                # 換手率與市值
                shares = info.shares_outstanding
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000 # 億
                
                market_data = {
                    "price": last_p, "change": chg_pct, "v_ratio": v_ratio,
                    "turnover": turnover, "mkt_cap": mkt_cap
                }

            # B. 抓取 FinMind 數據 (籌碼)
            chip_res = {"date": "-", "total": 0, "details": "無數據", "error": None}
            if dl:
                try:
                    time.sleep(0.5)
                    df = dl.taiwan_stock_institutional_investors(
                        stock_id=sid, 
                        start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                    )
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
                        chip_res = {"date": last_d, "total": n_total, "details": " | ".join(det), "error": None}
                    else:
                        chip_res["error"] = "FinMind 未回傳籌碼數據"
                except Exception as ce:
                    chip_res["error"] = f"籌碼抓取崩潰: {str(ce)}"

            # 儲存至記憶體
            st.session_state.stock_cache[sid] = {
                "name": sname, "market": market_data, "chips": chip_res,
                "errors": error_logs
            }
            
        except Exception as ge:
            st.session_state.stock_cache[sid] = {"name": sname, "market": None, "chips": None, "errors": [str(ge)]}

# --- 3. 側邊欄：控制與狀態回報 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except Exception as e:
        st.error(f"Google Sheets 連線失敗: {e}")
        st.stop()
        
    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        with st.spinner("同步數據中，請稍候..."):
            run_full_update(watchlist)
            st.rerun()

    if st.button("🧹 清除快取記憶", use_container_width=True):
        st.session_state.stock_cache = {}
        st.rerun()

# --- 4. 主畫面：卡片式呈現 ---
st.title("🚀 專業監控站 (全指標+除錯版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    
    with st.container(border=True):
        if sid in st.session_state.stock_cache:
            d = st.session_state.stock_cache[sid]
            st.subheader(f"{d['name']} ({sid}.TW)")
            
            # 顯示錯誤訊息 (如果有)
            if d['errors']:
                for err in d['errors']:
                    st.error(f"系統訊息: {err}")
            
            # 顯示行情指標
            if d['market']:
                m = d['market']
                c1, c2, c3, c4 = st.columns(4)
                color = "red" if m['change'] > 0 else "green"
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m['turnover']:.2f}%")
                c4.metric("流通市值", f"{m['mkt_cap']:.1f} 億")
            
            # 顯示籌碼指標
            c = d['chips']
            if c and not c.get("error"):
                t_color = "red" if c['total'] > 0 else "green"
                st.markdown(
                    f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; margin-top:5px;'>"
                    f"🗓️ 數據日期: {c['date']} | 三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span>"
                    f"<br><small>{c['details']}</small></div>", 
                    unsafe_allow_html=True
                )
            elif c and c.get("error"):
                st.warning(f"籌碼警告: {c['error']}")
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未獲取數據，請點擊左側「一鍵同步所有數據」。")
