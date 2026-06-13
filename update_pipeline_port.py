import re
with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'r', encoding='utf8') as f:
    code = f.read()

# Update portfolio dict
old_port = r'''        portfolio_result\.append\(\{\n\s*\"code\":\s*code,\n\s*\"name\":\s*name,\n\s*\"is_etf\":\s*is_etf.*?\"alert\":\s*alert,\n\s*\}\)'''
new_port = r'''        shares   = p.get("shares")
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
        }
        port_item.update(calc_health_score_and_advice(port_item))
        portfolio_result.append(port_item)'''
code = re.sub(old_port, new_port, code, flags=re.DOTALL)

with open('c:\\vibe coding\\國家寶藏\\pipeline.py', 'w', encoding='utf8') as f:
    f.write(code)
