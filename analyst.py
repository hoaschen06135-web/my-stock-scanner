import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 環境初始化與數據常駐設定 ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 技術指標計算 (KDJ) ---
def calculate_kdj(df):
    """計算 9,3,3 的 KDJ 指標"""
    low_9 = df['Low'].rolling(window=9).min()
    high_9 = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
    df['K'] = rsv.ewm(com=2).mean()
    df['D'] = df['K'].ewm(com=2).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df

# --- 3. 核心更新邏輯 (修正 AttributeError) ---
def sync_data(watchlist):
    dl = DataLoader()
    # 修正登入屬性錯誤
    try:
        if hasattr(dl, 'login'): dl.login(token=TOKEN)
    except: pass

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        try:
            # A. Yahoo 數據與 KD 計算
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            # 修正 image_30aac3.png 的屬性抓取路徑
            shares = tk.info.get('sharesOutstanding', 0)
            
            if not hist.empty:
                hist = calculate_kdj(hist)
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000
                
                # B. FinMind 籌碼
                time.sleep(0.5)
                chips = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                chip_res = {"date": "-", "total": 0, "details": "無數據"}
                if chips is not None and not chips.empty:
                    last_d = chips['date'].max()
                    td = chips[chips['date'] == last_d]
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    n_total = 0
                    det = []
                    for label, kw in mapping.items():
                        r = td[td['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            n_total += n
                            det.append(f"{label}:{n}張")
                    chip_res = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                st.session_state.stock_memory[sid] = {
                    "name": row['名稱'], "price": last_p, "change": chg, "v_ratio": v_ratio,
                    "turnover": turnover, "mkt_cap": mkt_cap, "chips": chip_res, "hist": hist
                }
        except: continue

# --- 4. 側邊欄控制面板 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    
    # 功能一：新增股票到 Sheets
    with st.expander("➕ 新增單一股票"):
        add_sid = st.text_input("代號")
        add_name = st.text_input("名稱")
        if st.button("確認寫入 Sheets"):
            if add_sid and add_name:
                try:
                    df_old = conn.read().dropna(how='all')
                    df_new = pd.DataFrame([[add_sid, add_name]], columns=df_old.columns[:2])
                    df_final = pd.concat([df_old, df_new], ignore_index=True)
                    conn.update(data=df_final)
                    st.success("已成功寫入，頁面即將重新整理")
                    time.sleep(1)
                    st.rerun()
                except: st.error("寫入失敗，請檢查權限")

    # 讀取清單
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.stop()

    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        sync_data(watchlist)
        st.rerun()

    if st.button("🧹 清除數據快取", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 5. 主畫面呈現 ---
st.title("🚀 專業關注清單監控")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_title, col_kd = st.columns([7, 3])
        
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_title:
                st.subheader(f"{d['name']} ({sid}.TW)")
            
            with col_kd:
                # 浮動式窗 KD 線圖 (放在名稱右側)
                with st.popover("📈 查看 KD 趨勢"):
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值', line=dict(color='blue')))
                    fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值', line=dict(color='orange')))
                    fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                    st.plotly_chart(fig, use_container_width=True)

            # 四大指標列
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['v_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 籌碼與數據常駐
            c = d['chips']
            t_col = "red" if c['total'] > 0 else "green"
            st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 法人合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未獲取數據，請點擊左側同步按鈕。")
