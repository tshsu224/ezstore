# EZStore 雙 Agent 協同架構規格書（A2A Protocol & OKF Knowledge Fabric）

本文件完整記述 EZStore 多 Agent 協同系統架構，包含：
1. **報價單管理 Agent (`quotation_agent`)**：負責客戶銷售端之報價單查詢、複製、調價、轉訂單。
2. **智慧庫存與補貨 Agent (`inventory_agent`)**：負責倉儲水位監控、安全存量評估與採購補貨建議。
3. **A2A (Agent-to-Agent) 通訊協定**：兩大獨立 Agent 間之跨領域自治協同機制。
4. **OKF (Open Knowledge Fabric) 知識庫**：為 Agent 提供企業採購規範、起訂量 (MOQ)、交期與金額審批層級之結構化知識支援。

---

## 1. 系統整體架構全景圖

```mermaid
flowchart TB
    subgraph Client_Layer [使用者互動層]
        WebUI["React 19 Chat UI\n(http://localhost:3000/agent)"]
        CLI["CLI / Python 驗收終端\n(scripts/verify_spec42.py)"]
    end

    subgraph Agent_Layer [ADK Multi-Agent 核心層]
        direction TB
        subgraph Agent_A [Quotation Agent 銷售端]
            QA_WF["Graph Workflow\n(quotation_agent)"]
            QA_LLM["LLM 意圖分類\n(Gemini 3.8 Flash)"]
            QA_Route["確定性路由\n(Python Logic)"]
            QA_A2A_Client["A2A Client 模組"]
        end

        subgraph Agent_B [Inventory Agent 倉儲端]
            IA_WF["Graph Workflow\n(inventory_agent)"]
            IA_LLM["LLM 意圖分類\n(Gemini 3.8 Flash)"]
            IA_Route["確定性路由\n(Python Logic)"]
            IA_A2A_Server["A2A RPC Server\n(/a2a/inventory_agent)"]
        end

        QA_A2A_Client <== "A2A Protocol (JSON-RPC 2.0)\n跨 Agent 自治協同" ==> IA_A2A_Server
    end

    subgraph Knowledge_Layer [OKF 知識庫層]
        OKF_Engine["OKF 知識引擎\n(OKFKnowledgeBase)"]
        OKF_Suppliers["供應商規範目錄\n(supplier_directory.json)"]
        OKF_Safety["安全庫存門檻與公式\n(safety_stock_policy.json)"]
        OKF_Approval["採購簽核層級規範\n(approval_governance.json)"]
        OKF_Engine --- OKF_Suppliers
        OKF_Engine --- OKF_Safety
        OKF_Engine --- OKF_Approval
    end

    subgraph Tool_and_Service_Layer [工具與服務層]
        MCP["MCP Server (Streamable HTTP :8000)\n6 個報價單操作工具"]
        InvTools["庫存管理工具模組\n(inventory_tools.py)"]
    end

    subgraph Infrastructure_Layer [後端與資料儲存層]
        BackendAPI["EZStore REST API (Go Gin :8080)\n/api/v1/quotations, /products, /orders"]
        DB[(PostgreSQL 16\nezstore 資料庫)]
        BackendAPI --- DB
    end

    %% 連線關係
    WebUI --> QA_WF
    CLI --> QA_WF
    CLI --> IA_WF

    QA_WF --> QA_LLM
    QA_LLM --> QA_Route
    QA_Route --> MCP
    QA_Route --> QA_A2A_Client

    IA_WF --> IA_LLM
    IA_LLM --> IA_Route
    IA_Route --> InvTools
    IA_Route --> OKF_Engine

    MCP --> BackendAPI
    InvTools --> BackendAPI
```

---

## 2. A2A (Agent-to-Agent) 協同通訊架構

A2A 協定採用標準 **JSON-RPC 2.0** 與 **Agent Card** 發現機制，確保兩個 Agent 各自擁有清晰的領域邊界（Domain Separation），同時在需要跨領域業務時無縫協作。

### A2A 跨 Agent 循序圖（銷售報價 ──► 倉儲庫存與交期）

```mermaid
sequenceDiagram
    autonumber
    actor User as 使用者
    participant QA as Quotation Agent (銷售端)
    participant A2A as A2A 通訊管道 (JSON-RPC)
    participant IA as Inventory Agent (倉儲端)
    participant OKF as OKF 知識庫
    participant API as 後端 REST API (Products)

    User->>QA: 「查詢 A4影印紙 庫存與補貨建議」
    QA->>QA: classify_intent 識別為 check_inventory_a2a
    QA->>A2A: 發起 A2A 呼叫: agent.execute("查詢 A4影印紙 庫存與補貨建議")
    A2A->>IA: 路由至 Inventory Agent 接收端點
    
    IA->>API: query_product_stock("A4") 取得即時庫存 (2000 箱)
    IA->>OKF: 檢索安全庫存規範、供應商交期 (3天) 與起訂量 MOQ (20箱)
    OKF-->>IA: 回傳政策門檻與簽核規範 (TIER_1_AUTO)
    
    IA->>IA: 結合現存與 OKF 政策生成合規報告
    IA-->>A2A: 回覆標準 A2A 結構化文字與系統純文字連結
    A2A-->>QA: 跨 Agent 訊息傳遞完成
    
    QA->>QA: respond 封裝 A2A 協同報告
    QA-->>User: 回覆最終報告（含庫存量、交期預估、OKF 依據與純文字連結）
```

---

## 3. OKF (Open Knowledge Fabric) 知識庫設計

OKF 知識庫將原本寫死在業務代碼中的「商業規則」抽離為結構化的知識實體，由 `OKFKnowledgeBase` 引擎提供推論與合規校驗：

```
agent/inventory_agent/okf/
├── kb.py                    # OKF 知識檢索與推論核心引擎
├── supplier_directory.json  # 供應商名錄、前置交期 (Lead Time)、起訂量 (MOQ)、批次折扣
├── safety_stock_policy.json # 各品類最低安全存量標準、斷貨風險等級 (Risk Level)
└── approval_governance.json # 採購金額審批層級 (TIER_1_AUTO, TIER_2_MANAGER, TIER_3_EXECUTIVE)
```

### OKF 補貨決策推論邏輯矩陣

| 評估維度 | 輸入參數 | OKF 知識規則處理 | 輸出結果 |
|---|---|---|---|
| **最低安全存量** | 商品類別: 辦公用紙 | `category_policies["辦公用紙"].threshold = 15` | 現有庫存 < 15 時標記為 HIGH 風險警示 |
| **起訂量規整 (MOQ)** | 原始需求量: 8 箱 | 查詢 `supplier_directory`: 大同紙業 MOQ = 20 箱 | 自動向上規整為 20 箱（`moq_applied=True`） |
| **批次階梯折扣** | 採購數量: 50 箱 | 命中 `volume_discounts` (≥50 箱折 5%) | 自動套用 5% 成本折減並計算總額 |
| **簽核治理階層** | 總採購金額: NT$ 7,600 | 命中 `TIER_1_AUTO` (≤ 10,000 元) | 判定為自動放行，不需人工主管簽核 |
| **高額簽核治理** | 總採購金額: NT$ 32,000 | 命中 `TIER_2_MANAGER` (> 10,000 元) | 標記「需採購經理線上簽核後方可下單」 |

---

## 4. 兩大 Agent 之 Graph Workflow 狀態圖

### 1. Quotation Agent 狀態流程圖

```mermaid
stateDiagram-v2
    [*] --> START
    START --> classify_intent: 使用者訊息
    classify_intent --> route_intent: IntentClassification Schema
    
    route_intent --> refuse_node: 離題需求 (off_topic)
    route_intent --> clarify_node: 缺少必要參數 (clarify)
    route_intent --> node_get_quotation: 查詢單號
    route_intent --> node_duplicate: 複製報價單
    route_intent --> node_update_factor: 修改報價因子
    route_intent --> node_adjust_price: 二分法調總價
    route_intent --> node_convert_order: 轉訂單
    route_intent --> node_check_inventory_a2a: 跨 Agent 查庫存 (A2A)

    node_get_quotation --> respond
    node_duplicate --> respond
    node_update_factor --> respond
    node_adjust_price --> respond
    node_convert_order --> respond
    node_check_inventory_a2a --> respond
    refuse_node --> respond
    clarify_node --> respond

    respond --> [*]: 回傳 types.Content (含純文字連結)
```

### 2. Inventory Agent 狀態流程圖

```mermaid
stateDiagram-v2
    [*] --> START
    START --> classify_intent: 使用者訊息 / A2A 請求
    classify_intent --> route_intent: InventoryIntent Schema
    
    route_intent --> refuse_node: 離題需求 (off_topic)
    route_intent --> clarify_node: 缺少商品名稱 (clarify)
    route_intent --> node_check_stock: 查詢品項現況
    route_intent --> node_list_low_stock: 列出不足水位清單
    route_intent --> node_replenish_advice: 結合 OKF 知識庫推論補貨

    node_check_stock --> respond
    node_list_low_stock --> respond
    node_replenish_advice --> respond
    refuse_node --> respond
    clarify_node --> respond

    respond --> [*]: 回傳 types.Content (含純文字連結)
```

---

## 5. 驗證與展示執行指令

### 執行 A2A 跨 Agent 協同與 OKF 知識推論展示
```bash
uv --directory agent run python ../scripts/demo_a2a_and_inventory.py
```

### 執行 Inventory Agent 單元測試（涵蓋 OKF 規則與 MOQ 斷言）
```bash
uv --directory agent run pytest inventory_agent/tests/test_inventory_agent.py -v
```

### 啟動 Inventory Agent 本機獨立服務（支援 A2A 與 REST API）
```bash
uv --directory agent run python -m inventory_agent.fast_api_app
```

