import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 介面與記憶體初始化 ---
st.set_page_config(layout="wide", page_title="全指標專業監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 初始化數據保險箱 (Session State)，確保數據不會因為刷新而消失
if 'stock_data' not in st.session_state:
    st.session_state.stock_data = {}

# --- 2. 數據抓取與指標計算核心 ---
def update_all_data(watchlist):
    """一鍵同步更新行情指標與籌碼數據"""
    # 修正 image_30508c.png 的屬性錯誤：改用更穩定的初始化
    try:
        dl = DataLoader()
        # 僅在有 Token 且物件支援時執行登入
        if hasattr(dl, 'login') and TOKEN:
            dl.login(token=TOKEN)
    except:
        dl = None

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        try:
            # A. Yahoo 數據：行情、量比、換手、市值
            ticker = yf.Ticker(sid_tw)
            hist = ticker.history(period='1mo') # 取一個月資料算平均量
            fast = ticker.fast_info
            
            if not hist.empty:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                
                # 1. 漲幅 (Change %)
                chg_pct = ((last_p - prev_p) / prev_p) * 100
                
                # 2. 量比 (Vol Ratio)：今日成交量 / 前5日平均成交量
                avg_vol_5d = hist['Volume'].iloc[-6:-1].mean()
                v_ratio = hist['Volume'].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
                
                # 3. 換手率 (Turnover %)
                shares = fast.shares_outstanding
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                
                # 4. 流通市值 (Market Cap)：單位 億元
                mkt_cap = (last_p * shares) / 100000000
                
                # B. FinMind 數據：三大法人籌碼
                chip_info = {"date": "-", "total": 0, "details": "讀取中..."}
                if dl:
                    time.sleep(0.5) # 避開頻率過快攔截
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
                        chip_info = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                # 寫入記憶體
                st.session_state.stock_data[sid] = {
                    "name": sname, "price": last_p, "change": chg_pct,
                    "v_ratio": v_ratio, "turnover": turnover, "mkt_cap": mkt_cap,
                    "chips": chip_info
                }
        except:
            continue

# --- 3. 側邊欄控制面板 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    # 讀取雲端清單
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.error("無法讀取 Google Sheets")
        st.stop()
        
    if st.button("🚀 一鍵更新所有數據 (常駐)", use_container_width=True):
        with st.spinner("同步行情與籌碼數據中..."):
            update_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除快取記憶", use_container_width=True):
        st.session_state.stock_data = {}
        st.rerun()

# --- 4. 主畫面數據呈現 ---
st.title("🚀 專業關注清單監控 (全指標版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    
    with st.container(border=True):
        if sid in st.session_state.stock_data:
            d = st.session_state.stock_data[sid]
            
            # 標題列
            st.markdown(f"### {d['name']} ({sid}.TW)")
            
            # 第一列：四大核心指標
            c1, c2, c3, c4 = st.columns(4)
            p_color = "red" if d['change'] > 0 else "green"
            
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['v_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 第二列：籌碼深度資訊
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(
                f"<div style='background-color:#f8f9fb; padding:10px; border-radius:5px; margin-top:10px;'>"
                f"🗓️ 數據日期: {c['date']} | 三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span>"
                f"<br><small style='color:#666;'>{c['details']}</small></div>", 
                unsafe_allow_html=True
            )
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未獲取數據，請點擊左側「一鍵更新所有數據」。")
