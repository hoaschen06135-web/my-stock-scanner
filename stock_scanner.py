import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import math
import time # 新增：用於控制請求頻率
import urllib3
from io import StringIO
from streamlit_gsheets import GSheetsConnection

# 基礎環境設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="台股雲端精確篩選系統")

# ... (Google Sheets 連線與 Ticker 抓取函數保持不變) ...

def fetch_stock_data(tickers_with_names, low_chg, high_chg, low_vol, high_vol, low_turn, high_turn):
    """加入防封鎖與頻率控制的抓取邏輯"""
    if not tickers_with_names: return pd.DataFrame()
    
    mapping = {t.split(',')[0]: t.split(',')[1] for t in tickers_with_names}
    
    # 增加延遲，避免 Yahoo 偵測為攻擊
    time.sleep(1.5) 
    
    try:
        # 使用 Session 優化請求
        data = yf.download(
            list(mapping.keys()), 
            period="6d", 
            group_by='ticker', 
            progress=False,
            threads=False # 關閉多線程，速度稍慢但更安全
        )
    except Exception as e:
        st.error(f"Yahoo Finance 連線失敗：{e}")
        return pd.DataFrame()

    if data.empty:
        st.warning("Yahoo 目前沒有回傳任何數據，請稍候 30 秒再試。")
        return pd.DataFrame()
    
    results = []
    for t in mapping.keys():
        try:
            # 判斷回傳格式
            t_data = data[t] if len(mapping) > 1 else data
            if t_data.empty or len(t_data) < 2: continue
            if isinstance(t_data.columns, pd.MultiIndex): 
                t_data.columns = t_data.columns.get_level_values(0)
            
            c_now = t_data['Close'].iloc[-1]
            c_pre = t_data['Close'].iloc[-2]
            
            # 檢查數據是否有效
            if pd.isna(c_now) or pd.isna(c_pre): continue
            
            change = round(((c_now - c_pre) / c_pre) * 100, 2)
            vol_avg = t_data['Volume'].iloc[:-1].mean()
            vol_ratio = round(t_data['Volume'].iloc[-1] / vol_avg, 2) if vol_avg > 0 else 0
            
            # 使用快取機制抓取 Info，減少請求次數
            tk = yf.Ticker(t)
            info = tk.info
            shares = info.get('sharesOutstanding', 1)
            turnover = round((t_data['Volume'].iloc[-1] / shares) * 100, 2)
            mcap = f"{round(info.get('marketCap', 0) / 1e8, 2)} 億"

            # 條件過濾
            if not (low_chg <= change <= high_chg and 
                    low_vol <= vol_ratio <= high_vol and 
                    low_turn <= turnover <= high_turn):
                continue
                
            results.append({
                "選取": False, "股票代號": t, "名稱": mapping[t], 
                "漲幅": change, "量比": vol_ratio, 
                "換手率": turnover, "流通市值": mcap
            })
        except: continue
        
    return pd.DataFrame(results)

# ... (介面與按鈕邏輯保持不變) ...
