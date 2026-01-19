# --- 修正後的法人籌碼顯示區域 ---
    with c2:
        try:
            # 抓取最近 10 天數據
            start_c = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            inst_df = dl.taiwan_stock_institutional_investors(stock_id=pure_id, start_date=start_c)
            
            if inst_df is not None and not inst_df.empty:
                latest_date = inst_df['date'].max()
                today_data = inst_df[inst_df['date'] == latest_date]
                
                chips_list = []
                # 改用「關鍵字比對」，增加相容性
                mapping = {
                    "外資": ["外資", "陸資"],
                    "投信": ["投信"],
                    "自營": ["自營"]
                }
                
                total_net = 0 # 用於計算合計
                
                for label, keywords in mapping.items():
                    # 只要名稱包含關鍵字就抓取
                    r = today_data[today_data['name'].str.contains('|'.join(keywords), na=False)]
                    if not r.empty:
                        # 買進 - 賣出 = 買賣超 (換算張數)
                        net_shares = r['buy'].sum() - r['sell'].sum()
                        net_lots = int(net_shares // 1000)
                        total_net += net_lots
                        
                        color = "red" if net_lots > 0 else "green" if net_lots < 0 else "gray"
                        chips_list.append(f"{label}: <span style='color:{color}'>{net_lots}張</span>")
                
                # 加入「合計」讓畫面更豐富
                total_color = "red" if total_net > 0 else "green" if total_net < 0 else "gray"
                st.markdown(f"🗓️ {latest_date} | 合計: <span style='color:{total_color}'>{total_net}張</span>", unsafe_allow_html=True)
                st.markdown(f"<small>{' | '.join(chips_list)}</small>", unsafe_allow_html=True)
            else:
                st.caption("尚未公布最新法人數據")
        except Exception as e:
            st.caption("數據解析中...")
