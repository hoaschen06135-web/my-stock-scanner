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

# --- 1. 初始化環境 ---
st.set_page_config(layout="wide", page_title="法人鎖碼監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
# 嘗試轉成字串，避免格式錯誤導致 AttributeError
TOKEN = str(st.secrets.get("FINMIND_TOKEN", ""))

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# 模擬真實瀏覽器 Headers (提升證交所連線成功率)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

# --- 2. 核心計算函式 ---
def calculate_kdj(df):
    """計算 KD 指標"""
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except: return None

def get_streak(df):
    """[核心功能] 計算法人連買天數"""
    if not isinstance(df, pd.DataFrame) or df.empty: return 0
    # 合併三大法人計算單日淨買賣
    daily = df.groupby('date').apply(lambda x: (pd.to_numeric(x['buy']).sum() - pd.to_numeric(x['sell']).sum())).sort_index(ascending=False)
    streak = 0
    for val in daily:
        if val > 0: streak += 1
        else: break
    return streak

# --- 3. 證交所 API (雙保險: BWIBYK + T86) ---
@st.cache_data(ttl=3600)
def fetch_twse_bwibyk():
    """獲取本益比、殖利率 (基本面)"""
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # 延長 timeout 至 20 秒，避免連線逾時
        res = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        if res.status_code == 200: return pd.DataFrame(res.json()).set_index('Code')
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_twse_t86():
    """[備援] 獲取三大法人買賣超日報 (T86_ALL)"""
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/T86_ALL"
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        res = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        if res.status_code == 200: return pd.DataFrame(res.json()).set_index('Code')
    except: pass
    return pd.DataFrame()

# --- 4. 數據同步核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    
    # [修復] 安全登入機制：避免 AttributeError 導致程式崩潰
    if TOKEN and len(TOKEN) > 5:
        try: 
            dl.login(token=TOKEN)
        except Exception as e: 
            print(f"FinMind Login Skipped: {e}")
            # 登入失敗不影響後續，繼續以訪客模式運行
    
    # 預先抓取證交所資料 (雙表)
    twse_bwibyk = fetch_twse_bwibyk()
    twse_t86 = fetch_twse_t86()
    
    # 準備股票代號
    sids_raw = [str(x).split('.')[0].strip() for x in watchlist['股票代號']]
    sids_tw = [f"{s}.TW" for s in sids_raw]
    
    st.info(f"正在同步 {len(sids_tw)} 檔個股數據...")
    progress_bar = st.progress(0)
    
    # Yahoo 批次下載
    try:
        all_hist = yf.download(sids_tw, period='3mo', group_by='ticker', threads=True)
    except: all_hist = pd.DataFrame()

    for i, (sid, sid_full) in enumerate(zip(sids_raw, sids_tw)):
        name = watchlist.iloc[i]['名稱']
        report = {"name": name, "market": None, "chips": None, "twse": None, "hist": None}
        
        # --- 1. Yahoo: 價/量/KD/市值 ---
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

        # --- 2. 證交所基本面 ---
        if sid in twse_bwibyk.index:
            s = twse_bwibyk.loc[sid]
            report["twse"] = {"pe": s.get('PEratio', '-'), "yield": s.get('DividendYield', '-')}

        # --- 3. 法人籌碼 (雙保險邏輯) ---
        chips_found = False
        
        # [優先] FinMind (為了算連買天數)
        try:
            time.sleep(random.uniform(0.5, 1.2)) # 安全延遲
            raw_res = dl.get_data(
                dataset="TaiwanStockInstitutionalInvestors", 
                data_id=sid, 
                start_date=(datetime.now() - timedelta(40)).strftime('%Y-%m-%d')
            )
            
            if isinstance(raw_res, pd.DataFrame) and not raw_res.empty:
                last_date = raw_res['date'].max()
                today_data = raw_res[raw_res['date'] == last_date]
                
                # 詳細數據拼湊
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
        
        # [備援] 證交所 T86 (如果 FinMind 失敗)
        if not chips_found and sid in twse_t86.index:
            try:
                t86 = twse_t86.loc[sid]
                # [關鍵修復] 去除逗號再轉數字
                f_net = int(str(t86.get('ForeignInvestorNetBuySell', '0')).replace(',', '')) // 1000
                t_net = int(str(t86.get('InvestmentTrustNetBuySell', '0')).replace(',', '')) // 1000
                d_self = int(str(t86.get('DealerSelfNetBuySell', '0')).replace(',', ''))
                d_hedge = int(str(t86.get('DealerHedgingNetBuySell', '0')).replace(',', ''))
                d_net = (d_self + d_hedge) // 1000
                
                total_net = f_net + t_net + d_net
                details = f"外資:{f_net} | 投信:{t_net} | 自營:{d_net}"
                
                # 備援模式 streak 設為 None
                report["chips"] = {"streak": None, "net": total_net, "details": details, "source": "TWSE(備援)"}
            except Exception as e:
                print(f"T86 Parse Error: {e}")

        st.session_state.stock_memory[sid] = report
        progress_bar.progress((i + 1) / len(sids_raw))

    st.success("同步完成！")

# --- 5. UI 呈現 ---
st.title("🛡️ 專業級法人鎖碼監控站")

with st.sidebar:
    st.header("控制台")
    if st.button("🧹 清除快取並重整"):
        st.cache_data.clear()
        st.rerun()

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
    # 排序：連買天數 > 0 優先
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
                else:
                    st.write("-")

            with c3:
                if d['chips']:
                    streak = d['chips']['streak']
                    net = d['chips']['net']
                    details = d['chips']['details']
                    source = d['chips'].get('source', '')
                    
                    if streak is not None:
                        if streak >= 3:
                            label, color = f"🔥 連買 {streak} 天", "#FF4B4B"
                        elif streak > 0:
                            label, color = f"👍 連買 {streak} 天", "#FFA500"
                        else:
                            label, color = "⚖️ 籌碼觀望", "#808080"
                    else:
                        label, color = "📊 當日籌碼", "#4682B4"

                    st.markdown(f"""
                        <div style='background-color:{color}; padding:8px; border-radius:5px; color:white; text-align:center; margin-bottom:5px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
                        <b>{label}</b> (合計 {net} 張)
                        </div>
                        <div style='text-align:center; font-size:12px; color:#555;'>{details}</div>
                        """, unsafe_allow_html=True)
                    
                    if source == "TWSE(備援)":
                        st.caption("⚠️ 使用證交所備援數據")
                else:
                    st.info("暫無籌碼數據")

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
