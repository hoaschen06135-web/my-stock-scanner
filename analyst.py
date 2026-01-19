import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"] 

# --- 2. 修正後的 KD 計算函數 (FinMind 專用欄位) ---
def calculate_kd(df):
    """修正欄位名稱：FinMind 使用 'min' 與 'max'"""
    # 判斷必要欄位是否存在，避免 KeyError
    if 'min' not in df.columns or 'max' not in df.columns:
        return None
        
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

# --- 3. 分析彈窗 (修正版本不相容問題) ---
@st.dialog("📈 個股深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    with st.spinner("連線 FinMind 數據源..."):
        dl = DataLoader()
        # 嘗試登入，若失敗則繼續執行 (部分版本差異)
        try: dl.login(token=TOKEN)
        except: pass
            
        start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        # 處理股票代號，確保只傳入純數字
        pure_id = stock_id.split('.')[0].replace(' ', '').split(',')[0]
        
        df = dl.taiwan_stock_daily(stock_id=pure_id, start_date=start_dt)
        
        if df is not None and not df.empty:
            df = calculate_kd(df)
            if df is not None:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='blue')))
                fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='orange')))
                fig.update_layout(yaxis=dict(range=[0, 100]), height=400, margin=dict(l=0,r=0,t=20,b=0))
                fig.add_hline(y=80, line_dash="dash", line_color="red")
                fig.add_hline(y=20, line_dash="dash", line_color="green")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("計算指標時發生錯誤，請檢查資料欄位。")
        else:
            st.error(f"找不到代號 {pure_id} 的歷史數據。")

# --- 4. 主介面：處理試算表欄位偏移 ---
st.title("⭐ 雲端關注清單監控")

try:
    # 讀取試算表並強制清理偏移的欄位
    raw_watchlist = conn.read()
    if raw_watchlist is not None and not raw_watchlist.empty:
        # 自動尋找包含「代號」和「名稱」的欄位
        id_col = [c for c in raw_watchlist.columns if "代號" in str(c)][0]
        name_col = [c for c in raw_watchlist.columns if "名稱" in str(c)][0]
        watchlist = raw_watchlist[[id_col, name_col]].dropna()
        watchlist.columns = ["股票代號", "名稱"]
    else:
        st.info("目前雲端清單為空。")
        st.stop()
except:
    st.error("試算表讀取失敗，請確認欄位標題是否有『股票代號』與『名稱』。")
    st.stop()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

for _, row in watchlist.iterrows():
    # 清理代號中的雜訊，防止 image_22aceb.png 中的 CSV 格式干擾
    sid = str(row['股票代號']).split(',')[0].strip()
    sname = str(row['名稱']).strip()
    pure_id = sid.split('.')[0]
    
    c1, c2, c3 = st.columns([2, 5, 1])
    c1.write(f"### {sname}\n`{sid}`")
    
    with c2:
        try:
            start_c = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            inst_df = dl.taiwan_stock_institutional_investors_buy_sell(stock_id=pure_id, start_date=start_c)
            if not inst_df.empty:
                last_dt = inst_df['date'].max()
                today = inst_df[inst_df['date'] == last_dt]
                chips = []
                for _, r in today.iterrows():
                    net = (r['buy'] - r['sell']) // 1000
                    color = "red" if net > 0 else "green"
                    chips.append(f"{r['name']}: <span style='color:{color}'>{net}張</span>")
                st.markdown(f"🗓️ {last_dt}<br>{' | '.join(chips)}", unsafe_allow_html=True)
        except: st.caption("籌碼資料讀取中...")

    if c3.button("📈 分析", key=f"btn_{pure_id}"):
        show_kd_dialog(sid, sname)
