#!/usr/bin/env python3
"""EZStore A2A (Agent-to-Agent) & OKF (Open Knowledge Fabric) 展示腳本。

演示：
1. 庫存與採購補貨 Agent (inventory_agent) 結合 OKF 知識庫產出智慧補貨計畫。
2. 報價單管理 Agent (quotation_agent) 透過 A2A 協定向 inventory_agent 請求倉儲現況與交期。
"""

import os
import sys

# Windows 控制台 UTF-8 相容
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 設定環境變數與路徑
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, AGENT_DIR)
os.environ["LOCAL_DEV"] = "1"
os.environ.setdefault("BACKEND_URL", "http://localhost:8080")
os.environ.setdefault("MCP_URL", "http://localhost:8010/mcp")


def print_banner(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def demo_inventory_okf():
    print_banner("1. 測試 Inventory Agent + OKF 知識庫（補貨決策與政策合規）")
    from inventory_agent.okf.kb import OKFKnowledgeBase
    from inventory_agent.tools.inventory_tools import generate_replenishment_advice, query_product_stock

    kb = OKFKnowledgeBase()
    prod_name = "A4影印紙 80磅 (5包/箱)"
    print(f"[步驟 1] 查詢商品現況與安全庫存水位：{prod_name}")
    stock = query_product_stock("A4")
    print(f"  • 目前庫存: {stock.get('inventory')} 箱")
    print(f"  • OKF 安全庫存門檻: {stock.get('minimum_safety_stock')} 箱（風險等級：{stock.get('stockout_risk')}）")
    print(f"  • 配合供應商: {stock.get('supplier')}")
    print(f"  • 系統連結: {stock.get('system_link')}")

    print(f"\n[步驟 2] 模擬補貨需求 8 箱（觸發 OKF 供應商 MOQ 20 箱約束與審批規範）：")
    plan = generate_replenishment_advice("A4", target_qty=8)
    print(f"  • 原始需求量: {plan['raw_needed_qty']} 箱")
    print(f"  • 依 OKF MOQ 規範調整後採購量: {plan['suggested_order_qty']} 箱（MOQ生效: {plan['moq_applied']}）")
    print(f"  • 預估前置交期 (Lead Time): {plan['lead_time_days']} 個工作天")
    print(f"  • 預估採購金額: NT$ {plan['estimated_total_cost']:,} 元")
    print(f"  • 審批層級: {plan['approval_tier']}（{plan['approver']}）")
    print("  • OKF 政策合規依據：")
    for note in plan.get("policy_notes", []):
        print(f"    - {note}")


def demo_a2a_communication():
    print_banner("2. 測試 A2A (Agent-to-Agent) 協定跨 Agent 自治協同")
    from quotation_agent.a2a_client import call_inventory_agent_a2a

    query = "查詢 A4影印紙 庫存與補貨建議"
    print(f"Quotation Agent (銷售端) 發起 A2A 請求 ──[ A2A Protocol JSON-RPC ]──► Inventory Agent (倉儲端)")
    print(f"A2A Payload Message: \"{query}\"\n")

    reply = call_inventory_agent_a2a(query)
    print("Inventory Agent 經由 A2A 協定回覆結果：")
    print("-" * 60)
    print(reply.strip())
    print("-" * 60)
    print("\n✅ A2A 協同成功完成！Quotation Agent 已能即時掌握倉儲庫存與 OKF 補貨政策。")


if __name__ == "__main__":
    demo_inventory_okf()
    demo_a2a_communication()

