import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化與 Session State ---
st.set_page_config(layout="wide", page_title="旗艦雙引擎數據站-穩定版")
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

# --- 3. 數據同步核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    try:
        dl.login(token=TOKEN)
    except: pass
    
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        # A. Yahoo 引擎：僅抓取股價歷史
        try:
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo') 
            if hist.empty:
                report["err_y"] = "Yahoo 目前限流 (Rate Limited)"
            else:
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                # 初始給予預設值防止 0.0 顯示
                report["market"] = {"price": last_p, "change": chg, "v_ratio": v_ratio, "turnover": 0.0, "mkt_cap": 0.0}
                report["hist"] = calculate_kdj(hist)
        except Exception as e: report["err_y"] = str(e)

        # B. FinMind 引擎：負責市值與籌碼
        try:
            time.sleep(0.5)
            # 擴大查詢範圍至 30 天，確保能抓到市值數據
            mv_df = dl.taiwan_stock_total_market_value(
                stock_id=sid, start_date=(datetime.now()-timedelta(30)).strftime('%Y-%m-%d')
            )
            chips_df = dl.taiwan_stock_institutional_investors(
                stock_id=sid, start_date=(datetime.now()-timedelta(14)).strftime('%Y-%m-%d')
            )
            
            # 修復市值 0.0 問題：偵測欄位名稱
            if mv_df is not None and not mv_df.empty and report["market"]:
                # 嘗試不同的市值欄位名稱
                mv_col = 'total_market_value' if 'total_market_value' in mv_df.columns else 'market_cap'
                last_mv = mv_df.iloc[-1][mv_col]
                mkt_cap_billion = round(last_mv / 100000000, 1)
                
                # 更新市值與換手率
                vol = hist['Volume'].iloc[-1]
                price = report["market"]["price"]
                turnover = (vol * price / last_mv) * 100
                report["market"]["turnover"] = turnover
                report["market"]["mkt_cap"] = mkt_cap_billion
            elif report["market"]:
                report["err_f"] = "FinMind 市值獲取失敗"

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
        except Exception as ef:
            report["err_f"] = f"FinMind 數據異常: {str(ef)}"
        
        st.session_state.stock_memory[sid] = report

# --- 4. 側邊欄與介面 (維持全功能) ---
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

    raw = conn.read(ttl=600).dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]

    if st.button("🚀 一鍵同步所有數據指標", use_container_width=True):
        with st.spinner("雙引擎數據同步中..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除畫面數據", use_container_width=True):
        st.session_state.stock_memory = {}; st.rerun()

# --- 5. 主畫面呈现 ---
st.title("🚀 專業數據監控站 (雙引擎穩定版)")

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
            
            # 診斷訊息回報
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 籌碼/市值故障: {d['err_f']}")

            if d["market"]:
                m = d["market"]; c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                # 換手率與市值若仍為 0 則顯示警告
                c3.metric("換手率", f"{m['turnover']:.2f}%")
                c4.metric("流通市值", f"{m['mkt_cap']:.1f} 億")
            
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側「一鍵同步」。")
