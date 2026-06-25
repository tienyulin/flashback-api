# flashback-api 實際怎麼運作（含真實紀錄）

> 這是一個**範例上游 app**：把 Oracle DBA 的 flashback 救援操作（誤刪救回、誤改回溯、整庫回溯）
> 包成 REST API。它有兩個用途：(1) 本身是個有風險分級的好範例服務；(2) 它的 README 就是
> 「推進 wiki 的文件」，示範 app 怎麼進到 llm-wiki。下面用 **mock 模式**（`MOCK_ORACLE=true`，
> 不需真 Oracle）現場跑的真實輸出，拆開它的「風險閘門」設計。擷取 2026-06-25。

> **名詞**：**flashback** Oracle 的回溯/救援功能；**dry_run** 只試算不真執行；**回收筒
> （recyclebin）** 被 drop 的表暫存區；**restore point（還原點）** 資料庫的時間書籤；
> **428** HTTP 狀態碼「需要前置條件」（這裡＝缺確認/審批）。

## 啟動（mock，免真 Oracle）
```bash
docker compose up -d --build      # http://localhost:8003
curl -s localhost:8003/health     # {"status":"ok"}
```
Mock 內建確定性測試資料：一個還原點、`SCOTT.EMP`/`SCOTT.DEPT` 兩張表、回收筒裡一張被刪的
`SCOTT.BONUS`。

---

## 核心設計：風險分級 + 閘門（真實紀錄）

每個會改資料的操作都分級：🟢 唯讀、🟡 可逆、🔴 不可逆。規則：
- 🟡/🔴 操作 **`dry_run` 預設 `true`** —— 不講就只試算、不真做。
- 🔴 操作真執行還要 `confirm: "I-UNDERSTAND-DATA-LOSS"` ＋ `approval_id`（審批單號），缺一回 **428**。
- 所有 🟡/🔴 請求（含試算、被拒）都寫 audit。

### 1. 看回收筒裡有什麼（🟢）
```bash
curl -s localhost:8003/recyclebin
```
真輸出：
```json
{"entries":[{"owner":"SCOTT","object_name":"BIN$jx8kQ3vT==$0",
 "original_name":"BONUS","droptime":"2026-06-12T08:30:00"}]}
```

### 2. 試算救回誤刪的表（🟡，dry_run 預設 true）
```bash
curl -s -X POST localhost:8003/flashback/drop -H 'Content-Type: application/json' \
  -d '{"owner":"SCOTT","table_name":"BONUS"}'
```
真輸出（**只試算、沒真做**）：
```json
{"dry_run": true,
 "would_restore": {"owner":"SCOTT","object_name":"BIN$jx8kQ3vT==$0",
                   "original_name":"BONUS","droptime":"2026-06-12T08:30:00"},
 "restored_as": "BONUS"}
```
**這代表什麼：** 先告訴你「會還原哪個版本、變成什麼名字」，你看過再決定。要真做才加 `"dry_run":false`。

### 3. 不可逆操作缺確認 → 擋下來（🔴）
整庫回溯真執行，但沒給 `confirm` + `approval_id`：
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST localhost:8003/flashback/database \
  -H 'Content-Type: application/json' -d '{"target":{"restore_point":"BEFORE_UPGRADE_20260611"},"dry_run":false}'
```
真輸出：`HTTP 428`
**這代表什麼：** 危險操作預設擋住。要真跑必須帶確認字串 + 審批單號，缺一不可 —— 防手滑。
**這就是「安全閘門」**：dry_run 預設、🔴 雙重確認、全程 audit。

---

## 它怎麼進到 llm-wiki（跨服務）
這份服務的 README 有 H1 + endpoint 清單，**本身就是餵給 wiki-processor 的文件**。模擬 app 端
CI push（平台 repo 根目錄）：
```bash
docker compose up -d minio wiki-processor mcp-server   # mock 全鏈，免 key
bash examples/simulate-app-push.sh                     # 拿 README POST /process
curl -s 'localhost:8002/search_apis?query=flashback'   # 在 wiki 裡查到 flashback 的 API
```

更多（完整端點 + dry-run/confirm 流程）見 [README.md](../README.md)；
從 SOP → spec → API 的來源鏈見平台 `docs/guides/sop-to-wiki-pipeline.md`。
</content>
