import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# 1. 初始化環境
st.set_page_config(layout="wide", page_title="旗艦監控站-雙按鈕版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 2. Yahoo 數據抓取 (解決行情與換手率問題)
@st.cache_data(ttl=600)
def get_yahoo_data(sid_tw):
    try:
        ticker = yf.Ticker(sid_tw)
        hist = ticker.history(period='1mo')
        shares = ticker.info.get('sharesOutstanding', 0)
        return hist, shares
    except:
        return pd.DataFrame(), 0

# 3. FinMind 籌碼抓取 (獨立按鈕控制)
def get_fm_chips(sid):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
        time.sleep(1) # 保護延遲
        df = dl.taiwan_stock_institutional_investors(
            stock_id=sid, 
            start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
        )
        return df if (df is not None and not df.empty) else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 主介面
st.title("🚀 專業關注清單 (雙來源按鈕控制)")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("清單為空，請從左側新增。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號']).strip()
    sid = sid_full.split('.')[0]
    sid_tw = f"{sid}.TW"
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        st.markdown(f"### **{sname}** `{sid_tw}`")
        
        # UI 第一層：行情 (Yahoo 來源)
        col_y, col_fm = st.columns([1, 1])
        
        with col_y:
            if st.button(f"🔍 檢查行情與換手 ({sid})", key=f"y_{sid}"):
                hist, shares = get_yahoo_data(sid_tw)
                if not hist.empty:
                    last_p = round(hist['Close'].iloc[-1], 2)
                    chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                    vol = hist['Volume'].iloc[-1]
                    # 換手率計算：$$Turnover\ Rate = \frac{Volume}{Total\ Shares} \times 100\%$$
                    turnover = (vol / shares) * 100 if shares > 0 else 0
                    
                    color = "red" if chg > 0 else "green"
                    st.write(f"價: **{last_p}** | 幅: <span style='color:{color}'>{chg:.2f}%</span>", unsafe_allow_html=True)
                    st.write(f"換手率: **{turnover:.2f}%** (分母: Yahoo 提供)")
                else:
                    st.error("Yahoo 行情獲取失敗")

        with col_fm:
            if st.button(f"📊 讀取法人籌碼 ({sid})", key=f"fm_{sid}"):
                with st.spinner("FinMind 數據加載中..."):
                    chips = get_fm_chips(sid)
                    if not chips.empty:
                        last_d = chips['date'].max()
                        today = chips[chips['date'] == last_d]
                        mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                        total_net = 0
                        results = []
                        for label, kw in mapping.items():
                            r = today[today['name'].isin(kw)]
                            if not r.empty:
                                n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                                total_net += n
                                c = "red" if n > 0 else "green"
                                results.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                        
                        t_c = "red" if total_net > 0 else "green"
                        st.write(f"🗓️ {last_d} | 合計: <span style='color:{t_c}'>{total_net}張</span>", unsafe_allow_html=True)
                        st.markdown(f"<small>{' | '.join(results)}</small>", unsafe_allow_html=True)
                    else:
                        st.warning("籌碼額度已滿或頻率過快，請稍後再試")
