def send_daily_summary(
    portfolio_result: list,
    market_result:    list,
    us_market:        dict,
    now_iso:          str,
) -> None:
    """組合並發送每日 Telegram 智能摘要報告。"""
    today_str = now_iso[:10]
    lines: list[str] = []

    lines.append(f"📊 <b>台股輿情雷達 每日報告</b>")
    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"📅 {today_str} 收盤後分析")
    lines.append("")

    # ── 美股表現 ──
    lines.append("🇺🇸 <b>【美股昨夜表現】</b>")
    sp500_chg = None
    sox_chg   = None
    for name, data in us_market.items():
        if data is None:
            lines.append(f"  ❓ {name}：無法取得")
            continue
        chg  = data["chg_pct"]
        icon = "📈" if chg >= 0 else "📉"
        sign = "+" if chg >= 0 else ""
        lines.append(f"  {icon} {name}：{sign}{chg}%")
        if name == "S&P 500":  sp500_chg = chg
        if name == "費半指數": sox_chg   = chg

    # 台股影響研判
    if sp500_chg is not None and sox_chg is not None:
        if sp500_chg >= 1.0 and sox_chg >= 1.0:
            lines.append("  ✅ 美股強勁，明日台股科技股偏多開")
        elif sp500_chg <= -1.5 or sox_chg <= -2.0:
            lines.append("  ⚠️ 美股顯著回落，明日台股注意開盤賣壓")
        elif sp500_chg <= -0.5 or sox_chg <= -1.0:
            lines.append("  ➡️ 美股小跌，台股開盤可能偏弱，觀望為主")
        else:
            lines.append("  ➡️ 美股平盤震盪，台股自行表態")
    lines.append("")

    # ── 我的庫存狀態 ──
    if portfolio_result:
        lines.append("📂 <b>【我的庫存狀態】</b>")
        for s in portfolio_result:
            price     = s.get("price") or 0
            ma60      = s.get("ma60") or 0
            stop_loss = s.get("suggested_stop_loss") or 0
            pnl       = s.get("pnl_percent")

            if stop_loss and price < stop_loss:
                status = "🚨 跌破停損，強烈建議評估出場"
            elif ma60 and price < ma60:
                status = "⚠️ 跌破均線，轉弱留意"
            else:
                status = "✅ 均線之上，持續觀察"

            pnl_str = f"{'+' if pnl and pnl >= 0 else ''}{pnl}%" if pnl is not None else "未設成本"
            bias    = round((price - ma60) / ma60 * 100, 1) if ma60 else 0
            bias_str = f"{'+' if bias >= 0 else ''}{bias}%"

            lines.append(f"  📌 <b>{s['code']} {s['name']}</b>")
            lines.append(f"     股價 {price} | MA60 {ma60} | 乖離 {bias_str}")
            lines.append(f"     損益 {pnl_str} | {status}")
        lines.append("")

    # ── 市場掃描亮點 ──
    alert_map = {
        "fomo_warning":     "🔥 FOMO",
        "golden_divergence": "⚡ 黃金背離",
        "news_surge":       "📰 新聞暴增",
    }
    alerts = [s for s in market_result if s.get("alert")]
    if alerts:
        lines.append("⚡ <b>【今日警報標的】</b>")
        for s in alerts[:5]:
            a_str = alert_map.get(s.get("alert", ""), "")
            lines.append(f"  {a_str} {s['code']} {s['name']} 股價 {s.get('price')}")
        lines.append("")

    top5 = market_result[:5]
    if top5:
        lines.append("📡 <b>【法人買超前5名】</b>")
        for i, s in enumerate(top5, 1):
            net  = s.get("inst_net_buy_3d") or 0
            sign = "+" if net >= 0 else ""
            lines.append(f"  #{i} {s['code']} {s['name']} | {sign}{net:,}張")
        lines.append("")

    # ── 明日開盤注意事項 ──
    lines.append("🔔 <b>【明日開盤注意事項】</b>")
    has_note = False

    fomo_stocks   = [s for s in market_result if s.get("alert") == "fomo_warning"]
    golden_stocks = [s for s in market_result if s.get("alert") == "golden_divergence"]
    weak_port     = [
        s for s in portfolio_result
        if s.get("ma60") and s.get("price") and s["price"] < s["ma60"]
    ]
    stoploss_port = [
