import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# --- 1. 初始化與環境設定 ---
st.set_page_config(layout="wide", page_title="專業行動分析站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 核心計算函數 ---
def calculate_metrics(df, total_shares):
    """計算漲幅、量比與換手率"""
    vol_col = 'Trading_Volume' # FinMind 標準成交量欄位
    if vol_col not in df.columns or len(df) < 5: return None
    
    close_t = df['close'].iloc[-1]
    close_y = df['close'].iloc[-2]
    change_pct = ((close_t - close_y) / close_y) * 100
    
    # 量比：今日量 / 前5日平均量
    avg_vol_5d = df[vol_col].iloc[-6:-1].mean()
    vol_ratio = df[vol_col].iloc[-1] / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 換手率：今日成交股數 / 總發行股數
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

@st.dialog("📈 深度分析圖表")
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

# --- 3. 側邊欄：控制與新增 ---
st.sidebar.title("⚙️ 控制面板")

# 手動更新按鈕
if st.sidebar.button("🔄 立即重新整理數據"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("➕ 新增關注股票")
new_sid = st.sidebar.text_input("輸入代號 (如: 2330)")

dl = DataLoader()
try: dl.login(token=TOKEN)
except: pass
stock_info = dl.taiwan_stock_info()

if st.sidebar.button("確認新增"):
    if new_sid:
        with st.sidebar:
            with st.spinner("同步雲端中..."):
                match = stock_info[stock_info['stock_id'] == new_sid]
                if not match.empty:
                    sname = match['stock_name'].values[0]
                    existing = conn.read().dropna(how='all')
                    if new_sid in existing.values:
                        st.warning("已在清單中")
                    else:
                        new_row = pd.DataFrame([{"股票代號": f"{new_sid}.TW", "名稱": sname}])
                        updated = pd.concat([existing, new_row], ignore_index=True)
                        conn.update(data=updated)
                        st.success(f"已新增: {sname}")
                        st.rerun()
                else: st.error("查無此代號")

# --- 4. 主介面顯示 ---
st.title("🚀 專業關注清單監控")

try:
    raw = conn.read().dropna(how='all')
    id_col = [c for c in raw.columns if "代號" in str(c)][0]
    name_col = [c for c in raw.columns if "名稱" in str(c)][0]
    watchlist = raw[[id_col, name_col]].copy()
    watchlist.columns = ["股票代號", "名稱"]
except:
    st.info("清單為空，請從左側新增股票。")
    st.stop()

for _, row in watchlist.iterrows():
    sid_full = str(row['股票代號'])
    sid = sid_full.split('.')[0].strip()
    sname = str(row['名稱']).strip()
    
    with st.container(border=True):
        col_main, col_btn = st.columns([8, 2])
        with col_main:
            st.markdown(f"**{sname}** `{sid_full}`")
            
            # 抓取日數據 (計算漲幅、量比、換手)
            df_daily = dl.taiwan_stock_daily(stock_id=sid, start_date=(datetime.now()-timedelta(15)).strftime('%Y-%m-%d'))
            
            if df_daily is not None and not df_daily.empty:
                # 獲取總發行股數 (換手率關鍵)
                t_info = stock_info[stock_info['stock_id'] == sid]
                # 相容不同版本的欄位名稱
                total_shares = 0
                for col in ['public_shares', 'issued_shares', 'shares']:
                    if col in t_info.columns:
                        total_shares = t_info[col].values[0]
                        break
                
                m = calculate_metrics(df_daily, total_shares)
                if m:
                    c1, c2, c3, c4 = st.columns(4)
                    color = "red" if m['change'] > 0 else "green"
                    c1.markdown(f"價: **{m['price']}**")
                    c2.markdown(f"幅: <span style='color:{color}'>{m['change']:.2f}%</span>", unsafe_allow_html=True)
                    c3.markdown(f"量比: **{m['vol_ratio']:.1f}**")
                    c4.markdown(f"換手: **{m['turnover']:.1f}%**")
                
                # --- 法人籌碼顯示 (優化邏輯) ---
                inst_df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=(datetime.now()-timedelta(20)).strftime('%Y-%m-%d'))
                if inst_df is not None and not inst_df.empty:
                    # 強制轉數值
                    inst_df['buy'] = pd.to_numeric(inst_df['buy'], errors='coerce')
                    inst_df['sell'] = pd.to_numeric(inst_df['sell'], errors='coerce')
                    inst_df['net'] = inst_df['buy'] - inst_df['sell']
                    
                    # 尋找有實際交易數據的最新日期
                    valid_dates = inst_df.groupby('date')['net'].apply(lambda x: x.abs().sum()).reset_index()
                    latest_d = valid_dates[valid_dates['net'] > 0]['date'].max()
                    
                    if pd.notna(latest_d):
                        today_inst = inst_df[inst_df['date'] == latest_d]
                        mapping = {"外資": ["外資", "陸資"], "投信": ["投信"], "自營": ["自營"]}
                        chips = []
                        total_net = 0
                        for label, kw in mapping.items():
                            r = today_inst[today_inst['name'].str.contains('|'.join(kw), na=False)]
                            if not r.empty:
                                n = int(r['net'].sum() // 1000)
                                total_net += n
                                c = "red" if n > 0 else "green"
                                chips.append(f"{label}:<span style='color:{c}'>{n}張</span>")
                        
                        t_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                        # 完整顯示張數數據
                        st.markdown(f"🗓️ {latest_d} | 合計: <span style='color:{t_color}'>{total_net}張</span>", unsafe_allow_html=True)
                        st.markdown(f"<small>{' | '.join(chips)}</small>", unsafe_allow_html=True)
            
        with col_btn:
            if st.button("📈", key=f"btn_{sid}"):
                show_kd_dialog(sid, sname)
