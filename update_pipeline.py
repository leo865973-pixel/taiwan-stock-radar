import re
with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'r', encoding='utf8') as f:
    code = f.read()

# 1. Update fetch_ma60 to fetch_mas
old_fetch_ma = r'''def fetch_ma60.*?return ma60, stop_loss.*?except.*?return None, None'''
new_fetch_ma = r'''def fetch_mas(code: str) -> tuple[float | None, float | None]:
    """
    透過 FinMind API 獲取個股過去歷史資料，並計算 60 日均線與 20 日均線。
    回傳 (ma60, ma20)，若失敗回傳 (None, None)。
    """
    try:
        import datetime
        start_date = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
        
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={code}&start_date={start_date}"
        resp = fetch_with_retry(url)
        if not resp: return None, None
        
        data = resp.json()
        if data.get("msg") != "success":
            logger.warning(f"FinMind MAs [{code}] 錯誤: {data.get('msg')}")
            return None, None
            
        prices = [row["close"] for row in data.get("data", [])]
        
        if not prices or len(prices) < 10:
            logger.warning(f"FinMind {code} 歷史數據過少")
            return None, None
            
        closes_60 = prices[-60:]
        ma60 = float(round(sum(closes_60) / len(closes_60), 2))
        closes_20 = prices[-20:]
        ma20 = float(round(sum(closes_20) / len(closes_20), 2))
        
        return ma60, ma20
        
    except Exception as e:
        logger.warning(f"FinMind MAs 查詢失敗 [{code}]: {e}")
        return None, None'''
code = re.sub(old_fetch_ma, new_fetch_ma, code, flags=re.DOTALL)


# 2. Update calc_health_score_and_advice
old_score_func = r'''def calc_health_score_and_advice.*?score:\s*score,\n\s*\"light\":\s*light,\n\s*\"advice\":\s*advice\n\s*\}'''
new_score_func = r'''def calc_health_score_and_advice(s: dict) -> dict:
    """
    輸入個股資訊字典，產出給新手的體檢分數、紅綠燈與白話文解讀。
    支援短線防護 (ma20) 與成本停損 (cost_price)。
    """
    price = s.get("price")
    ma60 = s.get("ma60")
    ma20 = s.get("ma20")
    cost_price = s.get("cost_price")
    net_buy = s.get("inst_net_buy_3d") or 0
    it_buy = s.get("it_continuous_buy")
    rev_growth = s.get("revenue_double_growth")
    
    score = 50 # 基礎分
    
    # 動態停損判斷
    is_cost_stop_loss = False
    if cost_price and price and price < cost_price * 0.9:
        is_cost_stop_loss = True
        
    # 1. 技術面
    tech_status = ""
    if price and ma60:
        if is_cost_stop_loss:
            score -= 50
            tech_status = f"股價已跌破你的成本價 10% ({cost_price} -> {price})，觸發強制停損底線！"
        elif price < ma60 * 0.97:
            score -= 20
            tech_status = "股價明顯跌破季線，長線趨勢轉弱。"
        elif ma20 and price < ma20:
            score -= 10
            tech_status = "短線跌破月線轉弱，留意是否繼續向下測試季線。"
        elif price >= ma60 * 1.05:
            score += 20
            tech_status = "股價穩站季線之上，趨勢強勢。"
        else:
            score += 10
            tech_status = "股價維持在季線之上，長線算安全。"
            
    # 2. 籌碼面
    chip_status = ""
    if it_buy:
        score += 15
        chip_status = "有投信大哥在默默連買吃貨，背後有靠山。"
    elif net_buy > 2000:
        score += 10
        chip_status = "三大法人近期有明顯的大量買單。"
    elif net_buy < -2000:
        score -= 10
        chip_status = "近期法人在倒貨，要小心賣壓。"
        
    # 3. 基本面
    fund_status = ""
    if rev_growth:
        score += 15
        fund_status = "公司這個月賺得比上個月、去年都多，業績有支撐。"
        
    # 分數範圍 0-100
    score = max(0, min(100, score))
    
    # 紅綠燈與總結
    if score >= 75:
        light = "🟢 偏多觀察"
        advice = f"【體檢優良】{tech_status}{chip_status}{fund_status} 整體看來是好學生，可加入自選股觀察找買點。"
    elif score >= 50:
        light = "🟡 中立觀望"
        advice = f"【表現平平】{tech_status}{chip_status}{fund_status} 目前沒有特別突出的表現，建議多看少做。"
    else:
        light = "🔴 破線警報"
        advice = f"【危險警告】{tech_status}{chip_status} 請嚴格執行停損，切勿隨意凹單或攤平。"
        if is_cost_stop_loss:
            advice = f"【🚨 強制停損】{tech_status} 資金控管是活下去的唯一原則，請立刻評估出場以保護本金！"
            
    return {
        "score": score,
        "light": light,
        "advice": advice
    }'''
code = re.sub(old_score_func, new_score_func, code, flags=re.DOTALL)


# 3. run_pipeline logic:
# For scan logic:
code = re.sub(
    r'ma60, stop_loss = fetch_ma60\(code\)\n\s*if ma60 is None or price <= ma60 or net_buy <= 0: continue',
    r'ma_result = fetch_mas(code)\n        if ma_result == (None, None): continue\n        ma60, ma20 = ma_result\n        if ma60 is None or price <= ma60 or net_buy <= 0: continue\n        stop_loss = round(ma60 * 0.97, 2)',
    code
)

code = re.sub(
    r'"ma60":\s*ma60,',
    r'"ma60":               ma60,\n            "ma20":               ma20,',
    code, count=1  # Only first occurrence which is in scan loop dict creation
)

# For portfolio logic:
code = re.sub(
    r'ma60, stop_loss = fetch_ma60\(code\)',
    r'ma_result = fetch_mas(code)\n        if ma_result == (None, None): continue\n        ma60, ma20 = ma_result',
    code
)

old_port = r'''port_item = \{\n\s*\"code\":\s*code,\n\s*\"name\":\s*name.*?\"alert\":\s*alert,\n\s*\}'''
new_port = r'''shares   = p.get("shares")
        pnl_value = None
        if cost is not None and price is not None and shares:
            pnl_value = round((price - cost) * shares)
            
        dynamic_stop_loss = round(max(cost * 0.9, ma60 * 0.97), 2) if cost else round(ma60 * 0.97, 2)
        stop_loss = dynamic_stop_loss

        port_item = {
            "code":               code,
            "name":               name,
            "is_etf":             is_etf,
            "cost_price":         cost,
            "shares":             shares,
            "price":              price,
            "ma60":               ma60,
            "ma20":               ma20,
            "suggested_stop_loss": dynamic_stop_loss,
            "pnl_percent":        pnl_pct,
            "pnl_value":          pnl_value,
            "news_heat_today":    news_today,
            "news_heat_yesterday": news_yday,
            "ptt_push":           ptt_push,
            "ptt_boo":            ptt_boo,
            "keywords_hit":       keywords_hit,
            "inst_net_buy_3d":    inst_net,
            "it_continuous_buy":  it_continuous_buy,
            "revenue_double_growth": rev_info.get("revenue_double_growth", False),
            "alert":              alert,
        }'''
code = re.sub(old_port, new_port, code, flags=re.DOTALL)


with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'w', encoding='utf8') as f:
    f.write(code)
