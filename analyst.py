import streamlit as st
import pandas as pd
import yfinance as yf
from streamlit_gsheets import GSheetsConnection
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go

# --- 1. 初始化環境與記憶體 ---
# 強制設定寬版面模式，避免排版擠壓
st.set_page_config(layout="wide", page_title="旗艦數據分析站-穩定修復版")
conn = st.connection("gsheets", type=GSheetsConnection)
TOKEN = st.secrets["FINMIND_TOKEN"]

if 'stock_memory' not in st.session_state:
    st.session_state.stock_memory = {}

# --- 2. KDJ 指標計算邏輯 (純數學計算，穩定) ---
def calculate_kdj(df, n=9, m1=3, m2=3):
    df['Low_N'] = df['Low'].rolling(window=n).min()
    df['High_N'] = df['High'].rolling(window=n).max()
    rsv = (df['Close'] - df['Low_N']) / (df['High_N'] - df['Low_N']) * 100
    df['K'] = rsv.ewm(com=m1-1).mean()
    df['D'] = df['K'].ewm(com=m2-1).mean()
    # 避免除零錯誤後的清理
    df.dropna(inplace=True)
    return df

# --- 3. 數據更新核心 ---
def sync_all_data(watchlist):
    dl = DataLoader()
    # 嘗試登入，若失敗則跳過 (兼容性保護)
    try:
        if hasattr(dl, 'login'): dl.login(token=TOKEN)
    except: pass

    for _, row in watchlist.iterrows():
        sid = str(row['股票代號']).split('.')[0].strip()
        sid_tw = f"{sid}.TW"
        sname = row['名稱']
        try:
            # A. Yahoo 行情與 KD 計算
            tk = yf.Ticker(sid_tw)
            hist = tk.history(period='3mo')
            info = tk.info
            shares = info.get('sharesOutstanding', 0)
            
            if not hist.empty and len(hist) > 10: # 確保資料足夠計算 KD
                hist_kd = calculate_kdj(hist.copy())
                last_p = round(hist['Close'].iloc[-1], 2)
                prev_p = hist['Close'].iloc[-2]
                chg = ((last_p - prev_p) / prev_p) * 100
                
                # 量比計算 (防止除零)
                avg_vol = hist['Volume'].iloc[-6:-1].mean()
                v_ratio = hist['Volume'].iloc[-1] / avg_vol if avg_vol > 0 else 0
                
                # 換手率與市值
                turnover = (hist['Volume'].iloc[-1] / shares) * 100 if shares > 0 else 0
                mkt_cap = (last_p * shares) / 100000000

                # B. FinMind 籌碼
                time.sleep(0.3) # 輕微延遲
                chips = dl.taiwan_stock_institutional_investors(
                    stock_id=sid, start_date=(datetime.now()-timedelta(10)).strftime('%Y-%m-%d')
                )
                chip_res = {"date": "-", "total": 0, "details": "無籌碼數據"}
                if chips is not None and not chips.empty:
                    last_d = chips['date'].max()
                    td = chips[chips['date'] == last_d]
                    mapping = {"外資": ["Foreign_Investor"], "投信": ["Investment_Trust"], "自營": ["Dealer_self"]}
                    n_total = 0
                    det = []
                    for label, kw in mapping.items():
                        r = td[td['name'].isin(kw)]
                        if not r.empty:
                            n = int((pd.to_numeric(r['buy']).sum() - pd.to_numeric(r['sell']).sum()) // 1000)
                            n_total += n
                            det.append(f"{label}: {n}")
                    chip_res = {"date": last_d, "total": n_total, "details": " | ".join(det)}

                st.session_state.stock_memory[sid] = {
                    "name": sname, "price": last_p, "change": chg, "v_ratio": v_ratio,
                    "turnover": turnover, "mkt_cap": mkt_cap, "chips": chip_res, "hist": hist_kd
                }
        except Exception as e:
            print(f"Error syncing {sid}: {e}") # 在後台印出錯誤以便除錯
            continue

# --- 4. 側邊欄：控制面板 (含穩定寫入功能) ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    
    # 功能一：新增股票到 Sheets (增加錯誤捕捉)
    with st.expander("➕ 新增單一股票"):
        with st.form("add_stock_form"):
            new_sid = st.text_input("股票代號 (如 2330)")
            new_sname = st.text_input("股票名稱 (如 台積電)")
            submitted = st.form_submit_button("確認新增")
            
            if submitted:
                if new_sid and new_sname:
                    try:
                        st.info("正在寫入 Google Sheets...")
                        # 1. 讀取現有資料並標準化欄位
                        raw_data = conn.read()
                        if raw_data is None or raw_data.empty:
                             current_data = pd.DataFrame(columns=["股票代號", "名稱"])
                        else:
                             current_data = raw_data.iloc[:, :2].dropna(how='all')
                             current_data.columns = ["股票代號", "名稱"]

                        # 2. 建立新資料列
                        new_row = pd.DataFrame([[new_sid, new_sname]], columns=["股票代號", "名稱"])
                        # 3. 合併
                        updated_df = pd.concat([current_data, new_row], ignore_index=True)
                        # 4. 寫回 (最容易報錯的地方)
                        conn.update(data=updated_df)
                        
                        st.success(f"成功加入 {new_sname}！頁面將自動刷新。")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        err_msg = str(e)
                        if "403" in err_msg or "permission" in err_msg.lower():
                            st.error("❌ 寫入失敗：權限不足。請確認您的 Google Service Account 擁有試算表的「編輯」權限。")
                        else:
                            st.error(f"❌ 寫入時發生未知錯誤: {err_msg}")
                else:
                    st.warning("請填寫完整的代號與名稱。")

    # 讀取清單 (用於主畫面顯示)
    try:
        raw = conn.read().dropna(how='all')
        watchlist = raw.iloc[:, :2].copy()
        watchlist.columns = ["股票代號", "名稱"]
    except:
        st.error("無法讀取 Google Sheets，請檢查連線設定。")
        st.stop()

    if st.button("🚀 一鍵同步所有數據", use_container_width=True):
        with st.spinner("數據同步中，請稍候..."):
            sync_all_data(watchlist)
            st.rerun()

    if st.button("🧹 清除數據快取", use_container_width=True):
        st.session_state.stock_memory = {}
        st.rerun()

# --- 5. 主畫面呈現 ---
st.title("🚀 專業關注清單監控")

if watchlist.empty:
    st.info("清單為空，請從左側新增股票。")

for _, row in watchlist.iterrows():
    sid = str(row['股票代號']).split('.')[0].strip()
    sname = row.get('名稱', sid) # 防止名稱欄位缺失
    
    with st.container(border=True):
        col_title, col_kd = st.columns([7, 3])
        
        if sid in st.session_state.stock_memory:
            d = st.session_state.stock_memory[sid]
            with col_title:
                st.subheader(f"{d['name']} ({sid}.TW)")
            
            with col_kd:
                # 使用 try-except 包裹 popover，防止舊版 Streamlit 報錯
                try:
                    with st.popover("📈 查看 KD 趨勢"):
                        st.markdown(f"**{d['name']} 近三個月 KDJ**")
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['K'], name='K線 (快)', line=dict(color='blue', width=1.5)))
                        fig.add_trace(go.Scatter(x=d['hist'].index, y=d['hist']['D'], name='D線 (慢)', line=dict(color='orange', width=1.5)))
                        fig.update_layout(
                            height=300, 
                            margin=dict(l=10, r=10, t=30, b=10),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                except AttributeError:
                    st.warning("您的 Streamlit 版本過舊，不支援浮動視窗。")

            # 四大指標
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現價/漲幅", f"{d['price']}", f"{d['change']:.2f}%")
            c2.metric("量比", f"{d['v_ratio']:.2f}")
            c3.metric("換手率", f"{d['turnover']:.2f}%")
            c4.metric("流通市值", f"{d['mkt_cap']:.1f} 億")
            
            # 籌碼資訊
            c = d['chips']
            t_color = "red" if c['total'] > 0 else "green"
            st.markdown(f"<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; margin-top:5px;'>🗓️ {c['date']} | 三大法人合計: <span style='color:{t_color}; font-weight:bold;'>{c['total']} 張</span><br><small>{c['details']}</small></div>", unsafe_allow_html=True)
        else:
            st.subheader(f"{sname} ({sid}.TW)")
            st.caption("尚未同步數據，請點擊左側更新按鈕。")
