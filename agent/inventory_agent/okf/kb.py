"""Open Knowledge Fabric (OKF) Engine for EZStore Inventory Agent.

負責載入、解析與檢索企業採購規範、安全存量標準、供應商交期與起訂量 (MOQ)、
以及金額簽核層級政策，為庫存與補貨 Agent 提供確定性知識支援。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

OKF_DIR = Path(__file__).parent


class OKFKnowledgeBase:
    def __init__(self, data_dir: Path = OKF_DIR):
        self.data_dir = data_dir
        self.suppliers = self._load_json("supplier_directory.json").get("suppliers", [])
        self.safety_policies = self._load_json("safety_stock_policy.json")
        self.approval_tiers = self._load_json("approval_governance.json").get("tiers", [])

    def _load_json(self, filename: str) -> dict:
        filepath = self.data_dir / filename
        if not filepath.exists():
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def find_supplier_for_product(self, product_name: str) -> Optional[dict]:
        """依商品名稱或類別匹配最適供應商與採購政策。"""
        product_lower = product_name.lower()
        if "紙" in product_lower or "a4" in product_lower:
            target_cat = "辦公用紙"
        elif "包裝" in product_lower or "箱" in product_lower:
            target_cat = "包裝耗材"
        else:
            target_cat = "電子周邊"

        for supp in self.suppliers:
            if target_cat in supp.get("categories", []):
                return supp
        return self.suppliers[0] if self.suppliers else None

    def get_safety_stock_rule(self, product_name: str) -> dict:
        """取得產品對應的安全存量門檻與公式。"""
        product_lower = product_name.lower()
        if "紙" in product_lower or "a4" in product_lower:
            cat = "辦公用紙"
        elif "包裝" in product_lower:
            cat = "包裝耗材"
        else:
            cat = "電子周邊"

        for p in self.safety_policies.get("category_policies", []):
            if p.get("category") == cat:
                return p
        return {
            "category": "通用",
            "minimum_stock_threshold": self.safety_policies.get("default_safety_stock_units", 10),
            "stockout_risk_level": "MEDIUM",
            "notes": "套用一般通用安全庫存標準",
        }

    def get_approval_tier(self, total_amount: float) -> dict:
        """依據採購金額判定簽核層級。"""
        for tier in self.approval_tiers:
            max_amt = tier.get("max_amount")
            min_amt = tier.get("min_amount", 0)
            if max_amt is not None:
                if min_amt <= total_amount <= max_amt:
                    return tier
            else:
                if total_amount >= min_amt:
                    return tier
        return self.approval_tiers[0]

    def evaluate_replenishment_plan(
        self,
        product_name: str,
        current_inventory: int,
        unit_cost: float,
        target_qty: Optional[int] = None,
    ) -> Dict[str, Any]:
        """結合 OKF 知識庫，計算最符合企業合規之補貨計畫。"""
        supplier = self.find_supplier_for_product(product_name)
        safety_rule = self.get_safety_stock_rule(product_name)
        min_threshold = safety_rule.get("minimum_stock_threshold", 10)

        # 若未指定目標量，則補足至安全庫存的 2 倍
        raw_need = target_qty if target_qty is not None else max(0, (min_threshold * 2) - current_inventory)
        if raw_need <= 0:
            raw_need = min_threshold

        moq = supplier.get("moq", 1) if supplier else 1
        moq_unit = supplier.get("moq_unit", "件") if supplier else "件"
        lead_time = supplier.get("lead_time_days", 3) if supplier else 3

        # 考慮 MOQ 規範
        adjusted_qty = raw_need
        moq_applied = False
        if adjusted_qty < moq:
            adjusted_qty = moq
            moq_applied = True

        # 計算折扣
        discount_rate = 0.0
        if supplier:
            for vd in supplier.get("volume_discounts", []):
                if adjusted_qty >= vd.get("min_qty", 0):
                    discount_rate = max(discount_rate, vd.get("discount_rate", 0.0))

        actual_unit_cost = unit_cost * (1.0 - discount_rate)
        total_cost = actual_unit_cost * adjusted_qty
        approval = self.get_approval_tier(total_cost)

        return {
            "product_name": product_name,
            "current_inventory": current_inventory,
            "safety_stock_threshold": min_threshold,
            "is_below_safety_stock": current_inventory < min_threshold,
            "supplier_name": supplier.get("name", "未指定供應商") if supplier else "未指定",
            "lead_time_days": lead_time,
            "raw_needed_qty": raw_need,
            "moq": moq,
            "moq_unit": moq_unit,
            "moq_applied": moq_applied,
            "suggested_order_qty": adjusted_qty,
            "unit_cost": unit_cost,
            "discount_rate": discount_rate,
            "estimated_total_cost": round(total_cost, 2),
            "approval_tier": approval.get("tier"),
            "approver": approval.get("approver"),
            "requires_human_approval": approval.get("requires_human_approval", False),
            "policy_notes": [
                f"OKF 安全庫存政策：門檻為 {min_threshold} {moq_unit}（風險等級：{safety_rule.get('stockout_risk_level')}）",
                f"OKF 供應商規範：{supplier.get('name') if supplier else ''} 最小起訂量 (MOQ) 為 {moq} {moq_unit}，前置交期約 {lead_time} 天"
                + (f"（已自動依起訂量調整至 {adjusted_qty} {moq_unit}）" if moq_applied else ""),
                f"OKF 簽核規範：採購金額 NT$ {round(total_cost, 0):,} 元，簽核層級為「{approval.get('tier')} - {approval.get('approver')}」",
            ],
        }

