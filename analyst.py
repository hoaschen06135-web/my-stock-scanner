# --- 3. 引擎 B：證交所 OpenAPI (修復 SSL 憑證報錯版) ---
@st.cache_data(ttl=3600)
def fetch_twse_data():
    """直連證交所 JSON API (修復 SSL 憑證報錯版)"""
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBYK_ALL"
        
        # 使用 requests 抓取，並加入 verify=False 跳過 SSL 檢查
        # 同時使用 urllib3 停用不安全連線的警告訊息
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        res = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        
        if res.status_code == 200:
            return pd.DataFrame(res.json()).set_index('Code')
        else:
            st.warning(f"證交所 API 回傳錯誤碼: {res.status_code}")
            return pd.DataFrame()
            
    except Exception as e:
        # 針對截圖中的報錯進行捕捉，避免整台程式當掉
        st.warning(f"⚠️ 證交所 API 暫時連線異常 (已跳過): {e}")
        return pd.DataFrame()
