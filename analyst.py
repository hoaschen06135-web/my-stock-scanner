import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站-避險加強版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 核心數據同步邏輯 (雙引擎優化) ---
def sync_all_data(watchlist):
    dl = DataLoader()
    # 登入以獲取更高頻率權限
    try:
        dl.login(token=TOKEN)
    except: pass
    
    # 設定查詢日期範圍 (抓取最近 30 天確保數據完整)
    start_date = (datetime.now() - timedelta(30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # --- 【引擎 A】Yahoo Finance：僅抓取現價與量比 (避開 .info 以防封鎖) ---
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='1mo') 
            if hist.empty:
                report["err_y"] = "Yahoo 限流中"
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": 0.0, "mkt_cap": 0.0}
        except Exception as e:
            report["err_y"] = f"行情連線異常: {e}"

        # --- 【引擎 B】FinMind：抓取 KD、市值、法人 (使用 get_data 避開 AttributeError) ---
        try:
            time.sleep(0.5) # 保護延遲
            
            # 1. 抓取流通市值 (解決抓不到問題)
            mv_data = dl.get_data(dataset="TaiwanStockTotalMarketValue", data_id=sid, start_date=start_date)
            
            # 2. 抓取 KD 技術指標 (直接使用官方數據，不需自算)
            kd_data = dl.get_data(dataset="TaiwanStockKLineTechnicalIndex", data_id=sid, start_date=start_date)
            
            # 3. 抓取法人籌碼
            chips_data = dl.get_data(dataset="TaiwanStockInstitutionalInvestors", data_id=sid, start_date=start_date)

            # --- 處理數據並填入 report ---
            if not mv_data.empty and report["market"]:
                last_mv = mv_data.iloc[-1]['total_market_value']
                report["market"]["mkt_cap"] = round(last_mv / 100000000, 1) # 單位：億
                # 換手率計算: (成交量 * 股價 / 總市值) * 100
                vol = hist['Volume'].iloc[-1]
                report["market"]["turnover"] = (vol * report["market"]["price"] / last_mv) * 100

            if not kd_data.empty:
                # 篩選 KDJ 指標
                k_val = kd_data[kd_data['name'] == 'KDJ_K']
                d_val = kd_data[kd_data['name'] == 'KDJ_D']
                if not k_val.empty:
                    # 合併數據供畫圖使用
                    report["hist"] = pd.DataFrame({
                        'K': k_val['value'].values,
                        'D': d_val['value'].values
                    }, index=k_val['date'])

            if not chips_data.empty:
                last_d = chips_data['date'].max()
                td = chips_data[chips_df['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
            else:
                report["err_f"] = "FinMind 數據源暫無更新"
        except Exception as ef:
            report["err_f"] = f"FinMind 接口故障: {ef}"
        
        st.session_state.stock_memory[sid] = report

# --- 3. 介面呈現 (維持全功能) ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear(); st.rerun()

    try:
        raw = conn.read(ttl=600).dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except: st.stop()

    if st.button("🚀 一鍵同步雙引擎指標", use_container_width=True):
        with st.spinner("同步中..."):
            sync_all_data(watchlist); st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

st.title("🚀 專業數據監控站 (雙引擎避險版)")

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

            if d["market"]:
                m = d["market"]; c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m['turnover']:.2f}%")
                c4.metric("流通市值", f"{m['mkt_cap']:.1f} 億")
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側「一鍵同步」。")
