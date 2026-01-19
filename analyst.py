import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境與記憶體 ---
st.set_page_config(layout="wide", page_title="旗艦數據分析站-全功能版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. KDJ 指標計算邏輯 ---
def calculate_kdj(df, n=9, m1=3, m2=3):
    """計算 KDJ 指標"""
    low_list = df['Low'].rolling(window=n).min()
    high_list = df['High'].rolling(window=n).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    df['K'] = rsv.ewm(com=m1-1).mean()
    df['D'] = df['K'].ewm(com=m2-1).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df

# --- 3. 數據更新核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        try:
            # A. Yahoo 行情與 KD 計算
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo') # 抓三個月算 KD 較準
            info = tk.info
            shares = info.get('sharesOutstanding', 0)
            
            if not hist.empty:
                hist = calculate_kdj(hist)
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg = ((last_p - prev_p) / prev_p) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000
                
                # B. FinMind 籌碼
                time.sleep(0.5)
                chips = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                chip_res = {"date": "-", "total": 0, "details": "無籌碼數據"}
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
                            det.append(f"{label}: {n}張")
                    chip_res = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                st.session_state.stock_memory[sid] = {
                    "name": sname, "price": last_p, "change": chg, "v_ratio": v_ratio,
                    "turnover": turnover, "mkt_cap": mkt_cap, "chips": chip_res, "hist": hist
                }
        except: continue

# --- 4. 側邊欄：控制面板 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    
    # 功能一：新增股票到 Sheets
    with st.expander("➕ 新增單一股票"):
        new_sid = st.text_input("股票代號 (如 2330)", key="new_sid")
        new_sname = st.text_input("股票名稱", key="new_sname")
        if st.button("確認新增", use_container_width=True):
            if new_sid and new_sname:
                try:
                    # 讀取現有資料並追加
                    current_data = conn.read().dropna(how='all')
                    new_row = pd.DataFrame([[new_sid, new_sname]], columns=current_data.columns[:2])
                    updated_df = pd.concat([current_data, new_row], ignore_index=True)
                    conn.update(data=updated_df)
                    st.success(f"已成功加入 {new_sname}！")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"寫入失敗: {e}")
            else:
                st.warning("請填寫代號與名稱")

    # 讀取清單
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]

    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        with st.spinner("同步數據中..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除數據快取", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 5. 主畫面呈現 ---
st.title("🚀 專業關注清單監控")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    
    with st.container(border=True):
        # 名稱列與 KD 彈出視窗
        col_title, col_kd = st.columns([7, 3])
        
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_title:
                st.subheader(f"{d['name']} ({sid}.TW)")
            
            with col_kd:
                # 浮動式窗 (Popover) 放在名稱右邊
                with st.popover("📈 查看 KD 趨勢"):
                    st.write(f"**{d['name']} KDJ 技術指標**")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K線', line=dict(color='blue')))
                    fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D線', line=dict(color='orange')))
                    fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
                    st.plotly_chart(fig, use_container_width=True)

            # 四大指標列
            c1, c2, c3, c4 = st.columns(4)
            color = "red" if d['change'] > 0 else "green"
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['v_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 籌碼資訊
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步數據。")
