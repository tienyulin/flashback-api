---
type: api
source_app: flashback-api
tags: [oracle, recovery, dba]
---

# flashback-api — Oracle Flashback Recovery API

> 👉 想看這個服務**實際怎麼運作（含真實紀錄）**：[docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)。

把 Oracle DBA 的 flashback 復原操作（誤改回溯、誤刪救回、還原點管理、整庫回溯）
包成 REST API。來源文件鏈：

```
sop/oracle-flashback-recovery.md（DBA 操作手冊）
  → specs/oracle-flashback-recovery-api.spec.md（API 規格，Part A 白話摘要 + Part B 實作規格）
    → 本服務（照 spec 實作，47 個測試對應 spec 驗收準則）
```

## 快速啟動（mock 模式，不需要真 Oracle）

```bash
cd flashback-api
pip install -r requirements.txt
MOCK_ORACLE=true python main.py        # http://localhost:8003
```

或 docker compose（repo 根目錄）：

```bash
docker compose --profile flashback up -d
```

Mock 內建一套確定性測試資料：一個還原點 `BEFORE_UPGRADE_20260611`、
`SCOTT.EMP`/`SCOTT.DEPT` 兩張表、回收筒裡一張被刪的 `SCOTT.BONUS`。

## 端點總覽

| 端點 | 做什麼 | 風險 |
|------|--------|------|
| `GET /health` | 健康檢查 | 🟢 |
| `GET /flashback/status` | 能不能做 flashback（保護模式/空間/可回溯範圍） | 🟢 |
| `GET /restore_points`・`POST /restore_points`・`DELETE /restore_points/{name}` | 還原點查/建/刪 | 🟢/🟡 |
| `GET /recyclebin` | 回收筒內容 | 🟢 |
| `POST /flashback/table` | 單表回溯到過去時間點 | 🟡 |
| `POST /flashback/drop` | 從回收筒救回誤刪的表 | 🟡 |
| `POST /flashback/database` → `POST /flashback/database/finalize` | 整庫回溯（兩段式） | 🔴 |
| `GET /audit/log` | 操作審計 | 🟢 |

規則：🟡/🔴 操作 **`dry_run` 預設 `true`**（只檢查不執行）；🔴 操作真執行還需
`confirm: "I-UNDERSTAND-DATA-LOSS"` ＋ `approval_id`（審批單號），缺一回 428。
所有 🟡/🔴 請求（含試算、被拒）都寫入 audit。

## 實際走一遍

### 1. 救回誤刪的表

```bash
# 看回收筒裡有什麼
curl -s localhost:8003/recyclebin | python3 -m json.tool

# 先試算（dry_run 預設 true）：會還原哪個版本？
curl -s -X POST localhost:8003/flashback/drop \
  -H 'Content-Type: application/json' \
  -d '{"owner": "SCOTT", "table_name": "BONUS"}'

# 確認後真執行
curl -s -X POST localhost:8003/flashback/drop \
  -H 'Content-Type: application/json' \
  -d '{"owner": "SCOTT", "table_name": "BONUS", "dry_run": false}'
```

### 2. 單表回溯（誤改資料）

```bash
curl -s -X POST localhost:8003/flashback/table \
  -H 'Content-Type: application/json' \
  -d '{"owner": "SCOTT", "table_name": "EMP",
       "target": {"timestamp": "2026-06-11T09:00:10"}, "dry_run": false}'
# 回應含 prior_scn（回退碼）：倒錯了用它再倒回來
```

### 3. 整庫回溯（兩段式，不可逆）

```bash
# 試算：每項前置檢查的結果＋會用掉多少 flashback log
curl -s -X POST localhost:8003/flashback/database \
  -H 'Content-Type: application/json' \
  -d '{"target": {"restore_point": "BEFORE_UPGRADE_20260611"}}'

# 真執行（需要確認字串＋審批單號）→ 結束停在唯讀，等人工驗證
curl -s -X POST localhost:8003/flashback/database \
  -H 'Content-Type: application/json' \
  -d '{"target": {"restore_point": "BEFORE_UPGRADE_20260611"}, "dry_run": false,
       "confirm": "I-UNDERSTAND-DATA-LOSS", "approval_id": "CHG-2026-0612-001"}'

# 人工驗證資料無誤後，最後定案（OPEN RESETLOGS）
curl -s -X POST localhost:8003/flashback/database/finalize \
  -H 'Content-Type: application/json' \
  -d '{"dry_run": false, "confirm": "I-UNDERSTAND-DATA-LOSS",
       "approval_id": "CHG-2026-0612-001"}'

# 全程紀錄
curl -s localhost:8003/audit/log | python3 -m json.tool
```

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `MOCK_ORACLE` | `false` | `true` = in-memory mock（測試/demo） |
| `ORACLE_DSN` / `ORACLE_USER` / `ORACLE_PASSWORD` | — | real 模式必填（需 SYSDBA），缺 DSN 啟動即失敗 |
| `FLASHBACK_API_KEY` | 空 | 設定後所有 🟡/🔴 端點需 `X-API-Key` header；空 = dev 模式不驗 |
| `FRA_USAGE_THRESHOLD` | `85` | FRA 空間使用率門檻（%） |

## Dev Container

本 repo 附 [`.devcontainer/`](.devcontainer/)。VS Code / Cursor **Reopen in
Container** 即建立隔離的 Python 環境（不影響主機、不與其他服務衝突），原始碼
即時掛載於 `/app`。容器內：`python -m pytest`、`python main.py`（:8003）。

## 測試

```bash
cd flashback-api && python -m pytest -q     # 47 passed
```

測試名對應 spec 驗收準則編號（如 `test_ac_ft_2_timestamp_resolves_to_scn`
↔ spec Part B §3 AC-FT-2）。

## 推進 llm wiki

這份 README 本身就是送進 llm wiki 的文檔——它有 H1 與端點清單，wiki-processor
直接萃取得到。模擬應用端的 GitLab CI push（repo 根目錄執行）：

```bash
docker compose up -d minio wiki-processor mcp-server   # mock 全鏈，無需 key
bash examples/simulate-app-push.sh                     # 拿本 README POST /process
curl -s 'localhost:8002/search_apis?query=flashback' | python3 -m json.tool
```

完整 pipeline（SOP → spec → API → README → wiki → 查詢）與實跑輸出見
[docs/guides/sop-to-wiki-pipeline.md](../docs/guides/sop-to-wiki-pipeline.md)。

## 注意

- `RealOracleRepository` 是骨架（介面 docstring 寫明每個方法對應的 SQL）——
  本 repo 沒有真 Oracle 可接，接真環境時照 docstring 實作即可
- 整庫回溯後資料庫停在 `FLASHBACKED`（唯讀驗證窗），不 finalize 就不會 RESETLOGS
