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
st.set_page_config(layout="wide", page_title="法人鎖碼監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
# 確保 Token 格式正確，若無則設為 None
TOKEN = st.secrets.get("FINMIND_TOKEN", None)
if TOKEN and len(TOKEN) < 10: TOKEN = None

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# 模擬真實瀏覽器指紋 (解決 403 Forbidden)
def get_browser_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.twse.com.tw/',
        'Connection': 'keep-alive'
    })
    return s

# --- 2. 核心計算 ---
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
    if not isinstance(df, pd.DataFrame) or df.empty: return 0
    daily = df.groupby('date').apply(lambda x: (pd.to_numeric(x['buy']).sum() - pd.to_numeric(x['sell']).sum())).sort_index(ascending=False)
    streak = 0
    for val in daily:
        if val > 0: streak += 1
        else: break
    return streak

# --- 3. 證交所 API (偽裝瀏覽器版) ---
@st.cache_data(ttl=600) # 縮短快取時間以便重試
def fetch_twse_data_bundle():
    """一次抓取基本面與籌碼面，並回傳狀態"""
    session = get_browser_session()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    data = {"bwibyk": pd.DataFrame(), "t86": pd.DataFrame(), "status": "init"}
    
    # 1. 基本面 (BWIBYK)
    try:
        r1 = session.get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL", timeout=15, verify=False)
        if r1.status_code == 200: 
            data["bwibyk"] = pd.DataFrame(r1.json()).set_index('Code')
    except: pass
    
    # 2. 籌碼面 (T86)
    try:
        r2 = session.get("https://openapi.twse.com.tw/v1/exchangeReport/T86_ALL", timeout=15, verify=False)
        if r2.status_code == 200:
            data["t86"] = pd.DataFrame(r2.json()).set_index('Code')
            data["status"] = "success"
        else:
            data["status"] = f"blocked_{r2.status_code}" # 記錄被封鎖的狀態碼
    except Exception as e:
        data["status"] = f"error_{str(e)}"
        
    return data

# --- 4. 同步核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    
    # FinMind 登入 (失敗則靜音)
    if TOKEN:
        try: dl.login(token=TOKEN)
        except: pass
    
    # 抓取證交所資料包
    bundle = fetch_twse_data_bundle()
    twse_bwibyk = bundle["bwibyk"]
    twse_t86 = bundle["t86"]
    
    # 如果證交所被封鎖，顯示警告
    if "blocked" in bundle["status"] or twse_t86.empty:
        st.toast(f"⚠️ 證交所連線受阻 ({bundle['status']})，啟用備援顯示...", icon="⚠️")

    sids_raw = [str(x).split('.')[0].strip() for x in watchlist['股票代號']]
    sids_tw = [f"{s}.TW" for s in sids_raw]
    
    st.info(f"正在同步 {len(sids_tw)} 檔個股...")
    progress_bar = st.progress(0)
    
    try:
        all_hist = yf.download(sids_tw, period='3mo', group_by='ticker', threads=True)
    except: all_hist = pd.DataFrame()

    for i, (sid, sid_full) in enumerate(zip(sids_raw, sids_tw)):
        name = watchlist.iloc[i]['名稱']
        report = {"name": name, "market": None, "chips": None, "twse": None, "hist": None}
        
        # 1. Yahoo
        try:
            if not all_hist.empty:
                hist = all_hist[sid_full].dropna() if len(sids_tw) > 1 else all_hist.dropna()
                if not hist.empty:
                    last_p = round(float(hist['Close'].iloc[-1]), 2)
                    prev_p = round(float(hist['Close'].iloc[-2]), 2)
                    chg = ((last_p - prev_p) / prev_p) * 100
                    
                    vol_ma5 = hist['Volume'].iloc[-6:-1].mean()
                    v_ratio = hist['Volume'].iloc[-1] / vol_ma5 if vol_ma5 > 0 else 0
                    
                    try:
                        tk = yf.Ticker(sid_full)
                        shares = tk.fast_info['shares']
                        mkt_cap = last_p * shares / 100000000 
                        turnover = (hist['Volume'].iloc[-1] / shares) * 100
                    except:
                        shares = 0; mkt_cap = 0; turnover = 0

                    report["market"] = {
                        "price": last_p, "change": chg, 
                        "v_ratio": v_ratio, "turnover": turnover, "mkt_cap": mkt_cap
                    }
                    report["hist"] = calculate_kdj(hist)
        except: pass

        # 2. 基本面
        if sid in twse_bwibyk.index:
            s = twse_bwibyk.loc[sid]
            report["twse"] = {"pe": s.get('PEratio', '-'), "yield": s.get('DividendYield', '-')}

        # 3. 籌碼 (雙引擎)
        chips_found = False
        
        # [FinMind]
        try:
            time.sleep(random.uniform(0.2, 0.5)) # 降低延遲以防超時
            raw_res = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(40)).strftime('%Y-%m-%d')
            )
            
            if isinstance(raw_res, pd.DataFrame) and not raw_res.empty:
                last_date = raw_res['date'].max()
                today_data = raw_res[raw_res['date'] == last_date]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self", "Dealer"]}
                net_total = 0; details = []
                for label, kw in mapping.items():
                    r = today_data[today_data['name'].isin(kw)]
                    if not r.empty:
                        val = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        net_total += val
                        details.append(f"{label}:{val}")
                
                streak = get_streak(raw_res)
                report["chips"] = {"streak": streak, "net": net_total, "details": " | ".join(details), "source": "FinMind"}
                chips_found = True
        except: pass
        
        # [證交所備援]
        if not chips_found and sid in twse_t86.index:
            try:
                t86 = twse_t86.loc[sid]
                f_net = int(str(t86.get('ForeignInvestorNetBuySell', '0')).replace(',', '')) // 1000
                t_net = int(str(t86.get('InvestmentTrustNetBuySell', '0')).replace(',', '')) // 1000
                d_net = (int(str(t86.get('DealerSelfNetBuySell', '0')).replace(',', '')) + 
                         int(str(t86.get('DealerHedgingNetBuySell', '0')).replace(',', ''))) // 1000
                
                total_net = f_net + t_net + d_net
                details = f"外資:{f_net} | 投信:{t_net} | 自營:{d_net}"
                report["chips"] = {"streak": None, "net": total_net, "details": details, "source": "TWSE"}
            except: pass

        st.session_state.stock_memory[sid] = report
        progress_bar.progress((i + 1) / len(sids_raw))

    st.success("同步完成！")

# --- 5. UI ---
st.title("🛡️ 專業級法人鎖碼監控站")

with st.sidebar:
    st.header("控制台")
    if st.button("🧹 強制重連 (換IP)"):
        st.cache_data.clear()
        st.rerun()

    if st.button("🚀 一鍵同步全清單", use_container_width=True):
        raw_df = conn.read(ttl=0).dropna(how='all')
        watchlist = raw_df.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
        sync_all_data(watchlist)
        st.rerun()

if st.session_state.stock_memory:
    sorted_stocks = sorted(
        st.session_state.stock_memory.items(), 
        key=lambda x: (x[1]['chips']['streak'] if x[1]['chips'] and x[1]['chips']['streak'] else 0), 
        reverse=True
    )

    for sid, d in sorted_stocks:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
            
            with c1:
                st.subheader(f"{d['name']}")
                st.caption(f"{sid}.TW")
                if d['twse']:
                    st.write(f"PE: {d['twse']['pe']} | 殖利率: {d['twse']['yield']}%")
                if d['market'] and d['market']['mkt_cap'] > 0:
                     st.caption(f"市值: {d['market']['mkt_cap']:.1f}億")

            with c2:
                if d['market']:
                    m = d['market']
                    st.metric("股價", f"{m['price']}", f"{m['change']:.2f}%")
                    st.caption(f"量比: {m['v_ratio']:.2f} | 換手: {m['turnover']:.2f}%")
                else: st.write("-")

            with c3:
                if d['chips']:
                    streak = d['chips']['streak']
                    net = d['chips']['net']
                    details = d['chips']['details']
                    source = d['chips'].get('source', '')
                    
                    if streak is not None:
                        if streak >= 3: label, color = f"🔥 連買 {streak} 天", "#FF4B4B"
                        elif streak > 0: label, color = f"👍 連買 {streak} 天", "#FFA500"
                        else: label, color = "⚖️ 籌碼觀望", "#808080"
                    else:
                        label, color = "📊 當日籌碼", "#4682B4"

                    st.markdown(f"""
                        <div style='background-color:{color}; padding:8px; border-radius:5px; color:white; text-align:center; margin-bottom:5px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
                        <b>{label}</b> (合計 {net} 張)
                        </div>
                        <div style='text-align:center; font-size:12px; color:#555;'>{details}</div>
                        """, unsafe_allow_html=True)
                    if source == "TWSE": st.caption("⚠️ 使用證交所備援")
                else:
                    st.info("⚠️ 流量受限，暫無數據")

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
