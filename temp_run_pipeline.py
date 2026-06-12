def run_pipeline() -> None:
# ============================================================
def run_pipeline() -> None:
    start_time = time.time()
    today_str  = datetime.date.today().strftime("%Y%m%d")
    now_iso    = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    logger.info(f"🚀 Pipeline 啟動 [{now_iso}]")

    twse_prices = fetch_twse_prices(today_str)
    if not twse_prices:
        logger.info("📅 今日為非交易日或 TWSE 尚未更新，跳過執行。")
        return

    tpex_prices = fetch_tpex_prices(today_str)
    all_prices  = {**twse_prices, **tpex_prices}

    portfolio_codes = {p["code"] for p in MY_PORTFOLIO}
    etf_codes       = {p["code"] for p in MY_PORTFOLIO if p["is_etf"]}

    logger.info("正在抓取三大法人與投信資料（近3日）...")
    recent_dates = get_recent_trading_dates(3)
    candidate_non_etf_codes = [
        code for code in list(twse_prices.keys())[:SCAN_LIMIT * 2]
        if code not in etf_codes
    ]
    inst_data = fetch_institutional(candidate_non_etf_codes, recent_dates)
    
    logger.info("正在抓取上市月營收資料...")
    revenue_data = fetch_monthly_revenue()
    
    logger.info("正在分析大盤位階...")
    market_phase = fetch_tw_market_phase()

    logger.info("開始市場掃描篩選...")
    scan_candidates: list[dict] = []

    sorted_inst = sorted(inst_data.items(), key=lambda x: x[1]["net_buy_3d"], reverse=True)[:SCAN_LIMIT]

    for code, inst_info in sorted_inst:
        net_buy = inst_info["net_buy_3d"]
        it_continuous_buy = inst_info["it_continuous_buy"]
        price = all_prices.get(code)
        if price is None: continue

        ma60, stop_loss = fetch_ma60(code)
        if ma60 is None or price <= ma60 or net_buy <= 0: continue
        
        revenue_info = revenue_data.get(code, {})

        scan_candidates.append({
            "code":            code,
            "price":           price,
            "ma60":            ma60,
            "inst_net_buy_3d": net_buy,
            "it_continuous_buy": it_continuous_buy,
            "revenue_double_growth": revenue_info.get("revenue_double_growth", False),
            "stop_loss":       stop_loss,
        })

    scanned_total  = len(sorted_inst)
    passed_filter  = len(scan_candidates)
    alert_count   = 0
    market_result: list[dict] = []

    for s in scan_candidates:
        code  = s["code"]
        name  = code
        price = s["price"]
        ma60  = s["ma60"]
        net   = s["inst_net_buy_3d"]

        news_today, news_yday = fetch_news(code, name)
        ptt_push, ptt_boo     = fetch_ptt(code, name)
        keywords_hit          = match_keywords(code, name)
        alert                 = calc_alert(news_today, news_yday, ptt_push, ptt_boo, net)

        if alert: alert_count += 1
        kw_score = sum(k["weight"] for k in keywords_hit)
        score    = net + kw_score * 100

        market_result.append({
            "code":               code,
            "name":               name,
            "price":              price,
            "ma60":               ma60,
            "suggested_stop_loss": s["stop_loss"],
            "inst_net_buy_3d":    net,
            "it_continuous_buy":  s["it_continuous_buy"],
            "revenue_double_growth": s["revenue_double_growth"],
            "news_heat_today":    news_today,
            "news_heat_yesterday": news_yday,
            "ptt_push":           ptt_push,
            "ptt_boo":            ptt_boo,
            "keywords_hit":       keywords_hit,
            "alert":              alert,
            "_score":             score,
        })

    market_result.sort(key=lambda x: x["_score"], reverse=True)
    for r in market_result: r.pop("_score", None)

    portfolio_result: list[dict] = []
    for p in MY_PORTFOLIO:
        code     = p["code"]
        name     = p["name"]
        is_etf   = p["is_etf"]
        cost     = p.get("cost_price")
        price    = all_prices.get(code)

        if price is None: continue

        ma60, stop_loss = fetch_ma60(code)
        news_today, news_yday = fetch_news(code, name)
        ptt_push, ptt_boo     = fetch_ptt(code, name)
        keywords_hit          = match_keywords(code, name)

        inst_net = None
        it_continuous_buy = False
        if not is_etf:
            inst_res = fetch_institutional([code], recent_dates)
            inst_info = inst_res.get(code, {"net_buy_3d": 0, "it_continuous_buy": False})
            inst_net = inst_info["net_buy_3d"]
            it_continuous_buy = inst_info["it_continuous_buy"]

        alert = calc_alert(news_today, news_yday, ptt_push, ptt_boo, inst_net)
        if alert: alert_count += 1

        pnl_pct = None
        if cost is not None and price is not None:
            pnl_pct = round((price - cost) / cost * 100, 2)
            
        rev_info = revenue_data.get(code, {})

        portfolio_result.append({
            "code":               code,
            "name":               name,
            "is_etf":             is_etf,
            "cost_price":         cost,
            "price":              price,
            "ma60":               ma60,
            "suggested_stop_loss": stop_loss,
            "pnl_percent":        pnl_pct,
            "news_heat_today":    news_today,
            "news_heat_yesterday": news_yday,
            "ptt_push":           ptt_push,
            "ptt_boo":            ptt_boo,
            "keywords_hit":       keywords_hit,
            "it_continuous_buy":  it_continuous_buy,
            "revenue_double_growth": rev_info.get("revenue_double_growth", False),
            "alert":              alert,
        })

    output_path  = "dashboard_data.json"
    backup_path  = "dashboard_data_backup.json"
    if os.path.exists(output_path):
        try:
            import shutil
            shutil.copy2(output_path, backup_path)
        except Exception: pass

    elapsed = round(time.time() - start_time, 1)
    output  = {
        "updated_at":  now_iso,
        "run_summary": {
            "scanned_total":   scanned_total,
            "passed_filter":   passed_filter,
            "alert_count":     alert_count,
            "elapsed_seconds": elapsed,
        },
        "market_weather": market_phase,
        "portfolio":      portfolio_result,
        "market_scanned": market_result,
    }

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"JSON 寫出失敗：{e}")

    us_market = fetch_us_market()
    send_daily_summary(portfolio_result, market_result, us_market, market_phase, now_iso)
# ============================================================
# 【營收年月雙增】fetch_monthly_revenue
# ============================================================
def fetch_monthly_revenue() -> dict[str, dict]:
    """
    從 TWSE OpenAPI 抓取上市營收。
    回傳: { code: {"mom": 5.2, "yoy": 10.5, "revenue_double_growth": True} }
    """
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    resp = fetch_with_retry(url)
    if not resp: return {}
    try:
        data = resp.json()
        results = {}
        for row in data:
            code = row.get("公司代號", "")
            try:
                mom = float(row.get("上月比較增減(%)", "0"))
                yoy = float(row.get("去年同月增減(%)", "0"))
                results[code] = {
                    "mom": mom,
                    "yoy": yoy,
                    "revenue_double_growth": (mom > 0 and yoy > 0)
                }
            except ValueError:
                continue
        logger.info(f"✅ 取得營收資料: {len(results)} 檔")
        return results
    except Exception as e:
        logger.warning(f"fetch_monthly_revenue 失敗: {e}")
        return {}

# ============================================================
# 【大盤位階判斷】fetch_tw_market_phase
# ============================================================
def fetch_tw_market_phase() -> dict | None:
    """
    抓取台股加權指數 (^TWII) 計算大盤位階 (20MA)。
    回傳 {"close": 20000, "ma20": 19500, "weather": "🌞 晴天"}
    """
    try:
        hist = yf.Ticker("^TWII").history(period="30d")
        time.sleep(0.2)
        if hist.empty or len(hist) < 20:
            return None
        closes = hist["Close"].values
        last_close = float(closes[-1])
        ma20 = float(sum(closes[-20:]) / 20)
        weather = "🌞 晴天" if last_close >= ma20 else "🌧️ 雨天"
        return {"close": round(last_close, 2), "ma20": round(ma20, 2), "weather": weather}
    except Exception as e:
        logger.warning(f"fetch_tw_market_phase 失敗: {e}")
        return None

# ============================================================
# 【美股指數表現】fetch_us_market
# 使用 yfinance 抓取美股主要指數昨日收盤表現
# 包含：S&P500、NASDAQ、費城半導體指數（對台股科技股最相關）、台積電 ADR
# /* 收費風險警告：yfinance 為非官方套件，完全免費，但高頻請求可能暫時封IP */
# ============================================================
def fetch_us_market() -> dict:
    """
    透過 yfinance 抓取美股主要指數昨日收盤表現。
    回傳 {名稱: {"close": 收盤, "chg_pct": 漲跌%}} 字典。
    """
    indices = {
        "S&P 500":   "^GSPC",
        "NASDAQ":    "^IXIC",
        "費半指數":  "^SOX",
        "台積電ADR": "TSM",
    }
    results = {}
    for name, ticker_code in indices.items():
        try:
            hist = yf.Ticker(ticker_code).history(period="5d")
            time.sleep(0.2)
            if hist.empty or len(hist) < 2:
                results[name] = None
                continue
            closes   = hist["Close"].values
            prev_cls = float(closes[-2])
            last_cls = float(closes[-1])
            chg_pct  = round((last_cls - prev_cls) / prev_cls * 100, 2)
            results[name] = {
                "close":   round(last_cls, 2),
                "chg_pct": chg_pct,
            }
        except Exception as e:
            logger.warning(f"fetch_us_market [{ticker_code}]: {e}")
            results[name] = None

    return results


# ============================================================
# 【每日智能摘要推播】send_daily_summary
# 每次 pipeline 完成後，自動發送包含：
#   美股表現 / 庫存狀態 / 市場亮點 / 明日注意事項 / AI Prompt
# ============================================================
