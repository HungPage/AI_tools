# Amazon 3C 與家電熱銷趨勢

Apify 每週一、四 09:00（台北）抓 Amazon Electronics、Appliances 熱銷榜各前 50 名 → webhook 通知 Dify →
LLM 判斷子品類、品牌、賣點 → Apps Script 寫進 Google 試算表 → Looker Studio 儀表板。

完整操作說明見安裝手冊；這個資料夾放的是手冊裡的程式與設定，外加自動化腳本、可匯入的 Dify 工作流和離線測試。

| 路徑 | 內容 |
|---|---|
| `apps_script/Code.gs` | 試算表接收端（日期＋ASIN＋榜別去重，算 prev_rank、rank_change、is_new） |
| `apify/input.json` | Actor 輸入（兩個榜各 50 筆） |
| `apify/webhook_payload.txt` | Webhook payload template：`{"datasetId": {{resource.defaultDatasetId}}}` |
| `apify/setup_apify.py` | 用 Apify API 建立／更新 task、排程（`0 9 * * 1,4`，Asia/Taipei）和 webhook。可重複執行，不會建出重複的設定 |
| `dify/workflow_webhook.yml` | Dify 匯入檔，起始節點是 Webhook 觸發器 |
| `dify/workflow_start.yml` | 備用匯入檔，起始節點是一般 Start（輸入 `datasetId`），給沒有觸發器的 Dify 版本，或手動測試用 |
| `dify/prepare.py`、`dify/merge.py`、`dify/prompt.txt` | 兩個程式碼節點與 LLM 提示詞；改完執行 `python3 dify/build_dsl.py` 重新產生匯入檔 |
| `tests/` | 離線測試：程式碼節點、匯入檔結構、Apify 腳本、Apps Script（在 Node 中模擬試算表），以及兩次抓取的端到端模擬 |

## 設定步驟

金鑰一律存在各服務自己的設定畫面或你電腦的環境變數，不要貼在對話或 commit 進 repo。

1. **Google 試算表**（手冊階段 1）：建立「Amazon 熱銷趨勢」，時區設台北；Apps Script 貼上 `apps_script/Code.gs`，
   把 `TOKEN` 改成你自己的長字串，部署成網頁應用程式（執行身分：我；存取權：所有人），複製 `/exec` 網址。
2. **Dify**：工作室 → 匯入 DSL 檔案 → 選 `dify/workflow_webhook.yml`（匯入失敗或沒有觸發器時改用 `workflow_start.yml`）。
   - 匯入檔裡的 Webhook 觸發器節點在 Dify 雲端版不會產生 Webhook URL（檢查清單顯示「接收通知：需要 Webhook URL」、
     「取資料：無效的變數」）。這時刪掉「接收通知」，在畫布新增一個 Webhook 觸發器：POST、`application/json`、
     Request Body 新增 `datasetId`（String、必填），接到「取資料」。再把「取資料」的 URL 清空，貼
     `https://api.apify.com/v2/datasets/`，按 `/` 從選單插入新節點的 `datasetId`，最後接 `/items?clean=true&format=json`。
     變數一定要用選單插入，手打的 `{{#1.datasetId#}}` 會指向已刪除的節點。
   - 右上 **環境變數** 填入三個值：`APIFY_TOKEN`、`SHEET_URL`（上一步的 `/exec` 網址）、`SHEET_TOKEN`（Apps Script 裡的 TOKEN）。
   - 打開「分類」LLM 節點，模型改成你帳號裡可用的模型（匯入檔預設 OpenAI gpt-4o-mini，溫度 0）。
   - 發布，複製 Webhook 觸發器節點上的正式 Webhook URL。
3. **Apify**：在自己電腦執行（只需要 Python 3，不用另外安裝套件）：
   ```bash
   export APIFY_TOKEN=...        # Apify → Settings → API & Integrations
   export DIFY_WEBHOOK_URL=...   # 第 2 步複製的正式 Webhook URL
   python3 apify/setup_apify.py --dry-run   # 先看會送出哪些設定
   python3 apify/setup_apify.py             # 建立 task、排程、webhook
   python3 apify/setup_apify.py --run       # 加 --run 會立刻跑一次（每次約 100 筆，約 US$0.32）
   ```
   不想跑腳本也可以照手冊階段 2、4 在 Apify 網頁上手動設定，內容相同。
4. **驗收**：跑一次 task 後，試算表 `data` 分頁應有標題列加約 100 列資料。
5. **Looker Studio**（手冊階段 6）：連 `data` 工作表，做子品類趨勢、價格帶分布、品牌占比、竄升榜、新進榜。

## 費用

每次約 100 筆、每週兩次，一個月約 870 筆，以每 1,000 筆 US$3.20 計約 US$2.8，在 Apify 免費方案每月 US$5 額度內。
不要把排程改成每天跑（約 US$9.6/月，超過免費額度）。實際單價以 Actor 的 Pricing 分頁為準。

## 測試

```bash
python3 -m unittest discover -s tests -v   # 需要 Python 3 + PyYAML、Node.js
```

`tests/fixtures/apify_items_sample.json` 是依手冊描述的欄位（`position`、`name`、`price`、`url`、`categoryName`）
做的合成資料，不是真實 Amazon 資料。Actor 的實際輸出欄位、Dify 匯入檔能否在你的 Dify 版本匯入、
Apify webhook 是否送達，都要在真實帳號跑過一次才算驗證。
