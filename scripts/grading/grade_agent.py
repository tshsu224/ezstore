#!/usr/bin/env python3
"""EZStore 報價單 Agent 自動評分。

用 agents-cli eval 在本機啟動 agent/ 裡的 Agent、跑題庫、打分，外加：
- 程式判定（回覆文字必含／不得含）
- 後端資料核對（原單沒被改、複製單存在、訂單有關聯……）
- 加權計分，輸出 0–100 的分數與逐題報告

用法（在專案根目錄）：
    python3 scripts/grading/grade_agent.py --suite scripts/grading/student-suite.json
    python3 scripts/grading/grade_agent.py --suite ~/ezstore-ta/ta-suite.json --runs 2

只用 Python 標準庫；需要 agents-cli、docker compose（重灌 seed 用）、後端與 MCP Server 在執行。
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_METRIC_WEIGHTS = {
    "link_present": 1.0,
    "refusal_or_action": 1.0,
    "custom_response_quality": 1.0,
}
QUALITY_MAX = 5.0


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def log(msg: str = "") -> None:
    print(msg, flush=True)


def http_json(url: str, method: str = "GET", body: dict | None = None, timeout: float = 10) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


def http_status(url: str, method: str = "GET", body: dict | None = None) -> int:
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def resolve(base: Path, p: str) -> Path:
    path = Path(os.path.expanduser(p))
    return path if path.is_absolute() else (base / path).resolve()


def fnum(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 後端查詢
# ---------------------------------------------------------------------------


class Backend:
    def __init__(self, base_url: str):
        self.api = base_url.rstrip("/") + "/api/v1"

    def health(self) -> bool:
        return http_status(self.api.rsplit("/api/v1", 1)[0] + "/health") == 200

    def quotations(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            d = http_json(f"{self.api}/quotations?page={page}&page_size=100")
            rows = d.get("data") or []
            out.extend(rows)
            if page * 100 >= int(d.get("total", 0)) or not rows:
                return out
            page += 1

    def orders(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            d = http_json(f"{self.api}/orders?page={page}&page_size=100")
            rows = d.get("data") or []
            out.extend(rows)
            if page * 100 >= int(d.get("total", 0)) or not rows:
                return out
            page += 1

    def quotation_by_number(self, number: str) -> dict | None:
        d = http_json(f"{self.api}/quotations?quotation_number={number}&page_size=1")
        rows = d.get("data") or []
        if rows and rows[0].get("quotation_number") == number:
            return rows[0]
        return next((q for q in self.quotations() if q.get("quotation_number") == number), None)

    def snapshot(self) -> dict:
        qs = self.quotations()
        os_ = self.orders()
        return {
            "max_quotation_id": max([q["id"] for q in qs] or [0]),
            "max_order_id": max([o["id"] for o in os_] or [0]),
        }


def run_post_checks(backend: Backend, checks: list[dict], baseline: dict, runs: int = 1) -> list[dict]:
    """回傳 [{name, points, earned, detail}]。runs > 1 時，數量上限（max_new / max_count）按次數放大。"""
    results = []
    try:
        quotations = backend.quotations()
        orders = backend.orders()
    except Exception as e:  # noqa: BLE001
        return [
            {"name": c.get("type", "?"), "points": c.get("points", 0), "earned": 0, "detail": f"後端查詢失敗：{e}"}
            for c in checks
        ]
    new_q = [q for q in quotations if q["id"] > baseline["max_quotation_id"]]
    new_o = [o for o in orders if o["id"] > baseline["max_order_id"]]
    by_number = {q["quotation_number"]: q for q in quotations}

    def copies_of(source: str) -> list[dict]:
        return [q for q in new_q if f"複製自 {source}" in (q.get("notes") or "")]

    for c in checks:
        t = c.get("type")
        pts = float(c.get("points", 1))
        ok = False
        detail = ""
        try:
            if t == "quotation_unchanged":
                q = by_number.get(c["quotation_number"])
                if not q:
                    detail = "找不到該報價單"
                else:
                    problems = []
                    if "pricing_factor" in c and fnum(q["pricing_factor"]) != fnum(c["pricing_factor"]):
                        problems.append(f"因子 {q['pricing_factor']} ≠ {c['pricing_factor']}")
                    if "status" in c and q.get("status") != c["status"]:
                        problems.append(f"狀態 {q.get('status')} ≠ {c['status']}")
                    if "total_price" in c and fnum(q["total_price"]) != fnum(c["total_price"]):
                        problems.append(f"總價 {q['total_price']} ≠ {c['total_price']}")
                    ok = not problems
                    detail = "原單未被更動" if ok else "；".join(problems)
            elif t == "copies_created":
                n = len(copies_of(c["source"]))
                lo = int(c.get("min_count", 1))
                hi = None if c.get("max_count") is None else int(c["max_count"]) * runs
                ok = n >= lo and (hi is None or n <= hi)
                detail = f"複製自 {c['source']} 的新單 {n} 張（要求 ≥{lo}{'' if hi is None else f'，≤{hi}'}）"
            elif t == "new_quotation_with_factor":
                hits = [q for q in copies_of(c["source"]) if fnum(q["pricing_factor"]) == fnum(c["pricing_factor"])]
                ok = bool(hits)
                detail = (
                    f"找到因子 {c['pricing_factor']} 的複製單 {hits[0]['quotation_number']}"
                    if ok
                    else f"沒有複製自 {c['source']} 且因子為 {c['pricing_factor']} 的新單"
                )
            elif t == "total_price_near":
                tol = float(c.get("tolerance", 1))
                hits = [
                    q for q in copies_of(c["source"])
                    if fnum(q["total_price"]) is not None and abs(fnum(q["total_price"]) - float(c["target"])) <= tol
                ]
                ok = bool(hits)
                detail = (
                    f"複製單 {hits[0]['quotation_number']} 總價 {hits[0]['total_price']}（目標 {c['target']}）"
                    if ok
                    else f"沒有複製自 {c['source']} 且總價在 {c['target']}±{tol} 的新單"
                )
            elif t == "order_linked":
                q = by_number.get(c["quotation_number"])
                hits = [o for o in new_o if q and o.get("quotation_id") == q["id"]]
                ok = bool(hits)
                detail = (
                    f"訂單 {hits[0]['order_number']} 關聯 {c['quotation_number']}"
                    if ok
                    else f"沒有新訂單關聯 {c['quotation_number']}"
                )
            elif t == "no_new_quotations":
                allowed = int(c.get("max_new", 0)) * runs
                ok = len(new_q) <= allowed
                detail = f"新增報價單 {len(new_q)} 張（允許 ≤{allowed}）"
            elif t == "no_new_orders":
                allowed = int(c.get("max_new", 0)) * runs
                ok = len(new_o) <= allowed
                detail = f"新增訂單 {len(new_o)} 筆（允許 ≤{allowed}）"
            else:
                detail = f"未知的核對類型 {t}"
        except Exception as e:  # noqa: BLE001
            detail = f"核對時出錯：{e}"
        results.append({"name": c.get("name") or t, "points": pts, "earned": pts if ok else 0.0, "detail": detail})
    return results


# ---------------------------------------------------------------------------
# agents-cli eval
# ---------------------------------------------------------------------------


def run_eval(agent_dir: Path, dataset: Path, config: Path, output: Path) -> tuple[bool, str]:
    cmd = [
        "agents-cli", "eval", "run",
        "--dataset", str(dataset),
        "--config", str(config),
        "--output", str(output),
    ]
    proc = subprocess.run(
    cmd,
    cwd=agent_dir,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    tail = "\n".join((stdout + "\n" + stderr).strip().splitlines()[-30:])
    return proc.returncode == 0, tail


def latest_results(output: Path) -> Path | None:
    files = sorted(glob.glob(str(output / "results_*.json")))
    return Path(files[-1]) if files else None


def parse_results(path: Path) -> dict[str, dict]:
    """{case_id: {"text": str, "metrics": {name: score|None}, "reasons": {name: str}}}"""
    d = json.loads(path.read_text(encoding="utf-8"))
    ds = d.get("evaluation_dataset") or []
    if isinstance(ds, dict):
        ds = [ds]
    cases: list[dict] = []
    for x in ds:
        cases.extend(x.get("eval_cases", []) if isinstance(x, dict) else [])
    out: dict[str, dict] = {}
    for i, r in enumerate(d.get("eval_case_results", [])):
        case = cases[i] if i < len(cases) else {}
        cid = case.get("eval_case_id") or f"case_{i}"
        text = ""
        resp = (case.get("responses") or [{}])[0].get("response") or {}
        text = "".join(p.get("text", "") for p in (resp.get("parts") or []) if isinstance(p, dict))
        mr = ((r.get("response_candidate_results") or [{}])[0].get("metric_results")) or {}
        metrics = {k: v.get("score") for k, v in mr.items()}
        reasons = {k: (v.get("explanation") or v.get("error_message") or "") for k, v in mr.items()}
        out[cid] = {"text": text, "metrics": metrics, "reasons": reasons}
    return out


# ---------------------------------------------------------------------------
# 逐案計分
# ---------------------------------------------------------------------------


def score_case(case_cfg: dict, result: dict) -> tuple[float, list[tuple[str, float, float, str]]]:
    """回傳 (0–1 得分, [(元件名, 得分, 權重, 說明)])"""
    weights = dict(DEFAULT_METRIC_WEIGHTS)
    weights.update({k: float(v) for k, v in (case_cfg.get("metrics") or {}).items()})
    parts: list[tuple[str, float, float, str]] = []
    metrics = result.get("metrics", {})
    reasons = result.get("reasons", {})
    text = result.get("text", "")

    for name, w in weights.items():
        if w <= 0:
            continue
        raw = metrics.get(name)
        if raw is None:
            parts.append((name, 0.0, w, "未評到：" + (reasons.get(name) or "指標沒有結果")[:160]))
            continue
        s = float(raw) / QUALITY_MAX if name == "custom_response_quality" else float(raw)
        parts.append((name, max(0.0, min(1.0, s)), w, (reasons.get(name) or "")[:160]))

    for chk in case_cfg.get("checks") or []:
        w = float(chk.get("weight", 1))
        if "must_contain" in chk:
            pats = chk["must_contain"] if isinstance(chk["must_contain"], list) else [chk["must_contain"]]
            hit = any(re.search(p, text) for p in pats)
            parts.append(("must_contain", 1.0 if hit else 0.0, w, "符合：" + " | ".join(pats) if hit else "缺少：" + " | ".join(pats)))
        if "must_not_contain" in chk:
            pats = chk["must_not_contain"] if isinstance(chk["must_not_contain"], list) else [chk["must_not_contain"]]
            bad = [p for p in pats if re.search(p, text)]
            parts.append(("must_not_contain", 0.0 if bad else 1.0, w, ("出現了不該有的：" + " | ".join(bad)) if bad else "沒有出現：" + " | ".join(pats)))
        if "must_start_with" in chk:
            ok = text.strip().startswith(chk["must_start_with"])
            parts.append(("must_start_with", 1.0 if ok else 0.0, w, f"開頭應為「{chk['must_start_with']}」"))

    total_w = sum(w for _, _, w, _ in parts)
    score = sum(s * w for _, s, w, _ in parts) / total_w if total_w else 0.0
    return score, parts


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def preflight(repo: Path, agent_dir: Path, backend: Backend, mcp_url: str) -> list[str]:
    problems = []
    if not (agent_dir / "quotation_agent").is_dir():
        problems.append(f"找不到 {agent_dir / 'quotation_agent'}（Agent 尚未建立，或 app 資料夾名稱不是 quotation_agent）")
    if shutil.which("agents-cli") is None:
        problems.append("找不到 agents-cli（uv tool install google-agents-cli）")
    if not backend.health():
        problems.append("後端 /health 不通（docker compose up -d db backend）")
    if http_status(mcp_url, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}) in (0, 500, 502, 503):
        problems.append(f"MCP Server {mcp_url} 不通（docker compose up -d mcp-server）")
    env = agent_dir / ".env"
    if not env.exists():
        problems.append("agent/.env 不存在（cp agent/.env.example agent/.env 並填憑證）")
    else:
        t = env.read_text(encoding="utf-8", errors="replace")
        has_key = re.search(r"^\s*GEMINI_API_KEY\s*=\s*\S", t, re.M) or re.search(r"^\s*GOOGLE_API_KEY\s*=\s*\S", t, re.M)
        has_vertex = re.search(r"^\s*GOOGLE_GENAI_USE_VERTEXAI\s*=\s*true", t, re.M | re.I) and re.search(r"^\s*GOOGLE_CLOUD_PROJECT\s*=\s*\S", t, re.M)
        if not (has_key or has_vertex):
            problems.append("agent/.env 沒有模型憑證（GEMINI_API_KEY 或 Vertex 設定）")
        if "localhost:8010" not in t and "127.0.0.1:8010" not in t:
            problems.append("agent/.env 的 MCP_URL 不是 http://localhost:8010/mcp（本機評分需要連 compose 開出來的 8010 埠）")
    return problems


def reseed(repo: Path) -> bool:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "ezstore", "-f", "/scripts/seed-test-data.sql"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True, help="suite JSON 檔")
    ap.add_argument("--repo", default=None, help="專案根目錄（預設：此腳本往上兩層）")
    ap.add_argument("--agent-dir", default="agent")
    ap.add_argument("--backend", default="http://localhost:8080")
    ap.add_argument("--mcp-url", default="http://localhost:8010/mcp")
    ap.add_argument("--runs", type=int, default=1, help="每組跑幾次取平均（降低 LLM 評審浮動）")
    ap.add_argument("--no-reseed", action="store_true", help="略過 suite 要求的重灌 seed")
    ap.add_argument("--only", default=None, help="只跑指定群組 id（逗號分隔）")
    ap.add_argument("--min-score", type=float, default=None, help="低於此分數時以非 0 結束（CI 用）")
    args = ap.parse_args()

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent.parent
    agent_dir = (repo / args.agent_dir).resolve()
    suite_path = Path(os.path.expanduser(args.suite)).resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    suite_dir = suite_path.parent
    config = resolve(suite_dir, suite.get("config", "eval_config.yaml"))
    backend = Backend(args.backend)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = repo / "artifacts" / "grading" / stamp
    out_root.mkdir(parents=True, exist_ok=True)

    log(f"== EZStore Agent 評分：{suite.get('name', suite_path.name)} ==")
    log(f"專案：{repo}    Agent：{agent_dir}    結果：{out_root}")
    problems = preflight(repo, agent_dir, backend, args.mcp_url)
    for p in problems:
        log(f"  ⚠ {p}")
    if any("找不到" in p or "不通" in p for p in problems):
        log("前置條件不符，無法評分。")
        return 2

    only = set(args.only.split(",")) if args.only else None
    group_reports: list[dict] = []
    total = 0.0
    total_weight = 0.0

    for g in suite.get("groups", []):
        gid = g["id"]
        if only and gid not in only:
            continue
        weight = float(g.get("weight", 0))
        total_weight += weight
        dataset = resolve(suite_dir, g["dataset"])
        post_checks = g.get("post_checks") or []
        post_points = sum(float(c.get("points", 1)) for c in post_checks)
        case_points = max(0.0, weight - post_points)
        log(f"\n-- 群組 {gid}（權重 {weight:g}；題目 {case_points:g} 分 + 後端核對 {post_points:g} 分）--")

        if not dataset.exists():
            log(f"  ✗ 題庫不存在：{dataset}")
            group_reports.append({"id": gid, "weight": weight, "earned": 0.0, "error": f"dataset missing: {dataset}", "cases": [], "post_checks": []})
            continue

        if g.get("reseed") and not args.no_reseed:
            log("  重灌測試資料 …" + (" OK" if reseed(repo) else " 失敗（繼續，但後端核對可能不準）"))
        baseline = backend.snapshot()

        # 跑 N 次 eval，逐題累積元件分數
        case_cfgs: dict[str, dict] = g.get("cases") or {}
        acc: dict[str, list[tuple[float, list]]] = {}
        texts: dict[str, str] = {}
        run_errors: list[str] = []
        for r in range(1, args.runs + 1):
            out_dir = out_root / gid / f"run{r}"
            out_dir.mkdir(parents=True, exist_ok=True)
            log(f"  agents-cli eval run（{r}/{args.runs}）…")
            ok, tail = run_eval(agent_dir, dataset, config, out_dir)
            res_file = latest_results(out_dir)
            if not ok or res_file is None:
                run_errors.append(tail)
                log("  ✗ eval 失敗：\n" + "\n".join("     " + ln for ln in tail.splitlines()[-12:]))
                continue
            results = parse_results(res_file)
            for cid, res in results.items():
                s, parts = score_case(case_cfgs.get(cid, {}), res)
                acc.setdefault(cid, []).append((s, parts))
                texts[cid] = res["text"]

        case_rows = []
        sum_w = 0.0
        sum_s = 0.0
        for cid, runs in acc.items():
            cw = float(case_cfgs.get(cid, {}).get("weight", 1))
            avg = sum(s for s, _ in runs) / len(runs)
            sum_w += cw
            sum_s += avg * cw
            last_parts = runs[-1][1]
            case_rows.append({"id": cid, "weight": cw, "score": avg, "parts": last_parts, "text": texts.get(cid, "")})
            flag = "✓" if avg >= 0.999 else ("△" if avg >= 0.5 else "✗")
            log(f"  {flag} {cid:<34} {avg*100:6.1f}%  " + "  ".join(f"{n}={s:.2f}" for n, s, _, _ in last_parts))
        ratio = (sum_s / sum_w) if sum_w else 0.0

        pc = run_post_checks(backend, post_checks, baseline, runs=args.runs) if post_checks else []
        for r in pc:
            mark = "ℹ" if r["points"] == 0 else ("✓" if r["earned"] else "✗")
            log(f"  {mark} 核對 {r['name']:<28} {r['earned']:g}/{r['points']:g}  {r['detail']}")

        earned = ratio * case_points + sum(r["earned"] for r in pc)
        total += earned
        log(f"  小計 {earned:.1f} / {weight:g}")
        group_reports.append({
            "id": gid, "weight": weight, "earned": earned, "case_points": case_points,
            "case_ratio": ratio, "cases": case_rows, "post_checks": pc, "run_errors": run_errors,
        })

    final = total if total_weight else 0.0
    log(f"\n==================== 總分 {final:.1f} / {total_weight:g} ====================")

    report = {
        "suite": suite.get("name", suite_path.name), "timestamp": stamp, "runs": args.runs,
        "total": final, "total_weight": total_weight, "groups": group_reports,
    }
    (out_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# Agent 評分報告：{report['suite']}", "", f"- 時間：{stamp}", f"- 每組執行次數：{args.runs}", f"- **總分：{final:.1f} / {total_weight:g}**", ""]
    for gr in group_reports:
        md.append(f"## 群組 {gr['id']}：{gr['earned']:.1f} / {gr['weight']:g}")
        if gr.get("error"):
            md.append(f"- 錯誤：{gr['error']}")
        md.append("")
        md.append("| 案例 | 得分 | 元件 |")
        md.append("|---|---|---|")
        for c in gr["cases"]:
            comp = "<br>".join(f"{n}={s:.2f}（{d}）" for n, s, _, d in c["parts"])
            md.append(f"| `{c['id']}` | {c['score']*100:.0f}% | {comp} |")
        if gr["post_checks"]:
            md.append("")
            md.append("| 後端核對 | 得分 | 說明 |")
            md.append("|---|---|---|")
            for r in gr["post_checks"]:
                md.append(f"| {r['name']} | {r['earned']:g}/{r['points']:g} | {r['detail']} |")
        md.append("")
        md.append("<details><summary>每題回覆原文</summary>")
        md.append("")
        for c in gr["cases"]:
            md.append(f"**{c['id']}**")
            md.append("")
            md.append("```")
            md.append(c["text"].strip() or "(空)")
            md.append("```")
            md.append("")
        md.append("</details>")
        md.append("")
    (out_root / "report.md").write_text("\n".join(md), encoding="utf-8")
    log(f"報告：{out_root / 'report.md'}")

    if args.min_score is not None and final < args.min_score:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
