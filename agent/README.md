# EZStore Quotation Management Agent (`quotation_agent`)

EZStore 報價單管理智慧助手，基於 Python 3.12、**Google Agent Development Kit (ADK) 2.10+** 的 **Graph Workflow API** 與 **Gemini 3.8 Flash** 構建，透過 MCP Server（Streamable HTTP）與後端 REST API 進行資料互動，並直接串接 EZStore 前端 Chat UI。

---

## 1. Graph Workflow 圖架構設計

Agent 採用 ADK 的 Graph Workflow API（`google.adk.workflow.Workflow`）進行確定性狀態圖編排。
**全圖僅有意圖分類節點（`classify_intent`）呼叫 LLM**，後續之路由、追問、拒答、參數校驗與 MCP 工具呼叫均由純 Python 程式邏輯嚴格控制。

### 節點流程圖

```
                 START
                   │
                   ▼
            classify_intent (LLM: Gemini 3.8 Flash + Pydantic Schema)
                   │
                   ▼
              route_intent (純 Python 確定性路由與狀態分析)
        ┌──────────┼───────────────┬────────────────────────┐
        ▼          ▼               ▼                        ▼
     refuse     clarify      6 個 MCP 操作節點           未知例外
    (離題拒答) (缺資料追問)  (get, duplicate, etc.)      (防禦處理)
        └──────────┼───────────────┴────────────────────────┘
                   │
                   ▼
                respond (回傳 types.Content，附帶純文字系統連結)
                   │
                   ▼
                  END
```

### 核心節點說明

1. **`classify_intent`**（`LlmAgent`）：
   - 使用 Gemini 3.8 Flash，配合 `IntentClassification`（Pydantic Schema）進行結構化意圖提取（包含 `action`、`quotation_number`、`customer_name`、`pricing_factor`、`target_total_price`）。
2. **`route_intent`**（Python 函式）：
   - **離題防護（Guardrails）**：若判定為非報價單操作（如天氣、閒聊、客戶新增），由程式強制導向 `refuse_node`，不呼叫任何工具。
   - **缺資料主動追問（Clarify）**：若缺少必要參數（如報價單號、修改因子），自動暫存狀態並導向 `clarify_node` 進行追問。
   - **多輪接續**：使用者下一輪補上資料時，結合 session 歷史與狀態自動恢復原本意圖並繼續執行。
3. **MCP 操作節點（`node_*`）**：
   - 各節點透過 `call_mcp_tool` 呼叫對應的 MCP 工具（`get_quotation`、`list_customer_quotations`、`duplicate_quotation`、`update_pricing_factor`、`adjust_total_price`、`convert_to_order`）。
   - 修改操作遵循 **Copy-On-Write** 原則，保留原始報價單完整未改動。
4. **`respond`**（回覆節點）：
   - 將工具產生的結果封裝成 `types.Content(role="model", parts=[types.Part.from_text(...)])`，回覆中嚴格維持純文字系統連結（`http://localhost:3000/...`），禁止 Markdown 語法，供前端 SSE 解析顯示。

---

## 2. 如何新增一個報價單操作（Step-by-Step）

若未來需要為 Agent 擴充新的操作（例如：`cancel_quotation` 廢棄報價單），請依照以下 6 個步驟進行修改：

### 步驟 1：在 `IntentClassification` 加入新意圖與欄位

開啟 [`agent/quotation_agent/agent.py`](agent/quotation_agent/agent.py)，在 `IntentClassification` 的 `action` 新增列舉值，並視需要新增欄位：

```python
class IntentClassification(BaseModel):
    action: Literal[
        "get_quotation",
        # ... 原有操作 ...
        "cancel_quotation",  # 新增操作
        "off_topic",
        "supply_info",
        "unknown",
    ]
    cancel_reason: Optional[str] = Field(default=None, description="取消報價單原因")
```

### 步驟 2：更新 `classify_intent` 的提示詞與分類規則

在 `classify_intent` 的 `instruction` 中加入該操作的分類描述與範例：

```python
    instruction="""...
意圖分類規則：
...
7. 廢棄/取消報價單：action="cancel_quotation"，提取 quotation_number 與 cancel_reason。
..."""
```

### 步驟 3：在 `route_intent` 加入參數驗證與路由邏輯

在 `route_intent` 中處理缺少參數時的追問，以及參數完整時的派送：

```python
    elif action == "cancel_quotation":
        if not quotation_number:
            return Event(
                output="請提供您要取消的報價單編號（例如 QT-20260330-001）？",
                route="clarify",
                state={"pending_action": action, "pending_params": {}},
            )
```

### 步驟 4：定義新的 MCP 工具呼叫節點

定義該操作對應的 Python 異步函式：

```python
async def node_cancel_quotation(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "cancel_quotation",
        {
            "quotation_number": node_input["quotation_number"],
            "reason": node_input.get("cancel_reason", ""),
        },
    )
```

### 步驟 5：註冊節點與更新 Workflow 圖（`edges`）

在 `edges` 中將新節點加入 `route_intent` 字典映射，並連向 `respond`：

```python
    (
        route_intent,
        {
            "refuse": refuse_node,
            "clarify": clarify_node,
            # ... 原有節點 ...
            "cancel_quotation": node_cancel_quotation,  # 新增映射
        },
    ),
    # ...
    (node_cancel_quotation, respond),  # 連向回覆節點
```

### 步驟 6：新增評估測試並驗證

在 [`agent/tests/eval/datasets/quotation-actions.json`](tests/eval/datasets/quotation-actions.json) 加入該案例，並執行驗收：

```bash
uv run agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json
```

---

## 3. 本機開發與指令速查

```bash
# 安裝依賴
uv sync

# 本機互動式測試（Web Playground）
uv run agents-cli playground --port 8085

# 單次命令列執行
uv run agents-cli run "我要查詢報價單，報價單編號：QT-20260330-001"

# 執行單元與整合測試
uv run pytest tests/unit -q
uv run pytest tests/integration -q

# 執行評估測試
uv run agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json
uv run agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json
```
