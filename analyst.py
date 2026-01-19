import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="行動分析站-診斷版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 核心計算函數 ---
def calculate_metrics(df, total_shares):
    """計算漲幅、量比與換手率"""
    # 自動偵測成交量欄位名稱 (修正 KeyError: 'Volume')
    vol_col = next((c for c in df.columns if c.lower() in ['trading_volume', 'volume', 'vol']), None)
    if not vol_col or len(df) < 5: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
    vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 換手率：成交量 / 總股數
    turnover = (df[vol_col].iloc[-1] / total_shares) * 100 if total_shares > 0 else 0
    
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
    df = dl.taiwan_stock_daily(stock_id=stock_id.split('.')[0], start_date=(datetime.now()-timedelta(60)).strftime('%Y-%m-%d'))
    if df is not None and not df.empty:
        df = calculate_kd(df)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['date'], y=df['K'], name='K 線', line=dict(color='#1E90FF')))
        fig.add_trace(go.Scatter(x=df['date'], y=df['D'], name='D 線', line=dict(color='#FF8C00')))
        fig.update_layout(height=350, margin=dict(l=0,r=0,t=10,b=0), yaxis=dict(range=[0,100]))
        st.plotly_chart(fig, use_container_width=True)

# --- 3. 側邊欄 ---
st.sidebar.title("⚙️ 控制面板")
if st.sidebar.button("🔄 刷新全部數據"):
    st.cache_data.clear()
    st.rerun()

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass

# 修正：確保 stock_id 是字串，解決換手率 0.0% 問題
stock_info = dl.taiwan_stock_info()
stock_info['stock_id'] = stock_info['stock_id'].astype(str)

# --- 4. 主介面 ---
st.title("🚀 專業關注清單監控")

try:
    raw = conn.read().dropna(how='all')
    id_col = [c for c in raw.columns if "代號" in str(c)][0]
    name_col = [c for c in raw.columns if "名稱" in str(c)][0]
    watchlist = raw[[id_col, name_col]].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("請新增股票。")
    st.stop()

# 用於最後除錯的暫存變數
debug_info = {"inst_names": [], "info_cols": list(stock_info.columns)}

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號'])
    sid = sid_full.split('.')[0].strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_full}`")
            df_daily = dl.taiwan_stock_daily(stock_id=sid, start_date=(datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
            
            if df_daily is not None and not df_daily.empty:
                # 偵測股數欄位
                shares_col = next((c for c in stock_info.columns if 'share' in c.lower()), None)
                t_info = stock_info[stock_info['stock_id'] == sid]
                total_shares = t_info[shares_col].values[0] if shares_col and not t_info.empty else 0
                
                m = calculate_metrics(df_daily, total_shares)
                if m:
                    c1, c2, c3, c4 = st.columns(4)
                    color = "red" if m['change'] > 0 else "green"
                    c1.markdown(f"價: **{m['price']}**")
                    c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                    c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                    c4.markdown(f"換手: **{m['turnover']:.1f}%**")
                
                # --- 籌碼顯示與偵測 ---
                inst_df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d'))
                if inst_df is not None and not inst_df.empty:
                    # 紀錄 API 原始名稱
                    debug_info["inst_names"] = list(inst_df['name'].unique())
                    
                    last_d = inst_df['date'].max()
                    today_inst = inst_df[inst_df['date'] == last_d].copy()
                    today_inst['buy'] = pd.to_numeric(today_inst['buy'], errors='coerce')
                    today_inst['sell'] = pd.to_numeric(today_inst['sell'], errors='coerce')
                    
                    mapping = {"外資": ["外資", "Foreign"], "投信": ["投信", "Investment"], "自營": ["自營", "Dealer"]}
                    chips = []
                    total_net = 0
                    for label, kw in mapping.items():
                        r = today_inst[today_inst['name'].str.contains('|'.join(kw), na=False, case=False)]
                        if not r.empty:
                            n = int((r['buy'].sum() - r['sell'].sum()) // 1000)
                            total_net += n
                            c = "red" if n > 0 else "green"
                            chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                    
                    t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                    st.markdown(f"🗓️ {last_d} | 合計: <span style='color:{t_color}'>{total_net}張</span>", unsafe_allow_html=True)
                    st.markdown(f"<small>{' | '.join(chips)}</small>", unsafe_allow_html=True)
            
        with col_btn:
            if st.button("📈", key=f"btn_{sid}"):
                show_kd_dialog(sid, sname)

# --- 5. 除錯診斷區塊 ---
with st.expander("🛠️ API 原始診斷資訊 (若數據不對請截圖此處)"):
    st.write("**發行股數可用欄位:**", debug_info["info_cols"])
    st.write("**法人名稱原始清單:**", debug_info["inst_names"])
