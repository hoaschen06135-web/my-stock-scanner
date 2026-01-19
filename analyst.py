import streamlit as st
import pandas as pd
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time

# --- 1. 初始化 ---
st.set_page_config(layout="wide", page_title="行動分析站-穩定模式")
TOKEN = st.secrets["FINMIND_TOKEN"]

# --- 2. 安全抓取邏輯 (增加延遲與錯誤攔截) ---
def safe_fetch(dl, sid, dataset, start_date):
    """
    針對「未驗證帳號」優化的抓取邏輯
    """
    try:
        # 增加延遲，避免瞬間敲門太快被封鎖
        time.sleep(1.5) 
        if dataset == "Daily":
            res = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
        elif dataset == "Inst":
            res = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=start_date)
        elif dataset == "Poll":
            res = dl.taiwan_stock_shares_poll(stock_id=sid, start_date=start_date)
        
        # 解決 KeyError: 'data'，確保有資料才回傳
        if res is not None and isinstance(res, pd.DataFrame) and not res.empty:
            return res
    except Exception:
        return pd.DataFrame() # 失敗就回傳空表格，不讓程式崩潰
    return pd.DataFrame()

# --- 3. 換手率計算公式 ---
# $$Turnover\ Rate = \frac{Trading\ Volume}{Total\ Shares} \times 100\%$$

# --- 4. 顯示邏輯 ---
st.title("🚀 專業關注清單 (限流保護中)")
st.info("提示：由於帳號尚未驗證，目前每支股票數據加載約需 3-5 秒，請耐心等候。")

# ... (其餘 UI 顯示邏輯保持不變)
