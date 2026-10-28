"""評分用 deterministic 指標：回覆是否含純文字系統連結（且沒有 Markdown 連結語法）。

規則（依序）：
1. 出現 Markdown 連結 [文字](網址) → 0 分（spec 1.8 要求純文字連結）。
2. 離題拒答（eval_case_id 以 off_topic 開頭，或回覆含「只能協助」）→ 1 分，不需要連結。
3. 追問（回覆以「請提供」開頭，或含「請告訴我您要對報價單」）→ 1 分，不需要連結。
4. 查無資料（回覆含「找不到」）或誠實回報操作失敗（含「操作失敗」「必須大於」）→ 1 分，不需要明細連結。
5. 其他案例：必須含 http(s)://…/quotations/<id> 或 /orders/<id> → 1 分，否則 0 分。
"""

import re

_LINK = re.compile(r"https?://\S+/(quotations|orders)/\d+")
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")


def _response_text(instance) -> str:
    response = instance.get("response") or {}
    if isinstance(response, str):
        return response
    parts = response.get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def evaluate(instance):
    text = _response_text(instance)
    case_id = str(instance.get("eval_case_id", ""))

    if _MARKDOWN_LINK.search(text):
        return {"score": 0, "explanation": "回覆使用了 Markdown 連結語法，spec 要求純文字連結"}
    if case_id.startswith("off_topic") or "只能協助" in text:
        return {"score": 1, "explanation": "拒答案例不需要連結"}
    if text.strip().startswith("請提供") or "請告訴我您要對報價單" in text:
        return {"score": 1, "explanation": "追問案例不需要連結"}
    if "找不到" in text:
        return {"score": 1, "explanation": "查無資料的回覆不需要明細連結"}
    if "操作失敗" in text or "必須大於" in text:
        return {"score": 1, "explanation": "誠實回報操作失敗的回覆不需要明細連結"}
    if _LINK.search(text):
        return {"score": 1, "explanation": "回覆包含純文字系統連結"}
    return {"score": 0, "explanation": "回覆缺少 /quotations/<id> 或 /orders/<id> 的純文字連結"}
