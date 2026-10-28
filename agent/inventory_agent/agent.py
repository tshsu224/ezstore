# ruff: noqa
import os
import re
from typing import Any, Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.agents.context import Context
from google.adk.models import Gemini
from google.adk.workflow import Workflow
from google.genai import types

from .tools.inventory_tools import (
    generate_replenishment_advice,
    query_low_stock_list,
    query_product_stock,
)

MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")


# ---------------------------------------------------------------------------
# 1. 意圖分類結構（Pydantic Output Schema）
# ---------------------------------------------------------------------------
class InventoryIntent(BaseModel):
    action: Literal[
        "check_stock",
        "list_low_stock",
        "replenish_advice",
        "off_topic",
        "supply_info",
        "unknown",
    ] = Field(
        description="庫存管理與採購補貨操作意圖。若為非庫存補貨相關需求（如天氣、客戶CRUD、閒聊）則為 off_topic。"
    )
    product_identifier: Optional[str] = Field(
        default=None,
        description="商品名稱或商品編號（例如 A4影印紙、SP-001、伺服器等）。",
    )
    target_quantity: Optional[int] = Field(
        default=None,
        description="期望補貨或查詢之數量（整數）。",
    )
    threshold: Optional[int] = Field(
        default=None,
        description="低庫存查詢之門檻數量（整數）。",
    )


classify_intent = LlmAgent(
    name="classify_intent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""你是一個專業的企業倉儲與庫存管理助理（Inventory Agent）。
請根據使用者的輸入，嚴格分析並提取以下欄位：

意圖分類規則：
1. 查詢特定商品庫存與水位：action="check_stock"，提取 product_identifier（例如 A4影印紙、SP-001、印表機）。
2. 列出低庫存或警示商品：action="list_low_stock"，若有提到數量門檻則提取 threshold。
3. 產生補貨建議（結合 OKF 採購政策、交期、起訂量 MOQ 與主管簽核層級）：action="replenish_advice"，提取 product_identifier 與 target_quantity。
4. 使用者補充資料（如只說了商品名稱或數字）：action="supply_info"。
5. 離題需求（天氣、日常閒聊、客戶新增/修改、非庫存的雜項）：action="off_topic"。
6. 無法識別之需求：action="unknown"。
""",
    output_schema=InventoryIntent,
)


# ---------------------------------------------------------------------------
# 2. 路由節點（純 Python 確定性控制）
# ---------------------------------------------------------------------------
def route_intent(ctx: Context, node_input: Any) -> Event:
    if isinstance(node_input, dict):
        intent = InventoryIntent(**node_input)
    elif isinstance(node_input, InventoryIntent):
        intent = node_input
    else:
        intent = InventoryIntent(action="unknown")

    pending_action = ctx.state.get("pending_action")
    action = intent.action
    product_identifier = intent.product_identifier or ctx.state.get("pending_product")
    target_qty = intent.target_quantity
    threshold = intent.threshold

    if (action in ("supply_info", "unknown") or action is None) and pending_action:
        action = pending_action

    # 若仍未定但有商品名稱，預設為查詢庫存
    if (action in ("supply_info", "unknown") or action is None) and product_identifier:
        action = "check_stock"

    # 離題防護（Guardrails）
    if action in ("off_topic", "unknown"):
        ctx.state["pending_action"] = None
        ctx.state["pending_product"] = None
        return Event(
            output="抱歉，我是 EZStore 智慧庫存與採購補貨 Agent，僅能協助處理庫存查詢、低庫存預警與基於 OKF 規範的採購補貨建議。無法處理其他離題需求。",
            route="refuse",
            state={"pending_action": None, "pending_product": None},
        )

    # 缺資料追問
    if action in ("check_stock", "replenish_advice") and not product_identifier:
        return Event(
            output="請提供您要查詢或補貨的商品名稱或編號（例如：A4影印紙 80磅 或 SP-001）？",
            route="clarify",
            state={"pending_action": action, "pending_product": None},
        )

    args = {
        "product_identifier": product_identifier,
        "target_quantity": target_qty,
        "threshold": threshold,
    }
    return Event(
        output=args,
        route=action,
        state={"pending_action": None, "pending_product": None},
    )


# ---------------------------------------------------------------------------
# 3. 追問與拒答節點
# ---------------------------------------------------------------------------
def clarify_node(node_input: Any) -> str:
    return str(node_input)


def refuse_node(node_input: Any) -> str:
    return str(node_input)


# ---------------------------------------------------------------------------
# 4. 操作節點（串接後端 API 與 OKF 知識庫）
# ---------------------------------------------------------------------------
def node_check_stock(node_input: dict[str, Any]) -> str:
    info = query_product_stock(node_input["product_identifier"])
    if "error" in info:
        return f"查詢失敗：{info['error']}"

    return (
        f"商品庫存資訊：\n"
        f"- 商品編號: {info['product_number']}\n"
        f"- 商品名稱: {info['name']}\n"
        f"- 目前現有庫存: {info['inventory']} 件\n"
        f"- OKF 最低安全存量: {info['minimum_safety_stock']} 件\n"
        f"- 庫存水位狀態: {info['status']}（風險等級：{info['stockout_risk']}）\n"
        f"- 參考成本: NT$ {info['cost']:,} | 牌價: NT$ {info['list_price']:,}\n"
        f"- 配合供應商: {info['supplier'] or '未設定'}\n"
        f"- 系統連結: {info['system_link']}"
    )


def node_list_low_stock(node_input: dict[str, Any]) -> str:
    threshold = node_input.get("threshold")
    low_list = query_low_stock_list(threshold)
    if not low_list:
        return "目前所有商品庫存均高於安全水位，暫無需要緊急補貨之品項。"

    lines = [f"⚠️ 目前低於安全水位之商品清單（共 {len(low_list)} 項）："]
    for idx, item in enumerate(low_list, 1):
        lines.append(
            f"{idx}. {item['name']} ({item['product_number']}) — "
            f"現存: {item['current_inventory']} (門檻: {item['safety_threshold']}) | 連結: {item['system_link']}"
        )
    return "\n".join(lines)


def node_replenish_advice(node_input: dict[str, Any]) -> str:
    plan = generate_replenishment_advice(
        product_identifier=node_input["product_identifier"],
        target_qty=node_input.get("target_quantity"),
    )
    if "error" in plan:
        return f"無法產生補貨計畫：{plan['error']}"

    notes_str = "\n".join([f"  • {n}" for n in plan.get("policy_notes", [])])
    approval_warn = "⚠️ 本筆採購金額超過門檻，需提交主管簽核。" if plan["requires_human_approval"] else "✅ 金額在授權額度內，可自動放行採購。"

    return (
        f"📋 智慧補貨建議報告（依據 OKF 企業採購與安全庫存知識庫）：\n"
        f"- 補貨品項: {plan['product_name']} ({plan['product_number']})\n"
        f"- 目前庫存 / 安全門檻: {plan['current_inventory']} / {plan['safety_stock_threshold']} {plan['moq_unit']}\n"
        f"- 建議採購數量: {plan['suggested_order_qty']} {plan['moq_unit']}"
        + (f"（已遵循 MOQ 起訂量規整）\n" if plan['moq_applied'] else "\n")
        + f"- 配合供應商: {plan['supplier_name']}\n"
        f"- 預計交期: {plan['lead_time_days']} 個工作天\n"
        f"- 預估採購總金額: NT$ {plan['estimated_total_cost']:,} 元（單價: {plan['unit_cost']}"
        + (f"，已享折扣: {int(plan['discount_rate']*100)}%）\n" if plan['discount_rate'] > 0 else "）\n")
        + f"- 簽核層級: {plan['approval_tier']}（{plan['approver']}）\n"
        f"- 審批狀態: {approval_warn}\n"
        f"- OKF 政策合規依據：\n{notes_str}\n"
        f"- 產品系統連結: {plan['system_link']}"
    )


# ---------------------------------------------------------------------------
# 5. 回覆節點（respond 節點為前端 SSE 與 A2A 輸出口）
# ---------------------------------------------------------------------------
def respond(node_input: Any) -> types.Content:
    text = str(node_input)
    return types.Content(
        role="model",
        parts=[types.Part.from_text(text=text)],
    )


# ---------------------------------------------------------------------------
# 6. 建構 Workflow 圖與 App
# ---------------------------------------------------------------------------
edges = [
    ("START", classify_intent),
    (classify_intent, route_intent),
    (
        route_intent,
        {
            "refuse": refuse_node,
            "clarify": clarify_node,
            "check_stock": node_check_stock,
            "list_low_stock": node_list_low_stock,
            "replenish_advice": node_replenish_advice,
        },
    ),
    (refuse_node, respond),
    (clarify_node, respond),
    (node_check_stock, respond),
    (node_list_low_stock, respond),
    (node_replenish_advice, respond),
]

root_agent = Workflow(
    name="inventory_agent",
    edges=edges,
)

app = App(
    root_agent=root_agent,
    name="inventory_agent",
)

