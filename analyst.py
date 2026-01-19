import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"] 

# --- 2. KD 計算函數 ---
def calculate_kd(df):
    """計算台股標準 KD (9, 3, 3)"""
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
    with st.spinner("獲取歷史數據..."):
        dl = DataLoader()
        try: dl.login(token=TOKEN)
        except: pass
        # 清理代號：移除 .TW 並確保純數字
        pure_id = stock_id.split('.')[0].replace(' ', '')
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        df = dl.taiwan_stock_daily(stock_id=pure_id, start_date=start_dt)
        if df is not None and not df.empty:
            df = calculate_kd(df)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='orange')))
            fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(fig, use_container_width=True)

# --- 4. 主介面：籌碼數據核心修正 ---
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
    st.error("試算表讀取錯誤。")
    st.stop()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

for _, row in watchlist.iterrows():
    # 統一清理代號，防止 image_22aceb.png 的資料干擾
    sid = str(row['股票代號']).split(',')[0].strip()
    sname = str(row['名稱']).strip()
    pure_id = sid.split('.')[0]
    
    c1, c2, c3 = st.columns([2, 5, 1])
    c1.write(f"### {sname}\n`{sid}`")
    
    # --- 法人籌碼顯示區域 ---
    with c2:
        try:
            # 抓取最近 10 天數據以確保包含最新交易日
            start_c = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            inst_df = dl.taiwan_stock_institutional_investors_buy_sell(stock_id=pure_id, start_date=start_c)
            
            if inst_df is not None and not inst_df.empty:
                # 取得最新的一天資料
                latest_date = inst_df['date'].max()
                today_data = inst_df[inst_df['date'] == latest_date]
                
                chips_list = []
                for _, r in today_data.iterrows():
                    # 關鍵修正：強制轉為整數並換算張數
                    net_shares = int(r['buy']) - int(r['sell'])
                    net_lots = net_shares // 1000 
                    color = "red" if net_lots > 0 else "green" if net_lots < 0 else "gray"
                    chips_list.append(f"{r['name']}: <span style='color:{color}'>{net_lots}張</span>")
                
                st.markdown(f"🗓️ {latest_date}<br>{' | '.join(chips_list)}", unsafe_allow_html=True)
            else:
                st.caption("尚未公布最新法人數據")
        except Exception as e:
            # 如果失敗，顯示錯誤原因方便除錯
            st.caption(f"數據解析失敗: {e}")

    if c3.button("📈 分析", key=f"btn_{pure_id}"):
        show_kd_dialog(sid, sname)
