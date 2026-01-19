import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go # 繪製 KD 線專用

# --- 1. KD 數據計算函數 ---
def calculate_kd(df, period=9):
    """計算台股常用的 K(9,3) 與 D(9,3)"""
    # 計算 RSV (未成熟隨機值)
    low_min = df['Low'].rolling(window=period).min()
    high_max = df['High'].rolling(window=period).max()
    rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50) # 初始值填充
    
    k_list, d_list = [50.0], [50.0]
    for i in range(1, len(rsv)):
        # K = 前日 K * (2/3) + RSV * (1/3)
        # D = 前日 D * (2/3) + 今日 K * (1/3)
        current_k = k_list[-1] * (2/3) + rsv.iloc[i] * (1/3)
        current_d = d_list[-1] * (2/3) + current_k * (1/3)
        k_list.append(current_k)
        d_list.append(current_d)
        
    df['K'] = k_list
    df['D'] = d_list
    return df

# --- 2. KD 線彈窗對話框 (st.dialog) ---
@st.dialog("個股 KD 指標即時分析")
def show_kd_window(ticker_with_name):
    code = ticker_with_name.split(',')[0]
    name = ticker_with_name.split(',')[1]
    
    st.write(f"### 📍 {name} ({code})")
    
    with st.spinner("正在抓取歷史數據..."):
        # 抓取一個月數據以顯示 KD 趨勢
        df = yf.download(code, period="1mo", interval="1d", progress=False)
        if not df.empty and len(df) > 9:
            df = calculate_kd(df)
            current_k = round(df['K'].iloc[-1], 2)
            current_d = round(df['D'].iloc[-1], 2)
            
            # 顯示當前數值
            col_k, col_d = st.columns(2)
            col_k.metric("當前 K 值", f"{current_k}")
            col_d.metric("當前 D 值", f"{current_d}")
            
            # 繪製 Plotly 圖表
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.index, y=df['K'], name='K線', line=dict(color='blue')))
            fig.add_trace(go.Scatter(x=df.index, y=df['D'], name='D線', line=dict(color='orange')))
            
            # 設定數值範圍 0-100 並加入超買(80)/超賣(20)參考線
            fig.update_layout(
                yaxis=dict(range=[0, 100], title="KD 數值範圍"),
                height=400,
                margin=dict(l=20, r=20, t=20, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="超買區")
            fig.add_hline(y=20, line_dash="dash", line_color="green", annotation_text="超賣區")
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("無法取得該股票數據。")
            
    if st.button("關閉視窗"):
        st.rerun()

# --- 3. 修改「我的關注清單」顯示頁面 ---
# (此部分請替換原本 stock_scanner.py 中的關注清單迴圈)
if page == "我的關注清單":
    st.header("⭐ 我的關注清單 (KD 分析版)")
    
    if not st.session_state['watchlist']:
        st.info("目前尚無關注股票。")
    else:
        # 表頭
        st.markdown("---")
        h1, h2, h3, h4, h5 = st.columns([1.5, 1, 1, 1, 1.5])
        h1.write("**股票名稱/代碼**")
        h2.write("**最新漲幅**")
        h3.write("**量比**")
        h4.write("**換手率**")
        h5.write("**KD 分析**")
        
        # 逐一顯示關注股票
        for item in st.session_state['watchlist']:
            code = item.split(',')[0]
            name = item.split(',')[1]
            
            # 抓取單一股票即時數據 (模式設為 full 以取得詳細資料)
            df_single = fetch_stock_data([item], mode="full")
            
            if not df_single.empty:
                r = df_single.iloc[0]
                c1, c2, c3, c4, c5 = st.columns([1.5, 1, 1, 1, 1.5])
                
                c1.write(f"**{name}** ({code})")
                # 漲幅顏色判定
                change_color = "red" if r['漲幅'] > 0 else "green"
                c2.markdown(f"<span style='color:{change_color}'>{r['漲幅']}%</span>", unsafe_allow_html=True)
                c3.write(f"{r['量比']}")
                c4.write(f"{r['換手率']}")
                
                # KD 線顯示按鈕
                if c5.button(f"📈 顯示 KD 線", key=f"kd_{code}"):
                    show_kd_window(item)
        
        st.markdown("---")
        if st.button("🔄 全部即時更新"):
            st.rerun()