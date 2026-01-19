import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境與數據記憶體 ---
st.set_page_config(layout="wide", page_title="旗艦診斷監控站")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. 技術指標計算 (KDJ) ---
def calculate_kdj(df):
    try:
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        df['K'] = rsv.ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        return df
    except:
        return df

# --- 3. 數據同步核心：新增詳細錯誤捕捉機制 ---
def sync_data_with_report(watchlist):
    dl = DataLoader()
    # 修正 image_30a344.png 的登入錯誤
    try:
        if hasattr(dl, 'login'): dl.login(token=TOKEN)
    except Exception as e:
        st.sidebar.warning(f"FinMind 登入略過: {e}")

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        
        # 準備存儲單支股票的數據與錯誤報告
        report = {"name": sname, "market": None, "chips": None, "err_y": None, "err_f": None, "hist": None}
        
        try:
            # A. Yahoo 數據抓取
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            
            if hist.empty:
                report["err_y"] = "Yahoo 回傳空數據 (請檢查代號或稍後再試)"
            else:
                # 修正 image_30aac3.png 屬性錯誤
                shares = tk.info.get('sharesOutstanding', 0)
                last_p = round(hist['Close'].iloc[-1], 2)
                chg = ((last_p - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                v_ratio = hist['Volume'].iloc[-1] / hist['Volume'].iloc[-6:-1].mean()
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000
                
                report["market"] = {
                    "price": last_p, "change": chg, "v_ratio": v_ratio,
                    "turnover": turnover, "mkt_cap": mkt_cap
                }
                report["hist"] = calculate_kdj(hist)
        except Exception as ey:
            report["err_y"] = f"Yahoo 指標錯誤: {str(ey)}"

        try:
            # B. FinMind 數據抓取
            time.sleep(0.5)
            df = dl.taiwan_stock_institutional_investors(
                stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
            )
            if df is not None and not df.empty:
                last_d = df['date'].max()
                td = df[df['date'] == last_d]
                mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                n_total = 0
                det = []
                for label, kw in mapping.items():
                    r = td[td['name'].isin(kw)]
                    if not r.empty:
                        n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                        n_total += n
                        det.append(f"{label}:{n}張")
                report["chips"] = {"date": last_d, "total": n_total, "details": " | ".join(det)}
            else:
                report["err_f"] = "FinMind 查無今日籌碼"
        except Exception as ef:
            report["err_f"] = f"FinMind 籌碼錯誤: {str(ef)}"

        # 更新至記憶體
        st.session_state.stock_memory[sid] = report

# --- 4. 側邊欄控制面板 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    
    with st.expander("➕ 新增股票"):
        add_sid = st.text_input("代號")
        add_name = st.text_input("名稱")
        if st.button("確認寫入"):
            try:
                df_old = conn.read().dropna(how='all')
                df_new = pd.DataFrame([[add_sid, add_name]], columns=df_old.columns[:2])
                conn.update(data=pd.concat([df_old, df_new], ignore_index=True))
                st.success("成功！頁面即將刷新"); time.sleep(1); st.rerun()
            except: st.error("寫入失敗，請檢查權限")

    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except: st.stop()

    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        with st.spinner("同步與診斷中..."):
            sync_data_with_report(watchlist)
            st.rerun()

    if st.button("🧹 清除數據快取", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 5. 主畫面數據呈現 ---
st.title("🚀 專業監控站 (診斷回報版)")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    with st.container(border=True):
        col_title, col_kd = st.columns([7, 3])
        
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_title:
                st.subheader(f"{d['name']} ({sid}.TW)")
            
            # --- 錯誤訊息回報區 ---
            if d["err_y"]: st.error(f"⚠️ 行情故障: {d['err_y']}")
            if d["err_f"]: st.warning(f"⚠️ 籌碼故障: {d['err_f']}")

            # KD 彈出視窗
            with col_kd:
                if d["hist"] is not None:
                    with st.popover("📈 查看 KD 趨勢"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K值'))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D值'))
                        fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0))
                        st.plotly_chart(fig, use_container_width=True)

            # 四大指標列
            if d["market"]:
                m = d["market"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現價/漲幅", f"{m['price']}", f"{m['change']:.2f}%")
                c2.metric("量比", f"{m['v_ratio']:.2f}")
                c3.metric("換手率", f"{m['turnover']:.2f}%")
                c4.metric("流通市值", f"{m['mkt_cap']:.1f} 億")
            
            # 籌碼資訊
            if d["chips"]:
                c = d["chips"]; t_col = "red" if c['total'] > 0 else "green"
                st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px;'>🗓️ {c['date']} | 法人合計: <span style='color:{t_col}; font-weight:bold;'>{c['total']}張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{row['名稱']} ({sid}.TW)")
            st.caption("尚未同步，請點擊左側按鈕。")
