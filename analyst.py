import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="終極數據監控站-四引擎穩定版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 本地引擎：KDJ 計算 (最穩定，不佔 API 額度) ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

# --- 3. 數據同步核心 (修正 NameError 與限流問題) ---
# 函式定義在最頂層
def sync_all_data(watchlist):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
    except: pass
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        report = {"name": row['名稱'], "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # --- Yahoo 引擎：極簡抓取 (避開限流) ---
        try:
            # 依照報錯建議，停止設定 session，讓 YF 自行處理
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": 0.0}
                report["hist"] = calculate_kdj(hist)
                
                # 嘗試抓取股數 (單獨 try 避免崩潰)
                try:
                    time.sleep(1) # 保護延遲
                    shares = tk.info.get('sharesOutstanding', 0)
                    report["market"]["turnover"] = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                except: pass
        except Exception as e: report["err_y"] = str(e)

        # --- FinMind 引擎：格式防護 (解決 'data' 錯誤) ---
        try:
            time.sleep(0.5)
            # 使用通用接口避開 AttributeError
            raw_chips = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(14)).strftime('%Y-%m-%d')
            )
            # 嚴格預檢，若非 DataFrame 則視為異常
            if isinstance(raw_chips, pd.DataFrame) and not raw_chips.empty:
                last_d = raw_chips['date'].max()
                td = raw_chips[raw_chips['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
            else:
                report["err_f"] = "籌碼接口異常 (可能是流量已滿)"
        except Exception as ef:
            report["err_f"] = f"FinMind 故障: {str(ef)}"
        
        st.session_state.stock_memory[sid] = report

# --- 4. 側邊欄 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    
    try:
        raw_df = conn.read(ttl=600).dropna(how='all')
        watchlist = raw_df.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except: st.stop()

    if st.button("🚀 一鍵同步所有數據指標", use_container_width=True):
        with st.spinner("四引擎同步中..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

# --- 5. 主畫面 ---
st.title("🚀 專業監控站 (旗艦全功能版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_t, col_k = st.columns([7, 3])
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_t: st.subheader(f"{d['name']} ({sid}.TW)")
            with col_k:
                if d["hist"] is not None:
                    with st.popover("📈 查看 KD"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值'))
                        fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                        st.plotly_chart(fig, use_container_width=True)
            
            # 報錯回報
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 籌碼/市值異常: {d['err_f']}")

            if d["market"]:
                m = d["market"]; c1, c2, c3 = st.columns(3)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                # 顯示降級後的狀態
                t_val = f"{m['turnover']:.2f}%" if m['turnover'] > 0 else "Yahoo 限流中"
                c3.metric("換手率", t_val)
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊一鍵同步。")
