import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. KD 計算函數 (FinMind 專用欄位) ---
def calculate_kd(df):
    """計算標準 KD (9, 3, 3)"""
    if 'min' not in df.columns: return None
    low_min = df['min'].rolling(window=9).min()
    high_max = df['max'].rolling(window=9).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        d = d_list[-1] * (2/3) + k * (1/3)
        k_list.append(k); d_list.append(d)
    df['K'], df['D'] = k_list, d_list
    return df

# --- 3. 分析彈窗 ---
@st.dialog("📈 個股深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("抓取 FinMind 數據中..."):
        dl = DataLoader()
        try: dl.login(token=TOKEN)
        except: pass
        pure_id = stock_id.split('.')[0].replace(' ', '').split(',')[0]
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(stock_id=pure_id, start_date=start_dt)
        if df is not None and not df.empty:
            df = calculate_kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='orange')))
            fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("無法取得歷史數據。")

# --- 4. 主介面：籌碼數據核心邏輯 ---
st.title("⭐ 雲端關注清單監控")

try:
    raw_watchlist = conn.read()
    if raw_watchlist is not None and not raw_watchlist.empty:
        # 修正 image_22aceb.png 的欄位偏移
        id_col = [c for c in raw_watchlist.columns if "代號" in str(c)][0]
        name_col = [c for c in raw_watchlist.columns if "名稱" in str(c)][0]
        watchlist = raw_watchlist[[id_col, name_col]].dropna()
        watchlist.columns = ["股票代號", "名稱"]
    else:
        st.stop()
except:
    st.error("試算表讀取錯誤，請確認欄位標題。")
    st.stop()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split(',')[0].strip()
    sname = str(row['名稱']).strip()
    pure_id = sid.split('.')[0]
    
    c1, c2, c3 = st.columns([2, 5, 1])
    c1.write(f"### {sname}\n`{sid}`")
    
    with c2:
        try:
            # 抓取最新法人數據
            start_c = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            inst_df = dl.taiwan_stock_institutional_investors(stock_id=pure_id, start_date=start_c)
            
            if inst_df is not None and not inst_df.empty:
                latest_date = inst_df['date'].max()
                today_data = inst_df[inst_df['date'] == latest_date]
                
                mapping = {"外資": ["外資", "陸資"], "投信": ["投信"], "自營": ["自營"]}
                chips_list = []
                total_net = 0
                
                for label, keywords in mapping.items():
                    r = today_data[today_data['name'].str.contains('|'.join(keywords), na=False)]
                    if not r.empty:
                        net_lots = int((r['buy'].sum() - r['sell'].sum()) // 1000)
                        total_net += net_lots
                        color = "red" if net_lots > 0 else "green" if net_lots < 0 else "gray"
                        chips_list.append(f"{label}: <span style='color:{color}'>{net_lots}張</span>")
                
                total_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                st.markdown(f"🗓️ {latest_date} | 合計: <span style='color:{total_color}'>{total_net}張</span>", unsafe_allow_html=True)
                st.markdown(f"<small>{' | '.join(chips_list)}</small>", unsafe_allow_html=True)
            else:
                st.caption("尚未公布最新法人數據")
        except:
            st.caption("數據解析中...")

    if c3.button("📈 分析", key=f"btn_{pure_id}"):
        show_kd_dialog(sid, sname)
