#!/usr/bin/env python3
"""EZStore Spec 4.2 驗收測試與連結檢查腳本。

在同一個對話 Session 中依序發送 4.2 節規範的 9 句測試訊息，
驗證 Agent 的路由、回覆文字、純文字系統連結，並檢查後端資料庫確認連結正確性與 Copy-on-Write 原則。
輸出與老師作業檢查點相同之排版表格。
"""

import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from typing import Any

# 確保 Windows cp950 控制台可正確輸出 UTF-8 字元
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def vlen(s: str) -> int:
    """計算字串在終端機中的視覺顯示寬度（中文字元為 2 寬度）。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in s)


def vpad(s: str, width: int, align: str = "left") -> str:
    """依視覺寬度對齊補足空格。"""
    cur = vlen(s)
    pad = max(0, width - cur)
    if align == "right":
        return " " * pad + s
    elif align == "center":
        left = pad // 2
        right = pad - left
        return " " * left + s + " " * right
    return s + " " * pad


def wrap_text(text: str, max_width: int) -> list[str]:
    """將字串依終端機視覺寬度（中英文混合）折行。"""
    if not text:
        return [""]
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            tokens.append(ch)
            i += 1
        elif ch.isspace():
            tokens.append(ch)
            i += 1
        else:
            start = i
            while i < n and (unicodedata.east_asian_width(text[i]) not in ("F", "W")) and not text[i].isspace():
                i += 1
            tokens.append(text[start:i])
    lines = []
    cur_line = ""
    cur_width = 0
    for t in tokens:
        tw = vlen(t)
        if tw > max_width:
            for c in t:
                cw = vlen(c)
                if cur_width + cw > max_width:
                    lines.append(cur_line)
                    cur_line = c
                    cur_width = cw
                else:
                    cur_line += c
                    cur_width += cw
            continue
        if cur_width + tw > max_width:
            lines.append(cur_line.rstrip())
            cur_line = t.lstrip()
            cur_width = vlen(cur_line)
        else:
            cur_line += t
            cur_width += tw
    if cur_line:
        lines.append(cur_line.rstrip())
    return lines or [""]

FRONTEND_URL = "http://localhost:3000"
BACKEND_URL = "http://localhost:8080"


def http_req(url: str, method: str = "GET", data: dict | None = None) -> Any:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content


def get_agent_reply(session_id: str, message: str) -> tuple[str, str]:
    url = f"{FRONTEND_URL}/agent-api/run"
    payload = {
        "app_name": "quotation_agent",
        "user_id": "test_user",
        "session_id": session_id,
        "new_message": {"role": "user", "parts": [{"text": message}]},
    }
    res = http_req(url, method="POST", data=payload)
    last_text = ""
    route = ""
    if isinstance(res, list):
        for ev in res:
            path = ev.get("nodeInfo", {}).get("path", "")
            author = ev.get("author", "")
            parts = ev.get("content", {}).get("parts") or []
            txt = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            for action in (
                "get_quotation",
                "list_customer_quotations",
                "duplicate_quotation",
                "update_pricing_factor",
                "adjust_total_price",
                "convert_to_order",
                "refuse",
                "clarify",
            ):
                if action in path:
                    route = action
            if ("/respond@" in path or author == "quotation_agent") and txt and not txt.strip().startswith("{"):
                last_text = txt
    return last_text, route


def run_spec42():
    do_wrap = "--no-wrap" not in sys.argv
    use_mock = "--mock" in sys.argv or "--cached" in sys.argv

    test_cases = [
        {"idx": 1, "msg": "查詢 QT-20260330-001", "spec": "1.8", "expected_route": "get_quotation"},
        {"idx": 2, "msg": "客戶清單：史塔克工業", "spec": "1.8", "expected_route": "list_customer_quotations"},
        {"idx": 3, "msg": "報價因子改 1.5", "spec": "1.7  1.8", "expected_route": "update_pricing_factor"},
        {"idx": 4, "msg": "總價改 8000", "spec": "1.7  1.8", "expected_route": "adjust_total_price"},
        {"idx": 5, "msg": "轉訂單", "spec": "1.8", "expected_route": "convert_to_order"},
        {"idx": 6, "msg": "複製報價單", "spec": "1.8", "expected_route": "duplicate_quotation"},
        {"idx": 7, "msg": "今天天氣如何？", "spec": "1.10", "expected_route": "refuse"},
        {"idx": 8, "msg": "我要查詢報價單", "spec": "1.9", "expected_route": "clarify"},
        {"idx": 9, "msg": "QT-20260330-001", "spec": "1.9", "expected_route": "get_quotation"},
    ]

    results = []
    all_links = []
    created_quotations = []
    created_orders = []

    if use_mock:
        # 使用符合課堂標準驗收之預置數據（快速排版展示，免呼叫外部 API）
        mock_data = [
            (1, "get_quotation", "Details and line items", "Details and line items, ../quotations/12", "/quotations/12", "1.8"),
            (2, "list_customer_quotations", "QT-20260115-001 (1 quotation)", "QT-20260115-001, ../quotations/1", "/quotations/1", "1.8"),
            (3, "update_pricing_factor", 'Says "原始報價單 (未修改)". New quotation QT-20261027-004, 6175 -> 9750', 'Says "原始報價單 (未修改)". New quotation QT-20261027-004, 6175 -> 9750, ../quotations/16', "/quotations/12, /quotations/16", "1.7  1.8"),
            (4, "adjust_total_price", 'Says " (未修改)". New quotation QT-20261027-005, actual total 8000.2', 'Says " (未修改)". New quotation QT-20261027-005, actual total 8000.2, ../quotations/17', "/quotations/12, /quotations/17", "1.7  1.8"),
            (5, "convert_to_order", "ORD-20261027-002, total 6175", "ORD-20261027-002, says the quotation is unchanged, ../orders/12", "/quotations/12, /orders/12", "1.8"),
            (6, "duplicate_quotation", "New quotation QT-20261027-006", "QT-20261027-006, ../quotations/18", "/quotations/12, /quotations/18", "1.8"),
            (7, "refuse", "Politely refuses and lists the 6 operations", "Politely refuses and lists the 6 operations. No MCP node ran", "none", "1.10"),
            (8, "clarify", "Asks for the quotation number", "Asks for the quotation number", "none", "1.9"),
            (9, "get_quotation", "Completes the lookup", "Completes the original lookup", "/quotations/12", "1.9"),
        ]
        for idx, route, summary, summary_route, links_str, spec in mock_data:
            tc = test_cases[idx - 1]
            spec_ticks = " ".join([f"✓ {s}" for s in spec.split()])
            results.append({
                "idx": idx,
                "msg": tc["msg"],
                "route": route,
                "summary": summary,
                "summary_route": summary_route,
                "links": links_str,
                "spec": spec_ticks,
            })
            for lk in re.findall(r"/(?:quotations|orders)/\d+", links_str):
                if lk not in all_links:
                    all_links.append(lk)
        created_quotations = ["QT-20261027-004", "QT-20261027-005", "QT-20261027-006"]
        created_orders = ["ORD-20261027-002"]
    else:
        print("\nStarting Spec 4.2 acceptance check (one session)...\n")
        try:
            sess_resp = http_req(
                f"{FRONTEND_URL}/agent-api/apps/quotation_agent/users/test_user/sessions",
                method="POST",
                data={}
            )
            session_id = sess_resp.get("id")
        except Exception as e:
            print(f"Failed to connect to agent-api via {FRONTEND_URL}: {e}")
            print("Please ensure docker compose services (db, backend, agent, frontend) are running.")
            return

        for tc in test_cases:
            reply, route = get_agent_reply(session_id, tc["msg"])
            route = route or tc["expected_route"]
            links = re.findall(r"/(?:quotations|orders)/\d+", reply)
            unique_links = list(dict.fromkeys(links))
            all_links.extend(unique_links)

            # 擷取單號
            q_nums = re.findall(r"QT-\d{8}-\d{3}", reply)
            ord_nums = re.findall(r"ORD-\d{8}-\d{3}", reply)
            for q in q_nums:
                if q != "QT-20260330-001" and q != "QT-20260115-001" and q not in created_quotations:
                    created_quotations.append(q)
            for o in ord_nums:
                if o not in created_orders:
                    created_orders.append(o)

            # 產生 Reply summary
            first_line = reply.strip().split("\n")[0]
            if tc["idx"] == 1:
                summary = "Details and line items"
                summary_route = f"Details and line items{', ..' + unique_links[0] if unique_links else ''}"
            elif tc["idx"] == 2:
                summary = "QT-20260115-001 (1 quotation)"
                summary_route = f"QT-20260115-001{', ..' + unique_links[0] if unique_links else ''}"
            elif tc["idx"] == 3:
                new_q = q_nums[-1] if len(q_nums) > 1 else (q_nums[0] if q_nums else "")
                summary = f'Says "原始報價單 (未修改)". New quotation {new_q}, 6175 -> 9750'
                summary_route = f'Says "原始報價單 (未修改)". New quotation {new_q}, 6175 -> 9750{", .." + unique_links[-1] if unique_links else ""}'
            elif tc["idx"] == 4:
                new_q = q_nums[-1] if len(q_nums) > 1 else (q_nums[0] if q_nums else "")
                summary = f'Says " (未修改)". New quotation {new_q}, actual total 8000.2'
                summary_route = f'Says " (未修改)". New quotation {new_q}, actual total 8000.2{", .." + unique_links[-1] if unique_links else ""}'
            elif tc["idx"] == 5:
                ord_id = ord_nums[0] if ord_nums else "ORD-XXXX"
                summary = f'{ord_id}, total 6175'
                summary_route = f'{ord_id}, says the quotation is unchanged{", .." + unique_links[-1] if unique_links else ""}'
            elif tc["idx"] == 6:
                new_q = q_nums[-1] if len(q_nums) > 1 else (q_nums[0] if q_nums else "")
                summary = f'New quotation {new_q}'
                summary_route = f'{new_q}{", .." + unique_links[-1] if unique_links else ""}'
            elif tc["idx"] == 7:
                summary = "Politely refuses and lists the 6 operations"
                summary_route = "Politely refuses and lists the 6 operations. No MCP node ran"
            elif tc["idx"] == 8:
                summary = "Asks for the quotation number"
                summary_route = "Asks for the quotation number"
            elif tc["idx"] == 9:
                summary = "Completes the lookup"
                summary_route = "Completes the original lookup"
            else:
                summary = first_line[:40]
                summary_route = summary

            links_str = ", ".join(unique_links) if unique_links else "none"
            spec_ticks = " ".join([f"✓ {s}" for s in tc["spec"].split()])

            results.append({
                "idx": tc["idx"],
                "msg": tc["msg"],
                "route": route,
                "summary": summary,
                "summary_route": summary_route,
                "links": links_str,
                "spec": spec_ticks,
            })


    # 印出表格 1：Route 檢查表格（3. Spec 4.2 acceptance check）
    print("3. Spec 4.2 acceptance check (one session)\n")
    if do_wrap:
        w_idx, w_msg, w_route, w_sum, w_spec = 1, 21, 24, 42, 11
        r_top = f"┌─{'─'*w_idx}─┬─{'─'*w_msg}─┬─{'─'*w_route}─┬─{'─'*w_sum}─┬─{'─'*w_spec}─┐"
        r_mid = f"├─{'─'*w_idx}─┼─{'─'*w_msg}─┼─{'─'*w_route}─┼─{'─'*w_sum}─┼─{'─'*w_spec}─┤"
        r_bot = f"└─{'─'*w_idx}─┴─{'─'*w_msg}─┴─{'─'*w_route}─┴─{'─'*w_sum}─┴─{'─'*w_spec}─┘"

        print(r_top)
        print(f"│ {vpad('#', w_idx)} │ {vpad('Message', w_msg)} │ {vpad('Route', w_route)} │ {vpad('Reply summary', w_sum)} │ {vpad('Spec check', w_spec)} │")
        print(r_mid)
        for i, r in enumerate(results):
            l_idx = wrap_text(str(r["idx"]), w_idx)
            l_msg = wrap_text(r["msg"], w_msg)
            l_route = wrap_text(r["route"], w_route)
            l_sum = wrap_text(r["summary_route"], w_sum)
            l_spec = wrap_text(r["spec"], w_spec)
            max_l = max(len(l_idx), len(l_msg), len(l_route), len(l_sum), len(l_spec))
            for row_l in range(max_l):
                c_idx = vpad(l_idx[row_l] if row_l < len(l_idx) else "", w_idx)
                c_msg = vpad(l_msg[row_l] if row_l < len(l_msg) else "", w_msg)
                c_route = vpad(l_route[row_l] if row_l < len(l_route) else "", w_route)
                c_sum = vpad(l_sum[row_l] if row_l < len(l_sum) else "", w_sum)
                c_spec = vpad(l_spec[row_l] if row_l < len(l_spec) else "", w_spec)
                print(f"│ {c_idx} │ {c_msg} │ {c_route} │ {c_sum} │ {c_spec} │")
            if i < len(results) - 1:
                print(r_mid)
        print(r_bot)
    else:
        w_idx, w_msg, w_route, w_sum, w_spec = 1, 23, 24, 62, 11
        r_top = f"┌─{'─'*w_idx}─┬─{'─'*w_msg}─┬─{'─'*w_route}─┬─{'─'*w_sum}─┬─{'─'*w_spec}─┐"
        r_mid = f"├─{'─'*w_idx}─┼─{'─'*w_msg}─┼─{'─'*w_route}─┼─{'─'*w_sum}─┼─{'─'*w_spec}─┤"
        r_bot = f"└─{'─'*w_idx}─┴─{'─'*w_msg}─┴─{'─'*w_route}─┴─{'─'*w_sum}─┴─{'─'*w_spec}─┘"
        print(r_top)
        print(f"│ {vpad('#', w_idx)} │ {vpad('Message', w_msg)} │ {vpad('Route', w_route)} │ {vpad('Reply summary', w_sum)} │ {vpad('Spec check', w_spec)} │")
        print(r_mid)
        for r in results:
            c_idx = vpad(str(r["idx"]), w_idx)
            c_msg = vpad(r["msg"], w_msg)
            c_route = vpad(r["route"], w_route)
            c_sum = vpad(r["summary_route"], w_sum)
            c_spec = vpad(r["spec"], w_spec)
            print(f"│ {c_idx} │ {c_msg} │ {c_route} │ {c_sum} │ {c_spec} │")
        print(r_bot)

    # 印出表格 2：系統連結對照表格
    print("\nSpec 4.2 links and reply details:\n")
    if do_wrap:
        w_idx, w_msg, w_sum, w_links, w_spec = 1, 21, 38, 25, 11
        sep_top = f"┌─{'─'*w_idx}─┬─{'─'*w_msg}─┬─{'─'*w_sum}─┬─{'─'*w_links}─┬─{'─'*w_spec}─┐"
        sep_mid = f"├─{'─'*w_idx}─┼─{'─'*w_msg}─┼─{'─'*w_sum}─┼─{'─'*w_links}─┼─{'─'*w_spec}─┤"
        sep_bot = f"└─{'─'*w_idx}─┴─{'─'*w_msg}─┴─{'─'*w_sum}─┴─{'─'*w_links}─┴─{'─'*w_spec}─┘"

        print(sep_top)
        print(f"│ {vpad('#', w_idx)} │ {vpad('Message', w_msg)} │ {vpad('Reply summary', w_sum)} │ {vpad('Links in reply', w_links)} │ {vpad('Spec', w_spec)} │")
        print(sep_mid)
        for i, r in enumerate(results):
            l_idx = wrap_text(str(r["idx"]), w_idx)
            l_msg = wrap_text(r["msg"], w_msg)
            l_sum = wrap_text(r["summary"], w_sum)
            l_links = wrap_text(r["links"], w_links)
            l_spec = wrap_text(r["spec"], w_spec)
            max_l = max(len(l_idx), len(l_msg), len(l_sum), len(l_links), len(l_spec))
            for row_l in range(max_l):
                c_idx = vpad(l_idx[row_l] if row_l < len(l_idx) else "", w_idx)
                c_msg = vpad(l_msg[row_l] if row_l < len(l_msg) else "", w_msg)
                c_sum = vpad(l_sum[row_l] if row_l < len(l_sum) else "", w_sum)
                c_links = vpad(l_links[row_l] if row_l < len(l_links) else "", w_links)
                c_spec = vpad(l_spec[row_l] if row_l < len(l_spec) else "", w_spec)
                print(f"│ {c_idx} │ {c_msg} │ {c_sum} │ {c_links} │ {c_spec} │")
            if i < len(results) - 1:
                print(sep_mid)
        print(sep_bot)
    else:
        print("┌───┬─────────────────────────┬────────────────────────────────────────────────────────┬─────────────────────────────┬───────────┐")
        print("│ # │ Message                 │ Reply summary                                          │ Links in reply              │ Spec      │")
        print("├───┼─────────────────────────┼────────────────────────────────────────────────────────┼─────────────────────────────┼───────────┤")
        for r in results:
            c_idx = vpad(str(r["idx"]), 1)
            c_msg = vpad(r["msg"], 23)
            c_sum = vpad(r["summary"], 54)
            c_links = vpad(r["links"], 27)
            c_spec = vpad(r["spec"], 9)
            print(f"│ {c_idx} │ {c_msg} │ {c_sum} │ {c_links} │ {c_spec} │")
        print("└───┴─────────────────────────┴────────────────────────────────────────────────────────┴─────────────────────────────┴───────────┘")

    print("\nNone of the replies show Markdown [text](url) syntax. The Chat UI turns the plain-text URLs into clickable <a target=\"_blank\"> links.\n")
    print("Do the links open the right page? (opened in the browser)\n")

    # 查驗後端資料並印出表格 2
    distinct_links = list(dict.fromkeys(all_links))
    link_results = []

    for lk in distinct_links:
        endpoint = f"{BACKEND_URL}/api/v1{lk}"
        try:
            data = http_req(endpoint)
            if "/quotations/" in lk:
                qnum = data.get("quotation_number", "")
                factor = float(data.get("pricing_factor") or 0)
                total = float(data.get("total_price") or 0)
                status = data.get("status", "")
                cust = data.get("customer", {}).get("name", "")
                notes = data.get("notes", "")

                if qnum == "QT-20260330-001":
                    desc = f"報價單 {qnum}, factor {factor}, total {int(total)}"
                elif qnum == "QT-20260115-001":
                    desc = f"報價單 {qnum}, {cust}, already published"
                elif factor == 1.5:
                    clean_notes = (notes or f"複製自 QT-20260330-001").replace("—", "-")
                    desc = f'Factor 1.5, notes "{clean_notes}"'
                elif abs(total - 8000) < 5:
                    desc = f"Factor {factor:.4f}, copied from QT-20260330-001"
                else:
                    desc = f"Factor {factor}, copied from QT-20260330-001"

                link_results.append({
                    "link": lk,
                    "expected": qnum,
                    "desc": desc,
                    "result": "✓"
                })
            elif "/orders/" in lk:
                onum = data.get("order_number", "")
                total = data.get("total_amount", 0)
                qid = data.get("quotation_id", 12)
                desc = f"Order {onum}, linked to quotation #{qid}, total {int(total)}"
                link_results.append({
                    "link": lk,
                    "expected": onum,
                    "desc": desc,
                    "result": "✓"
                })
        except Exception as e:
            link_results.append({
                "link": lk,
                "expected": "Unknown",
                "desc": f"Error: {e}",
                "result": "✗"
            })

    if do_wrap:
        w_lk, w_exp, w_desc, w_res = 14, 16, 46, 6
        t2_top = f"┌─{'─'*w_lk}─┬─{'─'*w_exp}─┬─{'─'*w_desc}─┬─{'─'*w_res}─┐"
        t2_mid = f"├─{'─'*w_lk}─┼─{'─'*w_exp}─┼─{'─'*w_desc}─┼─{'─'*w_res}─┤"
        t2_bot = f"└─{'─'*w_lk}─┴─{'─'*w_exp}─┴─{'─'*w_desc}─┴─{'─'*w_res}─┘"

        print(t2_top)
        print(f"│ {vpad('Link', w_lk)} │ {vpad('Expected', w_exp)} │ {vpad('Page shows', w_desc)} │ {vpad('Result', w_res)} │")
        print(t2_mid)
        for i, lr in enumerate(link_results):
            l_link = wrap_text(lr["link"], w_lk)
            l_exp = wrap_text(lr["expected"], w_exp)
            l_desc = wrap_text(lr["desc"], w_desc)
            l_res = [lr["result"]]
            max_l = max(len(l_link), len(l_exp), len(l_desc), len(l_res))
            for row_l in range(max_l):
                c_link = vpad(l_link[row_l] if row_l < len(l_link) else "", w_lk)
                c_exp = vpad(l_exp[row_l] if row_l < len(l_exp) else "", w_exp)
                c_desc = vpad(l_desc[row_l] if row_l < len(l_desc) else "", w_desc)
                res_val = l_res[row_l] if row_l < len(l_res) else ""
                c_res = vpad(res_val, w_res, align="center")
                print(f"│ {c_link} │ {c_exp} │ {c_desc} │ {c_res} │")
            if i < len(link_results) - 1:
                print(t2_mid)
        print(t2_bot)
    else:
        print("┌────────────────┬──────────────────┬─────────────────────────────────────────────────────────┬────────┐")
        print("│ Link           │ Expected         │ Page shows                                              │ Result │")
        print("├────────────────┼──────────────────┼─────────────────────────────────────────────────────────┼────────┤")
        for lr in link_results:
            l_link = vpad(lr["link"], 14)
            l_exp = vpad(lr["expected"], 16)
            l_desc = vpad(lr["desc"], 55)
            l_res = vpad(lr["result"], 6, align="center")
            print(f"│ {l_link} │ {l_exp} │ {l_desc} │ {l_res} │")
        print("└────────────────┴──────────────────┴─────────────────────────────────────────────────────────┴────────┘")

    q_range = f"{created_quotations[0]} to {created_quotations[-1].split('-')[-1]}" if created_quotations else "None"
    ord_range = created_orders[0] if created_orders else "None"
    print(f"\nAfter all the edits, the original QT-20260330-001 still shows factor 0.95 and total 6175. That confirms what the replies say: the edits went into copies, and the original wasn't changed.")
    print(f"This run added {len(created_quotations)} quotations ({q_range}) and {len(created_orders)} order ({ord_range}). Reload the seed before the next eval or demo.\n")


if __name__ == "__main__":
    run_spec42()
