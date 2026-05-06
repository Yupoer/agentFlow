# hermes-workflow

Hermes workflow MVP runtime：把 `啟用 workflow：...` 類訊息轉成可驗證、可保存、可 resume 的多階段工作流輸出。

## 5-stage 架構

```text
Stage 1  Request Normalizer  → normalized_request
Stage 2  Planner             → plan
Stage 3  Executor            → executor_output / executor_results
Stage 4  Verifier            → verifier_output
Stage 5  Writer / Assembler  → final_output
```

- Stage 1/2：可透過 Hermes `delegate_task` 執行；standalone 測試可用 `llm` callable fallback。
- Stage 3：只使用 Hermes `delegate_task`，不 fallback 到 LLM。
- Stage 4：deterministic 驗收 executor results，不呼叫 LLM / delegate_task。
- Stage 5：deterministic 組裝 final_output，不呼叫 LLM / delegate_task。

## standalone vs delegated

```text
standalone
- 沒有 live Hermes parent_agent context，或沒有 delegate_task。
- Stage 3 preflight 會標示：
  execution_mode = "standalone"
  stage3_available = false
  partial_reason = "delegate_task unavailable; Stage 3 requires Hermes delegate_task"
- 適合 static / fake delegate / CLI 開發驗證。

delegated
- 同時有 parent_agent 與 delegate_task。
- Stage 3 可以用 Hermes subagent 執行 plan steps。
- 適合最小 live smoke 或實際 Hermes workflow 執行。
```

## 啟用 workflow

```bash
python runtime/orchestrator.py "啟用 workflow：建立測試計畫"
```

Python：

```python
from runtime.orchestrator import WorkflowOrchestrator

result = WorkflowOrchestrator(llm=my_llm_callable).run("啟用 workflow：建立測試計畫")
```

支援的 activation prefix 以 `runtime/activation.py` 為準，常用：

```text
啟用 workflow：
啟用 workflow:
workflow：
workflow:
```

## Smoke test

低成本 static / fake 驗證：

```bash
python -m compileall -q runtime
pytest tests/ -q
```

最小 CLI smoke：

```bash
python runtime/orchestrator.py "啟用 workflow：建立最小測試計畫"
```

live Hermes delegation smoke 只在有 live `parent_agent` context 且確實需要驗 Stage 3 delegate path 時跑。

## Resume / continue

從最新 JSONL state resume：

```bash
python runtime/orchestrator.py --resume
```

從指定 workflow_id resume：

```bash
python runtime/orchestrator.py --resume <workflow_id>
```

Python：

```python
from runtime.orchestrator import WorkflowOrchestrator

result = WorkflowOrchestrator(llm=my_llm_callable).resume(workflow_id="optional-id")
```

Resume 規則：

```text
已有 normalized_request、沒有 plan          → 從 Stage 2 繼續
已有 plan、沒有 executor_output             → 從 Stage 3 繼續
已有 executor_output、沒有 verifier_output  → 從 Stage 4 繼續
已有 verifier_output、沒有 final_output      → 從 Stage 5 繼續
已有 final_output                            → 不重跑，直接回傳 final_output
```

## quota exceeded / blocked / partial

```text
quota exceeded / HTTP 429
- workflow status = blocked
- blocked_reason = "LLM quota exceeded, workflow paused"
- 立即停止後續 step
- 寫入 JSONL 保留目前 workflow_state
- 之後可用 --resume 嘗試從可恢復 stage 繼續

blocked
- 表示 workflow 暫停或前置條件不足。
- final_output 會保留 blockers / errors。

partial
- 表示部分 step failed 或 skipped，但 workflow 有可用的部分結果。
- Stage 4 / Stage 5 會反映 verdicts 與 final steps。
```

## 目錄結構簡表

```text
runtime/                  workflow runtime：activation、orchestrator、executor、verifier、writer、state_store、validator
schemas/                  Stage 1~5 JSON schema
prompts/                  Stage 1/2 prompt templates
kernel/                   routing rules 等核心設定
skills/hermes-workflow/   project-level Hermes skill 草稿與使用說明
tests/                    pytest 測試：stage、orchestrator、resume、preflight
manifest.json             stage / compact_output manifest
.hermes-workflow-state.jsonl  預設 workflow state JSONL（執行後產生）
```

## Project-level skill 載入確認

目前 `skills/hermes-workflow/SKILL.md` 放在專案根目錄底下，格式上是 project-level skill；但 Hermes 是否會掃描它，取決於 Hermes skills 搜尋路徑設定。

Hermes 目前會掃描：

```text
1. local skills：~/.hermes/skills/
2. external skill dirs：~/.hermes/config.yaml 裡的 skills.external_dirs
```

所以結論是：

```text
只放在 /home/qza/hermes-workflow/skills/hermes-workflow/SKILL.md
不保證會被目前 Hermes session 自動掃描。

若 /home/qza/hermes-workflow/skills 被加入 skills.external_dirs，
或 skill 被安裝 / 複製到 ~/.hermes/skills/，才會進入 Hermes skill index。
```

目前本機 config 檢查結果：

```text
skills.external_dirs = []
```

也就是說，此刻不能只靠「放在專案 skills/ 底下」確認它已被載入。

確認載入步驟：

```bash
# 1. 確認檔案存在且 frontmatter 有 name/description
python - <<'PY'
from pathlib import Path
p = Path('skills/hermes-workflow/SKILL.md')
print(p.exists())
print(p.read_text(encoding='utf-8').split('---', 2)[1])
PY

# 2. 將 project skills 目錄加入 external_dirs，或安裝/複製到 ~/.hermes/skills/
hermes config set skills.external_dirs '["/home/qza/hermes-workflow/skills"]'

# 3. 重啟 Hermes session / gateway，讓 skill index 重新建立
# CLI：開新 hermes session
# Gateway：/restart 或重啟 gateway

# 4. 查詢是否出現在 skill list
hermes skills list | grep hermes-workflow

# 5. 明確載入測試
hermes -s hermes-workflow chat -q "只回覆 hermes-workflow skill loaded"
# 或在互動 session：/skill hermes-workflow
```

注意：目前 session 的 skill 列表通常是啟動時快取；新增或修改 skill 後，要開新 session 或重啟 gateway 才能確認實際載入。
