import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import random
import plotly.graph_objects as go
import urllib3

# --- 1. 初始化 ---
st.set_page_config(layout="wide", page_title="全方位監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets.get("FINMIND_TOKEN", "")

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# 模擬 Headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}

# --- 2. 計算函式 ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def get_streak(df):
    """計算法人連買天數"""
    if not isinstance(df, pd.DataFrame) or df.empty: return 0
    daily = df.groupby('date').apply(lambda x: (pd.to_numeric(x['buy']).sum() - pd.to_numeric(x['sell']).sum())).sort_index(ascending=False)
    streak = 0
    for val in daily:
        if val > 0: streak += 1
        else: break
    return streak

# --- 3. 引擎 B：證交所 OpenAPI (SSL 修復版) ---
@st.cache_data(ttl=3600)
def fetch_twse_data():
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        res = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if res.status_code == 200:
            return pd.DataFrame(res.json()).set_index('Code')
        else: return pd.DataFrame()
    except: return pd.DataFrame()

# --- 4. 同步核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    if TOKEN:
        try: dl.login(token=TOKEN)
        except: pass
    
    twse_stats = fetch_twse_data()
    sids_raw = [str(x).split('.')[0].strip() for x in watchlist['股票代號']]
    sids_tw = [f"{s}.TW" for s in sids_raw]
    
    st.info(f"正在同步 {len(sids_tw)} 檔個股數據...")
    progress_bar = st.progress(0)
    
    try:
        all_hist = yf.download(sids_tw, period='3mo', group_by='ticker', threads=True)
    except: all_hist = pd.DataFrame()

    for i, (sid, sid_full) in enumerate(zip(sids_raw, sids_tw)):
        name = watchlist.iloc[i]['名稱']
        # 初始化報告結構
        report = {
            "name": name, 
            "market": None, # 包含現價、漲幅、量比、換手率、市值
            "chips": None,  # 包含連買天數、詳細張數
            "twse": None,   # 包含 PE, Yield
            "hist": None    # KD 線
        }
        
        # --- 1. Yahoo: 價格、量比、換手率、市值 ---
        try:
            tk = yf.Ticker(sid_full)
            
            # (A) 處理歷史股價與 KD
            if len(sids_tw) > 1:
                hist = all_hist[sid_full].dropna() if sid_full in all_hist else pd.DataFrame()
            else:
                hist = all_hist.dropna()

            if not hist.empty:
                last_p = round(float(hist['Close'].iloc[-1]), 2)
                prev_p = round(float(hist['Close'].iloc[-2]), 2)
                chg = ((last_p - prev_p) / prev_p) * 100
                
                # [新增] 量比計算: 今日量 / 5日均量
                vol_ma5 = hist['Volume'].iloc[-6:-1].mean()
                v_ratio = hist['Volume'].iloc[-1] / vol_ma5 if vol_ma5 > 0 else 0
                
                # [新增] 換手率與市值 (使用 fast_info 避雷)
                try:
                    shares = tk.fast_info['shares']
                    mkt_cap = last_p * shares / 100000000 # 億
                    turnover = (hist['Volume'].iloc[-1] / shares) * 100
                except:
                    shares = 0; mkt_cap = 0; turnover = 0

                report["market"] = {
                    "price": last_p, "change": chg, 
                    "v_ratio": v_ratio, 
                    "turnover": turnover, 
                    "mkt_cap": mkt_cap
                }
                report["hist"] = calculate_kdj(hist)
        except: pass

        # --- 2. 證交所: PE, Yield ---
        if sid in twse_stats.index:
            s = twse_stats.loc[sid]
            report["twse"] = {"pe": s.get('PEratio', '-'), "yield": s.get('DividendYield', '-')}

        # --- 3. FinMind: 法人詳細籌碼 ---
        try:
            time.sleep(random.uniform(0.5, 1.2))
            raw_res = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(40)).strftime('%Y-%m-%d')
            )
            
            if isinstance(raw_res, pd.DataFrame) and not raw_res.empty:
                last_date = raw_res['date'].max()
                today_data = raw_res[raw_res['date'] == last_date]
                
                # [新增] 詳細法人數據拼湊
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self", "Dealer"]}
                net_total = 0; details = []
                
                for label, kw in mapping.items():
                    r = today_data[today_data['name'].isin(kw)]
                    if not r.empty:
                        val = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        net_total += val
                        details.append(f"{label}:{val}")
                
                streak = get_streak(raw_res)
                report["chips"] = {
                    "streak": streak, 
                    "net": net_total, 
                    "details": " | ".join(details)
                }
        except: pass
        
        st.session_state.stock_memory[sid] = report
        progress_bar.progress((i + 1) / len(sids_raw))

    st.success("全指標同步完成！")

# --- 5. UI 呈現 ---
st.title("🛡️ 全方位監控站 (旗艦版)")

with st.sidebar:
    st.header("控制台")
    if st.button("🚀 一鍵同步全清單", use_container_width=True):
        try:
            raw_df = conn.read(ttl=0).dropna(how='all')
            watchlist = raw_df.iloc[:, :2].copy()
            watchlist.columns = ["股票代號", "名稱"]
            sync_all_data(watchlist)
            st.rerun()
        except Exception as e:
            st.error(f"清單讀取失敗: {e}")

if st.session_state.stock_memory:
    # 排序：優先顯示連買天數
    sorted_stocks = sorted(
        st.session_state.stock_memory.items(), 
        key=lambda x: x[1]['chips']['streak'] if x[1]['chips'] else 0, 
        reverse=True
    )

    for sid, d in sorted_stocks:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
            
            # 1. 基本面
            with c1:
                st.subheader(f"{d['name']}")
                st.caption(f"{sid}.TW")
                if d['twse']:
                    st.write(f"PE: {d['twse']['pe']} | 殖利率: {d['twse']['yield']}%")
                if d['market'] and d['market']['mkt_cap'] > 0:
                     st.caption(f"市值: {d['market']['mkt_cap']:.1f}億")

            # 2. 技術指標數據
            with c2:
                if d['market']:
                    m = d['market']
                    st.metric("股價", f"{m['price']}", f"{m['change']:.2f}%")
                    st.caption(f"量比: {m['v_ratio']:.2f} | 換手: {m['turnover']:.2f}%")
                else:
                    st.write("-")

            # 3. 法人籌碼 (含連買標籤 + 詳細數據)
            with c3:
                if d['chips']:
                    streak = d['chips']['streak']
                    net = d['chips']['net']
                    details = d['chips']['details']
                    
                    if streak >= 3:
                        label, color = f"🔥 連買 {streak} 天", "#FF4B4B"
                    elif streak > 0:
                        label, color = f"👍 連買 {streak} 天", "#FFA500"
                    else:
                        label, color = "⚖️ 籌碼觀望", "#808080"
                    
                    st.markdown(f"""
                        <div style='background-color:{color}; padding:8px; border-radius:5px; color:white; text-align:center; margin-bottom:5px;'>
                        <b>{label}</b> (合計 {net} 張)
                        </div>
                        <small style='color:grey'>{details}</small>
                        """, unsafe_allow_html=True)

            # 4. KD 圖
            with c4:
                if d['hist'] is not None:
                    with st.popover("📈 KD 技術圖"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D'))
                        fig.update_layout(height=250, margin=dict(l=0,r=0,t=20,b=0))
                        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("👈 請點擊左側「一鍵同步」開始分析")
