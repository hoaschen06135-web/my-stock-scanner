import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# 1. 初始化與環境設定
st.set_page_config(layout="wide", page_title="旗艦監控站-終極穩定版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 2. Yahoo 數據抓取：移除 Session 以解決環境衝突
@st.cache_data(ttl=600)
def fetch_market_data(sid_tw):
    try:
        # 不使用自定義 Session，讓 yfinance 自行處理連線
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period='5d')
        # 獲取總股數以解決換手率 0% 問題
        try:
            shares = ticker.fast_info.shares_outstanding
        except:
            shares = ticker.info.get('sharesOutstanding', 0)
            
        if not hist.empty:
            return hist, shares, None
        return pd.DataFrame(), 0, "暫無行情數據"
    except Exception as e:
        return pd.DataFrame(), 0, str(e)

# 3. FinMind 籌碼抓取 (認證保護版)
def fetch_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        time.sleep(0.5) 
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 主介面顯示
st.title("🚀 專業關注清單 (系統修復版)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.error("請確認 Google Sheets 連線。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.subheader(f"{sname} ({sid_tw})")
        c_y, c_fm = st.columns(2)
        
        with c_y:
            if st.button(f"🔍 更新行情 ({sid})", key=f"y_{sid}"):
                with st.spinner("讀取 Yahoo..."):
                    h, s, err = fetch_market_data(sid_tw)
                    if not h.empty:
                        last_p = round(h['Close'].iloc[-1], 2)
                        chg = ((last_p - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
                        vol = h['Volume'].iloc[-1]
                        
                        # 換手率公式：
                        # $$Turnover\ Rate = \frac{Trading\ Volume}{Total\ Shares} \times 100\%$$
                        turnover = (vol / s) * 100 if s > 0 else 0
                        
                        color = "red" if chg > 0 else "green"
                        st.metric("現價", f"{last_p}", f"{chg:.2f}%")
                        st.info(f"今日換手率: {turnover:.2f}%")
                    else:
                        st.error(f"錯誤: {err}")

        with c_fm:
            if st.button(f"📊 讀取籌碼 ({sid})", key=f"fm_{sid}"):
                with st.spinner("讀取 FinMind..."):
                    df = fetch_chips(sid)
                    if not df.empty:
                        last_d = df['date'].max()
                        today = df[df['date'] == last_d]
                        mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                        total_net = 0
                        results = []
                        for label, kw in mapping.items():
                            r = today[today['name'].isin(kw)]
                            if not r.empty:
                                n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                                total_net += n
                                c = "red" if n > 0 else "green"
                                results.append(f"{label}: <span style='color:{c}'>{n}張</span>")
                        
                        t_c = "red" if total_net > 0 else "green"
                        st.write(f"🗓️ {last_d} | 合計: <span style='color:{t_c}'>{total_net}張</span>", unsafe_allow_html=True)
                        st.markdown(f"<small>{' | '.join(results)}</small>", unsafe_allow_html=True)
                    else:
                        st.warning("籌碼資料讀取失敗，請檢查 API 狀態。")
