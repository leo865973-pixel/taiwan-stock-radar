import os
import json
import time
import logging
import datetime
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
import pandas as pd
import yfinance as yf

# ============================================================
# 日誌設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 【1-A】自選庫存設定
# ✅ 優先讀取 portfolio.json（可從網頁儀表板管理）
# 若 portfolio.json 不存在，才使用下方預設清單。
# cost_price 選填，未填寫設為 None。
# ============================================================
_DEFAULT_PORTFOLIO = [
    {"code": "0050",  "name": "元大台灣50",        "is_etf": True,  "cost_price": 150.0},
    {"code": "2330",  "name": "台積電",             "is_etf": False, "cost_price": 850.0},
    {"code": "00878", "name": "國泰永續高股息",      "is_etf": True,  "cost_price": 20.0},
]

def load_portfolio() -> list:
    """
    優先從 portfolio.json 讀取庫存設定。
    找不到檔案或解析失敗時，回傳預設清單。
    """
    portfolio_path = "portfolio.json"
    if os.path.exists(portfolio_path):
        try:
            with open(portfolio_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"✅ 從 portfolio.json 載入庫存，共 {len(data)} 檔")
            return data
        except Exception as e:
            logger.warning(f"portfolio.json 讀取失敗，使用預設清單：{e}")
    else:
        logger.info("portfolio.json 不存在，使用預設庫存清單")
    return _DEFAULT_PORTFOLIO

MY_PORTFOLIO = load_portfolio()

# ============================================================
# 產業關鍵字權重矩陣（1-H）
# ============================================================
KEYWORD_WEIGHTS = {
    "Vera Rubin": 5,
    "矽光子":     5,
    "GB200":      5,
    "CoWoS":      4,
    "全液冷":     4,
    "快接頭":     4,
    "AI伺服器":   4,
    "HBM":        3,
    "液冷":       3,
    "先進封裝":   3,
}

# ============================================================
# Telegram 憑證（透過環境變數讀取，嚴禁寫死）
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")

# ============================================================
# 掃描候選池上限
# ============================================================
SCAN_LIMIT = 80

# ============================================================
# Headers（模擬瀏覽器，避免被擋）
# ============================================================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ============================================================
# 【1-L】IP 退避重試機制
# ============================================================
def fetch_with_retry(url: str, max_retries: int = 3, **kwargs) -> requests.Response | None:
    """
    帶指數退避重試的 HTTP GET。
    若回傳 429 或 5xx，等待 2^retry 秒後重試，最多 3 次。
    三次均失敗後回傳 None（不 crash）。
    """
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, **kwargs)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                wait_sec = 2 ** (attempt + 1)
                logger.warning(
                    f"HTTP {resp.status_code} from {url}，"
                    f"第 {attempt+1} 次重試，等待 {wait_sec}s..."
                )
                time.sleep(wait_sec)
            else:
                logger.warning(f"非預期狀態碼 {resp.status_code} from {url}")
                return None
        except requests.RequestException as e:
            wait_sec = 2 ** (attempt + 1)
            logger.warning(
                f"請求例外 {e}（{url}），"
                f"第 {attempt+1} 次重試，等待 {wait_sec}s..."
            )
            time.sleep(wait_sec)

    logger.warning(f"⚠️ {url} 三次重試均失敗，跳過。")
    return None


# ============================================================
# 【1-C】上市收盤價（TWSE）
# ============================================================
def fetch_twse_prices(date_str: str) -> tuple[dict[str, float], dict[str, str]]:
    """
    抓取 TWSE MI_INDEX 全部上市股票收盤價與名稱。
    回傳 ({股票代號: 收盤價}, {股票代號: 公司名稱}) 的 tuple。
    若為非交易日，回傳 ({}, {})。
    """
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?response=json&type=ALLBUT0999&date={date_str}"
    )
    resp = fetch_with_retry(url)
    if resp is None:
        return {}, {}

    try:
        data = resp.json()
    except Exception:
        logger.warning("TWSE MI_INDEX JSON 解析失敗")
        return {}, {}

    # 非交易日 → stat 不為 "OK"
    if data.get("stat") != "OK":
        return {}, {}

    prices: dict[str, float] = {}
    names:  dict[str, str]   = {}
    for table in data.get("tables", []):
        fields = table.get("fields", [])
        # 找到含「收盤價」欄的表
        if "收盤價" not in fields:
            continue
        close_idx = fields.index("收盤價")
        code_idx  = fields.index("證券代號") if "證券代號" in fields else 0
        name_idx  = fields.index("證券名稱") if "證券名稱" in fields else None
        for row in table.get("data", []):
            try:
                code  = row[code_idx].strip()
                price_str = row[close_idx].replace(",", "").strip()
                prices[code] = float(price_str)
                if name_idx is not None:
                    names[code] = row[name_idx].strip()
            except (ValueError, IndexError):
                continue
    return prices, names


# ============================================================
# 【1-C】上櫃收盤價（TPEx）
# /* 收費風險警告：TPEx API 為公開免費端點，但結構可能隨時調整。*/
# ============================================================
def fetch_tpex_prices(date_str: str) -> dict[str, float]:
    """
    抓取 TPEx 上櫃股票收盤價。
    date_str 格式：YYYYMMDD → 轉換為 MM/DD/YYYY 送出。
    回傳 {股票代號: 收盤價} 字典。
    """
    # 轉換日期格式
    try:
        dt = datetime.datetime.strptime(date_str, "%Y%m%d")
        tpex_date = dt.strftime("%m/%d/%Y")
    except ValueError:
        return {}

    url = (
        "https://www.tpex.org.tw/web/stock/aftertrading/"
        "otc_quotes_no1430/stk_wn1430_result.php"
        f"?l=zh-tw&o=json&d={tpex_date}&se=EW"
    )
    resp = fetch_with_retry(url)
    if resp is None:
        return {}

    try:
        data = resp.json()
    except Exception:
        logger.warning("TPEx JSON 解析失敗")
        return {}

    prices: dict[str, float] = {}
    names:  dict[str, str]   = {}
    for row in data.get("aaData", []):
        try:
            # 欄位順序：[代號, 名稱, 收盤價, ...]
            code  = str(row[0]).strip()
            name  = str(row[1]).strip()
            price_str = str(row[2]).replace(",", "").strip()
            prices[code] = float(price_str)
            names[code]  = name
        except (ValueError, IndexError):
            continue
    return prices, names


# ============================================================
# ============================================================
# 【1-C】三大法人與投信（TWSE T86，僅上市，ETF 跳過）
# ============================================================
def fetch_institutional(target_codes: list[str], dates: list[str]) -> dict[str, dict]:
    """
    累加 dates 列表中每一天的三大法人淨買超張數，以及投信連買狀況。
    回傳 {股票代號: {"net_buy_3d": 123, "it_continuous_buy": True}}
    """
    results: dict[str, dict] = {}
    it_buy_history: dict[str, list[bool]] = {}

    for date_str in dates:
        url = (
            "https://www.twse.com.tw/rwd/zh/fund/T86"
            f"?response=json&date={date_str}&selectType=ALLBUT0999"
        )
        resp = fetch_with_retry(url)
        if resp is None: continue
        try: data = resp.json()
        except Exception: continue

        if data.get("stat") != "OK": continue

        fields = data.get("fields", [])
        try:
            code_idx = fields.index("證券代號")
            net_idx  = fields.index("三大法人買賣超股數")
            it_idx   = fields.index("投信買賣超股數")
        except ValueError:
            try:
                code_idx = 0
                net_idx = -1
                it_idx = fields.index("投信買賣超股數") if "投信買賣超股數" in fields else -2
            except ValueError:
                continue

        for row in data.get("data", []):
            try:
                code = row[code_idx].strip()
                if code not in target_codes: continue
                
                net_shares = int(str(row[net_idx]).replace(",", "").strip())
                net_lots   = net_shares // 1000
                
                it_shares = int(str(row[it_idx]).replace(",", "").strip())
                it_lots   = it_shares // 1000
                is_it_buy = it_lots > 0

                if code not in results:
                    results[code] = {"net_buy_3d": 0, "it_continuous_buy": False}
                    it_buy_history[code] = []
                
                results[code]["net_buy_3d"] += net_lots
                it_buy_history[code].append(is_it_buy)
            except (ValueError, IndexError):
                continue
        time.sleep(0.8)

    for code, history in it_buy_history.items():
        if len(history) > 0 and len(history) == len(dates) and all(history):
            results[code]["it_continuous_buy"] = True

    return results
# /* 收費風險警告：yfinance 為非官方開源套件，本身完全免費，
# ============================================================
# 【技術面】計算 60 日均線 (MA60) (改用 FinMind)
# ============================================================
def fetch_mas(code: str) -> tuple[float | None, float | None]:
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
        return None, None
# 【1-E】Google News RSS 今日/昨日新聞篇數
# /* 收費風險警告：Google News RSS 為非官方公開端點，
#    Google 可能隨時調整結構或頻率限制，但本身不收費。*/
# ============================================================
def fetch_news(code: str, name: str) -> tuple[int, int]:
    """
    搜尋 Google News RSS，統計今日與昨日新聞篇數。
    回傳 (today_count, yesterday_count)。
    """
    query = requests.utils.quote(f"{code} {name}")
    url   = (
        f"https://news.google.com/rss/search?q={query}"
        "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
    resp = fetch_with_retry(url)
    if resp is None:
        return 0, 0

    try:
        root  = ET.fromstring(resp.content)
        today     = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        today_count = 0
        yesterday_count = 0

        for item in root.iter("item"):
            pub_date_el = item.find("pubDate")
            if pub_date_el is None:
                continue
            pub_date_str = pub_date_el.text or ""
            # 格式：Thu, 12 Jun 2026 05:00:00 GMT
            try:
                # 解析 RFC 2822 格式
                pub_dt = datetime.datetime.strptime(
                    pub_date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S"
                )
                pub_date = pub_dt.date()
            except ValueError:
                continue

            if pub_date == today:
                today_count += 1
            elif pub_date == yesterday:
                yesterday_count += 1

        return today_count, yesterday_count

    except ET.ParseError as e:
        logger.warning(f"Google News RSS 解析失敗 [{code}]: {e}")
        return 0, 0


# ============================================================
# 【1-F】PTT Stock 版輿情（兩段式爬蟲）
# ============================================================
def fetch_ptt(code: str, name: str) -> tuple[int, int]:
    """
    爬取 PTT Stock 版，統計符合標題的文章推/噓數。
    速率限制：每篇 0.5s，每頁 1s，最多 3 頁。
    回傳 (total_push, total_boo)。
    """
    base_url  = "https://www.ptt.cc"
    cookies   = {"over18": "1"}
    push_total = 0
    boo_total  = 0

    # 取第一頁索引
    index_resp = fetch_with_retry(
        f"{base_url}/bbs/Stock/index.json",
        cookies=cookies
    )
    if index_resp is None:
        return 0, 0

    try:
        articles = index_resp.json()
    except Exception:
        return 0, 0

    # 最多爬 3 頁（每頁約 20 篇）
    pages_fetched = 0
    checked_hrefs: set[str] = set()

    # 先處理第一頁（index.json 已包含一頁）
    def process_page(article_list: list) -> None:
        nonlocal push_total, boo_total
        for art in article_list:
            title = art.get("title", "")
            href  = art.get("href", "")
            if not href or href in checked_hrefs:
                continue
            # 篩選包含代號或名稱的文章（不分大小寫）
            if code.lower() not in title.lower() and name not in title:
                continue
            checked_hrefs.add(href)
            art_resp = fetch_with_retry(f"{base_url}{href}.json", cookies=cookies)
            if art_resp is None:
                continue
            try:
                art_data = art_resp.json()
                push_total += art_data.get("push_count",  0)
                boo_total  += art_data.get("boo_count",   0)
            except Exception:
                pass
            time.sleep(0.5)

    process_page(articles)
    pages_fetched += 1

    # 繼續往前翻頁（PTT index 有 previous_page_href）
    # 使用索引 URL 模式往前翻
    try:
        # 取得 index 頁碼（從 articles 的 href 推算）
        if articles:
            last_href = articles[0].get("href", "")
            # 格式 /bbs/Stock/M.xxxxx.A.xxx.html → 提取頁碼偏移
            # PTT index URL 格式：/bbs/Stock/index{N}.json
            import re
            index_match = re.search(r"index(\d+)\.json", index_resp.url if hasattr(index_resp, 'url') else "")
            if index_match:
                page_num = int(index_match.group(1))
            else:
                page_num = None

            if page_num:
                for offset in range(1, 3):  # 再抓 2 頁
                    prev_num  = page_num - offset
                    prev_url  = f"{base_url}/bbs/Stock/index{prev_num}.json"
                    prev_resp = fetch_with_retry(prev_url, cookies=cookies)
                    if prev_resp is None:
                        break
                    try:
                        prev_articles = prev_resp.json()
                        process_page(prev_articles)
                    except Exception:
                        break
                    pages_fetched += 1
                    time.sleep(1.0)
                    if pages_fetched >= 3:
                        break
    except Exception as e:
        logger.warning(f"PTT 翻頁失敗 [{code}]: {e}")

    return push_total, boo_total


# ============================================================
# 【1-H】產業關鍵字權重矩陣
# ============================================================
def match_keywords(code: str, name: str) -> list[dict]:
    """
    對每個關鍵字搜尋 Google News RSS，
    近 7 日內有命中則加入結果。
    回傳 [{"tag": kw, "weight": w}, ...]。
    """
    seven_days_ago = datetime.date.today() - datetime.timedelta(days=7)
    hits: list[dict] = []

    for keyword, weight in KEYWORD_WEIGHTS.items():
        query = requests.utils.quote(f"{code} {name} {keyword}")
        url   = (
            f"https://news.google.com/rss/search?q={query}"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )
        resp = fetch_with_retry(url)
        if resp is None:
            continue

        try:
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                pub_el = item.find("pubDate")
                if pub_el is None:
                    continue
                try:
                    pub_dt   = datetime.datetime.strptime(
                        (pub_el.text or "")[:25].strip(), "%a, %d %b %Y %H:%M:%S"
                    )
                    pub_date = pub_dt.date()
                    if pub_date >= seven_days_ago:
                        hits.append({"tag": keyword, "weight": weight})
                        break  # 此關鍵字已命中，跳下一個
                except ValueError:
                    continue
        except ET.ParseError:
            pass

        time.sleep(0.3)  # 避免 Google 頻率限制

    return hits


# ============================================================
# 【1-G】警報判斷（優先順序：高蓋低）
# ============================================================
# ============================================================
# 【小白專屬 AI 體檢】綜合分數與白話文解讀
# ============================================================
def calc_health_score_and_advice(s: dict) -> dict:
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
    }
def calc_alert(
    news_today:     int,
    news_yesterday: int,
    ptt_push:       int,
    ptt_boo:        int,
    inst_net_buy:   int | None,
) -> str | None:
    """
    根據規格優先順序判斷警報類型。
    回傳 "fomo_warning" | "golden_divergence" | "news_surge" | None
    """
    safe_yesterday = max(news_yesterday, 1)
    news_ratio     = news_today / safe_yesterday
    safe_denom     = ptt_push + ptt_boo
    push_ratio     = ptt_push / safe_denom if safe_denom > 0 else 0
    boo_ratio      = ptt_boo  / safe_denom if safe_denom > 0 else 0

    # 1. FOMO 警告（最高優先）
    if news_ratio >= 2.0 and push_ratio > 0.80 and news_today >= 3:
        return "fomo_warning"

    # 2. 黃金背離
    if inst_net_buy is not None and inst_net_buy > 500 and boo_ratio > 0.30:
        return "golden_divergence"

    # 3. 新聞暴增
    if news_ratio >= 2.0 and news_today >= 3:
        return "news_surge"

    return None


# ============================================================
# 【1-I】Telegram 推播
# ============================================================
def send_telegram(message: str) -> bool:
    """
    透過 Telegram Bot API 發送訊息。
    parse_mode=HTML，Token/ChatID 從環境變數讀取。
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，跳過推播")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("✅ Telegram 推播成功")
            return True
        else:
            logger.warning(f"Telegram 推播失敗：{resp.status_code} {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        logger.warning(f"Telegram 推播例外：{e}")
        return False


# ============================================================
# 輔助：取最近 N 個交易日（排除週末，近似法）
# ============================================================
def get_recent_trading_dates(n: int = 3) -> list[str]:
    """
    回傳最近 n 個可能的交易日（YYYYMMDD 格式，排除週六日）。
    注意：此為近似法，無法排除國定假日。
    """
    dates: list[str] = []
    candidate = datetime.date.today()
    while len(dates) < n:
        if candidate.weekday() < 5:  # 0=週一 ... 4=週五
            dates.append(candidate.strftime("%Y%m%d"))
        candidate -= datetime.timedelta(days=1)
    return dates


# ============================================================
# 【1-J / 1-K / 主流程】run_pipeline
# ============================================================
def run_pipeline() -> None:
    start_time = time.time()
    today_str  = datetime.date.today().strftime("%Y%m%d")
    now_iso    = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    logger.info(f"🚀 Pipeline 啟動 [{now_iso}]")

    twse_prices, twse_names = fetch_twse_prices(today_str)
    if not twse_prices:
        logger.info("📅 今日為非交易日或 TWSE 尚未更新，跳過執行。")
        return

    tpex_prices, tpex_names = fetch_tpex_prices(today_str)
    all_prices = {**twse_prices, **tpex_prices}
    all_names  = {**twse_names, **tpex_names}

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

        ma_result = fetch_mas(code)
        if ma_result == (None, None): continue
        ma60, ma20 = ma_result
        if ma60 is None or price <= ma60 or net_buy <= 0: continue
        stop_loss = round(ma60 * 0.97, 2)
        
        revenue_info = revenue_data.get(code, {})

        scan_candidates.append({
            "code":            code,
            "price":           price,
            "ma60":               ma60,
            "ma20":               ma20,
            "ma20":               ma20,
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
        name  = all_names.get(code, code)  # 從 TWSE/TPEx 抓到的真實中文名稱
        price = s["price"]
        ma60  = s["ma60"]
        ma20  = s.get("ma20")
        net   = s["inst_net_buy_3d"]

        news_today, news_yday = fetch_news(code, name)
        ptt_push, ptt_boo     = fetch_ptt(code, name)
        keywords_hit          = match_keywords(code, name)
        alert                 = calc_alert(news_today, news_yday, ptt_push, ptt_boo, net)

        if alert: alert_count += 1
        kw_score = sum(k["weight"] for k in keywords_hit)
        score    = net + kw_score * 100

        # 市場掃描也計算小白解讀 (掃描版不含成本資訊，故 cost_price=None)
        scan_item_for_advice = {
            "price":              price,
            "ma60":               ma60,
            "ma20":               ma20,
            "cost_price":         None,
            "inst_net_buy_3d":    net,
            "it_continuous_buy":  s["it_continuous_buy"],
            "revenue_double_growth": s["revenue_double_growth"],
        }
        health = calc_health_score_and_advice(scan_item_for_advice)

        market_result.append({
            "code":               code,
            "name":               name,
            "is_etf":             False,  # 市場掃描只掃非ETF個股
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
            "score":              health["score"],
            "light":              health["light"],
            "advice":             health["advice"],
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

        ma_result = fetch_mas(code)
        if ma_result == (None, None): continue
        ma60, ma20 = ma_result
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

        shares   = p.get("shares")
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
        portfolio_result.append(port_item)
        
        if stop_loss and price < stop_loss:
            pnl_str = f"{pnl_pct}%" if pnl_pct is not None else "未設成本"
            msg = (
                f"🚨 <b>強制停損警告</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📌 標的：<b>{code} {name}</b>\n"
                f"💰 當前股價：<b>{price}</b> 元\n"
                f"🛡 建議防守價：<b>{stop_loss}</b> 元\n"
                f"📉 持倉損益：<b>{pnl_str}</b>\n"
                f"⏰ 時間：{now_iso}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚠️ 股價已跌破 MA60×0.97，請檢視停損策略！"
            )
            send_telegram(msg)
            
        if alert in ("fomo_warning", "golden_divergence"):
            alert_zh = {
                "fomo_warning":     "🔥 FOMO 散戶狂熱",
                "golden_divergence": "⚡ 黃金背離",
            }[alert]
            kw_str = "、".join(k["tag"] for k in keywords_hit) or "無"
            msg = (
                f"🔔 <b>台股警報：{code} {name}</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚠️ 警報類型：{alert_zh}\n"
                f"💹 股價：{price} 元 | MA60：{ma60} 元\n"
                f"🛡 建議防守價：{stop_loss} 元\n"
                f"🏦 法人3日淨買超：{inst_net if inst_net is not None else 'N/A'} 張\n"
                f"📰 新聞今日：{news_today} 篇\n"
                f"💬 PTT 推/噓：{ptt_push}/{ptt_boo}\n"
                f"🔑 命中關鍵字：{kw_str}\n"
                f"⏰ 時間：{now_iso}"
            )
            send_telegram(msg)

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
# 【大盤位階判斷】fetch_tw_market_phase (修正版：改用 TWSE API)
# ============================================================
def fetch_tw_market_phase() -> dict | None:
    """
    抓取台股加權指數 (^TWII) 計算大盤位階 (20MA)。
    避免 yfinance 經常斷線抓不到資料的問題，改用 TWSE 官方歷史指數 API。
    回傳 {"close": 20000, "ma20": 19500, "weather": "🌞 晴天"}
    """
    try:
        from dateutil.relativedelta import relativedelta
        import datetime
        
        closes = []
        today = datetime.date.today()
        # 抓取上個月與這個月的資料，確保有足夠的 20 天交易日
        dates_to_fetch = [
            (today - relativedelta(months=1)).strftime('%Y%m01'),
            today.strftime('%Y%m01')
        ]
        
        for d in dates_to_fetch:
            url = f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MIN_HIST?response=json&date={d}"
            resp = fetch_with_retry(url)
            if not resp: continue
            data = resp.json()
            if data.get("stat") == "OK":
                for row in data.get("data", []):
                    close_str = row[4].replace(",", "")
                    closes.append(float(close_str))
            time.sleep(1) # 避免過度頻繁請求
            
        if len(closes) < 20:
            logger.warning("TWSE API 歷史資料不足 20 天")
            return None
            
        last_close = float(closes[-1])
        ma20 = float(sum(closes[-20:]) / 20)
        weather = "🌞 晴天" if last_close >= ma20 else "🌧️ 雨天"
        
        return {"close": round(last_close, 2), "ma20": round(ma20, 2), "weather": weather}
    except Exception as e:
        logger.warning(f"fetch_tw_market_phase 失敗: {e}")
        return None
# 使用 yfinance 抓取美股主要指數昨日收盤表現
# ============================================================
# 【美股】抓取大盤指數 (改用 FinMind)
# ============================================================
def fetch_us_market() -> dict:
    """
    獲取 S&P 500 (^GSPC) 與 費半指數 (^SOX) 昨日收盤價。
    改用 FinMind USStockPrice 避免 yfinance 擋 IP。
    """
    res = {
        "S&P 500": None,
        "費半指數": None,
    }
    
    symbols = {
        "^GSPC": "S&P 500",
        "^SOX": "費半指數"
    }
    
    try:
        import datetime
        start_date = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        
        for code, name in symbols.items():
            url = f"https://api.finmindtrade.com/api/v4/data?dataset=USStockPrice&data_id={code}&start_date={start_date}"
            resp = fetch_with_retry(url)
            if not resp: continue
            
            data = resp.json()
            if data.get("msg") == "success" and data.get("data"):
                prices = data["data"]
                if len(prices) >= 2:
                    last_close = prices[-1]["Close"]
                    prev_close = prices[-2]["Close"]
                    chg_pct = round((last_close - prev_close) / prev_close * 100, 2)
                    res[name] = {"close": last_close, "chg_pct": chg_pct}
                    
    except Exception as e:
        logger.warning(f"US Market fetching failed: {e}")
        
    return res
# ============================================================
# 台股輿情雷達 v10 — 後端資料管道
# pipeline.py
# ============================================================
#
# 【排程設定 — GitHub Actions】
# 請在專案根目錄建立 .github/workflows/daily_pipeline.yml
#
# name: Daily Taiwan Stock Pipeline
# on:
#   schedule:
#     - cron: '30 8 * * 1-5'  # UTC 08:30 = 台灣時間 16:30 週一至週五
#   workflow_dispatch:
# jobs:
#   run-pipeline:
#     runs-on: ubuntu-latest
#     steps:
#       - uses: actions/checkout@v3
#       - uses: actions/setup-python@v4
#         with: { python-version: '3.11' }
#       - run: pip install -r requirements.txt
#       - name: Run Pipeline
#         env:
#           TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
#           TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
#         run: python pipeline.py
#       - name: Commit Output
#         run: |
#           git config user.email "bot@github.com"
#           git config user.name "Pipeline Bot"
#           git add dashboard_data.json dashboard_data_backup.json
#           git diff --cached --quiet || git commit -m "📊 Auto update $(date +'%Y-%m-%d')"
#           git push
#
# ============================================================
# requirements.txt
# requests==2.31.0
# beautifulsoup4==4.12.3
# pandas==2.2.2
# yfinance==0.2.40
# ============================================================
#
# 【Telegram Bot 設定說明】
# 1. 在 Telegram 搜尋 @BotFather，發送 /newbot 建立 Bot
# 2. 取得 Bot Token（格式：123456:ABC-DEF...）
# 3. 與你的 Bot 對話後，前往 https://api.telegram.org/bot<TOKEN>/getUpdates
#    找到 "chat":{"id": 你的 Chat ID}
# 4. 在 GitHub Repo → Settings → Secrets and variables → Actions 新增：
#    - TELEGRAM_BOT_TOKEN = 你的 Bot Token
#    - TELEGRAM_CHAT_ID   = 你的 Chat ID
# ============================================================


# ============================================================
# 【每日智能摘要推播】send_daily_summary
# 每次 pipeline 完成後，自動發送包含：
#   美股表現 / 庫存狀態 / 市場亮點 / 明日注意事項 / AI Prompt
# ============================================================
def send_daily_summary(
    portfolio_result: list,
    market_result:    list,
    us_market:        dict,
    market_phase:     dict | None,
    now_iso:          str,
) -> None:
    """組合並發送每日 Telegram 智能摘要報告。"""
    today_str = now_iso[:10]
    lines: list[str] = []

    lines.append(f"📊 <b>台股輿情雷達 每日報告</b>")
    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"📅 {today_str} 收盤後分析")
    lines.append("")
    
    # ── 大盤位階 ──
    if market_phase:
        weather = market_phase["weather"]
        close = market_phase["close"]
        ma20 = market_phase["ma20"]
        lines.append(f"🌦️ <b>【台股大盤氣象站】</b>")
        lines.append(f"  目前位階：{weather} (收盤 {close} / 月線 {ma20})")
        if "晴天" in weather:
            lines.append("  ✅ 指數站上月線，資金環境偏多，可積極操作。")
        else:
            lines.append("  ⚠️ 指數跌破月線，覆巢之下無完卵，請縮小部位並嚴守停損！")
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
            
            tags = []
            if s.get("it_continuous_buy"): tags.append("🏦投信連買")
            if s.get("revenue_double_growth"): tags.append("💰營收雙增")
            tag_str = " | ".join(tags)
            if tag_str: tag_str = f" [{tag_str}]"
            
            lines.append(f"  #{i} {s['code']} {s['name']} | {sign}{net:,}張{tag_str}")
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
        s for s in portfolio_result
        if s.get("suggested_stop_loss") and s.get("price") and s["price"] < s["suggested_stop_loss"]
    ]

    if stoploss_port:
        has_note = True
        names = "、".join(s["name"] for s in stoploss_port)
        lines.append(f"  ⛔ <b>庫存跌破停損</b>：{names}")
        lines.append("     👉 收盤確認破底，明日開盤建議優先處理。")

    if weak_port:
        has_note = True
        names = "、".join(s["name"] for s in weak_port if s not in stoploss_port)
        if names:
            lines.append(f"  ⚠️ <b>庫存轉弱</b>：{names}")
            lines.append("     👉 跌破季線支撐，可能進入整理期。")

    if golden_stocks:
        has_note = True
        names = "、".join(s["name"] for s in golden_stocks)
        lines.append(f"  ✨ <b>關注清單</b>：{names}")
        lines.append("     👉 法人買超且基本面題材浮現，可加入自選股觀察。")

    if fomo_stocks:
        has_note = True
        names = "、".join(s["name"] for s in fomo_stocks)
        lines.append(f"  🔥 <b>避開高危</b>：{names}")
        lines.append("     👉 市場過熱，切勿在此時追高進場，以免被套。")

    if not has_note:
        lines.append("  ✅ 今日無特殊異常，維持原交易紀律。")

    lines.append("")
    lines.append("🤖 /ai_analysis -> 呼叫 AI 進行深入診斷")

    msg = "\n".join(lines)
    send_telegram(msg)
# ============================================================
if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as e:
        err_time = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        err_msg  = (
            f"⛔ <b>Pipeline 執行失敗</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"❌ 錯誤訊息：{str(e)[:300]}\n"
            f"⏰ 時間：{err_time}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 今日儀表板資料可能未更新，請手動檢查。"
        )
        logger.exception(f"❌ Pipeline 未捕捉例外：{e}")
        send_telegram(err_msg)




