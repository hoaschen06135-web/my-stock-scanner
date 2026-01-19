# --- 修正後的同步邏輯 ---
if st.button("➕ 將選中股票同步至 Google Sheets"):
    # 僅取出需要的兩欄資料
    to_add = edit_df[edit_df["選取"] == True][["股票代號", "名稱"]]
    
    if not to_add.empty:
        with st.spinner("同步中..."):
            # 1. 讀取現有資料
            existing = conn.read()
            
            # 2. 如果現有資料是空的，直接給予正確欄位
            if existing is None or existing.empty:
                updated = to_add
            else:
                # 3. 確保 existing 只保留我們需要的欄位，移除像 ticker_item 這種多餘欄位
                # 只保留與 to_add 相同的欄位名稱
                existing = existing[["股票代號", "名稱"]] if "股票代號" in existing.columns else pd.DataFrame(columns=["股票代號", "名稱"])
                
                # 4. 合併並去重
                updated = pd.concat([existing, to_add]).drop_duplicates(subset=["股票代號"])
            
            # 5. 強制寫回，覆蓋原本錯誤的結構
            conn.update(data=updated)
        st.success("✅ 欄位已修正並同步成功！")
