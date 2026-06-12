請扮演資深全端量化系統架構師與新手投資導師。我需要設計一套
「全自動免費台股多維度篩選與新聞輿情監控系統」。

這套系統必須兼顧「後端輕量資料管道」、「前端動態網頁儀表板」，
支援「手機版 PWA」、「自動推播通知」，並且必須「100% 完全免費」。
使用者是一位「股市新手」，系統必須具備強大的防呆、風險提示機制，
並能「獨立追蹤使用者的現有持股與 ETF」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【🔥 錢包防禦、資安與費用最高原則】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 嚴格禁止主動引入任何需要註冊、綁定信用卡、或超過免費額度後
   會收費的第三方 API 或服務。

2. 通知機制：
   - 前端：HTML5 Notification API（含授權詢問邏輯）。
   - 後端：Telegram Bot API（官方免費無限量）。
   - 嚴禁使用已於 2025/03/31 停止服務的 LINE Notify。

3. 憑證安全（防止金鑰洩漏）：
   - Telegram Bot Token 與 Chat ID 嚴禁寫死在程式碼中。
   - 必須透過 os.environ.get() 讀取環境變數。
   - 在 GitHub Actions 中透過 Repo Secrets 注入
     （${{ secrets.TELEGRAM_BOT_TOKEN }}、${{ secrets.TELEGRAM_CHAT_ID }}）。

4. 收費風險標註義務：
   - 若判斷有任何技術「可能」在未來產生費用，
     必須立刻在程式碼旁寫下顯眼的 /* 收費風險警告 */ 並說明原因。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【🛠️ 全域技術限制與架構規範】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 後端語言與套件：Python 3，僅允許使用：
   requests、BeautifulSoup、pandas、yfinance、os、json、
   time、datetime、logging、xml.etree.ElementTree

2. 前端架構：單一 index.html，優先使用原生 HTML5、CSS3、Vanilla JS（ES6+）。

3. 框架封印（絕對禁止）：
   C#、React、Vue、Angular、Svelte 或任何需要 Node.js / npm 編譯環境的工具鏈。

4. 唯一前端套件特例：
   <script src="https://cdn.tailwindcss.com"></script>
   /* 收費風險警告：Tailwind Play CDN 目前免費，正式生產環境建議改用本地編譯版。*/

5. 本地執行環境：
   python -m http.server 8080
   啟動後於瀏覽器開啟 http://localhost:8080

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【🎯 核心系統功能架構 10.0（終極完整版）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

請輸出完整、乾淨、無任何省略號（...）的程式碼。

────────────────────────────────────────────────────
▌ 1. Python 後端資料管道（pipeline.py）
────────────────────────────────────────────────────

【1-A】自選庫存設定

  在程式碼開頭定義：
  MY_PORTFOLIO = [
    {"code": "0050", "name": "元大台灣50",  "is_etf": True,  "cost_price": 150.0},
    {"code": "2330", "name": "台積電",       "is_etf": False, "cost_price": 850.0},
    {"code": "00878","name": "國泰永續高股息","is_etf": True,  "cost_price": 20.0},
  ]
  使用者可自行修改此列表。cost_price 選填，未填寫設為 None。

【1-B】雙軌抓取邏輯

  軌道 A — 市場掃描（有篩選條件）：
    篩選：(股價 > 60MA) 且 (近3日三大法人合計淨買超 > 0 張)
    候選池上限：前 80 檔（依三大法人淨買超降序）

  軌道 B — 庫存 VIP 豁免（無篩選條件）：
    對 MY_PORTFOLIO 內的所有標的，無視上述篩選條件，
    強制抓取報價、60MA、新聞與 PTT 數據。

  ETF 處理規則（重要）：
    is_etf = True 的標的，跳過 T86 三大法人查詢，
    inst_net_buy_3d 設為 null，不參與法人篩選條件。
    仍正常抓取：報價、yfinance MA60、Google News、PTT。

【1-C】籌碼與報價抓取

  上市股票收盤價（TWSE）：
    GET https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
        ?response=json&type=ALLBUT0999&date={YYYYMMDD}

  上櫃股票收盤價（TPEx）：
    /* 收費風險警告：TPEx API 為公開免費端點，但結構可能隨時調整。*/
    GET https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php
        ?l=zh-tw&o=json&d={MM/DD/YYYY}&se=EW
    解析 aaData 陣列，欄位順序：[代號, 名稱, 收盤價, ...]

  三大法人（僅上市，TWSE T86）：
    GET https://www.twse.com.tw/rwd/zh/fund/T86
        ?response=json&date={YYYYMMDD}&selectType=ALLBUT0999
    近3個交易日迴圈累加，每次請求間隔 time.sleep(0.8)。
    ETF 代號跳過此查詢。

【1-D】技術線與停損計算

  /* 收費風險警告：yfinance 為非官方開源套件，本身完全免費，
     但高頻請求可能導致 Yahoo Finance 暫時封鎖 IP。
     務必在每次 yfinance 請求後加入 time.sleep(0.2)。*/

  台股代號格式：{代號}.TW（例：2330.TW）
  ETF 代號格式：{代號}.TW（例：0050.TW）
  抓取最近 6 個月歷史資料（period="6mo"）
  計算：ma60 = 最近 60 個交易日收盤價平均
  計算：suggested_stop_loss = round(ma60 * 0.97, 2)
  計算損益（庫存標的，有 cost_price 時）：
    pnl_percent = round((price - cost_price) / cost_price * 100, 2)
    若 cost_price 為 None，則 pnl_percent = null

【1-E】新聞聲量抓取

  /* 收費風險警告：Google News RSS 為非官方公開端點，
     Google 可能隨時調整結構或頻率限制，但本身不收費。*/

  URL：https://news.google.com/rss/search?q={代號}+{名稱}
           &hl=zh-TW&gl=TW&ceid=TW:zh-Hant
  統計今日與昨日新聞篇數，使用 xml.etree.ElementTree 解析。

【1-F】PTT Stock 版輿情（兩段式爬蟲）

  速率限制：每篇 0.5s，每頁 1s，最多 3 頁。
  Step 1：GET https://www.ptt.cc/bbs/Stock/index.json（Cookie: over18=1）
  Step 2：對符合標題的文章，請求 {article_href}.json 取推噓數。
  計算：ptt_boo_ratio = ptt_boo / (ptt_push + ptt_boo)

【1-G】警報判斷（優先順序，高蓋低）

  1. fomo_warning：
     新聞今日量 / max(昨日量,1) >= 2.0
     且 ptt_push / (ptt_push + ptt_boo) > 0.80
     且今日新聞量 >= 3（防止基數過低誤判）

  2. golden_divergence：
     inst_net_buy_3d > 500
     且 ptt_boo_ratio > 0.30

  3. news_surge：
     新聞今日量 / max(昨日量,1) >= 2.0
     且今日新聞量 >= 3

  4. null：無特殊狀況

  額外規則（庫存標的專屬）：
    若 price < suggested_stop_loss，觸發 Telegram 強制停損推播，
    推播訊息包含：標的名稱、當前股價、建議防守價、持倉損益。

【1-H】產業關鍵字權重矩陣

  對「{代號} {名稱} {關鍵字}」搜尋 Google News RSS，
  近 7 日內有命中則加入 keywords_hit。

  關鍵字與權重：
    "Vera Rubin":5, "矽光子":5, "GB200":5,
    "CoWoS":4, "全液冷":4, "快接頭":4, "AI伺服器":4,
    "HBM":3, "液冷":3, "先進封裝":3

【1-I】Telegram 推播格式

  觸發條件：fomo_warning、golden_divergence、庫存跌破停損。
  格式：parse_mode="HTML"，內容包含：
    股票代號與名稱、股價與 60MA、建議停損價、
    警報類型（中文）、法人淨買超、PTT 推噓比、
    命中關鍵字、時間戳。

【1-J】Pipeline 執行日誌與錯誤推播（新增）

  執行摘要：每次 pipeline 完成後，在最後用 logging 輸出：
    ✅ 執行摘要：掃描 N 檔 / 通過篩選 M 檔 / 警報 K 檔 / 耗時 Xs

  錯誤推播：用 try/except 包住 run_pipeline() 主流程，
    若發生任何未捕捉例外，自動發 Telegram 推播：
    「⛔ Pipeline 執行失敗
       錯誤訊息：{error}
       時間：{datetime}
       ⚠️ 今日儀表板資料可能未更新，請手動檢查。」

  非交易日優雅退出：
    若 TWSE MI_INDEX 回傳空資料（假日或休市），
    pipeline 應輸出 log「今日為非交易日，跳過執行」並正常退出，
    不發送錯誤推播，不覆蓋現有 dashboard_data.json。

【1-K】冪等性保護（新增）

  每次寫出 dashboard_data.json 前，先將現有檔案備份為
  dashboard_data_backup.json，確保單日重複執行不會遺失前次資料。

【1-L】IP 退避重試機制（新增）

  實作 fetch_with_retry(url, max_retries=3) 函式：
    若回傳 429 或 5xx，使用指數退避（exponential backoff）重試：
    第1次失敗等 2s，第2次等 4s，第3次等 8s。
    三次均失敗後，記錄 log warning 並回傳 None（不 crash）。
  所有 TWSE、PTT、Google News 的 requests.get() 呼叫
  皆改為使用此函式。

【1-M】排程設定（GitHub Actions）

  在腳本頂部多行註解中，提供完整 YAML：

  # .github/workflows/daily_pipeline.yml
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

【1-N】requirements.txt（版本鎖定，新增）

  在腳本頂部註解中同時提供 requirements.txt 內容：
  # requirements.txt
  # requests==2.31.0
  # beautifulsoup4==4.12.3
  # pandas==2.2.2
  # yfinance==0.2.40

【1-O】資料輸出

  json.dump(..., ensure_ascii=False, indent=2) 寫出 dashboard_data.json。
  格式嚴格遵循下方資料契約。

────────────────────────────────────────────────────
▌ 2. 前端網頁儀表板（index.html）
────────────────────────────────────────────────────

【2-A】固定法律免責聲明橫幅（新增，最高優先）

  在頁面最頂部固定一條不可關閉的橫幅：
  「⚠️ 本系統資訊僅供參考，不構成任何投資建議。
     投資一定有風險，本系統對任何投資損益概不負責。
     新手請務必獨立評估風險，建議先了解商品特性再操作。」
  樣式：橙黃底色，黑色文字，全寬，字體小但清晰。

【2-B】視覺風格（Bloomberg 終端機深色科技風）

  配色：
    背景底色：#0a0e1a（深海軍藍黑）
    卡片底色：#111827
    主要文字：#e2e8f0
    數字強調：#00d4ff（氰藍）
    正值：#00ff88（螢光綠）
    負值：#ff4444（警戒紅）
    警告閃爍：#ff6b00（橙色）
  字型：透過 Google Fonts CDN 引入 JetBrains Mono。
  /* 收費風險警告：Google Fonts CDN 目前免費，
     若有隱私顧慮可改用系統等寬字型。*/

【2-C】頂部 Header

  左側：「📊 台股輿情雷達 v10」
  中間：即時時鐘（每秒更新）
  右側：
    資料新鮮度時間戳（最後更新：HH:MM）
    資料狀態指示燈（綠點=正常 / 紅點閃爍=離線模式）
    🔄 手動刷新按鈕（新增）：點擊後重新 fetch JSON 並重新渲染

【2-D】新手 Onboarding 說明（新增）

  首次開啟頁面時（localStorage["onboarding_done"] 不存在），
  顯示一個模態說明框，包含：
  「👋 歡迎使用台股輿情雷達！
   📌 上方「我的庫存」：追蹤你持有的標的，顯示帳面損益與技術面狀態。
   📡 下方「市場掃描」：系統自動篩選法人買超且股價強勢的標的。
   🛡 建議防守價：若股價跌破此價，建議考慮停損。
   🔥 紅色閃爍警告：代表市場散戶過熱，新手此時追買風險極高。
   點擊任意卡片上的 ⓘ 圖示可查看術語白話說明。」
  底部有「我了解了，開始使用」按鈕，關閉後寫入 localStorage。

【2-E】版面結構（兩大區塊）

  區塊一：「📂 我的庫存（My Portfolio）」
    獨立視覺區塊，與下方明確分隔（標題列 + 分隔線）。
    卡片額外顯示：
      帳面損益（pnl_percent）：正值綠色 / 負值紅色 / null 顯示「未設成本」
      距季線乖離率（前端即時計算）：
        bias_pct = ((price - ma60) / ma60 * 100).toFixed(1) + "%"
      庫存停損警告規則：
        price < suggested_stop_loss → 紅燈閃爍「🚨 嚴格執行停損」
        price < ma60 → 黃燈「⚠️ 轉弱警戒，留意出場時機」

  區塊二：「📡 市場掃描（強勢股雷達）」
    篩選結果列表，依綜合評分排序。
    評分公式：score = inst_net_buy_3d + (keywords_hit 權重總和 × 100)

【2-F】排序與篩選工具列（新增）

  在「市場掃描」區塊標題下方，加一排 Vanilla JS 篩選按鈕：
    [全部] [⚡ 只看警報] [📈 依法人買超] [📰 依新聞熱度] [★ 依關鍵字分數]
  點擊後即時重新排序/篩選卡片，不需重新 fetch。
  同時加一個搜尋框，支援即時依代號或公司名稱過濾。

【2-G】股票卡片設計

  每張卡片包含：
  ┌──────────────────────────────────────────┐
  │ [代號] 公司名稱   [排名箭頭] [Alert Badge] │
  │ 股價: 980  ↕ 60MA: 850 ⓘ  乖離率: +15.3% │
  │ 🛡 建議防守價: 824.5 ⓘ                    │
  │ 法人3日淨買: +15,000張 ⓘ                  │
  │ 新聞: 今45 / 昨15篇  PTT推/噓: 120/50     │
  │ [矽光子 ★5] [CoWoS ★4]  ← 可點擊過濾     │
  │ [🤖 AI診斷] [📋 複製原始數據]              │
  └──────────────────────────────────────────┘
  關鍵字 Tag 可點擊（新增）：
    點擊某 Tag 後，自動篩選出所有命中該關鍵字的標的。

【2-H】RWD 斷點（Tailwind）

  手機：單欄卡片流
  平板（md:）：雙欄
  桌機（lg:）：三欄

【2-I】Tooltip 白話文系統

  60MA ⓘ → 「60日均線：最近60個交易日的平均股價。
              股價站在均線之上，代表中期走勢偏強。」
  三大法人 ⓘ → 「外資、投信、自營商三類機構的合計買賣動向，
                 通常視為聰明錢的指標。連續買超代表機構看好。」
  建議防守價 ⓘ → 「60MA × 0.97。若股價跌破此位，
                   代表原本支撐可能失效，建議新手設定停損。」
  黃金背離 ⓘ → 「法人大買但散戶看空的罕見現象，
                 歷史上常見於主力默默佈局階段。僅供參考。」
  乖離率 ⓘ → 「股價距離60MA的百分比距離。
              正值代表股價在均線之上，負值代表跌破均線。」
  FOMO ⓘ → 「Fear Of Missing Out（害怕錯過）。
             新聞爆量且散戶一面倒看多，通常是追高前的危險訊號。」

【2-J】警報視覺規則

  fomo_warning：
    卡片邊框橙紅閃爍（CSS @keyframes pulse）
    頂部橫幅：「🔥 散戶狂熱中，慎防追高！入場風險極高。」

  golden_divergence：
    卡片邊框金色（#ffd700）
    Badge：「⚡ 黃金背離」

  news_surge：
    Badge：「📰 新聞暴增」

【2-K】LocalStorage 歷史排名軌跡

  載入時讀取 localStorage["prev_ranking"]，比對排名變化：
    🚀 +N（綠）/ 📉 -N（紅）/ —（灰）/ 🆕（藍，新進榜）
  儲存目前排名回 localStorage["prev_ranking"]。

【2-L】菜鳥 AI 診斷 Prompt（兩種版本）

  庫存版（My Portfolio 卡片）：
  「我是股市新手，這是我目前持有的標的，請幫我用白話文分析。
   請告訴我現在應該『續抱』還是『減碼/停損』，最大風險在哪？

   【持股資訊】
   - 代號：{code} {name}（{'ETF' if is_etf else '個股'}）
   - 成本價：{cost_price} 元
   - 當前股價：{price} 元
   - 帳面損益：{pnl_percent}%
   - 60MA：{ma60} 元 / 建議停損價：{suggested_stop_loss} 元
   - 距季線乖離率：{bias_pct}
   - 今日新聞量：{news_heat_today} 篇
   - PTT 推/噓：{ptt_push}/{ptt_boo}
   - 警報狀態：{alert}
   - 資料時間：{updated_at}」

  掃描版（Market Scan 卡片）：
  「我是股市新手，請用白話文解釋這檔股票目前的數據，
   並特別強調最大潛在風險與操作上的防禦建議。

   【股票資訊】
   - 代號：{code} {name}
   - 股價：{price} 元 / 60MA：{ma60} 元 / 停損價：{suggested_stop_loss} 元
   - 法人近3日淨買超：{inst_net_buy_3d} 張
   - 今/昨新聞量：{news_heat_today}/{news_heat_yesterday} 篇
   - PTT 推/噓：{ptt_push}/{ptt_boo}
   - 命中關鍵字：{keywords_hit_str}
   - 警報：{alert} / 資料時間：{updated_at}」

【2-M】離線降級與資料讀取

  1. 嘗試 fetch("dashboard_data.json")
  2. 成功 → 渲染，顯示綠色指示燈 + 更新時間。
  3. 失敗 → 使用 Mock Data，顯示「⚠️ 離線模式」
             橙色橫幅：「目前顯示為範例資料，非即時行情」

  內建 Mock Data（5 檔，涵蓋所有 alert 類型）：
    portfolio:
      - 0050 元大台灣50（is_etf:true, 有成本價, alert:null）
      - 00878 國泰永續高股息（is_etf:true, 有成本價, 跌破ma60 → 轉弱警戒）
    market_scanned:
      - 2330 台積電（alert:null）
      - 6669 緯穎（alert:golden_divergence）
      - 3711 日月光投控（alert:fomo_warning）

【2-N】持股比例風險提示（新增）

  在「我的庫存」區塊底部，固定顯示一段風險提醒文字：
  「📌 分散投資提醒：不建議將超過總資金 20% 集中在單一標的。
     本系統僅追蹤技術面與輿情，無法預測基本面風險與黑天鵝事件。」

【2-O】PWA 支援

  <head> 加入：
    <meta name="theme-color" content="#0a0e1a">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="manifest" href="manifest.json">

  manifest.json 內容（同時提供獨立檔案內容）：
  {
    "name": "台股輿情雷達",
    "short_name": "輿情雷達",
    "start_url": ".",
    "display": "standalone",
    "background_color": "#0a0e1a",
    "theme_color": "#0a0e1a",
    "icons": [{"src":"icon.png","sizes":"192x192","type":"image/png"}]
  }

【2-P】Web Notification

  頁面載入完成後詢問 Notification.requestPermission()。
  偵測到 alert 不為 null 的標的，發出通知（含股票名稱與警報類型）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【📄 dashboard_data.json 資料契約（最終版）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "updated_at": "2026-06-12T14:30:00",
  "run_summary": {
    "scanned_total": 80,
    "passed_filter": 12,
    "alert_count": 3,
    "elapsed_seconds": 142
  },
  "portfolio": [
    {
      "code": "0050",
      "name": "元大台灣50",
      "is_etf": true,
      "cost_price": 150.0,
      "price": 180.0,
      "ma60": 175.0,
      "suggested_stop_loss": 169.75,
      "pnl_percent": 20.0,
      "news_heat_today": 10,
      "news_heat_yesterday": 8,
      "ptt_push": 50,
      "ptt_boo": 10,
      "keywords_hit": [],
      "alert": null
    }
  ],
  "market_scanned": [
    {
      "code": "2330",
      "name": "台積電",
      "price": 980,
      "ma60": 850,
      "suggested_stop_loss": 824.5,
      "inst_net_buy_3d": 15000,
      "news_heat_today": 45,
      "news_heat_yesterday": 15,
      "ptt_push": 120,
      "ptt_boo": 50,
      "keywords_hit": [
        {"tag": "矽光子", "weight": 5},
        {"tag": "CoWoS",  "weight": 4}
      ],
      "alert": "fomo_warning"
    }
  ]
}

欄位說明：
  run_summary       → pipeline 執行摘要（掃描總數/通過篩選/警報數/耗時秒數）
  portfolio         → 庫存標的陣列
  market_scanned    → 市場掃描結果陣列
  is_etf            → 是否為 ETF（boolean）
  cost_price        → 持有成本價（浮點數或 null）
  pnl_percent       → 未實現損益 %，= (price-cost_price)/cost_price×100，或 null
  inst_net_buy_3d   → 近3日三大法人淨買超（整數，ETF 為 null）
  keywords_hit      → 命中關鍵字陣列（可為 []）
  alert             → "fomo_warning"|"golden_divergence"|"news_surge"|null

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【📌 輸出格式要求】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

請依序輸出以下三份完整、乾淨、無省略號的程式碼：

1. pipeline.py
   函式：fetch_with_retry、fetch_twse_prices、fetch_tpex_prices、
         fetch_institutional、fetch_ma60、fetch_news、fetch_ptt、
         match_keywords、calc_alert、send_telegram、run_pipeline
   主程式：if __name__ == "__main__": run_pipeline()

2. index.html
   包含所有互動功能（Tooltip、排名箭頭、排序篩選、AI診斷、
   Onboarding、Web Notification、手動刷新）
   包含內建 Mock Data（5 檔）

3. manifest.json
   獨立 JSON 檔案內容