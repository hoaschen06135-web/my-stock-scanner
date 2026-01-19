import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化與記憶體設定 ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 初始化 Session State，確保數據更新後「數據常駐」不會消失
if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 核心數據抓取與指標計算 ---
def sync_all_data(watchlist):
    """一鍵同步更新行情與籌碼數據"""
    # 修正 image_30a344.png 的登入錯誤
    dl = DataLoader()
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        try:
            # A. Yahoo 行情指標 (漲幅、量比、換手、市值)
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='1mo')
            
            # 修正 image_30aac3.png 的屬性錯誤
            info = tk.info
            shares = info.get('sharesOutstanding', 0)
            
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg = ((last_p - prev_p) / prev_p) * 100
                
                # 量比：今日量 / 前5日均量
                avg_vol_5d = hist['Volume'].iloc[-6:-1].mean()
                v_ratio = hist['Volume'].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
                
                # 換手率與市值
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000 # 億元
                
                # B. FinMind 籌碼數據
                time.sleep(0.5) # 避開頻率過快報錯
                chips = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, 
                    start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                
                chip_res = {"date": "-", "total": 0, "details": "無籌碼數據"}
                if chips is not None and not chips.empty:
                    last_d = chips['date'].max()
                    td = chips[chips['date'] == last_d]
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    n_total = 0
                    det = []
                    for label, kw in mapping.items():
                        r = td[td['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            n_total += n
                            det.append(f"{label}: {n}張")
                    chip_res = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                # 寫入常駐記憶體
                st.session_state.stock_memory[sid] = {
                    "name": sname, "price": last_p, "change": chg,
                    "v_ratio": v_ratio, "turnover": turnover, "mkt_cap": mkt_cap,
                    "chips": chip_res
                }
        except Exception as e:
            st.error(f"{sid} 數據更新失敗: {e}")

# --- 3. 側邊欄控制按鈕 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.stop()
        
    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        with st.spinner("正在同步全球行情與法人籌碼..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除數據快取", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 4. 主畫面呈現 ---
st.title("🚀 專業關注清單監控 (全指標常駐版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    
    with st.container(border=True):
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            st.subheader(f"{d['name']} ({sid}.TW)")
            
            # 第一排：四大指標
            c1, c2, c3, c4 = st.columns(4)
            color = "red" if d['change'] > 0 else "green"
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['v_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 第二排：籌碼詳情
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(
                f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; margin-top:10px;'>"
                f"🗓️ 數據日期: {c['date']} | 三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span>"
                f"<br><small>{c['details']}</small></div>", 
                unsafe_allow_html=True
            )
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步數據，請點擊左側「一鍵同步所有數據」。")
