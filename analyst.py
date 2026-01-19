import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站-旗艦版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 核心計算函數 ---
def calculate_metrics(df, total_shares):
    """計算漲幅、量比與換手率"""
    # 統一成交量欄位名稱，避免 KeyError
    vol_col = 'Trading_Volume'
    if vol_col not in df.columns or len(df) < 5: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    # 量比：今日量 / 前5日平均量
    avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
    vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 換手率：(今日成交股數 / 總發行張數*1000) * 100%
    turnover = (df[vol_col].iloc[-1] / (total_shares * 1000)) * 100 if total_shares > 0 else 0
    
    return {"price": close_t, "change": change_pct, "vol_ratio": vol_ratio, "turnover": turnover}

def calculate_kd(df):
    low_min = df['min'].rolling(9).min()
    high_max = df['max'].rolling(9).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    k, d = [50.0], [50.0]
    for i in range(1, len(rsv)):
        k.append(k[-1] * (2/3) + rsv.iloc[i] * (1/3))
        d.append(d[-1] * (2/3) + k[-1] * (1/3))
    df['K'], df['D'] = k, d
    return df

@st.dialog("📈 深度分析")
def show_kd_dialog(stock_id, name):
    st.write(f"### {name} ({stock_id})")
    dl = DataLoader()
    try: dl.login(token=TOKEN)
    except: pass
    # 修正：確保傳入 API 的是乾淨的代號字串
    pure_id = str(stock_id).split('.')[0].strip()
    df = dl.taiwan_stock_daily(stock_id=pure_id, start_date=(datetime.now()-timedelta(60)).strftime('%Y-%m-%d'))
    if df is not None and not df.empty:
        df = calculate_kd(df)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='#1E90FF')))
        fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='#FF8C00')))
        fig.update_layout(height=350, margin=dict(l=0,r=0,t=10,b=0), yaxis=dict(range=[0,100]))
        st.plotly_chart(fig, use_container_width=True)

# --- 3. 側邊欄控制 ---
st.sidebar.title("⚙️ 控制面板")
if st.sidebar.button("🔄 刷新全部數據"):
    st.cache_data.clear()
    st.rerun()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

# --- 4. 主介面 ---
st.title("🚀 專業關注清單監控")

try:
    raw = conn.read().dropna(how='all')
    watchlist = raw.iloc[:, :2].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("請新增股票。")
    st.stop()

for _, row in watchlist.iterrows():
    # 強化：代號清理，防止 image_24eb64.png 的 KeyError
    sid_full = str(row['股票代號'])
    sid = sid_full.split('.')[0].replace(' ', '').strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_full}`")
            df_daily = dl.taiwan_stock_daily(stock_id=sid, start_date=(datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
            
            if df_daily is not None and not df_daily.empty:
                # --- 配合「程式 1」的關鍵補強：多源獲取總張數 ---
                try:
                    # 優先從持股分級表加總總股數，這是最精確的來源
                    poll = dl.taiwan_stock_shares_poll(stock_id=sid, start_date=(datetime.now()-timedelta(45)).strftime('%Y-%m-%d'))
                    if not poll.empty:
                        last_p = poll['date'].max()
                        total_shares = poll[poll['date'] == last_p]['number_of_shares'].sum() // 1000
                    else:
                        # 備援：從資產負債表換算
                        fs = dl.taiwan_stock_financial_statement(stock_id=sid, start_date=(datetime.now()-timedelta(365)).strftime('%Y-%m-%d'))
                        target = fs[fs['type'].str.contains('Ordinary_share_capital', na=False)]
                        total_shares = (target['value'].iloc[-1] / 10 / 1000) if not target.empty else 0
                except:
                    total_shares = 0
                
                m = calculate_metrics(df_daily, total_shares)
                if m:
                    c1, c2, c3, c4 = st.columns(4)
                    color = "red" if m['change'] > 0 else "green"
                    c1.markdown(f"價: **{m['price']}**")
                    c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                    c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                    c4.markdown(f"換手: **{m['turnover']:.2f}%**")
                
                # --- 法人籌碼 (鎖定診斷出的英文標籤) ---
                inst_df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
                if inst_df is not None and not inst_df.empty:
                    last_d = inst_df['date'].max()
                    today_inst = inst_df[inst_df['date'] == last_d].copy()
                    
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    chips = []
                    total_net = 0
                    for label, kw in mapping.items():
                        r = today_inst[today_inst['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            total_net += n
                            c = "red" if n > 0 else "green"
                            chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    
                    t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                    st.markdown(f"<small>🗓️ {last_d} | 合計: <span style='color:{t_color}'>{total_net}張</span> | {' '.join(chips)}</small>", unsafe_allow_html=True)
            
        with col_btn:
            if st.button("📈", key=f"btn_{sid}"):
                show_kd_dialog(sid, sname)
