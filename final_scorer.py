#!/usr/bin/env python3
"""
final_scorer.py — Combine browser functional scores + static quality scores +
generation timing into final combined scores, then rebuild the entire
aitest.aiwrk.org site (index.html + 11 test pages) with the new combined
scoring, per-test winners, methodology, and honest failure reporting.

Data sources (all in repo root):
  - fair_results.json      generation success/failure + timing (1 shot, 0 retries)
  - browser_results.json   Playwright functional test scores (0-100)
  - strict_scores.json     static code-analysis quality scores (0-100, 6 dims)

Final score per (model, test):
  - generation FAILED  -> final = 0, status = FAILED
  - generation OK      -> final = round(functional*0.45 + quality*0.40 + speed*0.15)
                          speed normalized per test among successful generations
                          (fastest=100, slowest=0)

Outputs:
  - final_scores.json
  - index.html            (root rankings + methodology)
  - {test}/index.html     (11 test pages)
"""

import json
import os
import html

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

# 5 models in this rerun (Qwen excluded — server down).
MODELS = ["glm", "glm52", "opus", "ornith", "sonnet"]

MODEL_INFO = {
    "sonnet": {"name": "Sonnet 4.6",   "provider": "Anthropic",     "emoji": "🟡", "color": "#f59e0b"},
    "opus":   {"name": "Opus 4.7",     "provider": "Anthropic",     "emoji": "🔴", "color": "#ef4444"},
    "glm":    {"name": "GLM 5.1",      "provider": "ZAI",           "emoji": "🟢", "color": "#22c55e"},
    "glm52":  {"name": "GLM-5.2",      "provider": "ZAI / z.ai",    "emoji": "🔵", "color": "#3b82f6"},
    "ornith": {"name": "Ornith 35B",   "provider": "Local llama.cpp","emoji": "🟠", "color": "#f97316"},
}

# Order in which we display models in tables (Anthropic first, then ZAI, then local).
MODEL_ORDER = ["glm", "glm52", "opus", "ornith", "sonnet"]

TEST_INFO = {
    "kanban":     {"name": "Kanban Board",       "emoji": "📋"},
    "dashboard":  {"name": "Dashboard",          "emoji": "📊"},
    "chess":      {"name": "Chess Game",         "emoji": "♟️"},
    "markdown":   {"name": "Markdown Editor",    "emoji": "📝"},
    "calculator": {"name": "Calculator",         "emoji": "🧮"},
    "snake":      {"name": "Snake Game",         "emoji": "🐍"},
    "pomodoro":   {"name": "Pomodoro Timer",     "emoji": "🍅"},
    "weather":    {"name": "Weather App",        "emoji": "🌤️"},
    "password":   {"name": "Password Generator", "emoji": "🔐"},
    "gta":        {"name": "GTA-Style Game",     "emoji": "🎮"},
    "webos":      {"name": "WebOS Desktop",      "emoji": "🖥️"},
}
TEST_ORDER = ["kanban", "dashboard", "chess", "markdown", "calculator",
              "snake", "pomodoro", "weather", "password", "gta", "webos"]

# Quality dimension display info (name, max points).
DIM_INFO = [
    ("functionality",  "Functionality",   30),
    ("code_quality",   "Code Quality",    20),
    ("ux",             "UX Polish",       20),
    ("visual",         "Visual Design",   15),
    ("accessibility",  "Accessibility",   10),
    ("performance",    "Performance",     5),
]

# Scoring weights.
W_FUNCTIONAL = 0.45
W_QUALITY    = 0.40
W_SPEED      = 0.15

MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_json(path):
    with open(os.path.join(HERE, path)) as f:
        return json.load(f)


def load_all():
    fair    = load_json("fair_results.json")
    browser = load_json("browser_results.json")
    strict  = load_json("strict_scores.json")
    return fair, browser, strict


# --------------------------------------------------------------------------
# Score computation
# --------------------------------------------------------------------------

def compute_scores(fair, browser, strict):
    """Return dict: scores[test][model] -> entry dict."""
    # Index generation results.
    gen = {}
    for r in fair['results']:
        if r['model'] not in MODELS:
            continue
        gen[(r['test'], r['model'])] = r

    strict_tests = strict['tests']

    scores = {}
    for test in TEST_ORDER:
        # --- speed normalization among successful generations for this test ---
        ok_times = []
        for m in MODELS:
            r = gen.get((test, m))
            if r and r.get("success"):
                ok_times.append(r['time_seconds'])
        fastest = min(ok_times) if ok_times else 0
        slowest = max(ok_times) if ok_times else 0
        span = (slowest - fastest) if slowest > fastest else 0.0

        scores[test] = {}
        for m in MODELS:
            r = gen.get((test, m), {})
            success = bool(r.get("success", False))
            t = r.get("time_seconds")
            err = r.get("error")

            if not success:
                scores[test][m] = {
                    "final": 0, "status": "FAILED",
                    "functional": 0, "quality": 0, "speed": 0,
                    "gen_error": err, "time": t,
                    "passed": None, "total": None,
                    "console_errors": 0, "load_time_ms": None,
                    "dimensions": None, "size_kb": None,
                }
                continue

            # functional (browser)
            bk = f"{test}_{m}"
            bentry = browser.get(bk, {})
            functional = bentry.get("score", 0)
            passed = bentry.get("passed")
            total = bentry.get("total")
            console_errors = len(bentry.get("console_errors", []))
            load_time_ms = bentry.get("load_time_ms")

            # quality (strict)
            sentry = strict_tests.get(test, {}).get(m, {})
            quality = sentry.get("quality_score", 0)
            dims = sentry.get("dimensions")
            size_kb = (sentry.get("metrics", {}) or {}).get("size", 0) / 1024.0

            # speed (normalized)
            if span > 0 and t is not None:
                speed = max(0.0, 100.0 * (1 - (t - fastest) / span))
            else:
                speed = 100.0  # everyone tied -> full marks
            speed = round(speed, 1)

            final = round(functional * W_FUNCTIONAL + quality * W_QUALITY + speed * W_SPEED)
            final = max(0, min(100, final))

            scores[test][m] = {
                "final": final, "status": "OK",
                "functional": functional, "quality": round(quality, 1), "speed": speed,
                "gen_error": None, "time": t,
                "passed": passed, "total": total,
                "console_errors": console_errors, "load_time_ms": load_time_ms,
                "dimensions": dims, "size_kb": round(size_kb, 1) if size_kb else None,
            }
    return scores


def compute_aggregates(scores):
    """Per-model totals + averages + test wins/losses + dimension averages."""
    agg = {m: {
        "total": 0, "tests_ok": 0, "tests_failed": 0, "failures": [],
        "sum_func": 0.0, "sum_qual": 0.0, "sum_speed": 0.0,
        "n_func": 0, "n_qual": 0, "n_speed": 0,
        "dim_sums": {k: 0.0 for k, _, _ in DIM_INFO},
        "dim_counts": {k: 0 for k, _, _ in DIM_INFO},
        "test_wins": [], "test_scores": {}, "worst_tests": [],
    } for m in MODELS}

    for test in TEST_ORDER:
        # determine winner (highest final). ties broken by functional then quality.
        ranked = sorted(
            MODELS,
            key=lambda m: (scores[test][m]['final'],
                           scores[test][m]['functional'],
                           scores[test][m]['quality']),
            reverse=True,
        )
        winner = ranked[0]
        agg[winner]['test_wins'].append(test)

        # worst (lowest final among OK entries)
        ok_models = [m for m in MODELS if scores[test][m]['status'] == "OK"]
        if ok_models:
            worst = min(ok_models, key=lambda m: scores[test][m]['final'])
            agg[worst]['worst_tests'].append((test, scores[test][worst]['final']))

        for m in MODELS:
            e = scores[test][m]
            a = agg[m]
            a['total'] += e['final']
            a['test_scores'][test] = e['final']
            if e['status'] == "OK":
                a['tests_ok'] += 1
                a['sum_func'] += e['functional']; a['n_func'] += 1
                a['sum_qual'] += e['quality'];    a['n_qual'] += 1
                a['sum_speed'] += e['speed'];     a['n_speed'] += 1
                if e['dimensions']:
                    for key, _, _ in DIM_INFO:
                        d = e['dimensions'].get(key, {})
                        total_pts = d.get("total", 0)
                        if total_pts is not None:
                            a['dim_sums'][key] += total_pts
                            a['dim_counts'][key] += 1
            else:
                a['tests_failed'] += 1
                a['failures'].append({"test": test, "error": e['gen_error']})

    # finalize averages + dimension percentages
    for m in MODELS:
        a = agg[m]
        a['avg_func'] = round(a['sum_func'] / a['n_func'], 1) if a['n_func'] else 0.0
        a['avg_qual'] = round(a['sum_qual'] / a['n_qual'], 1) if a['n_qual'] else 0.0
        a['avg_speed'] = round(a['sum_speed'] / a['n_speed'], 1) if a['n_speed'] else 0.0
        a['dim_pct'] = {}
        for key, _, mx in DIM_INFO:
            cnt = a['dim_counts'][key]
            if cnt:
                avg_pts = a['dim_sums'][key] / cnt
                a['dim_pct'][key] = round(100 * avg_pts / mx, 1)
            else:
                a['dim_pct'][key] = 0.0

    return agg


def derive_strengths_weaknesses(a):
    """Return (strengths[], weaknesses[]) lists of strings."""
    strengths, weaknesses = [], []
    for key, label, mx in DIM_INFO:
        pct = a['dim_pct'][key]
        if pct >= 62:
            strengths.append((pct, f"Strong {label} ({pct:.0f}%)"))
        elif pct < 45:
            weaknesses.append((pct, f"Weak {label} ({pct:.0f}%)"))
    # add wins as a strength
    nwins = len(a['test_wins'])
    if nwins > 0:
        strengths.insert(0, (100, f"Won {nwins}/11 tests"))
    # sort & pick top few
    strengths.sort(key=lambda x: -x[0])
    weaknesses.sort(key=lambda x: x[0])
    return [s for _, s in strengths[:3]], [w for _, w in weaknesses[:3]]


def score_color(v):
    if v >= 75: return "#22c55e"
    if v >= 60: return "#a3e635"
    if v >= 45: return "#f59e0b"
    if v >  0:  return "#ef4444"
    return "#6b7280"


def chip(text, kind):
    """A small colored pill."""
    if kind == "good":
        bg, fg = "rgba(34,197,94,0.12)", "#22c55e"
    elif kind == "bad":
        bg, fg = "rgba(239,68,68,0.12)", "#ef4444"
    else:
        bg, fg = "rgba(139,148,158,0.12)", "#8b949e"
    return (f"<span style='display:inline-block;background:{bg};color:{fg};"
            f"padding:2px 8px;border-radius:6px;font-size:0.75rem;margin:2px'>"
            f"{html.escape(text)}</span>")


# --------------------------------------------------------------------------
# Shared CSS
# --------------------------------------------------------------------------

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d; --border: #30363d;
  --text: #e6edf3; --text2: #8b949e; --accent: #58a6ff;
  --purple: #6366f1; --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
  --sonnet:#f59e0b; --opus:#ef4444; --glm:#22c55e; --glm52:#3b82f6;
  --qwen:#6366f1; --ornith:#f97316;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; }

.hero { text-align: center; padding: 60px 24px 40px; position: relative; overflow: hidden; }
.hero::before { content:''; position:absolute; top:-50%; left:-50%; width:200%; height:200%;
  background: radial-gradient(ellipse at center, rgba(99,102,241,0.15) 0%, transparent 70%); }
.hero h1 { font-size: 3rem; font-weight: 800; position:relative;
  background: linear-gradient(135deg, #6366f1, #a855f7, #ec4899);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; margin-bottom: 8px; }
.hero .subtitle { color: var(--text2); font-size: 1.1rem; position:relative; }
.hero .meta { color: var(--text2); font-size: 0.85rem; margin-top: 6px; position:relative; }
.badge-old { display:inline-block; background: var(--bg3); border:1px solid var(--border);
  color: var(--text2); padding: 3px 10px; border-radius: 999px; font-size: 0.75rem;
  margin-top: 10px; position: relative; }

.card { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; transition: border-color 0.2s, transform 0.2s; }
.card:hover { border-color: var(--accent); transform: translateY(-2px); }

.section { padding: 40px 0; }
.section-title { font-size: 1.4rem; font-weight: 700; margin-bottom: 6px; }
.section-desc { color: var(--text2); font-size: 0.9rem; margin-bottom: 20px; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }

.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
.tab-btn { padding: 8px 18px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--bg2); color: var(--text2); cursor: pointer; font-size: 0.9rem;
  transition: all 0.2s; font-weight: 500; }
.tab-btn:hover { border-color: var(--text2); color: var(--text); }
.tab-btn.active { color: #fff; border-color: transparent; }

.stats-bar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.stat { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 14px; display: flex; flex-direction: column; min-width: 90px; }
.stat-label { font-size: 0.7rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-size: 1.1rem; font-weight: 700; }

.iframe-wrap { border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  background: #fff; height: 560px; }
.iframe-wrap iframe { width: 100%; height: 100%; border: none; }

.winner-badge { display: inline-block; background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff; padding: 3px 12px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }
.fail-badge { display: inline-block; background: rgba(239,68,68,0.15); color: #ef4444;
  border: 1px solid rgba(239,68,68,0.4); padding: 3px 12px; border-radius: 999px;
  font-weight: 700; font-size: 0.8rem; }
.rank-num { font-size: 1.5rem; font-weight: 800; }

.cmp-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.cmp-table th, .cmp-table td { padding: 10px 12px; text-align: left;
  border-bottom: 1px solid var(--border); }
.cmp-table th { color: var(--text2); font-weight: 600; text-transform: uppercase;
  font-size: 0.7rem; letter-spacing: 0.5px; }
.cmp-table tr:hover td { background: var(--bg3); }
.score-bar { height: 5px; border-radius: 3px; background: var(--bg3); min-width: 60px; margin-top: 3px; }
.score-bar-fill { height: 100%; border-radius: 3px; }
.best { color: #22c55e; font-weight: 700; }
.fail { color: #ef4444; font-weight: 700; }

/* Dimension breakdown bars */
.dim-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.dim-row { display: grid; grid-template-columns: 130px 1fr 50px; gap: 10px; align-items: center; font-size: 0.78rem; }
.dim-label { color: var(--text2); }
.dim-track { height: 7px; border-radius: 4px; background: var(--bg3); overflow: hidden; }
.dim-fill { height: 100%; border-radius: 4px; transition: width 0.4s; }
.dim-val { font-weight: 700; text-align: right; font-size: 0.78rem; }

/* Methodology */
.method-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.method-item { background: var(--bg2); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; }
.method-item h4 { font-size: 0.95rem; margin-bottom: 6px; display:flex; gap:8px; align-items:center; }
.method-item .pts { margin-left:auto; color: var(--accent); font-size: 0.8rem; font-weight: 700;
  background: rgba(88,166,255,0.1); padding: 2px 8px; border-radius: 999px; }
.method-item p { color: var(--text2); font-size: 0.82rem; }
.method-item ul { color: var(--text2); font-size: 0.78rem; margin-top: 6px; padding-left: 18px; }

.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text2);
  font-size: 0.9rem; padding: 10px 0; }
.back-link:hover { color: var(--accent); }

footer { text-align: center; padding: 28px 0; border-top: 1px solid var(--border);
  color: var(--text2); font-size: 0.82rem; margin-top: 40px; }

.dim-panel { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; margin-bottom: 14px; }
.dim-panel h4 { font-size: 0.85rem; color: var(--text2); text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 4px; }

@media (max-width: 760px) {
  .hero h1 { font-size: 2rem; }
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .iframe-wrap { height: 420px; }
  .cmp-table { font-size: 0.78rem; }
}
"""


def html_doc(title, body):
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{CSS}</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
# Home page (index.html)
# --------------------------------------------------------------------------

def build_ranking_cards(agg):
    ranked = sorted(MODELS, key=lambda m: agg[m]['total'], reverse=True)
    cards = []
    for i, m in enumerate(ranked):
        info = MODEL_INFO[m]
        a = agg[m]
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}"
        strengths, weaknesses = derive_strengths_weaknesses(a)
        total = a['total']
        tcolor = score_color(total / 11.0)
        gen_rate = f"{a['tests_ok']}/11"
        gen_html = (f"<strong style='color:#22c55e'>{gen_rate}</strong>"
                    if a['tests_failed'] == 0
                    else f"<strong style='color:#ef4444'>{gen_rate}</strong> "
                         f"<span style='color:var(--text2);font-size:0.78rem'>({a['tests_failed']} failed)</span>")
        s_chips = "".join(chip(s, "good") for s in strengths) or "<span style='color:var(--text2);font-size:0.75rem'>none</span>"
        w_chips = "".join(chip(w, "bad")  for w in weaknesses) or "<span style='color:var(--text2);font-size:0.75rem'>none</span>"

        cards.append(
            f"""    <div class="card" style="display:flex;gap:16px;border-left:4px solid {info['color']};padding:18px">
      <span style="font-size:2.2rem">{medal}</span>
      <div style="flex:1">
        <div style="font-size:1.1rem;font-weight:700">{info['emoji']} {info['name']} <span style="color:var(--text2);font-weight:400;font-size:0.85rem">({info['provider']})</span></div>
        <div style="color:var(--text2);font-size:0.85rem;margin:4px 0 8px">
          Total <strong style="color:{tcolor}">{total}/1100</strong> ·
          Avg functional <strong>{a['avg_func']:.0f}</strong> ·
          Avg quality <strong>{a['avg_qual']:.0f}</strong> ·
          Avg speed <strong>{a['avg_speed']:.0f}</strong> ·
          Gen success {gen_html}
        </div>
        <div style="margin-bottom:4px"><strong style="color:#22c55e;font-size:0.78rem">STRENGTHS</strong> {s_chips}</div>
        <div><strong style="color:#ef4444;font-size:0.78rem">WEAKNESSES</strong> {w_chips}</div>
      </div>
    </div>"""
        )
    return "\n".join(cards)


def build_winners_table(scores):
    rows = []
    for test in TEST_ORDER:
        tinfo = TEST_INFO[test]
        ranked = sorted(
            MODELS,
            key=lambda m: (scores[test][m]['final'],
                           scores[test][m]['functional'],
                           scores[test][m]['quality']),
            reverse=True,
        )
        win_m = ranked[0]
        run_m = ranked[1] if len(ranked) > 1 else None
        we = scores[test][win_m]
        wi = MODEL_INFO[win_m]
        win_cell = (f"<strong style='color:{wi['color']}'>{wi['emoji']} {wi['name']}</strong>"
                    f"<div style='color:var(--text2);font-size:0.72rem'>{we['final']}/100</div>")
        if run_m:
            re_ = scores[test][run_m]
            ri = MODEL_INFO[run_m]
            run_cell = (f"<span style='color:{ri['color']}'>{ri['emoji']} {ri['name']}</span>"
                        f"<div style='color:var(--text2);font-size:0.72rem'>{re_['final']}/100</div>")
        else:
            run_cell = "—"

        # notes: failures in this test
        fails = [m for m in MODELS if scores[test][m]['status'] == "FAILED"]
        if fails:
            notes = "; ".join(
                f"{MODEL_INFO[m]['name']}: {scores[test][m]['gen_error']}" for m in fails
            )
            notes_html = (f"<span style='color:#ef4444;font-size:0.75rem'>"
                          f"⚠ {html.escape(notes)}</span>")
        else:
            spread = we['final'] - (scores[test][run_m]['final'] if run_m else 0)
            if we['functional'] >= 95:
                note = "All apps functional"
            elif spread <= 2:
                note = "Close race"
            else:
                note = f"+{spread} over runner-up"
            notes_html = f"<span style='color:var(--text2);font-size:0.75rem'>{note}</span>"

        rows.append(
            f"""      <tr>
        <td><strong>{tinfo['emoji']} {tinfo['name']}</strong></td>
        <td>{win_cell}</td>
        <td style="text-align:center"><strong style="color:{score_color(we['final'])}">{we['final']}</strong></td>
        <td>{run_cell}</td>
        <td style="text-align:center">{scores[test][run_m]['final'] if run_m else '—'}</td>
        <td>{notes_html}</td>
      </tr>"""
        )
    return (
        '<div style="overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--bg2)">\n'
        '      <table class="cmp-table">\n'
        '        <thead><tr>\n'
        '          <th>Test</th><th>Winner</th><th style="text-align:center">Score</th>'
        '<th>Runner-up</th><th style="text-align:center">Score</th><th>Notes</th>\n'
        '        </tr></thead>\n'
        '        <tbody>\n' + "\n".join(rows) + '\n'
        '        </tbody>\n'
        '      </table>\n'
        '    </div>'
    )


def build_reliability_section(agg):
    items = []
    # ordered by reliability then name
    order = sorted(MODELS, key=lambda m: (agg[m]['tests_failed'], MODEL_INFO[m]['name']))
    for m in order:
        info = MODEL_INFO[m]
        a = agg[m]
        ok = a['tests_ok']
        fl = a['tests_failed']
        if fl == 0:
            status = f'<span style="color:#22c55e;font-weight:700">✅ {ok}/11 succeeded</span>'
            detail = '<span style="color:var(--text2);font-size:0.8rem">No generation failures.</span>'
        else:
            status = f'<span style="color:#ef4444;font-weight:700">❌ {ok}/11 succeeded ({fl} failed)</span>'
            fails = "; ".join(
                f"{TEST_INFO[f['test']]['name']} ({f['error']})" for f in a['failures']
            )
            detail = f'<span style="color:#ef4444;font-size:0.8rem">⚠ {html.escape(fails)}</span>'
        items.append(
            f"""      <div class="card" style="border-left:4px solid {info['color']};padding:14px 18px">
        <div style="font-weight:700;margin-bottom:4px">{info['emoji']} {info['name']} <span style="color:var(--text2);font-weight:400;font-size:0.8rem">({info['provider']})</span></div>
        <div style="margin-bottom:4px">{status}</div>
        <div>{detail}</div>
      </div>"""
        )
    return "\n".join(items)


def build_model_profile_cards(agg):
    ranked = sorted(MODELS, key=lambda m: agg[m]['total'], reverse=True)
    cards = []
    for m in ranked:
        info = MODEL_INFO[m]
        a = agg[m]
        strengths, weaknesses = derive_strengths_weaknesses(a)
        s_chips = "".join(chip(s, "good") for s in strengths) or "<span style='color:var(--text2);font-size:0.75rem'>—</span>"
        w_chips = "".join(chip(w, "bad")  for w in weaknesses) or "<span style='color:var(--text2);font-size:0.75rem'>—</span>"
        gen_rate = f"{a['tests_ok']}/11"
        cards.append(
            f"""    <div class="card" style="border-top:4px solid {info['color']};text-align:center;padding:22px">
      <div style="font-size:2.6rem;margin-bottom:6px">{info['emoji']}</div>
      <div style="font-size:1.05rem;font-weight:700">{info['name']}</div>
      <div style="color:var(--text2);font-size:0.8rem;margin-bottom:12px">{info['provider']}</div>
      <div class="stats-bar" style="justify-content:center;margin-bottom:10px">
        <div class="stat"><span class="stat-label">Total</span><span class="stat-value" style="color:{score_color(a['total']/11.0)}">{a['total']}</span></div>
        <div class="stat"><span class="stat-label">Func</span><span class="stat-value">{a['avg_func']:.0f}</span></div>
        <div class="stat"><span class="stat-label">Qual</span><span class="stat-value">{a['avg_qual']:.0f}</span></div>
        <div class="stat"><span class="stat-label">Speed</span><span class="stat-value">{a['avg_speed']:.0f}</span></div>
      </div>
      <div style="font-size:0.78rem;color:var(--text2);margin-bottom:10px">Gen success <strong style="color:{ '#22c55e' if a['tests_failed']==0 else '#ef4444'}">{gen_rate}</strong></div>
      <div style="text-align:left"><strong style="color:#22c55e;font-size:0.72rem">STRENGTHS</strong><div>{s_chips}</div></div>
      <div style="text-align:left;margin-top:6px"><strong style="color:#ef4444;font-size:0.72rem">WEAKNESSES</strong><div>{w_chips}</div></div>
    </div>"""
        )
    return "\n".join(cards)


def build_cross_test_table(scores, agg):
    head_cells = "".join(
        f"<th style='text-align:center'>{MODEL_INFO[m]['emoji']}<br>"
        f"<span style='font-weight:400;text-transform:none;font-size:0.7rem'>{MODEL_INFO[m]['name']}</span></th>"
        for m in MODEL_ORDER
    )
    rows = []
    for test in TEST_ORDER:
        tinfo = TEST_INFO[test]
        ranked = sorted(MODELS, key=lambda m: scores[test][m]['final'], reverse=True)
        winner = ranked[0]
        cells = [f"<td><strong>{tinfo['emoji']} {tinfo['name']}</strong></td>"]
        for m in MODEL_ORDER:
            e = scores[test][m]
            if e['status'] == "FAILED":
                cells.append(
                    f"<td class='fail'><strong style='color:#ef4444'>FAIL</strong>"
                    f"<div style='color:var(--text2);font-size:0.68rem'>gen failed</div></td>"
                )
                continue
            v = e['final']
            is_best = (m == winner)
            crown = ' 🏆' if is_best else ''
            cls = ' class="best"' if is_best else ''
            cells.append(
                f"<td{cls}><strong style='color:{score_color(v)}'>{v}</strong>/100{crown}"
                f"<div class='score-bar'><div class='score-bar-fill' style='width:{v}%;background:{score_color(v)}'></div></div></td>"
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    # totals row
    tot_cells = [f"<td><strong>📊 TOTAL (out of 1100)</strong></td>"]
    ranked_total = sorted(MODELS, key=lambda m: agg[m]['total'], reverse=True)
    best_total = ranked_total[0]
    for m in MODEL_ORDER:
        t = agg[m]['total']
        cls = ' class="best"' if m == best_total else ''
        tot_cells.append(
            f"<td{cls}><strong style='color:{score_color(t/11.0)}'>{t}</strong>"
            f"<div style='color:var(--text2);font-size:0.7rem'>avg {t/11.0:.1f}</div></td>"
        )
    return (
        '<div style="overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--bg2)">\n'
        '      <table class="cmp-table">\n'
        '        <thead><tr>\n'
        f'          <th>Test</th>{head_cells}\n'
        '        </tr></thead>\n'
        '        <tbody>\n' + "\n".join(rows) + '\n'
        '        </tbody>\n'
        '        <tfoot><tr style="font-weight:700;border-top:2px solid var(--accent)">' + "".join(tot_cells) + '</tr></tfoot>\n'
        '      </table>\n'
        '    </div>'
    )


def build_home(scores, agg):
    ranked = sorted(MODELS, key=lambda m: agg[m]['total'], reverse=True)
    champ = ranked[0]
    chi = MODEL_INFO[champ]

    body = f"""
<div class="hero">
  <h1>🏆 AI Model Bake-Off — Fair Rerun</h1>
  <p class="subtitle">5 models · 11 challenges · 1 shot each · Real browser testing</p>
  <p class="meta">Combined score = Functional (45%) + Quality (40%) + Speed (15%) · Max 1100 · failures score 0</p>
  <span class="badge-old">One-shot generation · no retries · GLM thinking disabled · Playwright browser tests</span>
</div>

<div class="container">

  <div class="section">
    <h2 class="section-title">🏅 Final Rankings</h2>
    <p class="section-desc">Ranked by total combined score out of 1100. Champion: <strong style="color:{chi['color']}">{chi['emoji']} {chi['name']}</strong> with <strong>{agg[champ]['total']}/1100</strong>.</p>
    <div class="grid-2" style="gap:14px">
{build_ranking_cards(agg)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">🏁 Per-Test Winners</h2>
    <p class="section-desc">Who won each challenge, who came second, and what happened. 🏆 = winner by combined score. Red FAIL = generation failure (score 0).</p>
{build_winners_table(scores)}
  </div>

  <div class="section">
    <h2 class="section-title">📊 Cross-Test Matrix (Final Combined Score / 100)</h2>
    <p class="section-desc">Every model · every test. 🏆 marks each test's winner. FAIL = generation failure.</p>
{build_cross_test_table(scores, agg)}
  </div>

  <div class="section">
    <h2 class="section-title">🧪 The 11 Challenges</h2>
    <div class="grid-3">
{build_challenge_cards(scores)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">🔬 Scoring Methodology</h2>
    <p class="section-desc">Each model was given an identical prompt from <code>prompts.json</code>, one shot, no retries, with a 600s timeout. GLM models had thinking disabled so reasoning tokens couldn't eat the output budget. Generated apps were then scored on three independent axes.</p>
    <div class="method-grid">
      <div class="method-item">
        <h4>🌐 Functional — Real Browser Tests <span class="pts">45%</span></h4>
        <p>Every generated app was loaded in headless Chromium via Playwright and exercised: buttons clicked, forms submitted, games played, console errors counted. Score = % of checks passed.</p>
        <ul><li>Page loads without JS errors</li>
            <li>Core UI elements present and interactive</li>
            <li>Real user flows work end-to-end</li>
            <li>App-specific behavior (move pieces, add tasks, start timers…)</li></ul>
      </div>
      <div class="method-item">
        <h4>📐 Quality — Static Code Analysis <span class="pts">40%</span></h4>
        <p>Each HTML/CSS/JS bundle parsed and graded across 6 strict dimensions. Intentionally scaled so a typical model lands 40–75/100, not 90+.</p>
        <ul><li>Functionality &amp; correctness (30)</li>
            <li>Code quality &amp; architecture (20)</li>
            <li>UX &amp; interaction polish (20)</li>
            <li>Visual design (15), Accessibility (10), Performance (5)</li></ul>
      </div>
      <div class="method-item">
        <h4>⚡ Speed — Generation Time <span class="pts">15%</span></h4>
        <p>Wall-clock time to produce the app. Per test, the fastest successful generation gets 100; the slowest gets 0; others scale linearly between.</p>
        <ul><li>Faster code generation = higher speed score</li>
            <li>Normalized per-test so a hard challenge doesn't punish everyone</li>
            <li>Only successful generations are ranked by speed</li></ul>
      </div>
      <div class="method-item" style="border-color:rgba(239,68,68,0.4)">
        <h4>⚠ Generation Failures <span class="pts" style="color:#ef4444;background:rgba(239,68,68,0.1)">score 0</span></h4>
        <p>If a model failed to produce valid HTML within 600s (timeout, empty output, or no HTML after stripping), that test scores <strong>0 on every axis</strong> — functional, quality, speed. One shot, no retries.</p>
        <ul><li><strong>Sonnet:</strong> 3/11 failed — "no HTML after strip"</li>
            <li><strong>Opus:</strong> 3/11 failed — timeout after 600s</li>
            <li>GLM 5.1, GLM-5.2, Ornith: 0/11 failed</li></ul>
      </div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">🔌 Generation Reliability</h2>
    <p class="section-desc">Combined score only rewards models that actually deliver. Here's how reliably each model produced a working app on the first try.</p>
    <div class="grid-2" style="gap:14px">
{build_reliability_section(agg)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">👥 Model Profiles</h2>
    <p class="section-desc">Full per-model breakdown: combined total, average functional / quality / speed, generation reliability, strengths and weaknesses.</p>
    <div class="grid-3">
{build_model_profile_cards(agg)}
    </div>
  </div>

</div>

<footer>
  <p>AI Model Bake-Off · Fair Rerun · 5 models · 11 challenges · combined functional + quality + speed scoring</p>
</footer>
"""
    return html_doc("AI Model Bake-Off — Fair Rerun", body)


def build_challenge_cards(scores):
    cards = []
    for test in TEST_ORDER:
        tinfo = TEST_INFO[test]
        ranked = sorted(MODELS, key=lambda m: scores[test][m]['final'], reverse=True)
        win_m = ranked[0]
        we = scores[test][win_m]
        wi = MODEL_INFO[win_m]
        # per-test mini scoreline (skip FAILs)
        parts = []
        for m in ranked:
            e = scores[test][m]
            mi = MODEL_INFO[m]
            if e['status'] == "FAILED":
                parts.append(f"<span style='color:#ef4444;font-weight:600'>{mi['name'].split()[0]}: FAIL</span>")
            else:
                parts.append(f"<span style='color:{score_color(e['final'])};font-weight:600'>{mi['name'].split()[0]}: {e['final']}</span>")
        scoreline = " ".join(parts)
        cards.append(
            f"""    <a href="{test}/" class="card" style="text-decoration:none;display:block">
      <div style="font-size:1.8rem;margin-bottom:6px">{tinfo['emoji']}</div>
      <div style="font-size:1rem;font-weight:700;margin-bottom:6px">{tinfo['name']}</div>
      <div style="font-size:0.72rem;color:var(--text2);margin-bottom:8px;line-height:1.5">{scoreline}</div>
      <div><span class="winner-badge">🏆 {wi['emoji']} {wi['name']} ({we['final']}/100)</span></div>
    </a>"""
        )
    return "\n".join(cards)


# --------------------------------------------------------------------------
# Test pages ({test}/index.html)
# --------------------------------------------------------------------------

def build_dim_rows(entry, color):
    """6 quality-dimension bars for a successful entry."""
    dims = entry['dimensions'] or {}
    rows = []
    for key, label, mx in DIM_INFO:
        d = dims.get(key, {})
        total_pts = d.get("total", 0) or 0
        pct = 100 * total_pts / mx if mx else 0
        rows.append(
            f'      <div class="dim-row">\n'
            f'        <span class="dim-label">{label}</span>\n'
            f'        <div class="dim-track"><div class="dim-fill" style="width:{pct:.0f}%;background:{color}"></div></div>\n'
            f'        <span class="dim-val">{total_pts:.1f}/{mx}</span>\n'
            f'      </div>'
        )
    return "\n".join(rows)


def build_score_table(test, scores):
    ranked = sorted(MODELS, key=lambda m: scores[test][m]['final'], reverse=True)
    head = (
        '      <table class="cmp-table">\n'
        '        <thead><tr>\n'
        '          <th>Rank</th><th>Model</th><th style="text-align:center">Functional</th>'
        '<th style="text-align:center">Quality</th><th style="text-align:center">Speed</th>'
        '<th style="text-align:center">Final</th><th>Notes</th>\n'
        '        </tr></thead>\n'
        '        <tbody>\n'
    )
    rows = []
    for i, m in enumerate(ranked):
        e = scores[test][m]
        info = MODEL_INFO[m]
        medal = MEDALS[i] if i < len(MEDALS) else str(i + 1)
        iemoji, iname, iprov, icolor = info["emoji"], info["name"], info["provider"], info["color"]
        if e["status"] == "FAILED":
            err = html.escape(e["gen_error"] or "")
            rows.append(
                "      <tr>"
                f'<td><span class="rank-num" style="color:#6b7280;font-size:1.1rem">{medal}</span></td>'
                f'<td><span style="color:{icolor};font-weight:700">{iemoji} {iname}</span>'
                '<div style="color:var(--text2);font-size:0.7rem">' + iprov + "</div></td>"
                '<td style="text-align:center" class="fail">—</td>'
                '<td style="text-align:center" class="fail">—</td>'
                '<td style="text-align:center" class="fail">—</td>'
                '<td style="text-align:center"><strong style="color:#ef4444">0</strong></td>'
                '<td><span class="fail-badge">Generation Failed</span>'
                f'<div style="color:var(--text2);font-size:0.72rem;margin-top:2px">{err}</div></td>'
                "</tr>"
            )
            continue
        efunc, equal, espeed, efinal = e["functional"], e["quality"], e["speed"], e["final"]
        notes_bits = []
        epass, etot = e.get("passed"), e.get("total")
        if epass is not None and etot:
            notes_bits.append(f"{epass}/{etot} browser checks")
        ece = e.get("console_errors")
        if ece:
            notes_bits.append(f"{ece} console error{'s' if ece != 1 else ''}")
        etime = e.get("time")
        if etime is not None:
            notes_bits.append(f"{etime:.0f}s gen")
        esize = e.get("size_kb")
        if esize is not None:
            notes_bits.append(f"{esize:.1f} KB")
        notes = html.escape(" · ".join(notes_bits))
        rows.append(
            "      <tr>"
            f'<td><span class="rank-num" style="color:{icolor};font-size:1.1rem">{medal}</span></td>'
            f'<td><span style="color:{icolor};font-weight:700">{iemoji} {iname}</span>'
            '<div style="color:var(--text2);font-size:0.7rem">' + iprov + "</div></td>"
            f'<td style="text-align:center"><strong style="color:{score_color(efunc)}">{efunc}</strong></td>'
            f'<td style="text-align:center"><strong style="color:{score_color(equal)}">{equal:.0f}</strong></td>'
            f'<td style="text-align:center"><strong style="color:{score_color(espeed)}">{espeed:.0f}</strong></td>'
            f'<td style="text-align:center"><strong style="color:{score_color(efinal)};font-size:1.05rem">{efinal}</strong></td>'
            f'<td style="color:var(--text2);font-size:0.75rem">{notes}</td>'
            "</tr>"
        )
    return head + "\n".join(rows) + "\n        </tbody>\n      </table>\n"


def build_test_page(test, scores):
    tinfo = TEST_INFO[test]
    ranked = sorted(MODELS, key=lambda m: scores[test][m]['final'], reverse=True)
    win_m = ranked[0]
    we = scores[test][win_m]
    wi = MODEL_INFO[win_m]

    # Winner subtitle
    if we['status'] == "OK":
        win_sub = (f"🏆 Winner: {wi['emoji']} {wi['name']} — "
                   f"{we['final']}/100 "
                   f"(func {we['functional']} · qual {we['quality']:.0f} · speed {we['speed']:.0f})")
    else:
        win_sub = "No valid submissions"

    # Score breakdown table
    score_table = (
        '<div style="overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--bg2)">\n'
        + build_score_table(test, scores) +
        '    </div>'
    )

    # Per-model dimension panels (stacked, OK first then FAILED)
    ok_models = [m for m in ranked if scores[test][m]['status'] == "OK"]
    fl_models = [m for m in ranked if scores[test][m]['status'] == "FAILED"]
    panels = []
    for i, m in enumerate(ok_models):
        e = scores[test][m]
        info = MODEL_INFO[m]
        iemoji, iname, iprov, icolor = info["emoji"], info["name"], info["provider"], info["color"]
        is_winner = (m == win_m)
        rank_idx = ranked.index(m)
        winner_badge = '<span class="winner-badge">🏆 WINNER</span>' if is_winner else ""
        size_str = f"{e['size_kb']:.1f} KB" if e.get("size_kb") else "—"
        efunc, equal, espeed, efinal = e["functional"], e["quality"], e["speed"], e["final"]
        etime = e.get("time") or 0
        epass, etot, ece = e.get("passed"), e.get("total"), e.get("console_errors")
        dim_rows = build_dim_rows(e, icolor)
        panels.append(
            f'    <div class="dim-panel" style="border-left:4px solid {icolor}">\n'
            '      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">\n'
            '        <div>\n'
            f'          <span style="font-size:1.05rem;font-weight:700">{iemoji} {iname}</span>\n'
            f'          <span style="color:var(--text2);margin-left:6px;font-size:0.8rem">{iprov}</span>\n'
            '        </div>\n'
            '        <div style="display:flex;gap:8px;align-items:center">\n'
            f'          <span class="rank-num" style="color:{icolor}">#{rank_idx+1}</span>\n'
            f'          {winner_badge}\n'
            '        </div>\n'
            '      </div>\n'
            '      <div class="stats-bar">\n'
            f'        <div class="stat"><span class="stat-label">Functional</span><span class="stat-value" style="color:{score_color(efunc)}">{efunc}/100</span></div>\n'
            f'        <div class="stat"><span class="stat-label">Quality</span><span class="stat-value" style="color:{score_color(equal)}">{equal:.0f}/100</span></div>\n'
            f'        <div class="stat"><span class="stat-label">Speed</span><span class="stat-value" style="color:{score_color(espeed)}">{espeed:.0f}</span></div>\n'
            f'        <div class="stat"><span class="stat-label">Final</span><span class="stat-value" style="color:{score_color(efinal)}">{efinal}/100</span></div>\n'
            f'        <div class="stat"><span class="stat-label">File Size</span><span class="stat-value">{size_str}</span></div>\n'
            f'        <div class="stat"><span class="stat-label">Gen Time</span><span class="stat-value">{etime:.0f}s</span></div>\n'
            '      </div>\n'
            f'      <div style="font-size:0.78rem;color:var(--text2);margin-bottom:2px">Browser checks: <strong>{epass}/{etot}</strong> · Console errors: <strong>{ece}</strong></div>\n'
            '      <div class="dim-list">\n'
            f'{dim_rows}\n'
            '      </div>\n'
            '      <div style="margin-top:14px">\n'
            f'        <div class="iframe-wrap"><iframe src="{m}.html" loading="lazy" title="{iname} output"></iframe></div>\n'
            '      </div>\n'
            '    </div>'
        )
    # Failed panels
    for m in fl_models:
        e = scores[test][m]
        info = MODEL_INFO[m]
        iemoji, iname, iprov = info["emoji"], info["name"], info["provider"]
        err = html.escape(e.get("gen_error") or "unknown")
        panels.append(
            '    <div class="dim-panel" style="border-left:4px solid #ef4444;opacity:0.92">\n'
            '      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">\n'
            '        <div>\n'
            f'          <span style="font-size:1.05rem;font-weight:700">{iemoji} {iname}</span>\n'
            f'          <span style="color:var(--text2);margin-left:6px;font-size:0.8rem">{iprov}</span>\n'
            '        </div>\n'
            '        <span class="fail-badge">⚠ Generation Failed</span>\n'
            '      </div>\n'
            '      <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:12px 14px;margin-top:6px">\n'
            '        <div style="color:#ef4444;font-weight:700;font-size:0.9rem;margin-bottom:4px">No app produced — scored 0 on all axes</div>\n'
            f'        <div style="color:var(--text2);font-size:0.82rem"><strong>Error:</strong> {err}</div>\n'
            '        <div style="color:var(--text2);font-size:0.78rem;margin-top:4px">This model did not produce valid HTML within the 600s single-shot limit, so it receives no functional, quality, or speed credit for this test. No retry attempted.</div>\n'
            '      </div>\n'
            '    </div>'
        )

    # Side-by-side compare grid (only OK models render iframes)
    compare_items = []
    for m in ranked:
        e = scores[test][m]
        info = MODEL_INFO[m]
        iemoji, iname, icolor = info["emoji"], info["name"], info["color"]
        if e["status"] == "OK":
            efinal = e["final"]
            compare_items.append(
                f'      <div><div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;color:{icolor}">{iemoji} {iname} — {efinal}/100</div>'
                f'<div class="iframe-wrap" style="height:380px"><iframe src="{m}.html" loading="lazy" title="{iname}"></iframe></div></div>'
            )
        else:
            err = html.escape(e.get("gen_error") or "")
            compare_items.append(
                f'      <div><div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;color:#ef4444">{iemoji} {iname} — FAILED</div>'
                f'<div class="iframe-wrap" style="height:380px;display:flex;align-items:center;justify-content:center;background:var(--bg2);color:var(--text2);font-size:0.85rem;text-align:center;padding:20px">⚠ Generation failed<br><span style="font-size:0.78rem">{err}</span></div></div>'
            )
    compare_grid = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px">\n'
        + "\n".join(compare_items) + '\n    </div>'
    )

    n_ok = len(ok_models)
    n_fl = len(fl_models)
    failed_str = f" · {n_fl} failed" if n_fl else ""
    panels_html = "\n".join("\n" + p for p in panels)

    body = f"""
<div class="hero">
  <h1>{tinfo['emoji']} {tinfo['name']}</h1>
  <p class="subtitle">{win_sub}</p>
  <p class="meta">Combined score = Functional (45%) + Quality (40%) + Speed (15%) · {n_ok} succeeded{failed_str}</p>
  <span class="badge-old">One-shot generation · Playwright browser tested · 5 models</span>
</div>

<div class="container">
  <a href="../" class="back-link">← Back to all tests</a>

  <div class="section">
    <h2 class="section-title">📊 Score Breakdown</h2>
    <p class="section-desc">All 5 models ranked by final combined score. FAILED = generation failure (scores 0 across the board).</p>
{score_table}
  </div>

  <div class="section">
    <h2 class="section-title">🔍 Per-Model Detail &amp; Dimension Breakdown</h2>
    <p class="section-desc">For each successful entry: functional / quality / speed / final, the 6 quality dimensions, and the live rendered app.</p>
{panels_html}
  </div>

  <div class="section">
    <h2 class="section-title">⚖️ Side-by-Side Comparison</h2>
    <p class="section-desc">All 5 outputs rendered together (where generation succeeded).</p>
{compare_grid}
  </div>

</div>

<footer>
  <p>AI Model Bake-Off · {tinfo['name']} · Fair rerun · combined functional + quality + speed scoring</p>
</footer>
"""
    return html_doc(f"{tinfo['name']} — AI Model Bake-Off (Fair Rerun)", body)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    fair, browser, strict = load_all()

    scores = compute_scores(fair, browser, strict)
    agg = compute_aggregates(scores)

    # --- save final_scores.json (trimmed to required schema + raw detail) ---
    out = {}
    for test in TEST_ORDER:
        out[test] = {}
        for m in MODELS:
            e = scores[test][m]
            out[test][m] = {
                "final":      e['final'],
                "status":     e['status'],
                "functional": e['functional'],
                "quality":    e['quality'],
                "speed":      e['speed'],
                "gen_error":  e['gen_error'],
                "time":       e['time'],
            }
    with open(os.path.join(HERE, "final_scores.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("wrote final_scores.json")

    # --- sanity print ---
    print("\n=== FINAL TOTALS (out of 1100) ===")
    for m in sorted(MODELS, key=lambda x: agg[x]['total'], reverse=True):
        a = agg[m]
        print(f"  {MODEL_INFO[m]['name']:14s} {a['total']:5d}  "
              f"(func {a['avg_func']:5.1f} | qual {a['avg_qual']:5.1f} | "
              f"speed {a['avg_speed']:5.1f})  gen {a['tests_ok']}/11  wins {len(a['test_wins'])}")

    print("\n=== PER-TEST WINNERS ===")
    for test in TEST_ORDER:
        ranked = sorted(MODELS, key=lambda x: scores[test][x]['final'], reverse=True)
        w = ranked[0]
        print(f"  {test:11s} -> {MODEL_INFO[w]['name']:14s} {scores[test][w]['final']:3d}/100")

    # --- build index.html ---
    home_html = build_home(scores, agg)
    with open(os.path.join(HERE, "index.html"), "w") as f:
        f.write(home_html)
    print("\nwrote index.html")

    # --- build test pages ---
    for test in TEST_ORDER:
        page = build_test_page(test, scores)
        path = os.path.join(HERE, test, "index.html")
        with open(path, "w") as f:
            f.write(page)
        print(f"wrote {test}/index.html")

    print("\nDone.")


if __name__ == "__main__":
    main()
