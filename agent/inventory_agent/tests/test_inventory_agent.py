"""Unit tests for Inventory Agent and OKF Knowledge Base."""

import pytest
from inventory_agent.okf.kb import OKFKnowledgeBase
from inventory_agent.tools.inventory_tools import (
    generate_replenishment_advice,
    query_low_stock_list,
    query_product_stock,
)


def test_okf_supplier_policy():
    kb = OKFKnowledgeBase()
    supp = kb.find_supplier_for_product("A4影印紙")
    assert supp is not None
    assert supp["name"] == "大同紙業有限公司"
    assert supp["moq"] == 20
    assert supp["lead_time_days"] == 3


def test_okf_safety_stock_rule():
    kb = OKFKnowledgeBase()
    rule = kb.get_safety_stock_rule("A4影印紙")
    assert rule["category"] == "辦公用紙"
    assert rule["minimum_stock_threshold"] == 15
    assert rule["stockout_risk_level"] == "HIGH"


def test_okf_replenishment_moq_adjustment():
    kb = OKFKnowledgeBase()
    # 需求量 8 箱，小於 MOQ 20 箱，應自動補足至 20 箱
    plan = kb.evaluate_replenishment_plan(
        product_name="A4影印紙",
        current_inventory=5,
        unit_cost=380.0,
        target_qty=8,
    )
    assert plan["suggested_order_qty"] == 20
    assert plan["moq_applied"] is True
    assert plan["estimated_total_cost"] == 7600.0
    assert plan["approval_tier"] == "TIER_1_AUTO"


def test_okf_approval_tiers():
    kb = OKFKnowledgeBase()
    tier1 = kb.get_approval_tier(5000)
    assert tier1["tier"] == "TIER_1_AUTO"
    assert tier1["requires_human_approval"] is False

    tier2 = kb.get_approval_tier(30000)
    assert tier2["tier"] == "TIER_2_MANAGER"
    assert tier2["requires_human_approval"] is True

    tier3 = kb.get_approval_tier(100000)
    assert tier3["tier"] == "TIER_3_EXECUTIVE"
    assert tier3["requires_human_approval"] is True


def test_inventory_query_tool():
    res = query_product_stock("A4")
    if "error" not in res:
        assert res["minimum_safety_stock"] == 15
        assert "system_link" in res
        assert "http://localhost:3000/products/" in res["system_link"]

