import re
with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'r', encoding='utf-8') as f:
    code = f.read()

old_func = r'''def calc_health_score_and_advice\(s: dict\) -> dict:.*?return\s*\{.*?\"score\":\s*score,.*?\"light\":\s*light,.*?\"advice\":\s*advice.*?\}'''

new_func = r'''def calc_health_score_and_advice(s: dict) -> dict:
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

code = re.sub(old_func, new_func, code, flags=re.DOTALL)

with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'w', encoding='utf-8') as f:
    f.write(code)
