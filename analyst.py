import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化與記憶體 ---
st.set_page_config(layout="wide", page_title="旗艦雲端監控站-FinMind市值版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. KDJ 指標計算 ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

# --- 3. 數據同步核心 (雙引擎優化) ---
def sync_all_data(watchlist):
    dl = DataLoader()
    dl.login(token=TOKEN)
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "hist": None}
        
        # A. Yahoo 引擎：僅抓取歷史數據計算 漲幅、量比、KD
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo') # 歷史數據請求較輕量，不易被封鎖
            if hist.empty:
                report["err_y"] = "Yahoo 暫時限流"
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio}
                report["hist"] = calculate_kdj(hist)
        except Exception as e: report["err_y"] = str(e)

        # B. FinMind 引擎：抓取 市值 與 籌碼
        try:
            time.sleep(0.5)
            # 獲取最新市值數據
            mv_df = dl.taiwan_stock_total_market_value(
                stock_id=sid, 
                start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
            )
            # 獲取三大法人籌碼
            chips_df = dl.taiwan_stock_institutional_investors(
                stock_id=sid, 
                start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
            )
            
            # 處理市值與換手率
            if mv_df is not None and not mv_df.empty:
                last_mv = mv_df.iloc[-1]['total_market_value'] # 單位：元
                mkt_cap_billion = round(last_mv / 100000000, 1) # 轉換為 億
                
                # 計算換手率：
                # $$Turnover\ Rate = \frac{Trading\ Volume \times Price}{Total\ Market\ Value} \times 100\%$$
                if report["market"]:
                    vol = hist['Volume'].iloc[-1]
                    price = report["market"]["price"]
                    turnover = (vol * price / last_mv) * 100
                    report["market"]["turnover"] = turnover
                    report["market"]["mkt_cap"] = mkt_cap_billion

            # 處理籌碼細節
            if chips_df is not None and not chips_df.empty:
                last_d = chips_df['date'].max()
                td = chips_df[chips_df['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0; det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n; det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
        except: pass
        
        st.session_state.stock_memory[sid] = report

# --- 4. 側邊欄控制 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    with st.expander("➕ 新增股票 (只需編號)"):
        with st.form("add_form", clear_on_submit=True):
            add_sid = st.text_input("股票代號")
            if st.form_submit_button("確認加入"):
                if add_sid:
                    try:
                        tk = yf.Ticker(f"{add_sid}.TW")
                        name = tk.info.get('shortName') or f"股票 {add_sid}"
                        df_old = conn.read(ttl=0).dropna(how='all')
                        df_new = pd.DataFrame([[str(add_sid), name]], columns=df_old.columns[:2])
                        conn.update(data=pd.concat([df_old, df_new], ignore_index=True))
                        st.cache_data.clear(); st.success(f"已加入 {name}"); time.sleep(1); st.rerun()
                    except: st.error("寫入失敗")

    if st.button("🚀 一鍵同步所有數據指標", use_container_width=True):
        sync_all_data(watchlist); st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

# --- 5. 主畫面呈現 ---
st.title("🚀 專業數據監控站 (FinMind 市值版)")
try:
    raw = conn.read(ttl=600).dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except: st.stop()

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
            if d["market"]:
                m = d["market"]; c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m.get('turnover', 0):.2f}%")
                c4.metric("流通市值", f"{m.get('mkt_cap', 0):.1f} 億")
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側「一鍵同步」。")
