# 奧爾樂透：跨平台活動與開獎日曆同步服務（首版）

> **用途**：獨立於「奧爾樂透選號」App 的公開唯讀日曆服務。網頁、iOS、Android 使用相同 JSON。此專案**不負責投注或 QR 編碼**，也不會修改已封存的 Public Beta 0.9.0。

## 1. 架構與安全界線

```
中國信託彩券管理部／台彩官方公告
              │
    GitHub Actions 定時檢查（每日 09:17、21:17，台灣時間）
              │
    ├─ 只符合嚴格模板的「春節新增開獎日」
    │     檢查來源、公告日期、彩種、期別、數量、星期和日期範圍
    │     驗證通過 → 自動合併已核實日曆
    │
    └─ 其他加碼／促銷／臨時改期
          不自動發布 → 待核對清單與 GitHub Issue
              │
      已驗證 JSON（GitHub Pages）
              │
       網頁 / iOS / Android 開啟時讀取
```

- **一般使用者無須操作同步服務**；App 只顯示可用的開獎日期／活動結果。
- **你是管理者**；只有你有權修改 GitHub Repository 設定和人工核對的公告。
- 官方網頁解析失敗或格式變動時，**不覆寫已驗證日曆**。
- 服務第一版可自動核准**官方格式明確的春節加開日期**；其他公告採先通知、人工確認。不能保證每篇未來公告都能自動解析。
- GitHub Pages 是公開靜態檔案服務；`aoer-schedule.json` 和網站原始碼均可公開讀取，**不要放密碼、個人資料或 API 金鑰**。

## 2. 第一次建立 GitHub 專案（建議專案名稱固定）

以目前的 GitHub 帳號 `meji0196` 為例：

1. 下載完整 ZIP，解壓縮，保留裡面的 `.github/workflows` 資料夾。
2. 用 **GitHub Desktop** 將解壓縮的 `our-lotto-sync` 資料夾建立為本機 Repository，接著 Publish repository，名稱填 `our-lotto-sync`，選擇 **Public**。或先在 GitHub 建立空的 `our-lotto-sync` Repo，再用 GitHub Desktop Clone，將 ZIP 內容複製進去、Commit、Push。
3. GitHub 網頁進入新專案 **Settings → Pages**，選 `Deploy from a branch` → `main` → `/docs` → Save。
4. 進入 **Settings → Actions → General**，確認 Actions 可執行；需要時於 Workflow permissions 允許 **Read and write permissions**（實際權限可能受帳號或組織政策限制）。本專案工作流程只要求 `contents: write` 和 `issues: write`。
5. 在 **Actions** 頁面，找到 `Official lottery notices and calendar sync`，按 `Run workflow` 執行第一次檢查。
6. 完成 GitHub Pages 部署後，預計資料 URL 為：

   **`https://meji0196.github.io/our-lotto-sync/aoer-schedule.json`**

   此網址是依建議 Repo 名稱組成的**預定網址**，建立及部署前不會存在。Repository 名稱若不同，請同步調整 App 中的資料入口。

7. 瀏覽器打開該網址，應能看到 `schemaVersion: 1`、`games`、`issuedAt` 和 `promotions`。

**特別注意**：單純把 ZIP 上傳到 Repository，GitHub 不會自動將 ZIP 解壓縮。要將 ZIP **內部檔案**連同 `.github/` 資料夾上傳。

## 3. 同步後 App 如何使用？

開發測試版 **V14-BT** 已設定讀取上述網址。當服務尚未部署或網路不可用時，它會繼續使用已驗證快取和原本內建的例行開獎日程；不會因連線失敗將預購選單清空。

**網頁版**：預購日期與最新活動在網頁開啟、返回前景及定期檢查時讀取。\
**iOS／Android**：未來只需 HTTP GET 相同 JSON，並做版本驗證、暫存及失敗回退；無需重新開發公告爬取程式。

消費者端日曆的資料格式：

```json
{
  "schemaVersion": 1,
  "issuedAt": "2026-11-08T00:00:00Z",
  "games": {
    "lotto649": {"weekdays": [2,5], "addedDates": [], "cancelledDates": []},
    "539": {"weekdays": [1,2,3,4,5,6], "addedDates": [], "cancelledDates": []}
  },
  "promotions": []
}
```

上面僅展示兩個彩種，**實際 API 包含八種彩種**。`addedDates`、`cancelledDates` 都使用西元 `YYYY-MM-DD`，App 可自行顯示民國年。

## 4. 管理新公告

- 自動監控來源：`https://lotto.ctbcbank.com/news115.htm` 等官方年度公告頁（依當年民國年自動切換）。
- **嚴格春節新增開獎日公告**：自動核對表格宣告的新增期數與實際逐筆資料（第一版只支援這種明確形式，不假設以後每年都增加14期與3期）；若公告格式、日期、期別不同，即放入待確認清單。
- **其他活動／不定期加碼獎號／取消開獎日**：先顯示在 GitHub `Issues` 的「待核對」項目，並記錄 `state/pending-notices.json`；未經你確認不發布。
- 手動核對後，修改 `config/approved-calendar.json` 或 `config/approved-promotions.json`（必須提供官方來源、正確日期與 `confirmed: true`），提交後 `Publish administrator-confirmed draw dates` 會自動發布。
- 如發現錯誤或官方更正，修改批准資料即可重新發布；原先的使用者快取會在成功取得較新版本後替換。**已生成的 QR 不會被遠端改寫**，需重新核對投注日期。
- 原始專案已內建 2026 春節經官方公告確認的**歷史例外日期**；**沒有預先猜測2027年春節開獎日**。
- `config/approved-promotions.json` 初始為空：2026 中秋8碼的媒體整理數字尚未逐期完成官方核對，因此不以「官方確認」名義推到跨平台資料來源。

## 5. 日常運作及限制

- 排程採台灣時間約 **09:17 與 21:17**，GitHub 排程可能延遲或漏跑，不能當成秒級推播。官方公告變更不代表同一分鐘內所有手機都更新。
- **公開 Repository 的 GitHub Actions 定時工作流程可能因60天無 Repository 活動而停用**；請定期檢查 Actions。如果商業化後需要 SLA，建議升級成專用定時與監控服務。
- 官方公告可能是 PDF、圖片、非標準表格，或臨時更正。任何不能通過白名單格式驗證的公告，會保持待確認，**不會將猜測日期加入 QR 預購**。
- GitHub Pages 的 CORS 表現須在 iOS、Android 和自訂網域正式部署後實測；跨來源請求失敗時 App 必須使用本地已核對資料。GitHub Pages 無法由 Repo 自行設定 HTTP 回應標頭。
- 此專案不包含使用者追蹤、付費資料或個人投注記錄；公開端點只提供官方公告導出的公用日曆資訊。

## 6. 主要檔案

| 路徑 | 功能 |
|---|---|
| `.github/workflows/monitor.yml` | 每天兩次掃描官方公告、驗證、產生資料並提交 |
| `.github/workflows/publish-on-change.yml` | 你批准日期後自動更新 JSON |
| `config/approved-calendar.json` | 已確認的特殊加開日／取消日 |
| `config/approved-promotions.json` | 已確認的加碼活動與8碼獎號 |
| `config/settings.json` | 自動發布安全範圍及 Issue 通知設定 |
| `state/auto-approved.json` | 程式嚴格驗證後自動接受的加開日 |
| `state/pending-notices.json` | 尚未批准的官方公告 |
| `docs/aoer-schedule.json` | 跨平台共用資料 API（公開） |
| `docs/feed-status.json` | 版本及最後發布時間 |
| `scripts/` | 驗證、監控、發布與 Issue 提醒程式 |
| `tests/` | 官方公告格式 fixture 與錯誤阻擋測試 |

## 7. 本機自我測試（可略過）

在專案根目錄執行：

```bash
python -m unittest discover -s tests -v
python scripts/publish.py
```

本地程式若無法連上官方網站，`monitor.py` 會失敗並保留現有資料；這是保護措施，不會清除先前通過驗證的日曆。
