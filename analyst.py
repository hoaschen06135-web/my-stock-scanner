import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="專業關注清單監控-穩定修復版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 數據同步核心邏輯 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
    except: pass
    
    start_date = (datetime.now() - timedelta(30)).strftime('%Y-%m-%d')

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # --- 【引擎 A】Yahoo Finance：負責現價、漲幅、量比、換手率 ---
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='1mo')
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                # 抓取總股數計算換手率
                try:
                    shares = tk.info.get('sharesOutstanding', 0)
                except: shares = 0
                
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                # 換手率公式：成交量 / 總股數
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": turnover}
        except Exception as e:
            report["err_y"] = f"行情故障: {e}"

        # --- 【引擎 B】FinMind：負責 KD、籌碼 (增加格式檢查) ---
        try:
            time.sleep(0.5)
            # 1. 抓取 KD 技術指標
            kd_data = dl.get_data(dataset="TaiwanStockKLineTechnicalIndex", data_id=sid, start_date=start_date)
            # 2. 抓取法人籌碼
            chips_data = dl.get_data(dataset="TaiwanStockInstitutionalInvestors", data_id=sid, start_date=start_date)

            # 處理 KD (檢查是否為 DataFrame)
            if isinstance(kd_data, pd.DataFrame) and not kd_data.empty:
                k_val = kd_data[kd_data['name'] == 'KDJ_K']
                d_val = kd_data[kd_data['name'] == 'KDJ_D']
                if not k_val.empty:
                    report["hist"] = pd.DataFrame({
                        'K': k_val['value'].values,
                        'D': d_val['value'].values
                    }, index=k_val['date'])

            # 處理籌碼 (修正 chips_df 變數錯誤)
            if isinstance(chips_data, pd.DataFrame) and not chips_data.empty:
                last_d = chips_data['date'].max()
                td = chips_data[chips_data['date'] == last_d] # 已修復為 chips_data
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
            else:
                report["err_f"] = "FinMind 數據源回傳格式錯誤或暫無更新"
        except Exception as ef:
            report["err_f"] = f"FinMind 接口故障: {ef}"
        
        st.session_state.stock_memory[sid] = report

# --- 3. 介面呈現 (移除流通市值) ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear(); st.rerun()

    try:
        raw = conn.read(ttl=600).dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except: st.stop()

    if st.button("🚀 一鍵同步數據指標", use_container_width=True):
        with st.spinner("同步中..."):
            sync_all_data(watchlist); st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

st.title("🚀 專業數據監控站 (避險穩定版)")

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
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值 (FinMind)'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值 (FinMind)'))
                        fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                        st.plotly_chart(fig, use_container_width=True)
            
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 財務數據故障: {d['err_f']}")

            # 只顯示三個指標：現價/漲幅, 量比, 換手率
            if d["market"]:
                m = d["market"]; c1, c2, c3 = st.columns(3)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m['turnover']:.2f}%")
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 法人合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側「一鍵同步」。")
