import re
import html

def beautify():
    with open('report.html', 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract body content
    body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', content)
    if not body_match:
        print("Error: Could not find <body> tag")
        return
    body = body_match.group(1)

    # 1. Remove the old vscode inline mermaid script inside body
    body = re.sub(r'<script>\s*mermaid\.initialize[\s\S]*?</script>', '', body)

    # 2. Extract and fix Mermaid diagrams
    # Replace <pre><code class="language-mermaid"><div class="mermaid">...</div></code></pre>
    # with clean <div class="diagram-card"><div class="diagram-bar"><span class="diagram-icon">📊</span><span class="diagram-title">系統架構圖 / 流程圖</span></div><div class="mermaid">...</div></div>
    def fix_mermaid(match):
        code_content = match.group(1)
        # remove inner <div class="mermaid"> if present
        clean_code = re.sub(r'</?div[^>]*>', '', code_content).strip()
        # determine title based on content
        title = "系統工作流程架構圖 (Workflow & Architecture)"
        if "sequenceDiagram" in clean_code:
            title = "A2A (Agent-to-Agent) 跨系統即時協同循序圖"
        elif "classDiagram" in clean_code:
            title = "OKF (Open Knowledge Fabric) 領域知識架構類別圖"
        elif "START([START])" in clean_code:
            title = "Quotation Agent - ADK Graph Workflow 狀態機轉移圖"
        elif "Quotation Agent :8080" in clean_code:
            title = "EZStore 雙 Agent 智慧商務系統整體架構拓撲圖"

        return f'''
<div class="diagram-card">
  <div class="diagram-bar">
    <div class="diagram-badge">
      <span class="diagram-dot"></span>
      <span class="diagram-title">{title}</span>
    </div>
    <span class="diagram-tag">Mermaid Interactive SVG</span>
  </div>
  <div class="diagram-body">
    <div class="mermaid">
{clean_code}
    </div>
  </div>
</div>
'''

    body = re.sub(r'<pre><code class="language-mermaid">([\s\S]*?)</code></pre>', fix_mermaid, body)

    # 3. Enhance Figures and Screenshots
    # Replace <p><img src="..." alt="..."></p> or <img src="..." alt="...">
    # with structured <figure class="figure-card">...
    def fix_image(match):
        full_tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', full_tag)
        alt_match = re.search(r'alt=["\']([^"\']+)["\']', full_tag)
        src = src_match.group(1) if src_match else ""
        alt = alt_match.group(1) if alt_match else ""

        # Determine badge & title
        badge = "📸 系統運行截圖"
        desc = alt
        if "checkpoint-1" in src:
            badge = "檢驗點 1 · Dev-UI"
            desc = "ADK Playground / Dev-UI 工作流程視覺化與即時狀態圖"
        elif "checkpoint-2-chat-ui-1" in src:
            badge = "檢驗點 2 · Chat UI (Part 1)"
            desc = "查詢筆電規格與折扣政策諮詢（意圖分類為 inquiry 並正確引導）"
        elif "checkpoint-2-chat-ui-2" in src:
            badge = "檢驗點 2 · Chat UI (Part 2)"
            desc = "跨產品比價與條件比對（展示表格化比對分析）"
        elif "checkpoint-2-chat-ui-3" in src:
            badge = "檢驗點 2 · Chat UI (Part 3)"
            desc = "提出退換貨申請（觸發確認流程與安全防護機制）"
        elif "checkpoint-3" in src:
            badge = "檢驗點 3 · Guardrails"
            desc = "Guardrails 安全防護測試（針對越獄攻擊、非商務話題與惡意注入之防禦成效）"
        elif "checkpoint-4" in src:
            badge = "檢驗點 4 · Actions Eval"
            desc = "Actions 執行正確性測試（6 項核心業務動作之自動化評估）"
        elif "checkpoint-5-spec42-1" in src:
            badge = "檢驗點 5 · 表 1"
            desc = "路由與參數摘要表（涵蓋 9 輪連續對話之狀態遷移、意圖辨識與參數追蹤）"
        elif "checkpoint-5-spec42-2" in src:
            badge = "檢驗點 5 · 表 2"
            desc = "系統連結摘要表（Spec 4.2 驗收之關聯連結、狀態碼與各節點回應摘要）"
        elif "checkpoint-5-spec42-3" in src:
            badge = "檢驗點 5 · 表 3"
            desc = "使用者查詢與 Agent 回應摘要表（終端機全自動多輪驗收完整執行紀錄）"

        return f'''
<figure class="figure-card">
  <div class="figure-header">
    <span class="figure-badge">{badge}</span>
    <span class="figure-file">{src}</span>
  </div>
  <div class="figure-viewport">
    <img src="{src}" alt="{alt}" loading="lazy">
  </div>
  <figcaption class="figure-caption">
    <strong>{desc}</strong>
  </figcaption>
</figure>
'''

    # Match images wrapped in <p> (all 9 images)
    body = re.sub(r'<p>\s*(<img[^>]+>)\s*</p>', fix_image, body)

    # 4. Enhance Terminal / Code blocks (pre hljs or pre code)
    def fix_code_block(match):
        pre_tag = match.group(0)
        # If this is already a diagram or figure, skip
        if 'class="mermaid"' in pre_tag or 'class="language-mermaid"' in pre_tag:
            return pre_tag
        
        # Check title
        title = "Terminal Console / Script"
        if "verify_spec42" in pre_tag or "Spec 4.2" in pre_tag or "A2A" in pre_tag:
            title = "bash - Acceptance Test Verification Output"
        elif "copy .env.example" in pre_tag or "docker-compose" in pre_tag:
            title = "bash - Deployment & Quickstart Commands"
        elif "vlen" in pre_tag or "def " in pre_tag:
            title = "python - East Asian Width Alignment Helper"

        return f'''
<div class="terminal-card">
  <div class="terminal-bar">
    <div class="terminal-controls">
      <span class="term-dot term-red"></span>
      <span class="term-dot term-yellow"></span>
      <span class="term-dot term-green"></span>
    </div>
    <span class="terminal-title">{title}</span>
    <span class="terminal-shell">bash / utf-8</span>
  </div>
  <div class="terminal-body">
{pre_tag}
  </div>
</div>
'''
    body = re.sub(r'<pre\b[^>]*>[\s\S]*?</pre>', fix_code_block, body)

    # 5. Enhance Headings and Checkpoints
    # Add badges to checkpoints: 【檢查點 1】 -> <span class="checkpoint-pill">檢查點 1</span>
    body = re.sub(r'【檢查點\s*([0-9]+)】', r'<span class="checkpoint-pill">✓ 檢查點 \1</span>', body)

    # 6. Enhance Table styling
    # Wrap tables in table-container with responsive scroll
    body = re.sub(r'(<table[\s\S]*?</table>)', r'<div class="table-container">\1</div>', body)

    # Enhance status badges in tables
    body = re.sub(r'<td>(✓\s*通過|Pass)</td>', r'<td><span class="badge badge-success">\1</span></td>', body)
    body = re.sub(r'<td>(HIGH)</td>', r'<td><span class="badge badge-warning">\1</span></td>', body)
    body = re.sub(r'<td>(TIER_1_AUTO)</td>', r'<td><span class="badge badge-info">\1</span></td>', body)
    body = re.sub(r'<td>(5\.00\s*/\s*5\.00)</td>', r'<td><span class="badge badge-score">\1</span></td>', body)

    # 7. Construct Modern Hero Header
    # Replace top h1 & subheaders with exquisite hero banner
    hero_html = '''
<header class="hero-banner">
  <div class="hero-badge-group">
    <span class="hero-chip chip-primary">Google ADK 2.11</span>
    <span class="hero-chip chip-cyan">Gemini 3.8 Flash</span>
    <span class="hero-chip chip-indigo">A2A Protocol</span>
    <span class="hero-chip chip-purple">Open Knowledge Fabric (OKF)</span>
    <span class="hero-chip chip-success">5/5 檢查點驗收通過</span>
  </div>
  <h1 class="hero-title">EZStore 雙 Agent 智慧商務系統專案報告書</h1>
  <p class="hero-subtitle">
    以 <strong>Google ADK Graph Workflow</strong> 為核心，實現報價協同 (Quotation Agent) 與庫存補貨 (Inventory Agent) 之跨系統 A2A 自主協作架構
  </p>
  <div class="hero-meta-grid">
    <div class="meta-item">
      <span class="meta-label">專案 Repository</span>
      <a class="meta-val meta-link" href="https://github.com/tshsu224/ezstore/tree/feature/ezstore-agent-develop" target="_blank" rel="noopener">
        tshsu224/ezstore <span class="external-icon">↗</span>
      </a>
    </div>
    <div class="meta-item">
      <span class="meta-label">工作分支</span>
      <span class="meta-val code-val">feature/ezstore-agent-develop</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">技術架構</span>
      <span class="meta-val">ADK 2.11 · Go Backend · Vue 3 · Docker</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">驗收狀態</span>
      <span class="meta-val text-success">✓ 全數規格與 Eval 測試 100% 通過</span>
    </div>
  </div>
</header>
'''
    # Replace the existing top h1 and paragraph
    body = re.sub(r'<h1[^>]*>EZStore[\s\S]*?</h1>\s*<p><strong>結合[\s\S]*?</strong></p>\s*<hr>', hero_html, body, count=1)

    # 8. Wrap TOC into a modern TOC card
    def fix_toc(match):
        toc_content = match.group(0)
        return f'''
<nav class="toc-wrapper">
  <div class="toc-header">
    <span class="toc-icon">📑</span>
    <span class="toc-title">報告書章節目錄 (Quick Navigation)</span>
  </div>
  <div class="toc-body">
    {toc_content}
  </div>
</nav>
'''
    body = re.sub(r'<h2 id="目錄">目錄</h2>\s*<ol>[\s\S]*?</ol>', fix_toc, body, count=1)

    # 9. Build Full Clean HTML Template with Modern CSS and Mermaid.js
    full_html = f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EZStore 雙 Agent 智慧商務系統專案報告書</title>
  
  <!-- Web Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+TC:wght@400;500;700;900&display=swap" rel="stylesheet">
  
  <!-- Mermaid.js for Interactive Diagram Rendering -->
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>

  <style>
    :root {{
      --primary: #4338ca;
      --primary-hover: #3730a3;
      --primary-light: #e0e7ff;
      --secondary: #0ea5e9;
      --accent: #8b5cf6;
      --success: #10b981;
      --success-light: #d1fae5;
      --warning: #f59e0b;
      --warning-light: #fef3c7;
      --danger: #ef4444;
      --slate-50: #f8fafc;
      --slate-100: #f1f5f9;
      --slate-200: #e2e8f0;
      --slate-300: #cbd5e1;
      --slate-400: #94a3b8;
      --slate-600: #475569;
      --slate-700: #334155;
      --slate-800: #1e293b;
      --slate-900: #0f172a;
      --card-bg: #ffffff;
      --text-main: #1e293b;
      --text-muted: #64748b;
      --border-color: #e2e8f0;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --radius-xl: 20px;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
      --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -4px rgba(0, 0, 0, 0.03);
      --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.03);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: 'Inter', 'Noto Sans TC', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.8;
      color: var(--text-main);
      background-color: #f8fafc;
      font-size: 15.5px;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      padding: 40px 20px;
    }}

    .container {{
      max-width: 1160px;
      margin: 0 auto;
      background: var(--card-bg);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-xl);
      border: 1px solid var(--slate-200);
      overflow: hidden;
      padding: 60px 70px;
    }}

    /* Hero Header */
    .hero-banner {{
      background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #1e293b 100%);
      color: #ffffff;
      padding: 45px 50px;
      border-radius: var(--radius-lg);
      margin-bottom: 50px;
      position: relative;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
      border: 1px solid rgba(255, 255, 255, 0.1);
    }}

    .hero-banner::after {{
      content: '';
      position: absolute;
      top: -50%;
      right: -20%;
      width: 500px;
      height: 500px;
      background: radial-gradient(circle, rgba(99, 102, 241, 0.25) 0%, rgba(0,0,0,0) 70%);
      pointer-events: none;
    }}

    .hero-badge-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 20px;
      position: relative;
      z-index: 1;
    }}

    .hero-chip {{
      font-size: 12px;
      font-weight: 700;
      padding: 4px 12px;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: inline-flex;
      align-items: center;
    }}

    .chip-primary {{ background: rgba(99, 102, 241, 0.25); color: #a5b4fc; border: 1px solid rgba(165, 180, 252, 0.3); }}
    .chip-cyan {{ background: rgba(14, 165, 233, 0.25); color: #7dd3fc; border: 1px solid rgba(125, 211, 252, 0.3); }}
    .chip-indigo {{ background: rgba(129, 140, 248, 0.25); color: #c7d2fe; border: 1px solid rgba(199, 210, 254, 0.3); }}
    .chip-purple {{ background: rgba(168, 85, 247, 0.25); color: #d8b4fe; border: 1px solid rgba(216, 180, 254, 0.3); }}
    .chip-success {{ background: rgba(16, 185, 129, 0.25); color: #6ee7b7; border: 1px solid rgba(110, 231, 183, 0.4); }}

    .hero-title {{
      font-size: 32px;
      font-weight: 900;
      line-height: 1.3;
      letter-spacing: -0.5px;
      margin-bottom: 16px;
      color: #ffffff;
      position: relative;
      z-index: 1;
    }}

    .hero-subtitle {{
      font-size: 17px;
      color: #cbd5e1;
      line-height: 1.6;
      margin-bottom: 30px;
      max-width: 900px;
      position: relative;
      z-index: 1;
    }}

    .hero-subtitle strong {{
      color: #38bdf8;
    }}

    .hero-meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 15px;
      background: rgba(15, 23, 42, 0.6);
      padding: 18px 24px;
      border-radius: var(--radius-md);
      border: 1px solid rgba(255, 255, 255, 0.08);
      position: relative;
      z-index: 1;
    }}

    .meta-item {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .meta-label {{
      font-size: 11.5px;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-weight: 600;
    }}

    .meta-val {{
      font-size: 13.5px;
      color: #f1f5f9;
      font-weight: 600;
    }}

    .meta-link {{
      color: #60a5fa;
      text-decoration: none;
      transition: color 0.2s;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}

    .meta-link:hover {{
      color: #93c5fd;
      text-decoration: underline;
    }}

    .code-val {{
      font-family: 'JetBrains Mono', monospace;
      color: #f472b6;
      font-size: 12.5px;
    }}

    .text-success {{
      color: #34d399 !important;
    }}

    /* TOC (目錄) Card */
    .toc-wrapper {{
      background: #f8fafc;
      border: 1px solid var(--slate-200);
      border-radius: var(--radius-lg);
      padding: 28px 32px;
      margin-bottom: 50px;
      box-shadow: var(--shadow-sm);
    }}

    .toc-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 20px;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--slate-200);
    }}

    .toc-icon {{
      font-size: 22px;
    }}

    .toc-title {{
      font-size: 19px;
      font-weight: 800;
      color: var(--slate-800);
    }}

    .toc-body ol {{
      list-style-type: none;
      counter-reset: toc-counter;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 10px 30px;
    }}

    .toc-body > ol > li {{
      counter-increment: toc-counter;
      position: relative;
      padding-left: 28px;
      font-size: 14.5px;
      font-weight: 600;
    }}

    .toc-body > ol > li::before {{
      content: counter(toc-counter);
      position: absolute;
      left: 0;
      top: 1px;
      width: 20px;
      height: 20px;
      background: var(--primary-light);
      color: var(--primary);
      border-radius: 50%;
      font-size: 11px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
    }}

    .toc-body a {{
      color: var(--slate-700);
      text-decoration: none;
      transition: all 0.2s;
    }}

    .toc-body a:hover {{
      color: var(--primary);
      text-decoration: underline;
    }}

    .toc-body ul {{
      margin-top: 6px;
      margin-bottom: 8px;
      list-style-type: disc;
      padding-left: 20px;
      font-weight: 400;
      font-size: 13.5px;
      color: var(--slate-600);
    }}

    /* Typography & Headings */
    h1, h2, h3, h4, h5, h6 {{
      color: var(--slate-900);
      font-weight: 800;
      line-height: 1.4;
      margin-top: 40px;
      margin-bottom: 16px;
    }}

    h2 {{
      font-size: 24px;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--slate-200);
      display: flex;
      align-items: center;
      gap: 12px;
      position: relative;
    }}

    h2::before {{
      content: '';
      display: inline-block;
      width: 6px;
      height: 24px;
      background: linear-gradient(to bottom, var(--primary), var(--secondary));
      border-radius: 4px;
    }}

    h3 {{
      font-size: 19px;
      margin-top: 32px;
      color: var(--slate-800);
      border-left: 3px solid var(--secondary);
      padding-left: 12px;
    }}

    h4 {{
      font-size: 16.5px;
      margin-top: 24px;
      color: var(--slate-700);
    }}

    h5 {{
      font-size: 15px;
      margin-top: 18px;
      color: var(--slate-700);
    }}

    p {{
      margin-bottom: 16px;
      color: var(--slate-700);
    }}

    ul, ol {{
      margin-bottom: 18px;
      padding-left: 26px;
      color: var(--slate-700);
    }}

    li {{
      margin-bottom: 6px;
    }}

    strong {{
      font-weight: 700;
      color: var(--slate-900);
    }}

    hr {{
      border: none;
      height: 1px;
      background: var(--slate-200);
      margin: 40px 0;
    }}

    a {{
      color: var(--primary);
      text-decoration: none;
    }}

    a:hover {{
      text-decoration: underline;
    }}

    /* Checkpoint Pill */
    .checkpoint-pill {{
      display: inline-flex;
      align-items: center;
      background: #ecfdf5;
      color: #065f46;
      border: 1px solid #a7f3d0;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 13.5px;
      font-weight: 700;
      margin-right: 8px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }}

    /* Code & Inlines */
    code:not(pre code) {{
      background: #f1f5f9;
      color: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: 'JetBrains Mono', Consolas, monospace;
      font-size: 13.5px;
      border: 1px solid #e2e8f0;
    }}

    /* Diagram Card (Mermaid) */
    .diagram-card {{
      background: #ffffff;
      border: 1px solid var(--slate-200);
      border-radius: var(--radius-lg);
      margin: 30px 0;
      overflow: hidden;
      box-shadow: var(--shadow-md);
    }}

    .diagram-bar {{
      background: #f8fafc;
      padding: 12px 20px;
      border-bottom: 1px solid var(--slate-200);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .diagram-badge {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .diagram-dot {{
      width: 10px;
      height: 10px;
      background: var(--secondary);
      border-radius: 50%;
      display: inline-block;
      box-shadow: 0 0 6px var(--secondary);
    }}

    .diagram-title {{
      font-size: 14.5px;
      font-weight: 700;
      color: var(--slate-800);
    }}

    .diagram-tag {{
      font-size: 11.5px;
      font-weight: 600;
      background: var(--primary-light);
      color: var(--primary);
      padding: 2px 8px;
      border-radius: 4px;
    }}

    .diagram-body {{
      padding: 30px 20px;
      display: flex;
      justify-content: center;
      align-items: center;
      background: #ffffff;
      overflow-x: auto;
    }}

    .diagram-body .mermaid {{
      width: 100%;
      text-align: center;
    }}

    .diagram-body .mermaid svg {{
      max-width: 100% !important;
      height: auto !important;
    }}

    /* Figure Card (Screenshots) */
    .figure-card {{
      background: #ffffff;
      border: 1px solid var(--slate-200);
      border-radius: var(--radius-lg);
      margin: 32px 0;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
      transition: transform 0.2s, box-shadow 0.2s;
    }}

    .figure-card:hover {{
      box-shadow: var(--shadow-xl);
    }}

    .figure-header {{
      background: #f8fafc;
      padding: 10px 18px;
      border-bottom: 1px solid var(--slate-200);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
    }}

    .figure-badge {{
      font-weight: 700;
      background: #e0e7ff;
      color: #3730a3;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 12px;
    }}

    .figure-file {{
      font-family: 'JetBrains Mono', monospace;
      color: var(--slate-400);
    }}

    .figure-viewport {{
      padding: 12px;
      background: #f1f5f9;
      display: flex;
      justify-content: center;
    }}

    .figure-viewport img {{
      max-width: 100%;
      height: auto;
      border-radius: var(--radius-sm);
      border: 1px solid var(--slate-300);
      box-shadow: var(--shadow-md);
      display: block;
    }}

    .figure-caption {{
      padding: 14px 20px;
      background: #ffffff;
      border-top: 1px solid var(--slate-200);
      font-size: 14px;
      color: var(--slate-700);
      line-height: 1.5;
    }}

    /* Terminal Console Card */
    .terminal-card {{
      background: #0f172a;
      border-radius: var(--radius-md);
      margin: 28px 0;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
      border: 1px solid #1e293b;
    }}

    .terminal-bar {{
      background: #1e293b;
      padding: 9px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #334155;
    }}

    .terminal-controls {{
      display: flex;
      gap: 7px;
    }}

    .term-dot {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      display: inline-block;
    }}

    .term-red {{ background: #ef4444; }}
    .term-yellow {{ background: #f59e0b; }}
    .term-green {{ background: #10b981; }}

    .terminal-title {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      color: #94a3b8;
      font-weight: 500;
    }}

    .terminal-shell {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      color: #64748b;
    }}

    .terminal-body {{
      padding: 18px 22px;
      overflow-x: auto;
      background: #0b0f19;
    }}

    .terminal-body pre {{
      margin: 0;
      padding: 0;
      background: transparent !important;
      border: none !important;
      font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
      font-size: 13px;
      line-height: 1.6;
      color: #e2e8f0;
    }}

    .terminal-body code {{
      background: transparent !important;
      padding: 0 !important;
      border: none !important;
      color: inherit !important;
      font-family: inherit !important;
    }}

    /* Syntax Highlighting overrides for terminal */
    .hljs-comment, .hljs-quote {{ color: #64748b; font-style: italic; }}
    .hljs-keyword, .hljs-selector-tag {{ color: #c084fc; font-weight: 600; }}
    .hljs-string, .hljs-attribute {{ color: #34d399; }}
    .hljs-built_in, .hljs-title {{ color: #38bdf8; }}
    .hljs-number, .hljs-literal {{ color: #fb923c; }}

    /* Data Tables */
    .table-container {{
      width: 100%;
      overflow-x: auto;
      margin: 28px 0;
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-sm);
      border: 1px solid var(--slate-200);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 14px;
      background: #ffffff;
    }}

    th {{
      background: #1e293b;
      color: #ffffff;
      padding: 12px 16px;
      font-weight: 700;
      border-bottom: 2px solid #0f172a;
      letter-spacing: 0.3px;
    }}

    td {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--slate-200);
      color: var(--slate-700);
      vertical-align: middle;
    }}

    tr:nth-child(even) td {{
      background: #f8fafc;
    }}

    tr:hover td {{
      background: #eef2ff;
    }}

    /* Badges */
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.2;
    }}

    .badge-success {{ background: #dcfce7; color: #15803d; border: 1px solid #86efac; }}
    .badge-warning {{ background: #fef3c7; color: #b45309; border: 1px solid #fde68a; }}
    .badge-info {{ background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }}
    .badge-score {{ background: #fdf4ff; color: #a21caf; border: 1px solid #f0abfc; font-weight: 800; }}

    /* Footer */
    .report-footer {{
      margin-top: 60px;
      padding-top: 25px;
      border-top: 1px solid var(--slate-200);
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--slate-400);
      font-size: 13px;
    }}

    /* Print Styles */
    @media print {{
      body {{
        background: #ffffff;
        padding: 0;
        font-size: 12pt;
      }}
      .container {{
        box-shadow: none;
        border: none;
        padding: 0;
        max-width: 100%;
      }}
      .hero-banner {{
        background: #0f172a !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .figure-card, .diagram-card, .terminal-card {{
        page-break-inside: avoid;
        box-shadow: none;
        border: 1px solid #ccc;
      }}
      h2, h3 {{
        page-break-after: avoid;
      }}
    }}

    @media (max-width: 768px) {{
      .container {{
        padding: 25px 20px;
      }}
      .hero-banner {{
        padding: 30px 20px;
      }}
      .hero-title {{
        font-size: 24px;
      }}
      .toc-body ol {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>

<div class="container">
{body}

<footer class="report-footer">
  <div>EZStore 雙 Agent 智慧商務系統專案報告書 · 2026</div>
  <div>Google ADK 2.11 · A2A Protocol · Open Knowledge Fabric</div>
</footer>
</div>

<script>
  // Initialize Mermaid with custom clean theme
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      primaryColor: '#e0e7ff',
      primaryTextColor: '#1e1b4b',
      primaryBorderColor: '#6366f1',
      lineColor: '#64748b',
      secondaryColor: '#f1f5f9',
      tertiaryColor: '#f8fafc',
      fontFamily: "'Inter', 'Noto Sans TC', sans-serif"
    }},
    flowchart: {{
      curve: 'basis',
      padding: 20
    }},
    sequence: {{
      actorMargin: 40,
      boxMargin: 10,
      boxTextMargin: 5,
      noteMargin: 10,
      messageMargin: 35
    }}
  }});
</script>

</body>
</html>
'''

    # Save to report.html
    with open('report.html', 'w', encoding='utf-8') as f:
        f.write(full_html)
    print("Successfully transformed report.html into exquisite presentation!")
    print(f"New report.html size: {len(full_html)} bytes")

if __name__ == '__main__':
    beautify()
