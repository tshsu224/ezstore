"""Inventory tools for EZStore Inventory Agent.

提供產品庫存查詢、低庫存預警、以及結合 OKF 知識庫的補貨建議產出。
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from ..okf.kb import OKFKnowledgeBase

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")
# 若在容器外本機執行，可切換為 localhost:8080
if not os.environ.get("BACKEND_URL") and os.environ.get("LOCAL_DEV"):
    BACKEND_URL = "http://localhost:8080"

okf_kb = OKFKnowledgeBase()


def _fetch_products(search: str = "", page_size: int = 50) -> List[dict]:
    url = f"{BACKEND_URL}/api/v1/products?pageSize={page_size}"
    if search:
        url += f"&search={urllib.parse.quote(search)}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", [])
    except Exception:
        # 備援嘗試 localhost
        try:
            fallback_url = url.replace("http://backend:8080", "http://localhost:8080")
            req = urllib.request.Request(fallback_url, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", [])
        except Exception:
            return []


def query_product_stock(product_identifier: str) -> Dict[str, Any]:
    """查詢單一產品之現有庫存與安全存量狀態。"""
    products = _fetch_products(search=product_identifier)
    if not products:
        # 若以代號查無，拉全部列表進行模糊匹配
        all_prods = _fetch_products()
        for p in all_prods:
            if product_identifier.lower() in p.get("name", "").lower() or product_identifier.upper() in p.get("product_number", ""):
                products = [p]
                break

    if not products:
        return {"error": f"找不到符合「{product_identifier}」的商品。"}

    prod = products[0]
    p_name = prod.get("name", "")
    current_inv = prod.get("inventory", 0)
    safety_rule = okf_kb.get_safety_stock_rule(p_name)
    threshold = safety_rule.get("minimum_stock_threshold", 10)

    return {
        "id": prod.get("id"),
        "product_number": prod.get("product_number"),
        "name": p_name,
        "inventory": current_inv,
        "cost": float(prod.get("cost", 0)),
        "list_price": float(prod.get("list_price", 0)),
        "supplier": prod.get("supplier"),
        "minimum_safety_stock": threshold,
        "status": "充足" if current_inv >= threshold else "庫存過低（需補貨）",
        "stockout_risk": safety_rule.get("stockout_risk_level"),
        "system_link": f"http://localhost:3000/products/{prod.get('id')}/edit",
    }


def query_low_stock_list(threshold: Optional[int] = None) -> List[Dict[str, Any]]:
    """列出目前庫存低於安全水位或指定門檻的所有商品。"""
    all_prods = _fetch_products()
    low_stocks = []
    for p in all_prods:
        inv = p.get("inventory", 0)
        p_name = p.get("name", "")
        rule = okf_kb.get_safety_stock_rule(p_name)
        min_threshold = threshold if threshold is not None else rule.get("minimum_stock_threshold", 15)

        if inv <= min_threshold:
            low_stocks.append({
                "id": p.get("id"),
                "product_number": p.get("product_number"),
                "name": p_name,
                "current_inventory": inv,
                "safety_threshold": min_threshold,
                "supplier": p.get("supplier"),
                "system_link": f"http://localhost:3000/products/{p.get('id')}/edit",
            })
    return low_stocks


def generate_replenishment_advice(product_identifier: str, target_qty: Optional[int] = None) -> Dict[str, Any]:
    """結合 OKF 知識庫（交期、起訂量 MOQ、簽核規範），計算建議補貨單。"""
    stock_info = query_product_stock(product_identifier)
    if "error" in stock_info:
        return stock_info

    plan = okf_kb.evaluate_replenishment_plan(
        product_name=stock_info["name"],
        current_inventory=stock_info["inventory"],
        unit_cost=stock_info["cost"],
        target_qty=target_qty,
    )
    plan["product_id"] = stock_info["id"]
    plan["product_number"] = stock_info["product_number"]
    plan["system_link"] = stock_info["system_link"]
    return plan

