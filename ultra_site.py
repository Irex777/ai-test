#!/usr/bin/env python3
"""
ultra_site.py — Generate aitest.aiwrk.org with 1000-point scoring system.
Dark theme, per-test breakdowns, per-dimension analysis.
"""
import json, os, html

HERE = os.path.dirname(os.path.abspath(__file__))

MODELS = ["sonnet", "opus", "glm", "glm52", "ornith"]
MODEL_NAMES = {
    "sonnet": "Sonnet 4.6", "opus": "Opus 4.7",
    "glm": "GLM 5.1", "glm52": "GLM-5.2", "ornith": "Ornith 35B",
}
MODEL_META = {
    "sonnet": {"provider": "Anthropic", "emoji": "🟡", "color": "#f59e0b"},
    "opus":   {"provider": "Anthropic", "emoji": "🔴", "color": "#ef4444"},
    "glm":    {"provider": "ZAI", "emoji": "🟢", "color": "#22c55e"},
    "glm52":  {"provider": "ZAI", "emoji": "🔵", "color": "#3b82f6"},
    "ornith": {"provider": "Local", "emoji": "🟠", "color": "#f97316"},
}
TESTS = ["kanban", "dashboard", "chess", "markdown", "calculator",
         "snake", "pomodoro", "weather", "password", "gta", "webos"]
TEST_NAMES = {
    "kanban": "Kanban Board", "dashboard": "Dashboard", "chess": "Chess Game",
    "markdown": "Markdown Editor", "calculator": "Calculator",
    "snake": "Snake Game", "pomodoro": "Pomodoro Timer",
    "weather": "Weather App", "password": "Password Generator",
    "gta": "GTA-Style Game", "webos": "WebOS Desktop",
}
TEST_ICONS = {
    "kanban":"📋","dashboard":"📊","chess":"♟️","markdown":"📝","calculator":"🧮",
    "snake":"🐍","pomodoro":"🍅","weather":"🌤️","password":"🔐","gta":"🎮","webos":"🖥️",
}

DIMS = [
    ("functional", "Functional", 400, "#ef4444"),
    ("code", "Code Quality", 200, "#3b82f6"),
    ("visual", "Visual Design", 200, "#a855f7"),
    ("features", "Features", 100, "#22c55e"),
    ("performance", "Performance", 50, "#f59e0b"),
    ("innovation", "Innovation", 50, "#06b6d4"),
]

def load_scores():
    with open(os.path.join(HERE, "ultra_scores.json")) as f:
        return json.load(f)

def generate_index(scores):
    # Compute aggregates
    model_data = {}
    for m in MODELS:
        total = 0
        count_ok = 0
        count_fail = 0
        dim_sums = {d[0]: 0 for d in DIMS}
        test_scores = {}
        for t in TESTS:
            entry = scores.get(t, {}).get(m, {})
            s = entry.get("total", 0)
            total += s
            test_scores[t] = s
            if entry.get("status") == "OK":
                count_ok += 1
            else:
                count_fail += 1
            for dk in dim_sums:
                dim_sums[dk] += entry.get("dimensions", {}).get(dk, 0)
        model_data[m] = {
            "total": total,
            "avg": total / 11,
            "ok": count_ok,
            "fail": count_fail,
            "dims": dim_sums,
            "tests": test_scores,
        }

    ranked = sorted(MODELS, key=lambda m: model_data[m]["total"], reverse=True)

    # Per-test winners
    test_winners = {}
    for t in TESTS:
        ts = [(m, scores.get(t, {}).get(m, {}).get("total", 0)) for m in MODELS]
        ts.sort(key=lambda x: x[1], reverse=True)
        test_winners[t] = ts

    # Build HTML
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Bake-Off — 1000-Point Scoring</title>
<style>
:root {{
  --bg: #0a0a0f;
  --card: #13131a;
  --border: #2a2a35;
  --text: #e4e4e7;
  --dim: #71717a;
  --accent: #6366f1;
  --gold: #fbbf24;
  --silver: #94a3b8;
  --bronze: #b45309;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
  line-height: 1.6;
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}}
h1 {{ font-size: 2em; margin: 20px 0 8px; }}
h2 {{ font-size: 1.4em; margin: 28px 0 12px; color: var(--text); }}
.subtitle {{ color: var(--dim); margin-bottom: 24px; font-size: 1.05em; }}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 10px 14px; text-align: left; }}
th {{ color: var(--dim); font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }}
td {{ border-bottom: 1px solid #1e1e28; }}
tr:hover td {{ background: #1a1a22; }}
.score-bar {{
  display: inline-block;
  height: 8px;
  border-radius: 4px;
  vertical-align: middle;
  margin-left: 8px;
}}
.rank-badge {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  border-radius: 50%;
  font-size: 1.1em;
  font-weight: bold;
}}
.total-score {{ font-size: 1.3em; font-weight: 700; }}
.dims-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-top: 8px; }}
.dim-cell {{
  background: #1a1a22;
  border-radius: 8px;
  padding: 10px;
  text-align: center;
}}
.dim-cell .label {{ font-size: 0.7em; color: var(--dim); text-transform: uppercase; }}
.dim-cell .value {{ font-size: 1.2em; font-weight: 600; margin-top: 2px; }}
.dim-cell .max {{ font-size: 0.7em; color: var(--dim); }}
.methodology {{ color: var(--dim); font-size: 0.9em; line-height: 1.7; }}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75em;
  font-weight: 600;
}}
.badge-fail {{ background: #2a1212; color: #ef4444; }}
.badge-ok {{ background: #122a12; color: #22c55e; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.test-link {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 0.9em;
  transition: border-color 0.2s;
}}
.test-link:hover {{ border-color: var(--accent); text-decoration: none; }}
.nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }}
</style>
</head>
<body>
<h1>🏆 AI Model Bake-Off</h1>
<p class="subtitle">1000-point multi-dimensional scoring · {len(TESTS)} tests · 5 models · Real browser testing with Playwright</p>
""")

    # ── Leaderboard ──
    html_parts.append('<h2>📊 Final Leaderboard</h2>')
    html_parts.append('<div class="card"><table>')
    html_parts.append('<thead><tr><th>Rank</th><th>Model</th><th>Provider</th>')
    html_parts.append('<th style="text-align:right">Total /11000</th>')
    html_parts.append('<th style="text-align:right">Avg /1000</th>')
    html_parts.append('<th style="text-align:center">Tests Passed</th>')
    for _, dn, dm, dc in DIMS:
        html_parts.append(f'<th style="text-align:right">{dn}<br><span style="font-weight:400;font-size:0.75em">/{dm}</span></th>')
    html_parts.append('</tr></thead><tbody>')

    for rank, model in enumerate(ranked):
        md = model_data[model]
        meta = MODEL_META[model]
        medal = medals[rank] if rank < len(medals) else f"{rank+1}"
        color = meta["color"]

        html_parts.append(f'<tr>')
        html_parts.append(f'<td><span class="rank-badge" style="background:{color}22">{medal}</span></td>')
        html_parts.append(f'<td><strong>{meta["emoji"]} {MODEL_NAMES[model]}</strong></td>')
        html_parts.append(f'<td style="color:var(--dim)">{meta["provider"]}</td>')
        html_parts.append(f'<td style="text-align:right"><span class="total-score" style="color:{color}">{md["total"]:,}</span></td>')
        html_parts.append(f'<td style="text-align:right">{md["avg"]:.0f}</td>')
        html_parts.append(f'<td style="text-align:center">{md["ok"]}/11</td>')

        for dk, _, dm, dc in DIMS:
            val = md["dims"][dk]
            pct = val / (dm * 11) * 100
            bar_w = min(100, pct)
            html_parts.append(f'<td style="text-align:right">{val}<span class="score-bar" style="width:{bar_w*0.6}px;background:{dc}"></span></td>')

        html_parts.append('</tr>')

    html_parts.append('</tbody></table></div>')

    # ── Per-test results ──
    html_parts.append('<h2>📋 Per-Test Results</h2>')
    html_parts.append('<div class="card"><table>')
    html_parts.append('<thead><tr><th>Test</th>')
    for model in ranked:
        meta = MODEL_META[model]
        html_parts.append(f'<th style="text-align:right">{meta["emoji"]} {MODEL_NAMES[model][:8]}</th>')
    html_parts.append('</tr></thead><tbody>')

    for test in TESTS:
        icon = TEST_ICONS.get(test, "")
        tname = TEST_NAMES.get(test, test)
        html_parts.append(f'<tr><td><strong>{icon} {tname}</strong></td>')
        for model in ranked:
            entry = scores.get(test, {}).get(model, {})
            s = entry.get("total", 0)
            status = entry.get("status", "FAILED")
            if status == "FAILED":
                html_parts.append(f'<td style="text-align:right"><span class="badge badge-fail">FAIL</span></td>')
            else:
                # Check if winner
                is_winner = test_winners[test][0][0] == model and s > 0
                color = "#fbbf24" if is_winner else "var(--text)"
                weight = "700" if is_winner else "400"
                html_parts.append(f'<td style="text-align:right;color:{color};font-weight:{weight}">{s}</td>')
        html_parts.append('</tr>')

    # Totals row
    html_parts.append('<tr style="border-top:2px solid var(--border)"><td><strong>TOTAL</strong></td>')
    for model in ranked:
        md = model_data[model]
        html_parts.append(f'<td style="text-align:right"><strong style="color:{MODEL_META[model]["color"]}">{md["total"]:,}</strong></td>')
    html_parts.append('</tr>')

    html_parts.append('</tbody></table></div>')

    # ── Test Winners Summary ──
    win_counts = {}
    for test in TESTS:
        w = test_winners[test][0]
        if w[1] > 0:
            win_counts[w[0]] = win_counts.get(w[0], 0) + 1

    html_parts.append('<h2>🥇 Test Wins</h2>')
    html_parts.append('<div class="card"><table><thead><tr><th>Model</th><th style="text-align:right">Wins</th></tr></thead><tbody>')
    for model in ranked:
        wins = win_counts.get(model, 0)
        meta = MODEL_META[model]
        html_parts.append(f'<tr><td>{meta["emoji"]} {MODEL_NAMES[model]}</td><td style="text-align:right;font-size:1.2em;font-weight:700;color:{meta["color"]}">{wins}</td></tr>')
    html_parts.append('</tbody></table></div>')

    # ── Navigation ──
    html_parts.append('<h2>📁 Browse Tests</h2>')
    html_parts.append('<div class="nav">')
    for test in TESTS:
        icon = TEST_ICONS.get(test, "")
        tname = TEST_NAMES.get(test, test)
        html_parts.append(f'<a class="test-link" href="{test}/index.html">{icon} {tname}</a>')
    html_parts.append('</div>')

    # ── Methodology ──
    html_parts.append('<h2>📐 Scoring Methodology</h2>')
    html_parts.append('<div class="card methodology">')
    html_parts.append('<p><strong>1000-point scale per test</strong> across 6 weighted dimensions:</p>')
    html_parts.append('<table style="margin:12px 0"><thead><tr><th>Dimension</th><th>Max</th><th>What We Measure</th></tr></thead><tbody>')
    html_parts.append('<tr><td><strong style="color:#ef4444">Functional Correctness</strong></td><td>400</td><td>Real Playwright browser tests — clicking, typing, playing games. Critical features weighted 40pts, important 25pts, minor 10pts. Console errors penalized.</td></tr>')
    html_parts.append('<tr><td><strong style="color:#3b82f6">Code Architecture</strong></td><td>200</td><td>8 sub-dimensions: CSS methodology, JS quality, semantic HTML, accessibility, code organization, file efficiency, modern features, self-contained (no CDN).</td></tr>')
    html_parts.append('<tr><td><strong style="color:#a855f7">Visual Design</strong></td><td>200</td><td>7 sub-dimensions: color sophistication, typography, spacing, animations, interactive feedback, responsive design, component polish.</td></tr>')
    html_parts.append('<tr><td><strong style="color:#22c55e">Feature Richness</strong></td><td>100</td><td>Core features implemented (60pts) + bonus features beyond spec: dark mode, animations, keyboard shortcuts, responsive (40pts).</td></tr>')
    html_parts.append('<tr><td><strong style="color:#f59e0b">Performance</strong></td><td>50</td><td>Browser load speed (30pts) + code efficiency/file size (20pts).</td></tr>')
    html_parts.append('<tr><td><strong style="color:#06b6d4">Innovation</strong></td><td>50</td><td>Creative patterns: sound effects, particle effects, keyboard shortcuts, loading states, toast notifications, easter eggs.</td></tr>')
    html_parts.append('</tbody></table>')
    html_parts.append('<p style="margin-top:12px"><strong>Test conditions:</strong> max_tokens=65536, temperature=0.7, one-shot generation (no retries), 1200s timeout. GLM-5.2 with thinking enabled. Sequential execution.</p>')
    html_parts.append('<p style="margin-top:8px;color:#ef4444"><strong>Note:</strong> Opus 4.7 results pending — Claude Pro session rate limit. Will be added when available.</p>')
    html_parts.append('</div>')

    html_parts.append("""
<script>
// Highlight winning cells
document.querySelectorAll('td').forEach(td => {
    const text = td.textContent.trim();
    if (text === 'FAIL') return;
});
</script>
</body>
</html>
""")

    return "".join(html_parts)


def generate_test_page(test, scores):
    """Generate per-test detail page."""
    tname = TEST_NAMES.get(test, test)
    icon = TEST_ICONS.get(test, "")

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{tname} — AI Bake-Off</title>
<style>
:root {{
  --bg: #0a0a0f; --card: #13131a; --border: #2a2a35;
  --text: #e4e4e7; --dim: #71717a; --accent: #6366f1;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg); color: var(--text);
  font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
  line-height: 1.6; padding: 20px; max-width: 1200px; margin: 0 auto;
}}
h1 {{ font-size: 1.8em; margin: 20px 0 8px; }}
h2 {{ font-size: 1.3em; margin: 24px 0 12px; }}
.back {{ color: var(--accent); text-decoration: none; font-size: 0.9em; }}
.back:hover {{ text-decoration: underline; }}
.card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px; margin-bottom: 16px;
}}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 10px 14px; text-align: left; }}
th {{ color: var(--dim); font-size: 0.85em; text-transform: uppercase; border-bottom: 1px solid var(--border); }}
td {{ border-bottom: 1px solid #1e1e28; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:0.75em; font-weight:600; }}
.badge-fail {{ background: #2a1212; color: #ef4444; }}
.badge-ok {{ background: #122a12; color: #22c55e; }}
.app-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; margin-top: 16px; }}
.app-card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; transition: border-color 0.2s;
}}
.app-card:hover {{ border-color: var(--accent); }}
.app-card iframe {{ width: 100%; height: 300px; border: none; pointer-events: none; }}
.app-info {{ padding: 14px; }}
.app-info h3 {{ font-size: 1em; margin-bottom: 4px; }}
.score-big {{ font-size: 1.5em; font-weight: 700; }}
.dims-mini {{ display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }}
.dim-pill {{
  padding: 2px 8px; border-radius: 4px; font-size: 0.75em;
  background: #1a1a22;
}}
</style>
</head>
<body>
<a class="back" href="../index.html">← Back to Leaderboard</a>
<h1>{icon} {tname}</h1>
""")

    # Rankings table
    test_scores = [(m, scores.get(test, {}).get(m, {})) for m in MODELS]
    test_scores.sort(key=lambda x: x[1].get("total", 0), reverse=True)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    html_parts.append('<div class="card"><table>')
    html_parts.append('<thead><tr><th>Rank</th><th>Model</th><th style="text-align:right">Score /1000</th>')
    for dk, dn, dm, _ in DIMS:
        html_parts.append(f'<th style="text-align:right">{dn}<br><span style="font-weight:400">/{dm}</span></th>')
    html_parts.append('<th>Status</th></tr></thead><tbody>')

    for rank, (model, entry) in enumerate(test_scores):
        meta = MODEL_META[model]
        medal = medals[rank] if rank < len(medals) else str(rank+1)
        color = meta["color"]
        total = entry.get("total", 0)
        status = entry.get("status", "FAILED")
        dims = entry.get("dimensions", {})

        html_parts.append(f'<tr>')
        html_parts.append(f'<td><span style="font-size:1.2em">{medal}</span></td>')
        html_parts.append(f'<td><strong>{meta["emoji"]} {MODEL_NAMES[model]}</strong></td>')
        html_parts.append(f'<td style="text-align:right"><span class="score-big" style="color:{color}">{total}</span></td>')

        for dk, dn, dm, dc in DIMS:
            val = dims.get(dk, 0)
            html_parts.append(f'<td style="text-align:right;color:{dc}aa">{val}</td>')

        badge = '<span class="badge badge-ok">OK</span>' if status == "OK" else '<span class="badge badge-fail">FAILED</span>'
        html_parts.append(f'<td>{badge}</td>')
        html_parts.append('</tr>')

    html_parts.append('</tbody></table></div>')

    # App previews
    html_parts.append('<h2>👁️ Live Previews</h2>')
    html_parts.append('<div class="app-grid">')
    for rank, (model, entry) in enumerate(test_scores):
        meta = MODEL_META[model]
        html_file = f"{model}.html"
        if os.path.exists(os.path.join(HERE, test, html_file)):
            html_parts.append(f"""
            <div class="app-card">
                <iframe src="{html_file}" loading="lazy" sandbox="allow-scripts"></iframe>
                <div class="app-info">
                    <h3>{meta["emoji"]} {MODEL_NAMES[model]} — {entry.get("total",0)} pts</h3>
                    <div class="dims-mini">""")
            dims = entry.get("dimensions", {})
            for dk, dn, _, dc in DIMS:
                val = dims.get(dk, 0)
                html_parts.append(f'<span class="dim-pill" style="color:{dc}">{dn}: {val}</span>')
            html_parts.append('</div></div></div>')
    html_parts.append('</div>')

    html_parts.append('</body></html>')
    return "".join(html_parts)


def main():
    scores = load_scores()

    # Generate index
    index_html = generate_index(scores)
    with open(os.path.join(HERE, "index.html"), "w") as f:
        f.write(index_html)
    print("✓ Generated index.html")

    # Generate per-test pages
    for test in TESTS:
        test_html = generate_test_page(test, scores)
        test_dir = os.path.join(HERE, test)
        os.makedirs(test_dir, exist_ok=True)
        with open(os.path.join(test_dir, "index.html"), "w") as f:
            f.write(test_html)
        print(f"✓ Generated {test}/index.html")

    print(f"\n✓ Site generated. {len(TESTS)+1} pages.")


if __name__ == "__main__":
    main()
