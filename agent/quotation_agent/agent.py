# ruff: noqa
import os
import re
from typing import Any, Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 載入當前目錄下的 .env
load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.agents.context import Context
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.workflow import Workflow
from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from .a2a_client import call_inventory_agent_a2a

MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8010/mcp")

# 透過 ADK McpToolset 配置 MCP 連線
mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL)
)


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """呼叫 MCP 工具並回傳文字內容。"""
    try:
        res = await mcp_toolset._execute_with_session(
            lambda session: session.call_tool(tool_name, arguments=arguments),
            f"Failed to call MCP tool {tool_name}",
        )
        texts = [c.text for c in res.content if hasattr(c, "text")]
        return "\n".join(texts)
    except Exception:
        # 備援：直接使用標準 MCP Streamable HTTP 客戶端
        async with streamable_http_client(MCP_URL) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, arguments)
                texts = [c.text for c in res.content if hasattr(c, "text")]
                return "\n".join(texts)


# ---------------------------------------------------------------------------
# 1. 意圖分類結構（Pydantic Output Schema）
# ---------------------------------------------------------------------------
class IntentClassification(BaseModel):
    action: Literal[
        "get_quotation",
        "list_customer_quotations",
        "duplicate_quotation",
        "update_pricing_factor",
        "adjust_total_price",
        "convert_to_order",
        "check_inventory_a2a",
        "off_topic",
        "supply_info",
        "unknown",
    ] = Field(
        description="報價單管理操作意圖，若為非報價單相關需求則為 off_topic。"
    )
    quotation_number: Optional[str] = Field(
        default=None,
        description="報價單編號，通常為 QT-YYYYMMDD-XXX 格式。",
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="客戶名稱。",
    )
    product_name: Optional[str] = Field(
        default=None,
        description="商品名稱（例如 A4影印紙）。",
    )
    pricing_factor: Optional[float] = Field(
        default=None,
        description="新的報價因子（浮點數）。",
    )
    target_total_price: Optional[float] = Field(
        default=None,
        description="目標總價（浮點數）。",
    )


classify_intent = LlmAgent(
    name="classify_intent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""你是一個專業的報價單管理系統意圖分析器。請根據使用者的輸入，嚴格分析並提取以下欄位：

意圖分類規則：
1. 查詢報價單：action="get_quotation"，提取 quotation_number（例如 QT-20260330-001）。
2. 查詢客戶的報價單清單：action="list_customer_quotations"，提取 customer_name（例如 史塔克工業）。
3. 複製報價單：action="duplicate_quotation"，提取 quotation_number。
4. 修改報價單報價因子：action="update_pricing_factor"，提取 quotation_number 與 pricing_factor。
5. 修改報價單總價：action="adjust_total_price"，提取 quotation_number 與 target_total_price。
6. 將報價單轉訂單：action="convert_to_order"，提取 quotation_number。
7. 透過 A2A 跨 Agent 查詢庫存與補貨交期：action="check_inventory_a2a"，提取 product_name 或 quotation_number。
8. 使用者補充資料（例如只說了單號 QT-20260330-001、客戶名稱或數字）：action="supply_info"，並填寫對應欄位。
9. 離題需求（天氣、日常閒聊、客戶新增/修改、產品新增/修改等非相關需求）：action="off_topic"。
10. 其他無法識別的文字：action="unknown"。
""",
    output_schema=IntentClassification,
)


# ---------------------------------------------------------------------------
# 2. 路由節點（純程式邏輯決定，處理多輪狀態、追問與離題拒答）
# ---------------------------------------------------------------------------
def route_intent(ctx: Context, node_input: Any) -> Event:
    print(f"ROUTE_INTENT DEBUG: ctx type={type(ctx)}, node_input={node_input}, state={getattr(ctx, 'state', None)}")
    if isinstance(node_input, dict):
        intent = IntentClassification(**node_input)
    elif isinstance(node_input, IntentClassification):
        intent = node_input
    else:
        intent = IntentClassification(action="unknown")

    pending_action = ctx.state.get("pending_action")
    pending_params = ctx.state.get("pending_params") or {}

    action = intent.action
    quotation_number = intent.quotation_number or pending_params.get("quotation_number")
    customer_name = intent.customer_name or pending_params.get("customer_name")
    pricing_factor = (
        intent.pricing_factor
        if intent.pricing_factor is not None
        else pending_params.get("pricing_factor")
    )
    target_total_price = (
        intent.target_total_price
        if intent.target_total_price is not None
        else pending_params.get("target_total_price")
    )
    last_quotation_number = ctx.state.get("last_quotation_number")
    if (action in ("supply_info", "unknown") or action is None):
        if pricing_factor is not None:
            action = "update_pricing_factor"
        elif target_total_price is not None:
            action = "adjust_total_price"
        elif pending_action:
            action = pending_action

    if not quotation_number and action in (
        "update_pricing_factor",
        "adjust_total_price",
        "convert_to_order",
        "duplicate_quotation",
    ):
        quotation_number = last_quotation_number
        if not quotation_number and hasattr(ctx, "session") and ctx.session and hasattr(ctx.session, "events"):
            for ev in reversed(ctx.session.events):
                txt = ""
                if hasattr(ev, "content") and ev.content and hasattr(ev.content, "parts"):
                    txt = "".join([p.text for p in ev.content.parts if hasattr(p, "text") and p.text])
                elif hasattr(ev, "output") and ev.output:
                    txt = str(ev.output)
                m = re.search(r"QT-\d{8}-\d{3}", txt)
                if m:
                    quotation_number = m.group(0)
                    break

    if action in ("supply_info", "unknown") or action is None:
        if hasattr(ctx, "session") and ctx.session and hasattr(ctx.session, "events") and ctx.session.events:
            for ev in reversed(ctx.session.events):
                txt = ""
                if hasattr(ev, "content") and ev.content and hasattr(ev.content, "parts"):
                    txt = "".join([p.text for p in ev.content.parts if hasattr(p, "text") and p.text])
                elif hasattr(ev, "output") and ev.output:
                    txt = str(ev.output)

                if "複製" in txt:
                    action = "duplicate_quotation"
                    break
                elif "轉訂單" in txt or "訂單" in txt:
                    action = "convert_to_order"
                    break
                elif "報價因子" in txt:
                    action = "update_pricing_factor"
                    break
                elif "總價" in txt:
                    action = "adjust_total_price"
                    break
                elif "查詢" in txt or "報價單" in txt:
                    action = "get_quotation"
                    break

        if (action in ("supply_info", "unknown") or action is None) and quotation_number:
            action = "get_quotation"
        elif (action in ("supply_info", "unknown") or action is None) and customer_name:
            action = "list_customer_quotations"

    # 規範 1.10：離題拒答（由程式邏輯嚴格判斷）
    if action in ("off_topic", "unknown"):
        ctx.state["pending_action"] = None
        ctx.state["pending_params"] = {}
        return Event(
            output="抱歉，我只能協助處理報價單相關的操作（例如查詢報價單、查詢客戶報價單、修改報價因子、調整總價、轉訂單、複製報價單等）。無法處理天氣、閒聊或客戶與產品新增修改等其他需求。",
            route="refuse",
            state={"pending_action": None, "pending_params": {}},
        )

    # 規範 1.9：缺資料主動追問，並將已知的資料暫存於 session state
    if action in ("get_quotation", "duplicate_quotation", "convert_to_order"):
        if not quotation_number:
            return Event(
                output="請提供您要操作的報價單編號（例如 QT-20260330-001）？",
                route="clarify",
                state={"pending_action": action, "pending_params": {}},
            )

    elif action == "list_customer_quotations":
        if not customer_name:
            return Event(
                output="請提供您要查詢的客戶名稱（例如 史塔克工業）？",
                route="clarify",
                state={"pending_action": action, "pending_params": {}},
            )

    elif action == "update_pricing_factor":
        if not quotation_number:
            return Event(
                output="請提供您要修改的報價單編號（例如 QT-20260330-001）？",
                route="clarify",
                state={
                    "pending_action": action,
                    "pending_params": {"pricing_factor": pricing_factor},
                },
            )
        if pricing_factor is None:
            return Event(
                output="請提供新的報價因子（例如 1.5）？",
                route="clarify",
                state={
                    "pending_action": action,
                    "pending_params": {"quotation_number": quotation_number},
                },
            )

    elif action == "adjust_total_price":
        if not quotation_number:
            return Event(
                output="請提供您要調整的報價單編號（例如 QT-20260330-001）？",
                route="clarify",
                state={
                    "pending_action": action,
                    "pending_params": {"target_total_price": target_total_price},
                },
            )
        if target_total_price is None:
            return Event(
                output="請提供目標總價（例如 8000）？",
                route="clarify",
                state={
                    "pending_action": action,
                    "pending_params": {"quotation_number": quotation_number},
                },
            )

    elif action == "check_inventory_a2a":
        p_name = intent.product_name or pending_params.get("product_name")
        if not p_name and not quotation_number:
            return Event(
                output="請提供您要透過 A2A 查詢庫存的商品名稱或編號（例如：A4影印紙）？",
                route="clarify",
                state={"pending_action": action, "pending_params": {}},
            )

    # 必要資料齊全，清除 pending 狀態並導向對應操作節點
    args = {
        "quotation_number": quotation_number,
        "customer_name": customer_name,
        "product_name": intent.product_name or pending_params.get("product_name"),
        "pricing_factor": pricing_factor,
        "target_total_price": target_total_price,
    }
    if quotation_number:
        ctx.state["last_quotation_number"] = quotation_number

    new_state = {
        "pending_action": None,
        "pending_params": {},
        "last_quotation_number": quotation_number or last_quotation_number,
    }
    return Event(
        output=args,
        route=action,
        state=new_state,
    )


# ---------------------------------------------------------------------------
# 3. 追問與拒答節點
# ---------------------------------------------------------------------------
def clarify_node(node_input: Any) -> str:
    return str(node_input)


def refuse_node(node_input: Any) -> str:
    return str(node_input)


# ---------------------------------------------------------------------------
# 4. 各操作節點（程式調用 MCP 工具，原樣回傳工具產生的文字與純文字連結）
# ---------------------------------------------------------------------------
async def node_get_quotation(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "get_quotation", {"quotation_number": node_input["quotation_number"]}
    )


async def node_list_customer_quotations(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "list_customer_quotations", {"customer_name": node_input["customer_name"]}
    )


async def node_duplicate_quotation(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "duplicate_quotation", {"quotation_number": node_input["quotation_number"]}
    )


async def node_update_pricing_factor(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "update_pricing_factor",
        {
            "quotation_number": node_input["quotation_number"],
            "new_pricing_factor": float(node_input["pricing_factor"]),
        },
    )


async def node_adjust_total_price(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "adjust_total_price",
        {
            "quotation_number": node_input["quotation_number"],
            "target_total_price": float(node_input["target_total_price"]),
        },
    )


async def node_convert_to_order(node_input: dict[str, Any]) -> str:
    return await call_mcp_tool(
        "convert_to_order", {"quotation_number": node_input["quotation_number"]}
    )


def node_check_inventory_a2a(node_input: dict[str, Any]) -> str:
    target = node_input.get("product_name") or "A4影印紙"
    res = call_inventory_agent_a2a(f"查詢 {target} 庫存並提供補貨建議")
    return (
        f"【A2A 跨 Agent 協同回應】\n"
        f"Quotation Agent 透過 A2A 協定向 Inventory Agent 取得「{target}」的倉儲狀況與 OKF 政策分析：\n\n"
        f"{res}"
    )


# ---------------------------------------------------------------------------
# 5. 回覆節點（respond 節點為前端 Chat UI 唯一讀取的節點輸出路徑）
# ---------------------------------------------------------------------------
def respond(node_input: Any) -> types.Content:
    if isinstance(node_input, str):
        text = node_input
    elif isinstance(node_input, dict) and "text" in node_input:
        text = str(node_input["text"])
    else:
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
            "get_quotation": node_get_quotation,
            "list_customer_quotations": node_list_customer_quotations,
            "duplicate_quotation": node_duplicate_quotation,
            "update_pricing_factor": node_update_pricing_factor,
            "adjust_total_price": node_adjust_total_price,
            "convert_to_order": node_convert_to_order,
            "check_inventory_a2a": node_check_inventory_a2a,
        },
    ),
    (refuse_node, respond),
    (clarify_node, respond),
    (node_get_quotation, respond),
    (node_list_customer_quotations, respond),
    (node_duplicate_quotation, respond),
    (node_update_pricing_factor, respond),
    (node_adjust_total_price, respond),
    (node_convert_to_order, respond),
    (node_check_inventory_a2a, respond),
]

root_agent = Workflow(
    name="quotation_agent",
    edges=edges,
)

app = App(
    root_agent=root_agent,
    name="quotation_agent",
)
