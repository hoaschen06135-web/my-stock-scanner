import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="專業數據監控站-三引擎避險版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# 記憶體常駐數據
if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 核心計算函式 (本地引擎：計算 KD) ---
def calculate_kdj(df):
    """直接在本地端計算 KD，不依賴外部 API 避免出錯"""
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except:
        return None

# --- 3. 數據同步核心 (三引擎邏輯) ---
# 將定義移至頂層，解決 image_320c02.png 的 NameError 問題
def sync_all_data(watchlist):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
    except: pass
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        # 初始狀態結構
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # --- 引擎 A: Yahoo Finance (僅現價/漲幅/量比) ---
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo') # 歷史數據請求較輕量，不易被封鎖
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)" #
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                
                # 同步本地計算 KD
                report["hist"] = calculate_kdj(hist)
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio}
        except Exception as e:
            report["err_y"] = f"連線異常: {str(e)}"

        # --- 引擎 B: FinMind (負責籌碼) ---
        try:
            time.sleep(0.5) # 輕微延遲避檢測
            # 解決 image_3274fc.png 的 'data' KeyError
            raw_data = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(14)).strftime('%Y-%m-%d')
            )
            
            # 嚴格預檢：確保回傳的是 DataFrame 格式
            if isinstance(raw_data, pd.DataFrame) and not raw_data.empty:
                last_d = raw_data['date'].max()
                td = raw_data[raw_data['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
            else:
                report["err_f"] = "籌碼數據目前無法取得 (FinMind 接口無回傳)"
        except Exception as ef:
            report["err_f"] = f"FinMind 故障: {str(ef)}"
        
        st.session_state.stock_memory[sid] = report

# --- 4. 側邊欄控制與清單讀取 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    try:
        raw_list = conn.read(ttl=600).dropna(how='all')
        watchlist = raw_list.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.error("無法連線至 Google Sheets")
        st.stop()

    if st.button("🚀 一鍵同步所有數據指標", use_container_width=True):
        with st.spinner("同步中..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 5. 主畫面數據呈現 ---
st.title("🚀 專業監控站 (三引擎避險版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_title, col_kd = st.columns([7, 3])
        
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_title: st.subheader(f"{d['name']} ({sid}.TW)")
            
            with col_kd:
                # 本地計算的 KD 圖表，保證穩定
                if d["hist"] is not None:
                    with st.popover("📈 查看 KD"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值', line=dict(color='#1f77b4')))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值', line=dict(color='#ff7f0e')))
                        fig.update_layout(height=250, margin=dict(l=5, r=5, t=5, b=5))
                        st.plotly_chart(fig, use_container_width=True)
            
            # 錯誤警示顯示
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 籌碼異常: {d['err_f']}")

            # 行情數據 (現價/漲幅, 量比)
            if d["market"]:
                m = d["market"]
                c1, c2, c3 = st.columns(3)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                # 換手率因 Yahoo 限流嚴重，本版改為提示
                c3.caption("換手率/市值 (Yahoo 限流中)")
            
            # 籌碼數據
            if d["chips"]:
                c = d["chips"]
                t_color = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步數據。")
