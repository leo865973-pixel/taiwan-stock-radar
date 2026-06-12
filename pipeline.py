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
# 使用者可自行修改此列表
# cost_price 選填，未填寫設為 None
# ============================================================
MY_PORTFOLIO = [
    {"code": "0050",  "name": "元大台灣50",        "is_etf": True,  "cost_price": 150.0},
    {"code": "2330",  "name": "台積電",             "is_etf": False, "cost_price": 850.0},
    {"code": "00878", "name": "國泰永續高股息",      "is_etf": True,  "cost_price": 20.0},
]

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
def fetch_twse_prices(date_str: str) -> dict[str, float]:
    """
    抓取 TWSE MI_INDEX 全部上市股票收盤價。
    回傳 {股票代號: 收盤價} 字典。
    若為非交易日，回傳空字典。
    """
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?response=json&type=ALLBUT0999&date={date_str}"
    )
    resp = fetch_with_retry(url)
    if resp is None:
        return {}

    try:
        data = resp.json()
    except Exception:
        logger.warning("TWSE MI_INDEX JSON 解析失敗")
        return {}

    # 非交易日 → stat 不為 "OK"
    if data.get("stat") != "OK":
        return {}

    prices: dict[str, float] = {}
    for table in data.get("tables", []):
        fields = table.get("fields", [])
        # 找到含「收盤價」欄的表
        if "收盤價" not in fields:
            continue
        close_idx = fields.index("收盤價")
        code_idx  = fields.index("證券代號") if "證券代號" in fields else 0
        for row in table.get("data", []):
            try:
                code  = row[code_idx].strip()
                price_str = row[close_idx].replace(",", "").strip()
                prices[code] = float(price_str)
            except (ValueError, IndexError):
                continue
    return prices


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
    for row in data.get("aaData", []):
        try:
            # 欄位順序：[代號, 名稱, 收盤價, ...]
            code  = str(row[0]).strip()
            price_str = str(row[2]).replace(",", "").strip()
            prices[code] = float(price_str)
        except (ValueError, IndexError):
            continue
    return prices


# ============================================================
# 【1-C】三大法人（TWSE T86，僅上市，ETF 跳過）
# ============================================================
def fetch_institutional(target_codes: list[str], dates: list[str]) -> dict[str, int]:
    """
    累加 dates 列表中每一天的三大法人淨買超張數。
    僅查詢 target_codes（已排除 ETF）。
    回傳 {股票代號: 3日累計淨買超} 字典。
    """
    cumulative: dict[str, int] = {}

    for date_str in dates:
        url = (
            "https://www.twse.com.tw/rwd/zh/fund/T86"
            f"?response=json&date={date_str}&selectType=ALLBUT0999"
        )
        resp = fetch_with_retry(url)
        if resp is None:
            continue

        try:
            data = resp.json()
        except Exception:
            continue

        if data.get("stat") != "OK":
            continue

        fields = data.get("fields", [])
        # 欄位含：證券代號、買賣差股數（三大法人合計）
        try:
            code_idx = fields.index("證券代號")
            # 三大法人合計買賣差（張）
            net_idx  = fields.index("三大法人買賣超股數")
        except ValueError:
            # 欄位名稱不符時嘗試第2、最後欄
            code_idx = 0
            net_idx  = -1

        for row in data.get("data", []):
            try:
                code = row[code_idx].strip()
                if code not in target_codes:
                    continue
                net_str = str(row[net_idx]).replace(",", "").strip()
                # 單位：股 → 張（1張=1000股）
                net_shares = int(net_str)
                net_lots   = net_shares // 1000
                cumulative[code] = cumulative.get(code, 0) + net_lots
            except (ValueError, IndexError):
                continue

        time.sleep(0.8)  # 每次請求間隔 0.8s

    return cumulative


# ============================================================
# 【1-D】yfinance MA60 與停損計算
# /* 收費風險警告：yfinance 為非官方開源套件，本身完全免費，
#    但高頻請求可能導致 Yahoo Finance 暫時封鎖 IP。
#    務必在每次 yfinance 請求後加入 time.sleep(0.2)。*/
# ============================================================
def fetch_ma60(code: str) -> tuple[float | None, float | None]:
    """
    透過 yfinance 取得台股 MA60 與建議停損價。
    台股代號格式：{code}.TW（ETF 同樣適用）。
    回傳 (ma60, suggested_stop_loss)，失敗時回傳 (None, None)。
    """
    ticker_code = f"{code}.TW"
    try:
        ticker = yf.Ticker(ticker_code)
        hist   = ticker.history(period="6mo")
        time.sleep(0.2)  # 防封鎖強制延遲

        if hist.empty or len(hist) < 10:
            logger.warning(f"yfinance {ticker_code} 歷史資料不足")
            return None, None

        closes = hist["Close"].dropna().values
        ma60   = float(round(closes[-60:].mean(), 2)) if len(closes) >= 60 else float(round(closes.mean(), 2))
        stop_loss = round(ma60 * 0.97, 2)
        return ma60, stop_loss

    except Exception as e:
        logger.warning(f"yfinance 查詢失敗 [{ticker_code}]: {e}")
        time.sleep(0.2)
        return None, None


# ============================================================
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
    """
    主資料管道，含：
    - 雙軌抓取（市場掃描 + 庫存 VIP 豁免）
    - 冪等備份（1-K）
    - 執行摘要日誌（1-J）
    - 錯誤推播（1-J）
    - 非交易日優雅退出（1-J）
    """
    start_time = time.time()
    today_str  = datetime.date.today().strftime("%Y%m%d")
    now_iso    = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    logger.info(f"🚀 Pipeline 啟動 [{now_iso}]")

    # ── 步驟 1：抓取今日 TWSE 上市收盤價 ──
    logger.info("正在抓取 TWSE 收盤價...")
    twse_prices = fetch_twse_prices(today_str)

    # 非交易日優雅退出
    if not twse_prices:
        logger.info("📅 今日為非交易日或 TWSE 尚未更新，跳過執行。")
        return

    # 補充 TPEx 上櫃收盤價
    logger.info("正在抓取 TPEx 收盤價...")
    tpex_prices = fetch_tpex_prices(today_str)
    all_prices  = {**twse_prices, **tpex_prices}

    logger.info(f"取得收盤價共 {len(all_prices)} 檔")

    # ── 步驟 2：確定庫存代號集合 ──
    portfolio_codes = {p["code"] for p in MY_PORTFOLIO}
    etf_codes       = {p["code"] for p in MY_PORTFOLIO if p["is_etf"]}

    # ── 步驟 3：三大法人（僅上市非ETF）──
    logger.info("正在抓取三大法人資料（近3日）...")
    recent_dates = get_recent_trading_dates(3)
    # 候選池前 80 檔（依收盤價排序，先以代號過濾非ETF）
    # 全部上市代號（排除 ETF 代號形式：通常5位以上或含字母開頭00xxx）
    # 注意：此為近似篩選，ETF 代號通常以 0 開頭且5位
    candidate_non_etf_codes = [
        code for code in list(twse_prices.keys())[:SCAN_LIMIT * 2]
        if code not in etf_codes
    ]
    inst_data = fetch_institutional(candidate_non_etf_codes, recent_dates)
    logger.info(f"法人資料取得 {len(inst_data)} 檔")

    # ── 步驟 4：篩選候選池（軌道 A — 市場掃描）──
    logger.info("開始市場掃描篩選...")
    scan_candidates: list[dict] = []

    # 依三大法人淨買超降序排列，取前 SCAN_LIMIT 檔
    sorted_inst = sorted(inst_data.items(), key=lambda x: x[1], reverse=True)[:SCAN_LIMIT]

    for code, net_buy in sorted_inst:
        price = all_prices.get(code)
        if price is None:
            continue

        # 取 MA60
        ma60, stop_loss = fetch_ma60(code)

        # 篩選：股價 > MA60 且 法人3日淨買超 > 0
        if ma60 is None:
            continue
        if price <= ma60 or net_buy <= 0:
            continue

        scan_candidates.append({
            "code":            code,
            "price":           price,
            "ma60":            ma60,
            "inst_net_buy_3d": net_buy,
            "stop_loss":       stop_loss,
        })

    logger.info(f"市場掃描：通過篩選 {len(scan_candidates)} 檔")
    scanned_total  = len(sorted_inst)
    passed_filter  = len(scan_candidates)

    # ── 步驟 5：對候選池補充新聞/PTT/關鍵字/警報 ──
    alert_count   = 0
    market_result: list[dict] = []

    for s in scan_candidates:
        code  = s["code"]
        name  = code  # 若無名稱對照表，先用代號（實際可從 TWSE 資料取名）
        price = s["price"]
        ma60  = s["ma60"]
        net   = s["inst_net_buy_3d"]

        logger.info(f"  抓取 {code} 新聞/PTT/關鍵字...")
        news_today, news_yday = fetch_news(code, name)
        ptt_push, ptt_boo     = fetch_ptt(code, name)
        keywords_hit          = match_keywords(code, name)
        alert                 = calc_alert(news_today, news_yday, ptt_push, ptt_boo, net)

        if alert:
            alert_count += 1

        # 關鍵字評分
        kw_score = sum(k["weight"] for k in keywords_hit)
        score    = net + kw_score * 100

        rec = {
            "code":               code,
            "name":               name,
            "price":              price,
            "ma60":               ma60,
            "suggested_stop_loss": s["stop_loss"],
            "inst_net_buy_3d":    net,
            "news_heat_today":    news_today,
            "news_heat_yesterday": news_yday,
            "ptt_push":           ptt_push,
            "ptt_boo":            ptt_boo,
            "keywords_hit":       keywords_hit,
            "alert":              alert,
            "_score":             score,
        }
        market_result.append(rec)

        # 關鍵字分數排序
    market_result.sort(key=lambda x: x["_score"], reverse=True)
    for r in market_result:
        r.pop("_score", None)

    # ── 步驟 6：庫存 VIP 豁免（軌道 B）──
    logger.info("開始處理庫存標的（VIP 豁免）...")
    portfolio_result: list[dict] = []

    for p in MY_PORTFOLIO:
        code     = p["code"]
        name     = p["name"]
        is_etf   = p["is_etf"]
        cost     = p.get("cost_price")
        price    = all_prices.get(code)

        logger.info(f"  庫存 {code} {name}（ETF={is_etf}）")

        if price is None:
            logger.warning(f"  ⚠️ {code} 無收盤價資料，跳過")
            continue

        ma60, stop_loss = fetch_ma60(code)
        news_today, news_yday = fetch_news(code, name)
        ptt_push, ptt_boo     = fetch_ptt(code, name)
        keywords_hit          = match_keywords(code, name)

        # ETF 不查法人
        inst_net = None
        if not is_etf:
            inst_res = fetch_institutional([code], recent_dates)
            inst_net = inst_res.get(code)

        alert = calc_alert(news_today, news_yday, ptt_push, ptt_boo, inst_net)

        # 損益計算
        pnl_pct = None
        if cost is not None and price is not None:
            pnl_pct = round((price - cost) / cost * 100, 2)

        rec = {
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
            "alert":              alert,
        }
        portfolio_result.append(rec)

        if alert:
            alert_count += 1

        # 庫存停損推播（1-G 額外規則）
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

        # 警報推播
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

    # ── 步驟 7：冪等備份（1-K）──
    output_path  = "dashboard_data.json"
    backup_path  = "dashboard_data_backup.json"

    if os.path.exists(output_path):
        try:
            import shutil
            shutil.copy2(output_path, backup_path)
            logger.info(f"✅ 已備份至 {backup_path}")
        except Exception as e:
            logger.warning(f"備份失敗：{e}")

    # ── 步驟 8：輸出 JSON（1-O）──
    elapsed = round(time.time() - start_time, 1)
    output  = {
        "updated_at":  now_iso,
        "run_summary": {
            "scanned_total":   scanned_total,
            "passed_filter":   passed_filter,
            "alert_count":     alert_count,
            "elapsed_seconds": elapsed,
        },
        "portfolio":      portfolio_result,
        "market_scanned": market_result,
    }

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ dashboard_data.json 寫出完成")
    except Exception as e:
        logger.error(f"JSON 寫出失敗：{e}")

    # ── 步驟 9：執行摘要日誌（1-J）──
    logger.info(
        f"✅ 執行摘要：掃描 {scanned_total} 檔 / "
        f"通過篩選 {passed_filter} 檔 / "
        f"警報 {alert_count} 檔 / "
        f"耗時 {elapsed}s"
    )

    # ── 步驟 10：每日智能摘要推播 ──
    logger.info("正在抓取美股指數表現...")
    us_market = fetch_us_market()
    send_daily_summary(portfolio_result, market_result, us_market, now_iso)


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
        s for s in portfolio_result
        if s.get("suggested_stop_loss") and s.get("price")
        and s["price"] < s["suggested_stop_loss"]
    ]

    if stoploss_port:
        names = "、".join(f"{s['code']}{s['name']}" for s in stoploss_port)
        lines.append(f"  🚨 {names} 已跌破停損價 — 開盤務必重新評估出場")
        has_note = True

    if weak_port:
        names = "、".join(f"{s['code']}{s['name']}" for s in weak_port)
        lines.append(f"  ⚠️ {names} 跌破均線 — 開盤觀察量能，必要時減碼")
        has_note = True

    if fomo_stocks:
        names = "、".join(f"{s['code']}{s['name']}" for s in fomo_stocks[:2])
        lines.append(f"  🔥 {names} FOMO警告 — 追高風險高，新手避免追買")
        has_note = True

    if golden_stocks:
        names = "、".join(f"{s['code']}{s['name']}" for s in golden_stocks[:2])
        lines.append(f"  ⚡ {names} 黃金背離 — 可小量留意，嚴設停損")
        has_note = True

    if not has_note:
        lines.append("  ➡️ 目前無特殊警示，維持原有計畫執行")
    lines.append("")

    # ── AI 分析 Prompt ──
    us_str = "\n".join(
        f"- {k}：{v['chg_pct']:+.2f}%" if v else f"- {k}：無資料"
        for k, v in us_market.items()
    )
    port_str = "\n".join(
        f"- {s['code']} {s['name']}：股價{s.get('price')}，"
        f"MA60={s.get('ma60')}，損益{s.get('pnl_percent','未設')}%，"
        f"警報={s.get('alert') or '無'}"
        for s in portfolio_result
    ) or "（無持股）"

    ai_prompt = (
        f"我是台股新手，請依以下數據給我今日分析：\n"
        f"1. 我的庫存現況與風險評估\n"
        f"2. 明日開盤具體操作策略（續抱/減碼/停損/觀望）\n"
        f"3. 明日開盤前30分鐘要注意的事\n\n"
        f"【美股昨夜】\n{us_str}\n\n"
        f"【我的庫存】\n{port_str}"
    )

    lines.append("🤖 <b>【複製到 ChatGPT 取得完整分析】</b>")
    # Telegram 單則限 4096 字，截斷 prompt
    prompt_preview = ai_prompt[:400] + "...（完整版請至儀表板 AI診斷按鈕）"
    lines.append(prompt_preview)
    lines.append("")
    lines.append(f"⏰ 報告時間：{now_iso}")

    message = "\n".join(lines)
    # Telegram 訊息長度上限 4096
    if len(message) > 4000:
        message = message[:3980] + "\n...（內容已截斷）"

    send_telegram(message)
    logger.info("✅ 每日智能摘要已推播")


# ============================================================
# 主程式入口
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
