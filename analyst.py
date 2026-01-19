import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化與函式定義 (必須放在最上方，防止 NameError) ---
st.set_page_config(layout="wide", page_title="專業數據監控站-避險穩定版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

def calculate_kdj(df):
    """引擎 3: 本地端計算 KD，不依賴外部 API 避免出錯"""
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def sync_all_data(watchlist):
    """四引擎數據同步核心"""
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    
    start_date = (datetime.now() - timedelta(30)).strftime('%Y-%m-%d')

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # --- 引擎 1 & 3: Yahoo 股價 + 本地 KD ---
        try:
            # 依照報錯建議，不設定自定義 session
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg = ((last_p - prev_p) / prev_p) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": 0.0}
                report["hist"] = calculate_kdj(hist)
                
                # 分離抓取 info 資料，避免因單一項目封鎖導致行情全消失
                try:
                    time.sleep(1) # 保護延遲
                    shares = tk.info.get('sharesOutstanding', 0)
                    report["market"]["turnover"] = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                except: pass
        except Exception as e: report["err_y"] = f"連線異常: {str(e)}"

        # --- 引擎 2: FinMind 籌碼 (格式防護) ---
        try:
            time.sleep(0.5)
            # 使用 get_data 避開屬性缺失問題
            raw_chips = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(14)).strftime('%Y-%m-%d')
            )
            # 解決 KeyError: 'data' 問題
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
                report["err_f"] = "FinMind 數據格式異常或暫無更新"
        except Exception as ef:
            report["err_f"] = f"FinMind 接口故障: {str(ef)}"
        
        st.session_state.stock_memory[sid] = report

# --- 2. 側邊欄控制 ---
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

# --- 3. 主畫面呈現 ---
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
            
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 籌碼/市值異常: {d['err_f']}")

            if d["market"]:
                m = d["market"]; c1, c2, c3 = st.columns(3)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                # 換手率顯示容錯處理
                t_val = f"{m['turnover']:.2f}%" if m['turnover'] > 0 else "Yahoo 限流中"
                c3.metric("換手率", t_val)
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊一鍵同步。")
