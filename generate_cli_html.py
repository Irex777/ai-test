#!/usr/bin/env python3
"""Generate cli.html with actual test scores."""
import json
import os

SCORES_PATH = "/tmp/ai-test/cli-outputs/opencode/scores.json"
OUTPUT_PATH = "/tmp/ai-test/cli.html"

with open(SCORES_PATH) as f:
    scores = json.load(f)

TESTS = [
    ("kanban", "📋", "Kanban Board"),
    ("dashboard", "📊", "Analytics Dashboard"),
    ("chess", "♟", "Chess Game"),
    ("markdown", "✏️", "Markdown Editor"),
    ("calculator", "🧮", "Calculator"),
    ("snake", "🐍", "Snake Game"),
    ("pomodoro", "⏱", "Pomodoro Timer"),
    ("weather", "🌤", "Weather Dashboard"),
    ("password", "🔐", "Password Generator"),
    ("gta", "🚗", "GTA Game"),
    ("webos", "💻", "Web OS"),
]

def get_score_badge(score, max_score):
    pct = round(score / max_score * 100) if max_score > 0 else 0
    if pct >= 90:
        color = "#00c853"
        bg = "#00c85322"
    elif pct >= 70:
        color = "#667eea"
        bg = "#667eea22"
    elif pct >= 40:
        color = "#ff9800"
        bg = "#ff980022"
    else:
        color = "#ff5253"
        bg = "#ff525322"
    return f'<span style="color:{color};background:{bg};padding:2px 8px;border-radius:4px;font-size:0.85em;font-weight:600">{score}/{max_score}</span>'

def get_na_badge(reason="N/A"):
    return f'<span style="color:#555;background:#1a1a1a;padding:2px 8px;border-radius:4px;font-size:0.85em">{reason}</span>'

def make_row(test_key, icon, test_name, models_data):
    cells = []
    for model_key, model_label in models_data:
        full_key = f"opencode/{model_key}/{test_key}"
        if full_key in scores:
            s = scores[full_key]
            cells.append(f'<td>{get_score_badge(s["score"], s["max"])}</td>')
        else:
            cells.append(f'<td>{get_na_badge()}</td>')
    row = f'<tr><td>{icon} {test_name}</td>' + ''.join(cells) + '</tr>'
    return row

def make_total_row(models_data):
    cells = []
    for model_key, model_label in models_data:
        total = 0
        max_total = 0
        for test_key, _, _ in TESTS:
            full_key = f"opencode/{model_key}/{test_key}"
            if full_key in scores:
                total += scores[full_key]["score"]
                max_total += scores[full_key]["max"]
        pct = round(total / max_total * 100) if max_total > 0 else 0
        cells.append(f'<td class="code-col" style="color:#ffd700">{total}/{max_total} ({pct}%)</td>')
    return '<tr class="totals"><td class="total-label">TOTAL</td>' + ''.join(cells) + '</tr>'

# Model data: (key_for_scores, display_label)
opencode_models = [
    ("glm-5.1", "GLM 5.1"),
    ("qwen-3.6-27b", "Qwen 3.6 27B MTP"),
]

# Claude Code can only use Anthropic models (no results yet)
claude_models = [
    ("sonnet-4.6", "Sonnet 4.6"),
    ("opus-4.7", "Opus 4.7"),
]

# Codex CLI can only use OpenAI models (no results yet)
codex_models = [
    ("gpt-4.1", "GPT-4.1"),
    ("o3", "o3"),
]

# Build rankings from what we have
rankings = []
for model_key, model_label in opencode_models:
    total = 0
    max_total = 0
    for test_key, _, _ in TESTS:
        full_key = f"opencode/{model_key}/{test_key}"
        if full_key in scores:
            total += scores[full_key]["score"]
            max_total += scores[full_key]["max"]
    pct = round(total / max_total * 100) if max_total > 0 else 0
    rankings.append(("OpenCode", model_label, total, max_total, pct))

rankings.sort(key=lambda x: x[2], reverse=True)
rank_symbols = ["🥇", "🥈", "🥉"] + [f"{i}th" for i in range(4, 13)]

# Build ranking rows
ranking_rows = []
for i, (agent, model, total, max_total, pct) in enumerate(rankings):
    sym = rank_symbols[i] if i < len(rank_symbols) else f"{i+1}th"
    ranking_rows.append(
        f'<tr><td>{sym}</td><td style="text-align:left">{agent}</td>'
        f'<td class="c-glm">{model}</td>'
        f'<td class="code-col">{total}/{max_total}</td>'
        f'<td class="code-col" style="color:#ffd700">{pct}%</td></tr>'
    )

# Add placeholder rows for untested combos
for agent, models in [("Claude Code", claude_models), ("Codex CLI", codex_models)]:
    for model_key, model_label in models:
        i = len(ranking_rows)
        sym = rank_symbols[i] if i < len(rank_symbols) else f"{i+1}th"
        ranking_rows.append(
            f'<tr><td>{sym}</td><td style="text-align:left">{agent}</td>'
            f'<td class="c-sonnet">{model_label}</td>'
            f'<td class="code-col" style="color:#555">pending</td>'
            f'<td class="code-col" style="color:#555">—</td></tr>'
        )

# Build OpenCode section rows
opencode_rows = []
for test_key, icon, test_name in TESTS:
    opencode_rows.append(make_row(test_key, icon, test_name, opencode_models))
opencode_rows.append(make_total_row(opencode_models))

# Build Claude Code section (Anthropic-only, pending)
claude_pending_row = '<tr><td>{icon} {name}</td><td>{na}</td><td>{na}</td></tr>'
claude_rows = []
for test_key, icon, test_name in TESTS:
    claude_rows.append(
        f'<tr><td>{icon} {test_name}</td>'
        f'<td>{get_na_badge("cooldown")}</td>'
        f'<td>{get_na_badge("cooldown")}</td></tr>'
    )
claude_rows.append(
    '<tr class="totals"><td class="total-label">TOTAL</td>'
    '<td class="code-col" style="color:#555">pending</td>'
    '<td class="code-col" style="color:#555">pending</td></tr>'
)

# Build Codex CLI section (OpenAI-only, N/A for non-OpenAI models)
codex_rows = []
for test_key, icon, test_name in TESTS:
    codex_rows.append(
        f'<tr><td>{icon} {test_name}</td>'
        f'<td>{get_na_badge("pending")}</td>'
        f'<td>{get_na_badge("pending")}</td></tr>'
    )
codex_rows.append(
    '<tr class="totals"><td class="total-label">TOTAL</td>'
    '<td class="code-col" style="color:#555">pending</td>'
    '<td class="code-col" style="color:#555">pending</td></tr>'
)

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CLI Agent Showdown - AI Test</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0a;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6}}
.container{{max-width:100%;padding:20px}}
h1{{text-align:center;font-size:2.2em;margin:30px 0 10px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.subtitle{{text-align:center;color:#888;margin-bottom:8px;font-size:1.1em}}
.nav{{text-align:center;margin-bottom:30px}}
.nav a{{color:#667eea;padding:6px 14px;background:#1a1a1a;border-radius:8px;font-size:0.9em;text-decoration:none;margin:0 4px}}
.nav a:hover{{text-decoration:underline}}
.nav a.active{{color:#fff;background:#333}}
.card{{background:#1a1a1a;border-radius:12px;padding:24px;margin-bottom:20px;border:1px solid #2a2a2a}}
.card h2{{color:#fff;margin-bottom:6px;font-size:1.3em}}
.card .card-sub{{color:#888;font-size:0.88em;margin-bottom:16px}}
.model-legend{{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:24px;font-size:0.88em}}
.model-legend span{{display:flex;align-items:center;gap:5px}}
.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.dot-glm{{background:#00c853}}
.dot-qwen{{background:#ff9800}}
.dot-sonnet{{background:#667eea}}
.dot-opus{{background:#764ba2}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th,td{{padding:8px 6px;text-align:center;border-bottom:1px solid #2a2a2a;font-size:0.82em}}
th{{color:#888;font-weight:600;position:sticky;top:0;background:#1a1a1a;z-index:1}}
td:first-child,th:first-child{{text-align:left;position:sticky;left:0;background:#1a1a1a;z-index:2}}
th:first-child{{z-index:3}}
a{{color:#667eea;text-decoration:none}}
a:hover{{text-decoration:underline}}
.code-col{{font-weight:700;font-size:0.88em;color:#e0e0e0}}
.totals td{{font-weight:700;border-top:2px solid #444;font-size:0.9em}}
.totals .total-label{{color:#ffd700}}
.c-glm{{color:#00c853}}
.c-qwen{{color:#ff9800}}
.c-sonnet{{color:#667eea}}
.c-opus{{color:#764ba2}}
.feature-table{{overflow-x:auto}}
.feature-table td,.feature-table th{{text-align:left;padding:10px 12px;font-size:0.88em}}
.feature-table td:first-child,.feature-table th:first-child{{position:static}}
code{{background:#222;padding:2px 6px;border-radius:4px;font-size:0.85em}}
.scroll-wrap{{overflow-x:auto}}
.note{{background:#1a1a1a;border-left:3px solid #ff9800;padding:12px 16px;margin-bottom:20px;border-radius:0 8px 8px 0;font-size:0.9em;color:#ccc}}
.note strong{{color:#ff9800}}
</style>
</head>
<body>
<div class="container">
<h1>CLI Agent Showdown</h1>
<p class="subtitle">3 CLI Agents &middot; 11 Coding Prompts &middot; 110 Features per Model &middot; Auto-Scored</p>
<div class="nav">
<a href="/">Model Showdown</a>
<a href="cli.html" class="active">CLI Agent Showdown</a>
<a href="methodology.html">Methodology</a>
</div>

<div class="model-legend">
<span><span class="dot dot-glm"></span> GLM 5.1 (ZAI)</span>
<span><span class="dot dot-qwen"></span> Qwen 3.6 27B MTP (local)</span>
<span><span class="dot dot-sonnet"></span> Sonnet 4.6 (pending)</span>
<span><span class="dot dot-opus"></span> Opus 4.7 (pending)</span>
</div>

<div class="note">
<strong>Status:</strong> OpenCode tested with GLM 5.1 and Qwen 3.6 27B MTP. Claude Code (Anthropic-only) and Codex CLI (OpenAI-only) pending — Claude models on cooldown, Codex CLI requires OpenAI Responses API.
</div>

<!-- RANKINGS -->
<div class="card">
<h2>🏆 Rankings</h2>
<p class="card-sub">110 features scored per model across 11 single-file app tests</p>
<div class="scroll-wrap">
<table>
<tr>
<th style="width:40px">Rank</th>
<th style="text-align:left">Agent</th>
<th>Model</th>
<th>Score</th>
<th>Pct</th>
</tr>
{"".join(ranking_rows)}
</table>
</div>
</div>

<!-- OPENCODE SECTION -->
<div class="card">
<h2>🖥 OpenCode — <code>opencode run -m "model" "prompt"</code></h2>
<p class="card-sub">Open source (MIT) · Go runtime · All model providers · Free + API costs · Tested 2026-05-17</p>
<div class="scroll-wrap">
<table>
<tr>
<th style="min-width:140px">Test</th>
<th class="c-glm">GLM 5.1</th>
<th class="c-qwen">Qwen 3.6 27B</th>
</tr>
{"".join(opencode_rows)}
</table>
</div>
</div>

<!-- CLAUDE CODE SECTION -->
<div class="card">
<h2>🤖 Claude Code — <code>claude -p "prompt"</code></h2>
<p class="card-sub">Anthropic proprietary · Terminal + IDE · $20/mo Pro or API · Deep git integration · Anthropic models only</p>
<div class="scroll-wrap">
<table>
<tr>
<th style="min-width:140px">Test</th>
<th class="c-sonnet">Sonnet 4.6</th>
<th class="c-opus">Opus 4.7</th>
</tr>
{"".join(claude_rows)}
</table>
</div>
</div>

<!-- CODEX CLI SECTION -->
<div class="card">
<h2>🛡 Codex CLI — <code>codex exec "prompt"</code></h2>
<p class="card-sub">Open source (Apache 2.0) · OpenAI Responses API only · Docker sandbox · Node.js runtime</p>
<div class="scroll-wrap">
<table>
<tr>
<th style="min-width:140px">Test</th>
<th class="c-sonnet">GPT-4.1</th>
<th class="c-qwen">o3</th>
</tr>
{"".join(codex_rows)}
</table>
</div>
</div>

<!-- FEATURE COMPARISON -->
<div class="card">
<h2>⚡ Agent Feature Comparison</h2>
<div class="feature-table">
<table>
<tr>
<th style="min-width:120px">Feature</th>
<th>Claude Code</th>
<th>OpenCode</th>
<th>Codex CLI</th>
</tr>
<tr><td>Command</td><td><code>claude -p "prompt"</code></td><td><code>opencode run -m "model"</code></td><td><code>codex exec "prompt"</code></td></tr>
<tr><td>Providers</td><td>Anthropic only</td><td>All providers</td><td>OpenAI Responses API</td></tr>
<tr><td>Sandbox</td><td style="color:#ff5253">No</td><td style="color:#ff5253">No</td><td style="color:#00c853">Docker</td></tr>
<tr><td>Open Source</td><td style="color:#ff5253">Proprietary</td><td style="color:#00c853">MIT</td><td style="color:#00c853">Apache 2.0</td></tr>
<tr><td>UI</td><td>Terminal + IDE</td><td>Go TUI</td><td>Terminal</td></tr>
<tr><td>Cost</td><td>$20/mo or API</td><td>Free + API</td><td>API / Free (local)</td></tr>
<tr><td>Config</td><td>CLAUDE.md</td><td>opencode.json</td><td>codex.md</td></tr>
<tr><td>Language</td><td>Node.js</td><td>Go</td><td>Node.js</td></tr>
<tr><td>Git Integration</td><td style="color:#00c853">Deep</td><td style="color:#ff9800">Basic</td><td style="color:#00c853">PR/commit</td></tr>
<tr><td>Multi-turn</td><td style="color:#00c853">Auto-loop</td><td style="color:#00c853">Auto-loop</td><td style="color:#00c853">Auto-loop</td></tr>
<tr><td>GLM 5.1</td><td style="color:#ff5253">No</td><td style="color:#00c853">Yes (ZAI)</td><td style="color:#ff5253">No</td></tr>
<tr><td>Qwen (local)</td><td style="color:#ff5253">No</td><td style="color:#00c853">Yes (llama.cpp)</td><td style="color:#ff5253">No</td></tr>
<tr><td>Custom Providers</td><td style="color:#ff5253">Anthropic only</td><td style="color:#00c853">Any OpenAI-compat</td><td style="color:#ff9800">OpenAI only</td></tr>
</table>
</div>
</div>

<!-- METHODOLOGY NOTE -->
<div class="card" style="text-align:center;color:#666;font-size:0.85em">
<p>Each agent receives identical prompts in single-shot mode (no conversation history).</p>
<p>11 single-file HTML app challenges, each with 10 feature requirements = 110 features scored per combo.</p>
<p>Scoring: automated feature detection via regex/DOM analysis of generated HTML.</p>
<p>Tested on Mac Mini M4 Pro. Qwen 3.6 27B MTP runs locally via llama.cpp at 10.0.0.160:8081.</p>
</div>
</div>
</body>
</html>'''

with open(OUTPUT_PATH, "w") as f:
    f.write(html)

print(f"Written {len(html)} bytes to {OUTPUT_PATH}")
