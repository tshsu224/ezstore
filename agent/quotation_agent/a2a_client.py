"""A2A (Agent-to-Agent) Client for Quotation Agent to communicate with Inventory Agent.

支援本地 Direct In-Process RPC 與遠端 A2A JSON-RPC 兩種通訊模式，
實現跨 Agent 自治協同。
"""

import json
import os
import urllib.request
from typing import Any


def call_inventory_agent_a2a(query: str) -> str:
    """透過 A2A 協定向 Inventory Agent 請求庫存現況、安全水位與 OKF 補貨政策分析。"""
    remote_a2a_url = os.environ.get("INVENTORY_A2A_URL")

    # 1. 若配置了遠端 A2A 端點，走標準 JSON-RPC 2.0 A2A 協定
    if remote_a2a_url:
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "agent.execute",
                "params": {"message": query},
                "id": 1,
            }
            req = urllib.request.Request(
                remote_a2a_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("result", {}).get("text", "")
        except Exception:
            pass

    # 2. 本地直接 A2A 執行環境（Direct In-Process A2A Executor）
    try:
        from inventory_agent.agent import app as inv_app
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types

        sess_service = InMemorySessionService()
        runner = Runner(app=inv_app, session_service=sess_service, auto_create_session=True)
        sess = sess_service.create_session_sync(app_name=inv_app.name, user_id="quotation_agent_a2a")
        content = types.Content(role="user", parts=[types.Part.from_text(text=query)])
        events = runner.run(user_id="quotation_agent_a2a", session_id=sess.id, new_message=content)

        last_reply = ""
        for ev in events:
            path = getattr(getattr(ev, "nodeInfo", None), "path", "") or ""
            author = getattr(ev, "author", "")
            parts = getattr(getattr(ev, "content", None), "parts", []) or []
            txt = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
            if ("/respond@" in path or author == "inventory_agent") and txt and not txt.strip().startswith("{"):
                last_reply = txt
        if last_reply:
            return last_reply
    except Exception as e:
        return f"[A2A 通訊異常: {e}]"

    return "A2A 呼叫成功完成，但未取得明確文字回覆。"

